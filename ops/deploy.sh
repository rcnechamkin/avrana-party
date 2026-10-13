#!/usr/bin/env bash
# The one deterministic deployment entry point for the appliance. Owner-run, on the Pi, as root:
#
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --party <sha> --games <sha> [--dry-run]
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --status      # where the last run stopped; the last known good
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --rollback    # return to the last known good (no SHAs needed)
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --recover     # after a run that DIED before the commit point
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --recover --force   # also on a closed journal (moves a kept revision)
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --finish      # after a run that died after it, or a kept revision whose
#                                                                  # failing check you have fixed: smoke, record, close
#
# It never decides *what* to deploy: both target commits are explicit arguments (the reviewed,
# CI-green commits named in the PRs). It then, in order:
#   1. refuses to run twice at once, after a run that died and was never recovered, on a dirty checkout
#      (unless --allow-dirty), on a Party commit that is not on origin/main (unless --allow-branch), on a
#      Party/Games pair that disagrees on the Party <-> Games contract (tools/contract_check.py run on the two
#      exact commits; unless --skip-contract-check), or while a game session is live (unless --force-busy);
#   2. records the before-state (JSON) under /var/backups/avrana-party/deploy-<UTC>/ and opens the journal
#      (deploy.journal there: the phase this run has reached, rewritten atomically at each phase);
#   3. installs the nginx site file of the deployed Party commit (checked with nginx -t, then reloaded; the old
#      file is put back on any failure; --skip-nginx-site leaves it alone), stops only the services whose code
#      changes, checks both repositories out at exactly the named commits (detached, so forward, backward and
#      rollback deployments are the same operation and no local branch is ever moved or reset), builds a root-owned
#      code release of each changed repository under /opt, installs a fresh atomic web release when Party changed,
#      and starts those services again. Any failure, or a HUP/INT/TERM, before step 4 puts site file, web build,
#      code releases and both checkouts back (same branch or commit, never --force/--hard) and starts every unit it
#      stopped. The run itself continues in its own session if the SSH connection drops (log under the backup root);
#   4. writes the deployment manifest (/var/lib/avrana-party/deployment.json, avrana.deployment/v0): the commit point;
#   5. runs the post-deploy smoke checks (python3 -m avrana.ops.smoke). Passed: the deployment is recorded as the
#      last known good and old releases and backups are pruned to the newest --keep (default 5). Failed: exit 2, the
#      new revision is kept and the one command back is printed. With --auto-rollback (opt-in) a smoke taken BEFORE
#      anything was stopped is the baseline: only a check that passed then and fails now is rolled back to the last
#      known good (smoke is run again, both results reported); checks that already failed are reported as pre-existing.
# Exit codes: 0 deployed and verified; 1 refused, or failed before the commit point and everything was put back; 2 the
# new revision is applied and kept (smoke failed, or a step after the commit point failed); 3 smoke failed and
# --auto-rollback returned to the last known good with a passing smoke; 4 a rollback also failed or a unit is down: a
# person is needed. After the commit point the exit code is never 1.
# The manifest and smoke tooling (avrana.ops) always runs from a code release under /opt, never
# from the checkout: the target commit's when it has the tooling, otherwise the release that is
# running. So this script, taken from the target commit, also deploys an appliance whose checkout
# predates the tooling, and can deploy back to such a commit.
# docs/runbooks/deploy.md explains the arguments, the paths and what to do when a step fails.
# Keys, certificates, NetworkManager and systemd unit files are never touched here.
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
openssl_bin=${AVRANA_OPENSSL:-openssl}
lock_file=${AVRANA_DEPLOY_LOCK:-/run/lock/avrana-deploy.lock}
# The last deployment whose smoke PASSED (a failed or skipped-smoke deployment never replaces it). It sits
# beside the manifest, which the status endpoint's service user can read; --rollback goes back to it.
lkg_file=${AVRANA_LAST_KNOWN_GOOD:-$(dirname "$manifest")/last-known-good.json}
party_units=(avrana-party-core avranaparty-arcade)   # code in this repository
games_units=(avranaparty-games)                      # code in the games repository

party_sha='' games_sha='' dry_run=0 allow_dirty=0 allow_branch=0 force_busy=0 skip_smoke=0 skip_contract=0
status_only=0 skip_nginx=0 prune=1 keep=${AVRANA_DEPLOY_KEEP:-5} auto=0 recover=0 rollback_kind='' force=0 finish=0
require_cert_names=0 internal_nested=0 internal_detached=0 internal_kind=''
settle=${AVRANA_DEPLOY_SMOKE_SETTLE:-90}   # seconds smoke may keep failing after the restart before it counts (see run_smoke_settled)
self=$(readlink -f "$0")
orig_args=("$@")

usage() { sed -n '2,/^set -Eeuo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "deploy: $*$([[ ${armed:-0} -eq 0 ]] && echo ' (nothing changed)')" >&2; exit 1; }
systemctl() { command "${AVRANA_SYSTEMCTL:-systemctl}" "$@"; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

# Settings that exist only for tests/unit/test_deploy_script.py are honoured only with AVRANA_DEPLOY_TESTING=1 AND a
# scratch root (none of the production roots below in use); anywhere else their presence is a refusal, so a stray
# variable can never redirect a production run.
testing=0
if [[ ${AVRANA_DEPLOY_TESTING:-0} == 1 && $backup_root != /var/backups/avrana-party && $party_releases != /opt/avrana-party \
        && $games_releases != /opt/avrana-party-games && $web_root != /var/www/avrana-party/web \
        && $manifest != /var/lib/avrana-party/deployment.json ]]; then testing=1; fi
for v in AVRANA_DEPLOY_SMOKE AVRANA_NGINX AVRANA_SYSTEMCTL AVRANA_DEPLOY_TEST_HOOK_DIR AVRANA_DEPLOY_UNPRIVILEGED \
        AVRANA_OPENSSL AVRANA_DEPLOY_FAIL_STEP AVRANA_DEPLOY_UNIT_GRACE AVRANA_DEPLOY_SMOKE_PAUSE AVRANA_DEPLOY_CATALOG_OWNER_UID; do
    if [[ -n ${!v:-} && $testing -eq 0 ]]; then
        die "$v is a test-only setting; it is honoured only with AVRANA_DEPLOY_TESTING=1 on a scratch root (never on the appliance). Unset it"
    fi
done
# The production waits: one second before each restarted unit is checked (a unit that dies at once), two seconds
# before the first smoke. Only the test harness may shorten them (the gate above), so CI speed never changes production.
unit_grace=${AVRANA_DEPLOY_UNIT_GRACE:-1}
smoke_pause=${AVRANA_DEPLOY_SMOKE_PAUSE:-2}
# inject <step>: test-only fault injection into the steps after the commit point (fails when asked to).
inject() { [[ $testing -eq 1 && ${AVRANA_DEPLOY_FAIL_STEP:-} == "$1" ]] && return 1; return 0; }

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
        --auto-rollback) auto=1; shift ;;
        --no-auto-rollback) auto=0; shift ;;          # the default; accepted so older command lines keep working
        --require-cert-names) require_cert_names=1; shift ;;
        --force) force=1; shift ;;
        --finish) finish=1; shift ;;
        --smoke-settle) settle=${2:-}; shift 2 ;;
        --internal-nested) internal_nested=1; shift ;;      # set by this script on its own nested rollback; not for operators
        --internal-detached) internal_detached=1; shift ;;      # set by the launcher for the detached run: only "do not detach again"; harmless typed by hand
        --internal-rollback-kind) internal_kind=${2:-}; shift 2 ;;
        --no-prune) prune=0; shift ;;
        --keep) keep=${2:-}; shift 2 ;;
        --rollback) rollback_kind=manual; shift ;;
        --recover) rollback_kind=recover; recover=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument $1 (see --help)" ;;
    esac
