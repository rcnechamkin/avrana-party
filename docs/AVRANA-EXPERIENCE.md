# Avrana Party Experience Standard

> **Status: aspirational product guidance.** See `ROADMAP.md` and
> `design/README.md` for what is accepted, implemented, and still proposed.

## Purpose

Avrana Party should feel like a modern consumer product, not a hobbyist interface wrapped around emulators and web services.

A feature is not complete because it works.

It is complete when it:

- works reliably
- is immediately understandable
- feels responsive
- looks intentional
- behaves consistently
- remains accessible
- handles failure gracefully
- requires little or no explanation

This document defines the experience standard for the Avrana Party platform and games built on top of it.

---

## 1. Product Philosophy

Avrana Party is a local multiplayer platform.

The user should experience:

> Join. Understand. Play.

They should not need to understand:

- services
- runtimes
- sessions
- manifests
- WebSockets
- emulators
- device identities
- seat allocation
- networking
- reconnect timers
- backend state
- infrastructure terminology

Those are implementation details.

The platform exists to hide them.

---

## 2. The Platform Provides Capabilities, Not Screens

Avrana should expose reusable capabilities that games can compose according to their own needs.

Examples:

- player identity
- presence
- joining and leaving
- hosting
- teams
- spectators
- chat
- direct messaging
- game-specific communication
- voting
- ready states
- game actions
- reconnection
- controller input
- private displays
- shared displays
- notifications
- permissions

Games should not be forced into one generic Avrana interface.

Bomberman, Codenames, trivia, social deduction, card games, and racing games may present completely different interfaces while still using the same platform services underneath.

---

## 3. Default First, Override When Necessary

The platform should provide sensible defaults.

A normal game should require very little configuration.

Example:

    chat:
      mode: default

That should provide normal Party chat automatically.

Games with specialized requirements may override platform behavior.

Example:

    chat:
      mode: game_managed

The game may then define:

- who may send messages
- who may receive messages
- available channels
- team chat
- private messages
- spectator visibility
- rate limits
- phase restrictions
- role restrictions
- custom communication actions

Specialization should be optional.

The common case must remain simple.

---

## 4. Progressive Disclosure

Only show users controls relevant to what they are doing right now.

Do not expose every available capability simultaneously.

Examples:

- host controls appear only to the host
- spectator controls appear only when spectating
- chat expands only when requested
- diagnostics remain hidden from normal players
- team controls appear only in team games
- game-specific actions appear only during relevant phases

Complex systems should feel simple because complexity is revealed only when necessary.

---

## 5. Onboarding

Joining an Avrana Party should require as little thought as possible.

Ideal flow:

1. Join Avrana Party Wi-Fi.
2. Open Avrana Party.
3. Enter or confirm a display name.
4. Join the active Party.
5. Play.

Avoid unnecessary setup screens.

Avoid asking users questions whose answers can be inferred.

Avoid exposing technical terminology.

A returning device should be recognized when practical.

Reconnection should normally happen silently.

---

## 6. Interface Language

Use normal consumer language.

Prefer:

- Join
- Play
- Leave
- Chat
- Ready
- Spectate
- Host
- Reconnect

Avoid:

- establish session
- assign device
- runtime active
- websocket connected
- seat allocation
- service unavailable
- instance
- client state

Technical information may exist in diagnostics, but not in normal user flows.

---

## 7. Visual Hierarchy

Every screen should have an obvious primary purpose.

The most important content receives the most visual weight.

For games:

> The game is the interface.

Platform UI should avoid competing with gameplay.

Controls, chat, notifications, status indicators, and platform navigation should occupy only as much space as necessary.

Avoid permanent chrome when temporary UI will suffice.

---

## 8. Game Screen Design

Game video or game content should receive maximum practical screen space.

Never place controls over important game content unless the design explicitly requires it.

Account for:

- portrait orientation
- landscape orientation
- device safe areas
- notches
- Dynamic Island-style cutouts
- browser chrome
- different aspect ratios
- tablets
- unusually small phones

Portrait and landscape layouts may be intentionally different.

Do not force one responsive layout to serve every orientation badly.

---

## 9. Communication System

Chat is a platform capability.

It is not inherently a dedicated screen.

### Default behavior

Normal Party chat should support:

- player identity
- message history
- system events
- unread state
- lightweight notifications
- offline/local operation

### HUD behavior

During gameplay, recent messages may appear temporarily as a non-invasive overlay.

Example:

    Cody: that was terrible
    Audrey: MOVE
    Ben: ???

Messages should fade after a short period.

The overlay should:

- avoid blocking important game content
- avoid stealing input focus
- remain readable
- respect accessibility settings
- be easy to reopen

