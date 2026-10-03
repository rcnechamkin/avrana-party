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
