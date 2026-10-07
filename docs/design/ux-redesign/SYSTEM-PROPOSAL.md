# Avrana shell: cross-surface system proposal

Status: **PROPOSED (2026-10-05, revision 2). Design-phase proposal for owner review; nothing here is implemented or accepted.**

This is the short system that the [screen concepts](SCREENS.md) share. It follows the
[UX/UI product brief](../AVRANA-UX-UI-PRODUCT-BRIEF.md); where the brief decides something, this
file only says how the concepts apply it. Every value is a proposal taken from the prototype
stylesheets (`prototypes/shared/shell.css`, `prototypes/shared/expo.css`), which exist to make
the screens reviewable, not to be shipped. Tokens follow the screens, not the other way round.

## 1. Frame

Three layers, always in the same places.

| Layer | Where | Holds | Never holds |
|---|---|---|---|
| People | top edge | the Party control: faces, a count of new things; the social drawer comes down from it | module navigation, health |
| Content | middle, the only part that scrolls | the module | permanent explanation, status prose |
| Modules | bottom edge | Home, Party, Library, System | chat, profile, notifications |

Spatial rule: **people come down from the top; things about what is on screen come up from the
bottom.** The social drawer and a suggestion drop from the Party control. Filters, your profile
and (later) rules rise as bottom sheets. A phone never has both open.

