# Runbook: logs, telemetry and their bounds (AVR-30)

**Correction 2026-10-12 (AVR-29): the journal is volatile, not persistent.** This runbook said the journal was
persistent because `/var/log/journal` existed on 2026-09-29. The directory existing does not make journald use
it. Read-only on 2026-10-12 ([baseline](../findings/2026-10-12-deployed-baseline.md)): the effective setting is
`Storage=volatile`, from the Raspberry Pi OS drop-in `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`;
`/etc/systemd/journald.conf.d/avrana.conf` (this repository's `deploy/journald/avrana-journald.conf`) sets sizes
and, deliberately, does not set `Storage`; `journalctl --list-boots` shows one boot; `--disk-usage` is 11.4M; the
live journal is under `/run/log/journal`. So logs are lost at every reboot, and `SYSTEM.md` ("volatile") was
right. The 2026-09-29 reading "24.3 MB" stands as a size, but the word "persistent" next to it was an inference
from the directory and is withdrawn; what the setting was on 2026-09-29 cannot be recovered from the record.
Whether rsyslog writes persistent copies under `/var/log` (`ForwardToSyslog=yes`) has not been checked. A
deliberate reboot proof (marker line, reboot, read it back) is **NOT RUN**: it is test A-19 in
[offline-acceptance](offline-acceptance.md) and is expected to fail until the setting below is decided.

**Change in source 2026-10-19 (AVR-29), NOT installed on the Pi:** `deploy/journald/avrana-journald.conf` now
sets `Storage=persistent` with the same size bounds, and `deploy/journald/install-persistent-journal.sh` installs,
verifies and rolls it back ("Persistent journal" below). Until the owner installs it and the reboot proof passes,
the appliance's journal is still volatile.

Every file the appliance keeps writing has a known bound. Measured on the Pi on 2026-09-29, read-only:
- 117 GB card, 8% used;
- journal 24.3 MB (labelled "persistent" at the time: see the correction above; it was volatile);
- `/var/log/avrana` 4.1 MB;
- `/var/log/nginx` 1.1 MB;
- `arcade/runtime` 3.1 MB;
- games `data/` 12 KB.

The card is nowhere near full. The bounds exist so that it never gets there over months of
parties, or on a smaller card.

## Inventory

| Source | Writer | Bound | Status |
|---|---|---|---|
| systemd journal (all Avrana services: `avranaparty-games`, `avranaparty-arcade`, `avrana-party-core`, the telemetry timer) | journald | `deploy/journald/avrana-journald.conf`: 256 MB on disk, 1 GB always kept free, 64 MB in RAM, one file per week | size bounds LIVE since 2026-09-29 (effective config verified); **volatile**: lost at reboot (observed 2026-10-12). `Storage=persistent` in source (AVR-29), not installed |
| `/var/log/nginx/*.log` | nginx | Debian's `/etc/logrotate.d/nginx`: daily, 14 generations, compressed | LIVE, unchanged (read 2026-09-29) |
| `/var/log/avrana/pi-throttle.jsonl` | `pi-throttle-check.timer`, one line a minute (~0.4 MB/day) | `telemetry/avrana-telemetry.logrotate`: weekly or past 10 MB, 8 compressed generations (about two months, well under 20 MB) | LIVE since 2026-09-29 (`logrotate -d` parses it as intended) |
| `/var/log/avrana/baseline.jsonl` and other hand-made captures | the owner, by hand | none on purpose: they're measurement evidence | Never rotated or expired automatically |
| `arcade/runtime/emulator.log` | `arcade/stream.py` | 20 MB, then the last 20 MB kept as `.1` (under ~45 MB) | LIVE |
| `arcade/runtime/client-stats.jsonl` | `arcade/stream.py` (per-second phone stats) | 20 MB, then rotated to `.1` (under ~40 MB). Before AVR-30 it stopped recording once full, dropping the newest stats | LIVE since the 2026-09-29 11:37 arcade restart |
| `arcade/runtime/webrtc-stats-sample1.txt`, `…8.txt` | `arcade/stream.py` | two fixed files, overwritten | LIVE |
| `arcade/runtime/pulse.log` | `arcade/with-audio.sh` | truncated at every arcade start; PulseAudio writes little | LIVE |
| games `data/chatmedia/` | `core/chatmedia.py` (chat photos and GIFs) | 400 files **and** 256 MB total, oldest pruned first. Before AVR-30 only the count was capped, which allowed ~6.4 GB of 16 MB GIFs | LIVE (games `eeedb19`, 2026-09-29) |
| games `data/avatars/` | `core/avatars.py` | one 256 px WebP (tens of KB) per player identity, replaced on update: bounded by use. Not pruned, because that would delete active players' pictures | LIVE |
| `/var/lib/avrana-party-core/devices.json` | Party Core (after AVR-51) | one short hashed entry per device that ever joined: bounded by use | LIVE since 2026-09-29 |
| `~/avrana-captures/*.jsonl` | `arcade/capture-load.py`, run by hand | none on purpose: manual evidence | manual |

nginx logs and the journal are the only sources that grow with traffic. Everything else is either
capped by count or size, or grows only when someone deliberately makes new evidence.

## Owner steps (Pi, sudo)

```bash
# telemetry rotation (idempotent: reinstalls files and re-enables the timer)
sudo bash /home/cody/avrana-party/telemetry/install-pi-throttle-check.sh
sudo logrotate -d /etc/logrotate.d/avrana-telemetry          # dry run: shows the plan, changes nothing
```

The journal (caps and persistence) is installed by its own script: "Persistent journal" below. Both need the
production checkout to contain the change first (a fast-forward, as usual).

## Persistent journal (AVR-29)

Status: **in source, NOT installed; reboot persistence NOT RUN on the Pi** (2026-10-19). Owner-run, with sudo,
not during a party. The script never deletes a log and never touches the Raspberry Pi OS files.

**What changes.** One key, `Storage=persistent`, in `/etc/systemd/journald.conf.d/avrana.conf`; the bounds stay
`SystemMaxUse=256M`, `SystemKeepFree=1G`, `RuntimeMaxUse=64M`, `MaxFileSec=1week`. Raspberry Pi OS ships
`/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` (`Storage=volatile`). journald reads the drop-ins
of `/usr/lib`, `/run` and `/etc` as one list sorted by file name, and a later file wins for a key it sets;
`avrana.conf` sorts after `40-rpi-…` (letters after digits), so it wins. The script does not trust that
reasoning: it reads the effective value from `systemd-analyze cat-config systemd/journald.conf`, systemd's own
ordering, and fails if any later drop-in sets `Storage` again.

**Bounded growth.** On disk the journal never exceeds 256 MB and never leaves less than 1 GB free; journald
deletes its oldest files to stay inside both. Each file covers at most a week. Before journald reaches `/var`
early in boot it keeps at most 64 MB in RAM.

**The SD-card writes.** Persistence moves the journal from RAM to the card. The size bound caps the space, not
the writes, so the cost is the log volume itself. On 2026-10-12 one boot of about 53 hours, mostly idle, held
11.4 MB: roughly 5 MB a day, more during parties. journald also rewrites its own indexes and syncs at most every
5 minutes (immediately for critical messages). That is an estimate, not a measurement, and small next to a
card's write endurance. To measure it, read the seventh field of `/sys/block/mmcblk0/stat` (512-byte sectors
written) a day apart, with and without the change. A power cut can lose the last few minutes of ordinary
messages; critical ones are synced at once. With `ForwardToSyslog=yes`, an installed and running rsyslog would
write a second copy under `/var/log`; preflight says whether rsyslog is active.

