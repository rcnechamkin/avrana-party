#!/usr/bin/env bash
# The one deterministic deployment entry point for the appliance. Owner-run, on the Pi, as root:
#
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --party <sha> --games <sha> [--dry-run]
#
# It never decides *what* to deploy: both target commits are explicit arguments (the reviewed,
# CI-green commits named in the PRs). It then, in order:
#   1. refuses to run twice at once, on a dirty checkout (unless --allow-dirty), on a Party commit
#      that is not on origin/main (unless --allow-branch), on a Party/Games pair that disagrees on
#      the Party <-> Games contract (tools/contract_check.py run on the two exact commits; unless
#      --skip-contract-check), or while a game session is live (unless --force-busy);
#   2. records the before-state (JSON) under /var/backups/avrana-party/deploy-<UTC>/;
#   3. stops only the services whose code changes, checks both repositories out at exactly the
#      named commits (detached, so forward, backward and rollback deployments are the same
#      operation and no local branch is ever moved or reset), builds a root-owned code release
#      of each changed repository under /opt (what the services run once they have their own
#      users, ADR 0016; unused until then), installs a fresh atomic web release when Party
#      changed, and starts those services again; a failure after a stop puts both
#      checkouts back where they were (same branch or commit, never --force/--hard) and restarts;
#   4. writes the deployment manifest (/var/lib/avrana-party/deployment.json, avrana.deployment/v0);
#   5. runs the post-deploy smoke checks (python3 -m avrana.ops.smoke) and records the result.
# The manifest and smoke tooling (avrana.ops) always runs from a code release under /opt, never
# from the checkout: the target commit's when it has the tooling, otherwise the release that is
# running. So this script, taken from the target commit, also deploys an appliance whose checkout
# predates the tooling, and can deploy back to such a commit.
# docs/runbooks/deploy.md explains the arguments, the paths and what to do when a step fails.
# Keys, certificates, nginx, NetworkManager and systemd unit files are never touched here.
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

# Everything runs inside main(), called on the last line: bash then parses the whole file before
# executing any of it, so checking out a different version of this very script mid-run (step 3)
# cannot change what this run does.
main() {

party_checkout=${AVRANA_PARTY_CHECKOUT:-/home/cody/avrana-party}
games_checkout=${AVRANA_GAMES_CHECKOUT:-/home/cody/avrana-party-games}
web_root=${AVRANA_WEB_ROOT:-/var/www/avrana-party/web}
# Root-owned code releases: <root>/releases/<sha> and a `current` link (ADR 0016, AVR-256). The
# checkouts stay the operator's and are only the source these are built from.
party_releases=${AVRANA_PARTY_RELEASES:-/opt/avrana-party}
games_releases=${AVRANA_GAMES_RELEASES:-/opt/avrana-party-games}
manifest=${AVRANA_DEPLOYMENT_MANIFEST:-/var/lib/avrana-party/deployment.json}
backup_root=${AVRANA_BACKUP_ROOT:-/var/backups/avrana-party}
party_core_url=${AVRANA_PARTY_CORE_URL:-http://127.0.0.1:8191}
party_host=${AVRANA_PARTY_HOST:-party.avrana.net}
checkout_user=${AVRANA_CHECKOUT_USER:-cody}
journal_file=$backup_root/deploy.journal
# The nginx site file is installed by this script (AVR-271) and validated by `nginx -t` first.
nginx_site=${AVRANA_NGINX_SITE:-/etc/nginx/sites-available/avrana-party}
nginx_enabled=${AVRANA_NGINX_ENABLED:-/etc/nginx/sites-enabled/avrana-party}
nginx_bin=${AVRANA_NGINX:-nginx}
lock_file=${AVRANA_DEPLOY_LOCK:-/run/lock/avrana-deploy.lock}
party_units=(avrana-party-core avranaparty-arcade)   # code in this repository
games_units=(avranaparty-games)                      # code in the games repository

party_sha='' games_sha='' dry_run=0 allow_dirty=0 allow_branch=0 force_busy=0 skip_smoke=0 skip_contract=0
status_only=0 skip_nginx=0
self=$(readlink -f "$0")
orig_args=("$@")

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "deploy: $*" >&2; exit 1; }
systemctl() { command "${AVRANA_SYSTEMCTL:-systemctl}" "$@"; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

while (($#)); do
    case $1 in
        --party) party_sha=${2:-}; shift 2 ;;
        --games) games_sha=${2:-}; shift 2 ;;
        --dry-run) dry_run=1; shift ;;
        --allow-dirty) allow_dirty=1; shift ;;
        --allow-branch) allow_branch=1; shift ;;
        --force-busy) force_busy=1; shift ;;
        --skip-smoke) skip_smoke=1; shift ;;
        --skip-contract-check) skip_contract=1; shift ;;
        --status) status_only=1; shift ;;
        --skip-nginx-site) skip_nginx=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument $1 (see --help)" ;;
    esac
