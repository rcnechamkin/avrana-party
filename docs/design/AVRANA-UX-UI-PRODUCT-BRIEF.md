# AVRANA UX/UI PRODUCT BRIEF

**Status:** Owner-approved v1 direction  
**Date:** 2026-10-05  
**Scope:** Avrana Party system shell, Party Core UX, Library/discovery, shared game UX, Arcade shell direction, and EXPO presentation direction  
**Audience:** Product/design agents, frontend agents, reviewers, orchestrators, future contributors

---

## 1. Purpose

Avrana Party is a portable local-first multiplayer appliance. Phones join and play without requiring a TV, upstream internet, or an installed player app.

This brief defines how the Avrana interface should feel, behave, and organize information across the system shell and first-party games.

It exists to prevent agents and contributors from inventing product direction while implementing UI work.

The goal is not to preserve the current frontend. The goal is to preserve Avrana's accepted behavior, authority boundaries, privacy, accessibility, game rules, and local-first product promise while substantially improving the user experience.

---

## 2. Product Character

Avrana should feel:

- **Playful**
- **Inviting**
- **Accessible**
- **Modern**
- **Streamlined**

Avrana should **not** feel:

- cartoony
- childish
- cutesy
- like a SaaS dashboard
- like a sysadmin/control portal
- AI-generated
- excessively technical
- unnecessarily complex
- overloaded with rounded cards, pills, widgets, or decorative panels
- like a generic retro-emulation frontend
- like a cyberpunk terminal
- like a literal 1990s interface recreation

The intended balance is a modern consumer game appliance with enough personality to feel playful, but enough restraint to feel deliberate and durable.

---

## 3. Core Design Principle

> **Party is the console. Games are the cartridges.**

The Avrana shell should have a coherent system identity, interaction language, navigation model, accessibility baseline, and social layer.

Individual games should inherit those platform expectations without being forced into the same palette, background, visual theme, or game-board style.

The shell should frame the experience, not visually overpower it.

---

## 4. Visual Language

### 4.1 Base palette

Use a mostly muted, monochromatic system palette.

The default shell should rely primarily on:

- near-black or dark neutral backgrounds
- restrained charcoal surfaces
- warm or neutral off-white primary text
- subdued secondary text
- minimal borders and separators
- restrained accent use

The UI should not become a "purple interface."

### 4.2 Atomic Purple reference

Avrana may use a **subtle smoky/translucent violet** as its default accent and material language.

The inspiration is the translucent Atomic Purple consumer-electronics aesthetic, but the reference should remain subtle.

Use the reference through:

- muted violet accents
- lightly translucent elevated surfaces
- selective edge highlights
- focus/selection states
- occasional material depth

Do **not** use:

- literal Game Boy UI motifs
- pixel fonts
- scanlines
- fake cartridge graphics
- faux retro operating-system chrome
- purple gradients everywhere
- heavy glassmorphism

The important idea is **material inspiration**, not retro cosplay.

### 4.3 Future themes

The default visual theme must not be structurally hardcoded into the information architecture.

Avrana should eventually support user-selectable themes.

Theme-sensitive decisions should therefore remain separable from:

- navigation
- layout
- game metadata
- authority
- accessibility
- Party state
- briefing flow
- game lifecycle

---

## 5. Typography

### 5.1 Temporary Avrana brand treatment

For now:

- Use **Helvetica Light** or the closest practical system Helvetica-style treatment for the "Avrana Party" brand/display text.
- This is temporary.
- Do not treat it as the final Avrana brand font.

### 5.2 Interface typography

Use **Geist** for general interface text where practical.

The system UI should prioritize legibility over personality.

Geist should cover:

- navigation
- buttons
- labels
- body text
- game metadata
- forms
- settings
- status
- filters
- warnings
- dialogs
- sheets

### 5.3 Current rounded font

The current rounded/playful font should not remain the general platform typeface.

It makes the whole product feel too whimsical and too close to a children's interface.

---

## 6. Density and Layout

Avrana should become noticeably more compact than the current Party UI.

Primary goals:

- reduce long vertical scrolling
- reduce giant cards
- reduce nested rounded containers
- reduce permanent explanatory copy
- prioritize content over chrome
- keep important actions within easy reach
- show more useful state in a single phone viewport
- use persistent navigation rather than one long page

Do not interpret "compact" as cramped.

Spacing should remain touch-friendly and readable.

The PlayStation mobile app is a useful **information-architecture reference** for compact console navigation, but Avrana should not visually clone it.

---

## 7. Primary Information Architecture

