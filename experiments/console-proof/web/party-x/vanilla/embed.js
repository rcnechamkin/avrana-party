import { hydrateIcons } from '/party/lib/icons.js';
import { GAME_ORIGIN, LAYER_PROTOCOL, api, parseTicketRequest } from '/party/x/shared/rules.js';

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);
const hide = ['display', 'visibility', 'offscreen'].includes(q.get('hide')) ? q.get('hide') : 'occlude';
const game = q.get('game') === 'turn' ? 'turn' : 'rt';
const frame = $('game');
frame.src = `${GAME_ORIGIN}/${game}.html?embed=1&fw=vanilla&s=M`;
addEventListener('message', async (ev) => {
  if (ev.origin !== GAME_ORIGIN || ev.source !== frame.contentWindow) return;
  const req = parseTicketRequest(ev.data);
  if (!req) return;
  const body = await api('/api/ticket', { game });
  frame.contentWindow.postMessage(body ? { avrana: LAYER_PROTOCOL, type: 'ticket', id: req.id, ticket: body.ticket, role: body.role }
    : { avrana: LAYER_PROTOCOL, type: 'ticket-error', id: req.id, error: 'unavailable' }, GAME_ORIGIN);
});
function setOpen(open) {
  $('console').hidden = !open;
  frame.className = open && hide !== 'occlude' ? `hide-${hide}` : '';
  if (open) $('back-to-game').focus(); else frame.focus();
}
$('open').addEventListener('click', () => setOpen(true));
$('back-to-game').addEventListener('click', () => setOpen(false));
addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('console').hidden) setOpen(false); });
hydrateIcons();
