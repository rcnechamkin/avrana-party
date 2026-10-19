// A small QR Code Model 2 encoder: byte mode, versions 1 to 10, all four error-correction levels.
// It exists so the join card is made offline, with no package fetched at print time (AVR-76).
// Ten versions hold 213 bytes at level M, far more than a Wi-Fi or Party link needs.
// The algorithm follows ISO/IEC 18004; tests/offline/join-card.test.mjs decodes every version and
// level with an independent decoder (jsQR) and checks error correction by damaging codes.

const MAX_VERSION = 10;

// Format-information value of each level, and its codewords per block and number of blocks,
// indexed by version (index 0 unused).
const LEVELS = {
  L: { bits: 1, ecc: [0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18], blocks: [0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4] },
  M: { bits: 0, ecc: [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26], blocks: [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5] },
  Q: { bits: 3, ecc: [0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24], blocks: [0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8] },
  H: { bits: 2, ecc: [0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28], blocks: [0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8] },
};

const MASKS = [
  (x, y) => (x + y) % 2 === 0,
  (x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

const bit = (value, i) => ((value >>> i) & 1) !== 0;

function rawDataModules(ver) {
  let n = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const align = Math.floor(ver / 7) + 2;
    n -= (25 * align - 10) * align - 55;
    if (ver >= 7) n -= 36;
  }
  return n;
}

const dataCodewords = (ver, level) =>
  Math.floor(rawDataModules(ver) / 8) - LEVELS[level].ecc[ver] * LEVELS[level].blocks[ver];

function alignmentPositions(ver) {
  if (ver === 1) return [];
  const count = Math.floor(ver / 7) + 2;
  const step = Math.ceil((ver * 4 + 4) / (count * 2 - 2)) * 2;
  const out = [6];
  for (let pos = ver * 4 + 17 - 7; out.length < count; pos -= step) out.splice(1, 0, pos);
  return out;
}

// GF(256) with the QR polynomial x^8 + x^4 + x^3 + x^2 + 1.
function gfMul(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

function rsDivisor(degree) {
  const out = new Array(degree).fill(0);
  out[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < out.length; j++) {
      out[j] = gfMul(out[j], root);
      if (j + 1 < out.length) out[j] ^= out[j + 1];
    }
    root = gfMul(root, 0x02);
  }
  return out;
}

function rsRemainder(data, divisor) {
  const out = divisor.map(() => 0);
  for (const b of data) {
    const factor = b ^ out.shift();
    out.push(0);
    divisor.forEach((coef, i) => { out[i] ^= gfMul(coef, factor); });
  }
  return out;
}

function encodeData(bytes, ver, level) {
  const bits = [];
  const put = (value, len) => { for (let i = len - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(0b0100, 4);                                   // byte mode
  put(bytes.length, ver < 10 ? 8 : 16);
  for (const b of bytes) put(b, 8);
  const capacity = dataCodewords(ver, level) * 8;
  put(0, Math.min(4, capacity - bits.length));      // terminator
  put(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) put(pad, 8);
  const out = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  return out;
}

function interleave(data, ver, level) {
  const blockCount = LEVELS[level].blocks[ver], eccLen = LEVELS[level].ecc[ver];
  const raw = Math.floor(rawDataModules(ver) / 8);
  const shortCount = blockCount - (raw % blockCount), shortLen = Math.floor(raw / blockCount);
  const divisor = rsDivisor(eccLen), blocks = [];
  for (let i = 0, k = 0; i < blockCount; i++) {
    const dat = data.slice(k, k + shortLen - eccLen + (i < shortCount ? 0 : 1));
    k += dat.length;
    const ecc = rsRemainder(dat, divisor);
    if (i < shortCount) dat.push(0);
    blocks.push(dat.concat(ecc));
  }
  const out = [];
  for (let i = 0; i < blocks[0].length; i++) {
    blocks.forEach((block, j) => { if (i !== shortLen - eccLen || j >= shortCount) out.push(block[i]); });
  }
  return out;
}

class Grid {
  constructor(ver) {
    this.size = ver * 4 + 17;
    this.dark = Array.from({ length: this.size }, () => new Array(this.size).fill(false));
    this.fixed = Array.from({ length: this.size }, () => new Array(this.size).fill(false));
  }
  set(x, y, dark) { this.dark[y][x] = dark; this.fixed[y][x] = true; }
}

function drawFunctionPatterns(g, ver) {
  const n = g.size;
  for (let i = 0; i < n; i++) { g.set(6, i, i % 2 === 0); g.set(i, 6, i % 2 === 0); }
  for (const [cx, cy] of [[3, 3], [n - 4, 3], [3, n - 4]]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy)), x = cx + dx, y = cy + dy;
        if (x >= 0 && x < n && y >= 0 && y < n) g.set(x, y, d !== 2 && d !== 4);
      }
    }
  }
  const pos = alignmentPositions(ver), last = pos.length - 1;
  pos.forEach((cx, i) => pos.forEach((cy, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) g.set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }));
  drawFormat(g, 'L', 0);                            // reserve; redrawn with the chosen mask
  if (ver >= 7) {
    let rem = ver;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (ver << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const a = n - 11 + (i % 3), b = Math.floor(i / 3);
      g.set(a, b, bit(bits, i));
      g.set(b, a, bit(bits, i));
    }
  }
}

