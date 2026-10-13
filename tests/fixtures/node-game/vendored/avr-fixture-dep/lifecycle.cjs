// What an install script would do if anything ran it: leave a mark. Nothing does (AVR-68): the
// installer runs no npm, no lifecycle script and no code of a package. The proofs look for the mark.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

for (const dir of [os.tmpdir(), process.cwd()]) {
  try {
    fs.writeFileSync(path.join(dir, 'avr68-lifecycle-ran'), `${process.argv[2] || 'unknown'}\n`);
  } catch { /* a read-only place: the other one tells */ }
}
