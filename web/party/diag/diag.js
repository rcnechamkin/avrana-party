// Diagnostics for the owner, developers and future agents (https://party.avrana.net/party/diag/).
// Machinery words are fine here and only here. The report is machine-readable and never leaves
// the phone unless someone copies it; it holds no identity, token or user-agent-based decision.

import { probeCapabilities, statuses } from '../lib/capabilities.js';
import { evaluateSeat } from '../lib/evaluate.js';
import { createKeepAwake } from '../lib/keep-awake.js';
import { describeShell, readVersion, registerShell, removeShell } from '../lib/shell.js';
import { hydrateIcons } from '../lib/icons.js';
import { h } from '../lib/ui.js';

const $ = (id) => document.getElementById(id);
const data = { report: null, catalog: null, origin: null, version: null, shell: null, evaluations: [] };
let awake = null;

async function json(url) {
  try {
    const res = await fetch(url, { cache: 'no-store' });
    return res.ok ? await res.json() : { error: `HTTP ${res.status}` };
  } catch (err) {
    return { error: (err && err.name) || 'unreachable' };
  }
}

function cell(text, cls) {
  return h('td', { class: cls, text: text === undefined || text === null ? '' : String(text) });
}

function dl(target, entries) {
  target.replaceChildren(...entries.flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: String(v) })]));
}

function renderCaps() {
  const rows = Object.entries(data.report.caps).map(([name, c]) =>
    h('tr', {}, cell(name), cell(c.status, `s-${c.status}`), cell(c.via), cell(c.note || '')));
  $('caps').tBodies[0].replaceChildren(...rows);
}

function describeResult(r) {
  if (r.outcome === 'unavailable') return `unavailable (${r.blockedBy})`;
  return `${r.outcome} → ${r.presentation} [${r.method}]`;
}

function renderGames() {
  const caps = statuses(data.report);
  data.evaluations = [];
  const rows = (data.catalog && !data.catalog.error ? data.catalog.games : []).map((game) => {
    const player = evaluateSeat(game, caps, 'player');
    const spectator = evaluateSeat(game, caps, 'spectator');
    data.evaluations.push({ game: game.id, installed: game.installed, player, spectator });
    const why = [
      player.missing.length ? `missing: ${player.missing.join(', ')}` : '',
      player.unverified.length ? `unverified: ${player.unverified.join(', ')}` : '',
      player.partial.length ? `partial: ${player.partial.join(', ')}` : '',
      player.degraded.length ? `degraded: ${player.degraded.join(', ')}` : '',
    ].filter(Boolean).join('; ');
    return h('tr', {}, cell(`${game.name}${game.installed ? '' : ' (not installed)'}`),
      cell(describeResult(player), `s-${player.outcome === 'unavailable' ? 'no' : 'yes'}`),
      cell(describeResult(spectator)), cell(why));
  });
  $('games').tBodies[0].replaceChildren(...rows);
}

function renderProviders() {
  const providers = data.catalog && data.catalog.providers ? data.catalog.providers : [];
  $('providers').tBodies[0].replaceChildren(...providers.map((p) =>
    h('tr', {}, cell(p.id), cell(p.kind), cell(p.status), cell(p.offers.join(', ')))));
}

function network(origin) {
  if (!origin || origin.error) return `unknown (${origin ? origin.error : 'no answer'})`;
  if (origin.serverAddr === '10.42.0.1') return 'Party Wi-Fi (10.42.0.1)';
  return `reached the Pi at ${origin.serverAddr} (not the Party Wi-Fi address)`;
}

function renderSummary() {
  const c = data.report.context;
  const v = data.version || {};
  const o = data.origin || {};
  dl($('summary'), [
    ['Page', location.origin + location.pathname],
    ['Secure context', c.secureContext],
    ['Network path', network(o)],
    ['TLS / HTTP', o.error ? '—' : `${o.tls || 'none'} / ${o.http || '?'}`],
    ['Build', `${v.build || '?'}${v.commit ? ` (${String(v.commit).slice(0, 12)})` : ''}`],
    ['Offline copy', data.shell ? `${data.shell.registration}${data.shell.controlled ? ', controlling this page' : ''}` : '…'],
    ['Display', `${c.displayMode}, ${c.orientation}, ${c.viewport.w}×${c.viewport.h} @${c.viewport.dpr}x`],
    ['Visibility / online', `${c.visibility} / ${c.online}`],
    ['Probe', `${data.report.depth} · v${data.report.probeVersion} · ${data.report.probedAt}`],
  ]);
}

function renderShell() {
  const s = data.shell || {};
  dl($('shell'), [
    ['Registration', s.registration || 'none'],
    ['Scope', s.scope || '—'],
    ['Worker state', s.workerState || '—'],
    ['Controls this page', Boolean(s.controlled)],
    ['Caches', (s.caches || []).map((c) => `${c.name} (${c.entries})`).join(', ') || '—'],
  ]);
}

function fullReport() {
  return {
    schema: 'avrana.diagnostics/v0',
    page: location.origin + location.pathname,
    build: data.version,
    origin: data.origin,
    shell: data.shell,
    capabilities: data.report,
    evaluations: data.evaluations,
    appliance: data.catalog && !data.catalog.error
      ? { id: data.catalog.appliance.id, runtime: data.catalog.runtime, providers: data.catalog.providers } : null,
    keepAwake: awake ? awake.state : 'not tested',
  };
}

function renderAll() {
  renderSummary();
  renderCaps();
  renderGames();
  renderProviders();
  renderShell();
  $('report').textContent = JSON.stringify(fullReport(), null, 2);
}

async function refreshShell(registration) {
  const d = await describeShell();
  data.shell = { registration, controlled: d.controlled, scope: d.scope, workerState: d.state,
    caches: d.caches, ...(d.error ? { error: d.error } : {}) };
}

async function boot() {
  $('ua').textContent = navigator.userAgent;
  const [report, catalog, origin, version] = await Promise.all([
    probeCapabilities(), json('../catalog.json'), json('../api/origin.json'), readVersion(),
  ]);
  Object.assign(data, { report, catalog, origin, version });
  renderAll();
  const registered = await registerShell({ version });
  await refreshShell(registered.error ? `${registered.state} (${registered.error})` : registered.state);
  renderAll();
}

$('deep').addEventListener('click', async (event) => {
  event.target.disabled = true;
  event.target.textContent = 'Checking…';
  data.report = await probeCapabilities(globalThis, { deep: true });
  renderAll();
  event.target.textContent = 'Deep checks done';
});

$('awake').addEventListener('click', async () => {
  if (!awake) awake = createKeepAwake({ onChange: (s) => { $('awake-state').textContent = `Keep-awake: ${s}`; } });
  if (awake.state === 'on') {
    await awake.release();
    $('awake').textContent = 'Test keep-awake';
  } else {
    await awake.want();
    $('awake').textContent = awake.state === 'on' ? 'Release keep-awake' : 'Test keep-awake';
  }
  $('awake-state').textContent = `Keep-awake: ${awake.state}`;
  renderAll();
});

$('remove').addEventListener('click', async () => {
  const removed = await removeShell();
  await refreshShell(`removed (${removed.registrations} worker, ${removed.caches} caches)`);
  renderAll();
});

$('copy').addEventListener('click', async () => {
  const text = $('report').textContent;
  try {
    await navigator.clipboard.writeText(text);
    $('copy').textContent = 'Copied';
  } catch {
    const range = document.createRange();
    range.selectNodeContents($('report'));
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    $('copy').textContent = 'Selected: copy it now';
  }
});

hydrateIcons();
boot();
