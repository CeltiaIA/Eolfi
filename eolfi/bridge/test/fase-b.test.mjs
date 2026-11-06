// Fase B del plan de mejoras: puente robusto (M1, M3, M7, M9).
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBridgeServer } from '../server.mjs';

const TOKEN = 'e'.repeat(64), PANEL = 'f'.repeat(64);
let srv, base, revoked = [];
const adapter = { uncertain: new Set(['c1']), status: async () => ({ ok: true }), send: async () => 'ok',
  reset(conv) { return this.uncertain.delete(conv); } };

before(async () => {
  const closed = Object.assign(new Error('Ventana cerrada'), { status: 404 });
  const r = await startBridgeServer({
    adapters: { deepseek: async () => adapter }, token: TOKEN, panelToken: PANEL,
    approve: async () => true,
    screens: { deepseek: async () => { throw closed; } },
    inputs: { deepseek: async () => { throw closed; } },
    revoke: (p, c) => { revoked.push([p, c]); return 1; },
  });
  srv = r.server; base = `http://127.0.0.1:${r.port}`;
});
after(() => srv.close());

const call = (path, { method = 'GET', body, token = TOKEN } = {}) => fetch(base + path, {
  method, body: typeof body === 'string' ? body : body && JSON.stringify(body), headers: { Authorization: `Bearer ${token}` } });

test('M1: la vista en directo de una ventana cerrada responde 404 y no la reabre', async () => {
  const r = await call('/v1/screen?provider=deepseek', { token: PANEL });
  assert.equal(r.status, 404);
  assert.match((await r.json()).error, /cerrada/);
  const i = await call('/v1/input', { method: 'POST', token: PANEL, body: { provider: 'deepseek', type: 'key', key: 'Enter' } });
  assert.equal(i.status, 404);
});

test('M3: /v1/reset levanta el estado «dudoso» de una conversación', async () => {
  const r = await call('/v1/reset', { method: 'POST', body: { provider: 'deepseek', conversation: 'c1' } });
  assert.deepEqual(await r.json(), { ok: true, reset: true });
  assert.equal(adapter.uncertain.has('c1'), false);
});

test('M9: los permisos temporales se pueden revocar', async () => {
  const r = await call('/v1/revoke', { method: 'POST', body: { provider: 'deepseek', conversation: 'c2' } });
  assert.equal((await r.json()).revoked, 1);
  assert.deepEqual(revoked.at(-1), ['deepseek', 'c2']);
});

test('M7: un cuerpo demasiado grande recibe un 413 legible', async () => {
  const r = await call('/v1/chat', { method: 'POST', body: JSON.stringify({ provider: 'deepseek', prompt: 'x'.repeat(200 * 1024) }) })
    .catch((e) => ({ status: 'cortada', e }));
  assert.equal(r.status, 413);
});
