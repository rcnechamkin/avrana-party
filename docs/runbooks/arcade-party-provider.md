# Runbook: make Gauntlet II a Party-launched game (AVR-134)

Status: **NOT RUN.** This is the owner's deploy for ADR 0009.

- It follows AVR-128 (ADR 0008) and needs that on the Pi first:
  - avrana-party #30 merged and deployed;
  - avrana-party-games #11 merged and deployed;
  - a Party Home release built from them.
- Every step below that uses `sudo` is the owner's.

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

**New:** the arcade listens on `127.0.0.1:8098`, loopback only.

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
4. **Party Home offers it.** On two phones, both Join. Gauntlet II shows "Start for everyone" to the Party Host only.
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
- **Controllers:** the arcade does not verify Party tickets yet. Controllers go to whoever opens the page while it runs, as before.