done

# journal_phase_kind <phase>: terminal (the run ended), open (it did not), or none.
journal_phase_kind() {
    case $1 in
        smoke-passed|smoke-skipped|smoke-failed|rolled-back|rollback-failed) echo terminal ;;
        '') echo none ;;
        *) echo open ;;
    esac
}
journal_value() { sed -n "s/^$1=//p" "$journal_file" 2>/dev/null | head -n1; }
# deploy_running: true while another deployment holds the lock.
deploy_running() {
    command -v flock >/dev/null || return 1
    [[ -e $lock_file ]] || return 1
    ! ( flock -n 9 ) 9>"$lock_file" 2>/dev/null
}
# --status: where the last deployment stopped. Read-only; needs no root and no SHAs.
status_cmd() {
    local phase kind
    echo "deploy journal: $journal_file"
    if [[ ! -f $journal_file ]]; then
        echo 'no deployment has been run with this script on this machine (no journal)'
        return 0
    fi
    sed 's/^/  /' "$journal_file"
    phase=$(journal_value phase); kind=$(journal_phase_kind "$phase")
    if deploy_running; then
        echo "RUNNING: a deployment holds the lock now (pid $(journal_value pid)); follow it with: tail -f $(ls -t "$backup_root"/deploy-*.log 2>/dev/null | head -n1)"
    elif [[ $kind == open ]]; then
        echo "INTERRUPTED: the last deployment died at phase '$phase' and nothing restored it."
        echo "  Put the machine back to a known state with: sudo bash $self --recover   (docs/runbooks/deploy.md)"
        echo "  Phases committed/auto-rollback mean the new revision was applied; the others mean it is half-switched."
    else
        echo "last deployment ended at phase '$phase' (a finished run)."
    fi
}
if [[ $status_only -eq 1 ]]; then status_cmd; exit 0; fi

[[ $party_sha =~ ^[0-9a-f]{40}$ ]] || die '--party needs a full 40-character commit SHA'
[[ $games_sha =~ ^[0-9a-f]{40}$ ]] || die '--games needs a full 40-character commit SHA'
# AVRANA_DEPLOY_UNPRIVILEGED=1 and AVRANA_SYSTEMCTL exist for the automated test of this script
# against throwaway checkouts (tests/unit/test_deploy_script.py); production runs as root.
[[ $EUID -eq 0 || $dry_run -eq 1 || ${AVRANA_DEPLOY_UNPRIVILEGED:-0} == 1 ]] \
    || die 'run as root (sudo); services and the web root need it'
[[ -d $party_checkout/.git && -d $games_checkout/.git ]] || die "checkouts missing: $party_checkout, $games_checkout"

# Git runs as the checkout owner so object files never become root-owned.
g() {
    local repo=$1; shift
    if [[ $EUID -eq 0 && $checkout_user != root ]]; then sudo -u "$checkout_user" git -C "$repo" "$@"
    else git -C "$repo" "$@"; fi
}
# The deploy tooling runs from $tools, a code release chosen before anything is stopped (below).
# The checkout cannot be that place: before the deployment it holds the commit being replaced,
# which may predate avrana.ops altogether.
tools=''
py() { (cd "$tools" && PYTHONDONTWRITEBYTECODE=1 python3 "$@"); }
has_tooling() { [[ -f $1/avrana/ops/manifest.py && -f $1/avrana/ops/smoke.py ]]; }
# stage_release <checkout> <sha> <root>: exactly the tracked files of that commit, owned by whoever
# runs this script (root in production), never group- or world-writable. An existing release of the
# same commit is reused. Nothing runs from a staged release until link_release points at it.
stage_release() {
    local repo=$1 sha=$2 root=$3 tmp
    install -d -m 0755 "$root" "$root/releases"
    if [[ ! -d $root/releases/$sha ]]; then
        tmp=$(mktemp -d "$root/releases/.new.XXXXXX")
        g "$repo" archive --format=tar "$sha" | tar -x -C "$tmp" --no-same-owner
        chmod -R u+rwX,go+rX,go-w "$tmp"
        mv -T "$tmp" "$root/releases/$sha"
    fi
}
# link_release <sha> <root>: switch `current` atomically, so a rollback is only the link.
link_release() {
    local sha=$1 root=$2
    ln -sfn "$root/releases/$sha" "$root/current.new" && mv -Tf "$root/current.new" "$root/current"
    log "code release $root/current -> releases/$sha"
}
build_release() { stage_release "$1" "$2" "$3"; link_release "$2" "$3"; }

