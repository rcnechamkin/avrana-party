// Realtime fixture: a canvas drawn every animation frame from the latest server tick, input sent
// on keys/taps, and a WebGL canvas whose context loss and restore the probe counts.
import { connect, focusStage, probe } from './common.js';

const stage = document.getElementById('stage'), ctx = stage.getContext('2d');
let latest = { t: 0, dots: {} }, seq = 0;
const net = connect('rt', (msg) => {
  if (msg.type === 'tick') latest = msg;
  if (msg.type === 'welcome' || msg.type === 'role') document.getElementById('status').textContent = msg.role === 'player' ? 'You are playing.' : 'You are watching.';
});
(function draw() {
  ctx.fillStyle = '#121218'; ctx.fillRect(0, 0, stage.width, stage.height);
  ctx.fillStyle = '#ffd84a'; ctx.font = '14px sans-serif'; ctx.fillText(`tick ${latest.t}`, 8, 18);
  for (const [, d] of Object.entries(latest.dots || {})) { ctx.beginPath(); ctx.arc(d.x, d.y, 10, 0, 7); ctx.fill(); ctx.fillText(d.name || '', d.x + 12, d.y); }
  requestAnimationFrame(draw);
})();
const move = (dx, dy) => net.send({ type: 'input', dx, dy, seq: ++seq });
stage.addEventListener('keydown', (e) => {
  const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (d) { e.preventDefault(); move(...d); }
});
for (const b of document.querySelectorAll('[data-d]')) b.addEventListener('click', () => move(...b.dataset.d.split(',').map(Number)));
document.addEventListener('avrana-party-layer', (e) => { probe.inputPaused = e.detail.open; });

// WebGL: count loss and restore; re-create resources on restore (what a real game must do).
const glc = document.getElementById('gl'), gl = glc.getContext('webgl');
function initGl() { if (!gl) return; gl.clearColor(1, 0.85, 0.3, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
glc.addEventListener('webglcontextlost', (e) => { e.preventDefault(); probe.glLost += 1; });
glc.addEventListener('webglcontextrestored', () => { probe.glRestored += 1; initGl(); });
initGl();
probe.loseGl = () => { const x = gl && gl.getExtension('WEBGL_lose_context'); if (!x) return false; x.loseContext(); setTimeout(() => x.restoreContext(), 100); return true; };
focusStage();
