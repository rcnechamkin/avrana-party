# Design documents

The broad direction drafts in the parent `docs/` directory cover platform architecture,
offline trust, Personal Viewports/emulation and experience quality. Reference/substrate
research is indexed in [research/](../research/README.md). They are proposals or research notes.
ADRs and canonical design docs own
architecture/product contracts; `../SYSTEM.md` owns verified deployed state. Linear owns live
sequencing, blockers, acceptance and ownership; `../ROADMAP.md` owns strategic direction.

Read in this order:

1. **`PARTY-PLATFORM.md`** — the hub: what Avrana Party is, the principles, locked decisions, the
   identity concepts (Device / Profile / Presence / Seat / Role / Persona), Admin vs Host, the social
   layer, security summary and open questions.
2. `../adr/0002-party-platform.md` and `../adr/0003-ids-and-keys.md` — the decisions, including
   which identifier or credential may authorize what. Read ADRs 0006–0011 for implemented
   session authority, navigation, arcade lifecycle, Play/Watch and the console model. Then read
   the 2026-10-02 forward architecture, accepted but not implemented:
   [ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md) (the Party stays usable in
   Limited Mode without trusted HTTPS), [ADR 0013](../adr/0013-party-and-game-browser-origins.md)
   (trusted Party origin vs game origin) and
   [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) (native games as isolated
   platform consumers; LAN Games retired to donor/reference). ADRs 0002, 0003, 0004, 0005, 0006
   and 0011 carry dated 2026-10-02 amendments pointing at them.
   [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md) (2026-10-03, accepted)
   is the service-identity, secret-ownership and local-IPC mechanism for ADR 0014: what each
   service may read, where a native game's socket, key and state live, and what the first
   field-test appliance does and does not promise.
3. Then whichever focused document matches the work:
   - `FULL-MODE.md` — the deployed HTTPS shell (capability probe, offline copy, keep-awake) and
     the accepted Full Mode / Limited Mode target contract, kept explicitly separate
   - `LIMITED-MODE.md` — the **accepted** mechanisms for ADR 0012 (doorway, canonical HTTP origin,
     separate credential, new device on a mode switch); steps 1–2 in source, not deployed (AVR-225)
   - `BROWSER-ORIGINS.md` — the **accepted** mechanisms for ADR 0013 (game host name, the Party
     bridge frame and its closed verb set, the `__Host-` cookie) and the decisions required
     (AVR-226)
   - `LAN-GAMES-ASSIMILATION.md` — **historical**: the completed MVP assimilation, donor inventory,
     profile/chat compatibility and provider catalogs; superseded going forward by ADR 0014
   - `LAN-GAMES-PROVIDER.md` — **historical / currently deployed** provider boundary, being
     superseded by ADR 0014; its operational facts hold until the runtime is removed
   - `PARTY-LIFECYCLE.md` — state machines and awkward-state rules (party, presence, host, seats)
   - `GAME-INTEGRATION.md` — the target architecture diagram (Party origin, game origin, registry,
     independent game processes, results back to Party), the current state, capability manifest
     v0, runtime vs grant, the party contract, and what today's code duplicates
   - `NATIVE-GAMES.md` — the phone as a private surface, hook strategy, reusable primitives;
     §3.1 classifies the LAN Games fork's code as donor, extraction candidate or legacy (AVR-228)
   - `PERSONAL-VIEWPORTS.md` — per-phone crops of one shared split-screen stream
   - `ONBOARDING.md` — tap/scan to join, the party address, party LAN vs upstream internet
   - `GAME-INSTALLATION.md` — open installation without a store; trust tiers; canonical manifest
     and per-game process direction; signing kept separate from isolation
   - `ACCESSIBILITY.md` — what every page and game must do; the manifest's accessibility block;
     the hub/BLUFF audit
   - `GAME-UX-CONTRACT.md` — the shared game UX and interaction contract (AVR-56): what the
     platform owns and what a game owns on a phone, the briefing, rules access, unavailable-action
     explanations, interaction floors, system cues and art slots; each rule labelled implemented,
     accepted or proposed; not validated on phones
   - `AVRANA-UX-UI-PRODUCT-BRIEF.md` — the **owner-approved** UX/UI direction (2026-10-05): product
     character, visual language, navigation, Party, Library, Host, degraded states, Arcade and EXPO
     presentation, the design-first process and what is deliberately undecided; direction for the
     redesign, not implemented
   - `PARTY-GAMES-CONTRACT.md` — the versioned Party ↔ Games boundary, its two declarations
     and the checker both CIs run
   - `DEPLOYMENT-MANIFEST.md` — what the Pi records about each deployment (`avrana.deployment/v0`)
   - `STATUS-ENDPOINT.md` — `GET /party/api/status`: the running build and its health
     (`avrana.status/v0`)
   - `COMMUNICATION.md` — chat as a platform capability: transport, policy, presentation and
     game-native actions kept separate; default Party chat (HUD + feed); game overrides (PROPOSED)

Implemented versus target: ADRs 0012–0014 describe accepted direction only. Limited Mode
(rollout steps 1 and 2) is in source and not deployed. Only Party Core's Limited listener and
credential are behind unset configuration; the shell changes and `mode` in every view ship with
the next ordinary deploy and are inert in Full Mode (ADR 0012 amendment says exactly what
changes). No
separate game origin, per-game process, per-service identity, game registry, result envelope, Profile store or Checkers
exists yet, and the LAN Games fork is still the deployed game runtime. Design documents mark such
passages "Target" or "accepted direction"; `../SYSTEM.md` is the only authority on what runs.

Party Core, Party Home, Game Contracts/providers and Games integration are implemented on main.
ADR 0011 is merged (Party #34 / Games #13); production/phone proof remains AVR-212. SYSTEM keeps
source separate from deployed revisions. Broader design sections retain explicit future/draft
labels. The party model and viewport PoC (`experiment/party-sim`), earlier Party service and
PS1 title profiles remain research evidence, not production contracts. Offline model checks live in
`experiments/` on branch `experiment/party-sim`.
