# Adding a game (today's routes, and where new native games are going)

There is no store and no installer yet. Pick the route that matches the game; each has its own
canonical guide, and this page only routes you there and lists the Avrana-specific extras.

## 0. A new native Avrana game (what exists today, 2026-10-09)

**A LAN Games module is no longer the normal route for a new native Avrana game.**
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) retires LAN Games as an Avrana
runtime: new native games are independent platform consumers (their own process, service
identity, secrets and state; generic routing from a game registry; one canonical manifest;
results reported to Party).

**EXPERIMENTAL, not an SDK, not frozen.** There is no SDK. An experimental `.avrgame` package format and a minimal installer exist
([AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md), [install-game](install-game.md); not run on the appliance); the pieces below are real but their names and shapes may change. Freeze gates remain:
Checkers integrated on the shared kit, review of the four-human BLUFF evidence (AVR-27) and Spades
boundary validation (ADR 0014). Nothing here is deployed by this page.

What a native game is today: a separate process (`avrana-game@<slug>`, systemd socket activation,
an inherited `AF_UNIX` listener on fd 3, its key as a credential, `$AVRANA_PARTY_ORIGIN`, a
separate game origin) that speaks the signed session protocol (launch, ticket redemption, `end`,
signed `ended` with an `avrana.game-result/v1`) and whose page reaches Party only through the
Party-owned bridge shim. Checkers (`checkers/` in the Games repository) is the first real one.
The Games repository also has an experimental kit, `avrana_gamekit/`, and a reference game,
`hello_party/` (AVR-38), whose READMEs are the developer-facing guide: how to write the game, run it
on Windows, macOS or Linux with no Pi (`python -m hello_party.conformance`), and test it against
the real Party service.

### Steps, and who can do them

| # | Step | An outside developer, alone? |
|---|---|---|
| 1 | Write the game process and page in the Games repository layout (a top-level package, stdlib only, the kit is optional), built on `core/party_protocol.py` and `core/party_result.py` as vendored there | Yes |
| 2 | Run it locally with `--dev-tcp` and a stand-in Party (`avrana_gamekit.devparty`), and run its tests | Yes |
| 3 | Prove it against the **real** Party code: the Games cross-repository test starts the real Party service in-process, with a game entry given by hand | Yes, with a Party checkout; to be able to launch the game the real Party needs its Game Contract file in that checkout's `contracts/games/` (a local, uncommitted copy should be enough for the test; **not exercised outside CI**) |
| 4 | Write the Game Contract (`avrana.game/v0`) | Yes, but it must live in **this** repository: `contracts/games/<slug>.json`. Party Core reads game facts only from there (no external contracts directory), so a third party needs a Party PR. **This is the first concrete blocker.** |
| 5 | A grant in the appliance profile (`contracts/appliances/avrana-pi4.json`, `installed[]`) with `runtime.command` and `working_directory` | No: a Party PR, reviewed by a maintainer |
| 6 | The game's code under a root-owned release path on the appliance (`/opt/avrana-party-games/current` for Games-repository games) | No: a Games deploy by the owner |
| 7 | `sudo python3 -m avrana.ops.provision_game <slug>` (key, systemd instance, registry entry, Party Core reload) | No: root on the appliance, owner action ([provision-game](provision-game.md)) |
| 8 | A catalog entry and artwork | No: derived from the Game Contract by `python3 -m avrana.contracts.catalog`; maintainers merge it |

**With an experimental `.avrgame` package** (not deployed, experimental): the package carries the Game Contract and the code, so steps 4 (the contract in this repository), 5 (the grant PR) and 6 (staging the code on the appliance) are replaced by `install-game install FILE.avrgame --grant ...`, which writes an install record, stages the files root-owned and calls step 7's `provision-game` path. What remains: **root on the appliance** (an owner action), the owner prerequisites (phase 1, prepare-native-games, the `packages` key in `party-core.json`, an empty `/opt/avrana-games`) and **the catalog on the appliance**: the phone's Party Home lists only what the static `catalog.json` lists, so an installed package is offered by Party Core but has no tile until the owner decides how a catalog that includes packages is served. The package is untrusted code; see the trust statement in [install-game](install-game.md). **The reference id `hello` cannot be installed as a package on a tree that carries the test fixture `contracts/games/hello.json`:** the installer refuses to shadow a repository contract (the CI proof deletes that fixture from its copied tree on purpose). A developer installs their own renamed game. **Validation cannot prove a package starts.** It checks bytes, the manifest and that the `-m` module exists in the package; the only gate is running it: the Games walkthrough's packaged-conformance step, and the real-systemd proof.

Platforms: the Hello Party tooling was exercised locally on Windows and in CI on Linux; macOS is expected to
work but is untested. The Hello Party page has not been opened in a browser.

Test-only games (like the stand-in and Hello Party) are the exception to 4, 5 and 8 in spirit: their
contract carries `"net.avrana.test": {"test_only": true}`, so they are in no product catalog and no
product appliance grants them; the grant lives in a CI fixture (`tests/fixtures/appliances/ci-hello.json`,
`ci-standin.json`). That is how Hello Party exists in this repository without being installable on
the Pi.

Do not hand-edit around a step an outsider cannot do: record it on the issue as the blocker.
Take scope and sequencing from Linear (umbrella AVR-224), not from this page.

Rules that hold regardless: do not start a new native game as a LAN Games module unless the Linear
issue says so explicitly; the platform rules are in `docs/design/PARTY-PLATFORM.md`,
`docs/design/NATIVE-GAMES.md`, `docs/design/GAME-INTEGRATION.md` and ADR 0006.

## 1. Legacy / current state: a LAN Games module in the games fork

This is how BLUFF and the donor titles are built and deployed **today**, and it stays correct for
maintaining them until the retirement work lands. It is the legacy route, kept as current-state
and donor/reference documentation.

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
**never** copied or committed. Running it is power-gated (ROADMAP’s emulation research boundaries): owner go-ahead first.

## 3. An external runtime (like the arcade)

Its own service behind an nginx location (a live nginx change: owner approval, byte-identical
files — [AGENTS](../../AGENTS.md)), plus a builtin manifest with `runtime.type: external` and the path it is
served at. Follow `arcade/` as the example.

## Later (design only)

Third-party games installed from a package with a manifest, isolated and granted a path by the
appliance — `docs/design/GAME-INSTALLATION.md`. Not built; the package format, sandbox and
signing workflow are unfrozen (ADR 0014).
