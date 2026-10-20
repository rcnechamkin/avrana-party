# Owner field-test gate: execution order

This page only puts the existing procedures in order. Every command lives in the runbook it links to, and that runbook wins if anything here disagrees. The one exception is the certificate-name gate in step 2, whose checks are written out below.

**Who runs it:** the owner, with sudo, at the Pi. Nothing here is run by an agent. A step passes only when its record sheet says PASS.

**Two separate sittings:**
- **Part 1 is the minimum friend-ready gate.** Its GO / NO-GO decides whether four people can use the appliance offline.
- **Part 2 is the disruptive appliance acceptance for AVR-33.** It is a different sitting, never with guests.

A Part 1 GO says nothing about AVR-33: that issue stays open until Part 2 is recorded.

**Stop rule:**
- A FAIL stops the sequence at that step. It is a finding, not a reason to change the access point, DNS, captive probes or certificates on the spot.
- If the party cannot continue, roll back (step 4).

---

## Part 1: minimum friend-ready gate (four people, offline)

### 0. Decide the release pair (laptop, no Pi changes)

1. **Choose the two commits.**
   - Party `main` (today `c903346`, which carries AVR-29 and AVR-33), plus #167 (Leave and Reconnect) and #173 (harness evidence only) if you merge them first.
   - Games `main` (today `4acc5ae`), plus #87 (realtime input coalescing) if you merge it first.
   - Record the full SHAs.
2. **Accept the local evidence in place of CI.** [deploy](deploy.md) "Before" item 1 asks for green CI lanes, but hosted CI is billing-blocked. Record that you accept local test evidence instead, and name the PR comments that hold it.
3. **Decide whether this test uses native games on the game origin.** That means Checkers or any title listed in Party Core's `game_origins`, served from `https://games.avrana.net` ([game-origin](game-origin.md)). If yes, the certificate-name gate in step 2 applies. If no, leave `game_origins` empty and run the Party-only test. Party itself does not need the second name.
4. **Check the deploy preconditions.** Work through [deploy](deploy.md) "Before" items 2-8: stage the Games commit, confirm no live session, run `--status`, check the certificate names, and confirm `nginx -t` passes.

### 1. Preflight and backups (Pi, read-only plus backups)

- Follow [friend-ready-acceptance](friend-ready-acceptance.md) §0-§1:
  - record the deployed "before" pair, which you need for rollback;
  - take the backups;
  - record the certificate runway and the power baseline.
- Copy any journal you need before anything restarts. The journal is volatile until step 3 ([service-recovery](service-recovery.md) §1).

### 2. Deploy (Pi, sudo), with the certificate-name gate when native games need the game origin

**Certificate-name gate (required when step 0.3 is yes).**

`nginx -t` is not this check. It parses the configuration and loads the certificate files. It does not check that a certificate's names cover the `server_name` it is served for. A one-name certificate passes `nginx -t`, and phones then get a name-mismatch error on `games.avrana.net`.

Check the actual subject alternative names on the Pi before the deploy, then deploy with refusal on.

1. **Installed certificate** (the file the 443 blocks name; [game-origin](game-origin.md) §1 and "Verify"):

   ```bash
   C=/etc/avrana-party/tls/current/fullchain.pem
   openssl x509 -in "$C" -noout -ext subjectAltName      # must list DNS:party.avrana.net AND DNS:games.avrana.net
   openssl x509 -in "$C" -noout -checkhost games.avrana.net    # "does match"
   openssl x509 -in "$C" -noout -checkhost party.avrana.net    # "does match"
   openssl x509 -in "$C" -noout -checkend 1209600 && echo "valid for 14 more days"   # record the runway, not just "valid"
   ```

2. **Deploy with refusal on.** Add `--require-cert-names` to the dry run and the real run in step 2 below ([deploy](deploy.md) "Before" item 6 and the options table). With the flag, a certificate that does not cover a 443 block's `server_name` makes the deploy exit before anything is installed or stopped. Without it, the deploy only warns (`nginx_site.cert_name_mismatch`).

3. **Served certificate, after the deploy.** This is what a phone receives for each name:

   ```bash
   for n in party.avrana.net games.avrana.net; do
     echo "== $n"; openssl s_client -connect 127.0.0.1:443 -servername "$n" </dev/null 2>/dev/null \
       | openssl x509 -noout -subject -ext subjectAltName
   done
   ```

   Both answers must list both names. Then run the verifying `curl` checks in [game-origin](game-origin.md) §3. They use `--resolve` and never `-k`, so a name mismatch fails them.

4. **If any check fails:** NO-GO for native games on the game origin.
   - Do not add the `game_origins` entry, or remove it.
   - The Party-only test may continue.
   - The fix is [game-origin](game-origin.md) §1, a new certificate with both names. It needs the DNS-challenge path and is not an on-the-spot change during the field test.

