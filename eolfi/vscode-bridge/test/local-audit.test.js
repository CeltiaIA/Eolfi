'use strict';
// Con «@eolfi /modelo local», la auditoría no debe pasar a Copilot cuando Eolas falla (gastaba la cuota de GitHub).
const test = require('node:test');
const assert = require('node:assert');
process.env.EOLFI_RATE_WAIT_SCALE = '0';
const { makeChatHandler } = require('../chat');
const { makeLocalModel } = require('../local-model');

function fakeVs(sent) {
  const model = { id: 'auto', name: 'Auto', family: 'auto', sendRequest: async () => { sent.push('copilot'); return { text: (async function* () { yield 'copilot'; })() }; } };
  return { lm: { selectChatModels: async () => [model] }, LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }) },
    workspace: { workspaceFolders: [], getConfiguration: () => ({ get: () => undefined }) }, window: {}, env: {} };
}

test('modelo local principal: si Eolas falla, reintenta y para sin usar Copilot', async () => {
  const sent = [];
  let calls = 0;
  const localModel = { name: () => 'gemma (local)', complete: async () => { calls++; throw new Error('modelo local gemma: HTTP 500 · out of memory'); } };
  const h = makeChatHandler({ vscode: fakeVs(sent), summarize: () => '', state: {}, getClient: async () => ({}), localModel, preferLocal: () => true });
  await assert.rejects(() => h.complete({}, 'revisa', null), /HTTP 500 · out of memory.*no paso a Copilot/s);
  assert.strictEqual(calls, 2);
  assert.deepStrictEqual(sent, []);
});

test('modelo local principal: un error de tamaño sube sin reintentar, para que la auditoría parta el lote', async () => {
  let calls = 0;
  const localModel = { name: () => 'gemma (local)', complete: async () => { calls++; throw new Error('modelo local gemma: HTTP 500 · input length exceeds the context length'); } };
  const h = makeChatHandler({ vscode: fakeVs([]), summarize: () => '', state: {}, getClient: async () => ({}), localModel, preferLocal: () => true });
  await assert.rejects(() => h.complete({}, 'revisa', null), /context length/);
  assert.strictEqual(calls, 1);
});

test('el error HTTP del modelo local incluye lo que dice el servidor', async () => {
  const fetchFn = async (url) => (url.endsWith('/api/tags') ? { ok: true, status: 200, json: async () => ({ models: [{ name: 'gemma-4-12b-it:latest' }] }) }
    : url.endsWith('/api/chat') ? { ok: false, status: 500, text: async () => '{"error":"model requires more system memory"}' } : { ok: false, status: 404 });
  const lm = makeLocalModel({ endpoints: ['http://127.0.0.1:11435'], fetchFn });
  await assert.rejects(() => lm.complete('hola'), /HTTP 500 · \{"error":"model requires more system memory"\}/);
});
