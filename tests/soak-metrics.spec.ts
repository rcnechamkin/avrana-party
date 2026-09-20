import { test, expect } from '@playwright/test';
import {
  median, percentile, minOf, maxOf,
  summarizeClientSeries, summarizeServerSeries, evaluate,
  DEFAULT_THRESHOLDS, type ClientSample, type ServerSample,
} from './lib/soak-metrics';

// Pure unit tests — no browser, no network. Guards the threshold/aggregation
// logic the live harness depends on.
test.describe('soak-metrics (pure)', () => {
  test('median / percentile / min / max ignore nulls', () => {
    expect(median([3, 1, 2, null, undefined])).toBe(2);
    expect(median([])).toBeNull();
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95)).toBe(10);
    expect(minOf([5, null, 2, 9])).toBe(2);
    expect(maxOf([5, null, 2, 9])).toBe(9);
    expect(minOf([null, undefined])).toBeNull();
  });

  test('summarizeClientSeries computes fps/loss/jitter and freeze delta', () => {
    const s: ClientSample[] = [
      { t: 0, fps: 60, pktLostD: 0, jitterBufMs: 20, pairRttMs: 5, freezes: 2, kbps: 1800 },
      { t: 5, fps: 59, pktLostD: 0, jitterBufMs: 30, pairRttMs: 6, freezes: 2, kbps: 1700 },
      { t: 10, fps: 58, pktLostD: 3, jitterBufMs: 40, pairRttMs: 9, freezes: 4, kbps: 1600 },
    ];
    const sum = summarizeClientSeries(s);
    expect(sum.n).toBe(3);
    expect(sum.fps.med).toBe(59);
    expect(sum.fps.min).toBe(58);
    expect(sum.loss.med).toBe(0);
    expect(sum.loss.max).toBe(3);
    expect(sum.freezesDelta).toBe(2); // 4 - 2
  });

  test('summarizeServerSeries reports audio-age drift and errors', () => {
    const s: ServerSample[] = [
      { t: 0, players: 2, error: null, audioAgeP50: 15, videoAgeP50: 10, uptime: 400 },
      { t: 30, players: 2, error: null, audioAgeP50: 60, videoAgeP50: 11, uptime: 430 },
    ];
    const sum = summarizeServerSeries(s);
    expect(sum.audioAgeMs.start).toBe(15);
    expect(sum.audioAgeMs.end).toBe(60);
    expect(sum.audioAgeMs.drift).toBe(45);
    expect(sum.errored).toBe(false);
    expect(sum.players.max).toBe(2);

    const errored = summarizeServerSeries([{ t: 0, players: 1, error: 'Emulator exited', audioAgeP50: 10 }]);
    expect(errored.errored).toBe(true);
  });

  test('evaluate passes a healthy 2-client window', () => {
    const good = summarizeClientSeries([
      { t: 0, fps: 60, pktLostD: 0, jitterBufMs: 25, pairRttMs: 4, freezes: 0, kbps: 1800 },
      { t: 5, fps: 60, pktLostD: 0, jitterBufMs: 28, pairRttMs: 5, freezes: 0, kbps: 1800 },
    ]);
    const server = summarizeServerSeries([{ t: 0, players: 2, error: null, audioAgeP50: 15, videoAgeP50: 10 }]);
    const v = evaluate([{ label: 'P1', summary: good }, { label: 'P2', summary: good }], server, 2);
    expect(v.pass).toBe(true);
    expect(v.violations).toEqual([]);
  });

  test('evaluate flags low fps, loss, wrong count, and server error (jitter is not gated)', () => {
    const bad = summarizeClientSeries([
      { t: 0, fps: 20, pktLostD: 5, jitterBufMs: 400, pairRttMs: 9, freezes: 0, kbps: 500 },
    ]);
    const server = summarizeServerSeries([{ t: 0, players: 1, error: 'Pipeline error', audioAgeP50: 15 }]);
    const v = evaluate([{ label: 'P1', summary: bad }], server, 2, DEFAULT_THRESHOLDS);
    expect(v.pass).toBe(false);
    expect(v.violations.join(' ')).toContain('median fps');
    expect(v.violations.join(' ')).toContain('median loss');
    expect(v.violations.join(' ')).toContain('expected 2 connected');
    expect(v.violations.join(' ')).toContain('server reported an error');
    // jitterBuf is high (400ms) but must NOT be a violation — it is report-only.
    expect(v.violations.join(' ')).not.toContain('jitterBuf');
  });
});
