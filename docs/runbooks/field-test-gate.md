# Owner field-test gate: execution order

This page only puts the existing procedures in order for one supervised field test. Every command lives in the runbook it links to, and that runbook wins if anything here disagrees.

**Who runs it:** the owner, with sudo, at the Pi. Nothing here is run by an agent. No step is passed until its record sheet says PASS.

**Stop rule:** a FAIL stops the sequence at that step. It is a finding, not a reason to change the access point, DNS, captive probes or certificates on the spot. Roll back (step 4) if the party cannot continue.

## 0. Decide the release pair (laptop, no Pi changes)

1. **Choose the two commits to deploy.**
   - Party `main` (today `c903346`, which carries AVR-29 and AVR-33). It also carries #167 (Leave and Reconnect) and #173 (harness evidence only) if you merge them first.
   - Games `main` (today `4acc5ae`). It also carries #87 (realtime input coalescing) if you merge it first.
   - Record the full SHAs.
2. **Accept the local evidence in place of CI.** [deploy](deploy.md) "Before" item 1 asks for green CI lanes, but hosted CI is billing-blocked. Record that you accept local test evidence instead, and name the PR comments that hold it.
3. **Check the deploy preconditions.** Work through [deploy](deploy.md) "Before" items 2-8: stage the Games commit, confirm no live session, run `--status`, and check the certificate names and that `nginx -t` passes.

## 1. Preflight and backups (Pi, read-only plus backups)

- Follow [friend-ready-acceptance](friend-ready-acceptance.md) §0-§1:
  - record the deployed "before" pair, which you need for rollback;
  - take the backups;
  - record the certificate runway and the power baseline.
- Copy any journal you need before anything restarts. The journal is volatile until step 3 ([service-recovery](service-recovery.md) §1).

## 2. Deploy (Pi, sudo)

- Do the dry run, then the real run, with explicit SHAs. Follow [friend-ready-acceptance](friend-ready-acceptance.md) §2 and [deploy](deploy.md) "Deploy", using `ops/deploy.sh` taken from the target commit.
- Pass condition: the smoke check passes and `--status` shows the new last known good.
- Units the script does not own keep their own runbooks:
  - socket and `avrana-game@*`: [party-core-deploy](party-core-deploy.md);
  - service users: [service-users-migration](service-users-migration.md);
  - game origin: [game-origin](game-origin.md).
  - Do these only if this field test needs them.

## 3. AVR-29: persistent journal, then the reboot proof (Pi, sudo)

1. Run the install. Follow [logs-and-retention](logs-and-retention.md) "Persistent journal": `preflight`, then `install`, then `verify`.
2. Run the reboot proof. Follow [logs-and-retention](logs-and-retention.md) "Prove it survives a reboot", recorded as **A-19** in [offline-acceptance](offline-acceptance.md): write the marker, reboot, then read the marker back from `-b -1`.
3. Record the result on AVR-29. Only this closes AVR-29's appliance acceptance.

## 4. Rollback, known before it is needed

- **Code pair:** `ops/deploy.sh --rollback` returns to the last known good ([deploy](deploy.md) "After a failed smoke").
- **Explicit before-pair:** use [friend-ready-acceptance](friend-ready-acceptance.md) §9, in reverse order of installation and with no session live.
- **Journal only:** `install-persistent-journal.sh rollback` ([logs-and-retention](logs-and-retention.md)).
- **Optional rehearsal:** run one `--rollback --dry-run`.

## 5. AVR-33: recovery checks on the appliance (Pi; disruptive, do them before the phones session)

Use the record sheets in [offline-acceptance](offline-acceptance.md). Recovery steps are in [service-recovery](service-recovery.md).

| Test | What |
|---|---|
| A-16 | Restart each service |
| A-25 | Game process failure (LAN Games and BLUFF) |
| A-17 | Full reboot mid-party |
| A-18 | Power interruption: idle, mid-game, during a join |

- `close_lost_game` stays **off**. C-08 is a separate owner decision and is not part of this gate.
- Record the results on AVR-33. Only these close its appliance acceptance.

## 6. QR onboarding (truly offline, upstream unplugged)

- Print the card, then do the real-phone check in [join-card](join-card.md), steps 1-12.
  - Use at least one iPhone with Safari and one Android with Chrome.
  - Start every phone with the network forgotten.
- Record the per-device results on AVR-11 and AVR-295.

## 7. Actual phone testing

1. Run the one-night pass in [friend-ready-owner-checklist](friend-ready-owner-checklist.md): four phones, offline, BLUFF to the end with no help. Its GO / NO-GO is the gate result.
2. If #167 is deployed, also run [party-layer-device-validation](party-layer-device-validation.md) §6-§7 (host controls, Leave, Reconnect, Limited Mode) on two phones.
3. If Games #87 is deployed, run the realtime game with 2, 4 and 6 phones. Follow [performance-measurement](performance-measurement.md) §2, step 4: Games CPU on the Pi, per-station airtime, and frame pacing.
   - The laptop figures do not stand in for this.
   - Dodgeball's resting-ball `bounce` traffic is AVR-675 and is out of scope here.

## 8. After

- Re-check health: `curl -s https://party.avrana.net/party/api/status`, then `python3 -m avrana.ops.smoke`, then one phone to Party Home ([friend-ready-acceptance](friend-ready-acceptance.md) §9 "After any rollback" lists the same checks).
- File every FAIL as an issue with its evidence file. Do not leave a changed configuration behind without recording it.
