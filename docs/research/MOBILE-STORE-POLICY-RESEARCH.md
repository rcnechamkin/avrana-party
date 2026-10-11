# Mobile store policy and platform limits for the owner app and storefront (research)

- **Status:** Research, unverified where marked. Not legal advice. External claims are paraphrased from the cited pages as accessed 2026-10-09.
- **Date:** 2026-10-10
- **Sources:** Apple App Store Review Guidelines (https://developer.apple.com/app-store/review/guidelines/); Apple DMA page (https://developer.apple.com/support/dma-and-apps-in-the-eu/); Google Play payments and dynamic-code policies (https://support.google.com/googleplay/android-developer/answer/9858738, https://support.google.com/googleplay/android-developer/answer/9888379); Android Bluetooth permissions; caniuse Web Bluetooth; secondary sources named inline. Linear AVR-45, AVR-143, AVR-316.
- **Related:** `docs/research/OWNER-APP-ARCHITECTURE.md`, `docs/research/BLE-OWNER-CONTROL-PLANE-SPIKE.md`

> **Reconciliation note (2026-10-10, AVR-335).** Where this note says the app must not execute or load game material, that holds for the package; hosting a downloaded web client (AVR-45) is a separate proposal and its policy status is open. Apple 2.5.2 and 4.7 and the Google Play dynamic-code text were re-read from the primary pages on 2026-10-10 and are summarized, with what remains to be validated, in [Portable game-client delivery](../design/PORTABLE-GAME-CLIENT-DELIVERY.md) section 10. No conclusion about legality is drawn, and no manual-import or sideload path is relied on. The text below is otherwise as written on 2026-10-09/10.

## Scope and caveats

Research note, **not legal advice**, no decision. External pages were read on **2026-10-09** through a summarising fetch tool, so wording is paraphrase unless quoted, and quotes are short. Content was not re-fetched on 2026-10-10. **Anything marked [NOT VERIFIED] could not be confirmed from a primary source and must not be relied on without counsel.** Several fetches returned incomplete page text (Apple's guidelines page truncated after 5.3.4; the Local Network page returned only a title).

Direction context (2026-10-09/10, **Approved direction**): the owner app is a first-class commercial requirement (AVR-45) and an optional official storefront for licensed games is approved (AVR-143). The constraints below are therefore design inputs for AVR-45, AVR-315 and AVR-316 rather than hypotheticals. Friend-ready 1.0 has no app or store dependency. "Section x" of the architecture note means `OWNER-APP-ARCHITECTURE.md`.

## 0. Summary: top risks, in order

1. **Selling games or entitlements inside the app (digital goods consumed on another device).** Both
   stores require their own billing for in-app digital goods unless an exception or link-out
   programme applies. Game packages that run on the appliance, not on the phone, do not obviously
   fit any named exception. Fee level is 15-30%-class and in flux (§A3, §B1).
2. **"App as a store for other software" and "app that downloads code that changes features".**
   Apple 2.5.2 and 3.2.2(i)/4.7, Google dynamic-code rule. The architecture note mitigates by never running or
   interpreting packages on the phone: the app moves opaque bytes to an appliance. Reviewer
   interpretation risk remains (§A1, §A2, §B2).
3. **iOS BLE and Local Network limits** make background courier and automatic discovery unreliable
   without foreground use; design must be foreground-session based (§C).
4. **No Web Bluetooth on iOS** (§C1) means no browser-only owner flow; a native app is the only BLE path
   on iPhone (§D). The no-app promise stays true for guests, not for BLE management.
5. **Policy volatility** (US link-out litigation, EU terms changing 2026-10-01, Google fee programmes
   changing 2026-06-30). Treat every number here as perishable.

## A. Apple

### A1. 2.5.2 downloading executable code; interpreted code
Source: App Store Review Guidelines, https://developer.apple.com/app-store/review/guidelines/
(page shows no revision date; accessed 2026-10-09).
- Text: apps must be "self-contained in their bundles" and may not "download, install, or execute
  code which introduces or changes features or functionality of the app, including other apps"; a
  narrow exception for educational apps that teach or test code.
- Interpreted-code allowance lives in the Apple Developer Program License Agreement, not the guidelines.
  A forum quote of the June 2022 text says downloaded interpreted code is allowed only if it does not
  change the app's primary purpose, does not "create a store or storefront for other code", and does
  not bypass signing/sandbox (https://lists.squeakfoundation.org/archives/list/vm-dev@lists.squeakfoundation.org/message/3VU454MMCALFKVBRVGXATZAA6YJOIWFI/,
  secondary source; **current agreement text [NOT VERIFIED]**; the EU page cites an agreement updated
  2026-08-18).
- **Constrains the architecture:** (i) the app must not execute downloaded game code (packages are native Linux
  code for the appliance, and `client/` bundles are JS for a WebView); (ii) a storefront for software
  inside the app is the exact pattern the clause fears; (iii) iSH-type enforcement history shows
  reviewers act on "remote package updating" (same Squeak/forum source, secondary).
- **Mitigation:** the app treats a package as an opaque file it transports and the appliance verifies
  (architecture note section 6). It does not unpack, render, or run it. The client-host phase client hosting is optional and separate.
- **Open question for counsel:** is an app that downloads a third-party file and uploads it to
  hardware a "storefront for other code" even though the code never runs on the phone? Also whether the
  App Review "hardware companion" framing helps (3.1.4 and 2.4.3 are about features/hardware inputs, not stores).

### A2. 3.2.2(i) and 4.7 (software inside apps)
Same guidelines page. 3.2.2(i): unacceptable to create "an interface for displaying third-party apps,
extensions, or plug-ins similar to the App Store or as a general-interest collection". 4.7 allows mini
apps/games/plug-ins subject to 4.7.1-4.7.5, including an index of software and metadata (4.7.4) and no
exposure of native APIs to that software without permission (4.7.2).
- **Constrains the architecture:** The client-host phase (hosting game clients in a WebView) falls under 4.7; a catalog UI that
  lists third-party games could fall under 3.2.2(i) if general-interest. A curated Avrana catalog that
  only manages the owner's own appliance may be argued as a specific purpose (3.2.1(ii)).
- **Mitigation:** curated, owner-specific, no native APIs to games, an index with metadata.
- **Open:** whether 4.7 even applies when games run on separate hardware; a pre-submission
  conversation with App Review is possible [NOT VERIFIED how available].

### A3. 3.1.1 in-app purchase for digital goods consumed elsewhere
Same page. 3.1.1: to "unlock features or functionality within your app" you must use in-app purchase,
and apps may not use "license keys, augmented reality markers, QR codes, cryptocurrencies" etc. 3.1.1(a):
link-out entitlements exist; they "are not required" for US storefront apps. 3.1.3(b) multiplatform
services allow access to content acquired elsewhere "provided those items are also available as
in-app purchases within the app". 3.1.3(e): physical goods and services consumed outside the app use
other payment. 3.1.4: hardware-specific features may unlock without IAP only "when features are
dependent upon specific hardware to function" (telescope example) and optional features need an IAP
option as well.
- **Constrains the architecture:** an entitlement token for a game the appliance will run is a licence key for
  digital content. Argument for 3.1.4 (the content only works with Avrana hardware) is plausible but
  untested; the guideline says optional hardware-combined features also need an IAP option.
- **Mitigations (pick with counsel):** (a) the app only *lists and installs* games bought on the
  web (3.1.3(b)-style, "reader"-like behaviour), no price in app, US link-out where permitted;
  (b) IAP in app at the store fee; (c) paid purchases only in a website/Avrana web store, with
  owner app consuming a signed token (no purchase UI).
- **Open for counsel:** is a game package "consumed on other hardware" (3.1.3(e) is about physical
  goods/services, not digital) a digital good needing IAP? Not answered in the text that was read.

### A4. US link-out and commissions
Sources: Ninth Circuit summary https://www.fenwick.com/insights/publications/ninth-circuit-largely-upholds-ruling-in-epic-v-apple
and https://perkinscoie.com/insights/update/epic-v-apple-ninth-circuit-weighs-in (search snippet;
secondary). Per those: on 2025-12-11 the court largely upheld the contempt order but held the total
ban on commissions overbroad and allowed Apple a cost-based commission, remanded to the district
court. **Current permitted US fee on link-outs [NOT VERIFIED]; no 2026 remand result found.**
- **Constrains the architecture:** do not model margin on "free US link-out" forever.

### A5. EU DMA alternative distribution
Source: https://developer.apple.com/support/dma-and-apps-in-the-eu/ (accessed 2026-10-09; refers to
terms updated 2026-08-18, in force from 2026-10-01).
- Alternative marketplaces and Web Distribution exist for notarized apps; a 5% Core Technology
  Commission applies outside the App Store; App Store rates listed as 26% / 15% (IAP), 20% / 10%
  (alternative payment in app), 15% / 10% (store services for link-outs) from 2026-10-01; eligibility
  needs a financial-stability criterion (for example an audit, a letter of credit, 1M installs).