```bash
cd /home/cody/avrana-party                         # the production checkout, fast-forwarded to this change
bash deploy/journald/install-persistent-journal.sh preflight       # read only: drop-in order, effective Storage, disk
sudo bash deploy/journald/install-persistent-journal.sh install    # backup, install, restart journald, flush, verify
bash deploy/journald/install-persistent-journal.sh verify          # read only; run any time
```

- **preflight** lists the drop-ins in the order systemd applies them, the effective `Storage` and `SystemMaxUse`,
  whether the installed file matches this release, free space, journal size and whether rsyslog is active.
  Expected today: `effective Storage: volatile`.
- **install** keeps a backup in `/var/backups/avrana-party/journald-<time>/` (the old `avrana.conf`, or a note
  that there was none), replaces the file atomically, restarts journald and runs `journalctl --flush` so this
  boot's journal moves to `/var/log/journal` now. Then it verifies. If verification fails it puts the previous
  file back and restarts journald again (exit 1). A second run with nothing to change does not restart journald.
- **verify** passes only if the effective `Storage` is `persistent`, the bounds are the effective values, the
  installed file matches this release and `/var/log/journal/<machine-id>/system.journal` exists.
- **Rollback:** `sudo bash deploy/journald/install-persistent-journal.sh rollback` restores the most recent backup
  (or `rollback /var/backups/avrana-party/journald-<time>` a chosen one) and restarts journald: volatile again.
  The files already under `/var/log/journal` stay (bounded, still readable). Removing them is a separate,
  deliberate step: `sudo journalctl --vacuum-size=1M`, then delete `/var/log/journal/<machine-id>` by hand.

