# Controller shortcut into the Party drawer (AVR-581)

Status: implemented for desktop Chromium behind nothing (it does nothing until a person sets it up);
hardware matrix **not measured**. Owner decisions from AVR-581 apply as written.

## What ships

- `web/party/lib/controller.js`: the rules. `web/party/lib/layer-app.js`: polling and the drawer's
  "Controller shortcut" group. `bridge/layer-mount.js` delegates `allow="gamepad"` to the Party frame.
- A connected controller **never** hides the floating button. The drawer then says so and offers
  "Set up a shortcut".
- Learning: hold the Home button, or two or three buttons together, for 0.8 s. One non-system button
  alone is refused (a game move waiting to happen). Then the same hold must work once ("verify")
  before anything is kept as working.
- Only after verification: "Hide the Party button while this controller is connected". It comes back
  on the next 50 ms poll after a disconnect, when no fitting pad is seen, or after 10 minutes without
  controller input. The setting is kept; a reconnect hides again only with that setting.
- The shortcut toggles the same compact drawer. It never acts: End, hand-over and the rest still need
  their own confirmation (and today a pointer or keyboard; D-pad navigation is future scope).
- Preference: `localStorage['avrana-controller/v1']` on the Party origin, this device only
  (`{v, shortcut: {buttons, mapping, id}, verified, hide}`). Anything malformed or of another version is
  forgotten; `hide` never holds without a verified shortcut. Account sync is deferred.
  Note: over a game page of another origin the frame's storage is partitioned by the top-level site in
  browsers that partition third-party storage, as the button position already is.

## Why a game cannot spoof it

The Gamepad API is read inside the Party-origin frame. The game page posts nothing about input to the
Party (`parseFromPage` accepts only viewport messages), and patching `navigator` in the game's own
document does not reach the frame's. The shortcut only opens the drawer; every Party action is still
a Core request with the Party credential and its own confirmation.

## Capability matrix (to fill on hardware)

| Platform / browser | Controller | Home/Guide delivered? | In a cross-origin frame? | Chord works? | Notes |
|---|---|---|---|---|---|
| Windows Chrome | Xbox (USB/BT) | not measured | not measured | Playwright fake only | |
| Windows Chrome | DualSense | not measured | not measured | not measured | |
| Android Chrome | Xbox BT | not measured | not measured | not measured | AVR-330 |
| iPhone Safari / PWA | Xbox / DualSense | not measured | not measured | not measured | |
| Linux Chromium (appliance TV) | any | not measured | not measured | not measured | |

Record browser, OS and controller firmware versions with each row. Expectation from public behaviour,
unverified here: browsers often reserve the Home/Guide button for the OS, which is why the chord path
exists and why the drawer never promises the Home button works.

## Open

- Whether Chromium delivers gamepad data to a `visibility:hidden` cross-origin frame (the hidden-button
  state) on real hardware.
- Gameplay conflict check against a game's declared controls: the Game Contract has no such
  declaration today, so the guard is "two buttons, held 0.8 s" plus the warning text.
- Two-player mid-game with real controllers (AVR-581 task 6).
