#!/usr/bin/env bash
# The Linux-only checks a Windows checkout cannot run, in one disposable Linux machine (a cloud
# session, a Codespace, a CI runner or a rented VM), against explicit local checkouts. Never the Pi,
# never the Media host. Prints one line per check, PASS, FAIL or NOT RUN, with its counts, and a summary;
# LATER marks what only the deployed site can show (the owner-gated steps), never counted as a pass.
# NOT RUN is never a pass: the summary lists it, and the exit status is 0 only with no FAIL and no NOT RUN
# (use --allow-not-run to get 0 with NOT RUN lines, e.g. for nft without CAP_NET_ADMIN).
#
#   bash tests/linux/verify.sh [--games ../avrana-party-games] [--allow-not-run] [--skip-browsers]
#
# Prerequisites (Debian/Ubuntu): python3 python3-venv nodejs>=20 npm git nginx nftables libxml2-utils
# shellcheck util-linux (flock). The unit tests' real deployment cases need a NON-root user; run as one.
set -uo pipefail
cd "$(dirname "$0")/../.."
GAMES=../avrana-party-games ALLOW=0 BROWSERS=1
while [[ $# -gt 0 ]]; do case $1 in
  --games) GAMES=$2; shift 2 ;; --allow-not-run) ALLOW=1; shift ;; --skip-browsers) BROWSERS=0; shift ;;
  *) echo "unknown option $1" >&2; exit 2 ;; esac; done
GAMES=$(cd "$GAMES" 2>/dev/null && pwd) || { echo "no Games checkout at $GAMES" >&2; exit 2; }
# Not under test-results/: every Playwright run empties that folder, and these logs with it.
LOG=${AVRANA_VERIFY_LOGS:-.linux-verify}; mkdir -p "$LOG"
fail=0 notrun=0
row() { printf '%-8s %-44s %s\n' "$1" "$2" "$3"; [[ $1 == FAIL ]] && fail=1; [[ $1 == 'NOT RUN' ]] && notrun=1; true; }
have() { command -v "$1" >/dev/null 2>&1; }
pyrun() { # name, log, command...: a unittest run; PASS only when it ran, with its own counts
  local name=$1 log=$LOG/$2; shift 2
  "$@" >"$log" 2>&1; local rc=$? counts
  counts=$(grep -E '^Ran [0-9]+ tests|^(OK|FAILED)' "$log" | tr '\n' ' ')
  if [[ $rc -eq 0 ]]; then row PASS "$name" "$counts"; else row FAIL "$name" "$counts (see $log)"; fi
}

echo "== Party $(git rev-parse --short HEAD) $(git rev-parse --abbrev-ref HEAD) | Games $(git -C "$GAMES" rev-parse --short HEAD) | $(uname -sr) | uid $(id -u)"
[[ $(id -u) -eq 0 ]] && row 'NOT RUN' 'deploy tests as a non-root user' 'running as root: the non-root deployment cases skip'

# 1. Python units, all of them, then the Linux-only ones on their own so a skip cannot hide
pyrun 'unit tests (all)' unit-all.txt python3 -m unittest discover -s tests/unit
python3 -m unittest -v tests/unit/test_deploy_script.py >"$LOG/deploy.txt" 2>&1; rc=$?
skips=$(grep -c "skipped '" "$LOG/deploy.txt"); hosted=$(grep -c 'HostedProfile.*ok$' "$LOG/deploy.txt")
if [[ $rc -ne 0 ]]; then row FAIL 'deploy.sh (Pi and hosted profiles)' "see $LOG/deploy.txt"
elif [[ $hosted -lt 7 ]]; then row 'NOT RUN' 'deploy.sh (Pi and hosted profiles)' "only $hosted HostedProfile tests ran, $skips skipped"
else row PASS 'deploy.sh (Pi and hosted profiles)' "$(grep -E '^Ran' "$LOG/deploy.txt"), $skips skipped"; fi
if have nginx || [[ -x /usr/sbin/nginx ]]; then
  pyrun 'nginx -t on the rendered hosted site' nginx.txt python3 -m unittest -v tests.unit.test_hosted_site.RealNginx
  grep -q "skipped" "$LOG/nginx.txt" && row 'NOT RUN' 'nginx -t (RealNginx skipped)' "see $LOG/nginx.txt"
