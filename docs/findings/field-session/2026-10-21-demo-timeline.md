# Field session 20261021T224206Z-demo-simulated-outage

- label: demo simulated outage
- started: `2026-10-21T22:42:06Z`; stopped: `2026-10-21T22:42:16Z`
- party: `4713f5c5e90f`, games: `unknown`, web build: `dev`, contract: `avrana.party-games/v0`
- collector: `4713f5c5e90f`, rules `avrana.redaction/v2`
- journal: 0 lines kept, dropped {'cap': 0, 'conversation': 0, 'outside': 0}; journal unavailable (not Linux)

| Time (UTC) | Event |
|---|---|
| `2026-10-21 22:42:06` | session start |
| `2026-10-21 22:42:06` | snapshot 001 (start): status unknown; new: certificate expiry unavailable; nginx site file unavailable to compare; no deployment manifest; 0 member(s), session none |
| `2026-10-21 22:42:07` | **MARK PASS** [D-1]: baseline: Party Home answers on the dev server |
| `2026-10-21 22:42:09` | snapshot 002 (snapshot): **status unreachable (ConnectionRefusedError)** |
| `2026-10-21 22:42:11` | **MARK FAIL** [D-2]: simulated outage: Party Core process killed |
| `2026-10-21 22:42:15` | snapshot 003 (snapshot): status unknown; 0 member(s), session none |
| `2026-10-21 22:42:16` | **MARK OBSERVED** [D-3]: Party Core answering again |
| `2026-10-21 22:42:16` | snapshot 004 (stop): status unknown; 0 member(s), session none |
| `2026-10-21 22:42:16` | session stop |

_Server-side evidence only: what phones showed is in the operator marks, not measured here._
