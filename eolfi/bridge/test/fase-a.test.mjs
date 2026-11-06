// Fase A del plan de mejoras: aprobación caducada, conversación correcta y saltos de línea.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startBridgeServer } from '../server.mjs';
import { ensureConversation, unixNewlines } from '../adapters/core.mjs';

const TOKEN = 'd'.repeat(64);

test('A1: aprobación caducada cierra el diálogo y una respuesta tardía no concede nada', async () => {
  let seen = null; const sent = [];
  const { server, port } = await startBridgeServer({
    adapters: { deepseek: async () => ({ status: async () => ({ ok: true }), send: async (p) => { sent.push(p); return 'ok'; } }) },
    token: TOKEN, panelToken: 'p'.repeat(64), approveTimeoutMs: 150,
    // Diálogo que el usuario «responde» tarde: Permitir, cuando ya caducó.
    approve: (prov, prompt, signal) => { seen = signal; return new Promise((res) => setTimeout(() => res(true), 400)); },
  });
  try {
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat`, { method: 'POST', headers: { Authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify({ provider: 'deepseek', prompt: 'hola' }) });
    assert.equal(r.status, 408);   // caducada: 408, no «denegada» (M7)
    assert.ok(seen?.aborted, 'la señal debe cerrar el diálogo al caducar');
    await new Promise((res) => setTimeout(res, 400));
    assert.equal(sent.length, 0);
    // El proveedor ya no está ocupado.
    const again = await fetch(`http://127.0.0.1:${port}/v1/chat`, { method: 'POST', headers: { Authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify({ provider: 'deepseek', prompt: 'otra' }) });
    assert.notEqual(again.status, 409);
  } finally { server.close(); }
});

function fakeContents(url) {
  const loads = [];
  return { loads, getURL: () => url, loadURL: async (u) => { loads.push(u); url = u; } };
}

test('A2: si el usuario navegó a otro chat, se vuelve a la conversación pedida', async () => {
  const adapter = { urls: new Map([['c1', 'https://chat.x/a/1']]), current: 'c1', lastUrl: 'https://chat.x/a/1' };
  const c = fakeContents('https://chat.x/a/OTRO');
  await ensureConversation(adapter, c, 'c1', 'https://chat.x/');
  assert.deepEqual(c.loads, ['https://chat.x/a/1']);
  // Conversación activa sin URL guardada y pestaña cambiada: chat nuevo, nunca el ajeno.
  const a2 = { urls: new Map(), current: 'default', lastUrl: 'https://chat.x/' };
  const c2 = fakeContents('https://chat.x/a/AJENO');
  await ensureConversation(a2, c2, 'default', 'https://chat.x/');
  assert.deepEqual(c2.loads, ['https://chat.x/']);
  // Ya en su sitio (solo cambia el #): no recarga.
  const c3 = fakeContents('https://chat.x/a/1#fin');
  await ensureConversation(adapter, c3, 'c1', 'https://chat.x/');
  assert.deepEqual(c3.loads, []);
});

test('A3: CRLF y CR sueltos pasan a LF', () => {
  assert.equal(unixNewlines('a\r\nb\rc\nd'), 'a\nb\nc\nd');
});
