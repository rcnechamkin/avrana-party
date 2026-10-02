# BookStack update — Avrana Party — 2026-09-20

> **ARCHIVED — non-authoritative.** Preserved publication draft; its BookStack authority claim
> and instructions below are historical. Start at [AGENTS](../../AGENTS.md) and [SYSTEM](../SYSTEM.md).

> Paste into the **Avrana Party** book (shelf: Avrana Party), pages *Decisions &
> Current State* and *Runbook*. Written to the repo because the BookStack MCP
> server was unavailable this session (failed to connect), so it could not be
> pushed directly. Git remains the code source of truth; BookStack the
> architectural/operational one.

## Current state (2026-09-20)

- **Two-iPhone Gauntlet II streaming: VERIFIED on real hardware.** A 3-min
  captured session (177 samples) held both phones at ~60 fps, 0 median packet
  loss, ~26 ms jitter buffer, ~3 ms pair RTT, ~6–7 ms input-ack RTT; one shared
  encode feeds both peers (server video capture-age ~11 ms). `MAX_PLAYERS` stays
  2 (no long soak yet).
- **Load/soak/fault/regression harness added** (`tests/`, `tests/lib/`):
  `npm run soak` (N clients, `SOAK_CLIENTS`/`SOAK_SECONDS`), `npm run fault`
  (abrupt drop, churn, over-subscription → recovery), `npm test` (fast suite),
  unit-tested pure logic. Gates on server health + connectivity + loss + fps
  (client-side jitter/RTT reported, not gated — co-located Chromium is pessimistic
  vs real phones). Run from a machine on the Avrana Party Wi-Fi. Design/rationale:
  repo `docs/adr/0001-load-soak-fault-harness.md`.
- **Audio capture-age ratchet — ROOT CAUSE CONFIRMED, fix implemented but
  UNVERIFIED.** Cause: capture pipeline runs on the system (wall) clock while
  `pulsesrc` (a `GstAudioBaseSrc`) timestamps from its sample-position ringbuffer
  clock and ignores `do-timestamp`; on an audio-thread stall the sample clock
  falls permanently behind wall-clock, so `capture_age = now − pts` ratchets per
  session (13→313→1003→2142 ms measured). PulseAudio latency ~0 → content is
  fresh, only the PTS is mislabelled; video is immune (ximagesrc is clock-stamped).
  Fix (commit `6acf0b0`): re-stamp audio `pts=now` in `distribute()`. **NOT yet
  verified — needs a restart + soak** (see Runbook). A `do-timestamp=true` attempt
  was a no-op and was reverted. Details: repo
  `docs/findings/2026-09-20-audio-ratchet-and-recovery.md`.
- **Fatal-error recovery gap (open, not started):** `Stream.watch()` returns
  instead of exiting on a fatal pipeline/emulator error, so systemd
  `Restart=on-failure` never fires (zombie 503s). Fix plan in the findings doc.
- **Sunshine + Moonlight benchmark — HELD (blocked on upstream).** Released
  Sunshine has no encoder path for the Pi 4 V4L2 hardware H.264 encoder (the
  zero-copy V4L2 encoder is unmerged draft PR LizardByte/Sunshine#5717 + needs
  FFmpeg patches); it would fall back to software x264, which can't do 720p60 on a
  Pi 4 and would be an unfair SW-vs-HW comparison. Revisit when #5717 ships. The
  Pi HW encoder is capable; the gap is Sunshine software support, not the Pi.
- **Power (recurring under-voltage): PARKED as accepted tech debt.** Validated
  ~6 dips/20 min at arcade-no-viewer load (occasional live throttling); no known-
  good hardware spares. Do not run further power experiments unless a new symptom
  appears. Authoritative dip counter needs NO sudo:
  `journalctl -k -b | grep -icE 'undervoltage|voltage normalis'` (÷2). Beszel hub
  confirmed recording `party`.

## Runbook additions

**First action next session — load & verify the audio fix (currently the running
service has a broken interim audio build until restarted):**
```bash
# on party
sudo systemctl restart avranaparty-arcade
# from a laptop on the Avrana Party Wi-Fi
cd avrana-party
SOAK_SECONDS=60 npx playwright test tests/soak.spec.ts --project=chromium
#   expect: PASS, server audio-age drift ~0 (was +2782 ms), no server error
# then confirm A/V by ear on a real iPhone
```
Rollback if worse: `git revert 6acf0b0 && git push`, then on party
`git pull --ff-only && sudo systemctl restart avranaparty-arcade` (restores
working audio; the ratchet returns).

**Regression harness (from a laptop on Avrana Party Wi-Fi):**
```bash
npm ci && npm run install-browsers   # once
npm test          # fast regression (excludes @heavy)
npm run soak      # 2-client 90s load/soak
npm run fault     # fault injection & recovery
```

**Environmental note:** the dev laptop repeatedly dropped off the "Avrana Party"
SSID this session (breaks harness runs; Pi/phones unaffected). Reconnect with
`netsh wlan connect name="Avrana Party"`; consider disabling the adapter's Wi-Fi
power-save for unattended soaks.
