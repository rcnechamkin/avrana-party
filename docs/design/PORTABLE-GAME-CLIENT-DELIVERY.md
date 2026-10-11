# Portable game-client delivery

- **Status:** **PROPOSED direction (2026-10-10, AVR-335). Mostly not built. Nothing here is deployed, frozen or accepted by an ADR.** It records owner direction from Linear (AVR-37, AVR-38) next to what the source does today, and lists what is unresolved. It decides nothing and supersedes nothing.
- **Reads with:** [AVRGAME-PACKAGE](AVRGAME-PACKAGE.md) (experimental format, unchanged), [GAME-PLATFORM-ARCHITECTURE](../GAME-PLATFORM-ARCHITECTURE.md), ADRs [0012](../adr/0012-limited-mode-party-survives-https-loss.md), [0013](../adr/0013-party-and-game-browser-origins.md), [0014](../adr/0014-native-games-isolated-lan-games-retired.md) and [0016](../adr/0016-service-identities-and-local-trust-boundary.md), [OWNER-APP-ARCHITECTURE](../research/OWNER-APP-ARCHITECTURE.md) and [MOBILE-STORE-POLICY-RESEARCH](../research/MOBILE-STORE-POLICY-RESEARCH.md) (research, no authority).
- **Not covered:** the `.avrgame` field list, signing, entitlements and the owner app's management functions. Linear owns sequencing.

## Status labels

Each section says which of these it is: **Implemented** (code on `main`, with the path), **Accepted** (an ADR), **Proposed direction** (owner direction in a Linear issue, not a guarantee), **Unresolved** (who decides is named). Implemented does not mean deployed; [SYSTEM](../SYSTEM.md) and `/party/api/status` say what runs.

## 1. The model in one paragraph

**Proposed direction (AVR-37, AVR-38).** A game keeps its authoritative runtime on the appliance. Its phone client is a portable bundle of HTML, JavaScript, assets and, optionally, WebAssembly that any normal phone browser can run. Browser play stays mandatory and needs no app, TV or Internet. A trusted native app may, when eligible, show the same bundle in a viewport over local Wi-Fi, but the app is a second way to display the client, never a second package authority. The complete package stays installed on the appliance. `.avrgame` stays storefront-neutral and host-neutral, and no package may require app-distribution eligibility or a paid entitlement silently.

## 2. What exists today

**Implemented.**

- `avrana/avrgame/` validates `avrana.avrgame/experimental.1`; `client.root` names a directory holding `index.html`. It is informational: the game's own server serves the client ([AVRGAME-PACKAGE](AVRGAME-PACKAGE.md)).
- `ops/install-game` (`avrana/ops/install_game.py`) stages the whole package on the appliance and writes an install record with a sha256 per file. Phones get the client from the appliance over its local HTTP(S) in an ordinary browser.
- Nothing about an app host, a WASM client, a client caching contract or installed-package discovery by phones is implemented. The phone catalog is static; whether the appliance serves one that lists installed packages is an owner decision recorded in AVRGAME-PACKAGE. In-progress issues, not facts: an appliance-local catalog overlay (AVR-337), trust hardening (AVR-336) and real-browser verification (AVR-338).

**Unresolved (owner).** Whether the experimental package may change at all: `.avrgame` is not frozen, not even as experimental, until the AVR-27 four-human BLUFF evidence is reviewed against the draft and the owner accepts. This document adds no field and no schema.

## 3. Authority stays on the appliance

**Accepted** (ADR 0013, 0014, 0016) and **Implemented** where [SYSTEM](../SYSTEM.md) says so: the game server is authoritative; the Party owns identity, tickets, presence, results and history; a client holds only a session ticket. **Proposed direction:** this does not change for a portable client. A cached or embedded client is untrusted input to the appliance exactly like a browser tab: it can request, never grant, and holding client bytes proves nothing. Package and source bytes on the appliance are canonical; a phone cache is disposable acceleration, never ownership or entitlement.

