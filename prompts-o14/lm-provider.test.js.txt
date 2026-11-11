'use strict';
// O14: Eolas como modelo de VS Code, para que el chat (y @eolfi) funcione sin sesión de Copilot.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { VENDOR, toOpenAI, makeEolasProvider, registerEolasModel } = require('../lm-provider');
const pkg = require('../package.json');

class TextPart { constructor(value) { this.value = value; } }
class ToolCallPart { constructor(callId, name, input) { this.callId = callId; this.name = name; this.input = input; } }
class ToolResultPart { constructor(callId, content) { this.callId = callId; this.content = content; } }
const vscode = { LanguageModelTextPart: TextPart, LanguageModelToolCallPart: ToolCallPart, LanguageModelToolResultPart: ToolResultPart };

test('package.json declara el proveedor «eolas» que registra la extensión', () => {
  assert.equal(VENDOR, 'eolas');
  assert.ok(pkg.contributes.languageModelChatProviders.some((p) => p.vendor === VENDOR && p.displayName));
});

test('mensajes de VS Code → formato OpenAI, con llamadas y resultados de herramientas', () => {
  const msgs = toOpenAI(vscode, [
    { role: 1, content: [new TextPart('lee a.py')] },
    { role: 2, content: [new TextPart('voy'), new ToolCallPart('c1', 'eolfi_read_file', { path: 'a.py' })] },
    { role: 1, content: [new ToolResultPart('c1', [new TextPart('print(1)')])] },
    { role: 3, content: [new TextPart('sé breve')] },
  ]);
  assert.deepEqual(msgs, [
    { role: 'user', content: 'lee a.py' },
    { role: 'assistant', content: 'voy', tool_calls: [{ id: 'c1', type: 'function', function: { name: 'eolfi_read_file', arguments: '{"path":"a.py"}' } }] },
    { role: 'tool', tool_call_id: 'c1', name: 'eolfi_read_file', content: 'print(1)' },
    { role: 'system', content: 'sé breve' },
  ]);
});

test('el modelo se anuncia con herramientas y con los límites de la configuración local', async () => {
  const p = makeEolasProvider({ vscode, localModel: {}, modelId: 'gemma-4-12b-it:latest', limits: () => ({ ctx: 32768, maxTokens: 4096 }) });
  const [m] = await p.provideLanguageModelChatInformation({}, {});
  assert.equal(m.id, 'gemma-4-12b-it:latest');
  assert.equal(m.capabilities.toolCalling, true);
  assert.equal(m.maxInputTokens, 32768 - 4096);
  assert.equal(m.maxOutputTokens, 4096);
});

test('respuesta: texto y llamadas a herramientas llegan a VS Code; las herramientas y la cancelación pasan al modelo local', async () => {
  const seen = {};
  const localModel = { chatTools: async (messages, tools, token) => { Object.assign(seen, { messages, tools, token });
    return { content: 'hecho', tool_calls: [{ id: 'x1', name: 'eolfi_list_files', arguments: { glob: '**/*.py' } }] }; } };
  const p = makeEolasProvider({ vscode, localModel, modelId: 'm' });
  const parts = [];
  const token = { isCancellationRequested: false };
  await p.provideLanguageModelChatResponse({}, [{ role: 1, content: [new TextPart('hola')] }],
    { tools: [{ name: 'eolfi_list_files', description: 'lista', inputSchema: { type: 'object' } }] }, { report: (x) => parts.push(x) }, token);
  assert.deepEqual(seen.tools, [{ name: 'eolfi_list_files', description: 'lista', inputSchema: { type: 'object' } }]);
  assert.equal(seen.token, token);
  assert.ok(parts[0] instanceof TextPart && parts[0].value === 'hecho');
  assert.ok(parts[1] instanceof ToolCallPart);
  assert.deepEqual([parts[1].callId, parts[1].name, parts[1].input], ['x1', 'eolfi_list_files', { glob: '**/*.py' }]);
});

test('sin la API en VS Code no se registra nada; con ella, se registra «eolas» una vez', async () => {
  const subs = [];
  assert.equal(registerEolasModel({ ...vscode, lm: {} }, { subscriptions: subs }, {}, { modelId: 'm' }), false);
  assert.equal(subs.length, 0);
  const reg = [];
  const ok = registerEolasModel({ ...vscode, lm: { registerLanguageModelChatProvider: (v, prov) => { reg.push([v, prov]); return { dispose() {} }; } } },
    { subscriptions: subs }, {}, { modelId: 'm' });
  assert.equal(ok, true);
  assert.equal(reg.length, 1);
  assert.equal(reg[0][0], 'eolas');
  assert.equal(typeof reg[0][1].provideLanguageModelChatResponse, 'function');
  assert.equal(subs.length, 1);
  assert.ok(await reg[0][1].provideTokenCount({}, 'abcdefg') > 0);
});
