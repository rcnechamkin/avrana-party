# Adding a game (today's three routes)

There is no store and no installer yet. Pick the route that matches the game; each has its own
canonical guide, and this page only routes you there and lists the Avrana-specific extras.

## 1. A native browser game (the normal route) — a LAN Games module in the games fork

The **canonical guide is `ADDING_A_GAME.md` at the root of the games fork** (Avrana Party Games; see
`docs/SYSTEM.md` for where it lives — edit in a laptop clone of `~/avrana-party-games.git`, never in
the live `/home/cody/LAN-Games`). In short: copy the closest sibling under `games/`, subclass
`GameSession` (`games/<slug>/game.py`), write the client in `games/<slug>/web/` with the shared kit
(`/shared/hubnet.js`, `shared.css`), add **one** entry to `games/registry.py`, and add
`tests/test_<slug>.py` + `tests/playtest_<slug>.mjs`. BLUFF (`games/bluff/`) is the reference for a
hidden-information game (server-side masking, differential tests).

Avrana extras on top of that guide:

- **Accessibility** — the MUST list in `docs/design/ACCESSIBILITY.md` (real controls, names, 44 px
  targets, no colour-only cues, announced prompts, focus kept across state pushes).
- **Manifest** — nothing to write: LAN titles are *derived* from the registry entry
  (`experiments/manifests/`, branch `experiment/party-service`). If the registry can't express
  something (a private per-player screen, accessibility facts), add the id to `lan-overlay.json`.
- **Identity** — don't invent profiles, chat or teams inside the game: they are platform features
  (`docs/design/PARTY-PLATFORM.md`). Key anything you store by the player id the game is given,
  never by name.
- **Test on the dev server** (`LANGAMES_PORT=8196`, in the Pi dev clone or a worktree) — never on the
  live service.

## 2. An emulated PS1 title — a title profile (branch `experiment/ps1-title-profiles`)

Add `ps1/titles/<id>.json` (keys and rules: `ps1/profiles.py`; examples: `worms.json`,
`bomberman.json`), then `python ps1/profiles.py list` and the tests in `ps1/tests/`. Add the matching
capability manifest `experiments/manifests/builtin/ps1-<id>.json` — `cross_check_ps1` fails if the
two disagree (slots, id). The disc image is the owner's own copy under `/srv` on the Pi and is
**never** copied or committed. Running it is power-gated (ROADMAP N4): owner go-ahead first.

## 3. An external runtime (like the arcade)

Its own service behind an nginx location (a live nginx change: owner approval, byte-identical
files — `CLAUDE.md`), plus a builtin manifest with `runtime.type: external` and the path it is
served at. Follow `arcade/` as the example.

## Later (design only)

Third-party games installed from a folder with an `avrana.json` manifest, sandboxed and granted a
path by the appliance — `docs/design/GAME-INSTALLATION.md`. Not built.
