// Política del motor Chrome con un navegador real (abre ventanas): EOLFI_REAL_BROWSER=1 node --test test/engine-policy.test.mjs
// Dos servidores locales hacen de «sitio» (admitido) y de «otro sitio» (no admitido).
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChromeEngine, findBrowser } from '../engine/chrome.mjs';
import { DENIED_PERMISSIONS } from '../policy.mjs';

const enabled = process.env.EOLFI_REAL_BROWSER === '1' && findBrowser('');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let site, other, engine, profile, servers = [];

async function serve(title) {
  const s = createServer((_q, r) => { r.writeHead(200, { 'Content-Type': 'text/html' }); r.end(`<!doctype html><title>${title}</title><p>${title}</p>`); });
  await new Promise((r) => s.listen(0, '127.0.0.1', r));
  servers.push(s);
  return `http://127.0.0.1:${s.address().port}`;
}

before(async () => {
  if (!enabled) return;
  site = await serve('sitio');
  other = await serve('otro');
  profile = mkdtempSync(join(tmpdir(), 'eolfi-policy-'));
  const allowed = (name, url) => name === 'demo' && new URL(url).origin === site;
  engine = new ChromeEngine({ browser: findBrowser(process.env.EOLFI_BROWSER || ''), profile, policy: { allowed, deniedPermissions: DENIED_PERMISSIONS } });
});
after(async () => {
  if (!enabled) return;
  try { const b = await engine.browserCdp(); await b.send('Browser.close').catch(() => {}); } catch { /* cerrado */ }
  for (const s of servers) s.close();
  await sleep(1500);
  rmSync(profile, { recursive: true, force: true });
});

const skip = !enabled && 'EOLFI_REAL_BROWSER=1 para ejecutarla';

test('motor Chrome: la navegación del marco principal a otro sitio se bloquea; la del propio sitio no', { skip }, async () => {
  const c = await engine.page('demo', site + '/', site);
  assert.equal(await c.executeJavaScript('document.title'), 'sitio');
  await c.executeJavaScript(`location.href = ${JSON.stringify(other + '/')}; 1`).catch(() => {});
  await sleep(2000);
  assert.equal(new URL(await c.executeJavaScript('location.href')).origin, site);
  await c.executeJavaScript(`location.href = ${JSON.stringify(site + '/otra')}; 1`).catch(() => {});
  await sleep(1500);
  assert.equal(await c.executeJavaScript('location.href'), site + '/otra');
});

test('motor Chrome: una ventana emergente hacia otro sitio se cierra', { skip }, async () => {
  const c = await engine.page('demo', site + '/', site);
  const root = await engine.browserCdp();
  await c.executeJavaScript(`window.open(${JSON.stringify(other + '/popup')}); 1`);
  await sleep(2500);
  const { targetInfos } = await root.send('Target.getTargets');
  assert.ok(!targetInfos.some((t) => t.url.startsWith(other)), JSON.stringify(targetInfos.map((t) => t.url)));
});

test('motor Chrome: permisos sensibles denegados', { skip }, async () => {
  const c = await engine.page('demo', site + '/', site);
  assert.ok(engine.deniedPermissions.includes('geolocation') && engine.deniedPermissions.includes('notifications'), String(engine.deniedPermissions));
  assert.equal(await c.executeJavaScript('Notification.permission'), 'denied');
  assert.equal(await c.executeJavaScript('navigator.permissions.query({name:"geolocation"}).then(p=>p.state)'), 'denied');
  assert.equal(await c.executeJavaScript('navigator.permissions.query({name:"notifications"}).then(p=>p.state)'), 'denied');
});
