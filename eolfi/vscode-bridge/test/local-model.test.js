'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { makeLocalModel, pickModel, isLoopback, DEFAULT_ENDPOINTS } = require('../local-model');

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });

test('sin Ollama: Eolas (11435) y llama-server (8080), solo en este equipo', () => {
  assert.deepStrictEqual(DEFAULT_ENDPOINTS, ['http://127.0.0.1:11435', 'http://127.0.0.1:8080']);
  assert.ok(!DEFAULT_ENDPOINTS.some((u) => u.includes('11434')));
  assert.ok(isLoopback('http://localhost:8080') && !isLoopback('http://192.168.1.5:8080') && !isLoopback('https://ejemplo.es'));
  assert.strictEqual(pickModel(['nomic-embed', 'qwen3:4b', 'gemma-4-12b-it:latest']), 'gemma-4-12b-it:latest');
});

test('Eolas (llama.cpp detrás de su API /api/*)', async () => {
  const calls = [];
  const fetchFn = async (url, opts = {}) => {
    calls.push([url, opts.body && JSON.parse(opts.body)]);
    if (url.endsWith(':11435/api/tags')) return reply(200, { models: [{ name: 'gemma-4-12b-it:latest' }] });
    if (url.endsWith(':11435/api/chat')) return reply(200, { message: { content: '### `a.py`\n- ok' } });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn });
  assert.strictEqual(await m.complete('revisa'), '### `a.py`\n- ok');
  assert.strictEqual(m.name(), 'gemma-4-12b-it:latest (llama.cpp local)');
  assert.strictEqual(calls.at(-1)[1].options.num_ctx, 32768);
});

test('llama-server propio (API de OpenAI en /v1/*) si Eolas no está', async () => {
  const fetchFn = async (url) => {
    if (url.includes(':11435')) throw new Error('ECONNREFUSED');
    if (url.endsWith(':8080/api/tags')) return reply(404, {});
    if (url.endsWith(':8080/v1/models')) return reply(200, { data: [{ id: 'qwen2.5-coder-7b-instruct-q4_k_m.gguf' }] });
    if (url.endsWith(':8080/v1/chat/completions')) return reply(200, { choices: [{ message: { content: 'revisado' } }] });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn });
  assert.strictEqual(await m.complete('x'), 'revisado');
  assert.match(m.name(), /coder.*llama\.cpp local/);
});

test('sin servidor local: error claro', async () => {
  const m = makeLocalModel({ fetchFn: async () => { throw new Error('ECONNREFUSED'); } });
  await assert.rejects(m.complete('x'), /no hay modelo local llama\.cpp/);
});

test('chatTools con llama-server (API OpenAI): envía las herramientas y lee las llamadas', async () => {
  let sent = null;
  const fetchFn = async (url, opts = {}) => {
    if (url.includes(':11435')) throw new Error('ECONNREFUSED');
    if (url.endsWith(':8080/api/tags')) return reply(404, {});
    if (url.endsWith(':8080/v1/models')) return reply(200, { data: [{ id: 'qwen3.5-4b' }] });
    if (url.endsWith('/v1/chat/completions')) {
      sent = JSON.parse(opts.body);
      return reply(200, { choices: [{ message: { content: '', tool_calls: [{ id: 't1', type: 'function', function: { name: 'eolfi_read_file', arguments: '{"path":"a.py"}' } }] } }] });
    }
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn });
  const r = await m.chatTools([{ role: 'user', content: 'lee a.py' }], [{ name: 'eolfi_read_file', description: 'lee', inputSchema: { type: 'object', properties: { path: { type: 'string' } } } }]);
  assert.deepStrictEqual(r.tool_calls, [{ id: 't1', name: 'eolfi_read_file', arguments: { path: 'a.py' } }]);
  assert.strictEqual(sent.tools[0].function.name, 'eolfi_read_file');
  assert.strictEqual(sent.tool_choice, 'auto');
  assert.deepStrictEqual(sent.chat_template_kwargs, { enable_thinking: false });
});

test('Gemma 4 vía Eolas: herramienta y razonamiento como texto en content', async () => {
  const content = '<|channel>thought\nVoy a leerlo.<channel|><|tool_call>call:eolfi_read_file{path:<|"|>notas.txt<|"|>,limit:20}<tool_call|>';
  const fetchFn = async (url) => {
    if (url.endsWith(':11435/api/tags')) return reply(200, { models: [{ name: 'gemma-4-12b-it:latest' }] });
    if (url.endsWith(':11435/api/chat')) return reply(200, { message: { content } });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn });
  const r = await m.chatTools([{ role: 'user', content: 'lee notas.txt' }], [{ name: 'eolfi_read_file', description: 'lee' }]);
  assert.strictEqual(r.tool_calls.length, 1);
  assert.strictEqual(r.tool_calls[0].name, 'eolfi_read_file');
  assert.deepStrictEqual(r.tool_calls[0].arguments, { path: 'notas.txt', limit: 20 });
  assert.strictEqual(r.content, '');
  assert.match(r.reasoning, /Voy a leerlo/);
});

test('Gemma: razonamiento con solo el cierre «<channel|>» no llega a la respuesta', async () => {
  const fetchFn = async (url) => {
    if (url.endsWith(':11435/api/tags')) return reply(200, { models: [{ name: 'gemma-4-12b-it:latest' }] });
    if (url.endsWith(':11435/api/chat')) return reply(200, { message: { content: 'Paso 1: leer.<channel|>CALABAZA-42' } });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn });
  const r = await m.chatTools([{ role: 'user', content: 'x' }], []);
  assert.strictEqual(r.content, 'CALABAZA-42');
  assert.match(r.reasoning, /Paso 1/);
  assert.strictEqual(await m.complete('x'), 'CALABAZA-42');
});
