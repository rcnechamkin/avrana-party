// The frame of the Party shell: which of its four places is on screen, and the words that say who
// is here. Pure: no DOM, no network, no storage.
//
// The places (Home, Party, Library, Me: Concept K, AVR-707) are views of one document, chosen by
// the address's fragment. They are only ever on screen while the party itself is home: where the
// party is comes from Party Core (lib/party-mode.js), and that always wins over the address.

export const PAGES = ['home', 'party', 'library', 'me'];
const TITLES = { home: 'Avrana Party', party: 'Party', library: 'Library', me: 'Me' };
/** Older addresses that name a place by another word: System became Me (its settings live there). */
const ALIASES = { system: 'me' };

/** The place a fragment names; anything else (none, an old link, a typo) is Home. */
export function pageOf(hash) {
  const name = String(hash || '').replace(/^#/, '');
  const page = ALIASES[name] || name;
  return PAGES.includes(page) ? page : 'home';
}

export const pageTitle = (page) => TITLES[page] || TITLES.home;

/** The game a fragment names ("#game/bluff"), or null. Only its shape is checked here: whether
 * such a title is on the shelf is the catalog's to say. A game's page is a fifth view of the same
 * document. It is browsing: it is not a place in the bar, and nothing on it moves the Party but
 * the Host's own button. */
export function gameOf(hash) {
  const found = /^#?game\/([A-Za-z0-9][A-Za-z0-9_-]{0,63})$/.exec(String(hash || ''));
  return found ? found[1] : null;
}

/** Where a game's page goes back to, in a word: the place it was opened from. */
export const backWord = (page) => (page === 'home' ? 'Home' : pageTitle(PAGES.includes(page) ? page : 'library'));

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

/** Who picks the games, for this phone. `me` and `host` are members (or null); `away`: Party
 * Core says the Host is away (lib/states.js awayHost). */
export function hostLine(me, host, away = false) {
  if (!me) return '';
  if (me.host) return 'You’re the host. Pick a game in the Library and everyone goes there together.';
  if (!host) return 'Nobody is hosting right now.';
  return away ? `${host.name} is the host, and is away.` : `${host.name} is the host and picks the games.`;
}

/** Is the Party room on offer? It is Party Core's (AVR-54), so it is there whenever this phone
 * is a member of the Party, whatever else is running. Never when the Pi is out of reach. */
export function chatOffered({ reachable, member } = {}) {
  return Boolean(reachable) && Boolean(member);
}

/** Which side of the drawer to open: the one asked for when it exists, else chat, else people;
 * null when there is nothing to open. */
export function startTab({ party, chat, want } = {}) {
  const has = { people: Boolean(party), chat: Boolean(chat) };
  if (want && has[want]) return want;
  return has.chat ? 'chat' : has.people ? 'people' : null;
}

/** The compact presence row (Concept K): how many are here as a number, and who is away by name
 * ("4 here", "4 here · Riley away", "12 here · 2 away"). Away is said in words, never by a dimmed
 * face alone. */
export function presenceLine(people) {
  const list = Array.isArray(people) ? people : [];
  const away = list.filter((m) => m.away);
  const gone = away.length === 1 ? ` · ${away[0].name} away` : away.length ? ` · ${away.length} away` : '';
  return `${list.length} here${gone}`;
}

/** The presence row's name for a screen reader and for voice control: the words it shows (who is
 * away included), then what it opens. */
export function presenceLabel(people, { host = false } = {}) {
  return `${presenceLine(people)}${host ? ' · You host' : ''}. Open people`;
}

/** The Party tab's name for a screen reader: its word, and what is new in the Party's chat (the
 * badge on its icon says the same as a number). */
export function partyTabLabel(unread = 0) {
  return unread > 0 ? `Party, ${unread === 1 ? '1 new message' : `${unread} new messages`}` : 'Party';
}

/** The unread mark on the Party tab: a count, capped so it stays one small badge. */
export const unreadMark = (n) => (n > 0 ? (n > 9 ? '9+' : String(n)) : '');
