// Loading the game catalog must never take Party Home down (AVR-220). A missing, non-2xx or
// corrupt catalog.json becomes an empty catalog plus ok:false, so the page can say so and offer
// Retry while party-follow and navigation keep working.

/** Pure: a parsed catalog body -> { catalog, ok }. Anything that is not a catalog is empty. */
export function normalizeCatalog(body) {
  if (!body || typeof body !== 'object' || !Array.isArray(body.games)) return { catalog: { games: [], labels: {} }, ok: false };
  return { catalog: body, ok: true };
}

/** Fetch and validate catalog.json; never throws. */
export async function loadCatalog(fetchFn, url = 'catalog.json') {
  try {
    const res = await fetchFn(url);
    if (!res.ok) return normalizeCatalog(null);
    return normalizeCatalog(await res.json());
  } catch {
    return normalizeCatalog(null);
  }
}

// The owner's game covers (AVR-306): covers/index.json says which games have one. It is written
// by the build and by the dev server from the files that passed their checks, so the page never
// asks for a cover that is not there. Nothing about a cover is ever required: any failure here is
// "no covers".
const COVER = /^covers\/([a-z][a-z0-9_-]{0,39})\.(jpg|jpeg|png|webp|avif)$/;

/** Pure: a parsed covers/index.json -> Map(game id -> path). An entry is kept only when its
 * path is a cover's path and is named for that game. */
export function normalizeCovers(body) {
  const covers = new Map();
  if (!body || typeof body !== 'object' || !body.covers || typeof body.covers !== 'object') return covers;
  for (const [id, path] of Object.entries(body.covers)) {
    const match = typeof path === 'string' ? COVER.exec(path) : null;
    if (match && match[1] === id) covers.set(id, path);
  }
  return covers;
}

// A game's optional wide cover for the wide frame of its page (AVR-308): covers/<id>.wide.<ext>, listed
// under "wide" in the same index. An index without the key has none.
const WIDE_COVER = /^covers\/([a-z][a-z0-9_-]{0,39})\.wide\.(jpg|jpeg|png|webp|avif)$/;

/** Pure: a parsed covers/index.json -> Map(game id -> wide cover path), kept by the same rule as the covers. */
export function normalizeWideCovers(body) {
  const wide = new Map();
  if (!body || typeof body !== 'object' || !body.wide || typeof body.wide !== 'object') return wide;
  for (const [id, path] of Object.entries(body.wide)) {
    const match = typeof path === 'string' ? WIDE_COVER.exec(path) : null;
    if (match && match[1] === id) wide.set(id, path);
  }
  return wide;
}

/** Fetch covers/index.json once: {covers, wide}, two Maps; never throws. */
export async function loadCoverIndex(fetchFn, url = 'covers/index.json') {
  try {
    const res = await fetchFn(url);
    if (!res.ok) return { covers: new Map(), wide: new Map() };
    const body = await res.json();
    return { covers: normalizeCovers(body), wide: normalizeWideCovers(body) };
  } catch {
    return { covers: new Map(), wide: new Map() };
  }
}

/** Fetch covers/index.json; never throws. The square covers only (loadCoverIndex has both). */
export async function loadCovers(fetchFn, url = 'covers/index.json') {
  return (await loadCoverIndex(fetchFn, url)).covers;
}
