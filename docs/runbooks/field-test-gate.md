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

1. **Choose the two commits and record the full SHAs.**
   - **Party:** `main` (today `c903346`, which carries AVR-29 and AVR-33), plus #167 (Leave and Reconnect) and #173 (harness evidence only) if you merge them first.
   - **Games: a commit that contains Games #84** (merge `51accf0`), which is Games `main` today (`4acc5ae`).
     - Games #87 (AVR-674) is held as an experimental optimization and is not part of this pair. It only changes `lan-dodgeball`, a donor title rather than a supported Party game.
     - Party `main` carries the Party layer, Party #162, merged 2026-10-16. Its Games half is #84, and the two must be deployed together as one merge set ([party-layer-device-validation](party-layer-device-validation.md)).
     - The checklist's "Games stays `bd7e01d`" predates #162. `bd7e01d` does not contain #84, so do not pair it with today's Party `main`.
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
