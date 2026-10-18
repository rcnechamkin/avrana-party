// The height a phone can actually show, for a drawer that holds a text field. With the software
// keyboard up, iPhone Safari and Android Chrome shrink window.visualViewport but not the layout
// viewport, so 100dvh still counts the keyboard's space. This publishes the visible height as
// --avrana-vvh (px); the CSS falls back to 100dvh until it is set, or where there is no
// visualViewport. It only sets a variable: no layout, focus or scroll is touched here.
export function trackVisibleHeight(win = window) {
  const vv = win.visualViewport;
  if (!vv) return () => {};
  const root = win.document.documentElement;
  const sync = () => root.style.setProperty('--avrana-vvh', `${Math.round(vv.height)}px`);
  sync();
  vv.addEventListener('resize', sync);
  return () => { vv.removeEventListener('resize', sync); root.style.removeProperty('--avrana-vvh'); };
}
