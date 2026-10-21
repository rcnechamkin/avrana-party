# Release candidate: Party 8de7ef20835a + Games 1dc48d22fc18

Verdict: **CANDIDATE_OK**. Generated 2026-10-21T22:45:00Z by `tools/release_candidate.py` (Party 160aa3bb02df). Schema `avrana.release-candidate/v0`. This is paperwork: nothing was installed or deployed, and nothing here was run on the Pi.

| | Party | Games |
|---|---|---|
| commit | `8de7ef20835a1d98ec55cb772c216cbd348084fa` | `1dc48d22fc189cc6e92fce23109d639230c471df` |
| subject | Merge pull request #167 from rcnechamkin/claude/avr-580-party-lifecycle-5316e0 | Merge pull request #92 from rcnechamkin/claude/avr-676-hearts-cleanroom |
| commit date | 2026-10-20T19:36:48-07:00 | 2026-10-20T18:36:20-07:00 |
| tree | `67ad5f864d31d98bc27e688e7511c088bdba67cd` | `a58da2feeb213966a7901de5515241b1045f701c` |
| origin/main | on origin/main | on origin/main |
| git archive sha256 | `4c02093e54f9a957394aa5fd2e0fb9dd2ff3057dd612b24ae43053e8c896569c` | `f9cf133c3184d2b7c0044f2bd4dd3920b8fca92852c481ad82bd01ec3f8156b0` |

- Contract check (tools/contract_check.py on the two exact trees): **compatible** - Party <-> Games contract: compatible
- Contract versions: Party implements `avrana.party-games/v0`, Games requires `avrana.party-games/v0`; session `avrana.party-session/v0`, result `avrana.game-result/v1`, bridge `avrana.party-bridge/v1`, layer `avrana.party-layer/v1`, launch `avrana.lan-launch/v1`
- Party layer (web/party/bridge/layer-mount.js): **match**; Games pins `2b60de2dfc2f360a85fdfec706444a6f119445e14de1bd3698ac4809fb123088`, this Party ships `2b60de2dfc2f360a85fdfec706444a6f119445e14de1bd3698ac4809fb123088`
- Runtime pins: Python 3.11 or newer; optional Node runtime 22.22.2; tools python3, git, nginx, openssl, curl, sudo; package-lock.json sha256 `ca9af4fea811b6fbd93093e689555272b7385a42b5eeb17ad21f85ac3205f315`
- Third-party inventory (tools/sbom.py --check): ok

Offline reproduction (git bundles of exactly each SHA, ref `refs/heads/release-candidate`):
- `party.bundle` sha256 `5a9f63eae26de2400e3d126a7cd8500a6ff88756375c0579846c56ad36c9d176` (26056542 bytes)
- `games.bundle` sha256 `98d07f235330442a250c87384587bf7641ef1e83adf36087edf0b7b1d9887ad0` (29296428 bytes)

## Flags

None.

Next: `verify` this manifest, take a preflight on the Pi, then `prereq`. See docs/runbooks/release-candidate.md.
