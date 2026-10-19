// The two-QR join card (AVR-76): tools/join-card/. Every QR code is decoded with jsQR, a decoder
// that shares no code with the encoder. The password here is a made-up test value.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import jsQR from 'jsqr';
import { encodeQr, qrToSvg } from '../../tools/join-card/qr.mjs';
import { FULL_MODE_URL, HTTP_DOORWAY_URL, JoinCardError, partyUrl, wifiPayload } from '../../tools/join-card/payloads.mjs';
import { renderCard } from '../../tools/join-card/card.mjs';

const PASSWORD = 'test-only;pass:word,"x\\';
const CLI = fileURLToPath(new URL('../../tools/join-card/join-card.mjs', import.meta.url));

function raster(qr, { scale = 4, border = 4, flip = [] } = {}) {
  const dim = (qr.size + border * 2) * scale, px = new Uint8ClampedArray(dim * dim * 4).fill(255);
  const dark = qr.modules.map((row) => row.slice());
  for (const [x, y] of flip) dark[y][x] = !dark[y][x];
  dark.forEach((row, y) => row.forEach((on, x) => {
    if (!on) return;
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
      const i = (((y + border) * scale + dy) * dim + (x + border) * scale + dx) * 4;
      px[i] = px[i + 1] = px[i + 2] = 0;
    }
  }));
  return { px, dim };
}

function decode(qr, options) {
  const { px, dim } = raster(qr, options);
  const got = jsQR(px, dim, dim, { inversionAttempts: 'dontInvert' });
  assert.ok(got, 'jsQR found no code');
  return got;
}

const decodesTo = (qr, text) => assert.deepEqual(Buffer.from(decode(qr).binaryData), Buffer.from(text, 'utf8'));
const svgsIn = (html) => html.match(/<svg xmlns[\s\S]*?<\/svg>/g).filter((s) => s.includes('crispEdges'));

// Byte-mode capacities of versions 1 to 10, from the ISO/IEC 18004 capacity table: an independent
// check of the encoder's block tables.
const CAPACITY = {
  L: [17, 32, 53, 78, 106, 134, 154, 192, 230, 271],
  M: [14, 26, 42, 62, 84, 106, 122, 152, 180, 213],
  Q: [11, 20, 32, 46, 60, 74, 86, 108, 130, 151],
  H: [7, 14, 24, 34, 44, 58, 64, 84, 98, 119],
};
const sample = (len) => Array.from({ length: len }, (_, i) => String.fromCharCode(33 + ((i * 31 + len) % 94))).join('');

test('every version 1 to 10 at every level holds exactly its standard capacity and decodes to the exact bytes', () => {
  for (const [level, caps] of Object.entries(CAPACITY)) {
    caps.forEach((cap, i) => {
      const version = i + 1, text = sample(cap);
      const qr = encodeQr(text, { level, mask: version % 8 });
      assert.equal(qr.version, version, `${level} ${cap} bytes`);
      assert.equal(qr.size, version * 4 + 17);
      const got = decode(qr);
      assert.equal(got.data, text, `${level} v${version}`);
      assert.equal(got.version, version);
      if (version < 10) assert.equal(encodeQr(sample(cap + 1), { level, mask: 0 }).version, version + 1, `${level} ${cap + 1} bytes`);
      else assert.throws(() => encodeQr(sample(cap + 1), { level }), /too long/);
    });
  }
});

test('all eight masks decode, and UTF-8 survives', () => {
  const text = 'WIFI:T:WPA;S:Fête Avrana ✨;P:abcdefgh;;';
  for (let mask = 0; mask < 8; mask++) {
    const qr = encodeQr(text, { level: 'Q', mask });
    assert.equal(qr.mask, mask);
    decodesTo(qr, text);
  }
});

test('Reed-Solomon codewords really correct damage', () => {
  const qr = encodeQr(FULL_MODE_URL, { level: 'H', minVersion: 5 });
  assert.equal(qr.version, 5);
  // Flip modules in the data area, away from finders, timing and format information.
  const flip = [];
  for (let i = 0; i < 24; i++) flip.push([12 + (i % 6), 14 + Math.floor(i / 6) * 2]);
  assert.equal(decode(qr, { flip }).data, FULL_MODE_URL);
});

test('the automatic mask choice decodes too', () => {
  for (const text of [FULL_MODE_URL, HTTP_DOORWAY_URL, sample(100)]) decodesTo(encodeQr(text), text);
});

