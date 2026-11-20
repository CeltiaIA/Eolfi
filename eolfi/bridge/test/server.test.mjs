import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBridgeServer } from '../server.mjs';
import { freshReply } from '../adapters/core.mjs';

const TOKEN = 'a'.repeat(64), PANEL = 'p'.repeat(64);
let srv, base, approvals = [], allow = true;
const fake = {
  status: async () => ({ ok: true, detail: 'listo' }),
  send: async (prompt, signal, conv) => `eco(${conv}): ${prompt.slice(0, 10)}`,
};
const slow = { status: async () => ({ ok: false, detail: 'lento' }),
  send: (p, signal) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason))) };

before(async () => {
  const r = await startBridgeServer({ adapters: { deepseek: async () => fake, gemini: async () => slow }, token: TOKEN, panelToken: 'p'.repeat(64),
    approve: async (prov, prompt) => { approvals.push([prov, prompt.length]); return allow; },
    screens: { deepseek: async () => Buffer.from([0xff, 0xd8, 0xff, 0xd9]) } });
  srv = r.server; base = `http://127.0.0.1:${r.port}`;
});
after(() => srv.close());

const call = (path, { method = 'GET', body, token = TOKEN, host } = {}) => fetch(base + path, {
  method, body: body && JSON.stringify(body),
  headers: { Authorization: `Bearer ${token}`, ...(host ? { Host: host } : {}) } });

test('estado con token', async () => {
  const r = await (await call('/v1/status')).json();
  assert.deepEqual(r.providers.deepseek, { ok: true, detail: 'listo', busy: false });
  assert.equal(r.providers.gemini.ok, false);
});

test('sin token o token erróneo: 401', async () => {
  assert.equal((await call('/v1/status', { token: 'x' })).status, 401);
});

test('chat aprobado devuelve el texto', async () => {
  const r = await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'hola mundo grande', conversation: 'c-1' } });
  assert.equal(r.status, 200);
  assert.equal((await r.json()).text, 'eco(c-1): hola mundo');
  assert.deepEqual(approvals.at(-1), ['deepseek', 17]);
});

test('chat denegado: 403', async () => {
  allow = false;
  const r = await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'x' } });
  allow = true;
  assert.equal(r.status, 403);
});

test('proveedor desconocido y conversación inválida', async () => {
  assert.equal((await call('/v1/chat', { method: 'POST', body: { provider: 'chatgpt', prompt: 'x' } })).status, 404);
  const r = await (await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'abc', conversation: '../x' } })).json();
  assert.equal(r.conversation, 'default');
});

test('cancelar la conexión aborta el envío', async () => {
  const ctrl = new AbortController();
  setTimeout(() => ctrl.abort(), 200);
  await assert.rejects(fetch(base + '/v1/chat', { method: 'POST', signal: ctrl.signal,
    headers: { Authorization: `Bearer ${TOKEN}` }, body: JSON.stringify({ provider: 'gemini', prompt: 'x' }) }));
});

test('comparativa cancelada durante la aprobación cierra el diálogo y no envía', async () => {
  let approvalStarted;
  const started = new Promise((resolve) => { approvalStarted = resolve; });
  let signal;
  let sends = 0;
  const adapter = { status: async () => ({ ok: true }), send: async () => { sends++; return 'enviado'; } };
  const { server, port } = await startBridgeServer({
    adapters: { one: async () => adapter, two: async () => adapter },
    token: TOKEN, panelToken: PANEL,
    approve: async (_provider, _prompt, pending) => { signal = pending; approvalStarted(); return new Promise(() => {}); },
  });
  try {
    const controller = new AbortController();
    const request = fetch(`http://127.0.0.1:${port}/v1/compare`, {
      method: 'POST', signal: controller.signal, headers: { Authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify({ providers: ['one', 'two'], prompt: 'hola' }),
    });
    await started;
    controller.abort();
    await assert.rejects(request);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(signal.aborted, true);
    assert.equal(sends, 0);
    const status = await (await fetch(`http://127.0.0.1:${port}/v1/status`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })).json();
    assert.equal(status.providers.one.busy, false);
    assert.equal(status.providers.two.busy, false);
  } finally { server.close(); }
});

