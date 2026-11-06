// Prueba del motor CDP con un navegador real (abre ventanas): EOLFI_REAL_BROWSER=1 node --test test/engine.test.mjs
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChromeEngine, findBrowser } from '../engine/chrome.mjs';

const enabled = process.env.EOLFI_REAL_BROWSER === '1' && findBrowser('');
const PAGE = `<!doctype html><title>t</title><textarea id="t"></textarea><ul id="out"></ul>
<script>t.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault();
  const li = document.createElement('li'); li.textContent = t.value; out.append(li); t.value = ''; } });</script>`;
let srv, base, engine, profile;

before(async () => {
  if (!enabled) return;
  srv = createServer((_q, r) => { r.writeHead(200, { 'Content-Type': 'text/html' }); r.end(PAGE); });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${srv.address().port}`;
  profile = mkdtempSync(join(tmpdir(), 'eolfi-engine-'));
  engine = new ChromeEngine({ browser: findBrowser(process.env.EOLFI_BROWSER || ''), profile });
});
after(async () => {
  if (!enabled) return;
  try { const b = await engine.browserCdp(); await b.send('Browser.close').catch(() => {}); } catch { /* cerrado */ }
  srv.close();
  await new Promise((r) => setTimeout(r, 1500));
  rmSync(profile, { recursive: true, force: true });
});

test('motor CDP: abrir, escribir, Intro, leer y capturar', { skip: !enabled && 'EOLFI_REAL_BROWSER=1 para ejecutarla' }, async () => {
  const c = await engine.page('demo', base + '/', base);
  assert.equal(c.getURL(), base + '/');
  assert.equal(await c.executeJavaScript('document.title'), 't');
  await c.executeJavaScript("document.getElementById('t').focus()");
  await c.insertText('hola desde Eolfi');
  assert.equal(await c.executeJavaScript("document.getElementById('t').value"), 'hola desde Eolfi');
  await c.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
  await c.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
  assert.equal(await c.executeJavaScript("document.querySelector('#out li')?.textContent"), 'hola desde Eolfi');
  await assert.rejects(c.executeJavaScript("(() => { throw new Error('fallo a propósito') })()"), /fallo a propósito/);
  await c.loadURL(base + '/otra');
  assert.equal(c.getURL(), base + '/otra');
  const jpg = await c.screenshot();
  assert.equal(jpg[0], 0xff); assert.equal(jpg[1], 0xd8);
  assert.equal(await engine.page('demo', base + '/', base), c);          // reutiliza la ventana
  // Control por tubería: no hay puerto de depuración al que otro proceso pueda conectarse.
  assert.equal(existsSync(join(profile, 'DevToolsActivePort')), false);
  assert.equal(await engine.alive(), true);
});
