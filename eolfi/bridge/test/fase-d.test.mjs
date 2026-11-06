// Fase D del plan de mejoras: pruebas que faltaban en el puente.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { createApprover } from '../approval.mjs';
import { DEEPSEEK_ORIGIN, DeepseekAdapter } from '../adapters/deepseek.mjs';
import { CdpContents, CdpSession, PipeConnection } from '../engine/chrome.mjs';
import { startBridgeServer } from '../server.mjs';

// ------------------------------------------------------------------ aprobación (antes atrapada en main.mjs)
test('aprobación: 30 minutos solo para esa conversación, visible y revocable', async () => {
  let t = 1000, answer = 1, shown = 0;
  const a = createApprover({ now: () => t, showMessageBox: async () => { shown++; return { response: answer }; } });
  assert.equal(await a.approve('meta', 'hola', undefined, 'c1'), true);
  answer = 2;
  assert.equal(await a.approve('meta', 'otra', undefined, 'c1'), true, 'c1 tiene permiso: sin diálogo');
  assert.equal(shown, 1);
  assert.equal(await a.approve('meta', 'otra', undefined, 'c2'), false, 'c2 no hereda el permiso de c1');
  assert.deepEqual(Object.keys(a.grants()), ['meta']);
  assert.equal(a.revoke('meta', 'c1'), 1);
  assert.deepEqual(a.grants(), {});
  t += 31 * 60 * 1000;
  assert.equal(a.preview('x'.repeat(5000)).includes('caracteres ocultos'), true);
});

test('aprobación: con la señal ya abortada no se abre diálogo y una respuesta tardía no concede nada', async () => {
  const c = new AbortController();
  c.abort();
  let shown = 0;
  const a = createApprover({ showMessageBox: async () => { shown++; return { response: 1 }; } });
  assert.equal(await a.approve('meta', 'x', c.signal), false);
  assert.equal(shown, 0);
  const late = new AbortController();
  const b = createApprover({ showMessageBox: async () => { late.abort(); return { response: 1 }; } });
  assert.equal(await b.approve('meta', 'x', late.signal, 'c'), false);
  assert.deepEqual(b.grants(), {});
});

// ------------------------------------------------------------------ send() de DeepSeek con un navegador falso
function fakeDeepseek({ cancelAfterWrite = null, url = `${DEEPSEEK_ORIGIN}/` } = {}) {
  const log = { inserted: [], keys: [], loads: [] };
  let here = url, draft = '', rows = [];
  const contents = {
    isDestroyed: () => false, getURL: () => here, focus: async () => {},
    loadURL: async (u) => { log.loads.push(u); here = u; },
    executeJavaScript: async (expr) => (expr === 'location.origin' ? DEEPSEEK_ORIGIN : null),
    insertText: async (text) => { log.inserted.push(text); draft = text; cancelAfterWrite?.abort(new Error('cancelado')); },
    sendInputEvent: async (ev) => {
      log.keys.push(ev.type);
      if (ev.type === 'keyUp') {
        rows = [{ assistant: false, text: draft, key: 'u1', complete: true },
          { assistant: true, text: 'respuesta', key: 'a1', complete: true }];
        draft = '';
        here = `${DEEPSEEK_ORIGIN}/a/chat/s/abc123`;
      }
    },
  };
  const a = new DeepseekAdapter(contents);
  a.readState = async () => ({ draft, blocked: false, rows });
  a.evaluate = async () => null;
  return { a, log, setUrl: (u) => { here = u; } };
}

test('send(): CRLF se normaliza antes de escribir', async () => {
  const { a, log } = fakeDeepseek();
  assert.equal(await a.send('linea1\r\nlinea2', undefined, 'c1'), 'respuesta');
  assert.ok(!log.inserted[0].includes('\r'));
  assert.ok(log.inserted[0].endsWith('linea1\nlinea2'));
});

test('send(): cancelado tras escribir → conversación «dudosa» hasta reset()', async () => {
  const c = new AbortController();
  const { a, log } = fakeDeepseek({ cancelAfterWrite: c });
  await assert.rejects(a.send('hola', c.signal, 'c1'));
  assert.deepEqual(log.keys, [], 'no se pulsa Intro si se canceló');
  await assert.rejects(a.send('otra', undefined, 'c1'), /interrumpido/);
  assert.equal(a.reset('c1'), true);
});

