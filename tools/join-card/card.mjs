// The printable two-QR join card (AVR-76): one self-contained HTML page with inline SVG and CSS,
// no script and no external resource, so it renders and prints with no network.
import { encodeQr, qrToSvg } from './qr.mjs';
import { FULL_MODE_URL, HTTP_DOORWAY_URL, JoinCardError, checkSsid, partyUrl, wifiPayload } from './payloads.mjs';

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
// Typed with http://: a bare address may be tried over HTTPS first and hit a certificate warning.
const DOORWAY_TYPED = HTTP_DOORWAY_URL.replace(/\/$/, '');

// The Party mark from web/party/icon.svg.
const MARK = '<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0e0c1d"/>' +
  '<path d="M32 11 L50 53 H41.5 L37.8 44 H26.2 L22.5 53 H14 Z M29 37 H35 L32 29.5 Z" fill="#c7b8ff" fill-rule="evenodd"/>' +
  '<circle cx="48" cy="16" r="4" fill="#8fe3c9"/></svg>';

const STYLE = `
@page { size: A6 landscape; margin: 6mm; }
* { box-sizing: border-box; }
html { background: #edeae4; }
body { margin: 0; padding: 16px; font: 14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; color: #121214; }
.card { max-width: 760px; margin: 0 auto; background: #fff; border-radius: 18px; overflow: hidden; border: 1px solid #d8d4cc; }
header { display: flex; align-items: center; gap: 12px; padding: 14px 20px; background: #161618; color: #edeae4; }
.mark { width: 36px; height: 36px; flex: none; }
header h1 { margin: 0; font-size: 20px; letter-spacing: .02em; }
header p { margin: 0 0 0 auto; color: #b9a9e8; font-size: 13px; }
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0; }
.step { padding: 18px 20px; text-align: center; }
.step + .step { border-left: 1px solid #e4e0d8; }
@media (max-width: 559px) { .step + .step { border-left: 0; border-top: 1px solid #e4e0d8; } }
.num { display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: #b9a9e8; color: #121214; font-weight: 750; }
.step h2 { margin: 6px 0 10px; font-size: 18px; }
.qr { width: 200px; height: 200px; margin: 0 auto; display: block; }
.qr svg { width: 100%; height: 100%; display: block; }
dl { margin: 12px 0 0; display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; text-align: left; }
dt { color: #5d5a57; } dd { margin: 0; font-weight: 650; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 13px; }
.how { margin: 10px 0 0; color: #3d3b39; font-size: 13px; text-align: left; }
.help { margin: 0; padding: 12px 20px 14px; background: #f6f4f0; border-top: 1px solid #e4e0d8; font-size: 12.5px; color: #3d3b39; }
.help h3 { margin: 0 0 4px; font-size: 13px; color: #121214; }
.help ul { margin: 0; padding-left: 18px; }
footer { padding: 6px 20px 10px; background: #f6f4f0; font-size: 11px; color: #6f6b67; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
@media print { html { background: #fff; } body { padding: 0; } .card { border: 0; border-radius: 0; } }
`;

function qrBlock(payload, label, level) {
  let qr;
  try { qr = encodeQr(payload, { level }); } catch (err) {
    if (err instanceof RangeError) throw new JoinCardError(`network name and password are too long for one QR code at level ${level}; try --level M or L`);
    throw err;
  }
  return `<div class="qr">${qrToSvg(qr, { dark: '#121214', light: '#ffffff', title: label })}</div>`;
}

/**
 * Render the join card.
 * @param {{ ssid: string, password?: string, hidden?: boolean, partyOnly?: boolean,
 *           partyLink?: string, generatedOn: string, level?: 'L'|'M'|'Q'|'H' }} options
 *   With `partyOnly`, the card has no Wi-Fi QR and never contains the password.
 */
export function renderCard({ ssid, password, hidden = false, partyOnly = false, partyLink = FULL_MODE_URL, generatedOn, level = 'M' }) {
  checkSsid(ssid);
  const link = partyUrl(partyLink);
  const full = link === FULL_MODE_URL;

  const wifiStep = partyOnly
    ? `<section class="step"><span class="num">1</span><h2>Join the Wi-Fi</h2>
<dl><dt>Network</dt><dd>${esc(ssid)}</dd><dt>Password</dt><dd>ask the host</dd></dl>
<p class="how">Open Settings › Wi-Fi and pick <strong>${esc(ssid)}</strong>.</p></section>`
    : `<section class="step"><span class="num">1</span><h2>Join the Wi-Fi</h2>
${qrBlock(wifiPayload({ ssid, password, hidden }), `Wi-Fi QR code for ${ssid}`, level)}
<dl><dt>Network</dt><dd>${esc(ssid)}</dd><dt>Password</dt><dd class="mono">${esc(password)}</dd></dl>
<p class="how"><strong>iPhone:</strong> point the Camera, tap <em>Join</em>. <strong>Android:</strong> Camera, or Wi-Fi settings › scan QR.</p></section>`;

  const partyStep = `<section class="step"><span class="num">2</span><h2>Open the Party</h2>
${qrBlock(link, 'Party link QR code', level)}
<dl><dt>Or type</dt><dd class="mono">${esc(link)}</dd></dl>
<p class="how">Scan with the Camera after step 1. It opens in Safari or Chrome. No app, no account, no internet.${full ? '' : ' Then tap <em>Open Avrana Party</em>.'}</p></section>`;

  const tips = [
    'Phone says the Wi-Fi has no internet? Choose to <strong>stay connected</strong>.',
    'Page did not open? Check you are on ' + `<strong>${esc(ssid)}</strong>, pause any VPN or Private DNS, and turn off mobile data.`,
    full ? `Still stuck? Type <span class="mono">${esc(DOORWAY_TYPED)}</span> and tap <em>Open Avrana Party</em>.` : '',
    'A small sign-in window opened? Leave it (<em>Cancel</em>, <em>Done</em> or <em>Use Without Internet</em>), then scan step 2 with the Camera: play in Safari or Chrome.',
    'Chrome on iPhone: allow <em>Local Network</em> if asked.',
  ].filter(Boolean).map((t) => `<li>${t}</li>`).join('');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avrana Party join card</title>
<style>${STYLE}</style>
</head>
<body>
<main class="card">
<header>${MARK}<h1>Avrana Party</h1><p>Two scans to play</p></header>
<div class="steps">
${wifiStep}
${partyStep}
</div>
<section class="help"><h3>If something is stuck</h3><ul>${tips}</ul></section>
<footer><span>Printed ${esc(generatedOn)}${partyOnly ? '' : '. Wi-Fi password changed? Print a new card.'}</span><span>${partyOnly ? 'No password on this card.' : 'Shows the Wi-Fi password: keep it with the box.'}</span></footer>
</main>
</body>
</html>
`;
}
