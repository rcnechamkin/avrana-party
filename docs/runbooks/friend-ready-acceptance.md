# Runbook: friend-ready acceptance session (AVR-10, AVR-12, AVR-261, AVR-27)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance** (2026-10-09).
This is one packet for one physical session on the Pi and real phones. It prepares
[AVR-10](https://linear.app/avranakern/issue/AVR-10) (offline cold boot),
[AVR-12](https://linear.app/avranakern/issue/AVR-12) (four-phone connectivity),
[AVR-261](https://linear.app/avranakern/issue/AVR-261) (Checkers on an iPhone and an Android phone) and
[AVR-27](https://linear.app/avranakern/issue/AVR-27) (four-human offline BLUFF). It also produces
evidence for AVR-11 (onboarding) and AVR-295 (shell-to-BLUFF journey); it closes none of them.
Written from source and Linear on 2026-10-09 (repository dates are local time). **Every command below is owner-run on the Pi or a phone.
Nothing here was run by an agent, nothing in CI or a document authorizes it, and no result is claimed.**
An agent cannot close any of these issues. Where this packet disagrees with a script's `--help` or
source, the script wins: stop and report the difference.

Evidence rules ([TESTING](../TESTING.md)): CI, Chromium and disposable-runner systemd runs are not
Raspberry Pi or phone evidence. A merged PR is not a deployment. A curl is not a phone test.
Leave a field blank when it was not measured; never estimate afterwards.

## Two sessions

**Session B cannot be run yet.** Native Checkers needs the separate game origin
`https://games.avrana.net`: the Checkers page (Games `fb711d9`, `checkers/web/app.mjs`) refuses to connect when
the Party origin it is told equals its own origin and shows "Open Checkers from Party Home."; `provision-game`
always tells it `AVRANA_PARTY_ORIGIN=https://party.avrana.net`. The repository has no `games.avrana.net` DNS record,
certificate name, nginx server block or `game_origins` entry. That work is Linear AVR-319 (blocks AVR-261), on
branch `feat/avr-319-game-origin-deployable`; its owner runbook will be `docs/runbooks/game-origin.md`, which
**arrives with AVR-319 and is not merged**. Until AVR-319 is merged **and** deployed, AVR-261 cannot pass.

| Session | Issues | Needs | Steps |
|---|---|---|---|
| **A: can run on today's release pair** | AVR-10, AVR-12, AVR-27 | The release pair, the matching nginx site file and the config check. BLUFF runs through the legacy same-origin route: no service-users migration, no `prepare-native-games`, no `provision-game`, no game origin | 0, 1, 2, 3, 5, 6, 8, 10 (and section 9 if needed) |
| **B: blocked** | AVR-261 | AVR-319 merged and deployed, then the service-users migration, `prepare-native-games`, the game origin, `provision-game checkers` | 4, 7, 10 (and section 9 if needed) |

Session A accepts BLUFF on the **pre-migration service layout** (services still run as `cody`). AVR-27 is worth a
short BLUFF re-check after the migration (a launch, a deal, one reconnect, an end) before the result is relied on for the shipping configuration.

## What counts as developer intervention

AVR-27 requires "no developer intervention on the normal happy path"; AVR-10 requires a cold boot
"without developer intervention". For this session:

| Counts as intervention (the criterion fails) | Does not count |
|---|---|
| Any command on the Pi, service restart, config or network change, or reboot after the first phone has joined, other than the scripted read-only observations in this packet | Steps 0 to 3 (Session A) or 0 to 4 (Session B) before any phone joins; the scripted cable pull and power cycle in step 5 |
| Explaining the objective, rules, controls, or what a screen means; telling a player which button to press; touching a participant's phone | The printed join card (step 6) and the scripted prompts in the record sheets ("lock your phone now"), given to everyone alike |
| Choosing or starting the game for the Host, ending it for them, or rejoining someone | Reading screens, timing with a stopwatch, taking notes, screen-recording |
| Re-running a step because it failed | Read-only checks at the checkpoints this packet names (they are timed and logged) |

A failure that needs any left-hand-column action is recorded as a failure with the action taken;
it is not repaired silently. Do not run continuous SSH polling during measurements (every session
is a CPU burst): read once at the checkpoints, or start `tools/radio-watch` detached and read its
file at the end.

## Stop conditions

Stop, record the exact step, time, exit status and sanitized error, and do not continue past:

- any step whose expected output below is not what you see, until you understand why;
- a deploy, migration, prepare or provision command that exits non-zero, or a "NOT complete" message;
- `summary.state` other than `ok` in `/party/api/status` after any deploy step;
- an under-voltage event or `vcgencmd get_throttled` other than `0x0` during a measured step;
- a certificate warning on any phone (do not tap through it);
- a phone that cannot reach `https://party.avrana.net/party/` after one rejoin of the Wi-Fi by the participant;
- any step that would need `--allow-dirty`, `--allow-branch`, `--force-busy` or `--skip-smoke`: those flags
  are not part of this procedure.

Each defect becomes its own scoped Linear issue with the evidence; fixing it is not part of the session.

## Owner decisions, with recommended defaults

| # | Decision | Recommended default | Why |
|---|---|---|---|
| D1 | How does native Checkers get its game origin? | **Checkers needs the game origin; same-origin does not work** (see "Two sessions"). Do Session A first and run Session B only after AVR-319 is merged and deployed, following `docs/runbooks/game-origin.md` (arrives with AVR-319, not merged). | Same-origin was considered and rejected: the page never connects when the Party origin equals its own. BLUFF and EXPO are unaffected (legacy route, same origin) and do not need it. |
| D2 | Run the never-run service-users migration (step 4b) before the BLUFF session? | **No. Keep Session A to the smallest change set**: the release pair, the matching nginx site file, the config check. Run the migration only as part of Session B. | A failed migration must not put the four-human BLUFF acceptance at risk. The cost: AVR-27 is accepted on the pre-migration layout and deserves a short re-check afterwards. |
| D3 | Run AVR-27 before or after Games [PR #57](https://github.com/rcnechamkin/avrana-party-games/pull/57) (AVR-313 BLUFF table polish, open, not in Games `fb711d9`)? | **Now, without waiting.** If #57 merges first, use the new Games `main` SHA, re-check Party's `Cross-repo contract` for that pair, and update the SHAs in step 0. | AVR-27 measures comprehension and completion of what ships; the unpolished reveal and focus behaviour are what AVR-313 records as gaps. Waiting delays all physical evidence. |
| D4 | How is "upstream removed" done for AVR-10? | **Pull the Ethernet cable (eth0) and power-cycle.** Observe from a laptop on the Party Wi-Fi (`ssh 10.42.0.1`). | `tools/avrana-offline` only blocks party clients and leaves the Pi's own upstream; it does not prove the Pi boots without one. The cost is losing the home SSH path ([network](network.md): "Never take eth0 down during a remote session"). Restore the cable only after the session. |
| D5 | Is AVR-31 (certificate renewal timer) required before this session? | **No**, but check the certificate runway in step 1 and install renewal before 2026-11-25. | Linear AVR-31 (2026-10-03): the certificate expires 2026-12-25; `lego renew --days 30` would act about 2026-11-25; the timer is not enabled. `/party/api/status` fails its certificate check below 21 days (about 2026-12-04). |
| D6 | Limited Mode (plain-HTTP fallback)? | **Out of scope; not deployed.** Mitigate with the phone checklist in step 6. | LIMITED-MODE rollout steps 3 and 4 have not happened; nginx has no port-80 `/party/`. A phone whose HTTPS to `party.avrana.net` fails has no way in. |

## 0. The release pair, and how to verify it

Pinned for this packet (checked 2026-10-09 local, 2026-10-10 UTC; Party `main` was `defd4a2` and Games `main` was `fb711d9`):

| Repository | SHA (pass the full 40 characters; `ops/deploy.sh` refuses short ones) | Evidence on that SHA |
|---|---|---|
| Party | `defd4a2e8120baddcc556615daf06a76d0b93ee4` (merge of #95 AVR-314, after #94 AVR-238 integration) | [Offline checks](https://github.com/rcnechamkin/avrana-party/actions/runs/38028266735) success; [Cross-repo contract](https://github.com/rcnechamkin/avrana-party/actions/runs/38028266746) success; [Graphify](https://github.com/rcnechamkin/avrana-party/actions/runs/38028266938) success (derived, not evidence) |
| Games | `fb711d95242789fafec18a22023a1d728a2f6a90` (merge of #54 AVR-238 Checkers) | [Test](https://github.com/rcnechamkin/avrana-party-games/actions/runs/38028219351) success |
| Both, on Party `main` | | [Service trust proof](https://github.com/rcnechamkin/avrana-party/actions/runs/38028629461) (manual dispatch) success: jobs `proof`, `native-game`, `prepare-native-games` and `checkers` (prepare, provision, a complete game, a Host-ended session, `boundary --phase 2`, remove) on a disposable Ubuntu runner. Tier 2 evidence about systemd, never about this Pi, nginx, TLS or phones |

If either `main` has moved, do not substitute silently: choose a Party `main` commit whose
`Offline checks` and `Cross-repo contract` are green and a Games commit Party's contract run
tested, write both full SHAs in the record sheet, and re-read the diffs since the pinned pair.
Verify from a laptop (read-only):

```bash
gh run list --repo rcnechamkin/avrana-party --branch main --limit 10
gh run list --repo rcnechamkin/avrana-party-games --branch main --limit 5
git ls-remote https://github.com/rcnechamkin/avrana-party.git refs/heads/main
```

An independent reviewer's (`reviewer` agent, REVIEW.md) result on the final heads belongs in the
record sheet; this packet does not supply it.

## 1. Preflight, backups and rollback preparation (before any change)

**On the Pi** (a shell from `ssh party`; the commands are written for the Pi's own shell). Nothing here changes the appliance except the backup copies.

```bash
# What is deployed now (the "before" pair; keep it for rollback)
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool
systemctl is-active avrana-party-core avranaparty-games avranaparty-arcade nginx
git -C /home/cody/avrana-party rev-parse HEAD; git -C /home/cody/avrana-party status --porcelain   # porcelain must be empty
git -C /home/cody/avrana-party-games rev-parse HEAD; git -C /home/cody/avrana-party-games status --porcelain
# Certificate runway and names (AVR-31, AVR-10 comment: record the runway, not just that HTTPS worked)
openssl x509 -in /etc/avrana-party/tls/current/fullchain.pem -noout -dates -ext subjectAltName
# Power baseline
vcgencmd get_throttled; journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
# Boundary before: how many phase-1 rules the Pi meets today (6 of 25 on 2026-10-03)
(cd /opt/avrana-party/current && sudo python3 -m avrana.ops.boundary --phase 1)   # only if /opt/avrana-party/current exists and carries avrana.ops; otherwise skip and record "not available"
```

Back up, **on the Pi** (root-only; the TLS copy holds a private key: never download it):

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -m 0700 "/root/avrana-friend-ready-backups/$stamp"
sudo cp -a /etc/nginx/sites-available/avrana-party /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf \
  /etc/avrana-party/party-core.json "/root/avrana-friend-ready-backups/$stamp/"
sudo cp -a /etc/avrana-party/tls "/root/avrana-friend-ready-backups/$stamp/"
sudo cp -a /etc/systemd/system "/root/avrana-friend-ready-backups/$stamp/systemd-system"
sudo tar -C /etc/NetworkManager -czf "/root/avrana-friend-ready-backups/$stamp/nm-system-connections.tgz" system-connections
echo "backup: /root/avrana-friend-ready-backups/$stamp"        # write this path in the record sheet
```

(The same backup list as [party-https](party-https.md) "Pre-deployment and backup" and
[network](network.md), widened to the systemd units and the Party Core config.) `ops/deploy.sh`
makes its own before-state under `/var/backups/avrana-party/deploy-<UTC>/`; the migration and
prepare commands each make theirs. Write all four paths down. Each reverses a different layer
(section 9).

**Config check against the target release (mandatory before step 2).** Party Core refuses to
start when `party-core.json` disagrees with a Game Contract (`avrana.party.service.main`
raises `SystemExit`), and a deploy that cannot start Party Core rolls itself back. The known
case: an old `games.arcade-gauntlet2.max_players: 2` against the contract's 4
([arcade-party-provider](arcade-party-provider.md)). Check with the target tree, not the installed one, **on the Pi**:

```bash
git -C /home/cody/avrana-party fetch origin
rm -rf /tmp/avrana-target && mkdir /tmp/avrana-target
git -C /home/cody/avrana-party archive defd4a2e8120baddcc556615daf06a76d0b93ee4 | tar -x -C /tmp/avrana-target
cd /tmp/avrana-target && sudo python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json
```

Expect `... game(s) agree with their contracts`. If it names `arcade-gauntlet2.max_players` (or another
derived key), edit only that line out of the config (the backup above is the undo), keep URL, key path
and timeout, and run the check again. Also confirm, without printing the file to anyone, that `origins`
holds exactly one bare `https://party.avrana.net` entry; `provision-game` (Session B) refuses zero or several usable origins. `game_origins` is set only in Session B, by the game-origin runbook.

## 2. Deploy with explicit SHAs (dry run first)

Stage the Games commit (the Pi's GitHub key reads `avrana-party`, not the private Games repository;
[games-fork-deploy](games-fork-deploy.md) section 1). **On the laptop**, in a Games checkout after `git fetch`:

```bash
git bundle create avrana-party-games.bundle origin/main && scp avrana-party-games.bundle party:
```

**On the Pi** (the fetch refspec form below is standard git; it is not spelled out in an earlier runbook):

```bash
git -C /home/cody/avrana-party-games fetch ~/avrana-party-games.bundle 'refs/remotes/origin/main:refs/remotes/bundle/main'
git -C /home/cody/avrana-party-games cat-file -e fb711d95242789fafec18a22023a1d728a2f6a90^{commit} && echo present
rm ~/avrana-party-games.bundle
```

Take the deploy script from the target commit (the checkout may predate `ops/deploy.sh`; [deploy](deploy.md) "First run"), then dry run, then the real run. No game session may be live; the real run refuses otherwise. **These lines run on the laptop** (`ssh party "..."` is the form [deploy](deploy.md) uses); the script is a copy at `/tmp/avrana-deploy.sh` on the Pi, taken from the target commit. Record that this copy was used: a rollback uses the same form (section 9).

```bash
P=defd4a2e8120baddcc556615daf06a76d0b93ee4; G=fb711d95242789fafec18a22023a1d728a2f6a90
ssh party "git -C /home/cody/avrana-party fetch origin && git -C /home/cody/avrana-party show $P:ops/deploy.sh > /tmp/avrana-deploy.sh"
ssh party "bash /tmp/avrana-deploy.sh --party $P --games $G --dry-run"
ssh -t party "sudo bash /tmp/avrana-deploy.sh --party $P --games $G"
```

The dry run changes nothing and needs no root; read its plan (which checkout moves, which units restart,
whether a web release is built). The real run: checks both repositories out detached at exactly those
SHAs, builds root-owned releases under `/opt/avrana-party` and `/opt/avrana-party-games`, installs a
web release, restarts only the changed units, writes the deployment manifest and runs
`python3 -m avrana.ops.smoke`. It prints the before pair and the rollback command if smoke fails
(exit 2). **Party Core is memory-only: this restart forgets every member. Do all of steps 2 and 3 (Session A), or 2 to 4 (Session B),
before any phone joins.**

Expected afterwards (**on the Pi**, or the `curl` from a Party-connected laptop):

```bash
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool
cd /opt/avrana-party/current && python3 -m avrana.ops.manifest validate
```

`summary.state` is `ok`; `party.deployed_sha` and `games.deployed_sha` are the two SHAs above;
`party_core.ok` is true with `session: null`; `summary.notes` may list the optional certificate timer
as not installed ([deploy](deploy.md) "After"). Copy the status JSON into the record sheet, with no secrets.

## 3. nginx site file, including the AVR-314 cookie rule

The web build and the site file of one commit are a single deployment unit (the catalog offers
exactly the games the site routes; [deploy](deploy.md)). `ops/deploy.sh` never installs nginx, so
install the site file **immediately** after step 2, still before any phone joins. Until then Party
Home may show tiles that lead to nginx's own 502. In Session A Checkers is not provisioned and
Party Home may still list it (the catalog comes from the contracts): nobody taps it.

**On the Pi:**

```bash
cmp /opt/avrana-party/current/avrana-party.nginx /opt/avrana-party/current/arcade/nginx-site && echo "repo files identical"
diff /etc/nginx/sites-available/avrana-party /opt/avrana-party/current/avrana-party.nginx | head -80   # read it: no Pi-only edits may be lost
sudo cp /opt/avrana-party/current/avrana-party.nginx /etc/nginx/sites-available/avrana-party
sudo nginx -t && sudo systemctl reload nginx
cmp /opt/avrana-party/current/avrana-party.nginx /etc/nginx/sites-available/avrana-party && echo "installed = repo"
```

(The backup of the previous site file is in step 1. `ops/check-party-config.sh <checkout>` is the
repository's candidate-config syntax check, with a throwaway certificate; run it against the target
tree before the copy if you want a second `nginx -t`.)

Verify the AVR-314 rule (the device cookie never reaches a game server). The expected count of
`proxy_set_header Cookie "";` directives depends on the Party SHA: **5 at `defd4a2`**; **7 once PR #96 (AVR-318, `/arcade/`
also clears Cookie) is in the deployed commit**. Take the number from the deployed `avrana-party.nginx` itself and compare
the installed file and the loaded config with it. **On the Pi** (lines marked laptop run from a Party-connected laptop):

```bash
grep -c 'proxy_set_header Cookie ""' /opt/avrana-party/current/avrana-party.nginx    # the expected count for this SHA (5 at defd4a2, 7 with #96)
grep -c 'proxy_set_header Cookie ""' /etc/nginx/sites-available/avrana-party        # equal to the line above
sudo nginx -T 2>/dev/null | grep -c 'proxy_set_header Cookie ""'                    # equal again: the LOADED config, not only the file
curl -s --noproxy '*' https://party.avrana.net/party/api/origin.json                 # (laptop) "scheme":"https", "serverAddr":"10.42.0.1" from a Party client
curl -s --noproxy '*' https://party.avrana.net/party/version.json                    # (laptop) the web release of the deployed Party SHA
curl -sk --resolve party.avrana.net:443:127.0.0.1 -o /dev/null -w '%{http_code}\n' https://party.avrana.net/games/checkers/avrana/x   # 404: control paths are never proxied
curl -sk --resolve party.avrana.net:443:127.0.0.1 -o /dev/null -w '%{http_code}\n' https://party.avrana.net/games/checkers/          # 502 while Checkers is not provisioned (no socket): expected in Session A
curl -s --noproxy '*' -i -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html   # (laptop) still the literal Success page
```

What this proves: the file and the loaded config carry the rule. Whether an upstream really receives
no `Cookie` header is proven by `tests/unit/test_nginx_site.py` against a real nginx in CI, and on the
Pi only by the phone inspection in step 7 (Session B). There is no
Pi-side echo test in the repository. Do not run any nginx command not listed here. No Checkers-specific
route, `Secure` cookie change, HSTS or `Service-Worker-Allowed` is part of this step.

## 4. Session B only: phase 1, migration, prepare, game origin, provision Checkers

**Not runnable yet** (see "Two sessions"): the game origin in 4d needs AVR-319 merged and deployed. Do not run this step in Session A (decision D2). All on the Pi (the lines written `ssh -t party "..."` run on the laptop), before any phone joins. Sources: [service-users-migration](service-users-migration.md),
[prepare-native-games](prepare-native-games.md), [provision-game](provision-game.md).

**4a. Is phase 1 applied?** From the deployed tree:

```bash
cd /opt/avrana-party/current && sudo python3 -m avrana.ops.boundary --phase 1
```

25 of 25 rules met means phase 1 is applied; go to 4c. On 2026-10-03 the Pi met 6 of 25 and
no document records the migration as run, so expect to do 4b.

**4b. Service-users migration (ADR 0016 phase 1, AVR-256), only if 4a is not 25 of 25.** Session B only. This is the least
proven step in the packet: it has never run on any host, and the arcade's hardening with RetroArch is
"never validated anywhere" (the runbook). Read the runbook's "To verify against the Pi before migration"
table against `systemctl cat avrana-party-core avranaparty-games avranaparty-arcade` first. Prerequisites
it names: the key store holds `arcade-gauntlet2.key`, `bluff.key` **and `expo.key`** (the Pi had no
`expo.key` on 2026-10-03; the script refuses until it exists), and no session is live.

```bash
# on the Pi:
sudo AVRANA_PARTY_KEY_OWNER=cody bash /opt/avrana-party/current/ops/provision-party-game-key.sh expo   # only if expo.key is missing; before migration the key store is still cody's
# on the laptop:
ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --dry-run"
ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh"
```

Record the printed backup directory (`/var/backups/avrana-party/service-users-<UTC>/`) and the line
`arcade core sha256: <hash>`. Expect step 5 of the script to print the phase-1 verdict. Then
`sudo python3 -m avrana.ops.boundary --phase 1` (25 of 25), `python3 -m avrana.ops.smoke`, and re-read
`/party/api/status`. The migration changes the listener of the games service to loopback and moves the
services to dedicated users. Its phone checks (BLUFF, EXPO and Gauntlet II each launch and end from Party Home)
are in step 7 (item 9) and, for BLUFF, the short re-check named under "Two sessions"; if you want them earlier, join and launch with one phone, then restart nothing.
If the script exits 2, a service is not active or a rule is not met: stop (section 9 reverses it).

**4c. Prepare the appliance for native games (AVR-304)**, on the Pi, from the deployed root-owned tree. It restarts
Party Core when it has to (it says so first, and refuses while a session runs):

```bash
sudo /opt/avrana-party/current/ops/prepare-native-games --dry-run
sudo /opt/avrana-party/current/ops/prepare-native-games
sudo /opt/avrana-party/current/ops/prepare-native-games     # second run: "nothing to change"
systemctl is-active avrana-party-core avrana-party-core.socket
stat -c '%F %a %U:%G' /run/avrana-party/internal.sock       # socket 660 avrana-party:avrana-games
systemctl show -p CanReload --value avrana-party-core       # yes
grep -n '"registry"' /etc/avrana-party/party-core.json
```

Keep the printed reverse command and the backup directory (`/var/backups/avrana-party/native-games-<UTC>/`).

**4d. Game origin (AVR-319; arrives with that issue, not merged).** Follow `docs/runbooks/game-origin.md` end to end:
the `games.avrana.net` DNS host-record, the certificate name, the nginx server block, `game_origins` in
`party-core.json` and the game servers' `AVRANA_PARTY_ORIGIN=https://party.avrana.net`. Its backups, checks and reverse
are its own; this packet does not restate or guess them. Do it before 4e so the first launch finds both names;
`provision-game` derives `AVRANA_PARTY_ORIGIN` from the single usable `origins` entry.

**4e. Provision Checkers**, on the Pi, from `/opt/avrana-party/current` (the grant's runtime is
`/usr/bin/python3 -m checkers` under `/opt/avrana-party-games/current`, which step 2 built):

```bash
cd /opt/avrana-party/current
sudo python3 -m avrana.ops.provision_game checkers --dry-run
sudo python3 -m avrana.ops.provision_game checkers
sudo python3 -m avrana.ops.provision_game checkers          # second run: "nothing to change"
systemctl is-active avrana-game@checkers.socket
curl -sk --resolve party.avrana.net:443:127.0.0.1 -o /dev/null -w '%{http_code}\n' https://party.avrana.net/games/checkers/   # expect 200 (the game's static page, served from its socket); 502 means the socket is missing or the game cannot start: stop. A 200 is not a phone test: the page refuses to run unless it was opened from the game origin
```

(A non-root dry run says "needs root to read the key store"; use `sudo`. The real run asks Party Core to
reload, never restart. Do not edit the registry or the key by hand.) The dry run does not make the
real run's root-owned-path check; a refusal naming a path means the Games release is not root-owned:
stop. `boundary --phase 2` needs Checkers **running** to inspect loaded units, and Checkers starts
only when launched from Party Home, so its verdict is taken in step 7. Run it now only if you launch a
test round; otherwise record "deferred to step 7".

**4f. Final preflight for the phones:** `/party/api/status` is `ok` with the two SHAs; `python3 -m avrana.ops.smoke` passes;
`sudo python3 -m avrana.ops.boundary --phase 1` still passes; the backup paths from steps 1 to 4 are written down.

## 5. AVR-10: offline cold boot

Purpose: upstream removed on purpose, a cold boot with nobody touching the Pi, a Party an unprimed phone
can reach. Session A: run after steps 2 and 3. Session B: the same checks apply after step 4 and also cover
`avrana-game@checkers.socket`. This is also the first reboot of the deployed configuration: it tests that the services come up by themselves.

Before the pull, record **on the Pi** (step 1 already holds most of it):

```bash
nmcli -f NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show   # is "Avrana Party Internal" priority above the client profiles? (network.md "Boot determinism", PROPOSED)
date -u; timedatectl                                                           # the Pi has no RTC: record the clock and sync state
vcgencmd get_throttled; journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
```

Do: note the time; `sudo poweroff`; unplug the Ethernet cable; wait 30 s; apply power. **No one touches the Pi, a
keyboard or a screen after power-on.** Start a stopwatch at power-on. The observer laptop and
phones are on the Party Wi-Fi only.

Checkpoints (**on the laptop** joined to "Avrana Party", read once each, times recorded; no polling; the `ssh` lines run commands on the Pi through it):

```bash
ssh 10.42.0.1 'ip -br addr; ip route; nmcli -t -f GENERAL.CONNECTION device show wlan0; iw dev wlan0 info | head -8'
ssh 10.42.0.1 'timedatectl; iw dev wlan0 get power_save; systemctl is-active avrana-party-core avrana-party-core.socket avranaparty-games avranaparty-arcade nginx'   # Session B: add avrana-game@checkers.socket
ssh 10.42.0.1 '! ping -c1 -W3 1.1.1.1 && echo "no upstream (expected)"'
dig +short @10.42.0.1 party.avrana.net                                         # 10.42.0.1
dig +time=3 +tries=1 @10.42.0.1 example.com                                    # must fail; record SERVFAIL/REFUSED/timeout
for h in captive.apple.com connectivitycheck.gstatic.com www.msftconnecttest.com detectportal.firefox.com; do dig +short @10.42.0.1 $h; done   # all 10.42.0.1
curl --noproxy '*' -s -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html
curl --noproxy '*' -s https://party.avrana.net/party/api/status | python3 -m json.tool
ssh -t 10.42.0.1 'vcgencmd get_throttled; journalctl -k -b | grep -icE "undervoltage|voltage normalis"; sudo tail -n 5 /var/log/avrana/pi-throttle.jsonl'   # -t: sudo needs a tty
```

(The last line prompts for the sudo password, which is why it uses `ssh -t`; `tools/avrana-topology-check` and `tools/radio-watch` can be copied to
`~/avrana-lab/` beforehand, per [network](network.md); the former is read-only and not to be run during a
power measurement.) On a **phone**, forget "Avrana Party", rejoin and record what the OS shows (iOS: no
sign-in sheet expected; Android: "no internet" but no sign-in sheet; both are expectations from
[network](network.md), not facts), then open `https://party.avrana.net/party/`: Party Home loads, no
certificate warning. Record the certificate dates (step 1) and the phone's own clock.

Stop if the AP is not up within 5 minutes, or if `wlan0` came up as a client of a home network: do not fix; record, then restore power and cable and use [network](network.md) "Boot determinism".

## 6. AVR-12: four-phone connectivity

Run with the same offline boot, no restart. Four real phones (at least one iPhone, one Android). Per phone, set
beforehand and record: mobile data **off**, VPN off, Android Private DNS off or "Automatic" (never a hostname),
iCloud Private Relay off for this network, and the phone's clock automatic. These are the known ways HTTPS to
`party.avrana.net` fails with no Limited Mode to catch it (D6). **Join card:** the printed instruction every
participant gets, identical for all: the Wi-Fi name, the Wi-Fi password written by the owner (never in the
repository), and the address `https://party.avrana.net/party/`. A link QR code of that address is optional;
the Wi-Fi password never goes into a document or issue.

Start `tools/radio-watch` detached **on the Pi** (copy it to `~/avrana-lab/` first; it records hashed station ids, never MACs, and
its file is read once at the end), e.g. `setsid -f ~/avrana-lab/radio-watch 1500 10 ~/avrana-lab/friend-ready-radio.jsonl </dev/null`.
Join the phones one at a time with a stopwatch, then use Party Home and navigation for at least 15 minutes (open Library, a game
detail, return; lock and unlock one phone; walk one phone to the edge of range and back). Afterwards, once, **on the Pi** (through `ssh -t 10.42.0.1` from the laptop on the Party Wi-Fi, since the cable is out):

```bash
iw dev wlan0 station dump | grep -c '^Station'                       # associated stations
cat /var/lib/NetworkManager/dnsmasq-wlan0.leases | wc -l             # leases (addresses stay local; do not paste them)
sudo journalctl -u NetworkManager -u avrana-party-core --since "<start time>" --no-pager | grep -iE 'deauth|disassoc|timeout|dhcp' | head -40
vcgencmd get_throttled; journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
```

Practical device limit: the Pi 4 AP is reported to top out near 8 stations ([network](network.md), unmeasured); four is below it. Record the observed maximum, not the reported one.

## 7. AVR-261: Checkers on two phones (iPhone Safari + Android Chrome)

**Session B only; blocked until AVR-319 is merged and deployed (see "Two sessions").** Needs steps 2 to 4 complete, including the game origin. Two of the four phones: one iPhone (Safari) and one Android (Chrome), joined to the Pi's own
Wi-Fi, no internet dependency, no installed player app. Full Mode only; Limited Mode is out of scope.

1. **Launch.** Host chooses Checkers on Party Home; each phone receives a distinct seat and reaches
   the Checkers page on the game origin (`https://games.avrana.net/games/checkers/...`, per `docs/runbooks/game-origin.md`) with no certificate warning on either name. The page connects to the Party through the bridge frame; it shows "Open Checkers from Party Home." if it was opened any other way.
2. **Boundary command, on the Pi** (the game is now running), from `/opt/avrana-party/current`:
   ```bash
   sudo python3 -m avrana.ops.boundary --phase 2
   systemctl is-active avrana-game@checkers.service avrana-game@checkers.socket
   python3 -m avrana.ops.smoke
   ```
   Acceptance criterion 4 is "every rule met with Checkers provisioned": record each rule line. A refusal or unmet rule blocks acceptance.
3. **Play** legal alternating moves to a finish, with a compulsory capture and a kinging on the way; try one illegal move (the board must not change).
4. **Reload / lock.** Reload one phone mid-game, then lock it for at least 60 seconds: same seat, same board. Repeat on the other phone.
5. **Disconnect** one phone from Wi-Fi and reconnect: same seat and board.
6. **Finish** a full match: both phones return to Party Home and show the result.
7. **Host End.** Start another round; the Host ends it mid-play; both phones return to Party Home. A guest cannot end it.
8. **Cookie boundary (iPhone Web Inspector or Android remote inspect if available; otherwise "not inspected").** `games.avrana.net` holds no cookie and no Party local storage; the Party frame stays on `party.avrana.net`. Redact tickets/tokens. [BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md) section 4 lists the ten real-phone bridge checks.
9. **Regression.** Afterwards launch and end BLUFF; launch and end Gauntlet II (the arcade after phase 1 is the least-proven path: see 4b); check Party Home/Library and presence. Record participant counts and anything not tested.

Failure capture and reverse: sections 9 and 10.

## 8. AVR-27: four-human offline BLUFF

**Session A.** Prerequisites in Linear (AVR-27 is Backlog and blocked): AVR-10 (step 5), AVR-12 (step 6) and the Done blockers AVR-51, AVR-90, AVR-91, AVR-23, AVR-24, AVR-25.
Four humans, four phones, **at least one first-time player who has not seen BLUFF** (say how many are first-timers); the upstream still disconnected (step 5 not undone).
Pick the Host in advance as the most reliable participant and tell them only: keep your phone awake and unlocked at Party Home; this is the same for all
roles and is not a rules explanation. The Host launches BLUFF from Party Home, chooses Play or Watch as prompted, and starts the game when ready (host-only Start, ADR 0010).

Observer script, in order (timestamps from a stopwatch; scripted prompts are given to everyone):

1. All four join; the Host launches BLUFF from Party Home; all four land in the same session. (Ask nobody to look at another phone.)
2. **Comprehension (before play):** each first-time player, unprompted, says what they think the objective is and what the controls do (observer records the words; no correction until after the session).
3. **Private views:** after the deal, each player reads their own hand aloud to the observer one at a time out of the others' hearing, or the observer checks each phone in turn; no player may see another's hand.
4. Play to completion. Note stalls, misreads of the challenge reveal, and every moment a player asks the observer a question (each is an intervention if answered).
5. **Reconnect:** at a scripted moment during someone else's turn, one phone locks for about 15 to 20 seconds (under BLUFF's `AWAY_GRACE` of 30 s, `games/bluff/game.py`), then unlocks; later a second phone reloads the page. Record seat, hand and time back. If a lock exceeds the grace, autopilot may act for that player: record that it did.
6. **Completion:** result shown, then each phone returns to a sane Party state (Party Home with the held result, usable Library). A second launch from Home works.
7. Debrief (after the session, intervention no longer matters): what was unclear, latency felt, friction, recovery.

Known context, not defects of the packet: Games `fb711d9` does not contain PR #57 (AVR-313), whose audit records the challenge outcome not shown where it happens, partial focus handling and small-phone overlaps; the redesigned shell and ADR 0011 console model have never been seen on a real phone since the 2026-09-29 verification (AVR-295, AVR-212 open). Record, do not fix.

## 9. Safe rollback for each layer

Roll back in the **reverse order** of installation, and only with no session live. Ending live rounds from Party Home comes first. A Party Core restart forgets all members.
Do not delete keys or state by hand; do not use `--force-busy`.

| Layer | Command (owner-run) | Notes |
|---|---|---|
| Checkers provisioning | `cd /opt/avrana-party/current && sudo python3 -m avrana.ops.provision_game checkers --remove` (optionally `--keep-state`) | Leaves the shared `avrana-game@` templates, Party Core's socket unit and the phase 1 identities. Must come before the prepare reverse |
| Native-game preparation | `sudo /opt/avrana-party/current/ops/prepare-native-games --reverse --dry-run`, then `sudo /opt/avrana-party/current/ops/prepare-native-games --reverse` (or with the recorded `/var/backups/avrana-party/native-games-<UTC>`) | Refused while any native game is provisioned. Puts the unit and `party-core.json` back byte for byte. Never restarts Party Core |
| Service-users migration | `ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --reverse /var/backups/avrana-party/service-users-<UTC>"` | Needs its own backup path. Users, groups, `/opt/avrana-arcade` and the venv stay. Do the prepare reverse first |
| nginx site | `sudo cp -a /root/avrana-friend-ready-backups/<stamp>/avrana-party /etc/nginx/sites-available/avrana-party && sudo nginx -t && sudo systemctl reload nginx` | (From step 1's backup, whose file is named `avrana-party`; or the `/root/avrana-party-site.<stamp>` copy from the older runbooks.) Phones fall back as in [party-core-deploy](party-core-deploy.md) |
| Web release only | `sudo bash /home/cody/avrana-party/ops/install-party-web.sh --rollback` | Switches back to the previous of the five kept releases. Pair it with the nginx restore: site file and web build of one commit are one unit |
| Code release (Party and Games) | `ssh -t party "sudo bash /opt/avrana-party/current/ops/deploy.sh --party <BEFORE_PARTY_SHA> --games <BEFORE_GAMES_SHA>"` (laptop form; first add `--dry-run` and read it) | This is the copy of the script that the forward step deployed (the target commit's `ops/deploy.sh`, root-owned under `/opt`). Not `/tmp/avrana-deploy.sh`, which the step-5 power cycle may have cleared, and not the checkout copy, whose content depends on where that checkout is. [deploy](deploy.md) prescribes the checkout path for routine rollbacks; `deploy.sh` does not locate itself, so any copy from the target commit does the same. Pair printed by the failing run and in `/var/backups/avrana-party/deploy-<UTC>/before.json`. Rolls back code and web only: **not** identities, provisioning, config, DNS, TLS or installed units. Going back to a commit that predates `avrana.ops` uses the running release's tooling, and its smoke will fail on `/party/api/status` ([deploy](deploy.md)) |
| Party Core config | `sudo cp -a /root/avrana-friend-ready-backups/<stamp>/party-core.json /etc/avrana-party/party-core.json`, then `python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json` (from the tree that will run) and only then `sudo systemctl restart avrana-party-core` | The restart ends the party. `prepare-native-games --reverse` already restores its own edit |
| Game origin (Session B: DNS record, certificate name, nginx block, `game_origins`) | Its own reverse in `docs/runbooks/game-origin.md` (arrives with AVR-319, not merged); do it after the Checkers removal and before the nginx site restore | Session A changes none of DNS, certificates or NetworkManager. For anything else, restore from the step 1 backup using [party-https](party-https.md) and [network](network.md)  |
After any rollback: `curl -s https://party.avrana.net/party/api/status`, `python3 -m avrana.ops.smoke`, and one phone to Party Home.

## 10. Failure capture, record sheet

**What to record on a failure** (sanitized): the step number, wall-clock time (note the Pi clock offset: it has no RTC), the exact command and exit status,
the deployed SHA pair from `/party/api/status`, the phone model, OS and browser version, a screenshot or screen recording of the phone (not of the Wi-Fi settings
with a password), and the shortest log excerpt that shows the cause.

```bash
sudo journalctl -u avrana-party-core -u avranaparty-games -u avranaparty-arcade -u avrana-game@checkers.service -u avrana-game@checkers.socket -u nginx -u NetworkManager --since "<time>" --no-pager > ~/friend-ready-<step>.journal
sudo journalctl -k -b | grep -iE 'undervoltage|voltage normalis|brcmfmac|wlan0' | tail -40
sudo tail -n 60 /var/log/avrana/pi-throttle.jsonl
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool
```

The journal is persistent on the Pi with caps ([logs-and-retention](logs-and-retention.md)), so it survives the
reboots in this session; copy it before any later reboot anyway. BLUFF's `EVENT {...}` lifecycle lines are the join, rejoin and disconnect record
(no tokens). **Never** attach or paste: Wi-Fi names or passwords, keys or credentials (`/etc/avrana-party/game-keys`, `LoadCredential`), cookies, tickets, device ids,
raw nginx access logs (they carry URLs and client addresses), lease files, the TLS or NetworkManager backups, or a raw journal. Read the excerpt first and redact. Keep raw files on the Pi or laptop, outside Git.

After the session: update [SYSTEM](../SYSTEM.md) only from observed deployment evidence, and write a dated finding under `docs/findings/`. Post the filled sheet to each issue. Leave statuses and acceptance boxes to the owner.

### Record sheet (blank; NOT RUN)

**Run header** (all issues)

| Field | Value |
|---|---|
| Date, place, owner/operator, observer | |
| Party / Games SHA actually deployed (`/party/api/status`) | |
| Linux CI and contract run URLs for those SHAs; final-head review evidence | |
| Backup paths: step 1 / deploy / migration / prepare | |
| Smoke verdict after step 2; `summary.state` | |
| Decisions taken (D1 to D6): value and by whom | |
| Phones: model, OS, browser version, mobile data/VPN/Private DNS/Private Relay state, for each of four | |
| Certificate `notBefore`/`notAfter` and the phone clock at join | |
| Developer interventions: time, who, what | |

**AVR-10: Prove offline cold boot** (one row per acceptance criterion)

| Acceptance criterion | Observation (time, value) | Pass / fail / not measured |
|---|---|---|
| Upstream connectivity intentionally removed (how verified: cable out, `ip route`, ping fails) | | |
| Cold boot with no developer intervention (power-on to AP visible; to Party Home reachable) | | |
| Party AP on the intended interface/profile (`wlan0`, "Avrana Party Internal"; client profile did not win) | | |
| Local DNS and the Party hostname work (`party.avrana.net` -> 10.42.0.1; external name fails) | | |
| Captive/onboarding probes behave as expected (iOS, Android, each probe host) | | |
| Party Home reachable from a phone | | |
| No upstream internet required for core join/navigation | | |
| Power/throttle healthy (`get_throttled` start/end; undervoltage count start/end) | | |
| Evidence and failures recorded (files, step list) | | |
| Added by comment 2026-10-03: clock state and trust at boot; certificate runway; AP power-save state | | |

**AVR-12: Four-phone connectivity**

| Acceptance criterion | Observation | Pass / fail / not measured |
|---|---|---|
| Four phones associate simultaneously (station count; times) | | |
| Each receives working local network configuration (DHCP lease, DNS) | | |
| Each reaches Party Home reliably (attempts, retries, time) | | |
| No device silently falls back to upstream/mobile data (data off; any "no internet" prompt, any cellular use) | | |
| AP stable during ordinary navigation (drops, deauths, `tx_failed`, loss/jitter from `radio-watch`) | | |
| Topology/radio evidence recorded (files kept, not committed) | | |
| Practical device-count limitation documented (observed maximum) | | |

**AVR-261: Checkers on real phones (Session B; blocked on AVR-319)**

| Acceptance criterion | Observation | Pass / fail / not measured |
|---|---|---|
| iOS Safari and Android Chrome: both launch from Party Home, play to a finish, return to Party Home showing the result | | |
| One phone locked or reloaded mid-game returns to the same seat and board | | |
| Host ends a game in progress; both phones return to Party Home | | |
| `sudo python3 -m avrana.ops.boundary --phase 2` reports every rule met with Checkers provisioned (paste the rule lines) | | |
| BLUFF and Gauntlet II still launch and end afterwards | | |
| Run recorded with date, devices, OS/browser versions and the deployed Party and Games commits | | |
| **Session B only; blocked on AVR-319 merged and deployed.** Game-origin facts to record: both names resolve and are trusted on both phones (no warning), the Checkers page ran from `games.avrana.net` and connected (not "Open Checkers from Party Home."), cookie inspection result | | |
| Beyond the issue, worth recording: spectator/late-join, second launch after End | | |

**AVR-27: Four-human offline BLUFF**

| Acceptance criterion | Observation | Pass / fail / not measured |
|---|---|---|
| Cold/offline appliance baseline already proven (AVR-10 and AVR-12 rows above) | | |
| Four phones join Party | | |
| Host selects and launches BLUFF | | |
| All four enter the correct game session | | |
| Private hands/views correct on every phone | | |
| Normal gameplay reaches completion (duration; stalls) | | |
| At least one phone reconnect succeeds (seat, hand, time; lock or reload; autopilot used?) | | |
| Completion returns the Party to a sane post-game state | | |
| No developer intervention on the happy path (count and list) | | |
| First-time players understood objective, basic flow and controls without explanation (quotes; first-timers: how many) | | |
| Failures, latency, UX friction, recovery behavior recorded | | |

## Related

[deploy](deploy.md), [service-users-migration](service-users-migration.md), [prepare-native-games](prepare-native-games.md),
[provision-game](provision-game.md), [party-core-deploy](party-core-deploy.md), [party-https](party-https.md),
[network](network.md), [logs-and-retention](logs-and-retention.md), [games-fork-deploy](games-fork-deploy.md),
[arcade-party-provider](arcade-party-provider.md), `docs/runbooks/game-origin.md` (arrives with AVR-319, not merged), [TESTING](../TESTING.md), [SYSTEM](../SYSTEM.md);
[BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md) (the separate game origin, required by Session B);
[bluff-playtest](bluff-playtest.md) and [bluff-party-reconnect](bluff-party-reconnect.md) are earlier lab procedures,
superseded for this session.
