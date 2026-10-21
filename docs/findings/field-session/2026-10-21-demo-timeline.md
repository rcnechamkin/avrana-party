# Field session 20261021T221257Z-demo-simulated-outage

- label: demo simulated outage
- started: `2026-10-21T22:12:57Z`; stopped: `2026-10-21T22:13:10Z`
- party: `8de7ef20835a`, games: `unknown`, web build: `dev`, contract: `avrana.party-games/v0`
- collector: `8de7ef20835a`, rules `avrana.redaction/v1`
- journal: 0 lines kept, dropped {'cap': 0, 'chat': 0, 'outside': 0}; journal unavailable (not Linux)

| Time (UTC) | Event |
|---|---|
| `2026-10-21 22:12:57` | session start |
| `2026-10-21 22:12:57` | snapshot 001 (start): status unknown; new: certificate expiry unavailable; nginx site file unavailable to compare; no deployment manifest; 0 member(s), session none |
| `2026-10-21 22:12:58` | **MARK PASS** [D-1]: baseline: Party Home answers on the dev server |
| `2026-10-21 22:13:01` | snapshot 002 (snapshot): **status unreachable (ConnectionRefusedError)** |
| `2026-10-21 22:13:03` | **MARK FAIL** [D-2]: simulated outage: Party Core process killed |
| `2026-10-21 22:13:08` | snapshot 003 (snapshot): status unknown; 0 member(s), session none |
| `2026-10-21 22:13:09` | **MARK OBSERVED** [D-3]: Party Core answering again |
| `2026-10-21 22:13:10` | snapshot 004 (stop): status unknown; 0 member(s), session none |
| `2026-10-21 22:13:10` | session stop |

_Server-side evidence only: what phones showed is in the operator marks, not measured here._
