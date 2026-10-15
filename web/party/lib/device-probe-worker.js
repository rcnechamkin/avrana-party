// EXPERIMENTAL (AVR-469). The Worker half of lib/device-check.js: can this browser make a WebGL 2
// context on an OffscreenCanvas inside a Worker, as a threaded engine port does? A file of Party's own
// origin (the shell's worker-src is 'self': no blob: workers), started and ended by device-check.js.
let ok = false;
let detail = 'no OffscreenCanvas in a Worker';
try {
  if (typeof OffscreenCanvas === 'function') {
    const gl = new OffscreenCanvas(16, 16).getContext('webgl2');
    ok = Boolean(gl);
    detail = ok ? 'WebGL 2 context created in a Worker' : 'OffscreenCanvas in a Worker has no WebGL 2 context';
    const lose = gl && gl.getExtension && gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  }
} catch (error) {
  detail = `WebGL 2 in a Worker threw: ${error && error.message ? error.message : error}`;
}
postMessage({ ok, detail });