done

# journal_phase_kind <phase>: terminal (the run ended), open (it did not), or none.
journal_phase_kind() {
    case $1 in
        smoke-passed|smoke-skipped|smoke-failed|post-commit-failed|rolled-back|auto-rolled-back|rollback-failed) echo terminal ;;
        '') echo none ;;
        *) echo open ;;
    esac
}
journal_value() { sed -n "s/^$1=//p" "$journal_file" 2>/dev/null | head -n1; }
lkg_value() {
    python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2]) or "")
except Exception:
    print("")' "$lkg_file" "$1" 2>/dev/null || true
}
# deploy_running: true while another deployment holds the lock.
deploy_running() {
    command -v flock >/dev/null || return 1
    [[ -e $lock_file ]] || return 1
    ! ( flock -n 9 ) 9>"$lock_file" 2>/dev/null
}
# --status: where the last deployment stopped. Read-only; needs no root and no SHAs.
status_cmd() {
    local phase kind
    if [[ -d $backup_root && ( ! -r $backup_root || ! -x $backup_root ) ]]; then
        echo "cannot read $backup_root as this user (it is root's): run this with sudo to see the journal and the last known good"
        return 1
    fi
    if [[ -s $lkg_file ]]; then
        echo "last known good ($lkg_file): party $(lkg_value party_sha), games $(lkg_value games_sha), smoke passed $(lkg_value smoke_at); site file sha256 $(lkg_value nginx_site_sha256)"
        echo "  go back to it with: sudo bash $self --rollback"
    else
        echo "last known good: none recorded ($lkg_file): no deployment has passed its smoke checks yet"
    fi
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
if [[ $status_only -eq 1 ]]; then status_cmd; exit $?; fi

# Internal arguments are for this script's own re-executions. The nested rollback must inherit the parent's held lock
# (fd 9); a person typing the flag has no such lock and is refused.
if [[ $internal_nested -eq 1 ]]; then
    if command -v flock >/dev/null && ! { flock -n 9; } 2>/dev/null; then die '--internal-nested is not for operators'; fi
    [[ $internal_kind == auto && $rollback_kind == manual ]] || die '--internal-nested needs --rollback --internal-rollback-kind auto'
    rollback_kind=auto
elif [[ -n $internal_kind ]]; then die '--internal-rollback-kind is not for operators'
fi
[[ $force -eq 0 || $recover -eq 1 ]] || die '--force goes with --recover only'

# --rollback / --recover need no SHAs: the pair is the last known good. A rollback is exactly a
# deployment of that pair (checkouts, code releases, web build and nginx site file together).
if [[ $finish -eq 1 ]]; then
    party_sha=$(journal_value party_target); games_sha=$(journal_value games_target)
elif [[ -n $rollback_kind ]]; then
    [[ -z $party_sha && -z $games_sha ]] || die '--rollback and --recover take the SHAs from the last-known-good record; do not pass --party/--games'
    if [[ ! -s $lkg_file && $dry_run -eq 0 && $internal_nested -eq 0 ]]; then
        # An appliance deployed before the record existed: the running deployment is the record when its manifest
        # says smoke passed and both checkouts are still at its commits (same rules as a deploy's first step).
        rel=$(readlink -f "$party_releases/current" 2>/dev/null || true)
        if [[ -f $rel/avrana/ops/manifest.py ]]; then
            site_now=''; [[ -f $nginx_site ]] && site_now=$(sha256sum "$nginx_site" | cut -d' ' -f1)
            ( cd "$rel" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.manifest last-known-good seed "$manifest" "$lkg_file" \
                --party "$party_checkout" --games "$games_checkout" ${site_now:+--nginx-sha256 "$site_now"} ) >/dev/null 2>&1 \
                && log "last-known-good seeded from the running deployment ($lkg_file)" || true
        fi
    fi
    party_sha=$(lkg_value party_sha); games_sha=$(lkg_value games_sha)
    if ! [[ $party_sha =~ ^[0-9a-f]{40}$ && $games_sha =~ ^[0-9a-f]{40}$ ]]; then
        [[ $recover -eq 1 ]] || die "no last-known-good record ($lkg_file): no deployment has passed its smoke checks yet; deploy explicit SHAs"
        party_sha=$(journal_value before_party); games_sha=$(journal_value before_games)
        [[ $party_sha =~ ^[0-9a-f]{40}$ && $games_sha =~ ^[0-9a-f]{40}$ ]]             || die "no last-known-good record ($lkg_file) and no usable journal ($journal_file): deploy explicit SHAs"
        log 'WARNING: no last-known-good record; recovering to the before-state of the deployment that died'
    fi
    log "$rollback_kind: target is party $party_sha, games $games_sha"
fi

[[ $keep =~ ^[0-9]+$ && $keep -ge 2 ]] || die '--keep needs a number of at least 2 (the running release and the one before it)'
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
staged_new=() backup_created=0       # what this run created before the point of no return; removed again if it refuses
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
        [[ $armed -eq 1 ]] || staged_new+=("$root/releases/$sha")
    fi
}
# link_release <sha> <root>: switch `current` atomically, so a rollback is only the link.
link_release() {
    local sha=$1 root=$2
    ln -sfn "$root/releases/$sha" "$root/current.new" && mv -Tf "$root/current.new" "$root/current"
    log "code release $root/current -> releases/$sha"
}
build_release() { stage_release "$1" "$2" "$3"; link_release "$2" "$3"; }

