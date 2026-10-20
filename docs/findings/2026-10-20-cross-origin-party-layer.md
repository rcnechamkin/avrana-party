# The Party layer on the game origin: integration, compatibility and security review

Observed 2026-10-20 (Sprint 03). Party branch `claude/xo-party-layer`, Games branch
`claude/xo-party-layer`. Evidence is from Windows 11 with Chromium at phone size over plain HTTP,
on two host names of one site. Nothing here was run on a phone, over HTTPS, behind nginx or on the
appliance. Hosted CI is billing-blocked and did not run.

## 1. What existed and what was missing

| Piece | State before this work | Where |
|---|---|---|
| Party-origin frame `/party/layer.html` and its app | built (#162, AVR-579 placement) | `web/party/layer.html`, `lib/layer-app.js`, `lib/layer.js` |
| The frame answers only its own origin or an origin Party Core registers for that game | built (#164) | `layer-app.js` `allowed()`, `bridge.js` `originAllows` |
| Host actions limited across origins to End and Bring everyone back | built (#164) | `layer.js` `actions(view, {crossOrigin})` |
| The import-free mount a game repository vendors | built (#162, #164) | `web/party/bridge/layer-mount.js` |
| `frame-ancestors 'self' https://games.avrana.net` on `layer.html` only | built (#164) | `avrana-party.nginx`, devserver, provider harness |
| Optional `layer` block in the contract; `contract_check.py` compares a vendoring Games repository | built (#164) | `contracts/party-games.v0.json`, `tools/contract_check.py` |
| Same-origin BLUFF and EXPO mount the layer | built (Games #84) | `party-follow.js` `syncLayer`, Games `avrana-integration.js` |
| **Games vendors the mount** | **missing** | — |
| **The game-origin path mounts the layer** | **missing**: `followThroughBridge` published `window.AvranaParty` but no layer | Games `web/avrana-integration.js` |
| **A real-page test of the layer on the game origin** | **missing**: `tests/offline/bridge.spec.ts` used a stub page | — |

AVR-292 recorded the gap ("Games-side vendoring need coordination"). No later branch addressed it.

## 2. What this work adds

**Games** (one PR):
- `web/avrana-party-layer.js`: `layer-mount.js` byte for byte. It is served at `/shared/avrana-party-layer.js` and pinned under `layer` in `provider/avrana-contract.json`.
- `avrana-integration.js` `followThroughBridge` mounts the layer by the `party-follow.js` rule:
  - mounted while the bridge's view says this phone is a member and the round or its results are this game;
  - stopped when the party goes home or to setup, switches games, or this phone stops being a member;
  - a mount that is still loading when the view leaves never appears;
  - a file that failed to load is fetched again at a new address, as the shim is.
- `ops/vendor_party.py`: re-vendors every Party file the declaration names, and its digest (see §4).
- Tests and docs. Same-origin code is unchanged.

**Party** (one PR):
- `tests/provider/game-origin-layer.spec.ts`: real BLUFF and EXPO on the game origin. This adds a harness instance, `--game-origin --expo-game` on port 8187.
- Docs: this finding, the device-validation evidence table and the control-center proposal.
- No product code, contract, vector, nginx or bridge change.

## 3. Security review

Trust boundary (ADR 0013): a game page holds no Party identity and reaches the Party only through Party-origin frames. Checked against this change:

| Question | Answer | Evidence |
|---|---|---|
| Does the game page gain a cookie, token, member id or Party storage? | No. The page creates the frame element. The frame's document is the Party's (opaque to the page), loaded with the phone's own credential. | spec `holdsNoParty`, at the end of each of the 10 tests that end on the game origin. The browser's cookie jar holds the device cookie for the Party host (the control) and none for the game host. The game origin's storage has none of the Party's keys (`avrana-layer-position`, `avrana-chat-seen`, `avrana-party-sent`) and no ticket. The page sent no `/party/api/` request (WebSockets and other paths are not counted; the harness game origin answers `/party*` with 404). The frame's document is opaque to the page. |
| What does the page receive? | Only placement messages (`ready`, `place`, `drag`, `hide`) and the `avrana-party-layer` `{open}` event. No member, view, chat or message text. | `layer-mount.js` `parseLayerMessage`; the vectors are unchanged |
| What can the page send to the frame? | Only `viewport` (size and safe areas). Host verbs, bridge messages, other types and a malformed `viewport` are ignored. | spec "forged layer messages": the round is still `active`, and the frame still opens afterwards |
| Can a page forge the frame's messages? | No. The mount accepts only messages from `partyOrigin` whose source is its own frame. | spec "forged layer messages". Messages the page posts to itself fail the origin check. A second Party-origin frame on the same page (same origin, another source) opens its own drawer, and the page's own frame does not move or open. |
| Can another origin frame the layer? | No. The browser refuses the frame (`frame-ancestors`). Behind that, `layer-app.js` stays silent for an origin Party Core does not register for that game. | spec "an origin the Party has not registered". The same mount from the registered game origin gets `ready`; from another origin it gets nothing, and the browser logs the `frame-ancestors` refusal. `allowed()` itself is not reached there (the browser refuses first, and the harness registers `'*'`); it has Party's own unit tests. |
| Are Host privileges wider across origins? | No. Across origins the drawer offers only `end` and `lobby` (what bridge v1 already allows a game page), each confirmed inside the frame. Handover and stop-hosting stay on Party pages. Party Core decides each verb again. | spec "the Host on the game origin is offered only End and Party Home" |
| Where does the Party origin come from? | The games server's configuration only (`/api/avrana` from `AVRANA_PARTY_ORIGIN`), as for the bridge, never from the address or a message. | Games `test_the_page_takes_the_party_origin_from_this_server_only` (unchanged) |
| Frame sandbox | `allow-scripts allow-same-origin allow-forms`: no top navigation, no popups. After End, navigation goes to the configured Party origin plus `/party/`, through the bridge. | spec asserts the attribute; End lands on `party…/party/` |
| New protocol or contract change? | None. Bridge v1 and its vectors are untouched. `avrana.party-layer/v1` and the optional `layer` block existed. | `contract_check.py` compatible |

Residual risks (accepted earlier, unchanged, recorded so they are not lost):
- **The page owns the frame element.** A hostile or buggy game can hide, remove, move, resize, make transparent or cover the frame (a lure).
  - Denial of the layer is the worst case for hiding it.
  - A lure needs two taps inside the frame for End (action, then confirm), and End is a verb a game page already has through bridge v1.
  - Owner decision D3 accepted "coverable" for first-party games only. This is why the layer is opt-in per game (`LAYER_GAMES`, or `<html data-avrana-party-layer>`).
- **The embedder names the game.** The page supplies `?game=` in the frame's address. Party Core's per-game registration (`game_origins`) is therefore only as strong as the origin: any page on a registered origin can claim any game that origin is registered for.
- **Version skew is caught only where the two repositories meet.** Games' tests pin its copy. That the pin is Party's current digest is checked by `contract_check.py --games` in Party's CI, which is billing-blocked. Run it locally before pairing commits.
- **A same-site frame relies on the browser sending the Party cookie into it.** `party.` and `games.avrana.net` are the same site, so `SameSite` does not block it. Safari's tracking prevention on a framed Party page is unproven (device validation 7.7). If it blocks the cookie, the frame sees no member and hides: the game is unaffected, but there is no button.

## 4. Vendoring and compatibility

- **Mechanism (existing, now used for the layer):** a byte-for-byte copy, LF-normalised and pinned by SHA-256 in both declarations.
  - Games' tests check the copy against its pin and check that the server serves those bytes at the declared path.
  - Party's `contract_check.py --games` names a copy that is not Party's (`layer mount drifted … re-vendor the file and update both declarations`).
- **Update path:** `python ops/vendor_party.py --party <checkout> --check` names every difference and writes nothing. Without `--check` it copies the files and writes Party's digests.
  - It refuses a Party checkout whose files disagree with its own declaration.
  - It copies nothing for a component Games does not declare.
  - No manual copying.
- **No guest steps, no per-game Party Core change.** The frame is the Party's own page. `game_origins` already decides which origins may frame it, per game.
- **Compatibility:**

  | Party | Games | Result |
  |---|---|---|
  | main, `layer.html` framed by the game origin | this branch | the layer on both origins |
  | main | main (no copy) | unchanged: the layer on the Party origin only |
  | a commit whose `layer-mount.js` differs | this branch | `contract_check` names drift; re-vendor |
  | one that refuses the frame (no `frame-ancestors`, origin not registered) | this branch | the frame is silent and hidden; the game plays normally (spec "unregistered origin") |

- **Rollback:** revert the Games commit. Party needs nothing.

## 5. Deployment status (owner decision, not taken here)

nginx serves BLUFF and EXPO only on the Party origin. `games.avrana.net` serves native games only ([game-origin](../runbooks/game-origin.md), "Known limits"). So on the appliance today BLUFF and EXPO use the same-origin layer, and this game-origin path is dormant.

Moving them to the game origin is a separate owner-approved change, set together:
- a `games.avrana.net` location for `/games/(bluff|expo)/`, their WebSocket, `/shared/` and `/api/avrana`, with the Cookie header cleared;
- if those pages are given a Content-Security-Policy there, `frame-src` must allow the Party origin (the bridge and the layer frames);
- `AVRANA_PARTY_ORIGIN` in the games drop-in;
- `bluff` and `expo` in `game_origins`;
- then device validation.

Nothing in these PRs makes that change.

## 6. Verification

| Check | Result | Where |
|---|---|---|
| Real BLUFF and EXPO on the game origin (12 tests) | 12 passed (4.3 min, final spec and Games runtime code) | `tests/provider/game-origin-layer.spec.ts`, Chromium (Pixel 7 project; iPhone 13 device profile in the contexts) |
| Same-origin layer, game-origin bridge and Party session regression | 26 of 27 passed in one run. The failure, `game-origin.spec.ts` "same pages on the Party origin keep the same-origin path", read `AvranaIntegration` after the page had already followed the party away. It is pre-existing and fails the same way with Games `main` `4acc5ae`. It is not an ordering effect, as first recorded here: the harness reset left the previous test's round on the games server, and the test opened BLUFF with no round, so the Party correctly sent the page home while the test read it. It fails with `game-origin.spec.ts` alone too (an earlier "passes alone" ran that one test by name). Fixed separately, tests only, in #176. Not caused by this change. | `party-layer.spec.ts`, `game-origin.spec.ts`, `game-origin-home.spec.ts`, `party-session.spec.ts` |
| Games: the mount's lifecycle on the game origin (including leave-and-return while loading, one retry at a time, a refused or unloadable layer) | 37/37 | `tests/avrana_bridge_test.mjs` |
| Games: pin, serving, vendor tool (including hostile paths and a refusal part way), contract | 38 passed; kit export 24 passed | `tests/test_avrana_bridge.py`, `test_vendor_party.py`, `test_avrana_contract.py`, `test_avrana_provider.py`, `test_export.py` |
| Cross-repository contract | compatible | `tools/contract_check.py --games` |

Environmental, not caused by this change:
- Games `tests/bluff_briefing_test.mjs` fails "Party launch: no page errors" against a standalone games server, which has no `/party/`. It fails the same way on Games `main` `4acc5ae`.
- Party `tests/offline/join-card.test.mjs` could not load `jsqr` from the `node_modules` borrowed for this worktree. No Party product code changed.

What the spec covers:
- Host and non-Host, BLUFF and EXPO.
- Open and close, long-press drag, edge parking as a tab and back, landscape and back.
- Chat and the unread count across origins.
- Keyboard: Enter opens, Escape closes and focus returns; closed, BLUFF's own rules sheet and Escape work.
- BLUFF quiet while the drawer is open, catching up after.
- Offline and recovery with the seat kept; End to Party Home with the frame removed.
- Forged messages; an unregistered origin; ten mount and stop cycles plus a second round; no credential on the game origin.

**Not verified (owner, Tier 3):**
- real iPhone (Safari tracking prevention, 7.7), Android and Raspberry Pi;
- HTTPS and the `__Host-` cookie; nginx's real headers;
- touch drag on glass; screen readers; enlarged text;
- Limited Mode, which is same-origin by D6 and out of this path;
- BLUFF and EXPO actually served on `games.avrana.net` (§5).
