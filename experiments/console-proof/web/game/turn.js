// Turn-based fixture: the server owns the turn timer; a hand is private to its seat.
import { connect, focusStage, probe } from './common.js';

const $ = (id) => document.getElementById(id);
let st = null, you = null;
const net = connect('turn', (msg) => {
  if (msg.type === 'welcome') you = msg.you;
  if (msg.type === 'welcome' || msg.type === 'role') {
    $('status').textContent = msg.role === 'player' ? 'You are playing.' : 'You are watching.';
    if (msg.role !== 'player') $('hand').replaceChildren();     // a spectator shows no hand, ever
  }
  if (msg.type === 'state') { st = msg; probe.deadline = msg.deadline; probe.turnNo = msg.turnNo; $('turn-no').textContent = msg.turnNo; $('whose').textContent = msg.turn === you ? 'your turn' : 'their turn'; $('log').replaceChildren(...msg.log.map((l) => Object.assign(document.createElement('li'), { textContent: l }))); }
  if (msg.type === 'hand' && probe.role === 'player') {
    $('hand').replaceChildren(...msg.cards.map((c) => { const li = document.createElement('li'); const b = document.createElement('button'); b.textContent = 'Play ' + c; b.dataset.card = c; b.onclick = () => net.send({ type: 'play', card: c }); li.append(b); return li; }));
  }
});
// The countdown is drawn from the server's deadline and the server clock offset, never a local timer of its own.
setInterval(() => { if (!st) return; const left = Math.max(0, Math.round((st.deadline - (Date.now() + (probe.serverOffset || 0))) / 1000)); $('left').textContent = left; probe.shownLeft = left; }, 200);
focusStage();
