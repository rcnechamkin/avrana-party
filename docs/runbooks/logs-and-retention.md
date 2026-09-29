# Runbook: logs, telemetry and their bounds (AVR-30)

Every file the appliance keeps writing has a known bound. Measured on the Pi on 2026-09-29, read-only:
- 117 GB card, 8% used;
- journal 24.3 MB, persistent (`/var/log/journal` exists);
- `/var/log/avrana` 4.1 MB;
- `/var/log/nginx` 1.1 MB;
- `arcade/runtime` 3.1 MB;
- games `data/` 12 KB.

The card is nowhere near full. The bounds exist so that it never gets there over months of
parties, or on a smaller card.

## Inventory

| Source | Writer | Bound | Status |
|---|---|---|---|
| systemd journal (all Avrana services: `avranaparty-games`, `avranaparty-arcade`, `avrana-party-core`, the telemetry timer) | journald | `deploy/journald/avrana-journald.conf`: 256 MB on disk, 1 GB always kept free, 64 MB in RAM, one file per week | LIVE since 2026-09-29 (effective config verified) |
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

# journal caps
sudo install -D -m 0644 /home/cody/avrana-party/deploy/journald/avrana-journald.conf /etc/systemd/journald.conf.d/avrana.conf
sudo systemctl restart systemd-journald
journalctl --disk-usage
```

Both steps need the production checkout to contain this change first (a fast-forward, as usual).
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
  - the journald caps are explicit and leave `Storage=` alone;
  - this inventory names every source.
  - The real `logrotate` runs in Linux CI: past 10 MB the file rotates, and the sampler's `>>`
    appends to the fresh file; a small file is left alone.
- `tests/unit/test_arcade_stream.py` `ClientStatsLog`: the stats log rotates, the newest record
  is kept, and there are never more than two files.
- games `tests/test_chat.py`: chat media is capped by bytes, the newest files are kept, and the
  file just saved is never pruned.
