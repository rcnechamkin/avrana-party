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
   session authority, navigation, arcade lifecycle, Play/Watch and the console model.
3. Then whichever focused document matches the work:
   - `LAN-GAMES-ASSIMILATION.md` — canonical ownership, donor inventory, profile/chat compatibility and provider catalogs
   - `PARTY-LIFECYCLE.md` — state machines and awkward-state rules (party, presence, host, seats)
   - `GAME-INTEGRATION.md` — capability manifest v0, runtime vs grant, the party contract, and what
     today's code duplicates
   - `NATIVE-GAMES.md` — the phone as a private surface, hook strategy, reusable primitives
   - `PERSONAL-VIEWPORTS.md` — per-phone crops of one shared split-screen stream
   - `ONBOARDING.md` — tap/scan to join, the party address, party LAN vs upstream internet
   - `GAME-INSTALLATION.md` — open installation without a store; trust tiers
   - `ACCESSIBILITY.md` — what every page and game must do; the manifest's accessibility block;
     the hub/BLUFF audit
   - `COMMUNICATION.md` — chat as a platform capability: transport, policy, presentation and
     game-native actions kept separate; default Party chat (HUD + feed); game overrides (PROPOSED)

Party Core, Party Home, Game Contracts/providers and Games integration are implemented on main.
ADR 0011 is merged (Party #34 / Games #13); production/phone proof remains AVR-212. SYSTEM keeps
source separate from deployed revisions. Broader design sections retain explicit future/draft
labels. The party model and viewport PoC (`experiment/party-sim`), earlier Party service and
PS1 title profiles remain research evidence, not production contracts. Offline model checks live in
`experiments/` on branch `experiment/party-sim`.
