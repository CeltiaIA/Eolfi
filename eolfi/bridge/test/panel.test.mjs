// Credencial del panel separada, proveedor ocupado (409) y cancelación durante la aprobación.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startBridgeServer } from '../server.mjs';

const TOKEN = 'b'.repeat(64), PANEL = 'c'.repeat(64);
let srv, base, approvals = 0, release;
const sent = [];
const echo = { status: async () => ({ ok: true }), send: async (p) => { sent.push(p); return 'ok'; } };
const hang = { status: async () => ({ ok: true }), send: (p, signal) => new Promise((_, rej) => signal.addEventListener('abort', () => rej(signal.reason))) };

before(async () => {
  const r = await startBridgeServer({
    adapters: { deepseek: async () => echo, gemini: async () => hang, meta: async () => echo },
    token: TOKEN, panelToken: PANEL,
    approve: async (prov) => { approvals++; if (prov === 'meta') return new Promise((res) => { release = res; }); return true; },
    screens: { deepseek: async () => Buffer.from([0xff, 0xd8]) },
    inputs: { deepseek: async () => {} },
  });
  srv = r.server; base = `http://127.0.0.1:${r.port}`;
});
after(() => srv.close());

const call = (path, { method = 'GET', body, token = TOKEN, signal } = {}) => fetch(base + path, {
  method, body: body && JSON.stringify(body), signal, headers: { Authorization: `Bearer ${token}` } });

test('captura y entrada directa: solo con la credencial del panel', async () => {
  assert.equal((await call('/v1/screen?provider=deepseek')).status, 403);
  assert.equal((await call('/v1/input', { method: 'POST', body: { provider: 'deepseek', type: 'key', key: 'Enter' } })).status, 403);
  assert.equal((await call('/v1/screen?provider=deepseek', { token: PANEL })).status, 200);
  assert.equal((await call('/v1/input', { method: 'POST', token: PANEL, body: { provider: 'deepseek', type: 'key', key: 'Enter' } })).status, 200);
});

test('source "panel" con el token de Eolfi sigue pidiendo aprobación', async () => {
  const before = approvals;
  await (await call('/v1/chat', { method: 'POST', body: { provider: 'deepseek', prompt: 'hola', source: 'panel' } })).json();
  assert.equal(approvals, before + 1);
  await (await call('/v1/chat', { method: 'POST', token: PANEL, body: { provider: 'deepseek', prompt: 'hola', source: 'panel' } })).json();
  assert.equal(approvals, before + 1);
});

test('proveedor ocupado: 409', async () => {
  const ctl = new AbortController();
  const first = call('/v1/chat', { method: 'POST', body: { provider: 'gemini', prompt: 'largo' }, signal: ctl.signal }).catch(() => {});
  await new Promise((r) => setTimeout(r, 100));
  assert.equal((await call('/v1/chat', { method: 'POST', body: { provider: 'gemini', prompt: 'otro' } })).status, 409);
  ctl.abort();
  await first;
});

test('cancelado mientras espera la aprobación: no se envía', async () => {
  const ctl = new AbortController();
  const p = call('/v1/chat', { method: 'POST', body: { provider: 'meta', prompt: 'secreto' }, signal: ctl.signal }).catch(() => {});
  await new Promise((r) => setTimeout(r, 100));
  ctl.abort();
  await p;
  await new Promise((r) => setTimeout(r, 50));
  release(true);
  await new Promise((r) => setTimeout(r, 100));
  assert.ok(!sent.includes('secreto'));
});
