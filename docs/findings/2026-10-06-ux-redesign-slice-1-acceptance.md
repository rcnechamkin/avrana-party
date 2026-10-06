# UX/UI redesign slice 1: acceptance evidence for PR 1.4 (AVR-287) — 2026-10-06

Dated evidence from one Windows laptop. **No real phone, no screen reader, no Safari, no Pi and
no deployment was involved in anything below.** Everything that passed, passed in Chromium at
phone sizes against the repository's dev server. What only real phones can show is listed at
the end as not done; it stays with AVR-295 (and AVR-212 for the appliance).

## Builds

| What | Exactly |
|---|---|
| Party, the change under test | branch `feat/avr-287-shell-states-accessibility` at `0ac53cce6a53f9060f7251516adb16ce1d86c56d`; the shell is tree `bbcfad28ba4d98f1b9eff6b022eececd20e92518` (`git rev-parse <commit>:web/party`). Later commits on the branch that change only documents and pictures leave that tree as it is |
| Party, the base | `origin/main` `1a2b89737e7d` (the merge of PR #82) |
| Games, for the real BLUFF | `origin/main` `a4489729e1d0522a302b0475a7631ed90c219812`, in a temporary detached worktree (the local Games checkout is on an older branch and was not used) |
| Browser | Playwright 1.63's Chromium, phone-sized contexts |
| Host | Windows 11; Python as `python`; suites run one at a time |

## Automated results

| Suite | Command (Windows form) | Result |
|---|---|---|
| Browser modules | `node --test "tests/offline/*.test.mjs"` | 163 pass, 0 fail |
| Offline browser, both projects | `AVRANA_PYTHON=python npx playwright test -c playwright.offline.config.ts` | 178 pass, 0 fail |
| Party, three and four phones | `AVRANA_PYTHON=python npx playwright test -c playwright.party.config.ts` | 32 pass, 0 fail |
| Provider, the real BLUFF | `playwright.provider.config.ts` with `AVRANA_GAMES_REPO` at the Games worktree above | 40 pass, 0 fail; 30 skipped (the `iphone-size` project, as that suite is configured to do on this host) |
| Rollback rehearsal, to `origin/main` | `AVRANA_PYTHON=python npx playwright test -c playwright.rollback.config.ts` | 1 pass |
| Rollback rehearsal, to `578534f` | the same with `AVRANA_ROLLBACK_FROM=578534f` | 1 pass |

Python unit tests and the repository checks are reported in the pull request, because they
also read this file.

An earlier state of the branch (`e6f536a`, shell tree `22edf925d0d2`) was run in full by a
separate verifier with the same counts except the Party suite (30 then; two tests were added
after review). A review of that state found three faults, fixed before the commit above and
each now held by a test that fails without its fix: a heads-up the Host had dismissed came
back after a moment out of touch with the box; the Host's System page could say "Everything's
working" while the shelf marked a game off for a reason the box's account does not name; and
"hosting now" from one Party could linger into a new one.

## The four-phone journey (Full Mode, real BLUFF)

`tests/provider/party-pregame.spec.ts`, "the acceptance journey on four phones". Ana hosts; Ben,
Cy and Dee are guests. One test, in order, with what it holds each step to:

1. **Home** on all four: "Four of you are here."; a lead cover; no button that starts anything;
   nothing sideways. Ana reads that she hosts; Dee reads "Ana is the host and picks the games."
2. **Library** on all four: the first shelf is "Great for four" and BLUFF is on it.
3. **BLUFF's page** on all four: "Room for all four of you." and BLUFF's own premise. Only Ana
   has "Start for everyone"; each guest reads "The host starts it. Ana chooses what the Party
   plays." Browsing moved nobody: the Party is still at home.
4. **The briefing** on all four after Ana starts it: four in the line-up, no bar of places, no
   Start for a guest. Ana and Ben choose Play, Cy and Dee choose Watch: "2 playing · 2
   watching", and Ana's Start is on.
5. **The round**: all four phones are in BLUFF; Ana and Ben are dealt two cards each; Cy and
   Dee are watchers.
6. **The result**, held for the Host: Ana has "Play again" and "Party Home"; no guest has
   either, and no guest's phone has left.
7. **Play again**: a new briefing on all four, every answer asked again; a second round is
   played and finished.
8. **Party Home**: all four are home together with the frame whole. Ana's and Ben's Home says
   "You played this last." under BLUFF; Cy's and Dee's does not, and their phones hold no
   recently played at all (the owner's decision of 2026-10-06).

Pictures of the run: [`pr-1.4-journey-1.png`](../design/ux-redesign/slice-1/pr-1.4-journey-1.png),
[`pr-1.4-journey-2.png`](../design/ux-redesign/slice-1/pr-1.4-journey-2.png).

The journey is a Full Mode journey. A phone in Limited Mode inside a game page is not moved
when the Party moves; that is an older gap, not made or changed here, and is AVR-290.

## The rollback rehearsal

`tests/rollback/rollback.spec.ts`. Two releases are built with the real build step
(`avrana.web.build`) and a `current` link is flipped between them under a running dev server
whose Party Core is not restarted.

| Run | NEW (this change) | OLD (gone back to) | Result |
|---|---|---|---|
| 1 | build `0ac53cce6a53` | build `1a2b89737e7d`, `origin/main` | pass |
| 2 | build `0ac53cce6a53` | build `578534f6c19c`, the last release before the redesign | pass; that build has no frame, so its shelves were not walked, only its game list and a briefing |

Each run showed, in order: the new build served and running with its offline copy; a favorite,
a played game, a name and the Library view kept on the phone; **flip**, after which the box
serves the old build, the Party still has its one member, and the page that was open is still
the new one (the flip alone is not a finished rollback); **reload**; **verify**: the old build
is the one running, the only offline copy is the old build's, the diagnostics page's "Shell
build" names it, the four kept values are exactly what they were, and the same person is still
the Host of the same Party; a briefing opens and closes on the restored build; then forward
again to the new build with everything still kept.

Not shown by it: `ops/install-party-web.sh --rollback` itself, nginx, the Pi, the
`web_release` field of the status endpoint, Safari, or a real phone's cache.

## The accessibility pass

`tests/offline/a11y.spec.ts` (10 tests, two projects), `tests/party/a11y.spec.ts` (3 tests)
and the fold test in `tests/offline/limited.spec.ts`. The helpers are first run against
planted faults (a dim line, a nameless faint-edged button, a label that points nowhere, a
control drawn out of order, a button with its focus ring taken away, something moving) and
must catch each.

What is covered, exactly:

- Contrast (4.5:1), edges (3:1), names and reading order: every page, the Library's sheets and
  empty states, the drawer, the rules, the briefing, and every state this pull request adds.
- The same screens drawn as a phone that asks for more contrast (7:1) and less motion (nothing
  may move) draws them.
- One top heading, no skipped level, 44 px targets, nothing sideways: every Party screen and
  state in the Party spec; the other pages by the suites that came before.
- A Tab walk with a visible ring required at every stop: the four places and a game's page;
  every Party screen and state, where it must also reach that state's own button ("Try again"
  on a page and on a briefing, both Dismiss buttons, the fold). The Library's sheets and empty
  states are not Tab-walked.

It found four things, fixed in the same pull request:

- "Choose your name" from Home or from a game's page went to the Party page without a step the
  phone's Back could undo; it is now a step, and Back returns where the person was;

- the edge of the search and name fields was 1.68:1 against the page; it is now the control
  colour, above 3:1;
- sheets carried an invisible "Close" button from the component library: an extra Tab stop with
  see-through words; removed (a tap outside still closes);
- on a short screen the rules sheet's "Got it" could sit below the fold with no way to reach
  it; the sheet's body now scrolls and the button stays in reach.

## Not done: needs real phones

None of these was done. Each is from section 4 of slice 1 in the
[implementation plan](../design/ux-redesign/IMPLEMENTATION-PLAN.md) and belongs to AVR-295.

- An iPhone in Safari and an Android phone in Chrome, each in Full Mode and in Limited Mode;
  three or four phones through the journey above; once from the home-screen install.
- Largest system text on both phones.
- VoiceOver and TalkBack through Home, Library, a game's page, the briefing, the drawer and
  the sheet, and through the new states: whether "Reconnecting", the lost-the-box notice, the
  Host-away line and the hand-over notice are announced, and announced once.
- The Host locking their phone for 75 s on Home and on a briefing (the Away line, then the
  hand-over), and during a BLUFF round (hosting does not move). The suite moves a simulated
  clock; no phone was locked.
- Wi-Fi off and on: the reconnecting line, the notice after about 10 seconds, recovery;
  whether 10 seconds feels right on the Party's own Wi-Fi; a phone waking from sleep.
- Rotation; one-handed reach of the bar and the dock.
- The rollback flip on the appliance.

## Not covered by any test here

- A briefing replaced by another round's briefing in a single update while a phone is out of
  touch: the dev party has one game with a briefing.
- "Nobody is hosting right now." on a briefing, in a browser (the sentence is tested as a
  function only).
- The catalog-only page (no Party Core) has no reconnecting line; it keeps the behaviour it had.
- The dev server's `/__test__/party/advance` has no unit test of its own; the Party suite uses
  it throughout.