The briefing is the one shell surface without the bottom bar: the Party is in one place
together, so there is nowhere else to go (ADR 0011). The Party control stays (open decision 1 in
[BACKEND-GAPS](BACKEND-GAPS.md#open-owner-decisions)).

## 2. Density and spacing

- 4 px base. Side gutter 16. Section gap 26. Rows 52 to 56. Controls 44 to 48.
- No section is a card. Sections are a heading and content; rows are separated by a hairline.
  The only filled surfaces are: the search field, a notice, and the two material surfaces below.
- A screen states its main fact as one sentence in large type ("Four of you are here.",
  "Choosing a game") in place of a labelled panel.
- Measured on the concepts: Home, Party, System and the briefing fit one 390 × 844 viewport
  without scrolling; Home needs about 160 px of scroll at 390 × 664 (the second shelf); the
  Library scrolls by design. Today's Home is about three viewports tall at 390 × 844.

## 3. Typography

| Role | Face | Size / weight | Use |
|---|---|---|---|
| Brand | Helvetica Neue Light or Helvetica Light where the phone has it, otherwise Geist at weight 300 | 23 px / 300 | the words "Avrana Party" only (temporary, brief §5.1) |
| Statement | Geist | 28 px / 550, tight | one per screen |
| Module title, game title | Geist | 22 px / 550 | top bar, hero |
| Section | Geist | 17 px / 550 | shelf and group headings |
| Body, controls | Geist | 15 px / 400 to 550 | everything else |
| Supporting | Geist | 13 px / 400 | one line of metadata |
| Smallest | Geist | 11 to 12 px / 500 | seat counts on covers, tags, tab labels |

Sentence case everywhere. No all-caps labels, no label above a heading, no monospace anywhere
(EXPO included: figures are tabular, in the same face). Sizes are `rem`. Android and Windows have no Helvetica (Windows silently substitutes
Arial for the name), so the brand face is asked for by its installed names only and Geist Light
stands in everywhere else; the brand line never falls back to a default sans. The screenshots
were taken on Windows and therefore show the Geist Light stand-in, not Helvetica. Geist is bundled (SIL OFL 1.1); no font is
fetched from outside the appliance.

## 4. Colour, surface and elevation

- Ground: near-black neutral (`#0d0d0f`), two quiet steps above it for wells and filled fields.
- Text: warm off-white (`#edeae4`), two greys for supporting and tertiary text. All text pairs
  in the concepts meet WCAG AA when computed from the stylesheet's colour values (see the review
  section of the [README](README.md#skill-review)); nothing was measured on a screen.
- The primary button is off-white with dark text. **No control is filled violet.**
- The edge of anything pressable (a secondary button, a field, a segmented control) is 3:1 or
  better against the surface it sits on. Hairlines between rows are quieter; they separate, they
  do not mark a control.
- State colour is amber (attention) and a soft red (destructive text), always with a word or an
  icon. Green is not used in the shell.
- Elevation is two levels: the page, and the material surfaces. Shadows appear only under things
  that float over content (the drawer, a sheet, a toast, the view menu).

### Atomic Purple, as a material

The smoky violet appears in exactly these places:

1. the bottom module bar (translucent over content, a one-pixel lit edge);
2. sheets, the social drawer, the toast and the view menu (the same surface, opaque: a smoky
   violet a few steps off neutral, with the lit edge doing most of the work);
3. the active-module marker (a 2 px bar);
4. focus rings, text selection and the caret;
5. the selected state of a toggle or a chosen option (a faint violet wash with a violet edge).

It is never a gradient, never a button fill, never a background for a whole region. A theme is a
different set of token values; no layout or component depends on the violet.

## 5. Iconography

Lucide, one stroke weight, used for system controls only. Every icon-only control has an
accessible name; wherever state matters the icon sits beside a word. No emoji. Game art is never
an icon from the system set.

## 6. Artwork

Covers are square (the existing cover slot) with one radius. A cover may carry one mark: seats,
bottom left. Titles without artwork show a flat geometric stand-in with the title set on it;
the concepts use them for EXPO, Worms, Spades and Checkers. No generated imagery anywhere.
The Library only becomes what the brief describes when each title has real cover art; that is a
human asset task, listed in [BACKEND-GAPS](BACKEND-GAPS.md).

## 7. Bottom navigation

Four destinations, icon above label, 58 px plus the home-indicator inset. The current one is
marked by weight, full-strength text and the violet bar, never by colour alone. It is present on
Home, Party, Library, a game's detail page and System; absent on first run, the briefing and
inside a game.

## 8. Social layer

- **Party control** (top right, everywhere in the shell): three faces, "+N" for the rest, and a
  count of unread things. One control, one drawer, opening over whatever page is open (the briefing included) and closing back to it. On the Party page, where the faces are the page, it shows the
  chat mark instead.
- **Social drawer**: comes down from the top. Tabs: Chat, People. System lines ("Priya joined",
  "Sam suggested EXPO") are in the same stream, styled as system text, never as a person's words.
- **Toast**: a suggestion or an attention request drops from the same edge, names the person,
  offers one action, and retracts into the count.
- Inside a game nothing of this is drawn in the concepts. A Party overlay during play is not
  designed here: its geometry is undecided (brief §29) and it needs an ADR 0011 amendment.

## 9. Sheets and dialogs

- Bottom sheet: grab handle, title, Close, scrolling body, one primary action pinned at the
  bottom ("Show 5 games", "Save"). Modal for assistive technology: `role="dialog"`,
  `aria-modal`, focus moved in and returned, Escape and Close both dismiss. (This is the
  specification. The static prototypes open and close sheets but do not manage focus.)
- Menu: small anchored list for a one-of choice (Library view).
- Destructive confirmation: one dialog, Cancel and the destructive verb, Cancel focused, as the
  owner decided for ending a game (GAME-UX-CONTRACT §8). Not drawn as a concept; the form is
  already decided.

## 10. Host

The Host is marked with the word "Host" in a small outlined tag, the same tag that marks "You".
No crown, no colour, no larger avatar. Host-only actions sit where the action is (the button on
a game's detail page, Start on the briefing, a row on the Party page) and each says what it does
to everyone in one short line ("Moves everyone to the briefing. Nothing starts yet."). Everyone
else sees, in the same place, who they are waiting for by name.

## 11. Motion principles (proposal; no timings)

Motion explains where something came from and where it went. Nothing loops, bounces or glows.

| Moment | Proposed behaviour |
|---|---|
| Module change | content cross-fades with a short shift in the direction of travel along the bar; the marker slides |
| Cover to game detail | the cover grows into the header art; the title travels with it |
| Detail to briefing (Host's phone) | art and title hold still; facts and button give way to the line-up; the module bar leaves downward; the dock arrives |
| The Party moves (other phones) | the current content recedes and the briefing arrives with one announced line ("Dana brought the Party to BLUFF") |
| Briefing to game | the cover expands, then a cut or short fade to the game's own first frame; no branded interstitial |
| Result to Party | the game recedes into its cover on Home |
| Drawer, sheet, toast | drawer and toast travel from the top edge and back; sheets from the bottom edge and back |
| EXPO: card played | the card travels from hand to its place in the trick |
| EXPO: winning changes | the marker moves from one card to the other |
| EXPO: result | the verdict is on screen at once; evidence follows it |

Reduced motion replaces every row with an instant change plus the same words. Durations and
easing are deliberately not proposed (brief §19, §29).

## 12. Accessibility principles

- Contrast: AA for all text and control outlines, checked on the token pairs in use.
- State is never colour alone: Host and You are words; Away is a word, an icon and a dimmed
  face; a game that does not fit is a word, an icon and amber; an unavailable EXPO card is
  darkened, keeps its suit colour, shape and word, and carries a struck-circle mark, with the
  reason in a sentence; the winning card is raised, outlined and
  named in a fixed line.
- Targets: 44 × 44 CSS px minimum for anything tappable, including cards in the hand. Small
  drawn controls (a switch, a slider knob, the Limited mark) get an invisible larger hit area.
- Text scales: `rem` sizes, the content column scrolls, nothing important is clipped at short
  heights (checked at 390 × 664 and 360 × 640). At 150% and 200% text the shell reflows: grids
  drop a column, the Play / Watch pair stacks, the briefing's dock joins the page, the top bar
  keeps one face and the count. EXPO's fixed board becomes one scrolling column with only the
  action keys pinned (revision 2; nothing scrolls inside anything else). These were checked by scaling the root font size in a desktop browser (over a
  hundred pictures taken, a selection kept); they are not a test with a phone's text setting or
  a screen reader.
- Semantics: real buttons and links, labelled landmarks, live status lines for turn, current
  winner and result, names in `bdi`. The prototypes are not a reference for semantics: tabs,
  sliders and disclosures in them are drawn, not wired (listed in the
  [README](README.md#skill-review)).
- Reduced motion and higher contrast follow the phone by default and can be set per device in
  System.

### Trouble has one grammar

Every "something is wrong" state uses the same parts: an icon, a few words, amber only when a
person should act, and the consequence written where it bites.

| State | Where it is said | What it does to controls |
|---|---|---|
| Limited Mode (this phone) | notice on Home once, then a mark on every page that opens the explanation as a sheet in place; a line under each affected title in every Library view | Play unavailable on a briefing, with the reason |
| Appliance trouble | Host-only notice on Home; "Off for now" under the affected title for everyone | the Host's button unavailable, with the reason |
| Reconnecting | one quiet line under the top bar; content stays, marked as possibly stale | actions that need the box are unavailable |
| Out of reach | a notice with what to check and "Try again" | the same |
| Host away (drawn on Home, the Party page and a briefing; a Host with a place in a round that is on is never Away and keeps the role) | "Away" on the Host's face; one line where Start would be | Start cannot happen; nothing else changes |
| Hosting has passed | a dismissible notice for the new Host; one line for everyone else | the new Host gets the Host's controls |
| Nothing found | the query or the filters named, and the one action that undoes it | none |

## 13. Responsive behaviour

- Designed at 390 × 844 and checked at 390 × 664 (an iPhone inside Safari, which is the common
  case because guests do not install anything) and 360 × 640.
- Rules respond to available height as well as width: short screens tighten type and art before
  they hide anything; what is hidden is one tap away, never the primary action.
- Tablet and desktop keep a centred phone-width column for now. A wide layout is not designed.
- Foldables get no special behaviour (brief §22).
