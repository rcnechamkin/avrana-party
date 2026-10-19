#!/usr/bin/env node
// Owner-run, offline: write the printable two-QR join card (AVR-76). See docs/runbooks/join-card.md.
//
//   node tools/join-card/join-card.mjs --ssid "Avrana Party" --out ~/avrana-join-card.html
//   node tools/join-card/join-card.mjs --ssid "Avrana Party" --party-only --out party-link.html
//
// The Wi-Fi password is read from AVRANA_WIFI_PASSWORD or typed at a hidden prompt, never from the
// command line (shell history, process lists). It is never printed, and a card that contains it is
// never written inside this repository.
import { realpathSync, writeFileSync, existsSync } from 'node:fs';
import { basename, dirname, resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { renderCard } from './card.mjs';
import { FULL_MODE_URL, JoinCardError, checkPassword } from './payloads.mjs';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const USAGE = `usage: join-card.mjs --out FILE.html [--ssid NAME] [--party-only] [--party-url URL] [--hidden] [--level L|M|Q|H]
  --ssid        Wi-Fi network name (or AVRANA_WIFI_SSID)
  --party-only  no Wi-Fi QR and no password on the card
  --party-url   ${FULL_MODE_URL} (default) or http://10.42.0.1/
  password      AVRANA_WIFI_PASSWORD, or a hidden prompt when run in a terminal`;

function real(p) {
  // Resolve symlinks on the longest existing prefix, so a link into the repository is caught.
  let head = resolve(p);
  const rest = [];
  while (!existsSync(head) && dirname(head) !== head) { rest.unshift(basename(head)); head = dirname(head); }
  const out = resolve(realpathSync(head), ...rest);
  return process.platform === 'win32' ? out.toLowerCase() : out;
}

function insideRepo(p) {
  const rel = relative(real(REPO), real(p));
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
}

function promptHidden(question) {
  return new Promise((done, fail) => {
    const { stdin, stderr } = process;
    if (!stdin.isTTY) { fail(new JoinCardError('Wi-Fi password is missing: set AVRANA_WIFI_PASSWORD or run in a terminal')); return; }
    stderr.write(question);
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding('utf8');
    let value = '';
    const onData = (chunk) => {
      for (const ch of chunk) {
        if (ch === '\r' || ch === '\n') { finish(); return; }
        if (ch === '\u0003') { finish(); fail(new JoinCardError('cancelled')); return; }
        if (ch === '\u007f' || ch === '\b') value = value.slice(0, -1); else value += ch;
      }
    };
    const finish = () => { stdin.off('data', onData); stdin.setRawMode(false); stdin.pause(); stderr.write('\n'); done(value); };
    stdin.on('data', onData);
  });
}

async function main(argv) {
  const { values } = parseArgs({
    args: argv,
    options: {
      out: { type: 'string' }, ssid: { type: 'string' }, 'party-only': { type: 'boolean', default: false },
      'party-url': { type: 'string', default: FULL_MODE_URL }, hidden: { type: 'boolean', default: false },
      level: { type: 'string', default: 'M' }, help: { type: 'boolean', default: false },
    },
  });
  if (values.help) { console.log(USAGE); return 0; }
  if (!values.out) throw new JoinCardError(`--out is required\n${USAGE}`);
  if (!['L', 'M', 'Q', 'H'].includes(values.level)) throw new JoinCardError('--level must be L, M, Q or H');
  const ssid = values.ssid ?? process.env.AVRANA_WIFI_SSID;
  if (!ssid) throw new JoinCardError('Wi-Fi network name is missing: pass --ssid or set AVRANA_WIFI_SSID');
  const partyOnly = values['party-only'];
  const out = resolve(values.out);
  if (!partyOnly && insideRepo(out)) {
    throw new JoinCardError('refusing to write a card with the Wi-Fi password inside the repository; choose a path outside it');
  }
  let password;
  if (!partyOnly) {
    password = process.env.AVRANA_WIFI_PASSWORD || await promptHidden(`Wi-Fi password for ${ssid}: `);
    checkPassword(password);
  }
  const html = renderCard({
    ssid, password, partyOnly, hidden: values.hidden, partyLink: values['party-url'],
    generatedOn: new Date().toISOString().slice(0, 10), level: values.level,
  });
  writeFileSync(out, html, { mode: 0o600 });
  console.log(`Wrote ${out}`);
  console.log(partyOnly ? 'Party-only card: no Wi-Fi password on it.' : 'It shows the Wi-Fi password: print it, keep it with the box, do not commit or post it.');
  return 0;
}

main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (err) => {
  // Only JoinCardError messages are known to be free of the password; anything else gets a generic line.
  console.error(err instanceof JoinCardError || err?.code?.startsWith?.('ERR_PARSE_ARGS') ? `join-card: ${err.message}` : `join-card: failed (${err?.code || err?.name || 'error'})`);
  process.exitCode = 2;
});
