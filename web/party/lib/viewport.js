// The height a phone can actually show, for a drawer that holds a text field. With the software
// keyboard up, iPhone Safari and Android Chrome shrink window.visualViewport but not the layout
// viewport, so 100dvh still counts the keyboard's space. This publishes the visible height as
// --avrana-vvh (px), and how far the phone has panned that region down inside the layout viewport
// (iPhone Safari does, to keep a focused field in view) as --avrana-vvt (px), since a position:fixed
// box stays anchored to the layout viewport. The CSS falls back to 100dvh and 0 until they are set,
// or where there is no visualViewport. It only sets variables: no layout, focus or scroll is touched.
export function trackVisibleHeight(win = window) {
  const vv = win.visualViewport;
  if (!vv) return () => {};
  const root = win.document.documentElement;
  const sync = () => {
    root.style.setProperty('--avrana-vvh', `${Math.round(vv.height)}px`);
    root.style.setProperty('--avrana-vvt', `${Math.round(vv.offsetTop)}px`);
  };
  sync();
  vv.addEventListener('resize', sync);
  vv.addEventListener('scroll', sync);
  return () => {
    vv.removeEventListener('resize', sync); vv.removeEventListener('scroll', sync);
    root.style.removeProperty('--avrana-vvh'); root.style.removeProperty('--avrana-vvt');
  };
}
