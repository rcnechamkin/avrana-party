// The frame of the Party shell: which of its four places is on screen, and the words that say who
// is here. Pure: no DOM, no network, no storage.
//
// The places (Home, Party, Library, System) are views of one document, chosen by the address's
// fragment. They are only ever on screen while the party itself is home: where the party is comes
// from Party Core (lib/party-mode.js), and that always wins over the address.

export const PAGES = ['home', 'party', 'library', 'system'];
const TITLES = { home: 'Avrana Party', party: 'Party', library: 'Library', system: 'System' };

/** The place a fragment names; anything else (none, an old link, a typo) is Home. */
export function pageOf(hash) {
  const name = String(hash || '').replace(/^#/, '');
  return PAGES.includes(name) ? name : 'home';
}

export const pageTitle = (page) => TITLES[page] || TITLES.home;

const COUNT = ['Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve'];

/** How many people are here, as a sentence. */
export function hereLine(count) {
  if (!(count > 1)) return 'You’re the only one here.';
  return `${COUNT[count - 2] || count} of you are here.`;
}

/** Their names, this phone's first: "Ana (you), Ben and Cleo." Nothing for one person. */
export function namesLine(people) {
  if (!Array.isArray(people) || people.length < 2) return '';
  const names = [...people].sort((a, b) => Number(Boolean(b.me)) - Number(Boolean(a.me)))
    .map((m) => m.name + (m.me ? ' (you)' : ''));
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}.`;
}

/** Who picks the games, for this phone. `me` and `host` are members (or null). */
export function hostLine(me, host) {
  if (!me) return '';
  if (me.host) return 'You’re the host. Pick a game in the Library and everyone goes there together.';
  return host ? `${host.name} is the host and picks the games.` : 'Nobody is hosting right now.';
}

/** Is today's chat on offer? It is served by the old games runtime, which is being retired
 * (ADR 0014), so it may simply not be there: it is offered only while that runtime answers
 * (`hub`), or while a conversation is already connected. Never when the Pi is out of reach. */
export function chatOffered({ reachable, hub, status } = {}) {
  return Boolean(reachable) && (Boolean(hub) || status === 'connected');
}

/** Which side of the drawer to open: the one asked for when it exists, else chat, else people;
 * null when there is nothing to open. */
export function startTab({ party, chat, want } = {}) {
  const has = { people: Boolean(party), chat: Boolean(chat) };
  if (want && has[want]) return want;
  return has.chat ? 'chat' : has.people ? 'people' : null;
}

/** The Party control's name for a screen reader. */
export function hudLabel({ party, count, chat } = {}) {
  if (!party) return chat ? 'Party chat' : '';
  const people = count === 1 ? '1 person' : `${count} people`;
  return `Your Party: ${people} here. Open people${chat ? ' and chat' : ''}`;
}
