'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { makeHandler } = require('../core');

// «vscode» falso con lo justo de la Language Model API.
function fakeVscode({ replies, tools = [] }) {
  class TextPart { constructor(v) { this.value = v; } }
  class ToolCallPart { constructor(callId, name, input) { Object.assign(this, { callId, name, input }); } }
  class ToolResultPart { constructor(callId, content) { Object.assign(this, { callId, content }); } }
  const seen = { requests: [], invoked: [] };
  const model = {
    id: 'copilot-gpt-x', family: 'gpt-x', name: 'GPT X', vendor: 'copilot', maxInputTokens: 100000,
    async sendRequest(msgs, opts) {
      seen.requests.push({ msgs: msgs.map((m) => ({ role: m.role, content: m.content })), tools: (opts.tools || []).map((t) => t.name) });
      const parts = replies.shift();
      return { stream: (async function* gen() { for (const p of parts) yield p(TextPart, ToolCallPart); })() };
    },
  };
  const vscode = {
    version: '1.145.0',
    LanguageModelTextPart: TextPart, LanguageModelToolCallPart: ToolCallPart, LanguageModelToolResultPart: ToolResultPart,
    LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }), Assistant: (c) => ({ role: 'assistant', content: c }) },
    CancellationTokenSource: class { constructor() { this.token = {}; } cancel() {} dispose() {} },
    LanguageModelError: class extends Error {},
    lm: {
      selectChatModels: async () => [model], tools,
      invokeTool: async (name, opts) => { seen.invoked.push({ name, input: opts.input }); return { content: [new TextPart(`resultado de ${name}`)] }; },
    },
  };
  return { vscode, seen };
}

async function serve(handler) {
  const srv = http.createServer(handler);
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;
  return { srv, base };
}

const T = 'k'.repeat(64);
const call = (base, path, body, token = T) => fetch(base + path, { method: body ? 'POST' : 'GET',
  headers: { Authorization: `Bearer ${token}` }, body: body && JSON.stringify(body) });

test('autenticación, Host y modelos', async () => {
  const { vscode } = fakeVscode({ replies: [] });
  const { srv, base } = await serve(makeHandler({ vscode, token: T }));
  try {
    assert.equal((await call(base, '/v1/status', null, 'malo')).status, 401);
    const st = await (await call(base, '/v1/status')).json();
    assert.deepEqual([st.ok, st.models], [true, 1]);
    const m = await (await call(base, '/v1/models')).json();
    assert.equal(m.models[0].family, 'gpt-x');
    const r = await new Promise((res) => http.get({ host: '127.0.0.1', port: srv.address().port, path: '/v1/status',
      headers: { Host: 'evil.com', Authorization: `Bearer ${T}` } }, (x) => { x.resume(); res(x.statusCode); }));
    assert.equal(r, 421);
  } finally { srv.close(); }
});

test('chat: el mensaje de sistema va delante del primero del usuario', async () => {
  const { vscode, seen } = fakeVscode({ replies: [[(Text) => new Text('{"ok": '), (Text) => new Text('true}')]] });
  const { srv, base } = await serve(makeHandler({ vscode, token: T }));
  try {
    const r = await (await call(base, '/v1/chat', { messages: [{ role: 'system', content: 'Eres útil.' }, { role: 'user', content: 'Hola' }] })).json();
    assert.equal(r.text, '{"ok": true}');
    assert.equal(r.model.id, 'copilot-gpt-x');
    assert.deepEqual(seen.requests[0].msgs, [{ role: 'user', content: 'Eres útil.\n\nHola' }]);
  } finally { srv.close(); }
});

