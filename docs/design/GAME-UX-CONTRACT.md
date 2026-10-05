# Shared game UX and interaction contract

Status: **contract in three labelled layers (AVR-56, 2026-10-04); not validated on phones.**

Every rule below carries one of three labels. They are not interchangeable.

| Label | Meaning | Authority |
|---|---|---|
| **[Implemented]** | In source on `main` of the named repository on 2026-10-04; a file is cited. Not a claim of deployment or phone proof | the cited code and its tests |
| **[Accepted]** | Decided elsewhere: an accepted ADR, a current repository document with scoped authority (ACCESSIBILITY, UI-DESIGN-SYSTEM, AGENTS), or the owner's direction recorded in [AVR-56](https://linear.app/avranakern/issue/AVR-56). Only what the source itself says is accepted; any elaboration in the same rule is marked **[Proposed]** | that source |
| **[Proposed]** | Drafted by this document. Direction for review, not contract, until the owner accepts it | none yet |

Where AVR-56's direction and an accepted ADR disagree (Rule 4.4), the rule says so and is not
contract until the ADR is amended. Nothing here is deployed or validated on real phones by this document.
[SYSTEM](../SYSTEM.md) says what runs. AVR-56 is formally blocked by AVR-27 (four-human offline
BLUFF acceptance), which has not happened; the owner authorized writing the contract first.
[§19](#19-evidence-still-outstanding) lists what that acceptance may change.

Games-repository paths (`games/...`, `web/...`, `core/...`) refer to `avrana-party-games`
`origin/main` at `5308705`; all other paths are this repository at `83788b3`.

## 1. What this document owns

It owns one question: **where the line runs between Avrana and a game on a player's phone, and
which behaviours are the same in every game.** It does not restate its neighbours.

| Question | Owner |
|---|---|
| Party page theme, tokens, `avrana-*` classes, build, avatar and artwork generation | [UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md) |
| The accessibility MUST table and the manifest's accessibility block | [ACCESSIBILITY](ACCESSIBILITY.md) |
| Location, presence, host and seat state machines | [PARTY-LIFECYCLE](PARTY-LIFECYCLE.md), ADRs [0010](../adr/0010-party-pregame.md), [0011](../adr/0011-party-console-model.md) |
| The wire between Party and Games | [PARTY-GAMES-CONTRACT](PARTY-GAMES-CONTRACT.md), `contracts/party-games.v0.json`, [ADR 0006](../adr/0006-party-session-protocol.md) |
| Chat transport, policy and presentation | [COMMUNICATION](COMMUNICATION.md) (proposed) |
| Full Mode / Limited Mode capability rules | [FULL-MODE](FULL-MODE.md), [LIMITED-MODE](LIMITED-MODE.md) |
| Product aspiration and the quality gate | [AVRANA-EXPERIENCE](../AVRANA-EXPERIENCE.md) (aspirational) |
| Platform versus game responsibility, the briefing, rules access, unavailable actions, shared interaction rules, system feedback, art slots | **this document** |

This document changes no machine contract. Where it believes one must change, it says so in
[§20](#20-machine-contract-changes-this-document-proposes-but-does-not-make).

## 2. The boundary

**Rule 2.1 [Accepted, AVR-56].** The common interaction layer "should feel coherent across Party
and games without making every game look identical"; "games retain intentional visual identity";
system feedback primitives are "not a requirement that every game share the same art direction
or sound design".

**[Proposed]** reading of it: Avrana is recognizable by *behaviour*; a game is recognizable by
*look and sound*. A game MAY have an art direction, palette, typeface, motion language and sound
design unrelated to the Party page. [UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md) ("Platform UX and
game identity") names "dark calm surfaces" among the shared ground; this document reads that as
describing platform-shaped surfaces (the Party page, the briefing shell), not a constraint on a
game's play viewport. If the owner means it for play too, this paragraph is wrong and Rule 4.2
narrows.

**Rule 2.2 [Accepted, ADR 0011 decision 5; AVR-56].** Once play begins, platform chrome recedes
and the game owns the viewport.

| Concern | Platform owns | Game owns |
|---|---|---|
| Who is in the Party, who hosts, where the Party is | everything | nothing; a game keeps no host and no membership (ADR 0006 amendment 2026-10-04) |
| Name and avatar | the identity and its picture ([§6](#6-player-identity-and-avatars)) | where and how large it is drawn in play; a game-local persona if its rules need one |
| Briefing (pre-round) | the shell: layout, roster, Ready/Watch, Start, rules sheet, host line ([§4](#4-the-briefing)) | the content: title, art, accent, premise, rules, example, declared settings |
| Play | reconnect recovery, the move to the next place, at most one host control when the game draws none | the whole viewport: board, HUD, controls, feedback, sound, motion, its own help entry |
| Results | holding the Party there; the host's Play again / Party Home verbs | how the result looks and what it celebrates |
| Rules content | the structure and the baseline renderer ([§5](#5-rules-content)) | every word, and whether to draw its own richer rules screen in play |
| What is legal | nothing; there is no Avrana rules engine | all of it ([§7](#7-actions-legality-and-unavailable-explanations)) |
| Interaction floor | touch target, focus, confirmation, sheet and reduced-motion rules ([§8](#8-controls-layout-and-surfaces), [§9](#9-accessibility-and-per-device-preferences)) | meeting the floor in its own visual language |
| System cues | join, leave, ready, attention, connection ([§11](#11-system-feedback-sound-haptics-motion)) | all game sound, music, haptics tied to game events |
| Icons | system controls: Lucide ([UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md) "Iconography") | game art; never borrowed from the system set to mean a game concept |

**Rule 2.3 [Proposed].** A game MUST NOT restyle or imitate platform surfaces that carry trust:
the Limited Mode notice, the connection state, the host line, the Ready/Start controls of the
briefing. A game MUST NOT draw a control labelled as a Party action (End for everyone, Party
Home, Play again) unless it calls the Party's verb for it.

## 3. One Party, one game: the phases

The location model is ADR 0011's: `home | setup | game | results`. This section is the UX reading
of it and of the owner's briefing standard in AVR-56.

**Rule 3.1 [Accepted, AVR-56; Implemented].** The Host selecting a game moves the Party into
that game. Followers do not join the game: there is no per-game Join, lobby admission or
second membership step. `destination()` in `web/party/lib/party-mode.js` moves every member's
page with `location.replace`, on load, on reconnect and on every change.

**Rule 3.2 [Accepted, AVR-56].** The briefing is a state *of the selected game*, not a second
membership ceremony. The behavioural reference is the Mario Party pre-minigame screen: title
and art, a short explanation, rules access, roster and Ready state, Host Start; Watch as a
secondary round-role choice when the game supports it.

Today the briefing is `location.at = setup` with `location.game` set, drawn by the platform shell
on the Party page (`#scene` in `web/party/index.html`, `renderScene` in `web/party/app.js`; ADR
0011 decision 4). That is compatible with Rule 3.2 as long as the screen reads as the game's
pre-round screen and not as Party Home: the library, chat row and "This phone" MUST NOT be
visible in it **[Implemented: `show('scene')` hides `#main`]**. Which page or origin draws the
shell is an implementation matter and may move with ADR 0013; the behaviour is the contract.

**Rule 3.3 [Accepted, AVR-56; Implemented].** While the Party is in a game, a non-host has no
normal route back to Party Home or to another game. The integration bar and every
`[data-avrana-global]` control are hidden in a Party (`web/avrana-integration.css`, games); a
page in the wrong place is moved back (`web/party/lib/party-follow.js`).

**Rule 3.4 [Accepted, ADR 0011, AVR-56].** The Host owns Party lifecycle transitions: select,
Start, End, Play again, Party Home. Leaving a game or returning to Party Home is a Party-level
host transition; a follower's own actions never change the location (ADR 0011 decision 1).
**[Proposed]** generalization of ADR 0011 decision 6, which says it of BLUFF's forfeit: a game's
own forfeit or sit-out is a game rule and MUST NOT move the player's page.

**Rule 3.5 [Accepted, AVR-56; Implemented].** Reconnect is recovery into the current Party
state. A phone that reloads, wakes or regains Wi-Fi lands where the Party is now, in its
existing role, with no offer, banner or Rejoin button (`party-follow.js` `onView`; a move that
arrives offline waits for `online`). **[Proposed]**: it MUST NOT pass through onboarding or the
briefing again if the round has started.

| Phase | `location.at` | Who draws | Platform chrome | Host can | Non-host can |
|---|---|---|---|---|---|
| Home | `home` | platform | all of it | select a game | browse, edit profile; chat where Party Chat is shown (the section is hidden until it is available) |
| Briefing | `setup` | platform shell, game content | the shell is the screen | Start; choose another game; set declared settings (**not built**, §4.4) | Ready or Watch; read rules |
| Play | `game` | game | none persistent; reconnect state only | End for everyone (confirmed); host actions the game defines | play or watch; open rules |
| Results | `results` | game | none persistent | Play again; Party Home | look; wait for the Host |

**Rule 3.6 [Proposed].** In Play and Results the platform MAY show only: a connection-lost state
while it is true, and a system cue ([§11](#11-system-feedback-sound-haptics-motion)). It MUST
NOT show Party prose ("0 playing · 0 watching"), a persistent bar, or its own brand mark over
the game. A game SHOULD NOT spend its own play viewport on the platform's brand either.

**Rule 3.7 [Implemented; Accepted, ADR 0011 decision 5].** A game that draws the Host's controls
itself marks an element `[data-avrana-party-shell]` and uses `window.AvranaParty` (`isHost`,
`hostName`, `end`, `goHome`, `playAgain`, `onChange`). A game that does not gets one host-only
"End game for everyone" control from the platform (`party-follow.js` `fallbackControls`).
`isHost()` only decides which controls are drawn; a host action inside a game is authorized by
the Party at the action (ADR 0006 amendment 2026-10-04).

**Rule 3.8 [Proposed].** Everyone who is not the Host MUST always be told who they are waiting
for, by name, in the same place the Host's control sits ("Waiting for Dana to start",
"Waiting for Dana to choose what's next"). **[Implemented]** in the scene (`app.js`
`scene-status`), BLUFF's results bar and the shared "Round over" panel (`web/hubnet.js`).

## 4. The briefing

### 4.1 Composition

**Rule 4.1 [Accepted, AVR-56; ADR 0011 decision 4].** The briefing shows the game's title and
art, a short readable explanation, rules access, the roster with each person's state, the
player's own round choice, and the Host's Start or everyone else's waiting line. **[Proposed]**:
that is also their order of visual weight.

| Slot | Supplied by | Today |
|---|---|---|
| Title, art, accent | game (catalog: `name`, `artwork`, `accent`) | **[Implemented]** `scene-title`, `scene-art`, `--game-accent` on the cover only |
| Premise | game (`onboarding.json` `premise`, else catalog `summary`) | **[Implemented]** |
| Rules entry "How to play" | shell; content from the game | **[Implemented]** `#rules` dialog, `openRules` |
| Roster with state | platform | **[Implemented]** `avrana-lineup`: Gaze avatar, host crown, Playing / Watching / Choosing as differently shaped icon badges with an accessible name (no visible word); the host crown likewise; away is opacity only (P-10) |
| Ready / Watch | platform | **[Implemented]**, as ADR 0011 decision 4 specifies: two large choices "Play this round" / "Watch this round" (`avrana-choice`, `aria-pressed`) |
| Host Start, or the waiting line | platform | **[Implemented]** `scene-start`, disabled with Party Core's `blocker` sentence as text |
| Host: choose another game | platform | **[Implemented]** `scene-cancel` |
| Host settings | game declares; shell draws | **not built** ([§4.4](#44-settings)) |
| Fake-turn example | game supplies; shell draws | **not built** ([§4.3](#43-simple-games-the-reusable-pattern)) |

**Rule 4.2 [Proposed].** A game's accent and art MAY tint the briefing (cover, primary button
fill, background wash) so that two games' briefings do not look like the same page with a
different icon. The shell's layout, control positions, type scale and wording stay fixed.
Today only the cover takes the accent.

### 4.2 Ready, Watch, Start

**Rule 4.3 [Accepted, ADR 0010; Implemented].** Every member who is here answers once per round:
play or watch. They may change their answer until the Start. Only the Host starts
(`POST /party/api/session/start`); Party Core refuses until everyone here has answered and the
player count is within the game's limits (`avrana/party/core.py` `setup_status`). Away members
do not block. Roles change only at this boundary; a late arrival watches.

**Rule 4.4 [AVR-56 owner direction; conflicts with accepted ADRs; not contract until an ADR is
amended].** AVR-56 says the briefing shows "roster/Ready state, and Host Start" and that
"Watch/Spectate may exist as a secondary round-role choice when the game supports it".

What is accepted and built today says something different, and the code conforms to it:

- ADR 0011 decision 4 specifies "two large **Play this round / Watch this round** choices", and
  UI-DESIGN-SYSTEM lists Play and Watch both as primary buttons.
- ADR 0010 decision 1 refuses the Start until every member who is here has chosen.
- ADR 0012's shell consequence relies on Watch never being taken away: a phone that cannot play
  here "may always choose Watch, so it can never hold up a round" (`seatChoice()` in
  `web/party/lib/limited.js`).
- The shell does not read the Game Contract's `spectators` field, and one contract already says
  `"spectators": "none"` (`contracts/games/arcade-gauntlet2.json`).

Making Watch visually secondary, or absent for a game without spectators, is therefore a change
to ADR 0011 decision 4 that interacts with ADR 0010 decision 1 and ADR 0012. This document does
not make it. The decisions are Q1, Q2 and Q12 in
[§18](#18-open-questions-for-the-owner); the differences are recorded as P-1 to P-3 in
[§16](#16-current-deviations-observations-not-tasks).

**Rule 4.5 [Accepted for Limited Mode, ADR 0012; Implemented].** A phone that cannot play this
game here sees Play disabled with the reason in words beside it, and Watch stays available
(`seatChoice()`, shown in `scene-seat`). **[Proposed]**: the same for any other reason a phone
cannot take a seat. What such a phone may answer when the game supports no spectators is
undecided (Q12).

**Rule 4.6 [Accepted, ADR 0010].** A game in a Party round MUST NOT run a second lobby: its own
ready, start and settings verbs are refused and the launch roster is seated at once
(`core/session.py` `party_start`, games).

### 4.3 Simple games: the reusable pattern

**Rule 4.7 [Accepted, AVR-56].** For a simple game the game provides content and Avrana provides
the familiar shell. The briefing covers: the objective, the basic flow, the controls or actions,
and a clear Ready.

**Rule 4.8 [Accepted, AVR-56].** A static or lightly animated *fake-turn example* is preferred
over maintaining a second interactive tutorial engine. **[Proposed]**: a game MUST NOT be
required to ship a playable tutorial. **[Proposed]** form: an ordered list of one to four frames, each an image from the
game's own art plus one caption, shown by the shell as a strip the player steps through; with
reduced motion it is the same frames without transitions. **Not built.**

**Rule 4.9 [Implemented; Accepted, ADR 0011 decision 4].** First play: a player who has not
acknowledged this game's briefing version sees How to play before their first Ready, and
"Got it, I'll play" is their Ready (`app.js` `choose` / `acknowledged`). The acknowledgement is
per browser (`localStorage`, key and version from the game's `ack`); it is a convenience, not an
identity or a record. A returning player goes straight to Ready.

**Rule 4.10 [Proposed].** The briefing MUST be readable in under about twenty seconds for a
simple game: a premise of at most two sentences and at most five rule sections of at most five
short points each. BLUFF's `onboarding.json` (five sections of 2, 4, 5, 3 and 3 points) is the
reference size.

### 4.4 Settings

**Rule 4.11 [Accepted, AVR-56].** "Host settings are optional and should not appear unless the
game genuinely needs pre-start configuration."

**[Proposed]**: a game with sensible defaults shows none; settings are the Host's; everyone else
sees the chosen values as plain text, not disabled controls.

**[Proposed]** shape: the game declares a short list of settings from a closed vocabulary
(`choice`, `toggle`, `count`), the shell draws them in the briefing between the premise and the
roster, and the game validates the values at the start and may refuse with a sentence. This
needs the values to reach the game with the launch, which the session protocol does not carry
today ([§20](#20-machine-contract-changes-this-document-proposes-but-does-not-make)). **Not
built.** Whether a game may instead draw its own settings panel inside the shell is an open
question ([§18](#18-open-questions-for-the-owner) Q3).

### 4.5 Heavy games: Quick Start plus Rules Guide

**Rule 4.12 [Accepted, AVR-56].** A heavier game provides two things:

- a concise **Quick Start** that gets players into the first meaningful turn;
- a structured **Rules Guide** for the full rule set and edge cases, with sections that can be
  linked, searched and consumed by future tooling, rather than one large prose blob.

**[Proposed]**: the Quick Start is shown in the briefing in place of the simple pattern, under
the same size limit as Rule 4.10.

**Rule 4.13 [Accepted, AVR-56].** Contextual help may link directly to the relevant rule
section. **[Proposed]** mechanism: a game control, a refusal message or an unavailable-action
explanation MAY carry a section id and open the guide at that section.

**Rule 4.14 [Proposed].** A game is "heavy" when its author says so by shipping a guide; the
platform does not classify games. Search is a plain substring match over section titles,
keywords and text, on the phone, with no network and no model. A rules assistant is downstream
and optional (AVR-56).

### 4.6 Rules stay reachable during play

**Rule 4.15 [Accepted, AVR-56].** Rules and how-to-play "remain reachable after launch"; "rules
remain reachable during play".

**[Proposed]** floor: at every moment of play and results, for player and spectator, in one tap
from a control that is always on screen.

**Rule 4.16 [Proposed].** Opening rules in play MUST NOT pause, forfeit or desynchronize the
game, MUST NOT cover a prompt without saying one is waiting, and MUST return focus to where it
was. The game owns this control's look and position; its accessible name is "How to play".
**[Implemented]** in BLUFF (`#rules`, `briefing.js` "reference" mode with its "Your call is
waiting" line) and EXPO (`#help-toggle`, the `help` sheet).

**Rule 4.17 [Proposed].** What the in-play control shows MUST be the same content the briefing
showed, from one source. Today neither game meets this
([§16](#16-current-deviations-observations-not-tasks) B-1, E-1).

## 5. Rules content

### 5.1 What exists: `avrana.onboarding/v0` [Implemented]

A game serves `onboarding.json` beside its entry page. The shell fetches it once per game
(`app.js` `onboardingFor`) and requires `schema: "avrana.onboarding/v0"` and a `rules` array.
Shape, from `games/bluff/web/onboarding.json`:

```json
{
  "schema": "avrana.onboarding/v0",
  "game": "bluff",
  "title": "BLUFF",
  "premise": "one or two sentences",
  "ack": { "key": "bluff-briefed", "version": "1" },
  "facts": { "coupCost": 7 },
  "rules": [ { "title": "On your turn, do one thing", "points": ["Coup: pay {coupCost} ..."] } ]
}
```

`{name}` placeholders are filled from `facts`, so a number is written once and a test can pin it
to the rules code (BLUFF: `tests/test_bluff_briefing.py`, games). A game with no file gets the
catalog `summary` as premise and as the only rules text. It is not declared in
`contracts/party-games.v0.json`, and this document does not add it.

### 5.2 Draft: `avrana.onboarding/v1` [Proposed, not built, not a contract]

A superset of v0 so that existing files keep working. It adds stable section ids, the heavy-game
guide, the fake-turn example, declared settings and declared unavailable-action reasons. Field
names are a draft for review; no code reads them.

```json
{
  "schema": "avrana.onboarding/v1",
  "game": "expo",
  "title": "EXPO",
  "weight": "simple | heavy",
  "premise": "one or two sentences",
  "ack": { "key": "expo-briefed", "version": "1" },
  "facts": { "handSize": 2 },

  "briefing": {
    "objective": "one sentence",
    "flow": ["short step", "short step"],
    "controls": ["short step"],
    "example": [
      { "art": "example/1.svg", "alt": "what the picture shows", "caption": "one sentence" }
    ]
  },

  "guide": {
    "sections": [
      {
        "id": "following-suit",
        "title": "Following suit",
        "summary": "one sentence, used in search results and contextual help",
        "points": ["short point with a {fact}"],
        "keywords": ["lead", "suit"],
        "see": ["submarines"]
      }
    ]
  },

  "reasons": {
    "must_follow_suit": { "text": "You must follow the opening suit.", "section": "following-suit" }
  },

  "settings": [
    { "id": "mission", "label": "Mission", "type": "choice", "default": "1",
      "options": [ { "value": "1", "label": "Mission 1" } ] }
  ]
}
```

Rules for the draft:

- `id` is `[a-z][a-z0-9-]*`, unique in the file and stable across versions: it is the link target
  (`#rules/<id>`), the search key and what a tool indexes.
- `rules` (v0) stays valid; a v1 file with only `rules` is a simple game with no example.
- `briefing` is the Quick Start. `guide` is present only for a heavy game.
- Every string is plain text. No HTML, no Markdown, no inline styles (the `/party/` CSP forbids
  them and the shell renders with `textContent`).
- `art` is a path relative to the file, to a self-contained SVG or raster image served by the
  game; never a remote URL ([§13](#13-art-and-asset-slots)).
- `reasons` is a catalogue of the sentences the game uses to explain an unavailable action
  ([§7](#7-actions-legality-and-unavailable-explanations)), so they can be reviewed, linked to a
  section and later localized. The *decision* that an action is unavailable still comes only
  from the game's server.
- The file describes; it never executes. Nothing in it is evaluated as a rule.
- Suitable for package tooling: one JSON file, a schema name, stable ids, no code. Where it
  lives in a future `.avrgame` package is AVR-37's decision, not this document's.

## 6. Player identity and avatars

**Rule 6.1 [Accepted, ADR 0011 decision 2, [AGENTS](../../AGENTS.md) "Safety"; Implemented].**
Cross-game identity is the Party's, with "no parallel stores or tokens in Games". A phone with an
Avrana profile (name, Gaze avatar) is in the Party, and members carry their Gaze avatar id.
**[Proposed]**: in a Party round a game MUST NOT ask for a name, offer its own avatar picker or
keep its own profile. Avatars are the 32 bundled Gaze avatars (`web/party/avatars/`, `avatarNode` in
`web/party/lib/profile-ui.js`), vendored into games at `/shared/avatars/`.

**Rule 6.2 [Proposed].** Wherever a game shows a person, it MUST show the Party name and SHOULD
show the Party avatar, so a player is recognizable from the briefing roster into play. A game MAY
frame, crop, tint or badge the avatar in its own style and MAY add a game persona (a role, a
colour, a seat) beside it. It MUST NOT replace the person with only a game persona where others
need to know who acted.

**Rule 6.3 [Accepted, ACCESSIBILITY rule 11].** A name is text (`textContent`, inside `<bdi>`),
never markup. System text is never rendered as if a player said it.

**Rule 6.4 [Proposed].** "You", the Host and away are each marked with a visible word or a
distinct icon, never by colour or opacity alone. **Today, partly:** "You" is a visible word
(`You` in `avrana-lineup`, `(you)` in `avrana-roster`); the Host is a crown icon whose only text
is an accessible name (`aria-label="host"`), with no visible word; away is `data-away` drawn as
`opacity: 0.6` and nothing else in both lists (`web/src/party.css`, `personChip` and
`renderScene` in `web/party/app.js`), which is observation P-10.

**Rule 6.5 [Accepted, ADR 0006 and its 2026-10-04 amendment].** A game never receives device
identity, and a game keeps no host: the Party is the only place that answer exists.
**[Proposed]**: a game MUST label "Party Host" distinctly from any in-game leader role.
**[Implemented]** in EXPO (`crewSheet`: "Captain" and "Party Host" are separate labels).

## 7. Actions, legality and unavailable explanations

**Rule 7.1 [Accepted, AVR-56].** The executable-rule principle: normal UI makes an illegal move
difficult or impossible, and authoritative game code validates every submitted action against
current state regardless of what the client showed. The rules guide explains why; game authority
decides what is legal. There is no universal Avrana rules engine: games own rules, state,
rendering and turn logic.

**Rule 7.2 [Accepted for EXPO only; Proposed as a platform rule].** For EXPO the owner-approved
Linear document "EXPO — Gameplay Engine & Mission Board Contract" (§1) says: "illegal actions are
prevented; legal mistakes are allowed. The game is a referee, not an oracle", and that the UI
must not disable, tint, warn about or ask confirmation for a legal play that fails the mission.
EXPO's action contract repeats it (`games/expo/docs/ACTIONS.md`: "A legal card is never marked,
warned about or confirmed for what it may do to the mission"). Neither AVR-56 nor a Party ADR
states it for every game.

**[Proposed]** as the platform-wide rule: games are referees, not oracles. A legal move that is
bad for the player MUST NOT be warned about, marked, ranked or confirmed for its consequences.

**Rule 7.3 [Proposed].** A confirmation is for *irreversibility and slips*, applied to every
choice alike, never for strategy:
"Play 7 of blue?" as a two-step tap on a small card is allowed (it prevents a mis-tap); "Are
you sure? This loses the mission" is forbidden.

**Rule 7.4 [Proposed].** An unavailable action is shown, disabled, with one plain sentence that
says why, when the player can reasonably expect the control at this moment. A control that is
simply not part of this phase is not drawn. The sentence:

1. is visible text next to the control or in the control group's status line. A `title`
   attribute or tooltip is never the only carrier: a phone shows neither;
2. is decided by the server and delivered in the viewer's own view, with the legality it
   explains. The client may hold a fallback sentence; it MUST NOT compute legality the server
   did not send;
3. speaks in the game's own terms ("You must follow the opening suit.", "The Party Host starts
   the round."). It MUST NOT name code, states, timers, sockets, versions or error identifiers;
4. MUST NOT reveal hidden information: another player's cards, the deck, a hidden role;
5. names the person being waited for when the reason is a person;
6. MAY carry a rules section id (Rule 4.13).

**[Proposed]** view shape, per action, in the viewer's own state:
`{ "available": false, "reason": "plain sentence", "code": "must_follow_suit", "section": "following-suit" }`.
`code` is for tests and the `reasons` catalogue, never shown.

**Rule 7.5 [Proposed].** A refusal after submission (a race, a stale tap) uses the same sentence
vocabulary, is shown only to the sender, changes nothing, and is announced politely. The
pre-submission reason and the server's refusal for the same situation MUST be the same sentence.

What exists today:

| Where | Mechanism | Status |
|---|---|---|
| Party briefing: why the Host cannot start | Party Core's `blocker` sentence, shown as text under a disabled Start (`core.py` `setup_status`, `app.js` `scene-status`) | **[Implemented]** |
| Party briefing: why this phone cannot play | `seatChoice().why` from `evaluate.js` `explain()` | **[Implemented]**, Limited Mode only |
| Party library: why a game does not fit this phone | `avrana-fit`, `.why` on the tile, `explain()` | **[Implemented]** |
| EXPO | server-owned `me.legal_cards`, `me.play_reason`, `may_pass_task`, `may_decline_volunteer`; a `why()` paragraph beside the control; stable refusal codes with sentences | **[Implemented]**; six client sentences differ from the server's (EXPO defect E-D8, AVR-263) |
| BLUFF | the server lists `me.actions`; a missing action is drawn disabled with no reason | **[Implemented]** without explanation ([§16](#16-current-deviations-observations-not-tasks) B-2) |
| A shared primitive a game can import | none | **specified only** |

## 8. Controls, layout and surfaces

These are floors a game meets in its own style. The Party page's concrete classes are in
[UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md); a game is not required to use that stylesheet.

**Buttons [Proposed, extends UI-DESIGN-SYSTEM "Buttons"].**

- One primary action per region. In play, the primary action is the thing the game is waiting
  for from this player.
- A destructive action is never styled as primary and never sits where the primary action was a
  moment ago.
- A pressed, busy or disabled state is visible within one frame of the tap; a control that waits
  on the server shows that it is waiting and does not accept a second tap.
- Icon-only buttons carry an accessible name.

**Touch targets [Accepted, ACCESSIBILITY rule 3].** Touch targets are at least 44×44 CSS px. The
rule has no exception. **[Proposed]** reading: that includes cards, seats and board cells.
**[Proposed]**, and it would need an ACCESSIBILITY amendment before it is allowed: a dense board
whose cells cannot reach 44 px MAY instead use a two-step select-then-confirm, so a small target
cannot commit an action by a slip. **Today**: the Party theme sizes buttons and inputs at 48 px
(UI-DESIGN-SYSTEM); `tests/offline/party.spec.ts` asserts that no visible `main a.btn`,
`main button` or `summary` on the Party page is under 44 px *high* (height only; width and the
briefing scene are not covered by that assertion); `games/expo/web/expo.css` sets 44 px minimum
heights on its controls; EXPO's select-then-"Play" dock exists in addition to those sizes.

**Forms [Proposed].** A game in a Party round asks for nothing the Party already knows. Inputs
are at least 16 px so iOS does not zoom, have a visible label, use the right `inputmode`, and
are validated by the server with the refusal in words beside the field.

**Sheets, drawers and dialogs [Proposed].** One pattern, three rules:

- anything that is not this turn (history, roster detail, rules, a menu) opens as a sheet over
  the game, and closing it returns to exactly the state and focus left behind;
- a sheet or dialog is modal for assistive technology: `role="dialog"`, `aria-modal`, a
  labelled title, focus moved in, Tab kept inside, Escape and a visible Close both close it,
  the background inert;
- at most one is open at a time, and a result or a prompt that needs an answer outranks it.

**[Implemented]** in EXPO (`openSheet`, `modalTop`, `inert`, focus return) and on the Party page
(`<dialog class="modal">` for rules).

**Destructive confirmation [Proposed].** An action is destructive when it ends something for
other people or cannot be undone: End for everyone, Party Home from results, forfeit, clearing a
profile. It MUST be confirmed, the confirmation MUST say who is affected and that it cannot be
undone, the safe choice MUST be the default focus, and the destructive choice MUST NOT be the
primary style. Two forms are acceptable and both exist: a dialog (BLUFF `confirmAction`: "End
the game for everyone?" / "Keep playing" focused) and tap-again-within-four-seconds
(`party-follow.js` `onEnd`, EXPO `endButton`). Which one is the standard is open
([§18](#18-open-questions-for-the-owner) Q6).

**Phone-first layout [Proposed, extends UI-DESIGN-SYSTEM "Mobile first"].**

- Designed from 360 CSS px wide, portrait, one hand. No horizontal page scroll.
- Play fits one viewport: the page does not scroll as a document during a turn; what does not
  fit goes in a sheet. Use `100dvh` with a fallback, and respect all four safe-area insets.
- The primary action sits in the bottom third.
- Nothing depends on hover, a keyboard or a second screen unless the Game Contract's `screen`
  and `input` say so.
- Landscape and tablet MAY be a different layout; they MUST NOT be a stretched phone.

**[Implemented]** as measured assertions for EXPO on five phone sizes
(`tests/_expo_phone.mjs`, games; run by hand, not CI).

**Compact messaging and HUD [Proposed; chat policy is COMMUNICATION's].**

- A transient message (toast) is at most two lines, never takes focus, never covers the primary
  action, is announced politely, and is never the only place a needed fact appears.
- A prompt that needs an answer is not a toast: it is on the board, with its deadline as text.
- Connection loss is one calm line in a fixed place, in words ("Reconnecting…"), not a
  full-screen takeover unless play cannot continue.
- A game reserves a region where platform messages (a system cue's text, a future chat HUD) may
  appear without covering its controls; the default is the top safe area.

**[Implemented]**: `Hub.toast` and the "RECONNECTING…" banner in `web/hubnet.js` (neither is a
live region), EXPO's `status-strip` (`role="status"`). No chat HUD exists in play.

## 9. Accessibility and per-device preferences

**Rule 9.1 [Accepted].** [ACCESSIBILITY](ACCESSIBILITY.md)'s twelve MUST rules apply to the
platform and to every game, in every phase. They are not repeated here. This contract adds what
is specific to the platform/game line.

**Rule 9.2 [Proposed].** The platform shell (briefing, rules sheet, Round over, system cues) is
accessible by construction; a game inherits that for free. Inside its own viewport the game is
responsible, and declares honestly in its Game Contract `accessibility` block what it does not
do.

**Rule 9.3 [Proposed].** Turn and prompt state MUST be available without sight of the board:
"your turn", "answer now" and the result are announced through a live region (polite for
status, assertive only for a prompt with a deadline), and each is also a word on screen, not
only a glow, a colour or a sound.

**Rule 9.4 [Accepted, ACCESSIBILITY rule 7].** A state push MUST NOT drop focus. **[Implemented]**
in EXPO (`data-key` focus restore in `draw`).

**Rule 9.5 [Accepted, ACCESSIBILITY rule 4].** Text scales: never `user-scalable=no` or
`maximum-scale=1`; `rem` for text; the layout scrolls rather than clips at 200 % text. The
0.94 rem floor for guest text is the Party theme's own scale (UI-DESIGN-SYSTEM, prototype), not
an accessibility rule. **[Proposed]**: a game that fixes text in `px` declares
`text_scalable: false`.

**Rule 9.6 [Proposed].** Timers show remaining time as text; a deadline that can cost a turn is
declared (`timing_pressure`). A game SHOULD give the Host a way to relax or disable a turn timer
before the round as a declared setting.

**Reduced motion [Accepted, ACCESSIBILITY rule 8].** Honour `prefers-reduced-motion` (no
confetti, no pulsing) and `prefers-contrast`. **[Proposed]** elaboration: reduced motion removes
all non-essential motion on platform and game surfaces (also bobbing, parallax and animated
transitions); motion that carries meaning (a card moving to a trick) is replaced by an instant
state change plus the same information in words; it never removes information and never changes
timing rules. **[Implemented]**: `web/src/party.css`,
`games/bluff/web/table.css`, `games/expo/web/expo.css`, `web/shared.css`.

**Per-device preferences [Proposed; ACCESSIBILITY "Per-player preferences" is the design].**
Each player's phone is their own screen, so preferences are per device and never change anyone
else's game. The set: reduced motion, higher contrast, system sound on/off, haptics on/off, and
later text size and handedness. The system setting is the default; an explicit choice on the
device overrides it. The platform exposes the resolved values to a game as `data-` attributes on
`<html>` and CSS custom properties; a game MUST honour reduced motion, sound off and haptics off
and SHOULD honour the rest. They are not a durable Profile and do not follow a person to another
phone. **Today**: the donor code has per-browser sound, haptics, motion and contrast flags
(`web/hubnet.js` `prefs`, keys `wc-muted`, `lg-haptics`, `lg-motion`, `lg-contrast`) with no
Party-side control and no Party-owned storage; the Party page honours only the system media
queries.

## 10. Degraded and offline messaging

**Rule 10.1 [Accepted, ADR 0012, FULL-MODE].** Capabilities degrade individually and visibly; the
Party stays usable.

**Rule 10.2 [Proposed].** One message shape everywhere: **what is different on this phone, what
still works, what (if anything) the player can do.** Plain words, no protocol or component
names, no blame, no imitation of browser security UI. **[Implemented]** in the Limited Mode
notice (`web/party/lib/limited.js` `limitedNotice`, `avrana-limited`) and the library tile's fit
line.

**Rule 10.3 [Proposed].** Degradation is said once, where the decision is made (the library
tile, the briefing's Ready control), not repeated as a banner over play. In play, a game shows a
capability problem only when it changes what the player can do now.

**Rule 10.4 [Proposed].** Being offline from the internet is the normal state and is never
mentioned. Being unable to reach the Party is a state with a next action: it says so in words,
retries by itself, and offers one manual retry. **[Implemented]**: `#away` on the Party page
("Can't reach the party", Try again), `avrana-status`, the games' reconnect banner.

**Rule 10.5 [Proposed].** A game that cannot run on this phone at all sends the player to Watch
when the game supports it, with the reason; it never shows a blank or broken board. What that
phone gets when the game supports no spectators is undecided (Q12).

## 11. System feedback: sound, haptics, motion

Nothing in this section is built on the Party side: `web/party/` contains no audio and no
haptic call. It is specified here so that it is built once, restrained, and not per game.

**Rule 11.1 [Accepted, AVR-56].** System feedback is a platform primitive distinct from a
game's audiovisual identity. Premium feel comes from consistency and responsiveness, not
ornament.

**Rule 11.2 [Proposed].** The system cue set is closed and small:

| Cue | When | Sound | Haptic |
|---|---|---|---|
| join | someone arrives at the Party (Home and briefing only) | soft, short | none |
| leave | someone is removed or goes away (Home and briefing only) | soft, short | none |
| ready | a roster answer changes in the briefing; all ready for the Host | soft tick; a distinct "all ready" for the Host | none; one short pulse for the Host on all-ready |
| attention | this phone must act and has not: the Host's Start is waiting, the Party moved while the phone was hidden | one clear tone | one short pulse |
| connection | lost, and restored | none on loss; soft on restore | none |

**Rule 11.3 [Proposed].** Rules for every system cue:

- under 400 ms, quiet relative to game audio, one sound per event, coalesced when several happen
  within a second;
- never the only carrier: each has a visible word ([ACCESSIBILITY](ACCESSIBILITY.md) rule 10);
- sound only after a user gesture has unlocked audio and only when system sound is on; haptics
  only where `navigator.vibrate` exists and haptics is on. Absence of either is silent and is
  never reported to the player (iOS Safari has no vibration API);
- no system cue during Play except *attention* and *connection*. A game's "your turn" is the
  game's cue, in the game's voice;
- no music, no voice, no ambient sound from the platform, ever.

**Rule 11.4 [Proposed].** A game owns every sound and vibration tied to a game event and MAY
have none. It MUST honour sound-off and haptics-off, MUST NOT play before a user gesture, and
MUST NOT reuse or imitate a system cue for a game event.

**Rule 11.5 [Proposed] System transitions.** The platform animates only its own state changes:
a sheet opening, a roster entry arriving, the move between phases. Each is at most 200 ms,
opacity or a short translate, never blocks input, and is removed entirely under reduced motion.
The move into a game is a cut or a short fade to the game's own first frame; the platform does
not play a branded interstitial. **[Implemented]** baseline: 150 ms colour and border
transitions and a chevron turn on the Party page; a "Taking you to <game>…" holding screen
(`#going`).

## 12. Results, end and return

**Rule 12.1 [Accepted, ADR 0011].** A completed round's results are held until the Host chooses
Play again or Party Home. There is no automatic timer back to a lobby in a Party round. An
abandoned round has no results screen: the Party goes home.

**Rule 12.2 [Proposed].** The results screen is the game's, in the game's style, and says first
who won or what happened in words. In the same place on every phone: the Host's two choices
(Play again as the primary, Party Home as the secondary), and for everyone else the named
waiting line (Rule 3.8). **[Implemented]** in BLUFF's bar, EXPO's result takeover and the shared
"Round over" panel.

**Rule 12.3 [Proposed].** End for everyone during play is the Host's, confirmed
([§8](#8-controls-layout-and-surfaces)), reachable in at most two taps, and never placed beside
the turn's primary action.

**Rule 12.4 [Accepted for BLUFF, ADR 0011 decision 6; Proposed for every game].** "Rounds are
the host's to end": in a Party round BLUFF refuses its own `end_game` and empty-table takeover.
**[Proposed]** generalization: no game ends a Party round or returns phones by itself.

## 13. Art and asset slots

**Rule 13.1 [Accepted, AVR-56].** "No emoji is implicitly required as production game art."
**[Proposed]** consequence: no platform slot, contract field or shared component may assume an
emoji glyph; emoji render differently on every phone and are not an art direction.

**Rule 13.2 [Proposed].** A game MAY use emoji or typographic marks as a deliberate choice where
they are notation (card suits, ✓, ×) or a prototype placeholder; a placeholder is declared as
such. A platform surface never shows an emoji as a game's art: the fallback is the title's art,
then curated art, then a generic line icon ([UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md) "Game
artwork").

Slots:

| Slot | Used by | Today | Proposed |
|---|---|---|---|
| Cover (square) | library tile, briefing | **[Implemented]** `contracts/artwork.json` → `web/party/art/`, catalog `artwork` | unchanged |
| Accent colour | briefing cover | **[Implemented]** catalog `accent`, applied through CSSOM | also the briefing's wash and primary fill (Rule 4.2) |
| Summary line | tile, premise fallback | **[Implemented]** Game Contract `summary` | unchanged |
| Briefing example frames | briefing | none | onboarding v1 `briefing.example[].art` with required `alt` |
| Wide / hero art | briefing header | none | optional; falls back to the cover |
| System cue assets | platform | none | platform-owned, bundled, never per game |
| In-game art, fonts, sound | the game's own page | game-owned (BLUFF: Kenney family, `docs/ASSETS.md`, games) | unchanged; never routed through the platform |

Rules for every asset. **[Accepted, UI-DESIGN-SYSTEM "Offline rule" and "Architecture"]**:
everything a page needs comes from the appliance, never a remote URL; artwork SVGs carry no
styles or scripts. **[Proposed]**: licence and source recorded where the asset is vendored (the
practice of `assets/vendor/README.md` today); every image a person needs has text (`alt`, or a
label on its control); decorative art is `aria-hidden`.

## 14. Shared primitives: what exists and what is only specified

"Exists" means a thing in source that another surface can reuse or copy today. This contract
deliberately does not ask for a component library: a primitive is built when a second consumer
needs it.

**Exists today**

| Primitive | Where |
|---|---|
| One authoritative location and the follow rule | `web/party/lib/party-mode.js` (`destination`, `locationOf`), `party-follow.js` |
| Host controls for a game's own chrome | `window.AvranaParty` in `party-follow.js`; `[data-avrana-party-shell]`; fallback End |
| Host authority at the action | ticket `host` claim and the party's answer (ADR 0006 amendment); `conn.hostAction` in `web/hubnet.js` (games) |
| Briefing shell | `#scene` in `web/party/index.html`, `renderScene` in `app.js`, `avrana-scene`, `avrana-lineup`, `avrana-choice` in `web/src/party.css` |
| Start blocker as a sentence | `avrana/party/core.py` `setup_status`; `setupPanel` in `party-mode.js` |
| Rules sheet and first-play acknowledgement | `#rules`, `openRules`, `acknowledged` in `app.js`; `avrana-rules` |
| Onboarding content file | `avrana.onboarding/v0`: `games/bluff/web/onboarding.json` |
| Avatars and the roster | `web/party/avatars/`, `avatarNode` (`profile-ui.js`), `avrana-avatar`, `avrana-roster` |
| Capability and fit explanation | `web/party/lib/evaluate.js` (`evaluateSeat`, `explain`), `limited.js` (`seatChoice`, `limitedNotice`), `avrana-fit`, `avrana-limited` |
| Connection state on the Party page | `avrana-status`, `#away` |
| Buttons, inputs, modal, tokens for platform surfaces | daisyUI `avrana` theme in `web/src/party.css` |
| System icons | `web/party/lib/icons.js` (Lucide subset) |
| Held results and the "Round over" panel | `core/session.py`, `web/hubnet.js` (games) |
| In-Party chrome removal | `web/avrana-integration.css` (games): `[data-avrana-global]`, `[data-avrana-viewport]` |
| Toast and reconnect banner (donor) | `Hub.toast`, `conn-banner` in `web/hubnet.js` (games) |
| Per-browser sound, haptics, motion, contrast flags (donor) | `prefs` in `web/hubnet.js` (games) |
| Destructive confirmation | two unshared implementations: BLUFF `confirmAction`; tap-again in `party-follow.js` and EXPO |
| Modal sheet with focus handling | EXPO only (`openSheet`, `modalTop`); not shared |

**Specified here, not built**

| Primitive | Section |
|---|---|
| Watch as a secondary choice gated on the game's `spectators` (needs an ADR 0011 amendment first; Q1, Q12) | §4.2 |
| Game accent beyond the cover | §4.1 |
| Fake-turn example strip | §4.3 |
| Declared host settings drawn by the shell | §4.4 |
| Quick Start plus structured, linkable, searchable Rules Guide; `avrana.onboarding/v1` | §4.5, §5.2 |
| One rules source for briefing and in-play help; a platform rules sheet a game can open in play | §4.6 |
| A shared unavailable-action shape and a `reasons` catalogue | §7 |
| A shared announce (live region), sheet and confirm that a game can import | §8, §9 |
| Party-owned per-device preferences exposed to games | §9 |
| System sound and haptic cues | §11 |
| Briefing example and hero art slots | §13 |

The donor helpers proposed in ACCESSIBILITY ("Platform defaults to extract": announce, tappable,
focus restore) are the same unbuilt set; this document does not duplicate that list.

## 15. Pressure test

### BLUFF (current)

- **Fits.** Party briefing from `onboarding.json`; first-play gate; rules reachable in play;
  host End with a dialog; held results with host Play again / Party Home and a named waiting
  line; own art direction (felt table, Kenney art) clearly distinct from the Party page; no
  lobby in a Party round; reduced motion honoured.
- **Strains.** The in-play rules are a second, richer copy (art per card) of the briefing's
  text; the platform's plain rules sheet is visibly poorer than the game's own. Disabled actions
  have no reason. The response timer is a 20 s deadline with no host setting.
- **The contract says.** Keep the game's richer in-play rules screen (Rule 4.16 lets the game own
  it) but drive both from one source (Rule 4.17). Send a reason with each unavailable action
  (Rule 7.4). The timer is a candidate declared setting (Rule 9.6).

### EXPO (current)

- **Fits.** One-viewport play, sheets for everything that is not this turn, result takeover,
  server-owned legality and reasons shown as text, referee-not-oracle stated in its
  owner-approved contract and its action document, Party
  Host distinct from Captain, host authority confirmed at the action, no route to the old hub.
- **Strains.** It is a heavy game: 96 tasks, mission modifiers, a two-player variant. Its help
  is seven paragraphs in the client and it ships no onboarding file, so the Party briefing shows
  only the catalog summary. It genuinely needs host settings (mission, timed, the dummy's seat)
  and those exist only in its standalone lobby. The next mission is chosen in the game's result
  screen, which is a game-internal host action, not a Party transition.
- **The contract says.** EXPO is the first consumer of Quick Start plus Rules Guide (§4.5) and of
  declared settings (§4.4); both are unbuilt, and settings need a protocol change. Choosing the
  next mission stays a game-defined host action (Rule 3.7), not a Party verb: the Party's
  location does not change.

### A simple classic (tic-tac-toe or checkers class)

- **Fits.** The simple briefing is almost the whole need: premise, three or four points, a
  one-to-three-frame example, Ready, Start. No settings. Legality is a list of legal cells or
  moves from the server; an unavailable piece needs at most "It is Sam's turn." Results held;
  Play again is the common path.
- **Strains.** Exactly two players in a Party of six: four people must Watch, so Watch is not
  "secondary" for most of the room, and the start blocker ("At most 2 can play; 5 chose to
  play") becomes the main event. A thirty-second game makes a full briefing per round feel heavy.
  "Whose turn" on a board with no hand needs a non-colour cue.
- **The contract says.** Ready stays first-come up to the maximum and the blocker sentence is
  what resolves it today; who plays when more want to than fit is unsettled
  ([§18](#18-open-questions-for-the-owner) Q4). Play again returns to the briefing by the
  location model; whether a rematch may skip it is unsettled (Q5). Rule 9.3 covers the turn cue.

### A real-time, action-heavy game (hypothetical)

- **Fits.** Briefing, Ready, Start, host End, held results, identity, system cues outside play,
  the whole-viewport rule, declared `timing_pressure`.
- **Strains.** One viewport is easy; *sheets over play* are not: opening rules or a menu while
  the action continues costs the player. Per-action unavailable sentences do not fit a control
  held sixty times a second: a cooldown is shown by the control's own state. Reduced motion
  cannot remove motion that is the game. Destructive confirmation by dialog steals the screen
  mid-action. Reconnect recovery into a moving game may mean the round went on without the
  player. A turn-based "attention" cue has no meaning.
- **The contract says.** Rule 4.16 still holds: rules are reachable and opening them never
  pauses the game for others; the game MAY restrict the *full* guide to moments it defines as
  safe if a one-line control reminder stays reachable. Rule 7.4 applies to discrete choices
  (pick a character, use an item), not to continuous input; continuous controls show
  availability by state, with the word available in the rules. Reduced motion removes
  decoration and screen shake, not gameplay motion, and the game declares
  `reduced_motion_respected` honestly. Tap-again confirmation is the form that works here. What
  a late or returning player gets is the game's rule (Game Contract `late_join`, the game's own
  grace), not the platform's. Latency budgets are AVRANA-EXPERIENCE §15's subject, not this
  contract's. This genre is the least tested part of the contract: no such native game exists.

## 16. Current deviations (observations, not tasks)

Each is a fact about source on the commits named at the top. Most are measured against rules
this document only *proposes*, and P-1 to P-3 against AVR-56 direction that accepted ADRs do not
yet reflect: a row is a deviation from accepted contract only where it says so. None is a work
order; Linear decides what becomes work.

**Party (`avrana-party`)**

| # | Observation | Where |
|---|---|---|
| P-1 | Conforms to ADR 0011 decision 4 (two large choices). Differs from AVR-56's newer "secondary round-role choice" wording (Rule 4.4, Q1) | `web/party/index.html` `#choose-play`, `#choose-watch` |
| P-2 | Conforms to ADR 0011 decision 4 and ADR 0012 (Watch is always offered). Differs from AVR-56's "when the game supports it": the shell does not read the Game Contract's `spectators` (Q12) | `web/party/app.js` `renderScene`; `web/party/lib/limited.js` `seatChoice` |
| P-3 | The label "Play this round" is ADR 0011 decision 4's wording. AVR-56 speaks of a "Ready state"; whether the control's word changes is Q1, not a deviation | `web/party/index.html` |
| P-4 | The accent reaches only the cover; briefings for two games differ by icon and text only (Rule 4.2) | `app.js` `renderScene` (`--game-accent` on `#scene-cover`) |
| P-5 | No settings slot, no example slot, no Quick Start / guide rendering, no section links or search | `app.js` `openRules` renders `rules[].title/points` only |
| P-6 | A game without `onboarding.json` gets its catalog summary as the entire How to play | `app.js` `openRules` fallback |
| P-7 | No system sound or haptic cue; no Party-owned per-device preferences | `web/party/` (no audio or vibrate call) |
| P-8 | The fallback host End uses tap-again; BLUFF uses a dialog: two confirmation patterns | `web/party/lib/party-follow.js` `onEnd` |
| P-10 | An away member is shown by `opacity: 0.6` alone in both rosters, with no word, icon or shape. ACCESSIBILITY rule 5 names "disconnected" among states that must not be conveyed by colour alone and gives an "Away" badge as its example, so this looks like a deviation from an accepted rule; the Host is an icon with an accessible name and no visible word | `web/src/party.css` `.avrana-roster li[data-away]`, `.avrana-lineup li[data-away]`; `web/party/app.js` `personChip`, `renderScene` |
| P-9 | The briefing is not declared in the Party ↔ Games contract; `onboarding.json` is fetched by convention beside the entry page | `app.js` `onboardingFor`; `contracts/party-games.v0.json` |

**BLUFF (`avrana-party-games`)**

| # | Observation | Where |
|---|---|---|
| B-1 | Rules exist twice: `onboarding.json` for the Party briefing and `CARDS` in the in-play dialog; each is pinned to the rules code by a test, not to each other's wording (Rule 4.17) | `games/bluff/web/onboarding.json`, `games/bluff/web/briefing.js` |
| B-2 | Income, Foreign Aid and Coup are drawn disabled with no reason (Rule 7.4) | `games/bluff/web/client.js` `actBtn(..., !by.income)` |
| B-3 | No live region: prompts with a 20 s deadline and `Hub.toast` messages are not announced (Rule 9.3) | `games/bluff/web/client.js`, `index.html` (no `aria-live`); `web/hubnet.js` `toast` |
| B-4 | Text is sized in `px` (10 to 15 px in places); its Game Contract does not declare `text_scalable` (Rule 9.5) | `games/bluff/web/table.css` |
| B-5 | The server's role table and log lines carry emoji; the client replaces them with art when drawing | `games/bluff/game.py` `ROLES`, `_log`; `client.js` `ROLE_ART` |
| B-6 | The history drawer is an `<aside>`, not a modal dialog; focus handling was reported missing in the 2026-09-24 audit and was not re-verified for this document | `games/bluff/web/index.html` `#drawer`; [ACCESSIBILITY](ACCESSIBILITY.md) audit item 5 |

**EXPO (`avrana-party-games`)**

| # | Observation | Where |
|---|---|---|
| E-1 | No `onboarding.json`; help is seven paragraphs hard-coded in the client; the Party briefing shows only the catalog summary though the contract declares `pregame: true` | `games/expo/web/client.js` `HELP`; `contracts/games/expo.json` |
| E-2 | A heavy game with no Quick Start and no sectioned guide; no contextual link from a `why()` sentence to a rule (Rules 4.12, 4.13) | `games/expo/web/client.js` `helpSheet`, `why` |
| E-3 | Mission, timed and dummy-seat settings exist only in the standalone lobby and are ignored in a Party round; Party-round setup is open as AVR-245 | `games/expo/docs/ACTIONS.md` (`settings`, E-P1); `games/expo/README.md` |
| E-4 | Six unavailable-control sentences differ from the server's refusal (Rule 7.5); known as E-D8, AVR-263 | `games/expo/README.md` "Known defects" |
| E-5 | Reasons are also set as `title` on disabled buttons and cards; the visible `why()` and `hand-reason` text is what a phone shows | `games/expo/web/client.js` `button`, `cardNode` |
| E-6 | The play viewport's top bar shows the platform's name above the game's (Rule 3.6) | `games/expo/web/index.html` `.brand` |
| E-7 | Text is sized in `px` (11 to 14 px in places) while its Game Contract declares `text_scalable: true`; behaviour at large system text was not measured for this document | `games/expo/web/expo.css`; `contracts/games/expo.json` |
| E-8 | The standalone lobby still asks for a name and avatar; a Party round seats the launch roster without that lobby (ADR 0010 decision 5) | `games/expo/web/index.html` `#lobby-form` |

## 17. Exit criteria

| AVR-56 exit criterion | Answer |
|---|---|
| Platform-owned vs game-owned visual responsibilities are documented | §2 (table, Rules 2.1 to 2.3), §3 phase table, §13 slots |
| Required shared states have reusable primitives | §14. Built: location/follow, briefing shell, Ready/Watch/Start, start blocker, rules sheet, host controls API, held results, reconnect recovery, fit/degraded explanation. Specified only: settings, example, guide, shared unavailable-action shape, shared sheet/confirm/announce, system cues, preferences |
| Accessibility expectations are explicit | §9, on top of ACCESSIBILITY's MUST table; reduced motion and per-device preferences in §9; cues in Rule 11.3 |
| Games retain intentional visual identity | Rules 2.1, 2.2, 3.6, 4.2, 6.2, 11.4, 12.2; pressure test |
| Rules/settings screens have a common platform-shaped baseline | §4 (briefing shell, built), §4.4 (settings, proposed), §4.6 and §5 (rules) |
| No emoji is implicitly required as production game art | Rules 13.1, 13.2; observation B-5 |
| Simple games have a reusable first-play briefing pattern | §4.3; built except the example strip |
| Complex games have a Quick Start plus structured Rules Guide pattern | §4.5, §5.2; specified, not built; EXPO is the first consumer |
| Rules remain reachable during play | Rules 4.15 to 4.17; built in BLUFF and EXPO, each from its own second copy |
| Shared primitives can explain why an action is unavailable without exposing implementation details | §7. The rule and shape are specified; Party Core's blocker and EXPO's server reasons implement it locally; no shared primitive exists |
| Onboarding/rule content can be represented in a machine-readable structure suitable for future package tooling | §5.1 (v0, in use) and §5.2 (v1 draft) |

The second and tenth rows are honest partials: the contract is written, the shared code is not.

## 18. Open questions for the owner

Each needs a decision this document does not make. Several reopen something an ADR already
answers; the last column says which, so that a change is made as an amendment and not by drift.

| # | Decision needed | Accepted answer today; what a change would amend |
|---|---|---|
| Q1 | **Ready wording and Watch's weight.** Is the primary control "Ready" (AVR-56 speaks of a "Ready state") or "Play this round"? Is Watch an equal choice or a secondary one? | ADR 0011 decision 4: two large "Play this round / Watch this round" choices. A change would amend ADR 0011 decision 4 and UI-DESIGN-SYSTEM "Buttons" |
| Q2 | **Does every member have to answer?** The Mario Party reference starts when the Host starts. Keep the all-answer gate, or let the Host start once the minimum is in and treat the rest as watching? | ADR 0010 decision 1: Start is refused until every member who is here has chosen. A change would amend ADR 0010 decision 1 |
| Q3 | **Settings ownership.** Are host settings always drawn by the platform shell from a declared closed vocabulary (§4.4), or may a game draw its own settings panel inside the briefing? | No accepted answer for settings in the briefing. ADR 0010 decision 5 refuses a game's own lobby `settings` verb in a Party round; a game-drawn panel would amend it, and either path needs the launch to carry values (§20) |
| Q4 | **More players than seats.** When more people choose to play than the game allows, who plays: first to choose, Host picks, or rotation across rounds? | ADR 0010 decision 1: Start is refused with a sentence until someone changes their answer. Any allocation rule would amend ADR 0010 decision 1 |
| Q5 | **Rematch.** May a game with no settings go straight to a new round with the same roles? | ADR 0011 decision 1: Play again goes to a new setup; ADR 0010 decision 2: no choices carry over. A shortcut would amend both |
| Q6 | **One destructive confirmation.** Dialog (BLUFF) or tap-again (fallback End, EXPO) as the standard for End for everyone? Or dialog for turn-based and tap-again for real-time? | No accepted answer; ADR 0011 decision 5 only says BLUFF's End is "confirmed in its own dialog" |
| Q7 | **Briefing identity.** How far may a game's art and accent take over the briefing (Rule 4.2): cover only (today), tint and hero art (proposed), or a game-drawn briefing inside a fixed platform frame? | ADR 0011 decision 4: the setup is the Party's own scene in the Party Home design system, with the game's art and title. A tint fits inside it; a game-drawn briefing would amend it |
| Q8 | **System sound.** Is any platform sound wanted at all, given phones in a shared room, and if so is it on or off by default? | No accepted answer; AVR-56 lists "subtle platform sounds where useful" under "Consider" |
| Q9 | **In-play platform presence.** May the platform ever draw over a game during play beyond connection state and the attention cue, for example the proposed chat HUD (COMMUNICATION) or a Control Center (AVR-83)? | ADR 0011 decision 5: the game owns the viewport and the page shows no Party prose. An overlay would amend it |
| Q10 | **Direct titles.** Must every Party-integrated native game have a briefing? | ADR 0011 decision 1 allows a game without a pregame to go straight to `game`. Requiring a briefing would amend it; emulated titles have no briefing content today |
| Q11 | **Rules in play.** Should the platform provide the in-play rules sheet for games that do not draw their own, which requires platform UI over the game on the game's page (and, under ADR 0013, across origins)? | ADR 0011 decision 5 as in Q9; no accepted answer for a platform rules sheet in play |
| Q12 | **A game with no spectators.** If Watch is hidden when the Game Contract says `"spectators": "none"`, a member who cannot or does not want to play has no answer to give, and under the all-answer gate the Host can never start. In Limited Mode a phone that cannot play would have neither choice. What does such a member answer: a third "sitting out" state, an automatic non-answer that does not block, or Watch always offered regardless of the game? | ADR 0010 decision 1 (everyone here must choose) and ADR 0012 (a phone that cannot play "may always choose Watch, so it can never hold up a round"). Today Watch is always offered, so the case cannot arise; hiding Watch without answering this would break Start |

## 19. Evidence still outstanding

- No part of this contract has been observed on real phones for this document. The briefing,
  follow, host controls and held results are covered by automated tests at phone viewport sizes
  in their own repositories; ADR 0011's phone proof is AVR-212 and ADR 0010's Tier 3 list is
  still open.
- AVR-27, four humans playing BLUFF offline, has not happened. It is the first evidence of how
  strangers to the project read the briefing, find the rules in play, and cope with waiting for
  the Host. Most likely to change after it: briefing size limits (Rule 4.10), the first-play
  gate (Rule 4.9), the all-answer Start gate (Q2), Watch's prominence (Rule 4.4), the waiting
  line (Rule 3.8), text size floors, and whether any system cue is wanted (§11).
- The real-time pressure test is reasoning without a game. Checkers and Spades (ADR 0014's
  validation order) will test the simple and the team/private-hand cases.
- The EXPO evidence is its source and its hand-run playtests; EXPO states no deployment and no
  real-phone acceptance.

## 20. Machine-contract changes this document proposes but does not make

| Change | Why | Where it would land |
|---|---|---|
| Declare the onboarding file (schema name, path convention) in the Party ↔ Games contract | today it is an undeclared convention (P-9) | `contracts/party-games.v0.json`, both checkers, paired PRs |
| Adopt `avrana.onboarding/v1` | Quick Start, guide, example, reasons, settings | a schema and validator; AVR-37 for packaging |
| Carry declared settings in the launch | the shell cannot hand settings to a game today | ADR 0006 session protocol (additive), paired PRs |
| Per-action `available` / `reason` / `code` convention in a game's view | shared explanation primitive | games-side convention first; not a Party wire change |
| Read Game Contract `spectators` in the briefing | Watch only when supported | not shell-only: hiding Watch interacts with ADR 0010's all-answer Start gate and ADR 0012's "may always choose Watch" (a member who can neither play nor watch has no answer and Start blocks). Needs Q12 answered and ADR 0011 decision 4 amended first; no wire change by itself |

## References

ADRs [0006](../adr/0006-party-session-protocol.md), [0010](../adr/0010-party-pregame.md),
[0011](../adr/0011-party-console-model.md),
[0012](../adr/0012-limited-mode-party-survives-https-loss.md),
[0013](../adr/0013-party-and-game-browser-origins.md),
[0014](../adr/0014-native-games-isolated-lan-games-retired.md);
[PARTY-PLATFORM](PARTY-PLATFORM.md); [NATIVE-GAMES](NATIVE-GAMES.md);
[GAME-INTEGRATION](GAME-INTEGRATION.md); Linear AVR-56, AVR-27, AVR-90, AVR-129, AVR-212,
AVR-245, AVR-246, AVR-263, AVR-275.
