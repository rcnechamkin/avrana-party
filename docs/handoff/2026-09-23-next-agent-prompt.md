# Handoff prompt: next agent (written 2026-09-23)

> **Partly superseded (2026-09-24).** Read `docs/design/PARTY-PLATFORM.md` and ROADMAP N5 first.
> - **Games repo publishing:** the owner plans `rcnechamkin/avrana-party-games` as a *private*
>   repo; the **laptop** pushes `main` from its verified backup (`~/avrana-party-games.git`).
>   `party` does **not** need push access (it should become pull-only).
> - **Workflow:** edit on the laptop, not in a clone on `party`; the Pi is a deploy/test target.
> - **Chat and launcher/portal integration** are now party-platform features (N5), not BLUFF work.
>   BLUFF should not grow its own chat, profiles or teams. "Seat squatting with made-up tokens" is
>   addressed by the platform's server-issued device token and seat tickets (N5 F3/F5).

Paste everything below the line into a new Claude Code session.

---

You are continuing development of **BLUFF** (working title), the first native game for
**Avrana Party**. Avrana Party is a portable local-multiplayer appliance: a Raspberry Pi 4
(`party`) runs its own Wi-Fi, and **every player's phone is their complete seat at the
table**. It is not a controller, and no TV is required.

BLUFF is an original social bluffing card game. It uses **Coup-style mechanics as a TEMPORARY
baseline** to prove the interaction model, with **original placeholder roles**:
- Banker: Tax +3; blocks Foreign Aid
- Agent: Strike, pay 3, target loses a card; blocked by Guardian
- Smuggler: Steal 2; blocks stealing
- Broker: Exchange; blocks stealing
- Guardian: blocks a Strike

The mechanics and identity will be **redesigned after real-phone playtests**. Never copy
Coup's (or any commercial game's) art, names or text.

**It is NOT classic Diplomacy.** That direction was a misunderstanding and is abandoned. Never
work on countries, provinces, armies, phases or `diplomacy/diplomacy`.

## Read first

1. `docs/ROADMAP.md` in the private repo `rcnechamkin/avrana-party` (checked out on `party` at
   `/home/cody/avrana-party`). **Repository docs are the source of truth. BookStack's API/MCP
   is unreliable: do NOT try to repair it** unless the owner asks.
2. `docs/findings/2026-09-23-bluff-multi-agent-pass.md`: what was built and verified.
3. `games/bluff/README.md` in the game repo: architecture, privacy guarantees, lifecycle,
   test commands, limitations.
4. `CLAUDE.md` and `CLAUDE-HANDOFF.md` in `avrana-party` (the arcade/infra context).

## Where things are

- **Hosts.** `party` is the Pi (Debian 13, Python 3.13), reachable as `ssh party` from the
  home server `avrana`, with key auth. The Pi's home-LAN address is `10.0.0.143`; the party
  Wi-Fi (AP) address is `10.42.0.1`. `avrana` is a separate home server (media, BookStack,
  Beszel). If you run on `avrana`, its Claude Code Bash sandbox is broken (bwrap): pass
  `dangerouslyDisableSandbox: true`, and don't treat that as licence to broaden changes.
- **Game code:** `/home/cody/avrana-lab/avrana-party-games/` on `party`. This is a local fork
  of LAN Games (BEACNpool, MIT, upstream retired Sept 2026). Branch `main` is at `2cf4831`.
  - `games/bluff/game.py`: all rules and the lifecycle; server-authoritative.
  - `games/bluff/web/{index.html,client.js,table.css}`: the phone client, a CSS card table.
  - `games/registry.py`: one entry (slug `bluff`).
  - `server.py`: a `LANGAMES_PORT` override.
  - The rest of the framework (`core/session.py`, `core/net.py`, `web/hubnet.js`) is
    **unchanged upstream**. Keep it that way unless a change is essential and approved.
  - Branches:
    - `abandoned/classic-diplomacy`: preserved. **Never push, merge or integrate it**; it
      depends on AGPL code.
    - `agent/*`: already merged review branches, with worktrees under `~/avrana-lab/wt/`.
      Removable if the owner agrees.
- **Dev instance** (owner's test server): port **8196**, pid in `dev.pid`. Phones on the
  party Wi-Fi open `http://10.42.0.1:8196/games/bluff/`. The **live** LAN Games service
  (`avranaparty-games`, port 8096, `/home/cody/LAN-Games`) is production: **never touch
  it**.
- **Not published yet.** The public repo `rcnechamkin/avrana-party-games` doesn't exist.
  - The owner must create it: **empty** and public, **not a GitHub fork** (upstream has moved
    past our base `5da1764`).
  - `party` then needs push access; the current deploy key only covers `avrana-party`.
  - Creating a new SSH credential was blocked by the agent safety policy last session, so ask
    the owner rather than working around it.
  - Push **`main` only**.

## Architecture rules that must hold

- **The server is authoritative.** Every client message is parsed safely, tied to the
  sender's token and seat, validated against current state, rejected safely (an `invalid`
  fx, **never an exception**), and applied only by the server.
- **Private state is filtered on the server**, in `game_state(viewer)`.
  - Seats expose only coins, a hidden-card count, revealed cards and presence.
  - A player's own hand and exchange draw appear only in their `me` block.
  - Spectators get public data only.
  - Tokens, deck order and saved-state blobs are never sent.
  - The log holds public events only.
  - Keep the **differential masking tests** (another viewer's payload is byte-identical
    whatever the victim holds) and the frame-shape whitelists (`tests/ws_check_bluff.py`,
    `tests/sim_bluff.py`) up to date whenever the payload changes.