# settle_catalog: after the web release `current` points to has changed (a deployment, the nested rollback, a
# --recover, or the undo of a failed run), make the effective game catalog (AVR-337, EXPERIMENTAL; nginx serves
# it at /party/catalog.json in place of the release's own when the file exists) match THAT release, or take it
# away. The overlay is derived from the release catalog, so one built for another release is stale. It uses the
# code release that Party `current` points to AT THIS MOMENT (avrana.ops.catalog_overlay): on a deployment, the
# nested rollback and --recover that is the TARGET's (build_release moved it before the web install); in
# rollback_body it is the earlier one, already put back. The target of a rollback may predate the overlay (its own
# install-party-web.sh would not refresh it, hence this function); then there is no such code, the file is removed,
# and the first-party catalog is served with no tile for installed packages until `sudo ops/catalog-overlay refresh`
# or the next forward deploy. The same happens when the refresh fails. WARNING ONLY (owner decision 2026-10-10):
# this never fails the run, the rollback, the manifest or the smoke. Nothing to do on an appliance with no package
# and no overlay. On a deployment it makes the refresh in install-party-web.sh redundant (that hook stays for
# standalone runs of the script). It waits up to 30 s for a running install-game (lock order: the deploy lock, then
# the install lock; install-game never takes the deploy lock, so there is no cycle), and a refresh repeats itself if
# the release catalog moved while it ran, so an install that was in flight cannot publish an overlay of the old release.
settle_catalog() {
    local overlay=/var/lib/avrana-party/catalog/catalog.json records=/etc/avrana-party/packages.d tree
    if [[ $testing -eq 1 ]]; then       # the paths are fixed (this removes a file): only the test harness may move them
        overlay=${AVRANA_CATALOG_OVERLAY:-$overlay}; records=${AVRANA_PACKAGE_RECORDS:-$records}
    fi
    [[ -e $overlay || -L $overlay || -n $(ls -A "$records" 2>/dev/null) ]] || return 0
    tree=$(readlink -f "$party_releases/current" 2>/dev/null || true)
    if [[ -n $tree && -f $tree/avrana/ops/catalog_overlay.py && -f $web_root/current/catalog.json ]] \
            && (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.catalog_overlay refresh \
                --wait 30 --base "$web_root/current/catalog.json" --out-dir "$(dirname "$overlay")" --records-dir "$records") >/dev/null 2>&1; then
        log "catalog: the effective catalog matches web release $(basename "$(readlink -f "$web_root/current")")"
        return 0
    fi
    rm -f -- "$overlay" 2>/dev/null || true
    if [[ -e $overlay || -L $overlay ]]; then
        log "WARNING: catalog: the effective catalog could NOT be regenerated for web release $(basename "$(readlink -f "$web_root/current" 2>/dev/null || echo -)") AND $overlay could NOT be removed: phones may be served a STALE catalog. Run: sudo rm $overlay && sudo ops/catalog-overlay refresh"
    else
        log "WARNING: catalog: the effective catalog could not be regenerated for this web release; it was removed, so the first-party catalog is served and installed .avrgame packages have no tile. Run: sudo ops/catalog-overlay refresh"
    fi
    return 0
}

