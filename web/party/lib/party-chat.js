// The Party room on Party pages (AVR-54, docs/design/MESSAGING.md): one long poll of
// /party/api/messages and a send. Party Core is the only source of a line: who wrote it, its
// order and its words. The device cookie is the only identity; this module sends no name, id or
// token, and never shows a line it did not receive. Pure: fetch, timers and storage are passed in.
//
// A phone keeps the Party id and a cursor (the highest seq it holds). Lines are merged by seq, so
// a reconnect or a repeated answer never doubles one. Unread is counted here, from the highest seq
// this phone has shown in an open drawer; Party Core keeps no read state.

export const WAIT_S = 20;                 // long-poll wait; Party Core caps it at 25 s
export const KEEP = 80;                   // lines held: Core's 60 people + 20 system lines
export const TEXT_MAX = 400;              // code points, counted as Party Core counts them
const RETRY_MS = [1000, 2000, 5000];
const SEEN_KEY = 'avrana-chat-seen';      // {party, seq}: what this tab has shown

/** Code points, as Party Core counts them (an emoji is one, not two). */
export const length = (text) => [...String(text)].length;

/** A line as the shell may draw it, or null. Anything Party Core did not build is dropped. */
export function readLine(raw) {
  if (!raw || typeof raw !== 'object' || !Number.isSafeInteger(raw.seq) || raw.seq < 1) return null;
  if (typeof raw.from !== 'string' || typeof raw.name !== 'string') return null;
  const base = { seq: raw.seq, from: raw.from, name: raw.name.slice(0, 32),
    avatar: typeof raw.avatar === 'string' && /^gaze-\d\d$/.test(raw.avatar) ? raw.avatar : null,
    age: Number.isFinite(raw.age_ms) && raw.age_ms >= 0 ? raw.age_ms : 0 };
  if (raw.kind === 'member' && typeof raw.text === 'string')
    return { ...base, kind: 'member', text: raw.text.slice(0, TEXT_MAX * 2) };
  if (raw.kind === 'system' && SYSTEM_EVENTS.includes(raw.event))
    return { ...base, kind: 'system', event: raw.event,
      was: typeof raw.was === 'string' ? raw.was.slice(0, 32) : null,
      game: typeof raw.game === 'string' ? raw.game.slice(0, 64) : null,
      outcome: typeof raw.outcome === 'string' ? raw.outcome : null,
      more: Number.isSafeInteger(raw.more) && raw.more > 0 ? raw.more : 0 };
  return null;
}

export const SYSTEM_EVENTS = ['joined', 'returned', 'left', 'host', 'renamed', 'round_started', 'round_ended'];

/** A system line's words. Built here from a closed list of events: never text from anyone. */
export function systemText(line, gameName = (id) => id) {
  const n = line.name;
  const game = line.game ? gameName(line.game) : 'the game';
  const said = {
    joined: `${n} joined the Party`, returned: `${n} is back`, left: `${n} left the Party`,
    host: `${n} is hosting now`, renamed: line.was ? `${line.was} is now ${n}` : `${n} changed their name`,
    round_started: `${game} started`,
    round_ended: line.outcome === 'abandoned' ? `${game} stopped` : `${game} ended`,
  }[line.event];
  if (!line.more) return said;
  return `${said}, and ${line.more} more ${line.more === 1 ? 'change' : 'changes'}`;
}

/** Merge lines into a list held in seq order, without doubles, keeping the last KEEP. */
export function merge(held, lines) {
  const bySeq = new Map(held.map((l) => [l.seq, l]));
  for (const l of lines) if (l && !bySeq.has(l.seq)) bySeq.set(l.seq, l);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-KEEP);
}

/** Other people's words above what this phone has shown. */
export const unread = (lines, seen, me) =>
  lines.filter((l) => l.kind === 'member' && l.seq > seen && l.from !== me).length;

