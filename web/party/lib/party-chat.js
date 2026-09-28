// Party-wide UI boundary over the legacy ChatHub protocol. Same channel/store,
// same profile token. No durable client message store or second presence model.
import { gazePicture, photoPath } from './profile.js';

export function normalizeMessage(raw) {
  if (!raw || (!Number.isSafeInteger(raw.id) || raw.id < 1)
      || typeof raw.by !== 'string' || typeof raw.text !== 'string') return null;
  return { id: raw.id, by: raw.by.slice(0, 80), name: String(raw.name || 'Player').slice(0, 24),
    avatar: String(raw.avatar || '👤').slice(0, 32), pfp: photoPath(raw.pfp) || gazePicture(raw.pfp),
    text: raw.text.slice(0, 400), photo: Boolean(raw.img), ts: Number(raw.ts) || 0 };
}

export function createPartyChat({ identity, origin, Socket = globalThis.WebSocket, onChange,
  schedule = setTimeout, cancel = clearTimeout }) {
  const url = new URL('/chat/ws', origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  let socket = null, retry = null, heartbeat = null, timeout = null, enabled = false, attempt = 0;
  let state = { status: 'closed', online: 0, messages: [], you: null };
  const emit = () => onChange({ ...state, messages: [...state.messages] });
  function timers() {
    for (const id of [retry, heartbeat, timeout]) if (id !== null) cancel(id);
    retry = heartbeat = timeout = null;
  }
  function disconnect() {
    timers();
    const old = socket; socket = null;
    if (old) old.close();
  }
  function beat(current) {
    heartbeat = schedule(() => {
      if (socket !== current || state.status !== 'connected') return;
      current.send(JSON.stringify({ t: 'ping' }));
      beat(current);
    }, 25000);
  }
  function connect() {
    disconnect();
    if (!enabled) return;
    let me;
    try { me = identity(); } catch { state.status = 'profile_required'; emit(); return; }
    state = { ...state, status: 'connecting', online: 0 }; emit();
    let current;
    try { current = new Socket(url.href); }
    catch { lost(); return; }
    socket = current;
    current.onopen = () => {
      if (socket !== current) return;
      current.send(JSON.stringify({ t: 'hello', token: me.token, name: me.name, avatar: me.avatar }));
    };
    // A connected TCP socket without a ChatHub welcome is not a working chat.
    timeout = schedule(() => { if (socket === current && state.status !== 'connected') current.close(); }, 12000);
    current.onmessage = (event) => {
      if (socket !== current || typeof event.data !== 'string' || event.data.length > 262144) return;
      let msg; try { msg = JSON.parse(event.data); } catch { return; }
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'welcome' && typeof msg.you === 'string') {
        state.status = 'connected'; state.you = msg.you; attempt = 0;
        cancel(timeout); timeout = null; beat(current);
      } else if (msg.type === 'history' && Array.isArray(msg.messages)) {
        state.messages = msg.messages.slice(-60).map(normalizeMessage).filter(Boolean);
      } else if (msg.type === 'msg') {
        const item = normalizeMessage(msg);
        if (item && !state.messages.some((m) => m.id === item.id))
          state.messages = [...state.messages, item].slice(-60);
      } else if (msg.type === 'presence' && Number.isInteger(msg.online) && msg.online >= 0) {
        state.online = msg.online;
      } else if (msg.type === 'cleared') {
        state.messages = [];
      } else return;
      emit();
    };
    current.onerror = () => { if (socket === current) current.close(); };
    current.onclose = () => { if (socket === current) lost(); };
  }
  function lost() {
    disconnect();
    state = { ...state, status: 'unavailable', online: 0 }; emit();
    if (enabled) retry = schedule(connect, Math.min(5000, 600 + attempt++ * 700));
  }
  return {
    open() { if (enabled) return false; enabled = true; connect(); return true; },
    close() { enabled = false; disconnect(); state = { ...state, status: 'closed', online: 0, messages: [] }; emit(); },
    reconnect() { if (enabled) connect(); },
    send(text) {
      const clean = String(text).trim().slice(0, 400);
      if (!clean || !socket || state.status !== 'connected') return false;
      socket.send(JSON.stringify({ t: 'msg', text: clean }));
      return true; // Server echo is the sole new-message source.
    },
  };
}
