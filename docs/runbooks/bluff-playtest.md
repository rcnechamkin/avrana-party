# Runbook: first real-phone BLUFF playtest (N2)

Status: **ready to run**, subject to the owner's power decision (see "Gate" below). Prepared 2026-09-24 from a read-only
audit of the Pi and the BLUFF code; no server was started. Leave any result cell **blank** if it
wasn't measured — never estimate after the fact.

## Gate

**Owner decision (open, `PARTY-PLATFORM.md` §16):** either (a) wait for a clean power run first, or
(b) run on the current setup and record the dips (ROADMAP "Next action" item 2). Either way:

- Power: note `vcgencmd get_throttled` at the start (`0x0` under option a) **and** the kernel under-voltage count
  (`journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`) recorded at start and end. BLUFF
  is light; the arcade stream (Gauntlet II, load 2.4–3.9) is not. Stopping the arcade is a service
  change → owner's call; note whether it ran.
- Offline mode on (`docs/findings/2026-09-24-party-network-and-offline-mode.md`), or record that
  the test ran with home internet behind the Pi.

## What exists (facts, 2026-09-24)

- Dev fork: `~/avrana-lab/avrana-party-games` on `party`, `main` @ `2cf4831` (laptop backup
  identical). 391 BLUFF unit tests pass on the Pi. **Not running** after the reboot.
- **Everything happens on one origin: `http://10.42.0.1:8196/`.** Identity lives in per-origin
  browser storage, so a phone that also opens the port-80 hub is a *different player* there.
- Second game for the switch: **WORD RUSH** (1–12 players, 5–10 min, TV optional). Backup: CATEGORY
  BLITZ. Avoid Trivia (late-answer bug), Werewolf (needs 5), TV games.
- Behaviour to expect:
  - **Names** come from the hub profile (BLUFF has no name field); ASCII letters/digits/space and
    `-'.!?` only, 14 chars — emoji and accents are silently stripped. Opening BLUFF directly plays
    as "PLAYER".
  - **Start:** `MIN_PLAYERS = 1` — the first player to press Ready can START alone; anyone not ready
    becomes a spectator. Expected source of "who starts?" confusion. **Measure, don't fix.**
  - **Switch:** no "party follows host". Each phone taps ⌂ then the other tile. Leaving mid-game via
    ⌂ counts as a disconnect. Results always run 20 s before the lobby.
  - **Sleep/wake:** retry backoff 0.6 s + 0.8 s/attempt (max 5 s); same token → same seat, cards,
    deadline; others see "X is back". Away after 30 s (others' prompt) / 60 s (own turn) → passive
    autopilot. All seated humans gone → pause; ≥ 10 s on resume; a newcomer may end it after 60 s;
    abandoned after 5 min.
  - **Late join:** spectator (public view), a seat next game.
  - **No host exists.** The "starter" is only recorded. Their disconnect → reconnecting → away →
    autopilot; nobody gains powers.
- Logs today **cannot reconstruct a session**: `srv.sh` writes untimestamped uvicorn output to
  `/tmp` (tmpfs, lost on reboot); no join/leave lines; BLUFF's event log is in memory only.

## Setup (T−20 min)

1. Record the Pi clock next to a phone clock (`date` on the Pi; the Pi has no RTC and can't sync
   offline — note the offset).
2. Start the dev server **with a timestamped log** (quoting checked 2026-09-24; `srv.sh stop 8196`
   still stops it, it matches by port and working directory):

   ```bash
   mkdir -p ~/avrana-lab/playtest
   RUN=~/avrana-lab/playtest/$(date +%Y%m%dT%H%M%S)
   setsid -f sh -c 'cd ~/avrana-lab/avrana-party-games && LANGAMES_PORT=8196 .venv/bin/python -u server.py 2>&1 | awk "{ print strftime(\"%F %T\"), \$0; fflush() }" >> "$1-server.log"' sh "$RUN" < /dev/null
   ```
3. Start the 1 s state poller (per-game phase and player counts):

   ```bash
   setsid -f sh -c 'while :; do echo "$(date +%T) $(curl -s -m 2 http://127.0.0.1:8196/health)"; sleep 1; done >> "$1-health.log"' sh "$RUN" < /dev/null
   ```
   Stop both afterwards: `~/avrana-lab/srv.sh stop 8196` and `pkill -f '[8]196/health'`.
4. `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8196/games/bluff/` → 200.
5. Phones: 3–6, **at least one Android**. Per phone: model, OS, browser, mobile data on/off. No TV,
   no app installs.
6. Screen-record every phone (iOS stops recording at lock — the sleep phone's recording covers only
   up to the lock). Observer: stopwatch + this sheet.

Optional, needs the owner's OK (a new script): a watch-only WebSocket logger (`hello {watch:true}`)
that records public state frames (connected flags, `step`, public log) without taking a seat.

## Events

| # | Do | Capture |
|---|---|---|
| E1 First join | Say only "join the Avrana Party Wi-Fi, open 10.42.0.1:8196" (or show a QR). Each sets a name on the hub, then taps BLUFF | power-on → first game time; joined unaided (QR / typed); any captive or "no internet" prompt (exact words); mangled names |
| E2 Start | Don't say who starts | who pressed START; anyone left unseated |
| E3 Sleep/wake | During someone else's prompt, phone X locks 20 s, unlocks | same seat and cards? time to "X is back"? autopilot used? |
| E4 Network drop | Phone Y airplane mode 20 s, off | banner clears? seat kept? recovery time? Wi-Fi rejoins by itself? |
| E5 Late join | Phone Z joins mid-game | spectator view shown? seated next game? |
| E6 Starter leaves | The starter taps ⌂ and stays away | game continues? seat → away/autopilot? anyone confused about control? |
| E7 Clean end | Play to a winner (or Leave game) | results 20 s → lobby, everyone back? |
| E8 Switch (stopwatch) | From "let's switch": all tap ⌂ → WORD RUSH; stop when every phone is in its lobby. Then back to BLUFF, timed the same way | seconds each way; players lost; who was confused. **> 60 s or a lost player ⇒ "party follows host" is built first** |
| Wrap-up | Ask | wanted chat? "one more game?" requests? fun 1–5 |

## Results sheet

| Item | Phone / player | Clock time | Duration | Outcome / notes |
|---|---|---|---|---|
| Power: throttled / dip count at start, end | | | | |
| Offline mode on? arcade running? | | | | |
| Power-on → first game | | | | |
| Joined unaided (QR / typed) | | | | |
| Captive / no-internet prompt | | | | |
| E2 who pressed START; anyone unseated | | | | |
| E3 sleep/wake: seat kept? | | | | |
| E4 airplane 20 s: seat kept? | | | | |
| E5 late join: spectator OK? | | | | |
| E6 starter left: game continued? | | | | |
| E7 clean end | | | | |
| E8 switch there / back (s), players lost | | | | |
| Seats lost to sleep/reload | | | | |
| Chat wanted? / One more game? / Fun (1–5) | | | | |

Keep: `$RUN-server.log`, `$RUN-health.log`, the screen recordings, the power readings. Write the
results up as a dated `docs/findings/` entry; they set the platform timers and the F-item order
(ROADMAP N5).

## Known risks

One room per server — never restart it mid-test · private tabs lose the token when closed · no
target confirmation (a mis-tap can spend a Coup) · Android's probe gets 404 (expect "no internet";
with mobile data on, traffic may go cellular — see the network findings) · real iPhone Safari
(toolbar, safe areas, locking during someone's claim) untested.