# ---- survive the controlling terminal -------------------------------------------------------------
# A real run re-executes itself in its own session (setsid) with all output in a log file, and this
# process only follows that log. A dropped SSH session (SIGHUP) then kills the follower, not the
# deployment; Ctrl-C detaches the same way; SIGTERM to this process is passed on, which rolls the
# deployment back. AVRANA_DEPLOY_DETACH=0 keeps it in the foreground (the traps below still apply).
if [[ $dry_run -eq 0 && $internal_detached -eq 0 && ${AVRANA_DEPLOY_DETACH:-1} != 0 ]]; then
    if command -v setsid >/dev/null; then
        install -d -m 0750 "$backup_root"
        run_log=$backup_root/deploy-$(date -u +%Y%m%dT%H%M%SZ)-$$.log      # the pid keeps two runs in one second apart
        log "detaching: the deployment keeps running if this session drops. Log: $run_log"
        log "  follow it again: sudo tail -f $run_log      result so far: sudo bash $self --status"
        setsid bash "$self" ${orig_args[@]+"${orig_args[@]}"} --internal-detached > "$run_log" 2>&1 < /dev/null &
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
# KEY=VALUE lines that are only ever read as data. Terminal phases: smoke-passed, smoke-skipped, auto-rolled-back,
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
    # The two tracked copies are byte-identical (docs/GENERATED.md; CI checks it on main). A commit where they
    # are not is a repository defect: install neither.
    other=$(mktemp)
    if g "$party_checkout" show "$party_sha:arcade/nginx-site" > "$other" 2>/dev/null && ! cmp -s "$site_tmp" "$other"; then
        rm -f "$other"
        die "avrana-party.nginx and arcade/nginx-site differ at $party_sha; they must be byte-identical (docs/GENERATED.md). Nothing was changed"
    fi
    rm -f "$other"
    check_cert_names
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
# Before anything changes: root, nginx and its directory exist, and the EXISTING configuration already passes nginx -t
# (a configuration that fails before we touch it is not ours to blame or to restore).
nginx_preflight() {
    local out first
    [[ $EUID -eq 0 || ${AVRANA_DEPLOY_UNPRIVILEGED:-0} == 1 ]] || die 'the nginx site file needs root; nothing was installed'
    command -v "$nginx_bin" >/dev/null || die "$nginx_bin not found: the site file cannot be validated, so it is not installed (install nginx, or --skip-nginx-site)"
    [[ -d $(dirname "$nginx_site") ]] || die "$(dirname "$nginx_site") does not exist: no nginx site directory (--skip-nginx-site to leave the site file alone)"
    if ! out=$("$nginx_bin" -t 2>&1); then
        first=$(printf '%s\n' "$out" | head -n 3 | tr '\n' ' ')
        if [[ $recover -eq 1 || -n $rollback_kind ]]; then
            # A recovery exists for exactly this state: a dead run may have left a site file nginx rejects. Do not refuse;
            # the site file of the pair being returned to is installed and validated below (and if THAT is rejected, the
            # restore fails and a person is needed).
            log "WARNING: nginx -t fails with the live site file ($first); the site file of the pair being returned to is installed next and validated"
            return 0
        fi
        record_attempt refused
        die "the existing nginx configuration is already invalid: nginx -t fails before any change ($first). Fix nginx first; nothing was installed or stopped (or --skip-nginx-site)"
    fi
}
# check_cert_names: for every server_name in a 443 ssl server block of the TARGET site file, does the certificate
# that block names cover that name? A mismatch is a WARNING (Party must stay deployable) unless --require-cert-names.
# Needs root to read the root-only certificate directory; an unreadable certificate is reported, not guessed.
# Only a listener on exactly port 443 counts (not 8443). A parsing failure (no python, an odd file) yields no names and
# so never blocks a deploy by default; only a positively reported mismatch can, and only with --require-cert-names.
cert_mismatch=()
check_cert_names() {
    local name cert out
    [[ -n $site_tmp ]] || return 0
    command -v "$openssl_bin" >/dev/null || { log "nginx site: no openssl here; certificate names not checked"; return 0; }
    while read -r name cert; do
        [[ -n $name ]] || continue
        out=$("$openssl_bin" x509 -in "$cert" -noout -checkhost "$name" 2>&1) || true
        if [[ $out == *"does match certificate"* ]]; then log "nginx site: $name is covered by $cert"
        elif [[ $out == *"NOT match"* ]]; then
            cert_mismatch+=("$name")
            log "WARNING: the certificate $cert does not cover $name, the name its server block answers (a phone gets a name-mismatch error there; see docs/runbooks/game-origin.md)"
        else log "nginx site: could not check $name against $cert (unreadable here? root is needed)"; fi
    done < <(python3 -c 'import re,sys
t = re.sub(r"#.*", "", open(sys.argv[1]).read())
for m in re.finditer(r"\bserver\s*\{", t):
    j, depth = m.end(), 1
    while j < len(t) and depth:
        depth += (t[j] == "{") - (t[j] == "}"); j += 1
    body = t[m.end():j - 1]
    cert = re.search(r"\bssl_certificate\s+([^;\s]+)\s*;", body)
    names = re.search(r"\bserver_name\s+([^;]+);", body)
    if cert and names and re.search(r"\blisten\s+(?:\S*:)?443(?=[\s;])[^;]*\bssl\b", body):
        for n in names.group(1).split():
            if n != "_" and "*" not in n and not n.startswith("~"):
                print(n, cert.group(1))' "$site_tmp" 2>/dev/null)
}
install_site() {
    local out stage
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
        log 'The lines above say what nginx rejected (typically a file the new site refers to that this appliance does not have).'
        log 'Install that first (the games.avrana.net origin: docs/runbooks/game-origin.md), or deploy with --skip-nginx-site.'
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

# ---- accumulation: keep the newest $keep of everything, never what a rollback needs ----------------
# prune_dir <run|list> <label> <dir> <name-regex> <sort: mtime|name> <protected name>...
# Only a plain directory whose name matches <name-regex> is ever a candidate. Each candidate's real path must be
# exactly <real dir>/<name> (a link, or a name that resolves elsewhere, is skipped), and the directory itself must
# be a plain directory somewhere below the root of the filesystem: anything else is left alone and said so.
pruned_total=0
prune_dir() {
    local mode=$1 label=$2 dir=$3 re=$4 order=$5; shift 5
    local real_dir rank=0 name real p keepit
    if [[ ! -d $dir || -L $dir ]]; then log "prune: $label: $dir is not a plain directory; nothing removed"; return 0; fi
    real_dir=$(realpath -e -- "$dir") || return 0
    if [[ $dir != /* || $real_dir != /*/* ]]; then log "prune: $label: refusing $real_dir (not an expected release or backup directory)"; return 0; fi
    while IFS= read -r -d '' name; do
        [[ $name =~ $re ]] || continue
        [[ -d $dir/$name && ! -L $dir/$name ]] || { log "prune: $label: $name is not a plain directory; left alone"; continue; }
        rank=$((rank + 1))
        [[ $rank -gt $keep ]] || continue
        keepit=0
        for p in "$@"; do [[ -n $p && $p == "$name" ]] && keepit=1; done
        if [[ $keepit -eq 1 ]]; then log "prune: $label: keeping $name (running, previous, last known good or being deployed)"; continue; fi
        real=$(realpath -e -- "$dir/$name") || continue
        if [[ $real != "$real_dir/$name" ]]; then log "prune: $label: $name resolves to $real; left alone"; continue; fi
        if [[ $mode == list ]]; then log "prune: $label: would remove $name"
        else rm -rf --one-file-system -- "$real_dir/$name" && log "prune: $label: removed $name"; fi
        pruned_total=$((pruned_total + 1))
    done < <(
        if [[ $order == mtime ]]; then find "$real_dir" -mindepth 1 -maxdepth 1 -printf '%T@ %f\0' | sort -z -rn | sed -z 's/^[0-9.]* //'
        else find "$real_dir" -mindepth 1 -maxdepth 1 -printf '%f\0' | sort -z -r; fi)
}
prune_all() {
    local mode=$1 lkg_p lkg_g cur_p cur_g cur_w
    lkg_p=$(lkg_value party_sha); lkg_g=$(lkg_value games_sha)
    cur_p=$(basename "$(readlink -f "$party_releases/current" 2>/dev/null || echo -)")
    cur_g=$(basename "$(readlink -f "$games_releases/current" 2>/dev/null || echo -)")
    cur_w=$(basename "$(readlink -f "$web_root/current" 2>/dev/null || echo -)")
    log "prune: keeping the newest $keep of each (--keep), plus what the running state and a rollback point at"
    prune_dir "$mode" 'party code releases' "$party_releases/releases" '^[0-9a-f]{40}$' mtime         "$party_sha" "$before_party" "$lkg_p" "$cur_p"
    prune_dir "$mode" 'games code releases' "$games_releases/releases" '^[0-9a-f]{40}$' mtime         "$games_sha" "$before_games" "$lkg_g" "$cur_g"
    prune_dir "$mode" 'web releases' "$web_root/releases" '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}(-[0-9]+)?$' name         "$cur_w" "$(basename "$(cat "$backup/web-release-before" 2>/dev/null || echo -)")"
    prune_dir "$mode" 'deploy backups' "$backup_root" '^deploy-[0-9]{8}T[0-9]{6}Z$' name         "$(basename "$backup")" "$(basename "$(journal_value backup)")"
    prune_junk "$mode"; prune_logs "$mode"
    log "prune: $pruned_total director$([[ $pruned_total -eq 1 ]] && echo y || echo ies) $([[ $mode == list ]] && echo 'would be removed' || echo removed)"
}

# record_attempt <outcome>: the last_attempt object of the manifest (and so of /party/api/status): what this run
# targeted and how it ended, because after a rollback the manifest names the pair that is running, not the one that failed.
record_attempt() {
    [[ -n $tools && -n $backup && -f $manifest ]] || return 0
    py -m avrana.ops.manifest last-attempt "$manifest" --party "$party_sha" --games "$games_sha" \
        --outcome "$1" --backup "$([[ ${armed:-0} -eq 1 ]] && basename "$backup" || true)" >/dev/null 2>&1 || true
}

# ---- smoke ------------------------------------------------------------------------------------------
# AVRANA_DEPLOY_SMOKE names a stand-in for the smoke command (tests only; refused unless AVRANA_DEPLOY_TESTING=1).
run_smoke_json() { if [[ -n ${AVRANA_DEPLOY_SMOKE:-} ]]; then "$AVRANA_DEPLOY_SMOKE" --json; else py -m avrana.ops.smoke --json; fi; }
# smoke_names <json file> <pass|fail>: the names of the checks with that result; non-zero when unreadable.
smoke_names() {
    python3 -c 'import json, sys
try:
    checks = json.load(open(sys.argv[1]))["checks"]
    assert checks
except Exception:
    sys.exit(3)
for c in checks:
    if c.get("status") == sys.argv[2]:
        print(c["name"])' "$1" "$2"
}
render_smoke() {
    python3 -c 'import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for c in d["checks"]:
        print("%-5s %-28s %s" % (c["status"].upper(), c["name"], c.get("detail", "")))
    k = d["counts"]
    print("smoke: %d passed, %d failed, %d skipped" % (k["pass"], k["fail"], k["skip"]))
except Exception:
    print("smoke produced no readable result")' "$1"
}
# run_smoke_settled: smoke the restarted services, trying again while they come up. The arcade (RetroArch and
# its encoder) and the games provider need tens of seconds on a Pi 4; each check has its own 5 s timeout
# (avrana/ops/smoke.py TIMEOUT_S), so a slow start must not count as a failure. $settle seconds (default 90,
# --smoke-settle / AVRANA_DEPLOY_SMOKE_SETTLE; 0 = one attempt) is how long a failing result may still change.
run_smoke_settled() {
    local deadline=$((SECONDS + settle)) rc
    while :; do
        rc=0; run_smoke_json > "$backup/smoke.json" 2> "$backup/smoke.err" || rc=$?
        [[ $rc -ne 0 ]] || break
        (( SECONDS < deadline )) || break
        log "smoke is not passing yet; trying again in 3 s (the services get ${settle}s to come up)"
        sleep 3
    done
    render_smoke "$backup/smoke.json" | tee "$backup/smoke.txt"
    return "$rc"
}
# finish_cmd (--finish): a run died AFTER the commit point (phase committed / post-commit-failed): the new revision is
# applied and its smoke verdict is open. Smoke it; passed: record it and the last known good, and close the journal.
finish_cmd() {
    local phase k v
    phase=$(journal_value phase)
    [[ $phase == committed || $phase == post-commit-failed || $phase == smoke-failed ]] \
        || die "--finish closes a run that died after the commit point or kept a revision whose smoke failed; the journal is at '${phase:-none}'"
    backup=$(journal_value backup)
    [[ -d $backup ]] || die "the backup directory named by the journal is gone ($backup)"
    while IFS='=' read -r k v; do [[ -z $k ]] || J[$k]=$v; done < "$journal_file"
    tools=$(readlink -f "$party_releases/current" 2>/dev/null || true)
    has_tooling "$tools" || die "the running code release carries no deploy tooling ($party_releases/current)"
    armed=1; committed=1
    log "finish: smoke for the deployment that was applied (party $party_sha, games $games_sha)"
    if run_smoke_settled; then
        py -m avrana.ops.manifest smoke "$manifest" passed \
            && py -m avrana.ops.manifest last-known-good record "$manifest" "$lkg_file" \
            || { journal post-commit-failed; log 'smoke passed but the manifest or the last-known-good record could not be written'; exit 2; }
        journal smoke-passed; record_attempt ok
        log 'finished: smoke passed; recorded as the manifest result and the last known good'
        exit 0
    fi
    py -m avrana.ops.manifest smoke "$manifest" failed || true
    journal smoke-failed; record_attempt smoke-failed-kept
    log "finished: smoke FAILED; the revision is kept. Go back with: sudo bash $self --rollback"
    exit 2
}

# prune_junk <run|list>: leftovers that are not releases or backups. Same rules as prune_dir: plain entries with the
# exact expected name directly inside the expected directory; build leftovers only when an hour old.
prune_junk() {
    local mode=$1 dir kind re label minutes
    for spec in "d:$party_releases/releases:^\.new\.[A-Za-z0-9]{6}$:staging leftover:60" \
                "d:$games_releases/releases:^\.new\.[A-Za-z0-9]{6}$:staging leftover:60" \
                "d:$web_root/releases:^\.build\.[A-Za-z0-9]{6}$:web build leftover:60" \
                "f:$backup_root:^deploy\.journal\.tmp\.[0-9]+$:journal temp file:60"; do
        IFS=: read -r kind dir re label minutes <<< "$spec"
        [[ -d $dir && ! -L $dir ]] || continue
        while IFS= read -r -d '' name; do
            [[ $name =~ $re ]] || continue
            [[ $(realpath -e -- "$dir/$name" 2>/dev/null) == "$(realpath -e -- "$dir")/$name" ]] || continue
            if [[ $mode == list ]]; then log "prune: $label: would remove $name"; else rm -rf --one-file-system -- "$dir/$name" && log "prune: $label: removed $name"; fi
        done < <(find "$dir" -mindepth 1 -maxdepth 1 -type "$kind" -mmin "+$minutes" -printf '%f\0')
    done
}
# prune_logs <run|list>: the run logs of the detached runs, the newest $keep stay.
prune_logs() {
    local mode=$1 rank=0 name
    [[ -d $backup_root && ! -L $backup_root ]] || return 0
    while IFS= read -r -d '' name; do
        [[ $name =~ ^deploy-[0-9]{8}T[0-9]{6}Z(-[0-9]+)?\.log$ ]] || continue
        [[ -f $backup_root/$name && ! -L $backup_root/$name ]] || continue
        rank=$((rank + 1)); [[ $rank -gt $keep ]] || continue
        if [[ $mode == list ]]; then log "prune: run logs: would remove $name"; else rm -f -- "$backup_root/$name" && log "prune: run logs: removed $name"; fi
    done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -printf '%f\0' | sort -z -r)
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
    settle_catalog      # the web release is back to the earlier one: the overlay built for the failed one goes with it
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
    if [[ $armed -eq 0 && $rc -ne 0 ]]; then
        # A refusal before the first change says "nothing changed": leave nothing behind that this run created.
        [[ $backup_created -eq 0 || -z $backup ]] || rm -rf --one-file-system -- "$backup"
        for u in ${staged_new[@]+"${staged_new[@]}"}; do rm -rf --one-file-system -- "$u"; done
    fi
    if [[ $armed -eq 1 && $committed -eq 0 && $rollback_done -eq 0 ]]; then rollback_body "$rc"; fi
    if [[ $armed -eq 1 ]]; then
        report_units
        for u in ${stopped[@]+"${stopped[@]}"}; do
            [[ " ${down[*]:-} " == *" $u "* ]] && needs_human=1
        done
        if [[ $rollback_done -eq 1 ]]; then
            if [[ $rollback_ok -eq 1 && $needs_human -eq 0 ]]; then
                journal rolled-back; rc=1; record_attempt interrupted-restored
            else
                journal rollback-failed; record_attempt rollback-failed
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
if command -v flock >/dev/null && [[ $internal_nested -eq 0 ]]; then   # a nested rollback inherits the parent's lock
    # The braces keep 2>/dev/null from becoming this shell's stderr for the rest of the run.
    { exec 9>"$lock_file"; } 2>/dev/null || exec 9>/tmp/avrana-deploy.lock
    flock -n 9 || die 'another deployment is running'
fi

# A run that died (SIGKILL, power) leaves a journal in a phase that is not an end. Do not deploy on top of a
# half-switched machine and hide the evidence: say where it stopped and how to put it right. --rollback, --recover
# and --finish are the ways to put it right, so they pass; so does the nested rollback of a running deployment.
jphase=''; jkind=none
if [[ -f $journal_file ]]; then jphase=$(journal_value phase); jkind=$(journal_phase_kind "$jphase"); fi
if [[ $recover -eq 1 && $force -eq 0 && $internal_nested -eq 0 ]]; then
    # --recover repairs a run that DIED. It must not move a revision that was kept on purpose.
    if [[ $jkind == open ]]; then :
    elif [[ -z $jphase || $jphase == smoke-passed || $jphase == auto-rolled-back || $jphase == rolled-back ]]; then
        log "nothing to recover: the last run ended at '${jphase:-none}', a finished run. The machine is as that run left it (--status)"
        exit 0
    else
        die "the last run ended at '$jphase', which is a closed run that kept its revision on purpose (smoke failed or skipped, or a rollback that failed): --recover would move it. Use --rollback to return to the last known good (or --recover --force)"
    fi
elif [[ $finish -eq 1 && $internal_nested -eq 0 ]]; then :
elif [[ $internal_nested -eq 0 && -z $rollback_kind && $jkind == open ]]; then
    die "the previous deployment died at phase '$jphase' and nothing restored it (journal $journal_file); see: sudo bash $self --status, then put the machine back with: sudo bash $self --recover (after the commit point: --finish or --rollback)"
fi
if [[ $finish -eq 1 ]]; then finish_cmd; fi

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
    [[ $allow_branch -eq 1 || -n $rollback_kind ]] && log "WARNING: $party_sha is not on origin/main ($([[ -n $rollback_kind ]] && echo "a $rollback_kind goes back to what ran" || echo --allow-branch))" \
        || die "$party_sha is not on origin/main; merge first (or --allow-branch for a supervised test)"
fi
g "$games_checkout" fetch --quiet --all 2>/dev/null || true   # the Games clone may come from a bundle
g "$games_checkout" cat-file -e "$games_sha^{commit}" 2>/dev/null \
    || die "Games commit $games_sha is not in $games_checkout; stage it first (docs/runbooks/games-fork-deploy.md)"

party_changed=0; games_changed=0
[[ $before_party == "$party_sha" ]] || party_changed=1
[[ $before_games == "$games_sha" ]] || games_changed=1
# --recover re-applies everything: after a dead deployment the checkouts, links, web build and units
# cannot be trusted to agree, so nothing is skipped as "already there".
[[ $recover -eq 0 ]] || { party_changed=1; games_changed=1; }
if [[ $party_changed -eq 0 && $games_changed -eq 0 ]]; then
    log 'both checkouts are already at the requested commits'
fi

# The two exact commits must agree on the Party <-> Games contract (AVR-336). The checker and the
# declarations are read from the commits themselves, not the checkouts, so this holds for a
# forward, a backward and a rollback deployment alike. A commit that predates either is warned
# about, not refused: those pairs were deployed before the check existed.
pair='' contract_check=skipped       # recorded in the manifest: compatible | not_checkable | skipped
if [[ -n $rollback_kind ]]; then
    log "contract: not applied to a $rollback_kind (it returns to a pair that already ran)"
elif [[ $skip_contract -eq 1 ]]; then
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
    if [[ $prune -eq 1 ]]; then backup=''; prune_all list; fi   # what would be pruned after a passed smoke; removes nothing
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
nginx_before=$(site_hash "$nginx_site")
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=$backup_root/deploy-$stamp
[[ -e $backup ]] || backup_created=1
install -d -m 0750 "$backup"
# A copy of this script for the nested rollback below: the file in the checkout changes at step 3.
if [[ $self != "$backup"/* ]]; then cp "$self" "$backup/deploy.sh" && self_copy=$backup/deploy.sh; else self_copy=$self; fi
py -m avrana.ops.manifest write --out "$backup/before.json" --party "$party_checkout" \
    --games "$games_checkout" --web-root "$web_root" --allow-dirty --tool-sha "$tool_sha" >/dev/null
[[ -L $web_root/current ]] && readlink -f "$web_root/current" > "$backup/web-release-before" || true
[[ -L $party_releases/current ]] && readlink -f "$party_releases/current" > "$backup/party-release-before" || true
[[ -L $games_releases/current ]] && readlink -f "$games_releases/current" > "$backup/games-release-before" || true
log "before-state recorded in $backup"
# An appliance deployed before this record existed: its running deployment, if it passed its smoke checks and
# is still what is checked out, is the last known good. (Nothing is written when it is not.)
if [[ ! -s $lkg_file ]]; then
    py -m avrana.ops.manifest last-known-good seed "$manifest" "$lkg_file" --party "$party_checkout" --games "$games_checkout" \
        ${nginx_before:+--nginx-sha256 "$nginx_before"} >/dev/null 2>&1 \
        && log "last-known-good seeded from the running deployment ($lkg_file)" || true
fi

# ---- 3. stop, update, start (with rollback) ---------------------------------------------------
# The baseline: with --auto-rollback, smoke what is running BEFORE anything is stopped. Only a check that passed here
# and fails after the deployment counts as caused by it; a check that already failed is not this deployment's fault.
baseline_ok=0
if [[ $auto -eq 1 ]]; then
    if [[ -n $rollback_kind || $skip_smoke -eq 1 ]]; then auto_note='a rollback or a run without smoke'
    elif [[ $skip_nginx -eq 1 ]]; then auto_note='--skip-nginx-site makes the status check degrade by design'
    elif [[ ! -f $manifest ]]; then auto_note='there is no running deployment to measure against (first deployment)'
    else
        auto_note=''
        log 'baseline: smoking the running services before anything is stopped'
        run_smoke_json > "$backup/smoke-baseline.json" 2>/dev/null || true
        if bp=$(smoke_names "$backup/smoke-baseline.json" pass) && bf=$(smoke_names "$backup/smoke-baseline.json" fail); then
            baseline_ok=1
            J[baseline_pass]=$(echo $bp); J[baseline_fail]=$(echo $bf)
            log "baseline: passing: ${J[baseline_pass]:-none}; already failing (not this deployment's fault): ${J[baseline_fail]:-none}"
        else auto_note='the baseline smoke could not run'; fi
    fi
    [[ $baseline_ok -eq 1 ]] || log "NOTE: --auto-rollback is off for this run: $auto_note"
fi
if [[ -n $site_tmp && $site_state != match ]]; then nginx_preflight; fi
# Whenever the flag is given, also when the live file already matches the deployed one.
if [[ ${#cert_mismatch[@]} -gt 0 && $require_cert_names -eq 1 ]]; then
    record_attempt refused
    die "the certificate does not cover: ${cert_mismatch[*]} (--require-cert-names); nothing was installed or stopped. See docs/runbooks/game-origin.md"
fi
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
    AVRANA_ALLOW_DIRTY=$allow_dirty AVRANA_WEB_KEEP=$keep AVRANA_WEB_PRUNE=0 bash "$party_checkout/ops/install-party-web.sh" "$party_checkout"
    settle_catalog      # the target's own install-party-web.sh may predate the overlay (a rollback); this knows how
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
    sleep "$unit_grace"
    systemctl is-active --quiet "$unit" || { log "$unit did not stay active"; false; }
done
journal restarted; hook restarted

# ---- 4. manifest -----------------------------------------------------------------------------
py -m avrana.ops.manifest write --out "$manifest" --party "$party_checkout" --games "$games_checkout" \
    --web-root "$web_root" --tool-sha "$tool_sha" $([[ $allow_dirty -eq 1 ]] && echo --allow-dirty) \
    --restarted ${restart[@]+"${restart[@]}"}
# The commit point: the manifest names the new revision, so a trap no longer rolls anything back.
# From here nothing may exit 1 ("everything was put back" is no longer true): errexit is off, each step reports its own
# failure, and the run ends in a terminal journal phase with exit 0, or 2 (applied and kept, something after the switch failed).
committed=1
set +e
journal committed; hook committed
post_failed=()
post_err() { post_failed+=("$1"); log "WARNING: after the commit point, $1 failed; the new revision is applied and kept"; }
# Say how the pair was judged (additive manifest field; --skip-contract-check is on the record).
# A target whose tooling predates the subcommand cannot record it: warned about, not fatal.
{ inject contract-record && py -m avrana.ops.manifest contract-check "$manifest" "$contract_check"; } \
    || log 'WARNING: the manifest tooling of this release cannot record the contract check result'
# How the run went, additively: the nginx site file (and its hash) and every flag that was set.
info=(--nginx-status "$nginx_status")
for n in ${cert_mismatch[@]+"${cert_mismatch[@]}"}; do info+=(--cert-name-mismatch "$n"); done
[[ $baseline_ok -eq 0 ]] || info+=(--option auto_rollback)
[[ -z $nginx_sha ]] || info+=(--nginx-sha256 "$nginx_sha")
[[ $skip_smoke -eq 0 ]] || info+=(--option skip_smoke)
[[ $skip_contract -eq 0 ]] || info+=(--option skip_contract_check)
[[ $force_busy -eq 0 ]] || info+=(--option force_busy)
[[ $allow_dirty -eq 0 ]] || info+=(--option allow_dirty)
[[ $allow_branch -eq 0 ]] || info+=(--option allow_branch)
[[ $skip_nginx -eq 0 ]] || info+=(--option skip_nginx_site)
[[ -z $rollback_kind ]] || info+=(--rollback-kind "$rollback_kind")
{ inject deploy-info && py -m avrana.ops.manifest deploy-info "$manifest" "${info[@]}"; } \
    || log 'WARNING: the manifest tooling of this release cannot record the nginx site and the options'
{ inject copy-manifest && cp "$manifest" "$backup/after.json"; } || post_err "copying the manifest to $backup/after.json"
# The manifest is public (0644; /party/api/status serves it), but on the appliance its directory
# was created 0700 for the ACME state beside it, so no service user could reach the file. Grant
# search (not listing) on the directory, and only while every subdirectory is closed to others. The one
# exception is `catalog`, the effective game catalog (AVR-337): public by design (nginx serves it, root writes it),
# 0755 so that nginx can read it through this directory; it is exempt only while it is a real directory owned by
# whoever runs this script (root: it refuses to run otherwise) that nobody else can write to. A link named
# catalog is never exempt. (AVRANA_DEPLOY_CATALOG_OWNER_UID: test-only, so the harness can play "another owner".)
manifest_dir=$(dirname "$manifest")
catalog_uid=$EUID
[[ $testing -eq 0 ]] || catalog_uid=${AVRANA_DEPLOY_CATALOG_OWNER_UID:-$EUID}
if [[ -n $(find "$manifest_dir" -mindepth 1 -maxdepth 1 \( -type d -perm /077 ! \( -name catalog -uid "$catalog_uid" ! -perm /022 \) -o -name catalog -type l \) -print -quit) ]]; then
    log "WARNING: a directory in $manifest_dir is open to group or other; $manifest_dir left as it is."
    log "         /party/api/status cannot name this deployment until its service user can read the manifest."
else
    { inject chmod-dir && chmod go+x "$manifest_dir"; } || post_err "making $manifest_dir searchable for the status service"
fi
log "deployment manifest written: $manifest"

# ---- 5. smoke, and what a failed smoke does -------------------------------------------------------
# close_run <exit 0|2>: the run's end after the commit point: a failed post-commit step makes it exit 2, never 1.
close_run() {
    if [[ ${#post_failed[@]} -gt 0 ]]; then
        journal post-commit-failed "post_commit_failed=${post_failed[*]}"; record_attempt post-commit-failed
        log "the new revision is applied and kept, but these steps after the switch failed: ${post_failed[*]}. See docs/runbooks/deploy.md; --finish re-runs smoke and records the result"
        exit 2
    fi
    exit "$1"
}
if [[ $skip_smoke -eq 1 ]]; then
    { inject smoke-record && py -m avrana.ops.manifest smoke "$manifest" skipped; } || post_err 'recording the skipped smoke in the manifest'
    journal smoke-skipped; record_attempt ok
    log 'smoke checks skipped (--skip-smoke); the manifest says so; the last known good is NOT updated; old releases are NOT pruned'
    close_run 0
fi
sleep "$smoke_pause"
if run_smoke_settled; then
    smoke_recorded=1
    { inject smoke-record && py -m avrana.ops.manifest smoke "$manifest" passed; } || { smoke_recorded=0; post_err 'recording the passed smoke in the manifest'; }
    if [[ $smoke_recorded -eq 1 ]]; then
        { inject lkg-record && py -m avrana.ops.manifest last-known-good record "$manifest" "$lkg_file"; } \
            || post_err "recording the last known good ($lkg_file)"
    fi
    journal smoke-passed; record_attempt ok
    log 'deployment complete; smoke passed; recorded as the last known good. Physical phone acceptance is still a human step.'
    if [[ ${#post_failed[@]} -gt 0 ]]; then log 'old releases are NOT pruned (a step after the switch failed)'
    elif [[ $prune -eq 1 ]]; then { inject prune && prune_all run; } || log 'WARNING: pruning old releases failed; the deployment itself is fine'
    else log 'old releases and backups are not pruned (--no-prune)'; fi
    close_run 0
fi
py -m avrana.ops.manifest smoke "$manifest" failed || post_err 'recording the failed smoke in the manifest'
cp "$manifest" "$backup/failed-manifest.json" || true
journal smoke-failed
log "deployment applied but smoke FAILED (see $backup/smoke.txt); old releases and backups are NOT pruned"
manual="sudo bash $party_checkout/ops/deploy.sh --party $before_party --games $before_games"
lkg_party=$(lkg_value party_sha); lkg_games=$(lkg_value games_sha)
have_lkg=0; [[ $lkg_party =~ ^[0-9a-f]{40}$ && $lkg_games =~ ^[0-9a-f]{40}$ ]] && have_lkg=1
back_cmd=$manual; [[ $have_lkg -eq 0 ]] || back_cmd="sudo bash $party_checkout/ops/deploy.sh --rollback"
# Regressions: checks that passed in the baseline and fail now (only with --auto-rollback and a usable baseline).
regressions='' preexisting='' unchecked=''
if [[ $baseline_ok -eq 1 ]]; then
    post_fail=$(smoke_names "$backup/smoke.json" fail) || post_fail=''
    for n in $post_fail; do
        if [[ " ${J[baseline_pass]} " == *" $n "* ]]; then regressions+="$n "
        elif [[ " ${J[baseline_fail]} " == *" $n "* ]]; then preexisting+="$n "
        else unchecked+="$n "; fi          # skipped (or absent) in the baseline: nothing to compare with
    done
fi
keep_revision() {
    record_attempt smoke-failed-kept
    [[ ${#post_failed[@]} -eq 0 ]] || log "also failed after the switch: ${post_failed[*]}"
    exit 2
}
if [[ -n $rollback_kind ]]; then
    log "this was a $rollback_kind: it is not rolled back again. The machine runs party $party_sha, games $games_sha with a failing smoke: a person is needed."
    keep_revision
elif [[ $baseline_ok -eq 1 && -z $regressions ]]; then
    if [[ -n $unchecked ]]; then
        log "NOT CHECKED BEFORE THE DEPLOY, FAILING AFTER: ${unchecked% }. The baseline skipped these checks, so there is nothing to compare with: no automatic rollback. The new revision is kept."
        [[ -z $preexisting ]] || log "PRE-EXISTING, NOT CAUSED BY THIS DEPLOY: ${preexisting% } also failed in the baseline."
    else
        log "PRE-EXISTING, NOT CAUSED BY THIS DEPLOY: the failing checks (${post_fail:-none}) also failed in the baseline taken before anything was stopped. The new revision is kept."
    fi
    log "To go back anyway:  $back_cmd"
    keep_revision
elif [[ $baseline_ok -eq 0 ]]; then
    log "The new revision is kept. Decide: fix forward, or go back with:  $back_cmd"
    [[ $have_lkg -eq 1 ]] || log 'No last known good exists yet (no deployment has passed its smoke checks), so --rollback has nothing to return to; the command above restores the before-state.'
    keep_revision
elif [[ $have_lkg -eq 0 ]]; then
    log "A check that passed before now fails (${regressions% }), but no last known good exists yet, so there is nothing to roll back to automatically."
    log "Decide: fix forward, or go back to the before-state with:  $manual"
    keep_revision
elif [[ $lkg_party == "$party_sha" && $lkg_games == "$games_sha" ]]; then
    log 'the last known good is the very pair that failed just now; not rolling back to it. Investigate (smoke.txt, /party/api/status).'
    log "Or go back to the before-state with:  $manual"
    keep_revision
fi
log "AUTOMATIC ROLLBACK (--auto-rollback): ${regressions% } passed before this deployment and fail now. Returning to the last known good: party $lkg_party, games $lkg_games"
journal auto-rollback "rollback_to_party=$lkg_party" "rollback_to_games=$lkg_games"
nested=(--rollback --internal-nested --internal-rollback-kind auto --internal-detached --force-busy)
[[ $allow_dirty -eq 0 ]] || nested+=(--allow-dirty)
[[ $skip_nginx -eq 0 ]] || nested+=(--skip-nginx-site)
rc=0
env -u AVRANA_DEPLOY_TEST_HOOK_DIR bash "$self_copy" "${nested[@]}" || rc=$?
case $rc in
    0)  journal auto-rolled-back; record_attempt rolled-back
        log "DEPLOYMENT FAILED, ROLLED BACK: smoke failed on party $party_sha / games $games_sha; the last known good (party $lkg_party, games $lkg_games) is running again and its smoke PASSED."
        exit 3 ;;
    2)  journal rollback-failed; record_attempt rollback-failed
        log 'ROLLBACK APPLIED BUT ITS SMOKE ALSO FAILED: the machine runs the last known good and it is not healthy. A person is needed.'
        exit 4 ;;
    *)  journal rollback-failed; record_attempt rollback-failed
        log "ROLLBACK FAILED (exit $rc): a person is needed. State: sudo bash $self_copy --status"
        exit 4 ;;
esac
}

main "$@"
