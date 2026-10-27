// Which picture a game's art draws (AVR-466, experimental). Pure: no DOM, no network.
//
// A package has up to three pictures with three jobs: the cover (1:1, a tile), the icon (1:1, small) and the
// banner (16:9, a wide hero). Which one a place draws depends on the place, not on the phone, so the caller
// names its CONTEXT and, for a hero, whether its box is wide. First usable rung wins; the owner's cover always
// leads (the owner chose it, AVR-306); the title's own art and the kind icon always close the ladder:
//
//   tile, rail   own -> package cover -> package icon -> own art -> kind icon     (square and 3:4 boxes)
//   row          own -> package icon -> package cover -> own art -> kind icon     (4 rem, a list row)
//   hero, wide   own wide -> own -> package banner -> package cover -> package icon -> own art -> kind icon
//   hero, narrow own -> package cover -> package banner (whole) -> package icon -> own art -> kind icon
//
// The owner's wide cover (AVR-308) is drawn only in a wide hero, where it fills the box like a banner; anywhere
// else the owner's square cover leads as before.
// A banner is never cut into a square or a 3:4: a tile, a rail and a row do not use it. In a narrow hero (a
// phone held upright) it is the last picture that is not an icon, and is drawn whole rather than cropped.
// A rung whose picture failed to load (its address is in `failed`) is skipped, so a 404 where nginx does not
// serve /party/pkgart/ yet, or a picture this phone cannot draw, falls through to the next rung and never
// leaves a broken image. docs/design/AVRGAME-PACKAGE.md (Shell), docs/UI-DESIGN-SYSTEM.md (Game artwork).

// The only shape of a package picture address: the catalog's `images` field is appliance-set, but the shell
// still takes nothing else, and only for the game it was listed under.
const PACKAGE_URL = /^\/party\/pkgart\/([a-z][a-z0-9_-]{0,39})\/[0-9a-f]{16}\.(webp|png|jpg)$/;
const SIDE = /^[1-9][0-9]{0,3}$/;
export const ROLES = ['cover', 'icon', 'banner'];

// A hero's box is wide when its width over its height reaches WIDE_AT: there a 16:9 banner shows at least
// ~73% of its width and a square cover only ~77% of its height, so the banner (made for a wide box) is the
// better picture; below it, a banner would lose more than a quarter of its width. A box that is wide stays
// wide until it falls under NARROW_AT, so a stage that grows a line of text (200% text, a long name) does not
// swap its picture back and forth.
export const WIDE_AT = 1.3;
export const NARROW_AT = 1.2;

/** Is a hero box of this width / height wide? `was`: whether it was wide a moment ago. An aspect that cannot
 * be measured (a hidden box, 0 by 0) keeps the answer it had. */
export function heroIsWide(aspect, was = false) {
  if (typeof aspect !== 'number' || !Number.isFinite(aspect) || aspect <= 0) return was;
  return aspect >= (was ? NARROW_AT : WIDE_AT);
}

/** The context a cover's `shape` (and `small`) stands for: 'hero' (Home's stage, the briefing's, a game's
 * page), 'rail' (3:4), 'row' (a list row) or 'tile' (square). */
export function contextOf(shape = '', small = false) {
  if (shape === 'stage' || shape === 'wide') return 'hero';
  if (shape === 'tall') return 'rail';
  return small ? 'row' : 'tile';
}

/** {src, w, h} for a package's picture of this role ('cover' | 'icon' | 'banner'), or null when the game has
 * none or the entry is not exactly what the appliance writes. */
export function packageImage(game, role) {
  const entry = ROLES.includes(role) && game && game.images && typeof game.images === 'object' ? game.images[role] : null;
  if (!entry || typeof entry !== 'object' || typeof entry.url !== 'string') return null;
  const match = PACKAGE_URL.exec(entry.url);
  if (!match || match[1] !== game.id) return null;
  const sized = SIDE.test(String(entry.w)) && SIDE.test(String(entry.h));
  return { src: entry.url, w: sized ? Number(entry.w) : null, h: sized ? Number(entry.h) : null };
}

const PACKAGE_ORDER = {
  tile: ['cover', 'icon'],
  rail: ['cover', 'icon'],
  row: ['icon', 'cover'],
};

/** The rungs for a game in a context, best first, ending with the kind icon (`kind: 'icon'`, no `src`).
 * `own`: the owner's cover path or null; `ownWide`: the owner's wide cover path or null (used only in a wide hero);
 * `art`: the title's own art path (already checked) or null;
 * `wide`: for a hero, whether its box is wide (heroIsWide). A package banner's rung says how to draw it:
 * `fit: 'bleed'` fills a wide box, `fit: 'whole'` shows it uncropped in a narrow one. */
export function artRungs(game, context = 'tile', { own = null, ownWide = null, art = null, wide = false } = {}) {
  const rungs = [];
  if (ownWide && context === 'hero' && wide) rungs.push({ kind: 'own-wide', src: ownWide, w: null, h: null, fit: 'bleed' });
  if (own) rungs.push({ kind: 'own', src: own, w: null, h: null });
  const order = context === 'hero' ? (wide ? ['banner', 'cover', 'icon'] : ['cover', 'banner', 'icon'])
    : PACKAGE_ORDER[context] || PACKAGE_ORDER.tile;
  for (const role of order) {
    const picture = packageImage(game, role);
    if (picture) rungs.push({ kind: 'package-' + role, ...picture, ...(role === 'banner' ? { fit: wide ? 'bleed' : 'whole' } : {}) });
  }
  if (art) rungs.push({ kind: 'art', src: art, w: null, h: null });
  rungs.push({ kind: 'icon', src: null, w: null, h: null });
  return rungs;
}

/** The rung to draw: the first whose picture has not failed. Always returns one (the kind icon is last). */
export function pickArt(game, context, options = {}, failed = new Set()) {
  const rungs = artRungs(game, context, options);
  return rungs.find((rung) => !rung.src || !failed.has(rung.src)) || rungs[rungs.length - 1];
}

/** The ladder for a square tile, or a list row with `small` (the callers that predate contexts). */
export function coverRungs(game, { small = false, context = '', ...options } = {}) {
  return artRungs(game, context || (small ? 'row' : 'tile'), options);
}

export function pickCover(game, options = {}, failed = new Set()) {
  const rungs = coverRungs(game, options);
  return rungs.find((rung) => !rung.src || !failed.has(rung.src)) || rungs[rungs.length - 1];
}
