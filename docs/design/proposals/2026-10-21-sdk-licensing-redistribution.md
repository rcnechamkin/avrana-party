# Proposal: SDK licensing and redistribution (AVR-677)

**Status:** proposal, 2026-10-21. Nothing has been changed: no licence, header, file or export. **Owner decision required.** This is an engineering audit, not legal advice.

Sources: Party `origin/main` 8de7ef2; Games `origin/main` (`rcnechamkin/avrana-party-games`), read with `git show`.

## 1. Inventory: what ships where

Origin key: **MIT-inh** inherited LAN Games code (BEACNpool); **Kit** Avrana-authored; **Vend** vendored from Party; **3P** third party.

| Group | Files | Origin | In package (a) | Dev bundle (b) | Tools export (c) | Licence statement present | Copyright evidence |
|---|---|---|---|---|---|---|---|
| Kit Python runtime | `avrana_gamekit/{__init__,app,helpers,jsonio,party,runtime,devparty,conformance}.py` | Kit | yes (`scaffold.py:41-42`) | yes | no | none in file; repo `LICENSE` MIT | first commit 2026-10-09, author `rcnechamkin`; stdlib only |
| Kit dev tools | `__main__, scaffold*, comply, play, boot, browsers, match, export, pagerefs, artwork` | Kit | no (`scaffold.py:43`) | yes | no | as above | same |
| Kit Node runtime | `avrana_gamekit/js/{game-app,game-runtime,jsonio,party-protocol,party-result}.mjs` | Kit (`party-protocol.mjs` reimplements, not copies, Party's protocol; export NOTICE says so) | Node games | yes | no | none in file | 2026-10-13/14, `rcnechamkin` and `Claude`; imports only `node:` and relative |
| Kit page modules | `js/avrana-build.mjs`, `js/avrana-layer.mjs` | Kit | yes (recipe) | yes | no | none | `rcnechamkin` |
| Vendored protocol and result | `core/party_protocol.py`, `core/party_result.py` | Vend (byte copies, `ops/vendor_party.py:1-12`) | yes | yes | no (stand-in constants only) | none; the Games `LICENSE` is MIT | Party repo `LICENSE`: Cody Nechamkin, all rights reserved |
| Vendored bridge shim, layer mount | `web/avrana-party-bridge.js`, `web/avrana-party-layer.js` | Vend (Party `web/party/bridge/shim.js`, `layer-mount.js`) | yes | yes | no | none in file | same |
| `core/__init__.py` | empty marker | Kit | yes | yes | no | none | trivial |
| Other `core/*` | `session.py`, `chat.py`, `net.py`, ... | MIT-inh (e.g. `session.py` first commit BEACNpool 2026-07-17) | no | no | no | MIT | BEACNpool |
| Hello Party | `hello_party/` | Kit; manifest claims `"license": "MIT"` (`hello_party/avrgame.json:57`) | yes | yes | no | claim only | `rcnechamkin` |
| Docs | `docs/DEVELOPING-A-GAME.md`, `PARTY-SESSION-PROTOCOL.md` | Kit | no | yes | no | none | `rcnechamkin` |
| Legal files | `LICENSE`, `NOTICE.md` | MIT text, BEACNpool | **no** | `LICENSE` copied; generated NOTICE | generated NOTICE | n/a | n/a |
| Tanks reading reference | `colyseus-tanks/{server,tools,tests,web,...}` | Mixed: ported Colyseus demo (MIT, Dreyer and Mihejevs), Kit | built package only | source only, no npm, no model (`export.py:78-79`) | no | its own `NOTICE.md` (CC BY 4.0 model, MIT demo, `THIRD-PARTY-LICENSES.txt` written by `build.mjs:260-269`) | per its `NOTICE.md` |
| Validator and packer | `avrana/avrgame/{__init__,archive,artwork,build,common,manifest,node,__main__}.py`, `avrana/contracts/{strictjson,game,vocabulary}.py`, 3 stand-ins, reduced capability JSON, README, NOTICE, MANIFEST | Party-authored | no | no | yes (`build_avrgame_tools.py:93-104`) | none in file; export NOTICE says terms are "an open owner decision" | Party `LICENSE:1` |

Python `check`/`pack` recipes (hello_party) include the kit files, shim, protocol and result and no `LICENSE` or `NOTICE` (`hello_party/avrgame.build.json`, `scaffold.py:394-407`). The Node scaffold ships six `.mjs` files plus the shim (`scaffold_node.py:14,32`).

## 2. Findings

1. **The kit is MIT by default, not by decision.** Games `LICENSE:3` reads only "Copyright (c) 2026 BEACNpool". `NOTICE.md:9,13` says new Avrana files are "(c) 2026 Avrana Party Games" under MIT, but "Avrana Party Games" is not a named legal person, and the kit (first commit 2026-10-09) is entirely post-fork. The kit therefore sits under a licence nobody chose for it, with no per-file header. Six commits are authored "Claude"; ownership of those is for counsel.
2. **Party-owned files travel under a contradictory header.** The four vendored files are copies of proprietary Party code (Party `LICENSE:1-4`, "All rights reserved"; `package.json:42` UNLICENSED). They carry no header, sit in a repo whose LICENSE says MIT, and ship in every package and the dev bundle. The Games bundle NOTICE (`export.py:218-253`) calls their terms "an open owner decision" and says the bundle `LICENSE` "does not cover" them. Package users get neither statement.
3. **Packages carry no LICENSE or NOTICE.** No recipe lists either (see above); this is r1 G-12 / r2 G09 (`docs/findings/2026-10-20-sdk-clean-room-hearts.md:114`). The scaffold template pre-fills `"license": "MIT"` (`scaffold.py:384`) for the developer's own game, which is unrelated to the kit files inside it.
4. **Stale statement.** Tools-export `NOTICE.md.in:19-21` says the Party repo "carries no licence file". It has had one since 2026-10-14. `THIRD-PARTY.md:67,83` already records the owner position: Party Core all rights reserved; deliberately published SDK components get a permissive licence, exact one chosen at publication.
5. **Third-party.** Kit Python imports stdlib only; kit Node imports `node:` and relative paths only (grep of all modules). Tanks has real dependencies (`@colyseus/*`, `three`, `ws`, build-time `esbuild`; `colyseus-tanks/package.json`), bundled and licensed in its own package, and a CC BY 4.0 model that `NOTICE.md` says nobody has re-confirmed with the author. Neither goes in the dev bundle.
6. **Ambiguities.** (a) Whether any Party protocol constants in the Node twin are copied expression; (b) the tools export copies Party-authored validator code whose redistribution is undecided; (c) the Hello Party word list and `colyseus-tanks` mix MIT-inherited and Avrana content, so a blanket relicence of the Games repo is not available; (d) `core/` mixes inherited and kit files in one directory.

## 3. Options

| | A. Do nothing | B. Whole Games repo relicensed | C. Separately licensed SDK subset (recommended) |
|---|---|---|---|
| What | Keep MIT-by-default; add notices only | Replace MIT for everything | Name an SDK subset; headers and one licence for it; everything else unchanged |
| Problem | Vendored proprietary files stay under a wrong repo licence; packages stay unlabelled | Cannot: inherited BEACNpool code must stay MIT | Needs 3 owner decisions |
| Effort | Small | Not viable | Small to medium |

## 4. Recommendation: Option C

**SDK subset** (kit runtime, page modules, Node kit, Hello Party, protocol docs, plus the four reference copies):

| Files | Header |
|---|---|
| Kit files in rows 1-4 above, `core/__init__.py`, `hello_party/*` | `SPDX-License-Identifier: <owner's choice, e.g. MIT or Apache-2.0>` and `Copyright (c) 2026 <holder>`, plus a `NOTICE.md` naming the subset |
| `core/party_protocol.py`, `core/party_result.py`, `web/avrana-party-bridge.js`, `web/avrana-party-layer.js` | Same SPDX line and "Reference implementation, vendored unchanged from the Party repository; the wire contract is the specification." Header is added at the Party source, then re-vendored (digests in `provider/avrana-contract.json` change; `ops/vendor_party.py` handles it) |
| Validator and packer (tools export) | Same licence only if the owner elects to publish; otherwise omitted from any public distribution |
| Party Core (`avrana/party/*`, `avrana/ops/*`, installer, nginx, UI), never shipped | Unchanged: all rights reserved |
| Inherited `core/*`, games, `bestguess`, `checkers`, `colyseus-tanks` | Unchanged MIT/CC; keep their own notices |

Every package and every bundle then carries `LICENSE` (the SDK licence) and a `NOTICE.md` listing: SDK files and licence; "Party Core is not included"; the vendored reference files' origin; third-party items (Tanks `THIRD-PARTY-LICENSES.txt`).

**Owner decisions needed:**
1. Licence for Avrana-authored kit files (permissive; MIT is consistent with the Games repo, Apache-2.0 adds a patent grant).
2. Whether the four bridge/protocol/result/layer copies (and, separately, the validator and packer) may be redistributed under that licence, i.e. whether a permissive grant over reference implementations of the public wire contract is acceptable.
3. Copyright holder name for headers (suggest the individual named in Party `LICENSE`, "Cody Nechamkin", or a registered entity if one exists), and how to treat commits authored by Claude.

## 5. Validation proposal (no code written)

- `check` and `pack` emit a **warning** when the recipe lacks `LICENSE` or `NOTICE.md`, and the scaffold recipes include both (r2 G09). Later, an error if the packaged `LICENSE` is absent while a vendored file is present.
- A Games test that `export` lists exactly an allow-list: the `TOP_LEVEL`/`FILES`/`TANKS_*` set, plus generated files, and no `core/` file beyond the three shipped, no `node_modules`, no model or font, no `upstream/`.
- A test that each vendored file's SPDX header equals the Party source and the pinned digest, and a Party-side test that the tools export file list equals `COPIED` plus the declared stand-ins.
- Refresh the stale sentences in both NOTICE templates only after the decision.

## 6. Limits

This is not legal advice. No licence change, header, relicensing, publication or external distribution of any bundle or export happens without the owner's approval, ideally after review by counsel.
