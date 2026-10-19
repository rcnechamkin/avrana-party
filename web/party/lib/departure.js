// Left-by-choice, as this browser remembers it (AVR-580). Party Core holds the authoritative
// opt-out (`view.departed`: refresh, other tabs and stale pages are refused there). This marker
// covers what Core cannot: a new Party after the Pi restarted, when the device is unknown again
// and an automatic join would otherwise bring a person back who chose to leave. Same browser
// only, kept at the Party origin (the bridge frame shares it with game pages); it is never the
// reason to hide a real membership: a view that has `me` clears it.
export const LEFT_KEY = 'avrana-left-party';

export function createDeparture(storage = (() => { try { return globalThis.localStorage; } catch { return null; } })()) {
  const read = () => { try { return storage ? storage.getItem(LEFT_KEY) === '1' : false; } catch { return false; } };
  const write = (on) => { try { if (storage) { if (on) storage.setItem(LEFT_KEY, '1'); else storage.removeItem(LEFT_KEY); } } catch { /* then Core's answer alone decides */ } };
  return {
    left: read,
    mark: () => write(true),
    clear: () => write(false),
    /** Settle a Party Core view against the marker: `departed` is true for a device that left on
     * purpose (Core says so, or this browser remembers it and Core has no member for it). */
    apply(view) {
      if (!view || typeof view !== 'object') return view;
      if (view.me) { if (read()) write(false); view.departed = false; return view; }
      if (view.departed === true) write(true);
      else if (read()) view.departed = true;
      else view.departed = false;
      return view;
    },
  };
}