test('send(): si el usuario cambió de chat, se vuelve a la conversación pedida', async () => {
  const { a, log, setUrl } = fakeDeepseek();
  await a.send('primero', undefined, 'c1');
  setUrl(`${DEEPSEEK_ORIGIN}/a/chat/s/OTRO`);
  await a.send('segundo', undefined, 'c1');
  assert.deepEqual(log.loads, [`${DEEPSEEK_ORIGIN}/a/chat/s/abc123`]);
});

// ------------------------------------------------------------------ tramas de la tubería CDP
function fakeProc() {
  const proc = new EventEmitter();
  const toBrowser = new PassThrough(), fromBrowser = new PassThrough();
  proc.stdio = [null, null, null, toBrowser, fromBrowser];
  return { proc, toBrowser, fromBrowser };
}

test('PipeConnection: tramas partidas, juntas y corruptas', async () => {
  const { proc, toBrowser, fromBrowser } = fakeProc();
  const conn = new PipeConnection(proc);
  const sent = [];
  toBrowser.on('data', (d) => sent.push(...String(d).split('\0').filter(Boolean).map((x) => JSON.parse(x))));
  const p1 = conn.send('A.uno', {});
  const p2 = conn.send('A.dos', {});
  await new Promise((r) => setImmediate(r));
  const [m1, m2] = sent;
  const r1 = JSON.stringify({ id: m1.id, result: { n: 1 } }), r2 = JSON.stringify({ id: m2.id, result: { n: 2 } });
  fromBrowser.write(r1.slice(0, 5));                       // partida
  fromBrowser.write(r1.slice(5) + '\0{roto\0' + r2 + '\0'); // resto + corrupta + otra junta
  assert.deepEqual(await p1, { n: 1 });
  assert.deepEqual(await p2, { n: 2 });
});

test('CdpSession: al cerrarse quita sus manejadores', () => {
  const { proc } = fakeProc();
  const conn = new PipeConnection(proc);
  const s = new CdpSession(conn, 'S1');
  s.on('Page.x', () => {});
  conn.on('S1|#closed', () => {});
  s._markClosed();
  assert.ok(![...conn.handlers.keys()].some((k) => k.startsWith('S1|')));
});

// ------------------------------------------------------------------ loadURL espera SU loaderId
test('loadURL: espera el load de su navegación, no el de otra', async () => {
  const handlers = [];
  const cdp = {
    on: (_e, h) => handlers.push(h), off: () => {},
    send: async (method) => (method === 'Page.navigate' ? { loaderId: 'L2' } : {}),
  };
  const c = Object.create(CdpContents.prototype);
  Object.assign(c, { cdp, targetId: 'T' });
  let done = false;
  const p = c.loadURL('https://x/').then(() => { done = true; });
  await new Promise((r) => setTimeout(r, 20));
  handlers.forEach((h) => h({ name: 'load', frameId: 'T', loaderId: 'L1' }));   // otra navegación
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(done, false);
  handlers.forEach((h) => h({ name: 'load', frameId: 'T', loaderId: 'L2' }));
  await p;
  assert.equal(done, true);
});

// ------------------------------------------------------------------ 421 y since inválido
test('servidor: Host ajeno 421 y since inválido 400', async () => {
  const T = 'a'.repeat(64);
  const { server, port } = await startBridgeServer({ adapters: {}, approve: async () => true, token: T, panelToken: 'b'.repeat(64) });
  try {
    const http = await import('node:http');
    const status = (path, host) => new Promise((res) => {
      http.get({ host: '127.0.0.1', port, path, headers: { Host: host, Authorization: `Bearer ${T}` } }, (r) => { r.resume(); res(r.statusCode); });
    });
    assert.equal(await status('/v1/status', 'evil.com'), 421);
    assert.equal(await status('/v1/events?since=-1', '127.0.0.1'), 400);
    assert.equal(await status('/v1/events?since=abc', '127.0.0.1'), 400);
  } finally { server.close(); }
});