### Full feed

Players may open the full Party conversation when desired.

The full view may provide:

- history
- message composition
- channels
- reactions
- accessibility controls
- unread markers

Closing it should immediately return the player to gameplay.

---

## 10. Game-Specific Communication

Games may modify the communication model.

Examples include:

- team chat
- direct messages
- spectator-only chat
- dead-player chat
- role-specific chat
- phase-specific chat
- read-only feeds
- restricted sending
- predefined phrases
- temporary communication bans
- rate limiting

Games should define policy.

The platform should enforce it.

---

## 11. Game Actions Are Not Chat Messages

Communication infrastructure may transport game actions, but they should remain conceptually distinct.

Examples:

- clue
- vote
- accusation
- wager
- card selection
- answer
- emote
- ready state

A Codenames clue might travel through the same realtime system as chat, but it should render as a game element:

    ORBIT
    3

It may remain centered above the board rather than appearing as a disposable chat message.

The game determines presentation.

The platform provides transport, identity, authorization, state, and accessibility primitives.

---

## 12. Communication Permissions

The system should eventually support rules equivalent to:

    player:
      send:
        clue: true
        team_chat: false
        global_chat: false

      receive:
        team_chat: true
        global_chat: false
        system: true

Permissions may change dynamically during play.

Changing phases should immediately update what the player may send and receive.

The interface should reflect those permissions automatically.

Do not show unusable controls.

---

## 13. Rate Limiting and Anti-Spam

Games may allow playful interference without permitting abuse.

Example:

    global_chat:
      max_messages: 4
      window_seconds: 10
      cooldown_seconds: 20

Rate limits should be configurable by channel or role.

When limited, the user should receive understandable feedback.

Do not silently discard messages.

---

## 14. Responsiveness

Every input should receive immediate visual acknowledgment.

Examples:

- button press state
- loading indicator
- selection animation
- optimistic UI update
- short vibration where appropriate
- status change

A user should never wonder:

> Did that tap work?

Visual response should happen immediately even when the underlying operation requires additional time.

---

## 15. Latency Is Part of UX

For real-time games, latency is a product requirement.

The complete path should eventually be measurable:

    touch
    ↓
    browser input
    ↓
    network
    ↓
    Avrana runtime
    ↓
    game/emulator
    ↓
    frame capture
    ↓
    encode
    ↓
    network
    ↓
    decode
    ↓
    display

Measure each major stage independently.

Do not rely only on perceived lag.

Important metrics include:

- median latency
- p95 latency
- p99 latency
- jitter
- dropped frames
- encode time
- decode time
- network delay
- input processing delay

Random latency spikes are particularly damaging.

Stable latency is often preferable to lower average latency with severe jitter.

---

## 16. Performance Budgets

Features should have measurable budgets.

Examples may eventually include targets for:

- input latency
- frame delivery
- UI response time
- page load time
- reconnection time
- game launch time
- memory usage
- CPU usage
- wireless utilization

A feature that exceeds its performance budget should not be treated as complete merely because it functions.

---

## 17. Accessibility

Accessibility is platform infrastructure.

It should not be added after individual games are completed.

Platform components should support:

- semantic HTML
- screen readers
- logical focus order
- keyboard navigation where applicable
- scalable text
- sufficient contrast
- non-color-only state indicators
- large touch targets
- reduced motion
- safe-area awareness
- orientation changes
- descriptive labels
- status announcements
- error announcements

Games inherit accessible primitives wherever possible.

Custom game interfaces remain responsible for preserving those standards.

---

## 18. Motion

Animation should communicate state.

Good uses include:

- opening a panel
- confirming selection
- showing ownership changes
- bringing attention to a new message
- transitioning between Party and game states

Avoid animation that exists only to make the interface appear busy.

Support reduced-motion preferences.

Animations should never delay user interaction unnecessarily.

---

## 19. Notifications

Notifications should be contextual and restrained.

Examples:

- player joined
- host changed
- game started
- teammate messaged
- connection restored

Avoid excessive toast spam.

Repeated events may be grouped.

Gameplay notifications should avoid covering important controls or content.

---

## 20. System Events

System events and human messages are different information classes.

Examples:

    Audrey joined the Party
    Ben became Host
    Bomberman started
    Cody reconnected

System events may appear in Party history but should be visually distinct from human conversation.

Not every system event needs to appear in the gameplay HUD.

---

## 21. Error Handling

Errors should explain what happened in user language.

Bad:

    WebSocket connection failed: ECONNREFUSED

Better:

    Connection lost.
    Trying to reconnect…

If recovery succeeds, the interface should recover quietly.