- **Constrains the architecture:** an EU-only web-distributed owner app could avoid App Review's 2.5.2/IAP but
  carries CTC, notarization and eligibility. Does not help outside the EU.
- **Open:** the interaction of CTC with a catalog whose goods run off-device; the €1M letter-of-credit
  burden for a small company.

### A6. Core Bluetooth background limits
Source: Apple archive doc,
https://developer.apple.com/library/archive/documentation/NetworkingInternetWeb/Conceptual/CoreBluetooth_concepts/CoreBluetoothBackgroundProcessingForIOSApps/PerformingTasksWhileYourAppIsInTheBackground.html
(archived; may be out of date). Without `bluetooth-central` the app is suspended and cannot scan;
with it, duplicate-scan reporting is ignored and scan interval grows when all scanners are in
background; a woken app has about 10 s; state restoration exists for system-terminated apps. User
force-quit behaviour **[NOT VERIFIED from this page]**, commonly understood to stop relaunches.
- **Constrains the architecture:** BLE control sessions should be **foreground user sessions**, not
  background sync. An "install finished" notification can be a local notification from the appliance
  event only while the app is alive. No promise of unattended background pairing or cert renewal.

### A7. AccessorySetupKit (iOS 18+)
Source: https://developer.apple.com/documentation/accessorysetupkit (search results only, page
body not read; https://punchthrough.com/ios18-accessorysetupkit-everything-ble-developers-need-to-know/).
Provides privacy-preserving discovery and setup of a specific accessory; pairing without the usual
Bluetooth permission prompt, removal deletes the bond. **Whether it avoids location permission, and
its Info.plist and entitlement requirements, [NOT VERIFIED].**
- **Constrains the architecture:** use it for the iOS claim flow if it fits; Android needs its own path.