test('the SVG draws exactly the dark modules inside a four-module quiet zone', () => {
  const qr = encodeQr('avrana');
  const svg = qrToSvg(qr);
  const dim = qr.size + 8;
  assert.match(svg, new RegExp(`viewBox="0 0 ${dim} ${dim}"`));
  const drawn = [...svg.matchAll(/M(\d+) (\d+)h1v1h-1z/g)].map(([, x, y]) => `${x - 4},${y - 4}`);
  const want = qr.modules.flatMap((row, y) => row.map((on, x) => (on ? `${x},${y}` : null))).filter(Boolean);
  assert.deepEqual(drawn, want);
});

test('Wi-Fi payload follows the WIFI: convention and escapes \\ ; , : "', () => {
  assert.equal(wifiPayload({ ssid: 'Avrana Party', password: 'abcdefgh' }), 'WIFI:T:WPA;S:Avrana Party;P:abcdefgh;;');
  assert.equal(wifiPayload({ ssid: 'A;B', password: PASSWORD }), 'WIFI:T:WPA;S:A\\;B;P:test-only\\;pass\\:word\\,\\"x\\\\;;');
  assert.equal(wifiPayload({ ssid: 'Hidden', password: 'abcdefgh', hidden: true }), 'WIFI:T:WPA;S:Hidden;P:abcdefgh;H:true;;');
  assert.equal(wifiPayload({ ssid: 'x', password: 'f'.repeat(64) }), `WIFI:T:WPA;S:x;P:${'f'.repeat(64)};;`);
});

test('missing or invalid Wi-Fi settings fail with messages that never echo the password', () => {
  const bad = [
    [{ ssid: '', password: 'abcdefgh' }, /name is missing/],
    [{ ssid: 'x'.repeat(33), password: 'abcdefgh' }, /32 bytes/],
    [{ ssid: 'é'.repeat(17), password: 'abcdefgh' }, /32 bytes/],
    [{ ssid: 'a\nb', password: 'abcdefgh' }, /control/],
    [{ ssid: 'Avrana Party' }, /password is missing/],
    [{ ssid: 'Avrana Party', password: 'short7!' }, /8 to 63/],
    [{ ssid: 'Avrana Party', password: 'x'.repeat(64) }, /8 to 63/],
    [{ ssid: 'Avrana Party', password: 'tab\there-ok?' }, /8 to 63/],
    [{ ssid: 'Avrana Party', password: 'pässwörter' }, /8 to 63/],
  ];
  for (const [input, message] of bad) {
    assert.throws(() => wifiPayload(input), (err) => err instanceof JoinCardError && message.test(err.message)
      && (!input.password || !err.message.includes(input.password)));
  }
});

test('the Party link is only the Party origin, without tokens', () => {
  assert.equal(partyUrl(), FULL_MODE_URL);
  assert.equal(partyUrl('https://party.avrana.net/party'), FULL_MODE_URL);
  assert.equal(partyUrl('HTTPS://Party.Avrana.NET/party/'), FULL_MODE_URL);
  assert.equal(partyUrl('https://party.avrana.net:443/party/'), FULL_MODE_URL);
  assert.equal(partyUrl('http://10.42.0.1'), HTTP_DOORWAY_URL);
  for (const bad of [
    'https://games.avrana.net/party/', 'https://games.avrana.net/', 'https://party.avrana.net/',
    'https://party.avrana.net/party/?token=abc', 'https://party.avrana.net/party/#device=abc', 'https://party.avrana.net/party/?',
    'https://user:pw@party.avrana.net/party/', 'https://party.avrana.net:8443/party/', 'http://party.avrana.net/party/',
    'http://10.42.0.1/party/', 'http://party.local/', 'https://evil.example/party/', 'javascript:alert(1)', 'not a url',
    'https://party.avrana.net.evil.example/party/', 'http://010.42.0.1/',
  ]) {
    assert.throws(() => partyUrl(bad), JoinCardError, bad);
  }
});

