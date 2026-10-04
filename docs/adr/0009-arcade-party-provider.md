# ADR 0009: The arcade is a Party-launched provider

**Status: implemented and merged.**
- Implemented and TESTED on a laptop, on branch `fix/avr-134-arcade-provider`, stacked on AVR-128's `fix/avr-128-party-navigation`.
- Merged (PR #31) and **deployed 2026-09-29**, verified server-side on the Pi (`docs/findings/2026-09-29-avr128-134-deploy.md`). Not yet tried on a phone.
- Date: 2026-09-29. Linear: AVR-134. Extends ADR 0006 and ADR 0008.

## Context

ADR 0008 made Party Core enforce one Party activity, and a switch ends the old game at its server before the next launch. That covers games attached through the session protocol. BLUFF is one; the arcade was not.

`avranaparty-arcade` is an always-on systemd service. RetroArch, the 60 fps `ximagesrc` capture, the `v4l2h264enc` hardware encode and Opus audio all run from boot, whether or not anyone plays. So Gauntlet II could hold the CPU, the encoder and power while the party played BLUFF. On the Pi, the arcade already starves the PS1 experiment.

Letting Party Core stop the systemd unit was rejected, for three reasons:
- It needs new privileges: a polkit rule or sudoers entry for an unprivileged, sandboxed service (`NoNewPrivileges`, `ProtectSystem=strict`).
- It takes the arcade's page, `/stats` and controllers down with the runtime.
- It turns every host switch into a systemd operation.

## Decision

1. **Party Core controls the arcade's heavy runtime, not its unit.**
   - With a Party session key, `arcade/stream.py` starts idle. The page, the two uinput controllers, `/stats`, Xvfb and the audio sink stay up; they are light.
   - Party Core's signed `launch` starts RetroArch and the capture/encode. Its signed `end` stops them, encode first, then RetroArch.
   - This is the unchanged session protocol v0 (ADR 0006), so it needs no new privileges, systemd change or nginx change.
   - Rules and tests: `avrana/party/managed.py`.
2. **The control routes are loopback-only, on a port nginx never forwards.**
   (Loopback keeps browsers out; it does not identify the caller among local services, which
   all run as one user today. See [ADR 0016](0016-service-identities-and-local-trust-boundary.md).)
   - Party Core reaches the arcade at `http://127.0.0.1:8098/avrana/session/v0/{launch,end}`.
   - nginx's `/arcade/` proxy sets no `X-Forwarded-For`, so on port 8097 a phone's request would look local. The control routes therefore get their own `127.0.0.1:8098` listener.
   - They also refuse proxy headers, bodies over 8 KiB, and unsigned, expired, replayed or misaddressed messages.
3. **Ordering and failures are handled by one lock in the arcade.** Launch, end and abandon are serialized, so a stop never overlaps a start.
   - **Launch over a lost end:** a launch while an older run is still up stops that run first.
   - **Failed or slow start:** a start that fails, or takes longer than 15 s, is stopped again and answered `{"ok": false, message}`. The party then shows why.
   - **End for the running session:** stops it.
   - **End for another session while idle:** answered `ok`. After an arcade restart or a failed start nothing runs, so the host's switch can go on.
   - **End for another session while a newer one runs:** refused (409). A late message never stops the current game.
   - **A stop that fails:** is not confirmed, so the switch does not start the next game (ADR 0008).
4. **Party Core rolls back a failed launch at the game.**
   - When a launch fails or times out, `PartyService` sends that game an `end` before it records `launch_failed`, for every game.
   - While that happens the session is still `launching`, so nothing else can start.
   - Each game endpoint may set its own link `timeout`. The arcade's is 25 s: its 15 s start bound plus a 5 s stop.
5. **Recovery.**
   - **Fatal failure mid-session:** a fatal arcade failure (the watchdog, emulator death) during a Party session reports `ended: abandoned`: one signed POST, bounded to about 3 s. Then the process exits as before. The Party goes to the lobby instead of showing a game that is gone, and systemd restarts the arcade idle.
   - **Restart:** a restarted arcade has forgotten the session. The party's next `end` is answered `ok`, per rule 3.
6. **Always-on stays the default, and it is the rollback.**
   - With no key, or no loopback `AVRANA_PARTY_URL`, the arcade runs always-on exactly as before.
   - Party-managed mode is switched on only by the drop-in `deploy/arcade/avrana-party-session.conf` plus the key.
7. **Gauntlet II is a Party game.** `arcade-gauntlet2` is in the Party Core config (`max_players` 2, from its contract).
   - Party Home shows the host "Start for everyone" and "Switch everyone"; others see "The host starts it".
   - The arcade page follows the Party as that game (ADR 0008), so the host's End brings its players home, and a switch to BLUFF takes them there.
   - A phone that opens `/arcade/` while it is idle is told the Party Host starts it.

## Consequences

**Code and deploy files:**
- `avrana/party/managed.py`: the rules, the HTTP guard, and configuration.
- `arcade/stream.py`: `start_runtime`/`stop_runtime`, the control listener, `state` and `party_managed` in `/stats`, and the idle 503.
- `arcade/index.html`: the idle message, and following as `arcade-gauntlet2`.
- `avrana/party/service.py` and `avrana/party/sessions.py`: launch rollback and per-game link timeouts.
- `deploy/arcade/avrana-party-session.conf` and `deploy/party-core/party-core.example.json`.
- The owner's steps: `docs/runbooks/arcade-party-provider.md`.

**Tests:**
- `tests/unit/test_party_managed.py`:
  - the rules and the guard;
  - a cross-component run: real Party Core, the HTTP link, a reference BLUFF server and a managed arcade over HTTP, with one timeline showing BLUFF and the arcade never run at once;
  - start failure, a start slower than the link, restart recovery and abandon.
- `tests/unit/test_arcade_stream.py` `ManagedArcade`: `stream.py` idle, then launch, end, and launch again, plus the fatal report.
- `tests/unit/test_party_core_deploy.py`: the drop-in and the config agree, and nginx never names port 8098.

**Accepted limits in v0:**
- **Who gets a controller.** The arcade does not verify tickets. While Gauntlet II is the Party's game, any phone on its page can take a free controller, as today. Seating by the Party roster is a later step.
- **Standalone arcade.** The standalone `http://party.local/arcade/` path works only while the Party runs Gauntlet II. Always-on is the rollback.
- **A late start after a link timeout.** Party Core stops waiting after the link timeout. If the arcade finishes starting after that, it is stopped by the queued rollback `end` about a second later. The 25 s link timeout is set above the arcade's own bound to make this rare.
- **Not measured:** power and CPU when idle versus running on the Pi, and the effect on the PS1 experiment.

**Tier 3, still open:**
- The Pi: the RetroArch and encoder restart cycle, and SDL keeping the controllers across runs.
- Real phones.