### A8. Local Network privacy (iOS 14+)
Source: https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription
(page body not returned by the fetch; **everything below is general knowledge [NOT VERIFIED]**):
direct LAN connections or Bonjour trigger a one-time permission prompt, with `NSLocalNetworkUsageDescription`
and `NSBonjourServices` required; denial blocks LAN calls.
- **Constrains the architecture:** bulk transfer over local Wi-Fi (architecture note section 6) triggers the prompt and requires the
  phone to be on the Party AP, which on iOS often means cellular is bypassed and the Internet is
  unavailable. Keep bulk staging over Wi-Fi a user-initiated foreground step; allow USB/Files import as an alternative. BLE is not a transfer path (AVR-315).

## B. Google Play

### B1. Payments policy
Source: https://support.google.com/googleplay/android-developer/answer/9858738 (accessed
2026-10-09; no revision date on page). Charging for downloads, in-app features, virtual items,
subscriptions or "cloud software and services" must use Play billing; exempt categories are physical
goods/services, remittances, peer-to-peer and similar; steering users to non-Play payment is generally
prohibited except via alternative-billing / external-offer programmes in eligible regions. **The
page names no exemption for digital content consumed on a separate device.**
- US: an injunction required Google to allow alternative billing and external links in the US from
  2025-10-29 (https://9to5google.com/2025/10/30/google-play-now-allows-android-apps-to-use-other-billing-systems-in-the-us/,
  headline only fetched). Fee levels for External Payments / external content links reportedly 10%
  (subscriptions) and 20% (other) with per-install fees on link-outs
  (https://tech.slashdot.org/story/26/06/25/0554234/ via search summary); sources disagree on whether
  these apply to the US. **Current US terms [NOT VERIFIED]; check Play Console help.**
- **Constrains the architecture:** same as A3: a storefront in the Android app likely needs Play billing or an
  enrolled alternative programme. Mitigations (a)-(c) of A3 apply.

### B2. Dynamic code
Source: https://support.google.com/googleplay/android-developer/answer/9888379. "an app may not
download executable code (such as dex, JAR, .so files) from a source other than Google Play";
JavaScript in a WebView or interpreted code is outside that rule but "must not allow potential
violations of Google Play policies"; a WebView with a JavaScript interface loading untrusted web
content is a listed violation.
- **Constrains the architecture:** consistent with the architecture note: the app carries opaque package bytes and never loads them
  as code. If The client-host phase hosts game clients, **do not add a JavaScript interface** exposing app
  capabilities to game content.
- **Open:** does a downloaded file that is *not loaded* by the app but forwarded count as
  "download executable code"? The text speaks of an app downloading code; the clause is about the
  app's own execution. Counsel to confirm.

### B3. Android BLE permissions
Source: https://developer.android.com/develop/connectivity/bluetooth/bt-permissions. Android 12+:
runtime `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `BLUETOOTH_ADVERTISE` under "Nearby devices";
`neverForLocation` on SCAN avoids needing location (filters some beacons). Android 11 and below
require location; `CompanionDeviceManager` can scan without location on 8.0+.
- **Constrains the architecture:** appliance advertising must work with a service-UUID filter; target
  Android 12+ and use `CompanionDeviceManager` for the claim flow where possible. Background BLE
  limits on Android (foreground service rules, OEM battery killers) **[NOT VERIFIED: not fetched]**.

## C. Web platform limits

### C1. Web Bluetooth
Source: https://caniuse.com/web-bluetooth (accessed 2026-10-09). Supported in Chrome (Android and
desktop), Edge, Opera, Samsung Internet; **not supported in Safari macOS or iOS, nor Firefox** (the
page lists Mozilla's position as "Harmful"). A third-party bridge exists but is not WebKit.
- **Constrains the architecture:** a browser-only owner flow cannot use BLE on iPhone. Native app is required
  for iOS BLE; Android could in principle use Web Bluetooth over HTTPS only (secure context
  **[NOT VERIFIED on this page]**) but would then not work in Limited Mode (plain HTTP) or without
  Internet for the web origin.
- **Mitigation:** web Admin over Wi-Fi remains the no-app fallback for non-BLE operations, as today.

### C2. PWA limits on iOS
Source: https://webkit.org/blog/14112/webkit-features-for-safari-17-0/ (Safari 17.0; older). Web push
and badging apply to Home Screen web apps, push must be user-visible. **Storage eviction policy,
current iOS PWA/service-worker limits, and any change in the EU [NOT VERIFIED].**
- **Constrains the architecture:** a PWA cannot replace the owner app for BLE, key custody in secure hardware, or
  background courier. It remains fine for guests. ADR 0012 already treats the service-worker offline
  copy as a convenience.

## D. Cross-cutting notes
- **Hosting game clients in the app (AVR-45):** 4.7 (A2), 2.5.2 (A1), and the Android JS-interface
  rule (B2) all bite. Browser stays baseline; app hosting is optional later.
- **Reviewer testability:** App Review will need a way to exercise the app without an appliance
  (demo mode or a provided unit). **[NOT VERIFIED requirement for hardware companions; ask]**
- **Privacy labels (5.1.1):** the app should collect nothing about guests; owner key stays on device.
  Account-deletion rule applies if an account is ever introduced (guideline text read).
- **Age/content:** a storefront that sells third-party games adds content-rating and moderation
  duties on both stores **[NOT VERIFIED: not researched]**.

## E. Questions for counsel (consolidated)
1. Is a game package that executes on the owner's appliance a digital good requiring IAP/Play
   billing when bought in the app? Does 3.1.3(b), 3.1.4, or the Play device-companion concept apply?
2. Is carrying a third-party package to hardware "downloading code" (2.5.2, Play dynamic code)?
3. Can the app display and install games from an Avrana catalog without being a 3.2.2(i)
   "storefront"? Is a pre-clearance route available?
4. Current US/EU link-out and fee terms for Apple and Google, and their expected stability for
   a small publisher.
5. Is a no-IAP model viable: purchase on web (outside either store), app consumes a token only?
6. Liability and consumer-law duties when a store sells third-party code that runs on user hardware,
   plus refunds, takedown, and regional rules (also AVR-143's question list).
7. Export/crypto declarations for BLE-key and signature use in the app (not researched).

## F. What could not be verified
Apple guidelines revision date and the ADPLA current text; any Apple/Google hardware-companion
payments carve-out; the post-December-2025 US Apple commission; current US Google link-out fees;
Android background BLE limits; iOS Local Network details and force-quit behaviour; AccessorySetupKit
requirements; PWA eviction policy; the gap between Apple's EU terms and the Japan/other regimes;
store requirements for a demo mode. Several fetches returned incomplete page text (Apple's guidelines
page was truncated after 5.3.4; the Local Network page returned only a title).
