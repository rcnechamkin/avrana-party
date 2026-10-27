# Owner field-test gate: execution order

Status: **PROPOSED owner-run procedure, NOT RUN on the Pi or on a phone** (2026-10-20).

This page only puts the existing procedures in order. Every command lives in the runbook it links to, and that runbook wins if anything here disagrees. The one exception is the certificate-name gate in step 2, whose checks are written out below.

**Who runs it:** the owner, with sudo, at the Pi. Nothing here is run by an agent.

**Two separate sittings:**
- **Part 1 is the minimum friend-ready gate.** Its GO / NO-GO decides whether four people can use the appliance offline.
- **Part 2 is the disruptive appliance acceptance for AVR-33.** It is a different sitting, never with guests.

A Part 1 GO says nothing about AVR-33: that issue stays open until Part 2 and the other AVR-33 tests are recorded.

**Stop rule:**
- A step passes only when its record sheet says PASS.
- A FAIL stops the sequence at that step. The one exception is an A-19 FAIL in step 3, which does not block the night.
- A FAIL is a finding, not a reason to change the access point, DNS, captive probes or certificates on the spot.
- If the party cannot continue, roll back (step 4).
- The offline-acceptance sheets were written against an older deployed pair (`c59f1c8`). Read their "expected today" against the pair you actually deployed.

---

## Part 1: minimum friend-ready gate (four people, offline)

### 0. Decide the release pair and the game origin (laptop, no Pi changes)

