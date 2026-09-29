# 2026-09-29 — Gauntlet II: Play gave no stream in production (AVR-92)

Branch `fix/avr-92-gauntlet-launch` (from `main` `15f6322`). **Not deployed and not verified on a
phone.** The Pi was inspected read-only (management LAN, `ssh party`); nothing was restarted or
changed on it. The laptop was not on the Party Wi-Fi (`https://party.avrana.net/` did not answer),
so nothing below is a Party-WLAN measurement.

## Symptom (owner, real iPhone, 2026-09-28 ~14:04 PDT)

From Party Home, the Gauntlet II controller page opened over `https://party.avrana.net/arcade/`.
Play did not produce a picture. "Other games" went to the LAN Games home (`/`), not Party Home.
Diagnostics called the phone's capability path `ready`.

## Evidence (read-only, 2026-09-28 20:37–20:42 PDT)

| Check | Result |
|---|---|
| Production checkout | `15f6322`, clean. The page `:8097/` serves byte-for-byte the checkout's `arcade/index.html` (sha256 `fca90aa0…`), which is the same as `main`. So the "older controller UI" is the current page, not a stale copy. This page has never been redesigned for Full Mode. |
| `avranaparty-arcade` | `active (running)` since 2026-09-27 21:26:38 (the owner's deploy restart), `NRestarts=0`, `Result=success` |
| `/arcade/stats` on the Pi | `error: null`, `emulator_running: true`, `players: 0`. By these fields the arcade looked healthy, and Party Home's card health (`web/party/app.js` `health()`) reads exactly these fields. |
| `video_frames` | **1,533,856 in two reads 3 s apart; the count did not move.** `uptime` advanced. No video is being encoded. |
| Threads of `stream.py` (`/proc/<pid>/task/*/wchan`, `top -H`) | The whole process was at 0 % CPU. `ximagesrc0:src` was blocked in `futex_do_wait`, which means it was waiting for an encoder input buffer. `video_encoder:src` was blocked in `poll`, which means it was waiting for the V4L2 encoder to return a frame. RetroArch was still running at about 129 % CPU, and so was Xvfb. |
| Journal at the phone's Play (14:03:54–14:04:14) | Three `GET /ws` returned 101, so signalling over HTTPS/nginx 443 worked. Each was followed about 4 s later by `Peer failed … RuntimeError: Media caps did not reach WebRTC`, the `stream.py` join path giving up because no H.264 reached the new peer. There was no `Creating offer` or `Offer sent` line, so ICE was never attempted. |
| Earlier journal | `video_encoder: Too old frames, bug in encoder -- please file a bug` appeared in bursts (64 lines since 2026-09-20; the last ones on 2026-09-27 22:31 and 23:37). There was no bus ERROR and no `Fatal:` line after the 21:26 start. The kernel log since 21:00 has nothing from the codec. |
| Power | `vcgencmd get_throttled` = `0x0` |

When the counter froze is not known. At the nominal 60 fps, 1,533,856 frames is about 7.1 h after
the 21:26:42 start, which puts it near 04:30 on 2026-09-28. That is an estimate: the real frame rate
over the night was not recorded, and nothing was logged at that time.

## Root cause

**Confirmed (direct evidence above):** the shared capture/encode pipeline had stalled silently.
The `v4l2h264enc` encoder stopped returning frames, but GStreamer posted no bus ERROR. `stream.py`
`watch()` restarted the process only on a bus ERROR or an emulator exit, so the process stayed
`active`. `/stats` kept reporting `error: null, emulator_running: true`. Every Play then waited for
media caps that could never come, and failed after about 4 s.

The phone showed "Connecting…" on a faded, disabled button, then "Checking…", then "Can’t connect
right now. Stay on the Avrana Party Wi-Fi, then tap Play." That message blamed the phone's Wi-Fi for
a server-side stall. To the player, Play looked dead.

**Hypothesis (not established):** a V4L2 (bcm2835-codec) encoder wedge. The earlier "Too old
frames" bursts are consistent with the encoder losing frames. The last burst was about 5 h before the
estimated stall, so they are not shown to be the trigger. Whether a process restart clears the
wedge is **not verified**. Past restarts (2026-09-26, 2026-09-27) did bring streaming back, but that
is not proof for this state.

**Ruled out for this incident:** service down or crash-looping; emulator down; signalling or path
mismatch under HTTPS (the 101 upgrades succeeded and the `Origin` check passed); mixed content (the
page uses `wss://` from its own origin); ICE or AP addressing (the failure came before any offer); a
stale page (the hash matched `main`); under-voltage.

**Navigation:** `arcade/index.html` hard-coded `<a href="/">Other games</a>`. On the 443 server, `/`
is the LAN Games upstream, so the link left the Party experience.

## Fix (in `arcade/**` only)

`arcade/stream.py`, the minimum needed to make the stall self-healing and visible:
- A **video stall watchdog.** `ximagesrc` runs at a fixed 60 fps (`use-damage=false`), so when the
  arcade is healthy, encoded video never pauses, even on a still screen. If no encoded video frame
  arrives for `VIDEO_STALL_S` = 10 s (counted from pipeline start, before the first frame),
  `watch()` sets `error = 'Video capture stalled'`. It then takes the existing fatal path: close
  phones with 1011, clean up, and exit with status 1, so `Restart=on-failure` restarts the service.
- An **exit backstop.** If that graceful cleanup itself hangs on a wedged encoder, a daemon timer
  forces `os._exit(1)` after 20 s, so systemd still restarts the service.
- `/stats` gains `sample_age_s` (seconds since the newest encoded sample, per medium). This makes
  "running but not streaming" visible.
- The caps timeout now tells the phone why it failed (`{"type":"error","reason":"no-media"}`) and
  logs which medium is missing.

`arcade/index.html` (page ids and the texts the live suite checks are unchanged):
- **Play shows progress.** While connecting, the button is `aria-busy`, stays at full opacity (it is
  no longer faded like a disabled control), and shows a spinner. The spinner is static under
  `prefers-reduced-motion`. The button reads "Connecting…", then "Starting video…" until the first
  frame, and the `role="status"` line narrates each step.
- **Failures are named.**
  - The arcade reports no media: "Gauntlet II isn’t sending a picture right now…"
  - `/arcade/stats` answers non-OK, or reports `error` or `emulator_running:false`: "Gauntlet II
    isn’t running right now…"
  - Full: unchanged.
  - Anything else: the existing Wi-Fi message.
- **No endless wait.** An attempt that has not connected within 20 s counts as failed. A connection
  with no picture after 10 s says "Connected, but no picture yet. Tap Enable sound; if it stays dark,
  tap Leave, then Play."
- **"Other games" goes to Party Home** (`/party/`) in a secure context (HTTPS Full Mode). Plain HTTP
  (`http://party.local/arcade/`, the captive and legacy path, which has no `/party/`) keeps `/`, so
  the live HTTP suite's `href="/"` check still holds. The page adds no history entries. Back from
  Party Home returns to a clean, disconnected arcade page with Play enabled, because `pagehide`
  releases the slot.
- Controls, Enable sound and Leave behave as before.

Not changed: nginx, systemd units, the Pi, Party Home or Diagnostics code, and the games repo.

## Tests (Windows laptop, 2026-09-28)

- `python -m unittest discover -s tests/unit -p "test_arcade_*.py"` ran 16 tests. The 13 that are
  relevant here pass, including the new `WatchLoop` tests:
  - `test_silent_video_stall_is_fatal`
  - `test_video_that_never_starts_is_fatal`
  - `test_flowing_video_is_not_fatal`

  The 3 failures are the known pre-existing Windows-only ones (`ProcessLifecycle` ×2 and
  `test_presentation_provider_shape`), and they fail identically on untouched `main` on this host.
  Linux CI covers them. They do not exercise the stall path: the stubbed pipeline starts, then stops
  or dies well within 10 s.
- `AVRANA_PYTHON=python npx playwright test -c playwright.offline.config.ts tests/offline/arcade.spec.ts`
  covers 18 tests per project: the 10 existing ones, one updated (`href` is now `/party/`), and 8
  new. The new tests cover:
  - the HTTP fallback `/`
  - Other games → `/party/` and Back → a clean arcade page
  - the busy (not faded) button through "Starting video…" to the picture
  - the "no-media" refusal, with no retry loop
  - a stopped arcade (502)
  - the 20 s connect timeout (Playwright fake clock)
  - the "no picture yet" hint
  - input and sound after connecting

  Results on a heavily loaded laptop, with other agents' runs in parallel:
  - `android-chromium`: 18/18 passed.
  - `iphone-size-chromium`: 17/18 passed. The failure was the existing test "a full game says so…".
    It saw `wake.requests: 0`, because the keep-awake module had not loaded yet; this change does
    not touch that code. Re-run alone with `--repeat-each=2`, it passed 4/4 across both projects.
    An earlier run of the new busy-state test also flaked on timing, so it now holds "Connecting
    video…" for 4 s instead of 1.5 s, and it passed in the iPhone-size run.

## Unverified

- That a restart clears the wedge, and that the watchdog fires on the real encoder. Stubs prove
  only the process lifecycle.
- The real-phone path end to end: Play → a picture → input and sound → Other games → Party Home.
- Whether the wedge recurs, and how often. Watch `NRestarts` and the `No encoded video for` log
  line. If the encoder wedges at driver level, the service would restart about every 15–20 s. That
  would show as `NRestarts` climbing, and it would need a reboot (owner) and a deeper look.
- Party Home and Diagnostics (other owners) still treat "the service answers and the emulator runs"
  and "the phone's capabilities are ready" as healthy. Neither is evidence that a stream reaches a
  phone. With this change, a stalled arcade exits within about 10 s, and while it restarts
  `/arcade/stats` returns 502 (card health: not running). Suggestion for the Party Home owner:
  treat `sample_age_s.video > 5` as not running, and never word capability `ready` as "the game
  works".

## Owner actions

1. **Now, independent of this branch:** production is still stalled (`video_frames` frozen). The
   only way to recover it is `sudo systemctl restart avranaparty-arcade`. Then confirm with
   `curl -s http://127.0.0.1:8097/stats` twice, a few seconds apart, on the Pi: `video_frames` must
   increase.
2. After review and merge: fast-forward `/home/cody/avrana-party` to the merge commit. The **page**
   changes go live at once, because `stream.py` serves `index.html` from the checkout on every
   request. The **watchdog** (`stream.py`) runs only after the next service start, so
   `sudo systemctl restart avranaparty-arcade` again, with owner approval.
3. Afterwards, check `systemctl show avranaparty-arcade -p NRestarts` and
   `journalctl -u avranaparty-arcade | grep -E "No encoded video|Fatal"` over the following days.

## Real-phone check (Tier 3; record the results here)

On the Avrana Party Wi-Fi, with an iPhone (Safari) and, if you have one, an Android phone (Chrome):

1. On the Pi, `curl -s http://127.0.0.1:8097/stats` twice, 3 s apart. `video_frames` rises and
   `sample_age_s.video` is below 1.
2. Open `https://party.avrana.net/party/`, then tap the Gauntlet II card. `/arcade/` opens.
3. Tap Play. The button stays bright, with a spinner, "Connecting…" and then "Starting video…". The
   status line reads "You are Player N. Connecting video…" and then "Player N connected…". A
   picture appears within a few seconds, and the overlay goes away.
4. Tap Add coin, then Start, and move with the d-pad. The game responds. Tap Enable sound: the
   sound plays and the button reads "Mute sound".
5. Tap "Other games". You land on Party Home (`/party/`), not the LAN Games list. Press Back: the
   arcade page shows Play (not a frozen picture), and a second phone can take the freed slot.
6. Optional negative check (the owner only): with `sudo systemctl stop avranaparty-arcade`, tap
   Play. Expect "Gauntlet II isn’t running right now…". Then start the service again.
7. Record the iOS version, the time to the first picture, and any message text that differs.
