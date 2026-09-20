/**
 * Pure metrics + threshold logic for the Avrana Party load/soak/regression harness.
 *
 * No Playwright, no I/O — just data in, verdict out — so it is unit-testable in
 * isolation (see tests/soak-metrics.spec.ts) and reusable by the live harness
 * (tests/soak.spec.ts, tests/fault.spec.ts).
 */

export interface ClientSample {
  t: number;               // seconds since capture start
  fps?: number | null;
  pktLostD?: number | null;   // packets lost in the last interval
  jitterBufMs?: number | null;
  pairRttMs?: number | null;  // ICE pair RTT in ms
  freezes?: number | null;    // cumulative freeze count
  kbps?: number | null;
}

export interface ServerSample {
  t: number;
  players: number;
  error: unknown;
  audioAgeP50?: number | null;
  videoAgeP50?: number | null;
  uptime?: number | null;
}

const nums = (xs: (number | null | undefined)[]): number[] =>
  xs.filter((x): x is number => typeof x === 'number' && Number.isFinite(x));

export function median(xs: (number | null | undefined)[]): number | null {
  const v = nums(xs).sort((a, b) => a - b);
  if (!v.length) return null;
  return +(v[Math.floor((v.length - 1) / 2)]).toFixed(2);
}

export function percentile(xs: (number | null | undefined)[], q: number): number | null {
  const v = nums(xs).sort((a, b) => a - b);
  if (!v.length) return null;
  return +(v[Math.min(v.length - 1, Math.floor(q * v.length))]).toFixed(2);
}

export function minOf(xs: (number | null | undefined)[]): number | null {
  const v = nums(xs);
  return v.length ? Math.min(...v) : null;
}
export function maxOf(xs: (number | null | undefined)[]): number | null {
  const v = nums(xs);
  return v.length ? Math.max(...v) : null;
}

export interface ClientSummary {
  n: number;
  fps: { med: number | null; min: number | null };
  loss: { med: number | null; max: number | null };
  jitterBufMs: { med: number | null; p95: number | null };
  pairRttMs: { med: number | null; p95: number | null };
  kbps: { med: number | null };
  freezesDelta: number | null;   // freezes gained across the window
}

export function summarizeClientSeries(samples: ClientSample[]): ClientSummary {
  const frz = nums(samples.map(s => s.freezes));
  return {
    n: samples.length,
    fps: { med: median(samples.map(s => s.fps)), min: minOf(samples.map(s => s.fps)) },
    loss: { med: median(samples.map(s => s.pktLostD)), max: maxOf(samples.map(s => s.pktLostD)) },
    jitterBufMs: { med: median(samples.map(s => s.jitterBufMs)), p95: percentile(samples.map(s => s.jitterBufMs), 0.95) },
    pairRttMs: { med: median(samples.map(s => s.pairRttMs)), p95: percentile(samples.map(s => s.pairRttMs), 0.95) },
    kbps: { med: median(samples.map(s => s.kbps)) },
    freezesDelta: frz.length ? +(frz[frz.length - 1] - frz[0]).toFixed(0) : null,
  };
}

export interface ServerSummary {
  players: { max: number | null };
  audioAgeMs: { start: number | null; end: number | null; drift: number | null };
  videoAgeMs: { med: number | null };
  errored: boolean;
  uptimeStart: number | null;
  uptimeEnd: number | null;
}

export function summarizeServerSeries(samples: ServerSample[]): ServerSummary {
  const audio = nums(samples.map(s => s.audioAgeP50));
  const ups = nums(samples.map(s => s.uptime));
  return {
    players: { max: maxOf(samples.map(s => s.players)) },
    audioAgeMs: {
      start: audio.length ? audio[0] : null,
      end: audio.length ? audio[audio.length - 1] : null,
      drift: audio.length ? +(audio[audio.length - 1] - audio[0]).toFixed(2) : null,
    },
    videoAgeMs: { med: median(samples.map(s => s.videoAgeP50)) },
    errored: samples.some(s => s.error != null && s.error !== false),
    uptimeStart: ups.length ? ups[0] : null,
    uptimeEnd: ups.length ? ups[ups.length - 1] : null,
  };
}

/**
 * Gating thresholds. Deliberately driven by signals that stay meaningful under
 * this harness's load model — N Chromium clients co-located on ONE laptop over a
 * (sometimes flaky) Wi-Fi link, which is pessimistic for client-side jitter/RTT
 * vs N independent phones. So the hard gates are server health, connectivity, no
 * sustained loss, and "fps did not collapse". jitterBuf/RTT are reported, not
 * gated. Real phones remain authoritative for absolute latency/jitter numbers.
 */
export interface Thresholds {
  minFpsMed: number;   // each client's median fps must be >= this
  minFpsFloor: number; // each client's worst-sample fps must be >= this
  maxLossMed: number;  // each client's median per-interval packet loss must be <= this
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  minFpsMed: 45,
  minFpsFloor: 20,
  maxLossMed: 0,
};

export interface Verdict { pass: boolean; violations: string[] }

export function evaluate(
  clients: { label: string; summary: ClientSummary }[],
  server: ServerSummary,
  expectedConnected: number,
  cfg: Thresholds = DEFAULT_THRESHOLDS,
): Verdict {
  const violations: string[] = [];
  if (server.errored) violations.push('server reported an error during the window');
  if (clients.length !== expectedConnected)
    violations.push(`expected ${expectedConnected} connected client(s), got ${clients.length}`);
  for (const { label, summary } of clients) {
    if (summary.n === 0) { violations.push(`${label}: no samples`); continue; }
    if (summary.fps.med != null && summary.fps.med < cfg.minFpsMed)
      violations.push(`${label}: median fps ${summary.fps.med} < ${cfg.minFpsMed}`);
    if (summary.fps.min != null && summary.fps.min < cfg.minFpsFloor)
      violations.push(`${label}: fps floor ${summary.fps.min} < ${cfg.minFpsFloor}`);
    if (summary.loss.med != null && summary.loss.med > cfg.maxLossMed)
      violations.push(`${label}: median loss ${summary.loss.med} > ${cfg.maxLossMed}`);
    // jitterBuf / RTT are reported (formatReport) but not gated — see Thresholds.
  }
  return { pass: violations.length === 0, violations };
}

export function formatReport(
  title: string,
  clients: { label: string; summary: ClientSummary }[],
  server: ServerSummary,
  verdict: Verdict,
): string {
  const L: string[] = [`=== ${title} ===`, verdict.pass ? 'PASS' : 'FAIL'];
  for (const v of verdict.violations) L.push(`  ✗ ${v}`);
  L.push(`server: players.max=${server.players.max} video-age med=${server.videoAgeMs.med}ms ` +
    `audio-age ${server.audioAgeMs.start}→${server.audioAgeMs.end}ms (drift ${server.audioAgeMs.drift}ms) ` +
    `uptime ${server.uptimeStart}→${server.uptimeEnd}s errored=${server.errored}`);
  for (const { label, summary } of clients) {
    L.push(`${label}: n=${summary.n} fps med=${summary.fps.med}/min=${summary.fps.min} ` +
      `loss med=${summary.loss.med}/max=${summary.loss.max} ` +
      `jitterBuf med=${summary.jitterBufMs.med}/p95=${summary.jitterBufMs.p95}ms ` +
      `rtt med=${summary.pairRttMs.med}/p95=${summary.pairRttMs.p95}ms ` +
      `kbps med=${summary.kbps.med} freezesΔ=${summary.freezesDelta}`);
  }
  return L.join('\n');
}