### Prove it survives a reboot (owner, NOT RUN)

This is A-19 in [offline-acceptance](offline-acceptance.md). Only this, on the Pi, proves AVR-29; the
repository tests prove the script and the precedence on a simulated host, never a reboot.

```bash
# before: after install and a passing verify
journalctl --list-boots | tail -n 2
logger -t avrana-journal "AVR-29 marker before reboot $(date -u +%FT%TZ)"
journalctl -t avrana-journal -n 1 --no-pager        # the marker is in the journal
sudo reboot
# after it is back
journalctl --list-boots | tail -n 3                 # the previous boot is listed (index -1)
journalctl -b -1 -t avrana-journal --no-pager       # the marker, from the previous boot
journalctl -b -1 -u avrana-party-core -n 5 --no-pager
journalctl --disk-usage                              # within 256M
bash deploy/journald/install-persistent-journal.sh verify
```

PASS: the previous boot is listed, the marker and the previous boot's service lines are there, the disk usage is
within the bound and verify passes. FAIL: any of them missing; record exactly what was seen, then decide whether
to roll back. Record the result on AVR-29 and in A-19 with the date and the Party commit.

The arcade's stats-log rotation goes live when the arcade next restarts on the new code.

## Disk pressure: what happens if the card does fill

- **journald** stops writing before it would eat the last 1 GB (`SystemKeepFree`), then drops
  its oldest files. It never fills the card by itself.
- **logrotate** runs daily (`logrotate.timer`). Rotation only compresses or deletes old
  generations, so it frees space.
- **Arcade:**
  - `emulator.log` and `client-stats.jsonl` rotate before the card fills, so they don't add pressure.
  - If the card is already full for another reason, the per-second stats write fails inside that
    phone's session. Recovery is the arcade's existing restart path.
- **Games server:**
  - Chat uploads fail with an error. Play continues, because game state is in memory.
  - Avatar uploads fail the same way.
- **Party Core:** the device store is written atomically, so a failed write leaves the previous
  store intact. The party itself is memory-only.
- **What to do:**
  1. Run `df -h /`.
  2. Run `du -sh /var/log/* /home/cody/*/arcade/runtime /home/cody/avrana-party-games/data`.
  3. Run `sudo journalctl --vacuum-size=100M` if needed.
  4. Look for an unexpected large file before deleting anything.

## Tests

- `tests/unit/test_log_bounds.py`:
  - the telemetry rule covers exactly the sampler's output file;
  - the installer installs the rule;
  - the journald caps are explicit, with `Storage=persistent` (AVR-29);
  - this inventory names every source.
  - The real `logrotate` runs in Linux CI: past 10 MB the file rotates, and the sampler's `>>`
    appends to the fresh file; a small file is left alone.
- `tests/unit/test_persistent_journal.py` (AVR-29): the drop-in, its name sorting after the Raspberry Pi OS
  drop-in, and the installer on a simulated host (preflight, install, idempotent second run, a failed
  verification restored, rollback, a later drop-in caught). Linux uses the real `systemd-analyze`.
- `tests/unit/test_arcade_stream.py` `ClientStatsLog`: the stats log rotates, the newest record
  is kept, and there are never more than two files.
- games `tests/test_chat.py`: chat media is capped by bytes, the newest files are kept, and the
  file just saved is never pruned.