Treat Avrana as a **console operating environment**, not one large webpage.

The primary bottom navigation should contain:

1. **Home / Play**
2. **Party**
3. **Library**
4. **System / Settings**

These are major product modules.

### 7.1 Social layer

Social and Party-wide communication should sit in a distinct global layer, separate from the bottom module navigation.

This layer may include:

- Party presence
- Party chat
- notifications
- attention requests
- future game suggestions/votes

A useful structural model is:

- **Top:** people, social, notifications
- **Middle:** current content
- **Bottom:** primary Avrana modules

Do not interpret this as a requirement to visually copy another console app.

---

## 8. Home / Play

Home should answer quickly:

- Who am I?
- Who is here?
- What are we doing?
- What can we play next?

Home should not feel like account setup, diagnostics, or a web portal.

Likely emphasis:

- compact Party presence
- current activity if one exists
- continue/resume when appropriate
- recently played
- recommended games for the current Party
- obvious access to the full Library

Healthy infrastructure state should not dominate this screen.

---

## 9. Profile and Identity

Profile setup is important during first-run/onboarding.

Initial setup should prioritize:

- player name
- avatar

Once configured, profile management should recede.

Do not permanently dedicate major screen space to:

- "profile saved"
- browser storage explanations
- edit-profile forms
- account-like controls

Profile editing should be available when the player intentionally opens it.

The player should feel like a person in a Party, not an account record.

---

## 10. Party

The Party surface should make the group itself feel alive.

Primary information should include:

- current members
- avatars
- names
- Host
- Ready / Watch state where relevant
- current activity
- reconnect/away state when needed

The Party should feel like:

> "Here are the people in the room."

It should not feel like a membership form.

### 10.1 Party presence outside the Party page

Some compact Party state should remain available outside the Party page.

This persistent presence must stay restrained enough that it can eventually evolve into a universal overlay available during first-party and third-party games.

The exact universal Party HUD geometry is intentionally **not yet decided**.

---

## 11. Party Chat and Social Overlay

Party Chat should eventually be accessible as a global drawer or overlay from:

- Party Core
- Library
- briefings
- first-party games
- third-party games where platform integration permits it

On Party Core itself, chat/social access may have a dedicated top-level social affordance rather than being a large card embedded between unrelated sections.

Future social activity may include game suggestions such as:

> Player 2 wants to play EXPO.

The exact voting/suggestion interaction is intentionally open for later design.

---

## 12. Host

The Host is not a king, administrator, or superuser.

The Host is simply the person currently holding the metaphorical remote for the Party.

Use:

- a small neutral Host badge
- clear grouping of Host-only actions
- clear confirmation for Party-wide/destructive actions

Avoid:

- crowns
- royal imagery
- exaggerated status
- admin-panel language

Host authority should feel practical and temporary.

---

## 13. Technical and Health State

Err strongly toward **less technical** player-facing UI.

Healthy state should be mostly invisible.

Do not normally foreground:

- certificate state
- TLS details
- nginx
- services
- internal networking
- deployment state
- other operator-level diagnostics

### 13.1 Degraded and Limited Mode messaging

When something genuinely matters to play:

- show a compact, understandable banner or notice
- normally show technical/degraded notices only to the Party Host
- allow the Host to dismiss non-critical notices
- explain player impact, not infrastructure internals

Example principle:

Bad:
> Certificate validation failed.

Better:
> Some enhanced features are unavailable right now. Local play can continue.

Detailed diagnostics belong in System / Settings or operator tooling.

---

## 14. Library

The Library should feel like a standard modern console game library.

### 14.1 Default view

Default to a **medium cover-art grid**.

Also support:

- Large Grid
- Compact Grid
- List

List view may show richer descriptions and metadata.

### 14.2 Persist preferences

Remember per browser/device:

- chosen Library view
- useful sort preference
- useful filters where appropriate

### 14.3 Game tile hierarchy

Normal game tiles should emphasize:

1. cover artwork
2. title
3. restrained supporting metadata

Player count may appear as a small corner treatment on or near the artwork.

Do not turn every tile into a miniature dashboard.

### 14.4 Smart organization

Use current Party size to promote compatible games.

Useful top-level sections may include:

- Recently Played
- Favorites
- Great for Your Party
- All Games

Compatibility should influence ranking and recommendations, not erase games from the Library.

---

## 15. Library Categories and Filters

Initial useful categories/facets include:

- Party
- Co-op
- Competitive
- Team-based
- Free-for-all
- Classics
- Arcade / Console
- Quick Games
- Phone-only
- TV-only
- TV-enhanced

