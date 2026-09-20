# Findings 2026-09-20 — audio capture-age ratchet & fatal-error non-restart

Two code-level reliability issues confirmed during the harness sprint. Both need
a `stream.py` change + `avranaparty-arcade` restart to fix (root required); that
was **not deployed** this session because passwordless `sudo` was unavailable and
shipping to the live WebRTC path unverified was out of scope. Each has a concrete,
low-risk fix plan below.

## 1. Audio `capture_age` ratchet (was "audio latency drift")

### What it actually is
Not a slow uptime clock-drift. It is a **per-streaming-session ratchet**: audio
`capture_age` is flat at idle and steps up on each session, never recovering until
the process restarts. Measured on a fresh boot with a read-only /stats poller:

| uptime (s) | players | audio p50 (ms) | video p50 (ms) | note |
|---|---|---|---|---|
| 616 – 936 | 0 | **~12–14 (flat)** | ~10 | idle: no drift for 5+ min |
| 956 | 2 | 135 (p95 395) | 22 | soak session #1 (under load) |
| 976 – 1136 | 0 | **~313 (plateau)** | ~10 | stepped up, did NOT recover |
| 1156 | 2 | 641 | 13 | soak session #2 |
| 1176 – 1236 | 0 | **~1003 (plateau)** | ~10 | stepped up again |

So: 13 ms → 313 ms → 1003 ms, ~+300–690 ms per streaming session, persistent.
Video (`ximagesrc → v4l2h264enc`) never ratchets. This explains the earlier
session's 152 → 1553 ms climb (it tracked session count, not clock time).

### Reproducer
`npm run soak` (or any client session), then poll `/arcade/stats` at idle:
audio `capture_age_ms.p50` will have stepped up and stay there. Restart clears it.

### Where it lives
`stream.py` audio branch: `pulsesrc device=avrana_arcade.monitor ! audioconvert !
audioresample ! opusenc ! appsink sync=false max-buffers=4 drop=true`. Age is
`pipeline_running_clock − buffer.pts` measured in `distribute()` (stream.py:174).
Video uses the same measurement and is fine, so the metric is sound — the audio
*buffer timeline* falls progressively behind the running clock, one step per
session, and the step persists after peers detach.

### Hypotheses (ranked) to confirm with `GST_DEBUG` when deployable
1. **PulseAudio monitor latency grows when the null sink gains/loses a consumer.**
   Each peer transport adds/removes flow; the `avrana_arcade.monitor` source's
   reported latency may increase and not shrink, offsetting PTS. Check
   `pulsesrc` `actual-buffer-time`/latency across a session, and null-sink latency.
2. **Shared-clock / base-time interaction** between the capture pipeline and the
   per-peer transport pipelines (which call `use_clock(capture.get_clock())` +
   `set_base_time(...)`, stream.py:301–303). A re-latency event on attach could
   shift the audio segment.
3. **opusenc / resampler buffering** accumulating on live latency renegotiation.

### Fix candidates (low-risk first)
- **Re-timestamp audio to the running clock at distribution** (set `buffer.pts =
  now` for audio in `distribute()` before push). Decouples peers from any capture
  offset; for an arcade, low-latency recent audio ≫ exact lip-sync. Cheapest, and
  bounds the symptom regardless of root cause.
- **Bound the audio branch**: insert `queue max-size-time=100ms leaky=downstream`
  before `opusenc`, and/or pin `pulsesrc buffer-time/latency-time` low, so latency
  cannot ratchet.
- Confirm root cause (hypothesis 1/2) with `GST_DEBUG=pulsesrc:5,*clock*:5` across
  a connect/disconnect, then fix at the source if it's the null-sink latency.

**Verification:** restart to clear, capture idle baseline, run `npm run soak`,
confirm audio p50 no longer steps up and stays bounded. The harness already
measures `audioAgeMs.drift` per run.

## 2. Fatal pipeline/emulator error does not trigger a restart

`Stream.watch()` (stream.py:216–232) on a pipeline ERROR or emulator exit sets
`self.error`, closes peers, and **`return`s** — the process keeps running. New
connections then get `HTTPServiceUnavailable` (stream.py:253) forever: a zombie
serving 503s instead of crashing so systemd's `Restart=on-failure` recovers it.
Not appliance-grade.

### Fix
On a fatal, unrecoverable error, exit non-zero after cleanup so systemd restarts
the unit (or add `watchdog`/`Restart=always` semantics). Distinguish intentional
stop (SIGTERM) from a crash so a normal `systemctl stop` doesn't loop. Add a
harness/fault test that asserts `/arcade/stats` recovers (harder: needs a way to
induce a fatal error without root — candidate: a test hook, or observe after a
real crash). Currently `tests/fault.spec.ts` covers *client* faults; *server*
fault recovery needs deploy access to test end-to-end.
