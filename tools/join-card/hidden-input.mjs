// Key handling for the join card's hidden password prompt, kept pure so it can be tested without a
// terminal. In raw mode Ctrl-C is just a character: it must cancel, never submit what was typed.

/**
 * Apply one chunk of raw-mode input to the text typed so far.
 * @param {string} value
 * @param {string} chunk
 * @returns {{ value: string, end: null | 'enter' | 'cancel' }}
 */
export function typeKeys(value, chunk) {
  for (const ch of chunk) {
    if (ch === '\u0003') return { value: '', end: 'cancel' };
    if (ch === '\r' || ch === '\n') return { value, end: 'enter' };
    if (ch === '\u007f' || ch === '\b') value = value.slice(0, -1); else value += ch;
  }
  return { value, end: null };
}
