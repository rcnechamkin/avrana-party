# Party 1.0: authoritative launching and the membership lifecycle (assessment)

- **Status:** assessment, 2026-10-20. It records how the source behaves, what is tested, and what is missing.
  It decides nothing new: the authority is ADR 0011's, the origins are ADR 0013's, and Leave and Reconnect
  are AVR-580 (Party PR #167).
- **Reads with:** [ADR 0011](../adr/0011-party-console-model.md), [ADR 0013](../adr/0013-party-and-game-browser-origins.md),
  `web/party/lib/party-mode.js` (`destination()`), `web/party/lib/bridge.js`, Games `web/avrana-party-bridge.js`.

## 1. The invariant (Party 1.0)

1. **One authority.** Party Core's `location` (home, setup, game or results) says where the Party is. Only the
   Host moves it, or Core itself when a launch fails, a round is abandoned or the Host role passes on.
2. **Every member's page is where `destination()` says.** At home or setup that is Party Home, which shows the
   setup scene. During a round or its results it is the round's game. No member presses Join or navigates to
   follow. The shell, the follower on Party pages and the bridge all ask the same function.
3. **Roles are Core's.** With a pregame, players come from the Play/Watch choices. Without one, members are
   seated in join order up to `players.max`. Everyone else watches, and so does anyone who arrives during a round.
4. **A game page never moves the Party or itself.** The Party moves it: the bridge's one `navigate` goes only
   to Party Home (`/party/`), and Party Home forwards to wherever the Party is. A game gets no URL from a
   message and no navigation authority. Over a game origin the Host keeps only End and Party Home (D3).
5. **Recovery re-applies it.** After a reload, a wake, a dropped socket, going offline or switching between
   Full and Limited Mode, the page asks again where the Party is and goes there. The one exception is a device
   that left on purpose (#167): it stays out until its own Reconnect.
6. **Non-hosts move nobody.** Core refuses `end`, `switch`, `launch` and `start` from a non-Host (`not_host`).

## 2. Where it is enforced and tested

| Surface | Enforced by | Tested (Chromium, not a phone) | Gap |
|---|---|---|---|
| Party Core | `location`, Host-only moves, roles | `test_party_core`, `test_party_service`, `test_party_session_flow` (pregame, late arrivals, switch, abandonment) | none found |
| Party shell, same-origin game pages | `destination()` in `app.js`, `party-follow.js` | party lane: Host start, switch ("the old page follows"), End, late or reopened phones, pregame, Host leaving mid-game | none found |
| First-party games on a game origin (BLUFF, EXPO) | Party frame → bridge `navigate` | provider: `game-origin*.spec.ts` (start, End, reload, socket drop, a phone opening Party Home mid-round) | switching is covered on the Party origin only; on a game origin it uses the same `navigate`, but it is not tested there |
| Limited Mode | the same `destination()` | offline lane: `limited.spec.ts` ("Host moves reach Limited phones...", "comes back from offline") | none found |
| Native `.avrgame` packages, real Party | the shell, plus the kit's vendored bridge | provider `native-package.spec.ts` (#180): Host start direct and with pregame, seats up to `players.max` and a watcher, reload, End. The follow-up branch adds offline and back, a late joiner who watches, a non-Host refused, and End through Core | Limited Mode, wake and switch not run for packages; Python packages only (no Node package through the harness) |
| SDK tooling (`play`, `match`, `comply` with the stand-in Party) | the stand-in Party sends `navigate` only on End | `comply` lifecycle (Host End), `match` | no Host start from Party Home, no late watcher, no switch. Nothing checks that a page does not navigate itself or hold the page (`beforeunload`, `location.assign`, `window.open`), so a game could break rule 4 and pass `comply` |
| Physical phones (Safari, Android, an installed PWA, a real Wi-Fi drop, a Pi reboot) | — | not run | all of it |

**What games must not rediscover:** following is the Party's, never the game's. A kit game gets it by loading
the bridge, which `comply --boot` proves by taking a seat. What the platform does not yet guarantee is that a
package cannot undermine it. That is the SDK gap.

## 3. Leave and Reconnect: Party PR #167 (AVR-580)

**Verdict: ready for owner review after a small compatibility update, now pushed to #167 (467d2fb, aafe86d).**
- **Main merge:** main merges cleanly; it has moved only by #175 and #176.
- **Gap found:** the drawer offered Leave, including a Host's Leave, which hands over the role, over a game
  page of another origin. That breaks Sprint 03's D3 limit: only End and Party Home there.
- **Fix:** Leave is now hidden over game origins. A provider test fails without the fix and passes with it.
- **Re-runs:** the targeted Python, Node, party-lane and provider suites pass; the counts are in #167.

The behaviour matches the desired UX:
- **Disconnect** is away-grace, not Leave, and membership recovers.
- **Leave Party** is idempotent, authenticated by the device cookie, and blocks automatic joining from any
  tab, wake or stale URL.
- **Reconnect** is an explicit `POST /party/api/reconnect`, after which the page follows the current location.
- **Host Leave** is confirmed with its consequence. Succession is decided by Core. With no successor, the role
  goes vacant and the round goes on, which is the owner decision of 2026-10-18.

The accountless, device-local model is kept: the opt-out is a same-browser marker, and the server persists
nothing.

Remaining acceptance gates:
1. **ADR 0011 amendment and security review:** owner.
2. **Guest Leave during a round on a game origin:** owner decision. It is now unavailable there, and closing
   the page is a disconnect, not a Leave. Allowing a guest-only Leave would widen D3.
3. **Physical phones:** Safari and an installed PWA, Android, a real Wi-Fi drop mid-Leave, a Pi reboot, and
   VoiceOver and TalkBack on both confirmation sheets.
4. **Full suites on the updated head:** not re-run, and hosted CI is unavailable (billing).

## 4. Recommended order (owner-reviewed; nothing merged)

1. **#167**, after the owner accepts the ADR amendment and decides gate 2. It is independent of Sprint 04.
2. **The package coverage branch** (`claude/party-follow-package-coverage`, on #180), with its Linux run, after
   #180. It is tests only.
3. **An SDK follow-up (Games):**
   - `comply` refuses page code that navigates itself or holds the page;
   - the stand-in Party emulates a Host start from Party Home, a late watcher and a switch, so `match`
     exercises rule 4 and the roles.

   This is a kit change for approval, not done here.
4. **Physical acceptance**, one checklist for both features: start, Play/Watch, a late joiner, switch, End,
   offline and wake, Leave, Reconnect and Host Leave, on an iPhone and an Android phone, in Full and Limited
   Mode, against the appliance. It is owner-run.
