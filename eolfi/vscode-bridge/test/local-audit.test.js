'use strict';
// El agente con herramientas sigue local; el comando /meta y el respaldo de auditoría usan el puente web.
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

test('modelo local principal: si Eolas falla, reintenta y para si no hay fallback autorizado', async () => {
  const sent = [];
  let calls = 0;
  const localModel = { name: () => 'gemma (local)', complete: async () => { calls++; throw new Error('modelo local gemma: HTTP 500 · out of memory'); } };
  const h = makeChatHandler({ vscode: fakeVs(sent), summarize: () => '', state: {}, getClient: async () => ({}), localModel, preferLocal: () => true });
  await assert.rejects(() => h.complete({}, 'revisa', null), /HTTP 500 · out of memory.*Copilot está desconectado/s);
  assert.strictEqual(calls, 2);
  assert.deepStrictEqual(sent, []);
});

test('respaldo Meta Web de auditoría: solo recibe el prompt del lote, nunca el historial ni herramientas', async () => {
  const sent = [];
  const state = {};
  const localModel = { name: () => 'Gemma local', complete: async () => { throw new Error('fallo Eolas'); } };
  const client = { metaWeb: async (prompt, conversation) => { sent.push({ prompt, conversation }); return { text: 'hallazgo del lote' }; } };
  const h = makeChatHandler({ vscode: fakeVs([]), summarize: () => '', state, getClient: async () => client, localModel, preferLocal: () => true });
  const lot = 'Audita solo este lote: function add(a, b) { return a - b; }';
  const result = await h.complete(client, { command: 'auditar', _auditBatch: true }, lot, null);
  assert.strictEqual(result, 'hallazgo del lote');
  assert.deepStrictEqual(sent.map(x => x.prompt), [lot]);
  assert.match(sent[0].conversation, /^panel-meta-\d{1,16}$/);
  assert.ok(state.usedModels.has('Meta AI Web (respaldo de auditoría)'));
});
test('si falla Meta, DeepSeek recibe únicamente el mismo lote', async () => {
  const sent = [];
  const localModel = { name: () => 'Gemma local', complete: async () => { throw new Error('Eolas caído'); } };
  const client = {
    metaWeb: async (prompt) => { sent.push(['meta', prompt]); throw new Error('sesión web caída'); },
    deepseekWeb: async (prompt, conversation) => { sent.push(['deepseek', prompt, conversation]); return { text: 'respuesta de DeepSeek' }; },
  };
  const h = makeChatHandler({ vscode: fakeVs([]), summarize: () => '', state: {}, getClient: async () => client, localModel, preferLocal: () => true });
  const lot = 'lote sintético único';
  assert.strictEqual(await h.complete(client, { _auditBatch: true }, lot, null), 'respuesta de DeepSeek');
  assert.deepStrictEqual(sent.map(x => x.slice(0, 2)), [['meta', lot], ['deepseek', lot]]);
  assert.match(sent[1][2], /^panel-deepseek-\d{1,16}$/);
});

test('si Eolas se cuelga, el lote termina el intento local y activa Meta Web', async () => {
  const old = process.env.EOLFI_AUDIT_LOCAL_TIMEOUT_MS;
  process.env.EOLFI_AUDIT_LOCAL_TIMEOUT_MS = '5';
  try {
    let calls = 0;
    let remotePrompt = '';
    const localModel = { name: () => 'Gemma local', complete: async (_prompt, token) => {
      calls++;
      return new Promise((resolve, reject) => token.onCancellationRequested(() => reject(new Error('cancelado'))));
    } };
    const client = { metaWeb: async (prompt) => { remotePrompt = prompt; return { text: 'respaldo disponible' }; } };
    const h = makeChatHandler({ vscode: fakeVs([]), summarize: () => '', state: {}, getClient: async () => client, localModel, preferLocal: () => true });
    const lot = 'lote sintético';
    assert.strictEqual(await h.complete(client, { _auditBatch: true }, lot, null), 'respaldo disponible');
    assert.strictEqual(calls, 1);
    assert.strictEqual(remotePrompt, lot);
  } finally {
    if (old === undefined) delete process.env.EOLFI_AUDIT_LOCAL_TIMEOUT_MS;
    else process.env.EOLFI_AUDIT_LOCAL_TIMEOUT_MS = old;
  }
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

test('pie con el modelo: el agente y la auditoría dicen si trabajó el modelo local o Copilot', async () => {
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-pie-'));
  fs.writeFileSync(path.join(root, 'a.py'), 'x = 1\n');
  process.env.EOLFI_AUDIT_DIR = path.join(root, '.audits');
  const sent = [];
  const localModel = { name: () => 'gemma (local)', complete: async (prompt) => (/Resumen y prioridades/.test(prompt) ? '## Resumen y prioridades\nbien'
    : '### `a.py`\n- **Propósito:** x'),
  chatTools: async () => ({ content: 'Hecho en local.', tool_calls: [] }) };
  const vs = { ...fakeVs(sent), workspace: { workspaceFolders: [{ uri: { fsPath: root } }] }, window: {} };
  const actions = { append: async ({ path: p, content }) => { const f = path.join(root, p); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.appendFileSync(f, content); return { appended: f }; }, open: async () => ({}) };
  const h = makeChatHandler({ vscode: vs, summarize: () => '', state: {}, getClient: async () => ({}), localModel, actions,
    preferLocal: () => true, showModel: () => true });
  let md = '';
  const s = { markdown: (m) => { md += String(m?.value ?? m); }, progress: () => {}, button: () => {}, reference: () => {}, anchor: () => {} };
  await h({ prompt: 'hola' }, { history: [] }, s, {});
  assert.match(md, /_Modelo: gemma \(local\) · en tu equipo, sin Copilot\._/);
  md = '';
  await h({ command: 'auditar', prompt: root }, { history: [] }, s, {});
  assert.match(md, /_Modelos usados: gemma \(local\) · en tu equipo\._/);
  assert.deepStrictEqual(sent, []);
});