# ---- survive the controlling terminal -------------------------------------------------------------
# A real run re-executes itself in its own session (setsid) with all output in a log file, and this
# process only follows that log. A dropped SSH session (SIGHUP) then kills the follower, not the
# deployment; Ctrl-C detaches the same way; SIGTERM to this process is passed on, which rolls the
# deployment back. AVRANA_DEPLOY_DETACH=0 keeps it in the foreground (the traps below still apply).
if [[ $dry_run -eq 0 && -z ${AVRANA_DEPLOY_DETACHED:-} && ${AVRANA_DEPLOY_DETACH:-1} != 0 ]]; then
    if command -v setsid >/dev/null; then
        install -d -m 0750 "$backup_root"
        run_log=$backup_root/deploy-$(date -u +%Y%m%dT%H%M%SZ).log
        log "detaching: the deployment keeps running if this session drops. Log: $run_log"
        log "  follow it again: sudo tail -f $run_log      result so far: sudo bash $self --status"
        AVRANA_DEPLOY_DETACHED=1 setsid bash "$self" ${orig_args[@]+"${orig_args[@]}"} > "$run_log" 2>&1 < /dev/null &
        child=$!
        tail -n +1 -f --pid="$child" "$run_log" &
        follower=$!
        trap 'echo "[deploy] this session let go; the deployment (pid $child) continues. Log: $run_log" >&2; kill "$follower" 2>/dev/null; exit 130' INT HUP
        trap 'kill -TERM "$child" 2>/dev/null' TERM
        while :; do                      # a trapped signal interrupts `wait`: go back to waiting
            rc=0; wait "$child" || rc=$?
            kill -0 "$child" 2>/dev/null || break
        done
        wait "$follower" 2>/dev/null || true
        exit "$rc"
    fi
    log 'WARNING: setsid not found; running in the foreground (a dropped session is handled by the traps only)'
fi

# ---- state, journal, traps ---------------------------------------------------------------------
# One trap function owns every way out of this script, so the restore runs once and in order:
#   - a failure (set -e), a `die`, or a signal (HUP/INT/TERM: the SSH session dying, Ctrl-C, kill)
#     after the point where something may have changed (`armed`) and before the deployment is
#     recorded (`committed`) puts everything back, exactly once (`rollback_done`);
#   - after the commit point nothing is rolled back by a trap: the deployment is applied and only
#     its smoke verdict is open (the journal says so);
#   - the temporary Party/Games pair directory of the contract check is removed first, always.
# SIGKILL and power loss cannot be trapped: the journal (below) is what the next run reads.
stopped=() backup='' armed=0 committed=0 rollback_done=0 sig='' pair=''
start_order=(avranaparty-games avranaparty-arcade avrana-party-core)   # providers first, then the party
declare -gA J=()      # -g: main() is a function, and the EXIT trap runs after its locals are gone