## 4. Delivery of an unknown game: cold and warm

**Proposed direction; AVR-135 owns the semantics and none are built.** The constraints the direction implies:

- **Cold:** a phone that has never seen the game fetches the client from the appliance. The cost is paid in a room with one Wi-Fi access point and several phones, so size, ordering and a loading profile matter. A seat-ready signal and progressive content packs are listed as deferred in AVRGAME-PACKAGE.
- **Warm:** a phone with a cached copy may start without refetching, but only after confirming it is the version the appliance currently serves. The appliance is the only authority for "current".
- **Version and integrity:** the cache key must include the package version and content hashes so a stale or altered copy is detected; where the hashes come from, and whether they share the install record's per-file sha256, is part of the AVR-135 design. Games ship server code the phone never receives, so only the client root is ever delivered.
- **Cache boundary:** a cache may only hold the client bundle. It may not hold tickets, keys or results. Whether the browser's HTTP cache, a service worker or an app-side store holds it is **Unresolved (AVR-135)**.
- **Proof:** a real-phone cached relaunch is AVR-139, not done. No cold or warm timing exists.

## 5. Isolation and guest authority of a client inside an app host

**Proposed direction (AVR-45, AVR-334, not done); Unresolved in detail.** An app viewport must give the game page no more authority than a browser tab: no native APIs added, no bridge from game content to app capabilities, the Party layer owned by the Avrana shell and the game confined to its viewport. Do not freeze WebView- or WKWebView-specific APIs into SDK v0. AVR-334 is a prototype of downloaded clients inside Android and iOS hosts; nothing here depends on its result. The open conflict with accepted origin rules is in section 11.

## 6. Android handhelds

**Proposed direction.** AVR-330 (probing), AVR-331 (input) and AVR-332 (navigation) cover Android handheld hardware as clients. None is done. Handhelds are expected to join through a browser first; whether any needs the app host is an output of those issues, not an assumption.

## 7. No native mobile executable delivery

**Proposed direction (AVR-37).** `.avrgame` must not deliver an app binary, a native mobile module or any phone-side native code. Portable JavaScript and browser-hosted WASM are permitted client technologies, not mandatory, and not compatible with native Unity or Unreal binaries (AVR-38). AVRGAME-PACKAGE already enforces the narrow form: `client.root` must be a directory with `index.html`, and nothing else is allowed. The older sentence in GAME-PLATFORM-ARCHITECTURE that the mobile app may run game or emulator workloads on the phone is in tension with this; see section 11.

## 8. Mixed-device performance

**Documented principle (GAME-PLATFORM-ARCHITECTURE, not an ADR); application Proposed.** The weakest client does not downgrade the party; a seat chooses the first presentation it can run, and an `unknown` capability is not treated as `no` (GAME-PLATFORM-ARCHITECTURE invariants; capability handling in the Game Contract). A WASM or heavy JavaScript client raises the load on cheap phones, and the appliance must keep the authoritative simulation independent of client frame rate. No cross-device measurement of any such client exists; it is a prerequisite for claiming a minimum phone.

## 9. Porting rights for studios

**Proposed direction (AVR-38).** Adapt an existing game only with clear rights to its code, assets and tools. A C or C++ title can be compiled to WASM (an Emscripten reference experiment is AVR-333, not done), but that is a port, not a drop-in of the studio's native build. Store-host eligibility is a policy layer on top of one SDK, not a fork of it. The platform asks a studio for a rights statement; it does not review or grant rights, and this document gives none.

## 10. App-store gates: unresolved

**Unresolved. Decided by the owner with qualified counsel and, where possible, a pre-submission conversation with each store; not by this document or by any agent.** Two things are kept apart:

- **Host capability proposal** (AVR-45, AVR-135): the app might display a downloaded client. Described in OWNER-APP-ARCHITECTURE section 8.
- **Policy validation:** whether each store would accept that. Evidence is MOBILE-STORE-POLICY-RESEARCH.

