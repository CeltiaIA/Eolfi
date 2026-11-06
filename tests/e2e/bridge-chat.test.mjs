// Puente (Fase E, grupo 3) contra un chat SIMULADO en local y un navegador real: adaptador declarativo,
// autodiagnóstico, streaming (texto parcial), final con texto estable, URL de conversación y comparativa.
// Nada sale de 127.0.0.1: no se usa ningún chat real.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { chromium } from 'playwright-core';
import { makeDeclarativeAdapter } from '../../eolfi/bridge/adapters/declarative.mjs';
import { startBridgeServer } from '../../eolfi/bridge/server.mjs';

const PAGE = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Chat simulado</title></head><body>
<main id="log"></main>
<form id="f"><textarea id="prompt" aria-label="Mensaje"></textarea><button id="send" type="button">Enviar</button></form>
<script>
let n = 0;
document.getElementById('send').addEventListener('click', () => {
  const t = document.getElementById('prompt'); const text = t.value; if (!text.trim()) return; t.value = ''; n++;
  const u = document.createElement('div'); u.dataset.role = 'user'; u.dataset.id = 'u' + n; u.textContent = text;
  document.getElementById('log').append(u);
  const stop = document.createElement('button'); stop.id = 'stop'; stop.type = 'button'; stop.textContent = 'Parar';
  document.getElementById('f').append(stop);
  const a = document.createElement('div'); a.dataset.role = 'assistant'; a.dataset.id = 'a' + n;
  document.getElementById('log').append(a);
  const words = ('Respuesta ' + n + ' a «' + text + '»: ' + 'uno dos tres cuatro cinco seis siete ocho').split(' ');
  let i = 0;
  const tick = setInterval(() => {
    a.textContent += (i ? ' ' : '') + words[i++];
    if (i >= words.length) { clearInterval(tick); stop.remove(); history.replaceState(null, '', '/c/conv' + n + 'abcdef'); }
  }, 120);
});
</script></body></html>`;

let http, origin, browser;
const cfg = (name) => ({
  title: `Chat simulado ${name}`, origin, home: `${origin}/`, conversationPath: '^/c/[\\w-]{8,}', calibrated: true,
  submit: 'button', editor: ['textarea#prompt'], send: ['button#send'], stop: ['button#stop'],
  user: ['[data-role=user]'], assistant: ['[data-role=assistant]'], idAttr: ['data-id'], loggedOut: [], blocked: [],
});

function contentsOf(page) {
  return {
    isDestroyed: () => page.isClosed(), getURL: () => page.url(), focus: async () => {},
    loadURL: (u) => page.goto(u), executeJavaScript: (expr) => page.evaluate(expr),
    insertText: (t) => page.keyboard.insertText(t),
    sendInputEvent: async (ev) => { if (ev.type === 'keyDown') await page.keyboard.down('Enter'); else await page.keyboard.up('Enter'); },
  };
}

async function newChat(name) {
  const page = await browser.newPage();
  await page.goto(`${origin}/`);
  return new (makeDeclarativeAdapter(cfg(name)))(contentsOf(page));
}

before(async () => {
  http = createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(PAGE); });
  await new Promise((r) => http.listen(0, '127.0.0.1', r));
  origin = `http://127.0.0.1:${http.address().port}`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.EOLFI_E2E_BROWSER ? { executablePath: process.env.EOLFI_E2E_BROWSER } : { channel: process.env.EOLFI_E2E_CHANNEL || 'chrome' }) });
});
after(async () => { await browser?.close(); http?.close(); });

test('autodiagnóstico: encuentra editor, botón y mensajes sin escribir nada', async () => {
  const a = await newChat('A');
  const r = await a.selftest();
  assert.equal(r.ok, true, JSON.stringify(r.problems));
  assert.equal(r.groups.editor[0].visible, 1);
  assert.equal(await a.contents.executeJavaScript("document.querySelectorAll('[data-role=user]').length"), 0);
  // Selector desfasado → el autodiagnóstico lo dice.
  const broken = new (makeDeclarativeAdapter({ ...cfg('roto'), editor: ['textarea#ya-no-existe'] }))(a.contents);
  const r2 = await broken.selftest();
  assert.equal(r2.ok, false);
  assert.match(r2.problems[0], /editor/);
});

test('envío con streaming: el texto llega a trozos y la respuesta final está completa', async () => {
  const a = await newChat('B');
  const partials = [];
  const text = await a.send('hola\r\nmundo', undefined, 'c1', (t) => partials.push(t));
  assert.match(text, /^Respuesta 1 a «hola mundo»: uno dos .* ocho$/s);
  assert.ok(partials.length >= 3, `parciales: ${partials.length}`);
  assert.ok(partials.every((p, i) => i === 0 || p.length >= partials[i - 1].length), 'el texto parcial solo crece');
  assert.ok(partials.at(-1).endsWith('ocho'));
  // La URL de la conversación queda guardada y la siguiente petición vuelve a ella.
  assert.match(a.urls.get('c1'), /\/c\/conv1abcdef$/);
  const second = await a.send('otra', undefined, 'c1');
  assert.match(second, /^Respuesta 2 a «otra»/);
});

test('comparativa: el mismo mensaje a dos chats con una sola aprobación', async () => {
  const [a, b] = [await newChat('C'), await newChat('D')];
  let approvals = 0;
  const { server, port } = await startBridgeServer({
    adapters: { a: async () => a, b: async () => b }, token: 't'.repeat(64), panelToken: 'p'.repeat(64),
    approve: async (prov) => { approvals++; assert.equal(prov, 'a+b'); return true; },
  });
  try {
    const r = await fetch(`http://127.0.0.1:${port}/v1/compare`, { method: 'POST',
      headers: { Authorization: `Bearer ${'t'.repeat(64)}` },
      body: JSON.stringify({ providers: ['a', 'b'], prompt: 'compara esto', conversation: 'cmp1' }) });
    const data = await r.json();
    assert.equal(r.status, 200, JSON.stringify(data));
    assert.equal(approvals, 1);
    assert.match(data.results.a.text, /«compara esto»/);
    assert.match(data.results.b.text, /«compara esto»/);
  } finally { server.close(); }
});

test('descubrir: lista editores, botones y atributos de mensaje sin leer su texto', async () => {
  const a = await newChat('E');
  await a.send('secreto que no debe salir', undefined, 'c9');
  const d = await a.discover();
  assert.ok(d.editors.some((e) => e.id === 'prompt' && e.tag === 'textarea'));
  assert.ok(d.buttons.some((b) => b.id === 'send'));
  assert.ok(d.message_attributes['data-role=user'] >= 1 && d.message_attributes['data-role=assistant'] >= 1);
  assert.doesNotMatch(JSON.stringify(d), /secreto/);
});
