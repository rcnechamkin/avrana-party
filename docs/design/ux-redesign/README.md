# UX/UI redesign: design-phase package

Status: **PROPOSED (2026-10-05, revision 2). Design reference: the owner approved the direction, and slices 0 and 1 of the implementation plan, on 2026-10-05. Nothing here is contract, and the concepts are not implemented by this package.**

The first design review for the [UX/UI product brief](../AVRANA-UX-UI-PRODUCT-BRIEF.md): an
audit of what exists, phone-sized concepts for the shell and for EXPO, and the list of what the
concepts would need. No production file was changed to make it. Implementation waits for the
owner's answer to one question: does this feel like Avrana?

The owner reviewed the first package, kept the shell direction and asked for six gaps to be
closed. What was found and done is in [REVISION-1](REVISION-1.md). The owner then approved the
visual direction and asked for a cleanup pass and an implementation plan: the pass is in
[REVISION-2](REVISION-2.md) and the plan in [IMPLEMENTATION-PLAN](IMPLEMENTATION-PLAN.md). Start
with those two if you have seen revision 1.

On 2026-10-05 the owner approved revision 2 and the plan for slices 0 and 1, and answered slice
0's questions; the answers are in the plan's
[slice 0](IMPLEMENTATION-PLAN.md#slice-0-decisions-and-wording). The concepts in this folder are
what slice 1 is built from. They remain drawings: the code and its tests say what is built.

## How to look at it

- **Fastest:** ten overview sheets, four screens each: [shell](screenshots/overview-1-shell.png),
  [game and states](screenshots/overview-2-game-and-states.png), [EXPO](screenshots/overview-3-expo.png),
  five for revision 1, listed in [REVISION-1](REVISION-1.md#where-to-look), and two for
  revision 2, listed in [REVISION-2](REVISION-2.md#where-to-look).
  Every screen on its own is a picture kept outside Git
  ([where](#pictures-that-are-not-in-git)). Names
  starting `01` to `07` are the required screens; `x-` are supporting; `r-` were added in revision 1 and `r2-` in revision 2. `-390x844` is the main
  size; `-390x664` (an iPhone inside Safari) and `-360x640` are short-screen checks.
- **Live, on a computer:** open `prototypes/index.html` in a browser. It shows every screen in
  a phone frame, with a size switch and a Host / everyone-else switch.
- **Live, on a phone:** serve the repository root with any static file server on the same
  network and open `/docs/design/ux-redesign/prototypes/index.html`. (The prototypes borrow
  avatars and three covers from `web/party/`, so the root has to be the repository, not this
  folder.)

The prototypes are static HTML and CSS with canned content. They exist to be looked at. They
are not the start of the implementation and share no code with `web/party/`.

## What is in the package

| File | What it is |
|---|---|
| [REVISION-2.md](REVISION-2.md) | The cleanup pass after the direction was approved: five corrections, what was re-measured, what is still limited |
| [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) | A sliced plan grounded in both repositories: what each slice delivers, what exists, what is missing, contract changes, tests, dependencies and rollback |
| [REVISION-1.md](REVISION-1.md) | The first owner review's findings, what was done about each, what is still limited, and recommendations on three open decisions |
| [SCREENS.md](SCREENS.md) | Each concept: purpose, primary action, hierarchy, Host and everyone else, responsive behaviour, accessibility, states, what changed from today, what it needs, what is still a proposal |
| [SYSTEM-PROPOSAL.md](SYSTEM-PROPOSAL.md) | The short shared system: frame, density, type, colour and the violet material, icons, artwork, navigation, social layer, sheets, Host, motion principles, accessibility, responsive |
| [BACKEND-GAPS.md](BACKEND-GAPS.md) | Backend and state implications sorted by required, wanted-only-if, desirable, frontend-only and already supported; where the brief meets an accepted decision; the open owner decisions |
| [audit/PARTY-SHELL-AUDIT.md](audit/PARTY-SHELL-AUDIT.md) | The current Party shell, Library, briefing and Arcade shell: 103 findings, each categorised A to F |
| [audit/EXPO-AUDIT.md](audit/EXPO-AUDIT.md) | The current EXPO phone client: 48 findings, categorised the same way (Games repository read only, `a448972`) |
| [audit/STATE-INVENTORY.md](audit/STATE-INVENTORY.md) | What Party Core, the catalog, the phone and EXPO hold today, with source references |
| `screenshots/` | The ten overview sheets, which the documents link to |
| `capture/` | The scripts and job lists that took the pictures |
| not in Git: `current/` | 215 pictures of today's UI, the audits' evidence ([where](#pictures-that-are-not-in-git)) |
| not in Git: `concepts/` | 207 pictures of the concepts (60 from the first package, 110 from revision 1, 37 from revision 2; the pictures revision 2 changed were re-taken) |
| `prototypes/` | The live concepts and their shared stylesheets |

Audit categories: A visual, B information architecture, C interaction, D accessibility,
E backend or state gap, F product question. Category F is not settled here: where a
concept had to draw one answer to a product question, that answer is listed as an open decision
in [BACKEND-GAPS](BACKEND-GAPS.md#open-owner-decisions) (20 of them, with recommendations on three).

## The proposal in one page

**The shell.** Three fixed layers. People are at the top: one Party control with faces and an
unread count, and the social drawer comes down from it. The module is in the middle and is the
only thing that scrolls. Four destinations are at the bottom: Home, Party, Library, System.
Each screen says its main fact as one sentence ("Four of you are here.", "Choosing a game").
Nothing is a card. Atomic Purple is a material (the bottom bar, sheets, the focus ring), never
a fill; the primary button is off-white. Today's Home is about three screens tall at
390 × 844 and its first complete game tile starts at 794 px; the concept Home fits one screen.

**Library.** Covers first, three across, with seats in the cover's corner. Two groups, "Great
for four" then "Not for four": a game that does not suit the Party stays visible and says why
("Max 2"). The Party's size only orders the shelf; nothing is filtered until someone sets a
filter, and then the badge, the count and the results agree. Four views and one filter sheet,
remembered per phone.

**Game detail and briefing.** One surface in two moments. Browsing is private to the phone and
launches nothing. The Host's button, "Bring the Party in", says what it does to everyone. The
briefing keeps the accepted rules (Play this round or Watch this round, then the Host starts) and puts
the Quick start on the page.

**Limited and degraded.** Two different things. A phone's own Limited Mode is said once in plain
words on that phone and then folds to a mark that stays. Appliance trouble that changes play is
shown to the Host only and can be dismissed. A healthy system shows nothing. The consequence is
written where it bites: under the affected title on Home and in the Library, and on its detail
page.

**EXPO.** A field unit: powder-coated graphite housing, a window onto an irradiated dusk, one
amber signal colour, and full-colour cards as the brightest things on the board. Five zones,
demonstrated for hands of 8 to 14, two players with Tonoja and five seats at four sizes, with
what each case costs written down. The current trick winner has a fixed line, taken
from the server's own `trick_leading`. The result is the verdict, then the cause in one
sentence, then the evidence. No engine change is needed. One typeface. Two things on the board
are decoration and are named as such: sight marks on the window and fasteners on the Burst panel.

## Assets used

No generated imagery. Everything drawn is one of:

| Asset | Source | Licence |
|---|---|---|
| Avatars | `web/party/avatars/` (DiceBear Gaze, already in the repository) | CC0 1.0 |
| BLUFF cover | `web/party/art/lan-bluff.svg` (first-party, already in the repository) | project |
| Gauntlet II and Bomberman covers | `web/party/art/kenney-*.svg` (Kenney Board Game Icons, already in the repository) | CC0 1.0 |
| EXPO, Worms, Spades, Checkers covers; the EXPO land; suit shapes | flat CSS shapes written for these prototypes; stand-ins for human-made art | project |
| EXPO housing grain | procedural noise (an SVG turbulence filter in the stylesheet); a stand-in for a material tile | project |
| Icons | Lucide (`lucide-static`, the set the shell already uses) | ISC |
| Typeface | Geist, bundled in `prototypes/shared/fonts/` with `OFL.txt` | SIL OFL 1.1 |

Spades and Checkers are not in the catalog; they are sample titles so the shelves have enough
on them. Every length ("15 min") and kind ("Co-op") is sample content: no title has either today.

## Skill review

The sprint's skill sequence was followed: `avrana-ux-ui` and `ui-radar` for research; impeccable
`shape`, `frontend-design` and `ui-design` to shape; impeccable `critique` and `anti-ui-slop`
to critique; impeccable `distill`, `typeset`, `layout` and `polish` to refine; then
`web-design-guidelines`, impeccable `audit` and `anti-ui-slop` again as the final review.
`impeccable init` was not run and no `PRODUCT.md` was created; the brief was the product context.

Two reviews were independent: a separate agent that had not built the concepts critiqued the
first draft, and the same agent validated the refined package against the brief, the accepted
decisions and the three review skills. Its findings below are reported as it gave them,
including the ones that were not fixed.

### Critique (impeccable critique, independent pass)

| Pass | Score | Outcome |
|---|---|---|
| First draft | 26 / 40, no P0 | Four P1: EXPO card states read by colour alone; the crew strip was crowded; the top bar overflowed at 360 px with the Limited mark; guests had no visible way to understand a briefing's exit. All four fixed |
| Refined package | 29 / 40, no P0 | Three P1 (below), all fixed. Error recovery stays the weakest heuristic (2 of 4): no reconnecting, empty or error state is drawn |

### impeccable audit (static, before the last fixes): 14 / 20

Accessibility 2, performance 3, responsive 3, theming 3, implementation integrity 3 (each of 4).
It was not re-scored after the fixes.

| Finding | What was done |
|---|---|
| P1: the Arcade landscape menu button was hidden by a CSS specificity bug | fixed |
| P1: control outlines at 1.67:1 (shell) and 2.17:1 (EXPO), under the 3:1 the accessibility contract requires | fixed: pressable edges are now 3.3:1 to 3.8:1 on every surface they sit on |
| P1: targets under 44 px (EXPO objectives header on short screens, the Library "All" tab) | fixed with invisible larger hit areas |
| P2: the "cannot be played" mark on a darkened yellow card was 1.78:1 | fixed: light mark on a dark disc |
| P2: focus ring and "chosen card" ring were the same amber | fixed: focus is white, chosen is amber |
| P2: tabs, sliders, disclosures and the trick cards are drawn, not wired, in the prototypes | left: a prototype limit, listed for implementation below |
| P3: darkened card faces are 1.4:1 to 1.8:1 against the tray | left: the text on them is 7.6:1 or better and the state has a mark and a sentence |

Text contrast on the shell tokens: primary 14.3:1 to 16.2:1, secondary 7.3:1 to 8.5:1, tertiary
5.0:1 to 5.8:1, across the ground, wells and the sheet surface.

Detector (`impeccable detect`), before the last fixes: 24 findings. 18 were "cramped padding"
on 52 px hairline rows (false positives); 5 were "overused font" for Geist, which the brief
asks for, and Geist Mono in EXPO, which has since been removed; 1 was tight leading on an EXPO
heading.

### anti-ui-slop finish gate

| Check | Verdict | Note |
|---|---|---|
| Generic dashboard or settings look | partly | Home, Library, detail and EXPO pass. System and Party are plain lists and read as "phone settings" to the validator. Left as drawn; flagged as a risk |
| Card inside card | pass | |
| Too many pills, chips, badges | pass | "Active" badges removed from objectives; two word-tags remain (You, Host) |
| Gradients and glow | pass | none |
| Purple as paint | pass | no violet fill anywhere. The validator's concern is the opposite: the material is subtle enough that the purple people will notice is in three lavender covers (existing art) |
| Decorative icons | partly | the caret before "Winning now" was removed. The lightning icon for "Reduce motion" is a weak match |
| Permanent explanatory copy | partly | the Host's consequence line under "Bring the Party in" was cut to seven words and kept on purpose: the button moves everyone and has no confirmation |
| Every section boxed | pass in the shell, partly in EXPO | every EXPO zone is a bordered plate; that is the field-unit idea and is the owner's call (decision 8) |
| Uniform radius and shadow | pass | |
| Sample numbers that look real | partly | "You played 25 minutes ago", every length and every kind are sample content, said so in SCREENS and above; they need D1 and R1 |
| Everything centred | pass | |
| Emoji as interface | pass | |
| Small label above a heading | fixed | the mission line above "Mission failed" moved below the cause. First run keeps the brand wordmark above its question |
| Other tells | fixed | monospace "readout" type removed from EXPO; truncated cover titles now wrap to two lines |

### web-design-guidelines (Vercel Web Interface Guidelines)

Fixed in the prototypes: the Arcade landscape menu; a stylesheet rule that overrode the
short-screen spacing in EXPO; targets under 44 px; a filter count that disagreed with the
filters set, and a "Show 3 games" over a list of seven; a toast with no dismiss; the current
winner line not announced; the label above the result heading; straight apostrophes in notices.

Left for implementation, because a static prototype cannot carry them: focus moved into and
back out of EXPO's sheets (the shell's drawer and Limited sheet do it since revision 2); keyboard handling on the length slider; `aria-selected` on
tabs and `aria-expanded` on the view menu and the objectives disclosure; `aria-describedby`
from a disabled burst option to its reason; the cards in the trick as real elements with real
names; rows drawn with a chevron that lead nowhere; a skip link, `theme-color`, image
dimensions, hover states and input names.

### Against the brief's first-review checklist (§30)

The validator marked 15 of 22 met and 7 partly met. Four of the seven were closed afterwards
(the Party control now appears on System; Limited wording agrees across Home, System and the
docs; the result marks the trick's winner; the audit questions the drawing answers are now
open decisions). Three remain partly met:

- **Artwork is primary** (item 9): four of seven covers are geometric stand-ins. The Library
  cannot be judged as artwork-first until human-made covers exist (R4).
- **EXPO's five zones** (item 15): at 360 × 640 the board shows one objective, and none while a
  burst is open. The rest are one tap away.
- **Accessibility in the layouts** (item 17): contrast, targets and non-colour states are in the
  drawings; semantics and focus behaviour are specified, not demonstrated.

### What the validator thinks could fail the "feels like Avrana" test

Reported as given, because they are the honest risks in this direction:

1. The shell could read as a Geist-on-black settings app. Atomic Purple is restrained enough to
   be nearly invisible as a material; the bottom bar and sheets were tinted a little further
   after this note, and it is still subtle by design (brief §4.1: not "a purple interface").
2. EXPO could read as a graphite dashboard with an amber accent, not an expedition. The world
   is one thin flat strip until real art exists.
3. The avatars and the placeholder covers carry most of the personality, and they are the
   loudest and least appliance-like things on every screen.

### Not checked

Nothing was tried on a real phone or with a screen reader. Focus order, keyboard use, iOS font rendering (the pictures show the Geist stand-in for the brand face) and touch
reach are unverified. The audit's measurements of today's UI were taken in a desktop browser at
phone viewports.

The findings above are from the first package's two review passes. Revision 1 was measured
again by the same independent agent (31 / 40, no P0); what it confirmed, what it found and what
was left is in [REVISION-1](REVISION-1.md#revalidation). The cases revision 2 changed were
measured again; see [REVISION-2](REVISION-2.md#revalidation). Enlarged text was checked only by
scaling the root font size in a desktop browser.

## Pictures that are not in Git

The owner's decision (2026-10-05): documents, prototypes, overview sheets and the evidence the
documents link to are committed; bulk screenshots and ZIP archives are not. About 34 MB of
pictures and a 35 MB archive would otherwise sit beside about 4 MB of tracked files.

| What | Where |
|---|---|
| `concepts/` (207 pictures; the names the documents cite, such as `r2-…-390x844.png`) | On the owner's development machine, beside the repository checkout: `avrana-party-design-evidence/ux-redesign-2026-10-05/` |
| `current/` (215 pictures of the UI at Party `578534f` and Games `a448972`) | the same folder |
| `SCREENS.zip` (an archive of the pictures) | the same folder |

That folder is not backed up by Git and exists on one machine. The concept pictures can be
taken again from the prototypes: from the repository root, with the development dependencies
installed (`npm ci`, `npx playwright install chromium`),

```
node docs/design/ux-redesign/capture/shoot.mjs <output folder> $(cat docs/design/ux-redesign/capture/jobs-r2-1x.txt)
```

and the other job lists in `capture/` in the same way (`DPR=2` in the environment for the
`-2x` lists). Each job is `name=page.html?switches@WIDTHxHEIGHT`. The `current/` pictures
cannot be retaken once the shell changes; the audits describe what they showed.

## What this phase did not do

No production file changed. No backend change. No merge, deploy, Pi access or service change.
The Games repository was read, not written. Nothing here was tried on a real phone: sizes were
checked in a desktop browser at phone viewports, so reach, glare, and one-handed use are
unverified. Motion is described in words only. The TV is not drawn.
