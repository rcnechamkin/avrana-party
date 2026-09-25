# Power evidence, 2026-09-24 afternoon (boot 0d18f4ca, new PSU, NO USB Wi-Fi adapter)

The raw files listed below are archived outside Git in the laptop's
`avrana-party-raw-evidence-backup-20260925` directory. Their measurements
are summarized in the linked finding. Historical commits still contain
the files; the current branch tip does not track them.

Analysis: `../../2026-09-24-no-usb-power-baseline.md`. JSONL timestamps are UTC (`Z`); logs are PDT.

| File | What |
|---|---|
| `nousb-idle-20260924T114025.jsonl` / `.minute.log` | run A: 4,500 per-second samples + per-minute context, idle, no agent SSH |
| `nousb-load-20260924T135242.jsonl` / `.minute.log` | runs B/C/D: 2,760 per-second samples + per-minute context |
| `nousb-load-20260924T135242.phases.log` | phase and burst start/end times written by the load script |
| `power-load.sh` | the exact bounded load script that ran on the Pi |
| `laptop-phaseB-ssh.log` | when the laptop opened its phase-B SSH connections (incl. one unplanned) |
| `ssh-session-opens.txt` | every SSH session opened on the Pi this boot (times only) |
