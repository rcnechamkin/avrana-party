# Power evidence, 2026-09-24 (boot b90bd6d2, new PSU + USB Wi-Fi adapter)

The raw files listed below are archived outside Git in the laptop's
`avrana-party-raw-evidence-backup-20260925` directory. Their measurements
are summarized in the linked finding. Historical commits still contain
the files; the current branch tip does not track them.

Analysis: `../../2026-09-24-new-psu-power-baseline.md`.

| File | What |
|---|---|
| `newpsu-adapter-20260924T082508.jsonl` | Run A: 1,200 per-second `pi-throttle-check.sh` samples (flags, temp, ARM/V3D clock, core volts) |
| `newpsu-adapter-20260924T082508.minute.log` | Run A: per-minute context (load, kernel dip-line count, USB adapter present, wlan1 state, stations) |
| `newpsu-quiet-20260924T090016.jsonl` | Run B (quiet): 2,700 per-second samples |
| `newpsu-quiet-20260924T090016.minute.log` | Run B: per-minute context |
| `kernel-dips.txt` | Every kernel hwmon under-voltage / normalised line this boot (PDT time, message) |
| `ssh-session-opens.txt` | Times (PDT) of every SSH session opened on the Pi this boot — times only, no users or addresses |

Sample timestamps in the JSONL files are UTC (`Z`); logs are PDT (UTC−7). Two kernel lines = one dip.
