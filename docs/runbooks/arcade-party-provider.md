# Runbook: make Gauntlet II a Party-launched game (AVR-134)

Status: **RUN 2026-09-29** (production `0e97c2e`, games `03df5ae`): the owner ran steps 1–3 as one script, 0 failures; verified server-side (`docs/findings/2026-09-29-avr128-134-deploy.md`). Phone checks remain open. This is the owner's deploy for ADR 0009.

- It follows AVR-128 (ADR 0008) and needs that on the Pi first:
  - avrana-party #30 merged and deployed;
  - avrana-party-games #11 merged and deployed;
  - a Party Home release built from them.
- Every step below that uses `sudo` is the owner's.

> **2026-10-03 (AVR-256):** the unit files and drop-ins in source now describe the host *after*
> [the service-users migration](service-users-migration.md): dedicated users, code under `/opt`,
> keys as systemd credentials. They are installed by `ops/migrate-service-users.sh`, not by hand.
> **Do not run the `install` lines below on a host that has not been migrated**: the unit would
> name a user that does not exist. On such a host the installed units stay as they are, and
> `ops/provision-party-game-key.sh` needs `AVRANA_PARTY_KEY_OWNER=cody`. The steps below remain
> the record of how the deployed state was reached.

## What changes on the Pi

| Piece | Where | Source |
|---|---|---|
| Arcade session key | `/etc/avrana-party/game-keys/arcade-gauntlet2.key` (0600 `cody`; the same dir as BLUFF's) | `ops/provision-party-game-key.sh arcade-gauntlet2` |
| Arcade drop-in (`AVRANA_PARTY_KEYS`, `AVRANA_PARTY_URL`) | `/etc/systemd/system/avranaparty-arcade.service.d/avrana-party-session.conf` | `deploy/arcade/avrana-party-session.conf` |
| Party Core config: the `arcade-gauntlet2` entry (`http://127.0.0.1:8098`, `timeout` 25) | `/etc/avrana-party/party-core.json` | `deploy/party-core/party-core.example.json` |

**What does not change:**
- The arcade unit, its user, groups and permissions.
- nginx: port 8098 is never proxied.
- Party Core's unit.

**New:** the arcade listens on `127.0.0.1:8098`, loopback only. (Loopback keeps phones out. It
does not tell the arcade which local service is calling, and the key is `0600` for a user every
service shares: see [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md).)

## Deploy, in order

The arcade must be ready to be launched before Party Core offers it.

```bash
cd /home/cody/avrana-party                    # already fast-forwarded to the reviewed revision
# 1. Key (never printed; refuses to overwrite)
sudo bash ops/provision-party-game-key.sh arcade-gauntlet2
# 2. Arcade: Party-managed (it comes back idle: nobody can play Gauntlet II until a host starts it)
sudo install -D -m 0644 deploy/arcade/avrana-party-session.conf \
     /etc/systemd/system/avranaparty-arcade.service.d/avrana-party-session.conf
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-arcade
# 3. Party Core: the arcade becomes a Party game
sudo install -m 0644 deploy/party-core/party-core.example.json /etc/avrana-party/party-core.json
sudo systemctl restart avrana-party-core      # a restart starts a new, empty Party (memory-only)
```

## Verify

Steps 1–3 need no sudo. Measure power with the usual rule: sample on the Pi and read once at the end.

1. **The arcade is idle.**
   - Check: `curl -s http://127.0.0.1:8097/stats | python3 -m json.tool`.
   - Expect `"state": "idle"`, `"party_managed": true` and `"emulator_running": false`.
   - Expect no `retroarch` process: `pgrep -a retroarch` prints nothing.
2. **Only loopback listens on 8098.** `ss -ltnp | grep 8098` shows `127.0.0.1:8098` only.
3. **Idle is cheap.** `top -bn1 | head -15` shows no RetroArch, and Python sits near idle. Record CPU and `vcgencmd measure_temp`.
4. **Party Home offers it.** Use the deployed release’s membership flow on two phones.
   The 2026-09-29 release used manual membership; ADR 0011 source gains/resumes presence
   automatically with a saved local profile, with no normal Join/Leave UI (deployment/phone
   proof: AVR-212). Gauntlet II launch is host-only in both versions.
5. **Start.**
   - The host starts Gauntlet II. Both phones move to `/arcade/`.
   - Tap Play: a picture, controls and sound.
   - `/stats` shows `"state": "running"`.
6. **Switch to BLUFF.**
   - The host goes to Party Home and picks "Switch everyone to this" on BLUFF.
   - Within a few seconds `pgrep retroarch` is empty and `/stats` is `idle`.
   - Both phones are in BLUFF.
7. **Switch back.** The host switches back to Gauntlet II: BLUFF ends, then the arcade starts.
8. **End.** The host's "End for everyone" returns both phones home, and the arcade goes back to idle.
9. **Logs.**
   - Check `journalctl -u avranaparty-arcade -u avrana-party-core --since "-15min"`.
   - Expect "party session started" and "party session ended; runtime stopped".
   - Expect no tokens or keys in either log.
10. **Record.** Put the results in `docs/findings/`, and the port and state in `docs/SYSTEM.md`.

## Rollback (each step is independent)

```bash
# Party Core: Gauntlet II is no longer a Party game (Party Home shows its plain Play tile again)
sudo cp /etc/avrana-party/party-core.json /root/party-core.json.$(date +%s)   # optional backup
#   remove the "arcade-gauntlet2" entry from /etc/avrana-party/party-core.json, then:
sudo systemctl restart avrana-party-core
# Arcade: always-on again, exactly as before AVR-134
sudo rm /etc/systemd/system/avranaparty-arcade.service.d/avrana-party-session.conf
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-arcade
# The key can stay: without the drop-in the arcade never reads it.
```

If only the arcade drop-in is removed, Party Core still lists Gauntlet II. Its launch then fails with "The game server did not answer". Nothing runs twice, but the tile is useless, so roll back both.

## Security notes

- **Key:** the key is per game, so the arcade cannot mint tickets for or end BLUFF's sessions. It is never printed or logged.
- **Control routes:**
  - reachable only on 127.0.0.1:8098, which nginx does not proxy;
  - refuse proxy headers;
  - accept only fresh, signed, single-use `launch`/`end` messages addressed to `arcade-gauntlet2`.
- **Controllers (AVR-130):** before each connection, the page checks `/arcade/stats` and, when
  Party-managed, POSTs `{game: 'arcade-gauntlet2'}` to the authenticated
  `/party/api/session/ticket` API. The ticket goes only in the first WebSocket body
  `{type: 'hello', ticket: …}`, with a five-second hello deadline. `GameSide.admit()` validates
  it; no Party device identity reaches the arcade. Tickets and derived tokens are never logged.
- **Slot ownership:** an in-memory, session-local reservation uses the stable secret game token
  returned by `admit()`. A player receives the first unowned slot; reconnect order does not
  compact or renumber it. Disconnect releases held input immediately but reserves the slot for
  60 seconds (the lifecycle design's provisional seat grace). At the deadline a new admission
  can reuse it. A reconnect during grace binds the same slot immediately. A duplicate tab takes
  over that slot and closes the previous socket; old input and old cleanup cannot affect it.
  The replaced tab stops automatic retries until its user taps Play, avoiding takeover loops.
- **Release:** the arcade controller Leave button (not Leave Party) sends `{type: 'leave'}` before closing, releasing ownership
  immediately when the server receives it. A lost Leave message follows ordinary disconnect
  grace. End, switch, a newer launch, runtime stop or process restart discard reservations.
  Previous-session tickets cannot claim seats in a new session.
- **Roles and fallback:** spectator tickets receive a clear non-player response and no stream or
  controller. Without Party-managed configuration, first-free connection allocation remains:
  disconnect immediately frees the slot, and no Party ticket is required.

## AVR-130 acceptance checks (remaining on real devices)

The automated reservation and fake-media tests do not establish phone acceptance. With four
controller seats (AVR-311, below) the check is run on four phones, or on two as a first step. In
one Party arcade session, connect A, then B (then C and D), lock/disconnect them all, and reconnect
them in another order within 60 seconds: each must keep the Player number it had (A Player 1, B
Player 2, C Player 3, D Player 4), whatever the order. Check duplicate tabs, held-input release,
Leave and immediate reuse, reuse after grace, spectator refusal, and end/switch/relaunch. Repeat
on the Party Wi-Fi with actual streaming. This change has not been deployed by these tests.

## Four controller seats (AVR-311, 2026-10-07)

Gauntlet II seats four phones. `players.max` and `input.slots` are 4 in
`contracts/games/arcade-gauntlet2.json`, `MAX_PLAYERS` is 4 in `arcade/stream.py` (so the arcade opens
four virtual pads, "Avrana Player 1" to "Avrana Player 4"), and `arcade/retroarch.cfg` already maps
four players. Party Home then offers "1–4 players" and "N of 4 playing", and a fifth phone is
refused as full. Tests keep the contract, the constant and `retroarch.cfg` equal. This is source
until it is deployed; nothing on the Pi was changed or tried.

**Deploying it: one line to check first.** Party Core takes `max_players` from the Game Contract
(AVR-229; ADR 0010, Amendments) and refuses to start when its config repeats a different value, naming
the field: `arcade-gauntlet2.max_players: the config says 2 but the contract says 4`. The repository's
example config carries no such line, but a `/etc/avrana-party/party-core.json` made before AVR-229
may. After the Party checkout that holds this change is in place and before Party Core is restarted,
the owner can check the live file, read-only, from that checkout:

```bash
python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json
```

If it names `arcade-gauntlet2.max_players`, remove that line from the config (the contract decides).
The arcade picks up four pads when it restarts, as for any arcade change.

**What four phones must still prove.** None of this has been tried on the Pi with more than two
phones.
- **Pad order.** RetroArch's `input_playerN_joypad_index` is a position in the order the four pads
  are enumerated, not a name. Check that the phone shown as Player 3 moves the third hero, and
  Player 4 the fourth, after a cold start of the arcade and after a restart.
- **Coin and Start on slots 3 and 4.** Only P1's coin and a short two-phone session are on record.
  Each of the four must be able to add a coin and start in its own slot.
- **CPU and Wi-Fi headroom.** One shared encode, four WebRTC sends and a four-player emulation, on
  the party Wi-Fi: frame rate, `/stats` capture ages, CPU, temperature, `vcgencmd get_throttled`,
  and whether a join forcing a keyframe disturbs the other three.
