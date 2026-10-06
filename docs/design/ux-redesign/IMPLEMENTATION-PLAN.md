# UX/UI redesign: implementation plan

Status: **PROPOSED (2026-10-05). The owner approved slices 0 and 1 on 2026-10-05; slices 2 to 5 are proposals. Nothing here is implemented by this file, and it is a plan, not a contract.**

How the direction the owner approved in review on 2026-10-05 ([SCREENS](SCREENS.md),
[REVISION-2](REVISION-2.md); both stay proposals until accepted in the repository) could be built,
in slices that each leave a working product. It is grounded in what the two repositories hold
today: Party at `origin/main` `578534f`, Games at `origin/main` `a448972` (the Games working
tree on this machine is on an older branch, `feat/expo`; nothing here was read from it).
References are `path:line` in the Party repository unless they start with `games:`.

This is a plan, not a schedule. Each slice needs the owner's go-ahead. On 2026-10-05 the owner
approved revision 2 and this plan **for slices 0 and 1**, answered slice 0's questions (recorded
in that section) and asked for four things to be tightened, which this revision does: the
[rules for every PR](#rules-for-every-pr-of-slice-1), the rollback steps, the
[follow-up work](#follow-up-work) list, and slice 2's scope.

No Linear issue exists for this work yet: the workspace was at its free issue limit when
slice 0 started, so creating one was refused. Until that changes, each pull request carries the
issue text (outcome, acceptance criteria, out of scope, tests) in its body, as the design
tooling PR did, and follow-up work is listed here.

## What the repositories fix in advance

These facts shape every slice.

| Fact | Where | What it means for the plan |
|---|---|---|
| The shell is static HTML and plain ES modules; no framework, no bundler. Tailwind 4 and daisyUI 5 run on a dev machine and the compiled CSS is committed | `web/party/index.html`, `web/party/app.js` (585 lines), `web/src/party.css`, `docs/UI-DESIGN-SYSTEM.md:21-23`, `package.json:26-28` | The new shell is built the same way. No framework is introduced |
| Party Home is one page; views are `show('main'\|'scene'\|'going')` toggling `hidden` | `web/party/app.js:350-355` | The new shell stays one document at `/party/` with in-page views. `destination()` already treats `/party/` as the place for `home` and `setup` (`web/party/lib/party-mode.js:55-66`) |
| Every shell file must be listed in the service worker's `SHELL`; no inline script, style or handler | `web/party/sw.js`, `tests/unit/test_web_build.py:20-37` | New modules, fonts and pages are added to `SHELL`; the prototypes' inline styles cannot be copied |
| Guest-facing copy is scanned for jargon (seat, session, launch, presence, token, slot, server) | `tests/unit/test_web_build.py:39-45`, `tests/offline/party.spec.ts:8,86-87` | New copy must pass the same scan |
| Many specs bind to today's ids (`#scene`, `#scene-start`, `#choose-play`, `#choose-watch`, `#rules-ok`, `#party-members`, `#limited`, `#status`) | `tests/offline/party.spec.ts`, `tests/offline/limited.spec.ts`, `tests/offline/assimilation.spec.ts`, `tests/party/multi-client.spec.ts`, `tests/provider/party-pregame.spec.ts`, `web/party/lib/profile-ui.js` | Keep the ids of elements that survive; change the specs in the same PR as the markup they test |
| Party Core is the authority and is not touched by presentation: one location, Host-only moves, Play / Watch, the start blocker, tickets | `avrana/party/core.py`, `avrana/party/service.py:333-401` | Slices 1 and 2 need no server change |
| Game pages and the arcade page import the shell's own modules | `games:web/avrana-integration.js:176`, `arcade/index.html:92` (`/party/lib/party-follow.js`); the bridge frame and shim (`web/party/bridge.html`, `web/party/lib/bridge.js`, `web/party/bridge/shim.js`) | `party-follow.js`, `party-mode.js` and the bridge files keep their paths and exports through the rewrite |
| There is no feature flag. A web release is atomic and five are kept | `ops/install-party-web.sh:32-43,65-81`, `docs/runbooks/deploy.md:48-112` | No side-by-side shell. Rollback is the release flip. Each PR must leave `main` deployable |
| ADR, contract, `deploy/` and `ops/` changes are the owner's to merge. Agents never merge or deploy. A paired Party and Games change is one merge set | `AGENTS.md:59-78`, `REVIEW.md:34-41`, `docs/CROSS-REPO.md:9-39` | Wording changes are listed per slice as owner-merged prerequisites |
| The live catalog is five titles: BLUFF, EXPO and Gauntlet II installed; two PS1 titles declared but not installed and not in the Party Core configuration | `web/party/catalog.json`, `contracts/games/*.json` | The prototypes' seven-title Library is illustrative. PS1 work is paper until PS1 is a Party game |

## The slices

| # | Slice | Repository | Backend work | Depends on |
|---|---|---|---|---|
| 0 | Decisions and wording (**approved; this revision**) | Party (documents) | none | the owner |
| 1 | The shell journey: Home, Library, game detail, BLUFF briefing, play, back to the Party (**approved**) | Party | **none** | 0 |
| 2 | EXPO presentation, including the design of its undrawn states and the remaining enlarged-text work | Games (plus one descriptive note in Party's game UX contract) | **none** (optional items listed) | independent of 1 |
| 3 | Party-owned chat | Party | **essential**: chat state and routes in Party Core | 1; a new ADR |
| 4 | Briefings for Arcade and PS1 titles | Party (contracts, arcade page) | **essential**: contract flag, arcade-side handling, the not-playing state | 1; owner decision Q12's design |
| 5 | A Party layer during play | Party and Games, one merge set | **essential**: ADR amendments, new bridge verbs | 1, 3, and the geometry design task ([follow-up work](#follow-up-work)) |

Slices 1 and 2 are in different repositories and can run at the same time, one agent each.
3, 4 and 5 are independent of one another except where the table says so.

### Essential backend work and optional future features, side by side

| Essential (a slice cannot ship without it) | Optional (the product works without it; do it when wanted) |
|---|---|
| Slice 3: Party Core chat state, routes and identity (R3) | Library metadata for length and kind filters (R1); `pregame` copied into the catalog |
| Slice 4: `pregame` on the arcade contract and configuration; the arcade page honouring roles; the not-playing state (Q12) | Quick Start content per game, `avrana.onboarding/v1` (R2); covers for every title (R4) |
| Slice 5: ADR 0011 decision 5 amended; verbs added to the ADR 0013 bridge with vectors and the vendored shim | Suggestions (C1); Party-wide "recently played" (D1); player-impact wording in status (D2); roles in the view during play (D3); preferences handed to game pages (D4) |
| Slices 1 and 2: nothing | The Host countdown and successor in the view (D9); a hand-over control (the route exists: `POST /party/api/host`, `avrana/party/service.py:389`) |
| | EXPO: server text for a shared objective (D5), a reason for an unavailable burst (D6), the Host's seat by id (D7), Tonoja's covered columns (D8), mission names (EX-38) |
| | Chat photos, reactions and persistence across a restart; game pages following the Party in Limited Mode (`docs/design/LIMITED-MODE.md:26-27,169`, a gap that exists today) |

## Slice 0: decisions and wording

No code. Rows 0.1 to 0.5 and 0.7 are the owner's decisions of 2026-10-05. **Row 0.6 is not a
decision**: it lists what slice 1 builds as drawn while the question stays open. The wording
changes are in the same pull request as this revision and are the owner's to merge.

| # | Item | Decided (0.6: assumed) | Where it lands |
|---|---|---|---|
| 0.1 | The Party control, the People drawer and the Limited sheet on a briefing | **Allowed.** The owner: "Make Party access and the Limited explanation open over the briefing, preserving its location." They open over the briefing and close back to it; chat stays off it (0.2). Proposed with it, as drawn: the mark that opens the sheet; the Library, the navigation bar and "This phone" stay off the briefing; the sheet there has no link that leaves the page, so "Check for the full version" is on the ordinary pages and not there | `docs/design/GAME-UX-CONTRACT.md` Rule 3.2 and a dated amendment on ADR 0011 (decision 4), both in this pull request. Built in PR 1.3 |
| 0.2 | Today's chat in slice 1 | **Kept, in the drawer, on ordinary shell pages** (Home, Party, Library, System): the same hub and messages as now, connected only while it is on screen, and offered only while its hub answers; **people only over a briefing** | PR 1.1 builds the drawer. See "Today's chat and the runtime it depends on" below |
| 0.3 | Titles that are not installed | **Today's behaviour is kept**: listed, marked "Not installed", in the same line as other unavailable titles (decision 12) | PR 1.2 |
| 0.4 | Tokens and typeface | **The brief's temporary treatment is kept**: a Helvetica-style light face for the words "Avrana Party" (a real Helvetica Light where the phone has one, Geist Light elsewhere) and Geist for interface text (bundled, SIL OFL 1.1). The smoky-violet tokens go into `web/src/party.css` | PR 1.1, with `docs/UI-DESIGN-SYSTEM.md` in the same pull request so the document never describes tokens the code does not have |
| 0.5 | Where a Party layer would sit during play | **A separate design task.** It does not block slice 1 | [Follow-up work](#follow-up-work). Slice 5 depends on it; slice 2 proceeds without it |
| 0.6 | Open decisions the drawings already answer and slice 1 builds | *(As of 2026-10-05. Decision 7 and part of decision 4 were answered on 2026-10-06, below.)* **Not answered; provisional.** Slice 1 was approved as drawn and the owner did not name these, so each is built as drawn and stays open in [BACKEND-GAPS](BACKEND-GAPS.md#open-owner-decisions): Limited Mode visibility (decision 4), the drawer from the top edge (7), recents per phone (9), "Off for now" shown to everyone (15), the reconnecting timer (18). Each is called out again in the pull request that builds it, where it can still be changed. **Decision 4 wants an explicit yes before PR 1.4** folds the notice and adds the Host's notice: it reads an accepted ADR. PR 1.1 keeps today's notice and its wording, open on Home, and adds only the mark and its sheet | PR 1.1 (7; of 4, the mark and the sheet), PR 1.2 (9, 15), PR 1.4 (18; the rest of 4) |
| 0.7 | The design package's weight | *(The point "to confirm" was answered on 2026-10-06, below: "Nah.")* The owner: "Commit documents, prototypes, overview sheets and essential referenced evidence. Keep bulk screenshots and ZIP archives out of Git, with their location documented." **Read here as**: documents, prototypes, the ten overview sheets and the capture scripts are committed; the 422 loose pictures and the archive are not, and the [README](README.md#pictures-that-are-not-in-git) says where they are. **To confirm:** no loose picture was judged essential. The `current/` pictures cannot be retaken once the shell changes; if a small set of them should be in Git, say which | this pull request |

### Owner answers of 2026-10-06

After PR 1.1 and the slice 0 documents were merged, the owner was asked four things and answered each
in a word or two. The questions are as they were put; the answers are the owner's own words.

| Asked | The owner | What it changes |
|---|---|---|
| "**Limited Mode:** is 'notice on Home, small mark everywhere else' right? May the notice fold away? Should the Host be told when something on the box is wrong?" | "Correct" | The reading "notice on Home, small mark everywhere else" stands, which is what PR 1.1 built. One word answered three questions, so the other two are **not** taken as answered: PR 1.4 states the folded notice and the Host's notice again, in its own pull request, before it builds them |
| "**Drawer:** from the top edge, as built, or from the bottom?" | "Top edge" | Decision 7 is settled |
| "**The choices I made in #80:** smaller body text (15 px), no desktop rail, drawer opens on Chat first, 'Host' as a word instead of the crown. Say which to keep and which to change." | "That's fine" | Read as: all four stay |
| "**Old screenshots:** should a few pictures of the old UI go into Git? They can no longer be retaken from main." | "Nah." | Row 0.7's open point is closed: no loose picture of the old shell goes into Git |

Decisions 9 (recents per phone) and 15 ("Off for now" shown to everyone) were not among the
four. The issue for PR 1.2 (AVR-285) says to build them as the plan has them and to disclose
that in the pull request, which is what PR 1.2 does; they can still be changed at its review.
Decision 18 (the reconnecting timer) is still not answered and is PR 1.4's to raise.

### Today's chat and the runtime it depends on

Party chat is not Party Core's. The shell's chat client (`web/party/lib/party-chat.js`) speaks
the old chat hub's protocol at `/chat/ws`, which the LAN Games runtime serves
(`avranaparty-games`), under that runtime's own identity (`wc-token`, from
`web/party/lib/profile.js`). ADR 0014 retires that runtime. Keeping chat in slice 1 therefore
means three things:

- **The shell treats chat as something that may not be there.** The drawer offers its Chat tab
  only while the runtime that serves it answers (the page already asks it for the games list
  every 15 s: `GET /api/games`, `web/party/app.js:383`). When it does not answer, the drawer is
  people only and says nothing about chat. No "reconnecting" line stands forever in front of a
  runtime that is gone.
- **Nothing new is built on it.** No unread count, no system lines, no chat over a briefing, no
  chat inside a game. Those are slice 3's, on Party Core.
- **Retiring the runtime before slice 3 lands removes chat from the product**, cleanly, with no
  shell change. The owner chooses that order; this plan only makes sure neither order breaks
  the shell. Slice 3 (Linear AVR-53 and AVR-54 are the existing messaging issues) is the
  replacement.

It is connected only while the Chat tab is open, as today, and in Limited Mode it is offered on
the same test, so a Limited phone gets it only if that origin serves the hub.

## Slice 1: the shell journey

**Acceptance journey.** Four phones, one of them the Host. Each opens the Party, sees Home, opens
the Library, opens BLUFF's page. The Host brings the Party in; everyone lands on the briefing,
chooses Play or Watch, the Host starts, BLUFF plays to a result, the Host chooses Play again
(back to the briefing) or Party Home (back to Home, with BLUFF marked as just played on that
phone).

### 1. The working experience it delivers

- **The frame.** A top bar (page title, the Limited mark, the Party control with faces and a
  count of people) and a bottom bar (Home, Party, Library, System) while the Party is at `home`.
- **Home.** Who is here and who hosts; the last game played on this phone as the lead tile;
  "Great for N" from each title's player range and the number of people here; "Recently played".
- **Library.** Covers in medium, large, compact and list views, remembered per phone; search by
  name; a Players filter and a Screens filter; groups "Great for N" and "Not for N"; favorites.
  Under a title, when it applies: "Watch only on this phone", "Not on this phone", "Off for now",
  "Not installed", in every view.
- **Game detail.** Art, title, the catalog summary, players and screen facts, the fit sentence.
  The Host has "Bring the Party in"; everyone else reads who chooses. The premise and "How to
  play" appear when the game ships `onboarding.json` (BLUFF does; EXPO shows its summary only).
- **The Party drawer and the Limited sheet.** The Party control opens a drawer from the top
  edge with the people here and, while the old chat hub answers, today's chat. The Limited mark
  opens a sheet with what Limited Mode means on this phone. Both open over the page that is open.
- **Briefing.** Today's setup, redrawn: the line-up with Playing, Watching and Choosing, "Play
  this round" and "Watch this round", the server's own blocker sentence, the Host's "Start game"
  and "Choose another game", and the first-timer's rules step. The Party control opens people
  (no chat) over it; the Limited mark opens its sheet over it.
- **Play and return.** Unchanged: the phone moves to BLUFF's page, BLUFF draws the round and its
  result, and the Host's "Play again" and "Party Home" are BLUFF's existing buttons.
- **States.** Reconnecting and out of reach; the Host away and hosting passed (on Home, the
  Party page and the briefing); Limited Mode as notice, mark and sheet; appliance trouble as a
  Host-only notice and a System page; empty search, filter and favorites; text up to 200%.
- **Every other title keeps working.** EXPO takes the same path and gets the same briefing.
  Gauntlet II has no pregame, so the Host's button starts it at once, as today.

Left out on purpose, because the data or the decision does not exist: the three-step Quick
start (no game ships those steps; BLUFF's `onboarding.json` is `avrana.onboarding/v0` with a
premise, facts and rules), length and kind on tiles and in filters, "Suggest to the Party", an unread count, a hand-over control, a countdown on
the Host-away line, the one-screen first run (the existing profile form is kept and restyled).

### 2. Existing backend support, and what is missing

Everything this slice shows is already served.

| Need | Served by |
|---|---|
| People, Host, presence, this phone's mode, the one location | the view from `GET /party/api/state?since=&wait=` (`avrana/party/service.py:333-346`; fields at `avrana/party/core.py:739-772`) |
| Bring the Party in; Choose another game; Start; Play / Watch | `POST /party/api/session/launch`, `/session/end`, `/session/start`, `/session/choice` (`avrana/party/service.py:391-401`) |
| The line-up, who has not chosen, the blocker sentence | `session.setup` in the view (`avrana/party/core.py:750-759`) |
| Titles, player ranges, screen, watch support, art, installed | `web/party/catalog.json`, compiled by `avrana/contracts/catalog.py:99-127` |
| "Off for now" per title | the live health poll the page already runs (`web/party/app.js:32,378-389`) |
| "Watch only" and "Not on this phone" | the capability report and seat evaluation (`web/party/lib/limited.js:46-61`, `web/party/lib/evaluate.js`) |
| The Host's trouble notice and System's health line | `GET /party/api/status` (`avrana/ops/status.py:249-265`): the structured `arcade.ok`, `games_provider.ok` and `certificate.status` fields, not the operator sentences in `summary.reasons` |
| Favorites and recents | `lg-favorites` and `lg-recent` in `localStorage` (`web/party/lib/profile.js:52-57,79-89`); the shell adds a write to `lg-recent` when a round starts on this phone |
| The premise and the rules sheet for detail and briefing | `onboarding.json` beside the game (`web/party/app.js:267-276`): premise, facts, rules and the acknowledgement. No quick-start steps exist in it |
| Moving to the game and back | `destination()` and `location.replace` (`web/party/lib/party-mode.js:55-66`, `web/party/app.js:361-366`); BLUFF's result bar (`games:games/bluff/web/client.js:356-359`) |

Genuinely missing, and how the slice lives without each:

| Missing | Effect in slice 1 |
|---|---|
| `pregame` is not in the catalog (it lives in the contract extension, from which Party Core's game list is derived: `contracts/games/bluff.json:44`, `avrana/contracts/party_config.py:9-18,58-62`) | The Host's helper line is neutral, "Moves everyone to this game", which is true with and without a briefing. Copying the flag into the catalog is optional later work |
| Length, kind and how-you-play metadata (R1) | Tiles show players and screen. Those filter groups are not drawn |
| An EXPO cover (R4) | EXPO keeps today's fallback, its catalog icon on a plain cover (`web/party/app.js:96-104`). A drawn stand-in is not free: artwork references accept only a Games scene or a Kenney icon (`avrana/contracts/catalog.py:26-48`), so any new cover goes through `contracts/artwork.json` and the catalog, which is R4's work |
| Quick-start steps (R2) | Not drawn in slice 1. The premise and the rules sheet stand in |
| The in-round exception and countdown are not in the view (D9) | The Host-away line says "if Dana isn't back soon" and appears only where the rule applies and the shell is on screen: Home, the Party page and the briefing. While a round is on the Host keeps the role (`avrana/party/core.py:15-17,268`) and the shell is not on screen |
| A game page in Limited Mode does not follow the Party (`docs/design/LIMITED-MODE.md:165-170`; a paired change with Games) | The acceptance journey is a Full Mode journey. On a Limited phone the shell, the marks and the briefing work, and the return from a game is as it is today. Closing that gap is [follow-up work](#follow-up-work) F1, not part of this slice |
| Limited Mode names no games (no title requires a secure context today) | The consequence lines come from this phone's capability report, so they appear for the phones they are true for. The notice names the titles that report produces, or none |

### 3. Contract changes

No machine contract changes: routes, the session protocol, the catalog schema and the bridge
are untouched, so `npm run check:contract` and the Games repository are unaffected.

Documents, owner-merged, before or with the first PR that needs them:

- `docs/design/GAME-UX-CONTRACT.md` Rule 3.2 and a dated amendment on
  `docs/adr/0011-party-console-model.md` (decision 4): done in slice 0.
- `docs/UI-DESIGN-SYSTEM.md`: tokens, type, the navigation frame, in PR 1.1 with the code.
- `docs/design/LIMITED-MODE.md` §3.9, in the pull request that changes the notice's wording; the
  three required facts stay.
- `docs/design/ACCESSIBILITY.md`: no rule changes; MUST 4 is the one this slice finally tests.

### 4. Tests, and phone and accessibility checks

Automated, all existing commands (`docs/TESTING.md:35,87-104`). The npm scripts call `python3`;
on Windows run the same commands with `python`, and Linux CI is the authority:

| Check | What changes |
|---|---|
| `npm run test:unit` | `tests/unit/test_web_build.py` keeps guarding precache, inline code and jargon; new files join `SHELL` |
| `npm run test:modules` | New module tests: the view router (the location wins over the address; the bottom bar is absent on a briefing), Library grouping, search and filters, the view-mode and recents stores, status-to-wording mapping, Host away and passed detection (including "never during a round") |
| `npm run test:offline-browser` | `party.spec.ts`, `limited.spec.ts`, `assimilation.spec.ts` updated with the markup. New: the journey with a stubbed game page; the drawer and the Limited sheet over a briefing do not move the page and return focus; consequence lines in all four Library views; 44 px targets on every view; no sideways scroll at 360 and 375 px; nothing clipped at 200% root text |
| `npm run test:party-browser` | `tests/party/multi-client.spec.ts`: two and four phones through setup and start |
| Provider suite with a Games checkout (`playwright.provider.config.ts`) | `tests/provider/party-pregame.spec.ts` and `party-home.spec.ts` are the real acceptance journey with real BLUFF; they bind to BLUFF's `#bar` button texts, which this slice does not change |
| `npm run check:ui`, `check:repo`, `check:contract`, `python tools/repo-check.py` | compiled CSS, generated assets, catalog and documents stay fresh |

On real phones (the owner or someone the owner names; record in `docs/findings/`, alongside the
Tier 3 checklist in `docs/runbooks/party-https.md:250` and AVR-212):

- An iPhone in Safari and an Android phone in Chrome, each in Full Mode and in Limited Mode;
  three or four phones through the acceptance journey; once from the home-screen install.
- Largest system text on both phones: every view reflows, nothing is cut, the briefing's
  answers and Start stay reachable.
- VoiceOver and TalkBack through Home, Library, detail, briefing, drawer and sheet: every
  control has a name, the reading order is the visual order, focus goes into a sheet and comes
  back, turn and waiting lines are announced.
- The Host locks their phone for 75 s on Home and on a briefing: the Away line, then the
  hand-over notice, appear. The same during a BLUFF round: hosting does not move.
- Wi-Fi off and on: the reconnecting line, then recovery; rotate; one-handed reach of the bottom
  bar and the dock.

### 5. Dependencies and rollback

Depends on slice 0.1 to 0.4 and on nothing in Games.

Delivery as four PRs, each leaving `main` deployable, so no flag is needed:

| PR | Content |
|---|---|
| 1.1 | Tokens, Geist and compiled CSS; the frame (top bar with the Limited mark and the Party control, bottom bar, view router); the Party drawer (people, and today's chat while its hub answers) and the Limited sheet on the four ordinary pages; Home (who is here, and one row to the Library), Party and System; today's game list moved under Library unchanged; today's setup scene untouched |
| 1.2 | Library: covers, four views, search, the two filters, favorites, recents, consequence lines; Home's lead tile and its "Great for N" and "Recently played" rows, which are made of the same tiles. **As built (AVR-285):** a cover opens a sheet that holds today's tile and today's button, so nothing about starting a game changes before 1.3 draws the detail page |
| 1.3 | Game detail; the briefing redrawn; the drawer (people only) and the Limited sheet over it (needs slice 0 merged) |
| 1.4 | States (reconnecting, Host away and passed, the Host's notice and System's health line, the folded Limited notice, empty states), the accessibility pass, the phone findings |

Pictures of each pull request as built (before and after, and each state it adds) are in
[`slice-1/`](slice-1/), named for the pull request: `pr-1.1-*.png`, `pr-1.2-*.png`. They are
Chromium at phone sizes, not phones.

### Rules for every PR of slice 1

Each pull request keeps these working and says so in its report, naming the test that shows it.
A pull request that cannot keep one of them stops and says which.

- **Accessibility.** Every control has a name and a 44 px target; focus is visible, goes into
  whatever opens and comes back to what opened it; reading order is visual order; nothing
  scrolls sideways at 360 px; nothing is cut off at 200% text; reduced motion and higher
  contrast are honoured; state is never colour alone (`docs/design/ACCESSIBILITY.md`).
- **Reconnecting.** A phone that cannot reach the box says so and offers "Try again"; it
  recovers by itself when the network returns and when the page becomes visible again; a phone
  that wakes asks Party Core at once; a move made while it was away is followed on return
  (`web/party/app.js:575-583`). Of these, `tests/offline/party.spec.ts` "the offline copy"
  covers "Try again" and recovery when the network returns; a pull request that touches the
  others (waking, following a missed move) brings its own test for them.
- **Limited Mode.** The mode is always marked on the phone it applies to, with the three facts
  in plain words (not private, what is missing here, how Full Mode returns:
  `docs/design/LIMITED-MODE.md` §3.9) and, on the ordinary pages, the link that checks for the
  full version (the sheet over a briefing has no link that leaves it: slice 0.1); no padlock
  is shown; every member sees who is in Limited Mode; a phone that cannot play a title cannot
  choose Play and is told why; the shell works with no service worker and no secure context
  (`tests/offline/limited.spec.ts`).
- **The Party's rules.** One location, Host-only moves, Play or Watch, the server's blocker
  sentence, the Host hand-over rule: presentation changes none of them.

Each report also lists what only real phones can show for that pull request.

Rollback is the owner's, on the Pi, and has three steps. The flip alone is not a finished
rollback: a page that is already open keeps running the scripts it loaded.

1. **Flip.** `sudo bash ops/install-party-web.sh --rollback` points `current` at the release
   before the running one and touches nothing else: no service restarts, and a round that is on
   carries on (`ops/install-party-web.sh:32-43`). It goes back exactly one release; run it again
   to go back another (five are kept). The other route, `ops/deploy.sh` with the earlier SHA
   (`docs/runbooks/deploy.md:98-112`), restarts Party Core and is refused while a round is on
   (`docs/runbooks/deploy.md:61-63`), so the flip is the one to use for this slice.
2. **Reload.** Reload the Party page on every phone that has it open, or close and reopen it.
   The service worker is network-first (`web/party/sw.js:7-10`), so a reload on the Wi-Fi
   fetches the restored files; without a reload the phone keeps the newer page until it next
   navigates.
3. **Verify the restored build.** From the Party LAN,
   `curl -s https://party.avrana.net/party/version.json` shows the restored release's `build`
   and `commit`; `/party/api/status` shows the same under `web_release`; and on a reloaded
   phone `/party/diag/` shows that build as "Shell build". The deployment manifest still names
   the commit that `ops/deploy.sh` last deployed, because the flip does not rewrite it: note the
   flip in the deploy record. Then walk one phone through Home, the Library and a briefing.

Nothing on the server changed. `lg-favorites` and `lg-recent` are reused and the new keys are
additive, so going back loses no one's favorites. Game pages keep the palette they have in
either direction (their copy of it lives in Games).

## Slice 2: EXPO presentation

### 1. The working experience it delivers

EXPO as approved: the five zones in the field-unit treatment; the one live instruction on the
hand tray; hands of 13 and 14 in rows of seven; the "Yours / Tonoja" switch with a covered
count; the objectives control that opens every objective without blocking the hand; Burst
Transmission as the one equipment panel; the result as word, cause, evidence and every
objective's outcome; reconnecting and an away seat; below the size floor and at enlarged text,
one scrolling column with only the keys pinned.

The lifecycle does not change: EXPO's own setup before the first deal (the Host's mission choice
and "Deal mission N", the clock, agreeing Tonoja's seat), task selection, predictions, "Ready to
move out", "Begin mission", "Retry same tasks" and "Retry new tasks", the mission picker with
"Next mission", "End EXPO for everyone", "Look at the table", and the result's variants while a
seat is away or a crew decision is open (`games:games/expo/web/client.js:495,887-944,1222-1248`).

### 2. Existing backend support, and what is missing

Supported: every fact on the board is already in the view (`trick_leading`, `last_trick`,
`tasks[].state`, `result`, `cause`, `me.legal_cards`, `me.play_reason`,
`me.communication_options`, `tonoja`, `hand_counts`, `away`, the lifecycle reasons, `setup`).
The engine deals 14/13/13, 10 each, 8 each, or 13 each with seven Tonoja columns
(`games:games/expo/engine.py:382-404`). No engine change is needed, and the engine test files
must stay green untouched to prove it.

Missing for presentation: nothing. Three things the slice must do that the drawings do not yet
cover:

- **The undrawn states are designed inside this slice, first**: setup, task selection,
  predictions, ready and distress, the table menu, help and the log are the same client and
  must move to the new language with the board. They are drawn in this package's style and
  shown to the owner before the client is rewritten; they are this slice's work, not a
  separate one.
- **The remaining enlarged-text readability work is this slice's too.** REVISION-2 left EXPO at
  200% text "better, not good": a column two to three screens long, card ranks that grow only
  from 28 to 34 px, the suit word at 12 px in rows of seven, a 14-card hand in three rows of six
  at 320 px wide, and a result whose pinned choice takes 21 to 25% of the screen. This slice
  improves those without capping text scaling, and measures them again.
- **`px` to `rem`.** The client is entirely `px`, the body is fixed, the queries are height-only
  (`games:games/expo/web/expo.css:28,34,334-373`), although `contracts/games/expo.json:37`
  already declares `text_scalable: true`. This slice makes that declaration true.
- **Art.** The window's land is drawn shapes holding the place for a human-made or licensed
  environment piece. The slice ships without it and says so.

Optional server items, none blocking: D5 to D8 and mission names (see the table above). Tonoja's
covered cards stay a count, derived from `hand_counts.tonoja` minus the face-up tops.

### 3. Contract changes

None to machine contracts. `docs/design/GAME-UX-CONTRACT.md` §15 "EXPO (current)", in the Party
repository, is updated to describe the new client; that is a document note, not a paired code
change. Fiction words (the trump suit, Tonoja, the radio token) stay as today
until the owner names them (EX-40).

### 4. Tests, and phone and accessibility checks

- `python -m pytest -q` in Games: `tests/test_expo*.py` unchanged and green.
- `games:tests/_expo_phone.mjs` asserts the zone order, a mission stage of 15 to 25% of the
  screen, no scrolling and hand cards of at least 40 × 44. It is rewritten to the new
  specification: 44 × 44, no scrolling at or above the floor, one scroller below it.
- `games:tests/playtest_expo.mjs` and `playtest_expo_party.mjs` drive ids and `data-key`s, and
  the second also the texts "Deal mission 1" and "Begin mission". Keep those hooks so the
  playtests survive. `games:tests/expo_director_test.mjs` covers the motion director and must
  stay green or move with it.
- New: a layout measure in the Games tests, ported from this package's validation (hands of 8,
  10, 13 and 14 and two players at 360 × 640, 390 × 664, 390 × 844 and 320 × 568; no overlap;
  targets; every result outcome reachable), and the same at 150% and 200% text, for the newly
  drawn states as well as the board.
- Party's provider suite with the Games branch checked out, to prove the Party round still runs.
- Phones: two, three, four and five players on real phones. An iPhone SE in Safari has about
  553 px of height, which is below the board's floor, so that phone gets the scrolling column
  and must be one of the test phones. Largest system text; VoiceOver card names and the turn
  announcement; a colour-vision check of the four suits; a seat dropping and returning.

### 5. Dependencies and rollback

Independent of slice 1, and it does not wait for the Party layer's geometry (slice 0.5): if
that is settled before this slice ends the board leaves the area free, and if not slice 5
makes room later. Branch from Games `origin/main`, not from the local working tree.

Rollback: redeploy with the earlier Games SHA (`docs/runbooks/deploy.md:101-112`). Only
`games/expo/web/` changes; the result build id excludes `web/`
(`games:core/party_session.py:72`), and no state is migrated.

## Slice 3: Party-owned chat

### 1. The working experience it delivers

The drawer's Chat tab on every shell page and over a briefing; an unread count on the Party
control; messages under Party names and faces; a line when this phone is out of reach. Nothing
appears inside a game until slice 5.

### 2. Existing backend support, and what is missing

Exists: a client boundary with reconnect and message checks (`web/party/lib/party-chat.js`) that
talks to the old hub at `/chat/ws` on the retiring LAN Games runtime, under its own identity
(`wc-token`), connected only while the chat is open. Party Core has no chat state and no chat
route (`avrana/party/core.py`, `avrana/party/service.py:333-401`).

Essential and missing:

- Chat state in Party Core: a bounded message list, kept in memory like the Party itself and
  gone when the Party ends.
- Routes under `/party/api/`: send (members only, identified by the device cookie like every
  other member route) and delivery, either on the existing long poll or beside it.
- Limits: length (the old hub allows 400 characters) and rate.
- The Limited listener serves the same routes, and the Limited sheet's "not private" fact then
  covers chat too.

Optional: photos (the old hub carries them), reactions, system lines for joins and hand-overs,
suggestions in the stream (C1), persistence across a restart, mute or remove.

### 3. Contract changes

A new ADR for Party-owned chat (scope, identity, retention, Limited Mode exposure, the end of
the old hub's role; ADR 0014 already retires that runtime). `docs/design/PARTY-LIFECYCLE.md` and
the service's route documentation gain the routes. Rule 3.2's sentence from slice 0.1 widens
from people to chat. No Party to Games contract changes.

### 4. Tests, and phone and accessibility checks

- `tests/unit/test_party_core.py`, `test_party_service.py`: membership required, ordering,
  bounds, limits, cleared when the Party ends, both listeners.
- `tests/offline/party-chat.test.mjs` rewritten for the new client: unread counting, no
  duplicates after a reconnect.
- `tests/party/multi-client.spec.ts`: two phones exchange messages; the badge; chat over a
  briefing; a phone that was away receives what it missed.
- The load and soak harness (ADR 0001) on the Pi for long-poll fan-out with a full room.
- Phones: the keyboard does not cover the message field on iOS and Android; VoiceOver and
  TalkBack announce new messages politely and never interrupt "your turn"; largest text;
  names in other scripts.

### 5. Dependencies and rollback

Depends on slice 1 and the ADR. Rollback: the routes are additive, so restoring the previous web
release hides the feature, and redeploying the earlier Party SHA removes it. State is in memory
only. If slice 0.2 kept today's chat, a rollback returns to it.

## Slice 4: briefings for Arcade and PS1 titles

### 1. The working experience it delivers

Gauntlet II gets the same path as BLUFF: detail, briefing, Play or Watch, Start. Seats are
visibly scarce (two of four). A phone that cannot play the title (by its own capability report,
not by its mode alone) learns before the stream starts that it sits this round out. Someone not playing a title with no watch view gets a plain "Game in progress, you
are not playing this round" (owner decision Q12, `docs/design/GAME-UX-CONTRACT.md` §18).
The same applies to the PS1 titles when they exist as Party games.

### 2. Existing backend support, and what is missing

Exists: the pregame machinery is generic. A game configured with `pregame` opens in `setup`, and
its runtime is launched only when the Host starts the round
(`avrana/party/core.py:405-414,464-482`, `avrana/party/service.py:123-147`). The briefing from
slice 1 draws any title. Play / Watch gating on a Limited phone exists
(`web/party/lib/limited.js:46-61`).

Essential and missing:

- `pregame: true` on `contracts/games/arcade-gauntlet2.json`; Party Core derives its game list
  from the contract.
- The arcade page for a phone that arrives during `setup` or was not given a place. The arcade
  already admits by the ticket's role and refuses the rest (`arcade/stream.py:166-170`), and
  with a pregame the roles come from the answers (`avrana/party/core.py:476-479`), so seating
  itself needs no new rule.
- The not-playing state: where it is drawn, and what Party access it keeps (required follow-up 4
  in the game UX contract).
- Briefing content for these titles (`onboarding.json`, or the catalog summary as a fallback).
- For PS1: the titles are catalog entries only, not installed and not Party games; their runtime
  is on an experiment branch (`docs/TESTING.md:62-66`). That integration is a separate piece of
  work and comes first.

### 3. Contract changes

The contract extension on the arcade title and the regenerated catalog. The accepted rule does not need reversing: ADR 0011 decision 1 already sends a pregame
title to `setup` and any other straight to the game, so this slice only declares more titles as
pregame. The not-playing state may need a dated note on ADR 0010 decision 1 or ADR 0011
decision 3, which is the owner's call.

### 4. Tests, and phone and accessibility checks

- `tests/unit/test_party_core.py`: the arcade configuration through setup, limits of two.
- `tests/offline/arcade.spec.ts`: the arcade page for a player, a watcher where watching
  exists, and the not-playing state.
- `npm run check:contract`, `check:repo`.
- On the Pi with phones (`docs/runbooks/arcade-party-provider.md`): the stream starts only at
  Start; a Limited phone; four people with two seats; the TV.

### 5. Dependencies and rollback

Depends on slice 1, on the Q12 design, and on the owner choosing this over today's direct start
(decision 3). Rollback: set the flag back and redeploy; the title starts directly again. The
shell needs no change either way, because slice 1's wording is neutral.

## Slice 5: a Party layer during play

### 1. The working experience it delivers

A small Party control inside a running game: who is here, unread chat, and the drawer over the
game without leaving it. The platform rules overlay the owner has already decided (Q11) is its
natural first tenant.

### 2. Existing backend support, and what is missing

Exists: nothing drawn. The bridge's verbs are closed (`hello`, `ticket`, `end`, `home`,
`playAgain`; pushes `view`, `navigate`, `ticket`, `result`: `web/party/lib/bridge.js:12-18,33`),
and its view carries the Host, the location and the round only (`:60-74`). Games wrap their page
in `#avrana-game-room` and hide their bar in a Party
(`games:web/avrana-integration.js:140-152`, `games:web/avrana-integration.css:45-49`).

Essential and missing: the geometry (slice 0.5); who draws the layer, the Party in a visible
frame or each game from bridge data; roster and chat on the bridge; room for it in each game's
layout (BLUFF, EXPO, the arcade page); and a path in Limited Mode, where there is no game
origin and no bridge (`avrana/party/service.py:30-35,234-240`) and game pages do not follow the
Party yet (`docs/design/LIMITED-MODE.md:26-27,169`).

### 3. Contract changes

The largest of any slice: an amendment to ADR 0011 decision 5 (already required for the rules
overlay, follow-up 1 in the game UX contract); new verbs in ADR 0013 with
`contracts/vectors/party-bridge.v1.json`, the hashes in `contracts/party-games.v0.json` and the
shim vendored in Games (`games:provider/avrana-contract.json:6-26`); the reserved region in the
game UX contract §8 moving from proposed to accepted. Paired PRs, Party first, one merge set.

### 4. Tests, and phone and accessibility checks

- Bridge vectors in both repositories (`tests/offline/party-bridge.test.mjs`,
  `tests/offline/bridge.spec.ts`, `games:tests/avrana_bridge_test.mjs`) and the cross-repository
  contract check.
- Each game's layout test with the region reserved (`games:tests/_expo_phone.mjs` after
  slice 2); `tests/provider/game-origin.spec.ts`.
- Phones: the layer never covers a game control; safe areas; reach; the stream's frame rate on
  the Pi with the layer open; a screen reader moving between the layer and the game.

### 5. Dependencies and rollback

Depends on slices 1 and 3 and on the geometry decision. Games should detect the new verbs
rather than assume them, so the Party side can be rolled back alone; otherwise both SHAs go back
together.

## Follow-up work

Named so that it is not lost. None has a Linear issue yet (see the top of this file); each
needs one before it starts.

| # | Work | Why it is separate | Where it is described |
|---|---|---|---|
| F1 | **A game page in Limited Mode follows the Party.** Today game pages and the arcade page load the follower only in a secure context, so a Limited phone inside a game is not moved when the Host moves the Party, and its return from a game is as it is today | An existing gap, not made by the redesign. A paired Party and Games change, one merge set. Slice 1's acceptance journey is a Full Mode journey because of it, and slice 5 needs it | `docs/design/LIMITED-MODE.md:165-170` |
| F2 | **Design the geometry of the Party layer during play**: where the control sits, what it may cover, how each game leaves room | The owner made it a separate design task (slice 0.5). Slice 5 cannot start without it | Slice 5; brief §29 |
| F3 | **The Games copies of the palette.** The pre-game layer and the Back to Party bar in Games hold hex copies of today's tokens (`docs/UI-DESIGN-SYSTEM.md`, "Intentionally temporary"). After PR 1.1 they are the old palette beside the new shell | A Games change, cosmetic, no contract | Games `web/shared.css`, `web/avrana-integration.css` |
| F4 | **Real-phone acceptance of slice 1**, recorded as a dated finding | Only the owner, or someone the owner names, can do it | Slice 1, section 4 |

## What this plan does not settle

- Dates, order beyond the dependencies above, and who does what.
- The owner decisions still open in [BACKEND-GAPS](BACKEND-GAPS.md#open-owner-decisions); only
  the ones a slice needs are repeated here.
- Anything about deployment. Merged is not deployed, and the Pi is the owner's.