else row 'NOT RUN' 'nginx -t on the rendered hosted site' 'nginx is not installed'; fi
if python3 -m avrana.ops.hosted_site --check >"$LOG/render.txt" 2>&1; then row PASS 'hosted site is the current render' ''
else row FAIL 'hosted site is the current render' "see $LOG/render.txt"; fi

# 2. Shell and firewall files
bad=0; for f in ops/deploy.sh deploy/hosted/vm/*.sh tests/linux/verify.sh; do bash -n "$f" || bad=1; done
[[ $bad -eq 0 ]] && row PASS 'bash -n (deploy and VM scripts)' '' || row FAIL 'bash -n (deploy and VM scripts)' ''
if have shellcheck; then
  if shellcheck -S warning ops/deploy.sh deploy/hosted/vm/*.sh >"$LOG/shellcheck.txt" 2>&1; then row PASS 'shellcheck -S warning' ''
  else row FAIL 'shellcheck -S warning' "$(grep -c '^In ' "$LOG/shellcheck.txt") findings, see $LOG/shellcheck.txt"; fi
else row 'NOT RUN' 'shellcheck -S warning' 'shellcheck is not installed'; fi
if have xmllint; then
  xmllint --noout deploy/hosted/vm/avrana-staging-egress.nwfilter.xml >"$LOG/xml.txt" 2>&1 \
    && row PASS 'nwfilter XML is well formed' '' || row FAIL 'nwfilter XML is well formed' "see $LOG/xml.txt"
else row 'NOT RUN' 'nwfilter XML is well formed' 'xmllint is not installed'; fi
if have nft; then
  if nft -c -f deploy/hosted/vm/avrana-staging.nft >"$LOG/nft.txt" 2>&1; then row PASS 'nft -c (in-VM firewall parses)' ''
  elif grep -qi 'permission\|operation not permitted' "$LOG/nft.txt"; then row 'NOT RUN' 'nft -c (in-VM firewall parses)' 'needs CAP_NET_ADMIN here'
  else row FAIL 'nft -c (in-VM firewall parses)' "see $LOG/nft.txt"; fi
else row 'NOT RUN' 'nft -c (in-VM firewall parses)' 'nftables is not installed'; fi
row LATER 'nwfilter applied by libvirt' 'needs the Media host (owner-approved step 2)'

# 3. Games
( cd "$GAMES" && python3 -m venv .venv >/dev/null && .venv/bin/pip -q install -r requirements-dev.txt ) >"$LOG/games-venv.txt" 2>&1 \
  || row FAIL 'Games venv' "see $LOG/games-venv.txt"
# The same two invocations as Games CI (.github/workflows/test.yml): its suite, then the cross-repository
# job, here against this Party checkout (AVRANA_REQUIRE_PARTY: a missing Party fails instead of skipping)
( cd "$GAMES" && .venv/bin/python -m pytest -q --deselect tests/test_party_session_cross_repo.py \
    --ignore tests/test_hello_party_cross_repo.py --ignore tests/test_hello_party_package.py \
    --deselect tests/test_avrana_contract.py::test_cross_repository_contract_check ) >"$LOG/games-pytest.txt" 2>&1 \
  && row PASS 'Games pytest (as Games CI)' "$(tail -1 "$LOG/games-pytest.txt")" \
  || row FAIL 'Games pytest (as Games CI)' "$(tail -1 "$LOG/games-pytest.txt") (see $LOG/games-pytest.txt)"
"$GAMES/.venv/bin/python" tools/contract_check.py --party . --games "$GAMES" >"$LOG/contract.txt" 2>&1 \
  && row PASS 'Party <-> Games contract declarations' '' || row FAIL 'Party <-> Games contract declarations' "see $LOG/contract.txt"
( party=$PWD; cd "$GAMES" && AVRANA_PARTY_REPO="$party" AVRANA_REQUIRE_PARTY=1 .venv/bin/python -m pytest -q -rs \
    tests/test_party_session_cross_repo.py tests/test_hello_party_cross_repo.py tests/test_hello_party_package.py \
    tests/test_avrana_contract.py ) >"$LOG/games-cross.txt" 2>&1 \
  && row PASS 'Games cross-repo (real Party service)' "$(tail -1 "$LOG/games-cross.txt")" \
  || row FAIL 'Games cross-repo (real Party service)' "$(tail -1 "$LOG/games-cross.txt") (see $LOG/games-cross.txt)"
( cd "$GAMES" && node --test tests/party_drivers_test.mjs ) >"$LOG/drivers.txt" 2>&1 \
  && row PASS 'Games party drivers' "$(grep -E '^# (pass|fail)' "$LOG/drivers.txt" | tr '\n' ' ')" \
  || row FAIL 'Games party drivers' "see $LOG/drivers.txt"

# 4. Browsers: Party suites, the cross-repository provider suites (native Checkers is Linux-only), and
#    the hosted harness rehearsed against the provider harness (real BLUFF; native Checkers)
if [[ $BROWSERS -eq 1 ]]; then
  # Chromium's system libraries are a prerequisite (npx playwright install-deps chromium, as root, once);
  # a machine that brings its own browsers says so with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
  npm ci --no-audit --no-fund >"$LOG/npm.txt" 2>&1 || row FAIL 'npm ci' "see $LOG/npm.txt"
  if [[ -z ${PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD:-} ]]; then
    npx playwright install chromium >>"$LOG/npm.txt" 2>&1 || row FAIL 'Playwright Chromium' "see $LOG/npm.txt"
  fi
  node --test tests/offline/*.test.mjs >"$LOG/modules.txt" 2>&1 \
    && row PASS 'offline modules' "$(grep -E '^# (pass|fail)' "$LOG/modules.txt" | tr '\n' ' ')" || row FAIL 'offline modules' "see $LOG/modules.txt"
  pw() { # name, log, env..., -- args...
    local name=$1 log=$LOG/$2; shift 2
    env "$@" >"$log" 2>&1; local rc=$?
    local counts; counts=$(grep -E '^\s+[0-9]+ (passed|failed|skipped|flaky)' "$log" | tr -s ' \n' ' ')
    [[ $rc -eq 0 ]] && row PASS "$name" "$counts" || row FAIL "$name" "$counts (see $log)"
  }
  pw 'Party browser suite' party.txt AVRANA_PYTHON=python3 npx playwright test -c playwright.party.config.ts --reporter=line
  pw 'provider cross-repo (incl. native Checkers)' provider.txt AVRANA_GAMES_REPO="$GAMES" \
     AVRANA_PROVIDER_PYTHON="$GAMES/.venv/bin/python" npx playwright test -c playwright.provider.config.ts --reporter=line
  rehearse() { # name, port, games, server args..., then runs the hosted specs against it
    local name=$1 port=$2 games=$3; shift 3
    "$GAMES/.venv/bin/python" tests/provider/server.py --games "$GAMES" --port "$port" --party-session --game-origin "$@" \
      >"$LOG/harness-$port.txt" 2>&1 & local pid=$!
    for _ in $(seq 1 40); do curl -sf -o /dev/null -H "Host: party.avrana.test:$port" "http://127.0.0.1:$port/party/" && break; sleep 1; done
    pw "$name" "hosted-$port.txt" HOSTED_BASE_URL="http://party.avrana.test:$port" HOSTED_GAME_ORIGIN="http://games.avrana.test:$port" \
       HOSTED_RESOLVE_LOOPBACK=1 HOSTED_GAMES="$games" HOSTED_GAMES_REPO="$GAMES" \
       npx playwright test -c playwright.hosted.config.ts recovery.spec.ts journey.spec.ts --project android-size --reporter=line
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  }
  rehearse 'hosted rehearsal: real BLUFF, game origin' 8291 bluff
  rehearse 'hosted rehearsal: native Checkers' 8292 checkers --native-game checkers
  row LATER 'hosted edge (Access, two real hostnames)' 'needs the deployed site and a service token'
else row 'NOT RUN' 'browser suites' '--skip-browsers'; fi

echo
if [[ $fail -ne 0 ]]; then echo 'linux verification: FAIL'; exit 1; fi
if [[ $notrun -ne 0 ]]; then echo 'linux verification: incomplete (NOT RUN above is not a pass)'; [[ $ALLOW -eq 1 ]] && exit 0; exit 3; fi
echo 'linux verification: PASS'