**Deploy.**
- Do the dry run, then the real run, with explicit SHAs. Follow [friend-ready-acceptance](friend-ready-acceptance.md) §2 and [deploy](deploy.md) "Deploy", using `ops/deploy.sh` taken from the target commit.
- Add `--require-cert-names` when the gate applies.
- Pass condition: the smoke check passes and `--status` shows the new last known good.

Units the script does not own keep their own runbooks:
- socket and `avrana-game@*`: [party-core-deploy](party-core-deploy.md);
- service users: [service-users-migration](service-users-migration.md);
- game origin: [game-origin](game-origin.md).

Do these only if this field test needs them. The game origin comes only after the certificate gate passes.

### 3. AVR-29: persistent journal and the reboot proof (Pi, sudo; no party live)

1. **Install.** Follow [logs-and-retention](logs-and-retention.md) "Persistent journal": `preflight`, then `install`, then `verify`.
2. **Reboot proof.** Follow [logs-and-retention](logs-and-retention.md) "Prove it survives a reboot", recorded as **A-19** in [offline-acceptance](offline-acceptance.md): write the marker, do a planned reboot with no phone joined, then read the marker back from `-b -1`.
3. **Record the result on AVR-29.** Only this closes its appliance acceptance. An A-19 FAIL does not block the friend-ready night: undo the journal install only (`install-persistent-journal.sh rollback`), record the result, and continue.

### 4. Rollback, known before it is needed (unchanged procedures)

- **Code pair:** `ops/deploy.sh --rollback` returns to the last known good ([deploy](deploy.md) "After a failed smoke").
- **Explicit before-pair:** use [friend-ready-acceptance](friend-ready-acceptance.md) §9, in reverse order of installation and with no session live.
- **Journal only:** `install-persistent-journal.sh rollback` ([logs-and-retention](logs-and-retention.md)).
- **Game origin:** its own reverse in [game-origin](game-origin.md) "Reverse, in this order".
- **After any rollback** that changes the site file or the certificate, repeat the served-certificate check in step 2.3 if the game origin was live.
- **Optional rehearsal:** run one `--rollback --dry-run`.

### 5. QR onboarding (truly offline, upstream unplugged)

- Print the card, then do the real-phone check in [join-card](join-card.md), steps 1-12.
  - Use at least one iPhone with Safari and one Android with Chrome.
  - Start every phone with the network forgotten.
- Record the per-device results on AVR-11 and AVR-295.

### 6. Four-phone night: the GO / NO-GO

- Run [friend-ready-owner-checklist](friend-ready-owner-checklist.md): four phones, offline, BLUFF to the end with no help. **Its GO / NO-GO is the Part 1 result.**
- Its cold boot (row 1) is the AVR-10 check. It is not one of the AVR-33 recovery tests.

### 7. Extras for what was deployed (recorded, not part of the GO / NO-GO)

- **If #167 is deployed:** run [party-layer-device-validation](party-layer-device-validation.md) §6-§7 (host controls, Leave, Reconnect, Limited Mode) on two phones.
- **If Games #87 is deployed:** run the realtime game with 2, 4 and 6 phones. Follow [performance-measurement](performance-measurement.md) §2, step 4: Games CPU on the Pi, per-station airtime, and frame pacing.
  - Laptop figures do not stand in for this.
  - Dodgeball's resting-ball `bounce` traffic is AVR-675, out of scope.

### 8. After Part 1

- Re-check health: `curl -s https://party.avrana.net/party/api/status`, then `python3 -m avrana.ops.smoke`, then one phone to Party Home ([friend-ready-acceptance](friend-ready-acceptance.md) §9 "After any rollback" lists the same checks).
- File every FAIL as an issue with its evidence file. Do not leave a changed configuration behind without recording it.

---

## Part 2: AVR-33 recovery and power interruption (separate sitting, disruptive)

These tests stop, kill, reboot and unplug the appliance on purpose.

**When to run them:**
- after Part 1's deploy, on a day without guests, or after the four-phone night;
- with the backups and rollback from steps 1 and 4 still at hand;
- with [service-recovery](service-recovery.md) open.

They are **not** part of the friend-ready GO / NO-GO, and **AVR-33 stays open until their results are recorded**, whatever Part 1 shows.

Use the record sheets in [offline-acceptance](offline-acceptance.md), in this order, least disruptive first:

| Test | What | AVR-33 scope it answers |
|---|---|---|
| A-16 | Restart each service | Games, Arcade and nginx restart; one service never strands another |
| A-25 | Game process failure (LAN Games and BLUFF) | Games crash recovery; health shows a failed recovery |
| A-17 | Full reboot mid-party | Every service comes back unaided |
| A-18 | Power interruption: idle, mid-game, during a join | Recovery after power loss; repeated failures stay bounded |

- `close_lost_game` stays **off**. C-08 is a separate owner decision and is not part of this gate.
- AVR-33's "Remaining scope" checklist is the acceptance list. Tick only what a recorded PASS shows. The Party Core evidence from 2026-09-29 already stands; do not rerun it as if unknown.
