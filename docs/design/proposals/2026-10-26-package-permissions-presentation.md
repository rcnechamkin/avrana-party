# Package permissions and community-game trust presentation (AVR-62)

- **Status:** proposal, 2026-10-26. Nothing is implemented, and the contract vocabulary is unchanged. **Owner decisions required** (section 7).
- **Reads with:**
  - `avrana/contracts/game.py` (`PERMISSIONS`);
  - `avrana/avrgame/installed.py` (`GRANTABLE`, `ALWAYS_PROVIDED`) and `avrana/ops/install_game.py` (`_check_permissions`);
  - [AVRGAME-PACKAGE.md](../AVRGAME-PACKAGE.md) (sandbox, "NOT limited today");
  - `deploy/games/avrana-game@.service`;
  - `web/party/bridge/shim.js` (bridge v1);
  - the package-signing proposal (AVR-58, draft #230);
  - AVR-680 (game-origin trust tiers).

## 1. What is true today

The contract has **eight permission names** a game may request in `runtime.permissions`:

`persistent_storage`, `party_roster`, `controllers`, `microphone`, `camera`, `local_network`, `internet`, `host_devices`

| Layer | What enforces what | Source |
|---|---|---|
| **Server process** (the game's Python or Node process on the box) | `DynamicUser=yes`; `RestrictAddressFamilies=AF_UNIX` (no IP sockets at all); `PrivateDevices=yes`; `ProtectHome`, `ProtectKernel*`; a state directory only when `persistent_storage` is granted. `SystemCallFilter=` is deferred, and there is no disk quota. | `avrana-game@.service`, AVRGAME-PACKAGE.md |
| **Installer** | **Fails closed.** Only `persistent_storage` and `party_roster` can be granted, because a grant must not say more than the sandbox gives. `party_roster` must be requested and granted, because Core sends every game the roster. Anything else requested is recorded as "requested, not granted". | `install_game._check_permissions` |
| **Party Core at launch** | does not read grants; it relies on the unit and the installer | AVRGAME-PACKAGE.md |
| **The game's page in the guest's browser** | the kit's CSP: `default-src 'none'`, `connect-src 'self'`, `frame-src <party>`. **No `Permissions-Policy` header**, so the page may ask the browser for camera, microphone, motion, gamepads or geolocation like any web page, and the guest's browser prompt is the only gate. | `avrana_gamekit/helpers.page_policy` (Games) |
| **Party powers from a game page** | bridge v1 offers only `view`, `ticket`, `result`, `end`, and `navigate` with `to: "party"`. A game cannot post Party chat, a system line, or navigate the Party anywhere else. | `shim.js` |

So the box side is already strict and honest. The gap is the **browser side**: a declared or undeclared request for camera or microphone is decided only by the guest's browser.

## 2. Separate concepts, kept separate on every screen

| Concept | Question it answers | Comes from |
|---|---|---|
| **Source** | Where did this file come from? | the owner's action: USB, URL, repository |
| **Signature** | Who vouches for these exact bytes? | AVR-58: a publisher key, pinned on first use |
| **Provenance** | What was it built from? | AVR-58 statement: source revision, build |
| **Trust tier** | How much does the box let it do? | the appliance, never the package: `community` for every package today (AVR-680) |
| **Permissions** | What did the game ask for, and what was granted? | the contract's request, intersected with the owner's grant and what the box can enforce |

A signature never widens permissions. A permission screen never says "safe".

## 3. Vocabulary: keep the eight names and add one; present them as five groups

The names stay as they are; contract changes cost a version. One addition is proposed: **`motion_sensors`** (device orientation and motion). The browser exposes it, and it is the one sensor a party game is likely to want.

The owner and guest see five plain groups:

| Group shown | Contract names | Where it runs | Enforceable today? |
|---|---|---|---|
| **Saves things on the box** | `persistent_storage` | server | **yes**: no state directory without it |
| **Sees who is playing** (names and roles) | `party_roster` | server | always given: Core sends it. Shown as "always". |
| **Uses your phone's camera, microphone or motion sensors** | `camera`, `microphone`, `motion_sensors` | guest browser | **yes, with section 4** |
| **Uses controllers** | `controllers` | guest browser (Gamepad API) or the box (`host_devices`) | browser: with section 4; box: not grantable (no devices) |
| **Reaches the network or the Internet** | `local_network`, `internet` | server | **never granted**: AF_UNIX only. Shown as "not allowed on this box". |

`host_devices` stays not grantable.

## 4. Enforce the browser side with an appliance-owned `Permissions-Policy`

The box serves every game page, at `/games/<id>/` today and on the game origin later. It adds one response header to each, built from the **grant**, never from the package:

```
Permissions-Policy: camera=(), microphone=(), gyroscope=(), accelerometer=(), magnetometer=(),
                    gamepad=(), geolocation=(), usb=(), serial=(), bluetooth=(), display-capture=(),
                    payment=(), publickey-credentials-get=(), fullscreen=(self)
```

- A grant of `camera` changes `camera=()` to `camera=(self)`; the same goes for `microphone`, `motion_sensors` (gyroscope, accelerometer, magnetometer) and `controllers` (gamepad).
- Geolocation, USB, serial, Bluetooth, screen capture, payment and WebAuthn are never granted to a game.
- Where it is set: nginx. All native games share one location (`deploy/games/nginx-native-games.location`, `^/games/(?<native_game>…)/`), so:
  - the policy is chosen by a `map $native_game $avrana_permissions_policy { default "<deny all>"; <id> "<granted>"; … }`;
  - the installer regenerates that map from the install records, then runs `nginx -t` and reloads, as provisioning does today;
  - the location gets `add_header Permissions-Policy $avrana_permissions_policy always;` and `proxy_hide_header Permissions-Policy;`.
  A game cannot widen it: the header is the box's, and the game's own header is removed.
- **Undeclared access then fails closed in the browser**: a page that calls `getUserMedia` without the grant is refused by the browser, with no prompt.
- **Limits, said plainly:**
  - this binds the game's page and its frames, not a page on another site the game links to (the CSP and the bridge already stop navigation);
  - Safari's support for some features lags; where a browser ignores a feature, the guest's own prompt remains the gate.

## 5. What the owner and guests see

**At install** (owner page, or the `install-game` output until the page exists), for example:

```
Best Guess 0.4.0 · from a USB stick · signed by "Avrana Games" (key pinned 2026-11-02) · community game
This game:
  ✓ saves things on the box                       requested, will be allowed
  • sees who is playing                            always
  ✗ uses phones' microphones                       requested, NOT allowed unless you turn it on
  — reaches the Internet                           not asked (and never allowed on this box)
It cannot read other games' data, your Wi-Fi settings or anyone's chat.
```

**On the game's page in the catalog** (guests): only what is granted and needs the phone, e.g. "Uses your microphone if you allow it". Nothing is shown for what the game does not use.

**Privacy & Permissions center** (owner page): one table, games by permission groups, with the state for each cell: granted, requested and not granted, not requested, or not possible on this box. Each row has a switch for the browser-side groups, and changing a switch re-writes the header.

The words never claim isolation the box does not have:
- no system-call filter yet;
- no disk quota yet: a granted state directory can fill the disk. The center says so until a quota exists.

## 6. Exit criteria

| AVR-62 criterion | Answer |
|---|---|
| Small, comprehensible vocabulary | eight names (+`motion_sensors`), shown as five groups (section 3) |
| Undeclared privileged access fails closed where enforceable | box side: already (unit + installer); browser side: section 4 |
| Install UI explains meaningful risk | section 5, with what cannot be enforced stated |
| Trust, source, signature, provenance separate | section 2 |
| No arbitrary platform messages, no navigation outside the session | already true by bridge v1 (`navigate` only to `party`, no message API); a future game-to-Party message must be a new, granted capability (D4) |

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Add `motion_sensors` to the contract vocabulary | yes; later | **yes**, at the next contract version (AVR-72 window) |
| D2 | Set an appliance `Permissions-Policy` on game pages | now (deny all but granted); when community games arrive | **now**: first-party games request nothing it would block. Check BLUFF and EXPO first. |
| D3 | Can a guest see a game's permissions before joining it? | yes, only browser-side ones; no | **yes, browser-side only** |
| D4 | A future "game posts a line to Party chat" capability | never; a granted permission with a visible "from the game" label | **granted and labelled, later**; not in bridge v1 |
| D5 | Who can change grants after install | owner only; the host during a party | **owner only** |

## 8. Implementation sketch (not done here)

1. `installed.py`: map grants to a `Permissions-Policy` string (a pure function with a table test).
2. The installer writes the `map` include from every install record, then runs `nginx -t` and reloads. The native-games location adds the header and hides the game's own.
3. A browser test: a fixture game calls `getUserMedia` and `navigator.getGamepads()` without and with the grant, and is refused and then allowed.
4. Owner page: the install summary and the center, read from install records.
