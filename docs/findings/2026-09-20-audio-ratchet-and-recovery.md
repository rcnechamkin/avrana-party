# Findings 2026-09-20 — audio capture-age ratchet & fatal-error non-restart

Two confirmed reliability defects. #1 was root-caused and a fix implemented
(commit `6acf0b0`) but **NOT yet verified** — the session ended before a
verifying restart. #2 is characterized with a fix plan but not started.

---

## 1. Audio `capture_age` ratchet — ROOT CAUSE CONFIRMED, fix UNVERIFIED

### Symptom
Audio `capture_age` (from `/arcade/stats`) is flat at idle but steps up per
streaming session and never recovers until restart: **13 → 313 → 1003 → 2142 ms**
across sessions; video stays ~10 ms.

### Root cause (confirmed by direct evidence)
The capture pipeline runs on the **system (wall) clock**, but `pulsesrc` — a
`GstAudioBaseSrc` — timestamps audio from its **sample-position ringbuffer
clock**. When the audio streaming thread stalls during a client session, the
sample clock falls behind wall-clock and **never catches up** (a live source
resumes at 1×; it does not fast-forward). `capture_age = now − buffer.pts` is
that permanent offset. Video is immune because `ximagesrc` stamps each grab with
the current clock.

Evidence:
- **`AUDIODBG` trace across a ~4 s stall:** `now` (wall) advanced **+6739 ms**
  while audio `pts` advanced only **+3140 ms** → pts fell ~3.6 s behind, then
  settled at a permanent ~2100 ms plateau (pts and now advancing at equal rate
  thereafter).
- **PulseAudio latencies ~0** (`pactl`: null-sink 6 ms, monitor 0 µs, pulsesrc
  source-output Buffer/Source latency 0). So the samples are **fresh** — only the
  PTS *label* lags. This rules out a PulseAudio/queue backlog.
- All GStreamer buffering stages are bounded (appsink `max-buffers=4` ≈ 40 ms), so
  the ~1.5–2.8 s can only live in the PTS-vs-clock relationship.

### Fix journey (systematic-debugging)
1. **Hypothesis 1 — `pulsesrc do-timestamp=true`** (commit `fb84471`): **FAILED,
   no-op.** `GstAudioBaseSrc` ignores `do-timestamp` and always uses its
   ringbuffer timestamps. Ratchet unchanged (14 → 2796 ms). Reverted.
2. **Hypothesis 2 — re-timestamp audio to the running clock in `distribute()`**
   (current, commit `6acf0b0`): stamp each audio buffer `pts = now` (the pipeline
   running-clock) before pushing to peers, so a stall drops/gaps audio instead of
   banking permanent latency. First attempt used `buffer.make_writable()` →
   `AttributeError` (no such method in PyGObject) which **broke audio** for one
   restart; corrected to **`buffer.copy()`** (writable copy, shares memory).

### STATUS — action required next session
- `6acf0b0` is on `main` and pulled onto party's checkout, but the **running
  service still has the broken `make_writable` build** (audio down) until a
  restart. It is **UNVERIFIED**: do not claim the ratchet is fixed.
- **To restore audio + load the fix, then verify:**
  ```bash
  # on party:
  sudo systemctl restart avranaparty-arcade
  # from a laptop on the Avrana Party Wi-Fi:
  SOAK_SECONDS=60 npx playwright test tests/soak.spec.ts --project=chromium
  #   PASS + server audio-age drift ~0 (was +2782 ms) + no server error  => good
  ```
- **Rollback if worse** (restores known-good audio, ratchet returns):
  ```bash
  git revert 6acf0b0 && git push        # then git pull + restart on party
  ```
- **Metric caveat:** after re-stamp, `capture_age['audio'] = now − now ≈ 0` by
  construction. This is *honest* (PulseAudio latency ~0 proves the content is
  fresh; the pre-fix value measured the mislabel, not true staleness), but it
  means `capture_age` can no longer detect a future audio-staleness regression.
  Follow-up: verify with a **real iPhone** (A/V sync by ear) and/or measure
  **client-side audio jitter-buffer** in the harness instead.
- **Deeper root (optional):** the underlying audio-thread *stall* still occurs
  (cause not isolated — likely GIL contention / a heavy synchronous GStreamer op
  during peer connect/teardown). The re-timestamp makes the ratchet harmless;
  eliminating the stall itself is a separate, larger effort. An alternative fix
  worth evaluating is forcing the pipeline onto `pulsesrc`'s audio clock
  (`pipeline.use_clock(pulsesrc.provide_clock())`) so `now` and `pts` share one
  domain and `capture_age` stays honest — riskier (touches clock selection for
  video/WebRTC), so only with the harness as a safety net.

### Reproducer / tooling
`npm run soak` (or any client session) then poll `/arcade/stats`. Temporary
instrumentation lived on branch `debug/audio-ratchet` (an `AUDIODBG` log of
age/pts/now/peers in `distribute`); delete that branch once no longer needed.

---

## 2. Fatal pipeline/emulator error does not restart — NOT STARTED

`Stream.watch()` (`stream.py`) on a pipeline ERROR or emulator exit sets
`self.error`, closes peers, and `return`s — the process keeps running and serves
`HTTPServiceUnavailable` forever, so systemd `Restart=on-failure` never fires.

### Fix plan
On a fatal, unrecoverable error, exit non-zero after cleanup so systemd restarts
the unit; distinguish an intentional SIGTERM stop (clean exit) from a crash so a
normal `systemctl stop` does not loop. Add a recovery test (inducing a server
fatal error needs deploy access; `tests/fault.spec.ts` currently covers only
*client* faults). Ran out of session time before starting this.
