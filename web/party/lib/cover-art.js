// Which picture a game's cover draws (AVR-466 phase C, experimental). Pure: no DOM, no network.
//
// The ladder, first that is usable wins:
//   the owner's cover -> the package's cover -> the package's icon -> the title's own art -> the kind icon.
// A list row prefers the package's icon to its cover (`small`). A rung whose picture failed to load (its
// address is in `failed`) is skipped, so a 404 where nginx does not serve /party/pkgart/ yet, or a
// picture this phone cannot draw, falls through to the next rung and never leaves a broken image.
// docs/design/AVRGAME-PACKAGE.md (Shell), docs/UI-DESIGN-SYSTEM.md (Game artwork).

// The only shape of a package picture address: the catalog's `images` field is appliance-set, but the shell
// still takes nothing else, and only for the game it was listed under.
const PACKAGE_URL = /^\/party\/pkgart\/([a-z][a-z0-9_-]{0,39})\/[0-9a-f]{16}\.(webp|png|jpg)$/;
const SIDE = /^[1-9][0-9]{0,3}$/;

/** {src, w, h} for a package's picture of this role ('cover' | 'icon'), or null when the game has none
 * or the entry is not exactly what the appliance writes. */
export function packageImage(game, role) {
  const entry = game && game.images && typeof game.images === 'object' ? game.images[role] : null;
  if (!entry || typeof entry !== 'object' || typeof entry.url !== 'string') return null;
  const match = PACKAGE_URL.exec(entry.url);
  if (!match || match[1] !== game.id) return null;
  const sized = SIDE.test(String(entry.w)) && SIDE.test(String(entry.h));
  return { src: entry.url, w: sized ? Number(entry.w) : null, h: sized ? Number(entry.h) : null };
}

/** The rungs for a game, best first, ending with the kind icon (`kind: 'icon'`, no `src`).
 * `own`: the owner's cover path or null; `art`: the title's own art path (already checked) or null;
 * `small`: a list row. */
export function coverRungs(game, { own = null, art = null, small = false } = {}) {
  const rungs = [];
  if (own) rungs.push({ kind: 'own', src: own, w: null, h: null });
  const cover = packageImage(game, 'cover');
  const icon = packageImage(game, 'icon');
  for (const [kind, picture] of small ? [['package-icon', icon], ['package-cover', cover]] : [['package-cover', cover], ['package-icon', icon]]) {
    if (picture) rungs.push({ kind, ...picture });
  }
  if (art) rungs.push({ kind: 'art', src: art, w: null, h: null });
  rungs.push({ kind: 'icon', src: null, w: null, h: null });
  return rungs;
}

/** The rung to draw: the first whose picture has not failed. Always returns one (the kind icon is last). */
export function pickCover(game, options = {}, failed = new Set()) {
  const rungs = coverRungs(game, options);
  return rungs.find((rung) => !rung.src || !failed.has(rung.src)) || rungs[rungs.length - 1];
}