Primary sources read on **2026-10-10** (paraphrased; neither page showed a revision date; the Apple fetch read the first 100,000 of about 112,000 characters, which included the sections below):

| Source | What the text says, paraphrased | What must be validated |
|---|---|---|
| Apple App Review Guidelines 2.5.2, https://developer.apple.com/app-store/review/guidelines/ | Apps are to be self-contained and may not download, install or execute code that "introduces or changes features or functionality of the app"; a narrow exception exists for educational coding apps | Whether a downloaded web client counts as code that changes the app's functionality, or falls under 4.7 |
| Apple 4.7 to 4.7.5, same page | Apps may offer certain software not embedded in the binary, including HTML5 and JavaScript mini games, if the developer takes responsibility for it. 4.7.1: privacy, content filtering, reporting, blocking and Guideline 3.1 for digital goods. 4.7.2: no native platform APIs exposed to the software without Apple's permission. 4.7.3: no sharing of data or permissions without consent each time. 4.7.4: an index of the software with universal links. 4.7.5: age rating handling | Whether a game that runs on the owner's appliance, shown in a viewport, is "offered" under 4.7; whether the obligations above (filtering, reporting, index, age) apply and how a closed or private catalog meets them; payment treatment of paid titles |
| Google Play Device and Network Abuse policy, https://support.google.com/googleplay/android-developer/answer/9888379 | Apps may not download executable code such as dex, JAR or native libraries from outside Google Play, except code run in a virtual machine or interpreter that gives indirect access to Android APIs, such as JavaScript in a WebView. Interpreted code loaded at runtime must not allow potential violations of Play policy. A WebView with an added JavaScript interface that loads untrusted content is listed as a violation | Whether WebAssembly counts within the interpreter or VM carve-out (not stated on the page); how the policy treats a client bundle loaded from a local-network host; confirmation that no JavaScript interface is added |

Consequences kept deliberately small: no legality conclusion is drawn here; the research doc's earlier claims that an app must never run client code are superseded by the separation above, not by a ruling; and no manual-import or sideload path is relied on to satisfy either store. Payment rules for paid titles and the storefront question are AVR-143 and AVR-316 and stay in the research documents.

## 11. Conflicts recorded, not resolved

Each needs a reviewed decision. Until then the accepted text governs.

| # | Conflict | Where it is recorded | Decides |
|---|---|---|---|
| 1 | GAME-PLATFORM-ARCHITECTURE lists "Native-app execution" on the phone as an execution style; owner direction (AVR-37) rules out native mobile executable delivery | Pointer note in GAME-PLATFORM-ARCHITECTURE, section "Core Product Model" | Owner; likely an ADR or an amendment |
| 2 | Research said the app never runs or interprets game material, while AVR-45 and AVR-135 propose hosting web clients | Dated notes in OWNER-APP-ARCHITECTURE and MOBILE-STORE-POLICY-RESEARCH; reconciled as two separate questions in section 10, not settled | Owner with counsel |
| 3 | ADR 0013 separates the Party origin from a separate game origin (hostname chosen by AVR-226) to isolate game code; an app viewport loads a client in a context whose origin, cookies and storage differ, and Limited Mode serves plain HTTP (ADR 0012) | Here | Owner; may need an ADR 0013 amendment |
| 4 | ADR 0014 has each game's own process serve its client through the generic route; a client cache contract (AVR-135) needs version and integrity data about the client root that `client.root` currently leaves informational | Here; AVRGAME-PACKAGE unchanged | Owner at AVR-135 |
| 5 | ADR 0002 excludes a store and says the app is not required; AVR-143 approves an optional storefront | Already recorded in OWNER-APP-ARCHITECTURE ("Where this proposal needs new ADRs") | Owner |

ADRs 0012, 0013, 0014 and 0016 are unchanged by this document.

## 12. Guarantee preserved

Friend-ready V1.0: guests play in a browser with no app, no TV and no Internet. No section above weakens it, and any host capability that is later built must leave browser participation complete.