Filtering should support combinations such as:

### Player count
A direct selector or range.

### Duration
A sliding or range-based control for approximate game length.

### Gameplay genre/type
Examples:

- card game
- board game
- 2D strategy
- action
- trivia
- social deduction
- party
- puzzle
- arcade
- console

### Social format
Examples:

- co-op
- competitive
- teams
- free-for-all

### Display requirements
Examples:

- phone-only
- TV-only
- TV-enhanced

This taxonomy may grow over time.

Do not prematurely create dozens of categories simply because metadata supports them.

---

## 16. Games That Do Not Match the Current Party

Do not hide games simply because the current Party does not match their recommended/supported player count.

Keep them visible.

If the Host attempts to launch one:

- show an explicit compatibility warning
- explain the mismatch
- let the accepted game/platform rules determine whether launch is blocked or merely discouraged

Example:

> EXPO supports 2-5 players. Your current Party has 6.

Visibility is preferable to making the Library appear incomplete.

---

## 17. Browsing and Launch Flow

Selecting game artwork should **not** immediately launch the game.

Expected flow:

**Library → Game Detail / Briefing → Ready / Watch → Host Start → Game**

The detail/briefing surface should be able to show:

- artwork
- title
- short description
- player range
- approximate play time
- display requirements
- controls/capabilities where relevant
- Quick Start
- Rules access
- Ready / Watch
- game-specific setup when genuinely needed
- Host Start

Non-hosts may freely:

- browse
- inspect games
- read descriptions/rules
- favorite games
- eventually suggest/vote for games

Only the Host moves the Party into a game.

---

## 18. Shared Game UX Contract

Games should inherit platform-level expectations for:

- accessibility
- Party lifecycle behavior
- social overlays
- briefing/navigation behavior
- system sheets/dialogs where appropriate
- interaction quality
- unavailable-action clarity
- typography conventions where appropriate
- system-level motion behavior
- focus/touch behavior
- reduced-motion support

Games do **not** inherit a mandatory:

- palette
- background
- game-board style
- art direction

Each game may have a strong visual identity.

---

## 19. Motion

Motion should provide spatial continuity and make Avrana feel like a polished native console environment.

The desired reference is closer to modern iOS/native system movement than abrupt webpage route changes.

Examples:

- module changes should transition rather than flash
- launching a game should feel connected to the selected game
- result-to-Party transitions should feel intentional
- drawers/sheets should have coherent physical behavior

Avoid:

- constant floating
- ornamental bouncing
- motion for its own sake
- gratuitous glow effects

Exact:

- durations
- easing curves
- motion tokens

remain intentionally undecided for the first design phase.

The design agent should propose a restrained motion language rather than inventing permanent timing values during implementation.

---

## 20. Sound and Haptics

Avrana may use subtle platform-level cues for:

- player join
- Ready
- attention needed
- Host/lifecycle changes
- game launch
- error
- return/result transitions

Games retain ownership of their actual soundscape.

Sound/haptic preferences should eventually be adjustable per player/profile/device.

Do not assume every phone supports every haptic capability.

---

## 21. Accessibility

Accessibility is a product requirement from the beginning.

Require:

- WCAG AA contrast
- no color-only state
- meaningful screen-reader semantics
- reduced-motion support
- focus/keyboard behavior where relevant
- phone-appropriate touch targets
- resilient text scaling
- readable disabled/unavailable states
- critical information that does not disappear due to short screens
- interactive controls that remain understandable without visual effects

Accessibility should survive future themes.

---

## 22. Responsive Design

Primary design target:

- modern iPhone portrait
- modern Android portrait

Also support:

- smaller phones
- useful landscape layouts
- tablets
- desktop/browser testing

Do not design exclusively around large flagship-phone heights.

Use responsive rules based on available space and capability rather than hardcoding around a single current device.

Foldables and future dual-screen devices should degrade and adapt sensibly, but exact device-specific behavior is not required in the first redesign.

---

## 23. Artwork and Iconography

**No AI-generated images.**

This applies to:

- final artwork
- temporary decorative artwork
- concept images used as production dependencies

Allowed during design/implementation:

- neutral geometric placeholders
- CSS shapes
- simple hand-built placeholder surfaces
- open-source icon libraries/tools
- existing properly licensed assets

Final visual art and audio should be human-created or properly licensed.

The interface should remain usable even while placeholders are present.

---

## 24. Arcade / Console Shell Direction

Arcade is not currently the commercial center of Avrana, but it should still feel deliberate for owners/tinkerers who add their own games.

