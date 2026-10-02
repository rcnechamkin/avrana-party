# Runbook: Bomberman on real phones through Party Home (PS1 slice)

> **Experiment-only procedure.** The 2026-09-24 Party service/PS1 branch below has its
> own old Join UI and is not the current Party Core/ADR 0011 normal flow. Do not promote it
> as a canonical console contract. Current issue scope is in Linear; deployed state is in SYSTEM.

Status: **ready to run** (2026-09-24). Everything below was exercised on the Pi with *simulated*
phones over eth0 (`docs/findings/2026-09-24-ps1-bomberman-party-slice.md`); this run is the first
with real phones on the party Wi-Fi. About 30 minutes. Leave any result blank if it wasn't measured.

## What it tests

Join Avrana Party → Party Home → host picks Bomberman → phones follow into the game → each phone is
its own seat's controller → the host ends the game → everyone is back at Party Home.
Dev ports only: the party front door on **8190**, the PS1 stream on 127.0.0.1:8198 behind it.
No live service, nginx or network setting changes — **except that the arcade is stopped** for the
test (the only sudo step; it restarts at the end).

## 1. Owner, on the Pi (5 min)

```bash
ssh party
vcgencmd get_throttled; journalctl -k -b | grep -icE 'undervoltage|voltage normalis'   # expect 0x0 and a number; note both
cd ~/avrana-lab/avrana-party-docs && git fetch -q && git merge --ff-only origin/experiment/ps1-title-profiles
cd ~/avrana-lab/party-svc && git fetch -q && git merge --ff-only origin/experiment/party-service
sudo systemctl stop avranaparty-arcade        # frees ~1.7 cores; WITHOUT this Bomberman runs at ~65-70% speed
cd ~/avrana-lab/party-svc/experiments/party-service
AVRANA_PS1_MEASURE=1 AVRANA_PS1_SHOW_FPS=1 timeout 2h python3 front.py --port 8190 --host 10.42.0.1:8190 \
  --ps1 /home/cody/avrana-lab/avrana-party-docs/ps1 --devices ""
```

Leave that terminal open (Ctrl+C ends the party and stops the emulator). `AVRANA_PS1_MEASURE=1`
logs every latency stage (a small barcode appears in the picture's top-left corner; that is the
measurement, not a glitch). `AVRANA_PS1_SHOW_FPS=1`
prints RetroArch's real frame rate in the corner of the picture: **60 = full speed**.

## 2. Phones (2–4 people)

1. Join the **Avrana Party** Wi-Fi, open **`http://10.42.0.1:8190/party/`**, type a name, *Join the party*.
   The first to join is the host. (Names like "Host" or "System" are refused on purpose.)
2. Host: tap the **Bomberman Party Edition** card → *Start Bomberman Party Edition*. Party Home says "Starting…";
   after ~5 s every seated phone opens the game by itself.
3. Everyone taps **Play** (sound comes on with it; if not, tap the 🔇 speaker). The badge says *Player N* — it should match the
   seat Party Home showed.
4. Player 1 drives the menus: Start (skip the intro) → Start at the title → **Down** to BATTLE GAME →
   **✕** (Start does not confirm menus) → Battle Royal ✕ → Beginner ✕ → Single Match ✕ → rules ✕ →
   "How many players": Players 4–5 you don't have should be COM or off → ✕ → characters ✕ → stage ✕.
   Presses during screen fades are ignored; press again.
5. Play one full match. Then try: lock one phone for 30 s and unlock it (tap Play again: same player?);
   a late fifth phone joins the party (it gets an open seat or watches).
6. Host: tap **‹** (top-left of the game), then *End the game for everyone*. Every phone should land on Party Home.
   (Everything else a player might need — sound, giving up the controller, Party Home — is in the **⋯** menu.)

## 2b. Latency A/B: is the AP's power save the cause of the stalls? (20 min, sudo)

The first playtest's stalls (0.3–2.2 s, `docs/findings/2026-09-24-ps1-latency.md`) hit TCP and UDP
together, pointing at the Wi-Fi link; the AP radio reports `Power save: on`.

1. Play **5 minutes** as-is (one phone is enough; keep it awake and in hand). Note the start and end time.
2. On the Pi, **temporarily** turn the radio's power save off (reverts at the next reboot):
   `sudo iw dev wlan0 set power_save off` — check with `/usr/sbin/iw dev wlan0 get power_save`.
3. Play **5 more minutes** the same way. Note the times.
4. Compare the two halves (read-only, on the Pi):
   ```bash
   L=$(ls -t ~/avrana-lab/ps1/runtime/latency/*.jsonl | head -1)
   python3 ~/avrana-lab/avrana-party-docs/ps1/tools/latency-report.py $L --since HH:MM --until HH:MM
   ```
   Look at: WebSocket round trip p99/max, `gap_max` p95, spike seconds and how they are classified
   (network / server / browser). If the second half is clearly better, make it permanent with
   `sudo nmcli connection modify "Avrana Party Internal" 802-11-wireless.powersave 2` (a network
   setting: your call), then reconnect the AP.
5. Optional: open the game page with `#diag` at the end of its address to see the live numbers on
   the phone (A touch→sent, B uplink, C inject, E capture→shown, D touch→first frame after the press).

## 3. Record

| Item | Result |
|---|---|
| Start → phones in game (s) | |
| FPS in the corner during a match (min / typical) | |
| Each phone moves only its own bomber? | |
| Player N matches the Party Home seat? | |
| Sound on each phone? A/V in sync? | |
| Input feel (1 = unplayable, 5 = like a console) | |
| Picture: readable on a phone? portrait vs landscape | |
| Lock/unlock 30 s: same player back? | |
| End game: everyone back at Party Home? | |
| `get_throttled` and dip count at the end | |
| Fun (1–5), "one more round?" | |

## 4. Afterwards (owner)

Ctrl+C the front door, then:

```bash
pgrep -af 'stream_ps1|retroarch.*avrana-lab' || echo "PS1 stopped"
sudo systemctl start avranaparty-arcade
vcgencmd get_throttled; journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
```

Emulator logs: `~/avrana-lab/party-svc/experiments/party-service/dev-data/runtime-logs/`.

## Known limits

Hot-seat Worms also works through the same flow (one seat). Five players: pad 2D has no phone slot.
Personal Viewports (cropped views) are **off** in this flow; they are a stream flag
(`--viewports quad`) for experiments, and Bomberman is not split-screen.