test('herramientas: solo las permitidas, y el ciclo de llamada funciona', async () => {
  const tools = [{ name: 'buscar_archivos', description: 'busca', inputSchema: {} }, { name: 'terminal', description: 'ejecuta', inputSchema: {} }];
  const { vscode, seen } = fakeVscode({ tools, replies: [
    [(_T, Call) => new Call('c1', 'buscar_archivos', { patron: '*.py' })],
    [(Text) => new Text('Hay 3 archivos.')],
  ] });
  let allowed = ['buscar_archivos'];
  const { srv, base } = await serve(makeHandler({ vscode, token: T, getAllowedTools: () => allowed }));
  try {
    const denied = await call(base, '/v1/chat', { messages: [{ role: 'user', content: 'x' }], tools: ['terminal'] });
    assert.equal(denied.status, 403);
    const r = await (await call(base, '/v1/chat', { messages: [{ role: 'user', content: '¿Cuántos .py?' }], tools: ['buscar_archivos'] })).json();
    assert.equal(r.text, 'Hay 3 archivos.');
    assert.deepEqual(seen.invoked, [{ name: 'buscar_archivos', input: { patron: '*.py' } }]);
    assert.deepEqual(r.tool_calls, [{ name: 'buscar_archivos', ok: true }]);
    assert.deepEqual(seen.requests[0].tools, ['buscar_archivos']);
    const list = await (await call(base, '/v1/tools')).json();
    assert.deepEqual(list.tools.map((t) => [t.name, t.allowed]), [['buscar_archivos', true], ['terminal', false]]);
  } finally { srv.close(); }
});

test('modelo restringido para extensiones: se prueba el siguiente y se recuerda', async () => {
  const { chat } = require('../core');
  const mk = (id, max, fail) => ({ id, family: id, name: id, vendor: 'copilot', maxInputTokens: max,
    async sendRequest() {
      return { stream: (async function* g() { if (fail) throw new Error(`Model ${id} is only available to VS Code core.`); yield 'OK'; })() }; } });
  const models = [mk('chico', 10, false), mk('luna', 900, true), mk('auto', 999, false), mk('grande', 500, false)];
  const vscode = { lm: { selectChatModels: async () => models, tools: [] },
    LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }), Assistant: (c) => ({ role: 'assistant', content: c }) } };
  const logs = [];
  const r = await chat(vscode, { messages: [{ role: 'user', content: 'hola' }] }, [], {}, (m) => logs.push(m));
  assert.equal(r.text, 'OK');
  assert.equal(r.model.id, 'grande');   // ni «auto» ni el restringido
  assert.match(logs[0], /luna no disponible/);
  const r2 = await chat(vscode, { messages: [{ role: 'user', content: 'otra' }] }, [], {}, () => {});
  assert.equal(r2.model.id, 'grande');
});

test('si la petición falla a medias, lo escrito se deshace solo', async () => {
  const { chat } = require('../core');
  const written = [], undone = [];
  const actions = {
    journal_start: async () => ({ journal: 'J1' }),
    write: async (input) => { written.push(input); return { written: input.path }; },
    undo: async ({ journal }) => { undone.push(journal); return { restored: ['a.py'] }; },
  };
  class TP { constructor(v) { this.value = v; } }
  class CP { constructor(callId, name, input) { Object.assign(this, { callId, name, input }); } }
  let round = 0;
  const model = { id: 'm', family: 'm', name: 'm', vendor: 'copilot', maxInputTokens: 1000,
    async sendRequest() { round++;
      return { stream: (async function* g() {
        if (round === 1) { yield new CP('c1', 'eolfi_write_file', { path: 'a.py', content: 'x' }); return; }
        throw new Error('se cortó la conexión con Copilot');
      })() }; } };
  const vscode = { lm: { selectChatModels: async () => [model], tools: [] },
    LanguageModelTextPart: TP, LanguageModelToolCallPart: CP, LanguageModelToolResultPart: class { constructor(i, c) { this.c = c; } },
    LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }), Assistant: (c) => ({ role: 'assistant', content: c }) } };
  await assert.rejects(chat(vscode, { messages: [{ role: 'user', content: 'x' }], workspace_tools: true, auto_approve: true }, [], {}, () => {}, actions),
    /se cortó/);
  assert.deepEqual(written.map((w) => [w.path, w.auto, w.journal]), [['a.py', true, 'J1']]);
  assert.deepEqual(undone, ['J1']);
});
