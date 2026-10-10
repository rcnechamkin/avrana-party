# Hello Party reference game: historical design note

- **Status:** Proposal (historical design note). Superseded as the working record by AVR-38. Not a description of anything built.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-38 (owner: do not claim the SDK or package shipped; do not bypass the Checkers/BLUFF evidence gates); Checkers findings; `docs/design/NATIVE-GAMES.md`; ADR 0016.
- **Related:** `docs/research/MISSING-PUBLIC-ABSTRACTIONS.md`, `docs/research/DEVELOPER-FRICTION-AUDIT.md`

On 2026-10-09 a design was sketched for "Hello Party", a deliberately boring reference game for AVR-38: each seated
player holds a private number card (private view), anyone can press "Say hello" (input) to append to a shared list
(broadcast), the game ends when everyone has said hello once or the Host ends it. It was meant to be the smallest honest
vertical slice exercising join, private view, broadcast, input, start, end, shutdown and reconnect through the same public
boundary a first-party game uses, in a new directory of the Games repository mirroring `checkers/`, never in Party Core.

That design is **not maintained here**. Implementation of Hello Party is being carried out under **AVR-38**, and the
authoritative scope, files, tests and results belong to that issue and its pull requests. Nothing in this note should be
read as describing what was built. Principles that remain useful as constraints on whatever AVR-38 produces:

- Ship only the plumbing a game needs today, in one clearly marked boundary file, so later SDK work can replace that file.
- Do not freeze names, module paths, launch environment conventions, a manifest shape, transport (long poll versus WebSocket), idle durations or resource ceilings (ADR 0016 says the launch handoff "may change").
- Do not make the game page the top-level browser document (avoid an unexplained `frame-ancestors 'none'`).
- Do not add a second Party simulator in Games; reuse the provider harness on Linux and a clearly flagged development transport elsewhere.
- Do not claim "SDK v0"; describe it as a reference game that will become the SDK's first consumer.
