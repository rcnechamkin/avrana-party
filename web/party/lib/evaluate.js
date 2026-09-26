// Capability Engine v0, seat evaluation. Mirror of avrana/contracts/evaluate.py:evaluate_seat;
// both run the shared vectors in contracts/vectors/evaluate.v0.json.
//
// game: a catalog entry (web/party/catalog.json). Its presentations already say whether the
//       appliance can serve them ('available'), so only device capabilities are compared here.
// caps: { name: 'yes'|'no'|'partial'|'unknown' } (or { name: { status } }); absent = 'unknown'.
// role: 'player' | 'spectator'.
//
// One seat, one decision: nothing here looks at other seats, so a weak phone only changes its own
// result. 'no' rules a presentation out; 'unknown' and 'partial' keep it as 'limited'.

const STATUSES = new Set(['yes', 'no', 'partial', 'unknown']);

function status(caps, name) {
  let value = caps ? caps[name] : undefined;
  if (value && typeof value === 'object') value = value.status;
  return STATUSES.has(value) ? value : 'unknown';
}

function tryRole(presentations, caps, role) {
  const candidates = presentations.filter((p) => p.available && p.roles.includes(role));
  let bestMissing = null;
  for (const p of candidates) {
    const missing = p.requires.device.filter((c) => status(caps, c) === 'no');
    if (missing.length === 0) return { chosen: p, candidates, missing: [] };
    if (bestMissing === null || missing.length < bestMissing.length) bestMissing = missing;
  }
  return { chosen: null, candidates, missing: bestMissing || [] };
}

const sorted = (list) => [...list].sort();

export function evaluateSeat(game, caps, role = 'player') {
  if (role !== 'player' && role !== 'spectator') throw new Error('role must be player or spectator');
  const presentations = game.presentations;
  let { chosen, candidates, missing } = tryRole(presentations, caps, role);
  let seatRole = role;
  let outcome = null;
  if (!chosen && role === 'player' && game.fallback === 'spectate') {
    const watch = tryRole(presentations, caps, 'spectator').chosen;
    if (watch) {
      chosen = watch;
      seatRole = 'spectator';
      outcome = 'watch';
    }
  }
  if (!chosen) {
    let blockedBy = 'role';
    if (candidates.length) blockedBy = 'device';
    else if (presentations.some((p) => p.roles.includes(role))) blockedBy = 'runtime';
    return {
      role, outcome: 'unavailable', seatRole: null, presentation: null, method: null, blockedBy,
      missing: sorted(missing), unverified: [], partial: [], degraded: [],
    };
  }
  const unverified = sorted(chosen.requires.device.filter((c) => status(caps, c) === 'unknown'));
  const partial = sorted(chosen.requires.device.filter((c) => status(caps, c) === 'partial'));
  const degraded = sorted(chosen.optional.device.filter((c) => status(caps, c) === 'no'));
  if (outcome === null) outcome = unverified.length || partial.length || degraded.length ? 'limited' : 'ready';
  return {
    role, outcome, seatRole, presentation: chosen.id, method: chosen.method, blockedBy: null,
    missing: sorted(missing), unverified, partial, degraded,
  };
}

/**
 * One plain sentence for a guest, or '' when nothing needs saying (silence is success).
 * labels: catalog.labels ({ name: { label, missing } }). Never uses machinery words.
 */
export function explain(result, labels = {}) {
  const missing = (name) => (labels[name] && labels[name].missing) || '';
  const label = (name) => (labels[name] && labels[name].label) || '';
  if (result.outcome === 'ready') return '';
  if (result.outcome === 'watch') {
    const why = result.missing.length ? missing(result.missing[0]) : '';
    return `${why ? `${why} ` : ''}You can watch this one.`.trim();
  }
  if (result.outcome === 'unavailable') {
    if (result.blockedBy === 'device' && result.missing.length) return missing(result.missing[0]);
    if (result.blockedBy === 'role') return 'This game has no room for watchers.';
    return 'This game isn’t available on this Party box right now.';
  }
  if (result.degraded.length) return missing(result.degraded[0]);
  if (result.partial.length) return `Works, but ${label(result.partial[0]) || 'one feature'} is limited on this phone.`;
  return 'Should work. We’ll know for sure when you start.';
}
