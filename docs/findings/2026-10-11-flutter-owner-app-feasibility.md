# Flutter for the owner app: feasibility, 2026-10-11

Status: **research evidence (2026-10-11, AVR-424); a prototype on synthetic data and a desk assessment. Not a decision, not an architecture, and no appliance, phone or store was involved.**

The question: should Flutter power the planned commercial owner app (AVR-45)? This finding
records what a prototype showed, what Flutter does not give, and what would have to be proved on
real phones before choosing. The prototype is in
[`experiments/owner-app-flutter/`](../../experiments/owner-app-flutter/README.md).

## Short answer

Flutter is a credible way to build the owner app's **interface**. In an afternoon it gave four
themed, accessible, tested screens that look like Avrana and not like a Google app. It does **not**
decide any of the hard parts. Bluetooth pairing, joining the box's Wi-Fi, carrying certificates,
hosting downloaded game clients and store approval are operating-system and policy questions that
are the same size in any framework, and each needs native code or a plugin under Flutter.

Recommended: keep Flutter as the leading candidate, and choose only after a two-phone hardware
spike (below). Do not start a production app from this prototype.

## What was built and checked

| Item | Result |
|---|---|
| Environment | Windows 11, Flutter 3.47.7 stable, Dart 3.13.5 |
| Screens | Device Setup, Device Dashboard, Game Library (with a game's page), Party Management; bottom bar on a phone, rail at 600 wide and up |
| States drawn | scanning, Bluetooth off, permission denied, nothing found, pairing failed, box unreachable with last-known data, empty category, failed update, empty party, confirmation dialogs |
| `flutter analyze` | no issues |
| `flutter test` | 10 widget tests pass: navigation, the simulated labels, each setup failure, the unreachable state, the library, the party, the wide layout, Flutter's tap-target (48 and 44), labelled-target and text-contrast guidelines on every screen, and 200% text at 360 by 640 |
| Screenshots | 13 PNGs written by `tool/screenshots_test.dart` |
| Web release build | built with `--no-web-resources-cdn`; opened from a local static server in Chromium: 9 requests, all to the local server; about 8.2 MB uncompressed on first load (`main.dart.js` 2.3 MB, 0.7 MB gzipped; the CanvasKit engine 5.4 MB, 2.1 MB gzipped) |

Not done, and not claimed: an Android build (no Android SDK on this machine), an iOS build (needs
macOS and Xcode), any real phone, any screen reader, any Bluetooth or Wi-Fi call, the Geist
typeface (the prototype bundles Roboto; no Geist TTF is in the repository).

## What Flutter gives

- One codebase and one widget set for iOS and Android, with Material 3 widgets that take a
  hand-written colour scheme. The prototype maps the Design Foundation's Party roles straight into
  `ColorScheme`; nothing is tinted by a seed colour.
- Accessibility checks in the test runner (`meetsGuideline`), text scaling and semantics by
  default on mobile.
- Fast iteration on screens and states, which is where an owner app has most of its surface.
- Licence: BSD-3-Clause. Active project: stable 3.47 in August 2026; Android API 24 and up,
  iOS 15 and up.

## What Flutter does not give

Everything below is from platform documentation and general practice, **not tested here**.

### Bluetooth LE (pairing and the management plane, AVR-315)

| | iOS | Android |
|---|---|---|
| Permission | a Bluetooth usage string; the system prompt | `BLUETOOTH_SCAN` and `BLUETOOTH_CONNECT` at run time from API 31; location permission on older versions |
| Identity | no hardware address; a per-phone identifier for each peripheral | hardware address, often randomised |
| Bonding | the system decides when to show pairing; an app cannot force or script it | an app can ask to bond; behaviour varies by maker |
| Background | limited; scanning needs a service filter; long work wants the app in front | a foreground service of the connected-device type, declared to Play |

Consequences for Avrana: the pairing proof in AVR-315 (the matching code, session keys, replay
protection) must live in Avrana's own protocol above GATT, because the two systems' bonding
differs and neither is under the app's control. Flutter has no Bluetooth of its own. Plugin
choice matters: `flutter_blue_plus` is now under its own licence that requires a paid commercial
licence above an employee threshold and reports build telemetry; `flutter_reactive_ble`
(BSD-3-Clause, from the Philips Hue team) and `universal_ble` are alternatives; a thin platform
channel written in-house is the fourth option and removes the dependency.

### Joining the box's Wi-Fi

| | iOS | Android |
|---|---|---|
| Join a named network | `NEHotspotConfiguration`, with the Hotspot Configuration entitlement and a system prompt each time | `WifiNetworkSpecifier` (API 29 and up) with a system picker; the connection belongs to the app |
| List nearby networks | not available to ordinary apps | allowed with permission, throttled |
| Talk to a box with no internet | the Local Network permission prompt; the phone may keep mobile data as its default route | the app must bind its traffic to that network, or requests go out over mobile data |

Consequences: the phone should not be the one scanning for the owner's home Wi-Fi; the box can
scan and report the names over Bluetooth. Binding traffic to a no-internet network is native code
on Android and affects every HTTP call the app makes to the box, including any WebView.

### Offline delivery of game clients to the app (AVR-45, AVR-334)

- A WebView is a plugin (`webview_flutter`, first-party) around WKWebView and Android WebView.
  Serving a cached bundle from app storage under a proper origin needs native scheme or asset
  handlers that the plugin only partly exposes.
- Flutter cannot download and run new Dart code in a store build; that is not the model here
  anyway. Downloaded game material is web content inside a WebView.
- Whether Apple accepts a WebView that runs game clients fetched from a box (Review Guidelines
  2.5.2 and 4.7) and how Google Play's interpreted-code rule applies are open, as AVR-45 already
  records. Flutter neither helps nor hurts.

### Certificates (AVR-63, AVR-65)

- Neither system lets an app install a certificate authority silently. iOS needs a configuration
  profile and a manual trust switch in Settings; Android needs a manual install, and apps do not
  trust user-installed authorities by default.
- So guests' browsers can only trust the box through a publicly trusted certificate, which is the
  courier design's premise: the app carries a certificate signing request out and the certificate
  back, and the private key never leaves the box. The app's part is ordinary HTTPS and file
  transfer, which Flutter does well. Trust inside the app's own HTTP client can be pinned; trust
  inside a WebView is the platform's.

### Store policy

To be read against the current texts, and with counsel before any commercial claim: Apple's rules
on downloaded code and on hosted HTML5 games, the Bluetooth and Local Network purpose strings,
review of an app that needs hardware the reviewer does not have (a demo video or a review unit);
Google Play's data-safety form, permission and foreground-service declarations, and the yearly
target-API requirement. None is specific to Flutter.

## Dependency and maintenance risks

| Risk | Detail | Mitigation |
|---|---|---|
| Material is leaving the SDK | the in-SDK Material library was frozen in April 2026; `material_ui` 1.0 is on pub.dev and the SDK copy will be deprecated and later removed | start on `material_ui`; the prototype uses the SDK copy and would migrate with `dart fix` |
| Material 3 Expressive | not in Flutter's own library; third-party packages only | Avrana does not need it; the theme is its own |
| Bluetooth plugin licence | see above | choose a permissive plugin or write the channel |
| Toolchains | Xcode, Gradle and the Android plugin change every year; a Mac is required for iOS | budget recurring upkeep; CI on macOS |
| A second language | the repositories are Python and browser JavaScript; Dart is new, and Swift and Kotlin are still needed for the channels above | keep the native surface small and specified |
| Web target | CanvasKit build is about 8 MB and its accessibility tree is off until a user turns it on | never use Flutter web for guests or for a page the box serves |
| Prototype debt | this code has no architecture, storage or real state | throw it away; keep the theme mapping and the tests' shape |

## Alternatives, briefly

| Option | For | Against |
|---|---|---|
| Flutter | one interface codebase; strong widget tests; theme maps cleanly | native channels still needed; new language |
| Swift and Kotlin, two apps | direct access to every API above; no framework between the app and the hard parts | every screen built twice |
| Kotlin Multiplatform with native interfaces | shared logic, native Bluetooth and Wi-Fi | two interface codebases; younger tooling |
| React Native or Capacitor | reuses web skills | the same native-module work, plus a JavaScript bridge beside a WebView that hosts untrusted game code |
| Browser-only owner console | nothing to install | Web Bluetooth is not available in iOS Safari, so it cannot commission a box |

## Before choosing: a two-phone spike

After AVR-315 defines the management protocol, on one iPhone and one Android phone with a
prototype box:

1. Find and pair over Bluetooth with the matching-code step, using the candidate plugin and a
   thin in-house channel side by side.
2. Join the box's no-internet Wi-Fi from the app and complete one HTTPS request to it, with
   mobile data on.
3. Kill and reopen the app, walk out of range and back, and record what recovers by itself.
4. Load one game client in a WebView from the box (AVR-334's question).

Choose Flutter if the native code for steps 1, 2 and 4 stays small and stable. If most of the
app turns out to be those channels, two native apps are the simpler product.

## For the owner

- Is the owner app allowed to remove a guest or pass hosting? The prototype shows both to
  exercise menus and confirmations; Party's rule today is that Admin is not Host
  (`docs/design/PARTY-PLATFORM.md`), so this is undecided, not proposed.
- Which typeface file will the app ship? Geist is the interface face; a TTF or OTF is needed.
- Whether retail activation requires the app remains the open decision in AVR-45.

Sources checked 2026-10-11: [Flutter supported platforms](https://docs.flutter.dev/reference/supported-platforms),
[Flutter release notes](https://docs.flutter.dev/release/release-notes),
[Material and Cupertino decoupling](https://flutter.dev/blog/decoupling-material-cupertino),
[material-web](https://github.com/material-components/material-web),
[material-components-web](https://github.com/material-components/material-components-web),
[flutter_blue_plus licence](https://pub.dev/packages/flutter_blue_plus/license),
[flutter_reactive_ble](https://pub.dev/packages/flutter_reactive_ble).
