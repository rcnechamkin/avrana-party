#!/usr/bin/env node
// Owner-run, offline: write the printable two-QR join card (AVR-76). See docs/runbooks/join-card.md.
//
//   node tools/join-card/join-card.mjs --ssid "Avrana Party" --out <local, non-synced dir>/avrana-join-card.html
//   node tools/join-card/join-card.mjs --ssid "Avrana Party" --party-only --out party-link.html
//
// The Wi-Fi password is read from AVRANA_WIFI_PASSWORD or typed at a hidden prompt, never from the
// command line (shell history, process lists). It is never printed, and a card that contains it is
// never written inside a Git working tree.
import { realpathSync, writeFileSync, existsSync, lstatSync, unlinkSync } from 'node:fs';
import { basename, dirname, resolve, relative, isAbsolute, sep } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { renderCard } from './card.mjs';
import { typeKeys } from './hidden-input.mjs';
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
  const out = resolve(realpathSync.native(head), ...rest);
  return process.platform === 'win32' ? out.toLowerCase() : out;
}

function insideRepo(p) {
  const rel = relative(real(REPO), real(p));
  return rel === '' || !(rel === '..' || rel.startsWith(`..${sep}`) || isAbsolute(rel));
}

// Any Git working tree, not only this checkout: a card written into another clone or worktree of
// this repository (or any other) could be committed there. Asks git from the nearest existing
// directory, with the caller's GIT_* location variables removed (a hook or alias sets GIT_DIR,
// which would answer for another repository). Fails closed: only git's own "not a git repository"
// counts as outside; if git cannot run at all, the card is refused.
const GIT_LOCATION_VARS = ['GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_CEILING_DIRECTORIES',
  'GIT_COMMON_DIR', 'GIT_DISCOVERY_ACROSS_FILESYSTEM'];
function insideGitWorkTree(p) {
  let dir = dirname(resolve(p));
  while (!existsSync(dir) && dirname(dir) !== dir) dir = dirname(dir);
  const env = { ...process.env };
  for (const name of [...GIT_LOCATION_VARS, 'AVRANA_WIFI_PASSWORD']) delete env[name];
  env.LC_ALL = 'C';                                    // git's messages in English, for the check below
  const res = spawnSync('git', ['-C', dir, 'rev-parse', '--is-inside-work-tree'], { encoding: 'utf8', windowsHide: true, env });
  if (res.error) {
    throw new JoinCardError('git could not run, so the tool cannot check that the output path is outside every Git working tree; install git or put it on PATH (a --party-only card needs no check)');
  }
  if (res.status === 0) return true;                   // a work tree, or inside a .git directory or bare repository
  if (/not a git repository/i.test(res.stderr || '')) return false;
  throw new JoinCardError('could not tell whether the output path is inside a Git working tree (git refused it); choose a path outside any repository');
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
      const typed = typeKeys(value, chunk);
      value = typed.value;
      if (!typed.end) return;
      stdin.off('data', onData); stdin.setRawMode(false); stdin.pause(); stderr.write('\n');
      if (typed.end === 'cancel') fail(new JoinCardError('cancelled')); else done(value);
    };
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
  if (!partyOnly && insideGitWorkTree(out)) {
    throw new JoinCardError('refusing to write a card with the Wi-Fi password inside a Git working tree, where it could be committed; choose a path outside it');
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
  // Never follow a link at the output path; replace a previous card only if it is a plain file.
  let old;
  try { old = lstatSync(out); } catch { /* new file */ }
  if (old && !old.isFile()) throw new JoinCardError('the output path exists and is not a plain file');
  if (old) unlinkSync(out);
  writeFileSync(out, html, { mode: 0o600, flag: 'wx' });
  console.log(`Wrote ${out}`);
  console.log(partyOnly ? 'Party-only card: no Wi-Fi password on it.' : 'It shows the Wi-Fi password: print it, keep it with the box, do not commit or post it.');
  return 0;
}

main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (err) => {
  // Only JoinCardError messages are known to be free of the password; anything else gets a generic line.
  // Argument errors are not echoed: a password pasted as an argument would be repeated.
  if (err?.code?.startsWith?.('ERR_PARSE_ARGS')) console.error(`join-card: unrecognized arguments (the password goes in AVRANA_WIFI_PASSWORD or the prompt)
${USAGE}`);
  else console.error(err instanceof JoinCardError ? `join-card: ${err.message}` : `join-card: failed (${err?.code || err?.name || 'error'})`);
  process.exitCode = 2;
});
