#!/usr/bin/env bash
# The one deterministic deployment entry point for the appliance. Owner-run, on the Pi, as root:
#
#   sudo bash /home/cody/avrana-party/ops/deploy.sh --party <sha> --games <sha> [--dry-run]
#
# It never decides *what* to deploy: both target commits are explicit arguments (the reviewed,
# CI-green commits named in the PRs). It then, in order:
#   1. refuses to run twice at once, on a dirty checkout (unless --allow-dirty), on a Party commit
#      that is not on origin/main (unless --allow-branch), or while a game session is live
#      (unless --force-busy);
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
party_units=(avrana-party-core avranaparty-arcade)   # code in this repository
games_units=(avranaparty-games)                      # code in the games repository

party_sha='' games_sha='' dry_run=0 allow_dirty=0 allow_branch=0 force_busy=0 skip_smoke=0

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
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument $1 (see --help)" ;;
    esac
done
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

# ---- 1. refuse unsafe states -----------------------------------------------------------------
if command -v flock >/dev/null; then
    # The braces keep 2>/dev/null from becoming this shell's stderr for the rest of the run.
    { exec 9>/run/lock/avrana-deploy.lock; } 2>/dev/null || exec 9>/tmp/avrana-deploy.lock
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
stopped=()
rollback() {
    local rc=$?
    trap - ERR
    log "FAILED (exit $rc); rolling back"
    # Never --force or reset --hard: local changes (only possible with --allow-dirty) survive, and
    # no branch was moved by this script, so returning to the earlier ref restores the exact state.
    g "$party_checkout" checkout --quiet "$before_party_ref" || log "ROLLBACK INCOMPLETE: party checkout not restored"
    g "$games_checkout" checkout --quiet "$before_games_ref" || log "ROLLBACK INCOMPLETE: games checkout not restored"
    if [[ -f $backup/web-release-before ]] && [[ -d $(cat "$backup/web-release-before") ]]; then
        ln -sfn "$(cat "$backup/web-release-before")" "$web_root/current.new" && mv -Tf "$web_root/current.new" "$web_root/current"
    fi
    local pair root before
    for pair in "party:$party_releases" "games:$games_releases"; do
        root=${pair#*:}; before=$backup/${pair%%:*}-release-before
        if [[ ! -f $before ]]; then
            rm -f "$root/current"          # there was no release before this run: leave none behind
        elif [[ -d $(cat "$before") ]]; then
            ln -sfn "$(cat "$before")" "$root/current.new" && mv -Tf "$root/current.new" "$root/current"
        fi
    done
    for unit in ${stopped[@]+"${stopped[@]}"}; do systemctl start "$unit" || true; done
    log "after rollback: party $(g "$party_checkout" rev-parse HEAD), games $(g "$games_checkout" rev-parse HEAD)"
    log "expected:       party $before_party, games $before_games; services restarted. No manifest was written."
    exit "$rc"
}
trap rollback ERR

for unit in ${restart[@]+"${restart[@]}"}; do
    systemctl stop "$unit"; stopped+=("$unit"); log "stopped $unit"
done
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
# Start order matters: providers first, then the party that launches into them.
for unit in avranaparty-games avranaparty-arcade avrana-party-core; do
    for s in ${stopped[@]+"${stopped[@]}"}; do
        if [[ $s == "$unit" ]]; then systemctl start "$unit"; log "started $unit"; fi
    done
done
for unit in ${restart[@]+"${restart[@]}"}; do
    sleep 1
    systemctl is-active --quiet "$unit" || { log "$unit did not stay active"; false; }
done
trap - ERR

# ---- 4. manifest -----------------------------------------------------------------------------
py -m avrana.ops.manifest write --out "$manifest" --party "$party_checkout" --games "$games_checkout" \
    --web-root "$web_root" --tool-sha "$tool_sha" $([[ $allow_dirty -eq 1 ]] && echo --allow-dirty) \
    --restarted ${restart[@]+"${restart[@]}"}
cp "$manifest" "$backup/after.json"
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
    log 'smoke checks skipped (--skip-smoke); the manifest says so'
    exit 0
fi
sleep 2
if py -m avrana.ops.smoke | tee "$backup/smoke.txt"; then
    py -m avrana.ops.manifest smoke "$manifest" passed
    log 'deployment complete; smoke passed. Physical phone acceptance is still a human step.'
else
    py -m avrana.ops.manifest smoke "$manifest" failed
    log "deployment applied but smoke FAILED (see $backup/smoke.txt); decide: fix forward or roll back with"
    log "  sudo bash $party_checkout/ops/deploy.sh --party $before_party --games $before_games"
    exit 2
fi
}

main "$@"