Only ask the user to intervene when intervention is actually required.

Provide technical details separately when useful for diagnostics.

---

## 22. Reconnection

Temporary network interruption should not feel catastrophic.

Whenever possible:

1. retain local UI state
2. reconnect automatically
3. restore player identity
4. reclaim the player's role or seat
5. resynchronize state
6. continue

Do not send users back through onboarding for minor interruptions.

---

## 23. Offline-First Behavior

Avrana Party must behave normally without internet access.

Offline operation should not produce:

- broken cloud calls
- external font failures
- dead analytics requests
- certificate prompts
- CDN dependencies
- account login requests
- missing assets
- confusing browser errors

Core gameplay assets should exist locally.

Players should not need to understand that Avrana is operating offline.

---

## 24. Local-First Privacy

Party data should remain local unless a feature explicitly requires otherwise.

Normal operation should not require:

- accounts
- cloud identity
- telemetry uploads
- internet authentication
- external messaging services

Party identity should normally be temporary.

Party conversations may disappear when the Party ends unless a future feature explicitly requires persistence.

---

## 25. Host Experience

Being Host should grant additional capabilities without turning the interface into an administration console.

Host controls may include:

- choosing a game
- starting a game
- ending a game
- changing Party settings
- managing exceptional player issues

Normal host interaction should still feel consumer-oriented.

Advanced diagnostics belong elsewhere.

---

## 26. Spectators

Spectating is a first-class state.

A spectator may have different:

- views
- chat permissions
- game information
- controls
- notifications

Games decide whether spectators may join active play later.

The platform should not assume that spectating means inactivity.

---

## 27. Design System

Avrana should maintain a coherent platform design system.

Reusable primitives should eventually include:

- typography
- spacing
- buttons
- cards
- sheets
- dialogs
- menus
- overlays
- HUD messages
- chat
- inputs
- status indicators
- loading states
- error states
- player avatars
- player colors
- team indicators
- game launch states

Games may style these components while retaining recognizable interaction behavior.

Consistency reduces learning cost.

---

## 28. Platform Identity vs Game Identity

The concrete contract for this section is [GAME-UX-CONTRACT](design/GAME-UX-CONTRACT.md).

Games may have their own visual personality.

Avrana still needs recognizable platform behavior.

For example:

- closing chat behaves consistently
- reconnect states behave consistently
- leaving a game behaves consistently
- accessibility controls behave consistently
- host controls behave consistently

A game can look completely different without making basic interactions unfamiliar.

---

## 29. No Dead-End Screens

Every screen should provide a clear next action.

Avoid states where users must guess whether to:

- refresh
- go back
- wait
- reconnect
- reopen the browser
- restart the Party

When waiting is required, explain what is happening.

---

## 30. Testing With Real Humans

Automated tests are necessary but insufficient.

Important UX features should be tested with:

- real phones
- multiple simultaneous players
- different screen sizes
- portrait and landscape
- accidental disconnects
- late joiners
- spectators
- noisy wireless conditions
- users unfamiliar with the project

A system that only makes sense to the developer has failed its UX test.

---

## 31. Real-World Environments

Avrana should be designed for imperfect environments.

Examples:

- airplane rows
- cruise cabins
- hotel rooms
- bars
- living rooms
- conventions
- travel
- noisy public spaces

Assume players may:

- be unable to hear each other
- sit several meters apart
- have different phone models
- rotate their phones
- temporarily lose Wi-Fi
- arrive late
- leave early
- misunderstand instructions

The interface should remain resilient.

---

## 32. Quality Gate

Before declaring a user-facing feature complete, ask:

### Functionality
- Does it work?

### Clarity
- Would a first-time user understand it?

### Responsiveness
- Does every interaction acknowledge quickly?

### Accessibility
- Can different users operate it successfully?

### Failure
- What happens when the network or runtime misbehaves?

### Performance
- Does it meet its latency and resource expectations?

### Consistency
- Does it behave like the rest of Avrana?

### Presentation
- Does it look intentional?

### Complexity
- Are we exposing implementation details unnecessarily?

If several answers are weak, the feature is not finished.

---

## 33. Reference Standard

When evaluating Avrana UX, compare against modern consumer software rather than hobbyist projects.

Useful reference categories include:

- modern console interfaces
- multiplayer games
- party games
- mobile applications
- streaming applications
- contemporary messaging products

Open-source projects remain valuable sources of technology and interaction patterns, but their existing UX should not automatically define Avrana's quality ceiling.

---

## 34. Core Experience Rule

The platform may be technically complex.

The experience should not feel complex.

Avrana should hide infrastructure, expose intent, and let people get to the reason the device exists:

> being together and playing something.
