// Small DOM and wording helpers shared by the Party page and the diagnostics page.
// Guest wording only: people, games, playing, watching. No machinery words.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function playersText({ min, max }) {
  if (min === max) return max === 1 ? '1 player' : `${max} players`;
  return `${min}–${max} players`;
}

export function howText(game) {
  const parts = [];
  if (game.input && game.input.model === 'controller_slots') parts.push('your phone is the controller');
  else if (game.input && game.input.model === 'hotseat') parts.push('one controller, taking turns');
  else parts.push('play on your phone');
  if (game.screen === 'tv_required') parts.push('needs the TV');
  if (game.private_player_ui) parts.push('your cards stay private');
  return parts.join(' · ');
}

export function kindIcon(game) {
  if (game.kind === 'emulated') return '🕹️';
  if (game.private_player_ui) return '🃏';
  return '🎲';
}

export function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}