# The journal: where this run is, written atomically (temp file, fsync, rename) at every phase, as
# KEY=VALUE lines that are only ever read as data. Terminal phases: smoke-passed, smoke-skipped,
# smoke-failed, rolled-back, rollback-failed. Any other phase left behind means the run died.
journal_write() {
    [[ $dry_run -eq 1 || -z $backup ]] && return 0
    local k tmp=$journal_file.tmp.$$
    J[updated]=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        for k in "${!J[@]}"; do printf '%s=%s\n' "$k" "${J[$k]//$'\n'/ }"; done | sort > "$tmp" \
            && { sync "$tmp" 2>/dev/null || true; } && mv -f "$tmp" "$journal_file"
    } || { log "WARNING: could not write the deploy journal $journal_file"; rm -f "$tmp"; }
}
journal_note() { local kv; for kv in "$@"; do J[${kv%%=*}]=${kv#*=}; done; journal_write; }
journal() { local phase=$1; shift; J[phase]=$phase; log "phase: $phase"; journal_note "$@"; }
# TEST-ONLY hook: with AVRANA_DEPLOY_TEST_HOOK_DIR set (never in production), a file pause-at-<phase>
# in that directory makes the run announce reached-<phase> and wait there until the file is removed,
# so the tests can send a signal at a deterministic point. `wait` returns at once on a trapped signal.
hook() {
    local dir=${AVRANA_DEPLOY_TEST_HOOK_DIR:-}
    [[ -n $dir && -e $dir/pause-at-$1 ]] || return 0
    : > "$dir/reached-$1"
    while [[ -e $dir/pause-at-$1 ]]; do sleep 0.1 & wait $!; done
}

# start_stopped <start|restart>: attempt EVERY unit this run stopped, providers first; non-zero when
# any failed. (A unit that was started with the new code and must go back needs a restart.)
start_stopped() {
    local verb=$1 unit s rc=0
    for unit in "${start_order[@]}"; do
        for s in ${stopped[@]+"${stopped[@]}"}; do
            if [[ $s == "$unit" ]]; then
                if systemctl "$verb" "$unit"; then log "$verb $unit"; else log "FAILED to $verb $unit"; rc=1; fi
            fi
        done
    done
    return $rc
}

# report_units: which of the units are active now, printed and recorded; sets $down.
down=()
report_units() {
    local unit up=()
    down=()
    for unit in "${start_order[@]}"; do
        if systemctl is-active --quiet "$unit"; then up+=("$unit"); else down+=("$unit"); fi
    done
    log "units active at exit: ${up[*]:-none}"
    [[ ${#down[@]} -eq 0 ]] || log "units NOT active at exit: ${down[*]}"
    journal_note "active=${up[*]:-}" "inactive=${down[*]:-}"
}

# ---- the nginx site file: part of the deployment unit ---------------------------------------------
# The site file of the deployed Party commit is read from Git (not from a checkout), compared with
# the live one, and installed before anything is stopped: written atomically beside the live file,
# `nginx -t`, reload. Any failure restores the previous file (and tests and reloads that), and
# fails the deployment, so the site file and the web build always go back together.
site_tmp='' site_state='' nginx_status=not_managed nginx_sha='' nginx_replaced=0
plan_site() {
    local live_lines new_lines added removed
    if [[ $skip_nginx -eq 1 ]]; then
        nginx_status=skipped
        log 'nginx site: not managed in this run (--skip-nginx-site); the manifest says so'
        return 0
    fi
    site_tmp=$(mktemp)
    if ! g "$party_checkout" show "$party_sha:avrana-party.nginx" > "$site_tmp" 2>/dev/null || [[ ! -s $site_tmp ]]; then
        rm -f "$site_tmp"; site_tmp=''
        log "nginx site: $party_sha has no avrana-party.nginx; the live site file is left alone"
        return 0
    fi
    new_lines=$(( $(wc -l < "$site_tmp") ))
    if [[ ! -e $nginx_site ]]; then
        site_state=absent
        log "nginx site: $nginx_site is absent; the deployed file ($new_lines lines) would be created"
    elif cmp -s "$nginx_site" "$site_tmp"; then
        site_state=match
        log "nginx site: the live file already equals avrana-party.nginx of $party_sha"
    else
        site_state=differs
        live_lines=$(( $(wc -l < "$nginx_site") ))
        added=$(diff "$nginx_site" "$site_tmp" | grep -c '^>' || true)
        removed=$(diff "$nginx_site" "$site_tmp" | grep -c '^<' || true)
        log "nginx site: DIFFERS from avrana-party.nginx of $party_sha (live $live_lines lines, deployed $new_lines; +$added -$removed)"
        log "            it is installed, checked with nginx -t and reloaded before any service stops"
    fi
}
site_hash() { [[ -f $1 ]] && sha256sum "$1" | cut -d' ' -f1 || true; }
install_site() {
    local out stage
    [[ $EUID -eq 0 || ${AVRANA_DEPLOY_UNPRIVILEGED:-0} == 1 ]] || die 'the nginx site file needs root; nothing was installed'
    command -v "$nginx_bin" >/dev/null || die "$nginx_bin not found: the site file cannot be validated, so it is not installed (install nginx, or --skip-nginx-site)"
    [[ -d $(dirname "$nginx_site") ]] || die "$(dirname "$nginx_site") does not exist: no nginx site directory (--skip-nginx-site to leave the site file alone)"
    if [[ -e $nginx_site ]]; then cp -p "$nginx_site" "$backup/nginx-site-before"; else : > "$backup/nginx-site-before.absent"; fi
    stage=$nginx_site.new.$$
    install -m 0644 "$site_tmp" "$stage"
    { sync "$stage" 2>/dev/null || true; }
    mv -f "$stage" "$nginx_site"
    nginx_replaced=1; journal_note nginx_replaced=1
    if [[ -e $nginx_enabled && $(readlink -f "$nginx_enabled") != "$(readlink -f "$nginx_site")" ]]; then
        log "WARNING: $nginx_enabled does not point at $nginx_site; nginx may not serve the file just installed"
    fi
    if ! out=$("$nginx_bin" -t 2>&1); then
        log "nginx -t REJECTED the new site file (avrana-party.nginx of $party_sha); the previous file is put back:"
        printf '%s\n' "$out" | sed 's/^/    /'
        printf '%s\n' "$out" | grep -E 'No such file|cannot load|not found' | head -n 3 | sed 's/^/MISSING PREREQUISITE: /' || true
        log 'A file the site refers to is probably missing on this appliance (for example the games.avrana.net'
        log 'certificate, AVR-319): install it first, see docs/runbooks/game-origin.md; or deploy with --skip-nginx-site.'
        false
    fi
    systemctl reload nginx || { log 'nginx reload FAILED after a good nginx -t'; false; }
    log "nginx site installed and reloaded: $nginx_site"
}
restore_site() {
    local stage
    [[ $nginx_replaced -eq 1 ]] || return 0
    if [[ -f $backup/nginx-site-before ]]; then
        stage=$nginx_site.new.$$
        { cp -p "$backup/nginx-site-before" "$stage" && mv -f "$stage" "$nginx_site"; }             || { log 'ROLLBACK INCOMPLETE: the previous nginx site file was not restored'; rollback_ok=0; return 0; }
    else
        rm -f "$nginx_site"                    # there was none before this run
    fi
    if "$nginx_bin" -t >/dev/null 2>&1 && systemctl reload nginx; then log 'previous nginx site file restored and reloaded'
    else log 'ROLLBACK INCOMPLETE: nginx did not accept (or reload) the restored site file'; rollback_ok=0; fi
}

# rollback_body <rc>: put back what this run changed. Never --force or reset --hard: local changes
# (only possible with --allow-dirty) survive, and no branch was moved by this script, so returning
# to the earlier ref restores the exact state. Sets $rollback_ok.
rollback_ok=1
rollback_body() {
    local rc=$1 root before p
    rollback_done=1
    log "FAILED (exit $rc${sig:+, interrupted by SIG$sig}); rolling back"
    journal rollback-started "exit=$rc" "signal=${sig:-}"
    g "$party_checkout" checkout --quiet "$before_party_ref" || { log "ROLLBACK INCOMPLETE: party checkout not restored"; rollback_ok=0; }
    g "$games_checkout" checkout --quiet "$before_games_ref" || { log "ROLLBACK INCOMPLETE: games checkout not restored"; rollback_ok=0; }
    if [[ -f $backup/web-release-before ]] && [[ -d $(cat "$backup/web-release-before") ]]; then
        { ln -sfn "$(cat "$backup/web-release-before")" "$web_root/current.new" && mv -Tf "$web_root/current.new" "$web_root/current"; } \
            || { log "ROLLBACK INCOMPLETE: web release not restored"; rollback_ok=0; }
    fi
    for p in "party:$party_releases" "games:$games_releases"; do
        root=${p#*:}; before=$backup/${p%%:*}-release-before
        if [[ ! -f $before ]]; then
            rm -f "$root/current"          # there was no release before this run: leave none behind
        elif [[ -d $(cat "$before") ]]; then
            { ln -sfn "$(cat "$before")" "$root/current.new" && mv -Tf "$root/current.new" "$root/current"; } \
                || { log "ROLLBACK INCOMPLETE: $root/current not restored"; rollback_ok=0; }
        fi
    done
    restore_site
    start_stopped restart || rollback_ok=0
    log "after rollback: party $(g "$party_checkout" rev-parse HEAD), games $(g "$games_checkout" rev-parse HEAD)"
    log "expected:       party $before_party, games $before_games. No manifest was written."
}

on_signal() { sig=$1; log "received SIG$1"; exit "$2"; }
on_exit() {
    local rc=$? u needs_human=0
    set +e
    trap '' HUP INT TERM        # a second signal must not interrupt the restore
    trap - EXIT
    [[ -z $pair ]] || rm -rf "$pair"
    [[ -z $site_tmp ]] || rm -f "$site_tmp"
    if [[ $armed -eq 1 && $committed -eq 0 && $rollback_done -eq 0 ]]; then rollback_body "$rc"; fi
    if [[ $armed -eq 1 ]]; then
        report_units
        for u in ${stopped[@]+"${stopped[@]}"}; do
            [[ " ${down[*]:-} " == *" $u "* ]] && needs_human=1
        done
        if [[ $rollback_done -eq 1 ]]; then
            if [[ $rollback_ok -eq 1 && $needs_human -eq 0 ]]; then
                journal rolled-back; rc=1
            else
                journal rollback-failed
                log 'ROLLBACK DID NOT COMPLETE: this needs a person (docs/runbooks/deploy.md, "When it fails")'
                rc=4
            fi
        fi
    fi
    exit "$rc"
}
trap 'on_signal HUP 129' HUP
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap on_exit EXIT

# ---- 1. refuse unsafe states -----------------------------------------------------------------
if command -v flock >/dev/null; then
    # The braces keep 2>/dev/null from becoming this shell's stderr for the rest of the run.
    { exec 9>"$lock_file"; } 2>/dev/null || exec 9>/tmp/avrana-deploy.lock
    flock -n 9 || die 'another deployment is running'
fi

for repo in "$party_checkout" "$games_checkout"; do
    if [[ -n $(g "$repo" status --porcelain --untracked-files=no) ]]; then
        [[ $allow_dirty -eq 1 ]] && log "WARNING: $repo has uncommitted changes (--allow-dirty)" \
            || die "$repo has uncommitted changes; deploy only clean, reviewed commits (or --allow-dirty)"
    fi
done
before_party=$(g "$party_checkout" rev-parse HEAD)
before_games=$(g "$games_checkout" rev-parse HEAD)
# What to return to on rollback: the branch that was checked out, or the commit when detached.
before_party_ref=$(g "$party_checkout" symbolic-ref --quiet --short HEAD || echo "$before_party")
before_games_ref=$(g "$games_checkout" symbolic-ref --quiet --short HEAD || echo "$before_games")
log "before: party $before_party, games $before_games"

g "$party_checkout" fetch --quiet origin || die 'git fetch origin failed in the Party checkout'
g "$party_checkout" cat-file -e "$party_sha^{commit}" 2>/dev/null || die "Party commit $party_sha is not fetchable"
if ! g "$party_checkout" merge-base --is-ancestor "$party_sha" origin/main; then
    [[ $allow_branch -eq 1 ]] && log "WARNING: $party_sha is not on origin/main (--allow-branch)" \
        || die "$party_sha is not on origin/main; merge first (or --allow-branch for a supervised test)"
fi
g "$games_checkout" fetch --quiet --all 2>/dev/null || true   # the Games clone may come from a bundle
g "$games_checkout" cat-file -e "$games_sha^{commit}" 2>/dev/null \
    || die "Games commit $games_sha is not in $games_checkout; stage it first (docs/runbooks/games-fork-deploy.md)"

party_changed=0; games_changed=0
[[ $before_party == "$party_sha" ]] || party_changed=1
[[ $before_games == "$games_sha" ]] || games_changed=1
if [[ $party_changed -eq 0 && $games_changed -eq 0 ]]; then
    log 'both checkouts are already at the requested commits'
fi

# The two exact commits must agree on the Party <-> Games contract (AVR-336). The checker and the
# declarations are read from the commits themselves, not the checkouts, so this holds for a
# forward, a backward and a rollback deployment alike. A commit that predates either is warned
# about, not refused: those pairs were deployed before the check existed.
pair='' contract_check=skipped       # recorded in the manifest: compatible | not_checkable | skipped
if [[ $skip_contract -eq 1 ]]; then
    log 'WARNING: Party <-> Games contract check skipped (--skip-contract-check); the manifest says so'
else
    pair=$(mktemp -d)                   # removed by on_exit on every way out, a failed archive included
    mkdir "$pair/party" "$pair/games"
    g "$party_checkout" archive --format=tar "$party_sha" | tar -x -C "$pair/party" --no-same-owner
    g "$games_checkout" archive --format=tar "$games_sha" | tar -x -C "$pair/games" --no-same-owner
    if [[ ! -f $pair/party/tools/contract_check.py || ! -f $pair/games/provider/avrana-contract.json ]]; then
        contract_check=not_checkable
        log 'WARNING: one of these commits predates the contract check; the pair was not checked'
    elif drift=$(cd "$pair/party" && PYTHONDONTWRITEBYTECODE=1 "${AVRANA_DEPLOY_PYTHON:-python3}" \
            tools/contract_check.py --party "$pair/party" --games "$pair/games" 2>&1); then
        contract_check=compatible
        log 'contract: compatible (tools/contract_check.py on the two exact commits)'
    else
        die "Party <-> Games contract: party $party_sha and games $games_sha disagree: $drift (re-pair them, or --skip-contract-check for a supervised test)"
    fi
    rm -rf "$pair"; pair=''
fi

busy=$(curl -s -m 5 -H "Host: $party_host" "$party_core_url/party/api/state" \
    | python3 -c 'import json,sys
try:
    s = json.load(sys.stdin).get("session")
    print("busy" if s and s.get("state") in ("setup", "launching", "active", "ending") else "idle")
except Exception:
    print("unknown")' 2>/dev/null || echo unknown)
if [[ $busy == busy ]]; then
    [[ $force_busy -eq 1 ]] && log 'WARNING: a game session is live (--force-busy)' \
        || die 'a game session is live; wait for the party to return home (or --force-busy)'
fi
log "party core: $busy"

restart=()
[[ $party_changed -eq 1 ]] && restart+=("${party_units[@]}") || true
[[ $games_changed -eq 1 ]] && restart+=("${games_units[@]}") || true
log "plan: party $before_party -> $party_sha (changed=$party_changed), games $before_games -> $games_sha (changed=$games_changed)"
log "plan: restart ${restart[*]:-nothing}; web release $([[ $party_changed -eq 1 ]] && echo yes || echo no)"
plan_site
if [[ $dry_run -eq 1 ]]; then
    # Up to here the script only read state and fetched remote refs: no file, checkout, service,
    # backup or manifest was touched.
    log 'dry run: nothing changed'
    exit 0
fi

# ---- tooling: from the target commit, else from the release that is running --------------------
# Staging the target release changes nothing that runs: `current` moves only in step 3.
stage_release "$party_checkout" "$party_sha" "$party_releases"
for candidate in "$party_releases/releases/$party_sha" \
        "$(readlink -f "$party_releases/current" 2>/dev/null || true)" "$party_releases/releases/$before_party"; do
    if [[ -n $candidate ]] && has_tooling "$candidate"; then tools=$candidate; break; fi
done
[[ -n $tools ]] || die "neither $party_sha nor the running release carries the deploy tooling (avrana.ops); nothing was stopped"
tool_sha=$(basename "$tools")
[[ $tool_sha == "$party_sha" ]] \
    || log "WARNING: $party_sha predates the deploy tooling; manifest and smoke run from release $tool_sha"

# ---- 2. before-state --------------------------------------------------------------------------
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=$backup_root/deploy-$stamp
install -d -m 0750 "$backup"
py -m avrana.ops.manifest write --out "$backup/before.json" --party "$party_checkout" \
    --games "$games_checkout" --web-root "$web_root" --allow-dirty --tool-sha "$tool_sha" >/dev/null
[[ -L $web_root/current ]] && readlink -f "$web_root/current" > "$backup/web-release-before" || true
[[ -L $party_releases/current ]] && readlink -f "$party_releases/current" > "$backup/party-release-before" || true
[[ -L $games_releases/current ]] && readlink -f "$games_releases/current" > "$backup/games-release-before" || true
log "before-state recorded in $backup"

# ---- 3. stop, update, start (with rollback) ---------------------------------------------------
armed=1
journal started "pid=$$" "backup=$backup" "party_target=$party_sha" "games_target=$games_sha"     "before_party=$before_party" "before_games=$before_games" "restart=${restart[*]:-}"
hook started
if [[ -n $site_tmp && $site_state != match ]]; then
    install_site; nginx_status=installed
    journal site-installed; hook site-installed
elif [[ -n $site_tmp ]]; then
    nginx_status=unchanged
fi
nginx_sha=$(site_hash "$nginx_site")

for unit in ${restart[@]+"${restart[@]}"}; do
    stopped+=("$unit")          # recorded first: a stop that fails half-way still gets restarted
    systemctl stop "$unit"; log "stopped $unit"
done
journal stopped-services; hook stopped-services
if [[ $party_changed -eq 1 ]]; then
    g "$party_checkout" checkout --quiet --detach "$party_sha"
    [[ $(g "$party_checkout" rev-parse HEAD) == "$party_sha" ]] || { log 'party checkout is not at the requested commit'; false; }
    log "party at $party_sha"
    build_release "$party_checkout" "$party_sha" "$party_releases"
    AVRANA_ALLOW_DIRTY=$allow_dirty bash "$party_checkout/ops/install-party-web.sh" "$party_checkout"
fi
if [[ $games_changed -eq 1 ]]; then
    g "$games_checkout" checkout --quiet --detach "$games_sha"
    [[ $(g "$games_checkout" rev-parse HEAD) == "$games_sha" ]] || { log 'games checkout is not at the requested commit'; false; }
    log "games at $games_sha"
    build_release "$games_checkout" "$games_sha" "$games_releases"
fi
# The first run after this script learned to build code releases: nothing changed, none exists yet.
[[ -e $party_releases/current ]] || build_release "$party_checkout" "$party_sha" "$party_releases"
[[ -e $games_releases/current ]] || build_release "$games_checkout" "$games_sha" "$games_releases"
journal switched; hook switched
# Start order matters: providers first, then the party that launches into them.
start_stopped start || { log 'a unit did not start'; false; }
for unit in ${restart[@]+"${restart[@]}"}; do
    sleep 1
    systemctl is-active --quiet "$unit" || { log "$unit did not stay active"; false; }
done
journal restarted; hook restarted

# ---- 4. manifest -----------------------------------------------------------------------------
py -m avrana.ops.manifest write --out "$manifest" --party "$party_checkout" --games "$games_checkout" \
    --web-root "$web_root" --tool-sha "$tool_sha" $([[ $allow_dirty -eq 1 ]] && echo --allow-dirty) \
    --restarted ${restart[@]+"${restart[@]}"}
# The commit point: the manifest names the new revision, so a trap no longer rolls anything back.
# Everything after this is a report, not a step that can undo the deployment.
committed=1
journal committed; hook committed
# Say how the pair was judged (additive manifest field; --skip-contract-check is on the record).
# A target whose tooling predates the subcommand cannot record it: warned about, not fatal.
py -m avrana.ops.manifest contract-check "$manifest" "$contract_check" \
    || log 'WARNING: the manifest tooling of this release cannot record the contract check result'
py -m avrana.ops.manifest deploy-info "$manifest" --nginx-status "$nginx_status"         ${nginx_sha:+--nginx-sha256 "$nginx_sha"}         $([[ $skip_smoke -eq 1 ]] && echo --option skip_smoke) $([[ $skip_contract -eq 1 ]] && echo --option skip_contract_check)         $([[ $force_busy -eq 1 ]] && echo --option force_busy) $([[ $allow_dirty -eq 1 ]] && echo --option allow_dirty)         $([[ $allow_branch -eq 1 ]] && echo --option allow_branch) $([[ $skip_nginx -eq 1 ]] && echo --option skip_nginx_site)     || log 'WARNING: the manifest tooling of this release cannot record the nginx site and the options'
cp "$manifest" "$backup/after.json" || log "WARNING: could not copy the manifest to $backup/after.json"
# The manifest is public (0644; /party/api/status serves it), but on the appliance its directory
# was created 0700 for the ACME state beside it, so no service user could reach the file. Grant
# search (not listing) on the directory, and only while every subdirectory is closed to others.
manifest_dir=$(dirname "$manifest")
if [[ -n $(find "$manifest_dir" -mindepth 1 -maxdepth 1 -type d -perm /077 -print -quit) ]]; then
    log "WARNING: a directory in $manifest_dir is open to group or other; $manifest_dir left as it is."
    log "         /party/api/status cannot name this deployment until its service user can read the manifest."
else
    chmod go+x "$manifest_dir"
fi
log "deployment manifest written: $manifest"

# ---- 5. smoke ---------------------------------------------------------------------------------
if [[ $skip_smoke -eq 1 ]]; then
    py -m avrana.ops.manifest smoke "$manifest" skipped
    journal smoke-skipped
    log 'smoke checks skipped (--skip-smoke); the manifest says so'
    exit 0
fi
sleep 2
if py -m avrana.ops.smoke | tee "$backup/smoke.txt"; then
    py -m avrana.ops.manifest smoke "$manifest" passed
    journal smoke-passed
    log 'deployment complete; smoke passed. Physical phone acceptance is still a human step.'
else
    py -m avrana.ops.manifest smoke "$manifest" failed
    journal smoke-failed
    log "deployment applied but smoke FAILED (see $backup/smoke.txt); decide: fix forward or roll back with"
    log "  sudo bash $party_checkout/ops/deploy.sh --party $before_party --games $before_games"
    exit 2
fi
}

main "$@"
