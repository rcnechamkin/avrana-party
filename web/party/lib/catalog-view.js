// Only compiled, validated contracts are presented. The donor API confirms known
// slugs; it cannot inject a URL, grant, capability requirement or new game.
export function donorAvailability(body) {
  if (!body || !Array.isArray(body.games) || !Array.isArray(body.external)) return null;
  const available = new Map();
  for (const row of [...body.games, ...body.external]) {
    if (!row || typeof row.slug !== 'string' || row.hidden) continue;
    available.set(row.slug, {
      running: body.avranaIntegration === 'avrana.lan-launch/v1',
      integration: body.avranaIntegration === 'avrana.lan-launch/v1',
      players: Number.isInteger(row.live?.players) ? row.live.players : null,
      max: null,
    });
  }
  return available;
}
export function visibleGames(catalog) {
  return catalog.games.filter((game) => game.installed || game.status === 'experimental');
}
export function filterGames(games, { query = '', players = 0, view = 'all' }, profile) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  games.forEach((game) => profile.keyFor(game));
  const me = profile.snapshot();
  const filtered = games.filter((g) => {
    const words = [g.name, g.summary, g.category].filter(Boolean).join(' ').toLowerCase();
    if (!terms.every((term) => words.includes(term))) return false;
    if (players && !(g.players.min <= players && players <= g.players.max)) return false;
    if (view === 'favorites' && !me.favorites.includes(profile.keyFor(g))) return false;
    if (view === 'recent' && !me.recent.includes(profile.keyFor(g))) return false;
    return true;
  });
  if (view === 'recent') filtered.sort((a, b) =>
    me.recent.indexOf(profile.keyFor(a)) - me.recent.indexOf(profile.keyFor(b)));
  return filtered;
}

// Only appliance-granted paths are launch authority. Donor support gates activation.
export function launchTarget(game) {
  if (game.provider !== 'lan-games') return game.entry;
  const expected = '/games/' + game.legacySlug + '/';
  if (!game.legacySlug || game.entry !== expected || game.launchTarget !== expected
      || game.integration !== 'avrana.lan-launch/v1') return null;
  return expected + '?avrana=1';
}
