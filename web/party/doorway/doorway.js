// The doorway page: decide once, then leave. See ../lib/doorway.js.
import { chooseMode, targets } from '../lib/doorway.js';

const to = targets(document.documentElement.dataset);
if (to) {
  const mode = await chooseMode({ full: to.full });
  document.documentElement.dataset.mode = mode;
  document.getElementById('doorway-text').textContent = mode === 'full'
    ? 'Opening your party…' : 'Opening your party in Limited Mode…';
  location.replace(mode === 'full' ? to.full : to.limited);
} else {
  document.getElementById('doorway-text').textContent = 'This page is not set up. Ask the Party box’s owner.';
}
