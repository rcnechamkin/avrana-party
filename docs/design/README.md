# Design documents

Read in this order:

1. **`PARTY-PLATFORM.md`** — the hub: what Avrana Party is, the principles, locked decisions, the
   identity concepts (Device / Profile / Presence / Seat / Role / Persona), Admin vs Host, the social
   layer, security summary and open questions.
2. `../adr/0002-party-platform.md` and `../adr/0003-ids-and-keys.md` — the decisions, including
   which identifier or credential may authorize what.
3. Then whichever focused document matches the work:
   - `PARTY-LIFECYCLE.md` — state machines and awkward-state rules (party, presence, host, seats)
   - `GAME-INTEGRATION.md` — capability manifest v0, runtime vs grant, the party contract, and what
     today's code duplicates
   - `NATIVE-GAMES.md` — the phone as a private surface, hook strategy, reusable primitives
   - `PERSONAL-VIEWPORTS.md` — per-phone crops of one shared split-screen stream
   - `ONBOARDING.md` — tap/scan to join, the party address, party LAN vs upstream internet
   - `GAME-INSTALLATION.md` — open installation without a store; trust tiers

Nothing described here is built unless a document says so. Sequencing lives in `../ROADMAP.md`
(item N5). Offline executable checks of the lifecycle rules and viewport geometry live in
`experiments/` on branch `experiment/party-sim`.