The current Arcade UI should not remain a giant black viewport surrounded by oversized generic buttons.

Future direction:

### Portrait
- artwork/title context
- game/video viewport as the dominant element
- minimal status chrome
- ergonomically grouped touch controls
- quick access to sound, leave, rotate, controller options

### Landscape
- viewport should dominate
- system chrome should recede
- controls may move to edges/overlay where appropriate
- compact access to settings should remain available

Future manifests may describe controller needs such as:

- d-pad + 2 buttons
- d-pad + 4 buttons
- dual stick
- custom

The exact future Arcade controller/layout framework remains intentionally undecided.

---

## 25. EXPO

### 25.1 Redesign authority

EXPO's current presentation may be redesigned **almost completely**.

Preserve:

- authoritative engine
- rules
- privacy
- state model
- accepted interaction requirements
- Party lifecycle boundaries
- the useful five-zone information model

Do not preserve LAN Games visual ancestry merely because it exists.

The existing frontend is a **behavioral reference**, not a visual foundation.

### 25.2 Provisional art direction

EXPO should feel like:

> **A dangerous radiated expedition viewed through rugged field equipment, while remaining clean and modern enough that the cards stay the primary gameplay object.**

This direction may be refined later.

No final AI-generated imagery.

### 25.3 Selective diegesis

Selective diegesis is encouraged.

Examples:

- Burst Transmission can feel like operating helmet-radio equipment
- major mission/environment changes can live in the world
- result presentation can use environmental/cinematic treatment

But ordinary gameplay must remain plainly understandable.

Never require a player to decipher decorative machinery just to:

- play a card
- understand an objective
- see whose turn it is
- identify a legal action
- understand why an action is unavailable

### 25.4 Five-zone information model

Preserve:

1. **Mission stage**
2. **Crew strip**
3. **Shared trick**
4. **Crew objectives/tasks**
5. **Private hand and controls**

Agents may redesign:

- proportions
- layout treatment
- transitions
- styling
- exact responsive behavior

Agents should not casually discard one of these information zones.

### 25.5 Current trick winner

The current winner of an unfinished trick should be available as authoritative/public game state.

Do not independently reimplement EXPO trick-winner rules in presentation code.

### 25.6 Results

Result presentation should follow:

**clarity first, spectacle second**

Players should immediately understand:

- success/failure
- what caused it
- relevant objective/task
- relevant triggering public action where determinable

Then cinematic/presentation layers may embellish the moment.

---

## 26. Backend and Architecture Freedom

Owner explicitly authorizes a substantial frontend and UX restructuring.

Agents may:

- restructure pages
- replace current DOM hierarchy
- create new shared frontend primitives
- change navigation architecture
- add new backend endpoints/state where genuinely required by the approved UX
- propose contract changes when necessary

Agents must preserve:

- Party Core authority
- game authority
- privacy
- security boundaries
- accepted Party↔game contracts unless deliberately revised
- game rules
- accessibility
- local-first behavior
- Limited Mode philosophy

Do not rewrite backend architecture merely because a visual redesign makes a different implementation more fashionable.

Backend changes require a concrete UX/product need.

---

## 27. Design Process

### Phase 1: Audit and design only

Do **not** begin with a large frontend rewrite.

First:

1. audit the current Party shell
2. audit Party Home/Play behavior
3. audit Party presence/social behavior
4. audit Library/discovery
5. audit game briefing/navigation
6. audit Limited/degraded presentation
7. audit Arcade
8. audit EXPO
9. identify unnecessary scroll/cardification/chrome
10. identify information-hierarchy problems
11. identify accessibility problems
12. identify visual dependencies inherited from LAN Games
13. identify backend gaps that the desired UX truly requires

### Phase 2: Propose information architecture

Show the proposed:

- navigation model
- persistent social layer
- Party presence model
- Library organization
- game detail/briefing flow
- Host action model
- degraded-state behavior
- EXPO gameplay hierarchy

### Phase 3: Produce design artifacts

Produce realistic phone-sized concepts/wireframes/mockups for at least:

1. Home / Play
2. Party
3. Library, medium grid
4. Library, list view
5. Game Detail / Briefing
6. Limited / degraded state
7. EXPO gameplay

Useful additional concepts:

- first-run profile setup
- social/chat drawer
- game suggestion/vote notification
- compact Party overlay
- Library filters
- Arcade portrait
- Arcade landscape

### Phase 4: Owner approval gate

Stop.

Do not perform the large rewrite until the owner explicitly approves the direction.

The approval question is:

> **Does this feel like Avrana?**

