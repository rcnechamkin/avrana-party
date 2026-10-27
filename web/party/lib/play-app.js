// play.html's script: PROPOSAL play_shell (AVR-766; draft ADR 0018 revision 3, D5). A phone in a
// round stays on this Party page; the game fills it in a frame on the game's own origin, and the
// Party layer (bridge/layer-mount.js, the same one a game page mounts) floats above it as a
// sibling the game cannot cover.
//
// The page takes no parameter. What it frames is decided the way Party Home decides where a phone
// goes (destination() with Party Core's game origins), from the Party's own answer. Anything else,
// the round over, a switch to a same-origin game, the proposal off, Party Core unreachable for
// good, goes back to Party Home, which decides again.
import { createPartyClient } from './party-client.js';
import { createGameOrigins, gameAddress } from './game-origins.js';
import { destination, locationOf, HOME } from './party-mode.js';
import { loadCatalog } from './catalog-load.js';
import { createKeepAwake } from './keep-awake.js';
import { mountPartyLayer } from '../bridge/layer-mount.js';
import { playShellOn, frameTarget, FRAME_SANDBOX, FRAME_ALLOW } from './play.js';

const frame = document.getElementById('game');
frame.setAttribute('sandbox', FRAME_SANDBOX);
frame.setAttribute('allow', FRAME_ALLOW);
const diag = document.getElementById('play-diag');
const insets = document.getElementById('play-insets');   // padding: env(safe-area-inset-*), read as pixels
const origins = createGameOrigins();
const awake = createKeepAwake({ onChange: (state) => { shown.wake = state; showDiag(); } });
let catalog = null, framed = null, layer = null, layerGame = null, leaving = false;
const shown = { wake: 'off', framed: '' };

const addressOf = (game, entry) => gameAddress({ game, entry, origins: origins.get(), partyOrigin: location.origin });

function home() {
  if (leaving) return;
  leaving = true;
  awake.release();
  location.replace('./');
}

function decide(view) {
  if (leaving || !catalog || !view) return;
  if (!playShellOn(view)) return home();
  const to = destination(view, HOME, catalog, addressOf);
  const url = to && frameTarget(to, location.origin);
  if (!url) return home();
  const game = locationOf(view).game;
  if (url !== framed) {
    framed = url;
    frame.src = url;
    shown.framed = new URL(url).origin;
    showDiag();
  }
  if (game !== layerGame) {          // the layer names the game it floats over
    if (layer) layer.stop();
    layer = mountPartyLayer({ partyOrigin: location.origin, game });
    layerGame = game;
  }
}

const party = createPartyClient({ onView: (view) => { origins.settled().then(() => decide(party.view())); } });

// What the owner reads on the phone for the AVR-766 checks: shown for a few seconds at the top,
// never in the way of a touch (pointer-events: none), and in the console.
function showDiag() {
  const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const cs = getComputedStyle(insets);
  const inset = ['Top', 'Right', 'Bottom', 'Left'].map((s) => Math.round(parseFloat(cs[`padding${s}`]) || 0)).join('/');
  const text = `shell · ${standalone ? 'installed' : 'browser'} · ${innerWidth}×${innerHeight} · insets ${inset} · wake ${shown.wake}`
    + (shown.framed ? ` · ${shown.framed}` : '');
  diag.textContent = text;
  console.info('[play_shell]', text);
}

let fade = null;
function flashDiag() {
  showDiag();
  diag.classList.remove('gone');
  clearTimeout(fade);
  fade = setTimeout(() => diag.classList.add('gone'), 8000);
}

// PROPOSAL fab_panel (AVR-769): when the Party menu closes, the game has the focus again (Escape, Close
// or a tap outside the panel), so a keyboard or a controller is back in the game at once.
document.addEventListener('avrana-party-layer', (e) => {
  const view = party.view();
  if (e.detail && e.detail.open === false && view && (view.proposals || []).includes('fab_panel')) frame.focus({ preventScroll: true });
});

addEventListener('resize', showDiag);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') { party.poke(); flashDiag(); }
});
addEventListener('online', () => party.poke());
addEventListener('pagehide', () => awake.release());

flashDiag();
awake.want();
catalog = (await loadCatalog(fetch)).catalog;     // empty, never null, when catalog.json is missing
const first = await party.probeRetrying();
if (first) party.start(first); else home();          // no Party here for this phone: Party Home says so