test('freshReply exige una única respuesta nueva y completa', () => {
  assert.equal(freshReply(new Set(['a']), [{ id: 'a', text: 'x', complete: true }, { id: 'b', text: 'ok', complete: true }]), 'ok');
  assert.equal(freshReply(new Set(), [{ id: 'b', text: 'ok', complete: false }]), null);
  assert.throws(() => freshReply(new Set(), [{ id: 'b', text: '1', complete: true }, { id: 'c', text: '2', complete: true }]));
});

test('mensajes del panel no piden aprobación y quedan en el historial', async () => {
  allow = false;                                       // aunque se denegaría un envío automático
  const before = approvals.length;
  const r = await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'escrito a mano', conversation: 'panel-deepseek', source: 'panel' }, token: PANEL });
  allow = true;
  assert.equal(r.status, 200);
  assert.equal(approvals.length, before);
  const ev = await (await call('/v1/events?since=0')).json();
  const mine = ev.events.filter((e) => e.conversation === 'panel-deepseek');
  assert.deepEqual(mine.map((e) => [e.role, e.source]), [['user', 'panel'], ['assistant', 'panel']]);
  assert.equal(mine[1].text, 'eco(panel-deepseek): escrito a ');
  const later = await (await call(`/v1/events?since=${ev.last}`)).json();
  assert.deepEqual(later.events, []);
});

test('captura de pantalla por proveedor', async () => {
  const r = await call('/v1/screen?provider=deepseek', { token: PANEL });
  assert.equal(r.headers.get('content-type'), 'image/jpeg');
  assert.equal((await r.arrayBuffer()).byteLength, 4);
  assert.equal((await call('/v1/screen?provider=meta', { token: PANEL })).status, 404);
});

test('envío denegado queda registrado como error', async () => {
  allow = false;
  await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'auto' } });
  allow = true;
  const ev = await (await call('/v1/events?since=0')).json();
  assert.equal(ev.events.at(-1).role, 'error');
});

test('entrada remota: validada y reenviada', async () => {
  const got = [];
  const r = await startBridgeServer({ adapters: {}, approve: async () => true, token: TOKEN, panelToken: 'p'.repeat(64),
    inputs: { meta: async (ev) => { got.push(ev); } } });
  const b = `http://127.0.0.1:${r.port}`;
  const post = (body) => fetch(b + '/v1/input', { method: 'POST', headers: { Authorization: `Bearer ${PANEL}` }, body: JSON.stringify(body) });
  assert.equal((await post({ provider: 'meta', type: 'click', x: 0.5, y: 0.25 })).status, 200);
  assert.equal((await post({ provider: 'meta', type: 'click', x: 2, y: 0 })).status, 400);
  assert.equal((await post({ provider: 'meta', type: 'exec', x: 0, y: 0 })).status, 400);
  assert.equal((await post({ provider: 'gemini', type: 'click', x: 0, y: 0 })).status, 404);
  assert.equal((await post({ provider: 'meta', type: 'text', text: 'hola' })).status, 200);
  assert.deepEqual(got.map((e) => e.type), ['click', 'text']);
  r.server.close();
});

test('los cuerpos grandes reciben 413 y no procesan un JSON válido seguido de espacios', async () => {
  let sends = 0, inputs = 0, resets = 0, revokes = 0, approvals = 0;
  const adapter = { status: async () => ({ ok: true }), send: async () => { sends++; return 'ok'; },
    reset: () => { resets++; return true; } };
  const { server, port } = await startBridgeServer({
    adapters: { one: async () => adapter, two: async () => adapter },
    token: TOKEN, panelToken: PANEL,
    approve: async () => { approvals++; return true; },
    inputs: { one: async () => { inputs++; } },
    revoke: () => { revokes++; return 1; },
  });
  const post = (path, body, token = PANEL) => fetch(`http://127.0.0.1:${port}${path}`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body,
  });
  try {
    const cases = [
      ['/v1/compare', JSON.stringify({ providers: ['one', 'two'], prompt: 'hola' }) + ' '.repeat(129 * 1024)],
      ['/v1/reset', JSON.stringify({ provider: 'one' }) + ' '.repeat(4096)],
      ['/v1/revoke', JSON.stringify({ provider: 'one' }) + ' '.repeat(4096)],
      ['/v1/input', JSON.stringify({ provider: 'one', type: 'key', key: 'Enter' }) + ' '.repeat(65 * 1024)],
    ];
    for (const [path, body] of cases) assert.equal((await post(path, body)).status, 413, path);
    assert.deepEqual([sends, inputs, resets, revokes, approvals], [0, 0, 0, 0, 0]);
  } finally { server.close(); }
});
