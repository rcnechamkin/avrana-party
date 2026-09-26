// Browser secure-context evidence for the Party origin. Optional IP argument
// bypasses DNS for a management-LAN check; omit it for the Party Wi-Fi check.
import { chromium } from '@playwright/test';

const ip = process.argv[2];
const args = ['--no-proxy-server'];
if (ip) args.push(`--host-resolver-rules=MAP party.avrana.net ${ip}`);

const browser = await chromium.launch({ headless: true, args });
try {
  const page = await browser.newPage();
  const response = await page.goto('https://party.avrana.net/', {
    waitUntil: 'domcontentloaded',
    timeout: 20_000,
  });
  const capabilities = await page.evaluate(async () => {
    const websocket = await new Promise((resolve) => {
      const ws = new WebSocket(`wss://${location.host}/chat/ws`);
      const timeout = setTimeout(() => { ws.close(); resolve('timeout'); }, 5_000);
      ws.onopen = () => { clearTimeout(timeout); ws.close(); resolve('open'); };
      ws.onerror = () => { clearTimeout(timeout); resolve('error'); };
    });
    return {
      origin: location.origin,
      isSecureContext: window.isSecureContext,
      serviceWorker: 'serviceWorker' in navigator,
      cryptoSubtle: !!crypto.subtle,
      wakeLock: 'wakeLock' in navigator,
      mediaDevices: 'mediaDevices' in navigator,
      getGamepads: typeof navigator.getGamepads === 'function',
      websocket,
    };
  });
  console.log(JSON.stringify({
    route: ip ? `management override ${ip}` : 'system DNS',
    httpStatus: response?.status(),
    ...capabilities,
  }, null, 2));
  if (response?.status() !== 200 || !capabilities.isSecureContext ||
      capabilities.websocket !== 'open') process.exitCode = 1;
} finally {
  await browser.close();
}