function drawFormat(g, level, mask) {
  const data = (LEVELS[level].bits << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  const bits = ((data << 10) | rem) ^ 0x5412, n = g.size;
  for (let i = 0; i <= 5; i++) g.set(8, i, bit(bits, i));
  g.set(8, 7, bit(bits, 6));
  g.set(8, 8, bit(bits, 7));
  g.set(7, 8, bit(bits, 8));
  for (let i = 9; i < 15; i++) g.set(14 - i, 8, bit(bits, i));
  for (let i = 0; i < 8; i++) g.set(n - 1 - i, 8, bit(bits, i));
  for (let i = 8; i < 15; i++) g.set(8, n - 15 + i, bit(bits, i));
  g.set(8, n - 8, true);                            // the dark module
}

function drawCodewords(g, codewords) {
  const n = g.size;
  let i = 0;
  for (let right = n - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < n; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j, y = ((right + 1) & 2) === 0 ? n - 1 - vert : vert;
        if (!g.fixed[y][x] && i < codewords.length * 8) {
          g.dark[y][x] = bit(codewords[i >>> 3], 7 - (i & 7));
          i++;
        }
      }
    }
  }
}

function applyMask(g, mask) {
  for (let y = 0; y < g.size; y++) for (let x = 0; x < g.size; x++) {
    if (!g.fixed[y][x] && MASKS[mask](x, y)) g.dark[y][x] = !g.dark[y][x];
  }
}

// The standard penalty (rules N1 to N4). Any mask decodes; a lower score scans more easily.
function penalty(m) {
  const n = m.length;
  let score = 0, darkCount = 0;
  const line = (get) => {
    for (let a = 0; a < n; a++) {
      let run = 1;
      for (let b = 1; b <= n; b++) {
        if (b < n && get(a, b) === get(a, b - 1)) { run++; continue; }
        if (run >= 5) score += run - 2;
        run = 1;
      }
      for (let b = 0, word = 0; b < n; b++) {
        word = ((word << 1) | (get(a, b) ? 1 : 0)) & 0x7ff;
        if (b >= 10 && (word === 0b10111010000 || word === 0b00001011101)) score += 40;
      }
    }
  };
  line((row, col) => m[row][col]);
  line((col, row) => m[row][col]);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    if (m[y][x]) darkCount++;
    if (x < n - 1 && y < n - 1 && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) score += 3;
  }
  const total = n * n;
  score += 10 * Math.floor(Math.abs(darkCount * 100 / total - 50) / 5);
  return score;
}

/**
 * Encode text (UTF-8, byte mode) as a QR code.
 * @param {string} text
 * @param {{ level?: 'L'|'M'|'Q'|'H', mask?: number, minVersion?: number }} [options]
 * @returns {{ version: number, level: string, mask: number, size: number, modules: boolean[][] }}
 */
export function encodeQr(text, { level = 'M', mask, minVersion = 1 } = {}) {
  if (typeof text !== 'string') throw new TypeError('QR text must be a string');
  if (!LEVELS[level]) throw new RangeError(`unknown error-correction level: ${level}`);
  if (mask !== undefined && !(Number.isInteger(mask) && mask >= 0 && mask <= 7)) throw new RangeError('mask must be 0 to 7');
  const bytes = [...new TextEncoder().encode(text)];
  let ver = Math.max(1, minVersion);
  while (ver <= MAX_VERSION && 4 + (ver < 10 ? 8 : 16) + bytes.length * 8 > dataCodewords(ver, level) * 8) ver++;
  if (ver > MAX_VERSION) throw new RangeError(`text too long for a version ${MAX_VERSION} QR code at level ${level}`);
  const codewords = interleave(encodeData(bytes, ver, level), ver, level);
  const build = (m) => {
    const g = new Grid(ver);
    drawFunctionPatterns(g, ver);
    drawCodewords(g, codewords);
    applyMask(g, m);
    drawFormat(g, level, m);
    return g;
  };
  let best;
  for (const m of mask === undefined ? [0, 1, 2, 3, 4, 5, 6, 7] : [mask]) {
    const g = build(m), score = penalty(g.dark);
    if (!best || score < best.score) best = { g, m, score };
  }
  return { version: ver, level, mask: best.m, size: best.g.size, modules: best.g.dark };
}

/**
 * Render a QR code as a standalone SVG: one path of unit squares inside a light quiet zone.
 * @param {{ size: number, modules: boolean[][] }} qr
 * @param {{ border?: number, dark?: string, light?: string, title?: string }} [options]
 */
export function qrToSvg(qr, { border = 4, dark = '#000', light = '#fff', title = '' } = {}) {
  const dim = qr.size + border * 2, parts = [];
  qr.modules.forEach((row, y) => row.forEach((on, x) => { if (on) parts.push(`M${x + border} ${y + border}h1v1h-1z`); }));
  const label = title ? ` role="img" aria-label="${title.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`)}"` : ' aria-hidden="true"';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}" shape-rendering="crispEdges"${label}>` +
    `<rect width="${dim}" height="${dim}" fill="${light}"/><path d="${parts.join('')}" fill="${dark}"/></svg>`;
}