/** A client_id: 1 to 36 of A-Z a-z 0-9 _ -, fresh for each message. */
export function clientId(random = globalThis.crypto) {
  if (random && typeof random.randomUUID === 'function') return random.randomUUID();
  return `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export function createPartyChat({ fetch = globalThis.fetch.bind(globalThis), base = 'api/', onChange,
  storage = null, schedule = setTimeout, cancel = clearTimeout, newId = clientId } = {}) {
  let gen = 0, poll = null, wake = null;
  let party = null, me = null, cursor = 0, seen = 0;
  let state = { status: 'closed', party: null, messages: [], gap: false, unread: 0 };

  function loadSeen() {
    try {
      const kept = JSON.parse(storage && storage.getItem(SEEN_KEY));
      return kept && kept.party === party && Number.isSafeInteger(kept.seq) ? kept.seq : 0;
    } catch { return 0; }
  }
  function saveSeen() {
    try { if (storage) storage.setItem(SEEN_KEY, JSON.stringify({ party, seq: seen })); } catch { /* kept nowhere */ }
  }
  function emit(patch = {}) {
    state = { ...state, ...patch, party };
    state.unread = unread(state.messages, seen, me);
    onChange({ ...state, messages: [...state.messages] });
  }
  /** A new Party (it ended, or Party Core restarted): nothing from the old room is kept. */
  function adopt(id) {
    if (id === party) return;
    party = id; cursor = 0;
    seen = loadSeen();
    state = { ...state, messages: [], gap: false };
  }

  const sleep = (ms) => new Promise((resolve) => {
    const timer = schedule(() => { wake = null; resolve(); }, ms);
    wake = () => { cancel(timer); wake = null; resolve(); };
  });

  async function loop(g) {
    let failures = 0, first = true;
    while (g === gen) {
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const current = { ctl, poked: false };
      poll = current;
      const timer = schedule(() => ctl && ctl.abort(), (WAIT_S + 10) * 1000);
      let res = null, body = null;
      try {
        const wait = first || failures ? 0 : WAIT_S;
        res = await fetch(`${base}messages?party=${encodeURIComponent(party || '-')}&after=${cursor}&wait=${wait}`,
          { cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined });
        body = await res.json().catch(() => null);
      } catch { /* aborted, offline, or the Pi is restarting */ }
      cancel(timer);
      if (g !== gen) return;
      if (res && res.ok && body && typeof body.party === 'string' && Array.isArray(body.messages)) {
        failures = 0; first = false;
        const before = cursor;
        adopt(body.party);
        const lines = body.messages.map(readLine).filter(Boolean);
        const messages = merge(state.messages, lines);
        // Away longer than the room holds: the earliest line still held is past what we had.
        const gap = state.gap || (before > 0 && Number.isSafeInteger(body.first) && body.first > before + 1);
        if (Number.isSafeInteger(body.last) && body.last >= cursor) cursor = body.last;
        emit({ status: 'connected', messages, gap });
        const retry = Number.isFinite(body.retry_ms) ? Math.min(Math.max(body.retry_ms, 0), 30000) : 0;
        if (retry && !current.poked) await sleep(retry);
      } else if (res && res.status === 403) {
        // Not a member of this Party (yet, or any more): the page joins as it already does,
        // then opens the room again. Nothing is retried in a loop.
        gen++;
        party = null; cursor = 0;
        emit({ status: 'not_member', messages: [], gap: false });
        return;
      } else if (!current.poked) {
        emit({ status: 'unavailable' });
        await sleep(RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]);
      }
    }
  }

  function poke() {
    const current = poll;
    if (current) { current.poked = true; if (current.ctl) current.ctl.abort(); }
    if (wake) wake();
  }

  async function post(body) {
    try {
      const res = await fetch(`${base}messages`, { method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      let data = null;
      try { data = await res.json(); } catch { /* not JSON */ }
      return { ok: res.ok, status: res.status, body: data };
    } catch {
      return { ok: false, status: 0, body: null };
    }
  }

  return {
    state: () => state,
    /** Start reading the room of this Party as this member (from the Party view). Reading goes
     * on while the drawer is closed: that is how unread is counted. Calling it again with the
     * same Party and member does nothing. */
    open(partyId, memberId) {
      if (!partyId || !memberId) return false;
      if (state.status !== 'closed' && state.status !== 'not_member' && party === partyId && me === memberId) return false;
      gen++; poke();
      me = memberId;
      adopt(partyId);
      emit({ status: 'connecting' });
      loop(gen);
      return true;
    },
    close() {
      gen++; poke();
      party = null; me = null; cursor = 0;
      emit({ status: 'closed', messages: [], gap: false });
    },
    /** Ask again at once (the phone woke, the network came back). */
    poke,
    /** Everything drawn so far has been seen (the drawer is open on its Chat side). */
    markSeen() {
      const top = state.messages.length ? state.messages[state.messages.length - 1].seq : 0;
      if (top <= seen) return;
      seen = top; saveSeen(); emit();
    },
    /** Send a line. Resolves { ok } or { ok: false, error, message, retry_ms }. A lost answer is
     * retried once with the same client_id, so it can never land twice. */
    async send(text) {
      const clean = String(text).trim();
      if (!clean) return { ok: false, error: 'empty', message: 'Type a message.' };
      if (length(clean) > TEXT_MAX) return { ok: false, error: 'too_long', message: `Messages are at most ${TEXT_MAX} characters.` };
      if (!party || state.status === 'closed' || state.status === 'not_member')
        return { ok: false, error: 'not_connected', message: 'Chat is not connected yet. Please try again.' };
      const body = { party, text: clean, client_id: newId() };
      let res = await post(body);
      if (res.status === 0) res = await post(body);
      if (res.ok && res.body && res.body.message) {
        const line = readLine(res.body.message);
        if (line && res.body.party === party) emit({ messages: merge(state.messages, [line]) });
        poke();
        return { ok: true };
      }
      const b = res.body || {};
      const said = { too_fast: 'Slow down a little, then send again.', bad_party: 'The Party changed. Your message was not sent.',
        not_member: 'Join the Party to chat.', empty: 'Type a message.', too_long: `Messages are at most ${TEXT_MAX} characters.` };
      if (b.error === 'bad_party' || res.status === 403) poke();
      return { ok: false, error: b.error || 'offline', retry_ms: b.retry_ms || 0,
        message: said[b.error] || (res.status === 0 ? 'Not connected. Your message was not sent.' : 'Your message was not sent. Please try again.') };
    },
  };
}