### Phase 5: Implementation

Only after approval:

- plan implementation slices
- identify backend prerequisites
- preserve behavior with tests
- implement in reviewable increments
- capture before/after screenshots
- test on real phones
- run accessibility review
- run reduced-motion review
- run multiple viewport sizes
- verify Party↔game behavior
- verify Limited Mode/degraded behavior

---

## 28. Reference Principles for Design Agents

When choosing between two plausible approaches:

### Prefer
- fewer controls
- clearer hierarchy
- compact information
- meaningful artwork
- direct language
- quiet system chrome
- persistent navigation
- explicit player-impact messaging
- reusable layout behavior
- accessible interactions
- system consistency where it helps
- strong game identity where it helps

### Avoid
- giant rounded cards for every section
- pill-shaped everything
- unnecessary dashboards
- excessive badges
- decorative telemetry
- technical jargon
- generic "AI product" visuals
- purple gradients
- glass surfaces everywhere
- hidden critical state
- animation that delays play
- game-specific rules duplicated into generic client UI
- preserving old layout solely because tests/screenshots expect it

---

## 29. Explicitly Undecided: DO NOT INFER

The following are intentionally open and should **not** be silently decided by an agent:

- final Avrana brand/display typeface
- final commercial art direction
- final custom illustration language
- exact motion timings
- exact easing curves
- final degree of EXPO diegesis
- final user-facing theme customization system
- deeper profile customization
- exact foldable/dual-screen device behavior
- exact universal Party HUD geometry inside games
- exact game voting UX
- exact future Arcade controller/layout manifest
- final sound library
- final haptic pattern library
- final TV-focused shell design

Agents may propose options during the design phase.

They may not convert a proposal into product policy without owner approval.

---

## 30. First Design Review Acceptance Criteria

The initial design package is ready for owner review when:

- [ ] all seven required screens are represented at realistic phone dimensions
- [ ] the shell no longer depends on one long vertically scrolling page
- [ ] primary bottom navigation is clear
- [ ] social/Party communication is represented as a distinct global layer
- [ ] profile management recedes after onboarding
- [ ] healthy infrastructure state is mostly invisible
- [ ] degraded/Limited Mode messaging is understandable and restrained
- [ ] Library supports at least grid and list concepts
- [ ] Library organization uses artwork as the primary browsing affordance
- [ ] filters can represent player count, duration, genre/social format, and display requirements
- [ ] incompatible games remain discoverable
- [ ] Host is visually practical, not regal
- [ ] Game Detail / Briefing clearly separates browsing from launching
- [ ] EXPO visibly departs from LAN Games aesthetics
- [ ] EXPO preserves the five-zone information hierarchy
- [ ] EXPO current trick winner has a clear place in the design
- [ ] accessibility has been considered in the layouts, not deferred
- [ ] smaller phone heights have been considered
- [ ] no AI-generated imagery is used
- [ ] open decisions are labeled as proposals rather than silently resolved
- [ ] the agent explicitly lists backend changes that would be required for the proposed UX
- [ ] the agent stops before the large implementation rewrite

---

## 31. Implementation Review Acceptance Criteria

After owner approval and implementation, each major slice should demonstrate:

- [ ] behavior preserved or intentionally changed with documented owner approval
- [ ] before/after screenshots
- [ ] real-phone validation
- [ ] small-phone validation
- [ ] relevant landscape validation
- [ ] reduced-motion validation
- [ ] keyboard/focus validation where relevant
- [ ] screen-reader/semantic review where relevant
- [ ] WCAG AA contrast
- [ ] no color-only critical state
- [ ] no new technical jargon leaking into player UI
- [ ] no new unnecessary permanent chrome
- [ ] no AI-generated artwork
- [ ] Party Host authority preserved
- [ ] non-host browsing preserved where intended
- [ ] Party↔game lifecycle preserved
- [ ] Limited Mode/degraded behavior still works
- [ ] game presentation remains non-authoritative
- [ ] tests updated for behavior rather than brittle pixels/DOM shape where possible

---

## 32. Summary

Avrana is not being redesigned to look "fancier."

It is being redesigned to feel like a **coherent game appliance**.

The system shell should be quiet, compact, readable, and inviting.

The Party should feel social.

The Library should feel like a real console library.

The Host should feel like the person holding the remote.

Games should have room to look like themselves.

EXPO should stop looking inherited from LAN Games and start feeling like a first-party Avrana title.

Technical complexity should recede until the player actually needs to know about it.

And the redesign should begin with **design evidence and owner approval**, not a giant speculative frontend rewrite.
