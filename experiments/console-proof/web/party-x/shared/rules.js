// Pure rules both experimental consoles share (vanilla imports this file; the Svelte build bundles
// it). In a real change this would be a web/party/lib module. No DOM.
import { LAYER_PROTOCOL } from '/party/bridge/layer-mount.js';

export { LAYER_PROTOCOL };
export const GAME_ORIGIN = 'http://games.cp.test:8371';
export const LIVE_GAMES = ['rt', 'turn'];
export const TABS = [
  { id: 'home', label: 'Home' }, { id: 'party', label: 'Party' }, { id: 'library', label: 'Library' }, { id: 'me', label: 'Me' },
];
export const FIXTURE_NOTE = 'Preview: fixture data, not a voting backend.';

const keysAre = (o, ...names) => Object.keys(o).sort().join(',') === names.sort().join(',');

/** Where this console runs, from its own address: the layer frame over a game, or a top-level page. */
export function shellOf(loc) {
  const q = new URLSearchParams(loc.search);
  const fw = loc.pathname.includes('/x/svelte/') ? 'svelte' : 'vanilla';
  const strategy = q.get('s') === 'R' ? 'R' : 'M';
  const layer = loc.pathname.endsWith('/layer');
  const game = LIVE_GAMES.includes(q.get('game')) ? q.get('game') : null;
  // Limited Mode stand-in: the game is served same-origin under /g/ (no game origin, no bridge isolation).
  const limited = q.get('limited') === '1';
  return { shell: layer ? 'layer' : 'page', fw, strategy, game, limited, pageOrigin: limited ? loc.origin : GAME_ORIGIN };
}

/** The page's ticket request, checked, or null. */
export function parseTicketRequest(data) {
  if (!data || typeof data !== 'object' || data.avrana !== LAYER_PROTOCOL || data.type !== 'ticket-request') return null;
  return keysAre(data, 'avrana', 'type', 'id') && Number.isInteger(data.id) ? { id: data.id } : null;
}

/** Back to Game: the game page the Party's own location names. Never a URL from a message or the query. */
export function gameUrl(view, fw, strategy, limited = false, partyOrigin = '') {
  const game = view && view.location && view.location.game;
  if (!LIVE_GAMES.includes(game)) return null;
  const base = limited ? `${partyOrigin}/g` : GAME_ORIGIN;
  return `${base}/${game}.html?fw=${fw === 'svelte' ? 'svelte' : 'vanilla'}&s=${strategy === 'R' ? 'R' : 'M'}${limited ? '&limited=1' : ''}`;
}

export function names(list) {
  if (list.length <= 1) return list.join('');
  return `${list.slice(0, -1).join(', ')} and ${list.at(-1)}`;
}
export const approvalLine = (s) => (s.count ? `${s.count} ${s.count === 1 ? 'approval' : 'approvals'}: ${names(s.approvals)}` : 'No approvals yet');
export const gameName = (catalog, id) => ((catalog || []).find((g) => g.id === id) || { name: 'a game' }).name;

export function whereLine(view, catalog) {
  if (!view || !view.location) return '';
  const role = view.role === 'player' ? 'You’re playing' : 'You’re watching';
  return `${role} ${gameName(catalog, view.location.game)}.`;
}

/** A Party notice in words. Notices are typed ({kind, game, ...}); only the Party words them. */
export function attentionText(item, serverNow, catalog) {
  if (item.kind === 'your_turn') return `It’s your turn in ${gameName(catalog, item.game)}: ${Math.max(0, Math.round((item.deadline - serverNow) / 1000))} s left`;
  if (item.kind === 'top_suggestion') return `${item.by} suggested ${gameName(catalog, item.game)} next`;
  return '';
}

export async function api(path, body) {
  try {
    const res = await fetch(path, body === undefined ? { cache: 'no-store', credentials: 'same-origin' }
      : { method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}