test('the card is two decodable QR codes plus readable fallbacks, with nothing fetched', () => {
  const html = renderCard({ ssid: 'Avrana Party', password: PASSWORD, generatedOn: '2026-10-19' });
  const [wifi, party] = svgsIn(html);
  const wifiText = wifiPayload({ ssid: 'Avrana Party', password: PASSWORD });
  assert.equal(wifi, qrToSvg(encodeQr(wifiText), { dark: '#121214', light: '#ffffff', title: 'Wi-Fi QR code for Avrana Party' }));
  decodesTo(encodeQr(wifiText), wifiText);
  assert.equal(party, qrToSvg(encodeQr(FULL_MODE_URL), { dark: '#121214', light: '#ffffff', title: 'Party link QR code' }));
  decodesTo(encodeQr(FULL_MODE_URL), FULL_MODE_URL);
  // Offline: no script, no fetched resource of any kind.
  assert.doesNotMatch(html, /<script|<link|<img|<iframe|\ssrc=|\shref=|url\(|@import/i);
  for (const url of html.match(/https?:\/\/[^\s"<]+/g)) {
    assert.ok([FULL_MODE_URL, 'http://10.42.0.1', 'http://www.w3.org/2000/svg'].includes(url), url);
  }
  // Readable fallbacks for each failure the card can name.
  for (const words of ['Avrana Party', 'test-only;pass:word,&#34;x\\', FULL_MODE_URL, '>http://10.42.0.1<', 'stay connected', 'Use Without Internet', 'VPN', 'Private DNS',
    'mobile data', 'Local Network', 'sign-in window', 'Print a new card', 'Printed 2026-10-19']) {
    assert.ok(html.includes(words), words);
  }
});

test('a rotated password replaces the old one everywhere on the card', () => {
  const before = renderCard({ ssid: 'Avrana Party', password: 'old-password-1', generatedOn: '2026-10-01' });
  const after = renderCard({ ssid: 'Avrana Party', password: 'new-password-2', generatedOn: '2026-10-19' });
  assert.ok(before.includes('old-password-1'));
  assert.ok(!after.includes('old-password-1') && after.includes('new-password-2'));
  assert.notEqual(svgsIn(before)[0], svgsIn(after)[0]);
  assert.equal(svgsIn(before)[1], svgsIn(after)[1]);       // the Party link does not change
});

test('a Party-only card has one QR code and no password', () => {
  const html = renderCard({ ssid: 'Avrana Party', password: PASSWORD, partyOnly: true, generatedOn: '2026-10-19' });
  assert.equal(svgsIn(html).length, 1);
  assert.ok(!html.includes('test-only') && !html.includes('WIFI:'));
  assert.match(html, /ask the host/);
  assert.match(html, /No password on this card/);
});

test('the HTTP doorway link drops the redundant typed fallback, and names are HTML-escaped', () => {
  const html = renderCard({ ssid: '<b>"Party"</b>', password: 'abcdefgh', partyLink: 'http://10.42.0.1', generatedOn: 'x' });
  assert.doesNotMatch(html, /<b>/);
  assert.ok(html.includes('&#60;b&#62;&#34;Party&#34;&#60;/b&#62;'));
  assert.match(html, /tap <em>Open Avrana Party<\/em>/);
  assert.doesNotMatch(html, /Still stuck/);
  decodesTo(encodeQr(HTTP_DOORWAY_URL), HTTP_DOORWAY_URL);
  assert.throws(() => renderCard({ ssid: 'A', password: 'abcdefgh', partyLink: 'https://games.avrana.net/', generatedOn: 'x' }), JoinCardError);
});

function cli(args, env = {}) {
  const res = spawnSync(process.execPath, [CLI, ...args], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8', input: '', env: { ...process.env, AVRANA_WIFI_PASSWORD: '', AVRANA_WIFI_SSID: '', ...env },
  });
  return { ...res, said: res.stdout + res.stderr };
}

test('the CLI writes a card outside the repository and never prints the password', () => {
  const dir = mkdtempSync(join(tmpdir(), 'avr76-'));
  try {
    const out = join(dir, 'card.html');
    const res = cli(['--ssid', 'Avrana Party', '--out', out], { AVRANA_WIFI_PASSWORD: PASSWORD });
    assert.equal(res.status, 0, res.said);
    assert.ok(!res.said.includes('test-only'), res.said);
    assert.match(res.said, /do not commit or post it/);
    const html = readFileSync(out, 'utf8');
    assert.equal(svgsIn(html).length, 2);
    decodesTo(encodeQr(wifiPayload({ ssid: 'Avrana Party', password: PASSWORD })), wifiPayload({ ssid: 'Avrana Party', password: PASSWORD }));

    // A previous card at the same path is replaced (password rotation); a link there is refused.
    const again = cli(['--ssid', 'Avrana Party', '--out', out], { AVRANA_WIFI_PASSWORD: 'rotated-password-2' });
    assert.equal(again.status, 0, again.said);
    assert.ok(readFileSync(out, 'utf8').includes('rotated-password-2') && !readFileSync(out, 'utf8').includes('test-only'));
    const link = join(dir, 'link.html');
    let linked = true;
    try { symlinkSync(join(dir, 'target.html'), link); } catch { linked = false; }   // Windows may lack the privilege
    if (linked) {
      const res = cli(['--ssid', 'Avrana Party', '--out', link], { AVRANA_WIFI_PASSWORD: PASSWORD });
      assert.equal(res.status, 2, res.said);
      assert.ok(!existsSync(join(dir, 'target.html')));
    }

    const party = join(dir, 'party.html');
    assert.equal(cli(['--ssid', 'Avrana Party', '--party-only', '--out', party]).status, 0);
    assert.equal(svgsIn(readFileSync(party, 'utf8')).length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('the CLI refuses missing settings, bad links and in-repository output', () => {
  const dir = mkdtempSync(join(tmpdir(), 'avr76-'));
  try {
    const out = join(dir, 'card.html');
    const cases = [
      [['--out', out], {}, /network name is missing/],
      [['--ssid', 'Avrana Party', '--out', out], {}, /password is missing/],                      // no env, stdin not a terminal
      [['--ssid', 'Avrana Party', '--out', out], { AVRANA_WIFI_PASSWORD: 'short' }, /8 to 63/],
      [['--ssid', 'Avrana Party', '--out', out, '--party-url', 'https://party.avrana.net/party/?t=1'], { AVRANA_WIFI_PASSWORD: PASSWORD }, /query or fragment/],
      [['--ssid', 'Avrana Party', '--out', 'join-card.html'], { AVRANA_WIFI_PASSWORD: PASSWORD }, /inside the repository/],
      [['--ssid', 'Avrana Party', '--out', 'docs/x/../join-card.html'], { AVRANA_WIFI_PASSWORD: PASSWORD }, /inside the repository/],
      [['--ssid', 'Avrana Party'], {}, /--out is required/],
      [['--ssid', 'Avrana Party', '--out', out, '--password', 'test-only-argv'], {}, /unrecognized arguments/],
      [['--ssid', 'Avrana Party', '--out', out, 'test-only-positional'], {}, /unrecognized arguments/],
      [['--ssid', ';'.repeat(32), '--out', out, '--level', 'H'], { AVRANA_WIFI_PASSWORD: 'p'.repeat(63) }, /too long for one QR code/],
      [['--ssid', 'Avrana Party', '--out', join('..zz-avr76', 'c.html')], { AVRANA_WIFI_PASSWORD: PASSWORD }, /inside the repository/],
      [['--ssid', 'Avrana Party', '--out', dir], { AVRANA_WIFI_PASSWORD: PASSWORD }, /not a plain file/],
    ];
    for (const [args, env, message] of cases) {
      const res = cli(args, env);
      assert.equal(res.status, 2, `${args.join(' ')}: ${res.said}`);
      assert.match(res.said, message);
      assert.ok(!res.said.includes('test-only'), res.said);
    }
    assert.ok(!existsSync(out));

    // Another Git working tree (a second clone or worktree of this repository, or any repository)
    // is refused too: the card could be committed there.
    const other = join(dir, 'other-clone');
    if (spawnSync('git', ['init', '-q', other]).status === 0) {
      const res = cli(['--ssid', 'Avrana Party', '--out', join(other, 'sub', 'card.html')], { AVRANA_WIFI_PASSWORD: PASSWORD });
      assert.equal(res.status, 2, res.said);
      assert.match(res.said, /inside a Git working tree/);
      assert.ok(!existsSync(join(other, 'sub', 'card.html')));
      assert.equal(cli(['--ssid', 'Avrana Party', '--party-only', '--out', join(other, 'party.html')]).status, 0);

      // A GIT_DIR/GIT_WORK_TREE inherited from a hook or alias must not answer for another repository.
      const plain = join(dir, 'plain');
      mkdirSync(plain);
      const env = { AVRANA_WIFI_PASSWORD: PASSWORD, GIT_DIR: join(other, '.git'), GIT_WORK_TREE: other };
      const inherited = cli(['--ssid', 'Avrana Party', '--out', join(other, 'card2.html')], env);
      assert.equal(inherited.status, 2, inherited.said);
      assert.ok(!existsSync(join(other, 'card2.html')));
      const outside = cli(['--ssid', 'Avrana Party', '--out', join(plain, 'card.html')], env);   // and a plain directory is not refused because of it
      assert.equal(outside.status, 0, outside.said);
    }
    assert.ok(!existsSync(new URL('../../join-card.html', import.meta.url)));
    assert.ok(!existsSync(new URL('../../..zz-avr76', import.meta.url)));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