1. **Choose the two commits and record the full SHAs.** Refreshed 2026-10-21 (Sprint 05); re-read both mains on the day.
   - **Party:** `main` is `8de7ef2`. It carries AVR-29 and AVR-33 (#170, #171), the Sprint 03 cross-origin layer
     (#175, #176), the Sprint 04 SDK work (#177-#183) and Leave/Reconnect (#167, merged with the ADR 0011 AVR-580
     amendment). Optional, only if merged first by the owner: #173 (harness evidence only; updated to main at `bdb854b`),
     #186 (guest exit from a game origin), #185 (font).
   - **Games:** `main` is `1dc48d2`. It contains Games #84 (merge `51accf0`), Best Guess (#85, #86) and the Sprint 04 kit
     work (#89-#92). The Party layer (Party #162) and Games #84 are one merge set: both mains carry them.
     - Games #87 (AVR-674) stays out: an experimental optimization of `lan-dodgeball`, a donor title.
     - Sprint 05 PRs are **not** part of this pair unless the owner merges them first. None changes what a phone runs
       on the appliance except Games AVR-675 (dodgeball effects only; a donor title, so it can wait).
   - **Deployed today (the "before" pair):** last recorded as Party `c59f1c8`, Games `a448972` (deployed 2026-10-06,
     [baseline](../findings/2026-10-12-deployed-baseline.md)). Nothing has been deployed since by an agent. Read it again
     with `--status` in step 1; do not assume it.
2. **Accept the local evidence in place of CI.** [deploy](deploy.md) "Before" item 1 asks for green CI lanes, but hosted CI is billing-blocked. Record that you accept local test evidence instead, and name the PR comments that hold it.
3. **Decide whether this test uses native games on the game origin.** That means Checkers or any title listed in Party Core's `game_origins`, served from `https://games.avrana.net` ([game-origin](game-origin.md)).
   - **If yes:** the certificate with both names ([game-origin](game-origin.md) §1) must already exist from an **earlier, separate sitting**. It needs the DNS-challenge path, which is not available offline or mid-test. The certificate-name gate in step 2 then applies. The game origin's DNS, site file and `game_origins` steps ([game-origin](game-origin.md) §2-§4) come after the deploy, with no party running.
   - **If no:** leave `game_origins` empty and run the Party-only test. Party itself does not need the second name.
4. **Check the deploy preconditions.** Work through [deploy](deploy.md) "Before" items 2-8: stage the Games commit if it changes, confirm no live session, run `--status`, check the certificate names, and confirm `nginx -t` passes.

### 1. Preflight and backups (Pi, read-only plus backups)

- Follow [friend-ready-acceptance](friend-ready-acceptance.md) §0-§1:
  - record the deployed "before" pair, which you need for rollback;
  - take the backups;
  - record the certificate runway and the power baseline.
- Copy any journal you need before anything restarts. The journal is volatile until step 3 ([service-recovery](service-recovery.md) §1).

### 2. Deploy (Pi, sudo), with the certificate-name gate when native games need the game origin

**Certificate-name gate (required when step 0.3 is yes).**

`nginx -t` is not this check. It parses the configuration and loads the certificate files. It does not check that a certificate's names cover the `server_name` it is served for. A one-name certificate passes `nginx -t`, and phones then get a name-mismatch error on `games.avrana.net`.

Check the actual subject alternative names on the Pi before the deploy.

1. **Installed certificate.** This is the file both 443 blocks name ([game-origin](game-origin.md) §1 and "Verify"). The directory is root-only:

   ```bash
   C=/etc/avrana-party/tls/current/fullchain.pem
   sudo openssl x509 -in "$C" -noout -ext subjectAltName          # must list DNS:party.avrana.net AND DNS:games.avrana.net
   sudo openssl x509 -in "$C" -noout -checkhost games.avrana.net  # "does match certificate"
   sudo openssl x509 -in "$C" -noout -checkhost party.avrana.net  # "does match certificate"
   sudo openssl x509 -in "$C" -noout -checkend 1814400 && echo "valid for 21+ more days"
   ```

   21 days is the threshold at which `status` and the deploy's smoke report the certificate as expiring (`EXPIRING_DAYS`).

2. **Dry run and real run.**
   - Run the dry run with `sudo` and read its `nginx site: <name> is covered by <cert>` line for both names.
     - Without root it logs `could not check ... root is needed` and checks nothing.
     - A dry run never refuses on certificate names; it only prints a `WARNING`. It can still stop on other preconditions.
   - Run the real run with `--require-cert-names` ([deploy](deploy.md) "Before" item 6 and the options table). A certificate that does not cover a 443 block's `server_name` then makes the deploy exit before anything is installed or stopped.

3. **Served certificate, after the deploy.** This is what a phone receives for each name; no root needed:

   ```bash
   for n in party.avrana.net games.avrana.net; do
     echo "== $n"; openssl s_client -connect 127.0.0.1:443 -servername "$n" </dev/null 2>/dev/null \
       | openssl x509 -noout -subject -ext subjectAltName
   done
   ```

   Both answers must list both names. Then run the verifying `curl` checks in [game-origin](game-origin.md) §3. They use `--resolve` and never `-k`, so a name mismatch fails them.

4. **If any check before the deploy fails:** NO-GO for native games on the game origin.
   - Set step 0.3 to no and leave `game_origins` empty.
   - Deploy **without** `--require-cert-names`. The deploy prints the expected `WARNING: the certificate ... does not cover games.avrana.net` and still deploys ([deploy](deploy.md) "Before" item 6). Party is unaffected.
   - Do not get a new certificate during the field test.

**Deploy block.**
- Do the dry run, then the real run, with explicit SHAs. Follow [friend-ready-acceptance](friend-ready-acceptance.md) §2 and [deploy](deploy.md) "Deploy", using `ops/deploy.sh` taken from the target commit.
- Add `sudo` to the dry run, and `--require-cert-names` to the real run, when the gate applies.
- Pass condition: the smoke check passes and `--status` shows the new last known good.
- A run that dies or exits 2, 3 or 4: follow [deploy](deploy.md) "Which command next" (`--status`, then `--recover`, `--finish` or `--rollback`).

Units the script does not own keep their own runbooks:
- socket and `avrana-game@*`: [party-core-deploy](party-core-deploy.md);
- service users: [service-users-migration](service-users-migration.md);
- the game origin's DNS and `game_origins`: [game-origin](game-origin.md) §2 and §4. The deploy already installed the site file, so §3 is only its verification checks.

Do these only if this field test needs them, with no party running, and the game origin only after the certificate gate passed.

### 3. AVR-29: persistent journal and the reboot proof (Pi, sudo; no party live)

1. **Install.** Follow [logs-and-retention](logs-and-retention.md) "Persistent journal": `preflight`, then `install`, then `verify`.
2. **Reboot proof.** Follow [logs-and-retention](logs-and-retention.md) "Prove it survives a reboot", recorded as **A-19** in [offline-acceptance](offline-acceptance.md): write the marker, do a planned reboot with no phone joined, then read the marker back from `-b -1`.
   - This reboot is not A-17, which is a reboot mid-party.
3. **Record the result on AVR-29.** Only this closes its appliance acceptance.
   - An A-19 FAIL does not block the friend-ready night. Record exactly what was seen, then decide whether to undo the journal install (`install-persistent-journal.sh rollback`, [logs-and-retention](logs-and-retention.md)), and continue.
   - This step is optional for the night. Skip it to keep Part 1 minimal, and do it before Part 2 instead.

### 4. Rollback, known before it is needed (unchanged procedures)

- **Code pair:** `ops/deploy.sh --rollback` returns to the last known good ([deploy](deploy.md) "After a failed smoke").
- **Failed or dead deploy:** follow [deploy](deploy.md) "Which command next".
- **Explicit before-pair:** use [friend-ready-acceptance](friend-ready-acceptance.md) §9, in reverse order of installation and with no session live.
- **Journal only:** `install-persistent-journal.sh rollback` ([logs-and-retention](logs-and-retention.md)).
- **Game origin:** its own reverse in [game-origin](game-origin.md) "Reverse, in this order".
- **After any rollback** that changes the site file or the certificate, repeat the served-certificate check in step 2.3 if the game origin was live.
- **Optional rehearsal:** run one `--rollback --dry-run`.

### 5. QR onboarding (truly offline, upstream unplugged)

- Print the card, then do the real-phone check in [join-card](join-card.md), steps 1-10 and 12.
  - Step 11 is lab-only.
  - Steps 5-6 deliberately turn mobile data and VPN on. Do them on a spare phone, not the four used for the night.
  - Use at least one iPhone with Safari and one Android with Chrome.
  - Start every phone with the network forgotten.
- Record the per-device results on AVR-11 and AVR-295.

### 6. Four-phone night: the GO / NO-GO

- Run [friend-ready-owner-checklist](friend-ready-owner-checklist.md): four phones, offline, BLUFF to the end with no help. **Its GO / NO-GO is the Part 1 result.**
- Its row 1 is a clean shutdown and cold boot, the AVR-10 check. It is neither an AVR-33 recovery test nor A-17 evidence.

### 7. Extras for what was deployed (recorded, not part of the GO / NO-GO)

- **Party layer (Party #162 with Games #84, both in the step 0 pair):** run the host-control and lifecycle checks in [party-layer-device-validation](party-layer-device-validation.md) §6, and the Reconnect checks in §7, on its three phones (A, B, C). If the deployed pair lacks either half, record NOT RUN.
  - Record Limited Mode (§7.5-§7.6) as NOT SUPPORTED where friend-ready D6 keeps it out of scope.
  - **If #167 is deployed:** Leave Party has no step there. Its record is the #167 PR evidence until a phone check is added.

### 8. After Part 1

- Re-check health: `curl -s https://party.avrana.net/party/api/status`, then `python3 -m avrana.ops.smoke`, then one phone to Party Home. These are the same checks as the "After any rollback" line in [friend-ready-acceptance](friend-ready-acceptance.md) §9.
- File every FAIL as an issue with its evidence file. Do not leave a changed configuration behind without recording it.

---

## Part 2: AVR-33 recovery and power interruption (separate sitting, disruptive)

These tests stop, kill, reboot and unplug the appliance on purpose.

**When to run them:**
- after Part 1's deploy, on a day without guests, or after the four-phone night;
- with [service-recovery](service-recovery.md) open;
- with **fresh backups taken before A-18** ([friend-ready-acceptance](friend-ready-acceptance.md) §1, as the offline-acceptance run header requires).

They are **not** part of the friend-ready GO / NO-GO, and **AVR-33 stays open until their results are recorded**, whatever Part 1 shows.

Use the record sheets in [offline-acceptance](offline-acceptance.md), in this order, least disruptive first. Each test's own Expect / Pass wording is the criterion.

| Test | What it does |
|---|---|
| A-16 | Restarts each service one at a time: Games, Arcade, nginx, then Party Core (never NetworkManager) |
| A-25 | Kills the Games service (`avranaparty-games`) during a four-phone BLUFF round |
| A-17 | Full reboot mid-party |
| A-18 | Power interruption: idle, mid-game, during a join (the only deliberately unclean test) |

- **Also AVR-33, not in this sitting.** offline-acceptance marks A-26 (Games bundle staging, operations), B-03 (native game process failure) and B-04 (restart the native units and Party Core's socket) as serving AVR-33.
  - A-26 is not disruptive and can run in any sitting.
  - B-03 and B-04 need Checkers provisioned, which means prepare-native-games and the game origin.
  - All three stay **NOT RUN** and open until recorded; scheduling them is the owner's decision.
- `close_lost_game` stays **off**. C-08 is a separate owner decision and is not part of this gate.
- AVR-33's "Remaining scope" checklist in Linear is the acceptance list. Tick only what a recorded PASS shows. The Party Core evidence from 2026-09-29 already stands; do not rerun it as if unknown.


---

## Appendix: the release candidate after Sprint 05 (2026-10-21)

**Which owner gate each physical test needs.** Each gate is its own Linear issue and gets its own record. None is
closed by source tests, Chromium emulation, a simulator, or a successful install rehearsal.

| Gate | What it proves | On the deployed pair (`c59f1c8`/`a448972`, no deploy) | Needs the release pair above |
|---|---|---|---|
| AVR-10 | offline cold boot | yes (A-01 to A-26 run as "A: no deploy") | to prove it for the new pair |
| AVR-12 | four phones connect | yes | to prove it for the new pair |
| AVR-27 | four-human offline BLUFF | yes, for the old console | for the ADR 0011 launch authority, Leave/Reconnect (#167) and Host succession |
| AVR-261 | Checkers on real phones over the Pi's Wi-Fi | yes, if Checkers is installed today | if native games run on the game origin (step 0.3 yes) |
| AVR-139 | cached `.avrgame` relaunch on real phones | no: needs a rights-cleared package installed | yes, plus an owner-approved install |
| AVR-295 | real-phone and accessibility pass of the shell-to-BLUFF journey | no: the redesigned shell is not deployed | yes |
| AVR-301 | Wi-Fi latency with 1 to 10 clients | yes (an AP measurement) | to compare the pairs |

**Prerequisites before any deploy** (each is a separate owner approval):
- **Service users (AVR-256).** [service-users-migration](service-users-migration.md). The Linux test container has no
  `cody` user, so the deploy-script unit tests are not evidence here.
- **Game origin (AVR-319).** A certificate with both names, from an earlier sitting; then DNS, the nginx site and
  `game_origins` after the deploy (step 0.3, [game-origin](game-origin.md)). BLUFF and EXPO still run on the Party
  origin in nginx. Moving them is an owner decision (Sprint 03 finding §5).
- **Native game provisioning (AVR-304)** and, for any Node package, the pinned Node runtime (`avrana.ops.node_runtime`;
  not installed by any agent).
- **Backups, health and rollback.** Steps 1 and 4 above, unchanged.

**Approved versus experimental on 2026-10-21:**
- Approved and on main: everything listed under the release pair.
- Owner-gated, open: Party #186, #185, #173, #174 (this page), #178 (visualization only); Games #93 (font).
- Experimental, kept off the appliance: Games #87, the AVR-512 Tanks reproduction, every Sprint 05 SDK change
  (the kit's navigation conformance, the harness changes). Those change development tools, not what the appliance runs.
- Physical validation that remains: every gate above, plus phones for the Party layer, Leave/Reconnect, and guest exit
  if #186 merges.

**Do not touch the appliance without the owner.** This appendix is planning only. It deploys nothing, changes no
networking and records no acceptance.