- **Every prompt has a `step`.** Clients echo it, and stale answers are rejected. Lobby verbs
  don't carry it.
- **Lifecycle** (see the README table):
  - reconnecting → away after 30 s for prompts, 60 s for your own turn → a passive autopilot
    that never claims, challenges or blocks;
  - an empty table pauses, can be taken over by a newcomer after 60 s, and is abandoned after
    5 min;
  - Leave game / End game;
  - the results screen always runs its 20 s.
  - Test bots Coup at 7+; idle humans and autopilot Coup only at 10+.
- Don't build a universal Avrana game SDK yet. Wait for several real games.

## Testing (run on `party` from the game repo; venv at `.venv/bin/python`)

```sh
.venv/bin/python -m pytest -q tests/test_bluff*.py   # 391 BLUFF tests (rules/fuzz, security, lifecycle)
.venv/bin/python -m pytest -q                        # full suite: 1,197 incl. upstream
# live protocol checks against a FRESH server on a spare port (one room per server; restart between runs)
LANGAMES_PORT=8198 setsid -f .venv/bin/python server.py > /tmp/srv.log 2>&1 < /dev/null
.venv/bin/python tests/ws_check_bluff.py ws://127.0.0.1:8198         # privacy/shape
.venv/bin/python tests/ws_attack_bluff.py ws://127.0.0.1:8198        # hostile client (24 checks)
.venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 main               # 13 checks
.venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 countdown_abandon  # 3 checks
# simulator (rules oracle + invariants on every frame), seeded server
LANGAMES_PORT=8200 setsid -f .venv/bin/python tests/sim_bluff.py --serve --server-seed 19 > /dev/null 2>&1 < /dev/null
.venv/bin/python tests/sim_bluff.py --url ws://127.0.0.1:8200 --seed 19 --players 6 --games 2 --adversarial
```

- Stop servers **by exact PID** (`ss -ltnp | grep :PORT`, and check `/proc/PID/cwd`). Never
  use `pkill`.
- Helper scripts from last session live in `~/avrana-lab/` on `party`:
  - `srv.sh start|stop PORT`
  - `simrun.sh SEED args…`
- **Screenshots:** headless Playwright/Chromium was installed only in a scratch venv on
  `avrana`; it may be gone. Chromium has no emoji font (empty boxes are not a bug), and
  **Chromium is not iOS Safari.**

## Gotchas that cost time last session

- **Quoting over SSH.** Nested single-quoted `ssh party '…'` commands break on apostrophes:
  the local shell rejects the line and *nothing runs*. For anything non-trivial, write the
  script or commit message to a file, `scp` it over, and run or `git commit -F` it.
- `sed -i` fails in root-owned directories (temp-file permission). Use Python or the Edit tool.
- **One room per server.** A game in progress blocks the room: restart a dev server for a
  fresh lobby, and check that nobody is connected before restarting 8196.
- **Running six subagents at once exhausted the usage window.** Run at most about three in
  parallel, each in its own worktree and branch, with its own port.
- The Pi shows a sticky under-voltage flag (`0x50000`), and the arcade emulator keeps load
  around 2.7. Don't trust fine timing measurements; don't load-test alongside the arcade.
- **Never modify** nginx, dnsmasq/hostapd, the captive portal, networking, systemd units, the
  live LAN Games service, RetroArch/arcade, or telemetry without an explicit, approved
  proposal that states the blast radius.

## Workflow

- **`avrana-party` (private):** edit in a separate clone (e.g. `~/avrana-lab/avrana-party-docs`
  on `party`) or on the owner's laptop, commit, push to `origin/main`, then
  `git pull --ff-only` in `/home/cody/avrana-party`. Don't edit that checkout directly.
- **Game repo:** commit locally on `main` in `~/avrana-lab/avrana-party-games`; push only once
  the public repo exists and the owner approves.
- End commit messages with the attribution lines your harness specifies.

## The single next milestone

**A real 3–4 iPhone playtest on the Pi, then fix what it finds.** Prepare everything first
(fresh 8196 lobby, test bots available), then give the owner a short, concrete checklist:
- full game to a winner
- each phone shows only its own cards
- claim → Challenge; block a Steal; challenge a block
- lock a phone for ~20 s during someone else's claim
- switch apps for ~45 s on your own turn
- Safari toolbar collapse and expand; notch and home-indicator spacing; emoji
- Leave game and End game
- everyone closes, then one person reopens within a minute

Treat their feedback as the priority. Known UX follow-ups:
- confirm after tapping a target (a mis-tap can spend a Coup)
- grey out unaffordable claims
- clearer two-step prompts for targets (claim, then block)
- timer tuning; event feed readability

Later, not now: LAN Games-style **chat**, original art and identity, the rules redesign, an
optional TV spectator view, launcher/portal integration, and the core-level P2s (oversized
frames, full-state push amplification, seat squatting with made-up tokens).

## Separate project on `avrana` (don't mix it with BLUFF)

The home server `avrana` is recovering from an accidental deletion of `/home/cody`
(2026-09-20).
- Ledger and handoff: `/mnt/avrana_media/recovery-20260920/` (`RECOVERY-LEDGER.md`,
  `HANDOFF.md`).
- That work is paused mid-maintenance: `authentik-worker` was recreated (M5), and the owner
  has not yet approved recreating `authentik-server` (M6) or the other stale-bind containers.
- `~/.ssh` on `avrana` was rebuilt last session (key `id_ed25519`; `ssh party` works).
- Only touch that project if the owner asks.
