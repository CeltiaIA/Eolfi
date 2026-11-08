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
  const m = makeLocalModel({ fetchFn, options: () => ({ num_ctx: 12288, num_gpu: 20, num_thread: 4, temperature: 0.2 }) });
  assert.strictEqual(await m.complete('revisa'), '### `a.py`\n- ok');
  assert.strictEqual(m.name(), 'gemma-4-12b-it:latest (llama.cpp local)');
  // Eolas decide capas en GPU e hilos: Eolfi solo pide contexto y temperatura.
  assert.deepStrictEqual(calls.at(-1)[1].options, { num_ctx: 12288, temperature: 0.2 });
});

test('llama-server propio (API de OpenAI en /v1/*) si Eolas no está', async () => {
  const fetchFn = async (url) => {
    if (url.includes(':11435')) throw new Error('ECONNREFUSED');
    if (url.endsWith(':8080/api/tags')) return reply(404, {});
    if (url.endsWith(':8080/v1/models')) return reply(200, { data: [{ id: 'qwen2.5-coder-7b-instruct-q4_k_m.gguf' }] });
    if (url.endsWith(':8080/v1/chat/completions')) return reply(200, { choices: [{ message: { content: 'revisado' } }] });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn, options: () => ({ num_ctx: 12288, num_gpu: 20, num_thread: 4, temperature: 0.2 }) });
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
  assert.equal('num_ctx' in sent, false);
  assert.equal('num_gpu' in sent, false);
  assert.equal('num_thread' in sent, false);
});

test('Gemma 4 vía Eolas: herramienta y razonamiento como texto en content', async () => {
  const calls = [];
  const content = '<|channel>thought\nVoy a leerlo.<channel|><|tool_call>call:eolfi_read_file{path:<|"|>notas.txt<|"|>,limit:20}<tool_call|>';
  const fetchFn = async (url, opts = {}) => {
    calls.push([url, opts.body && JSON.parse(opts.body)]);
    if (url.endsWith(':11435/api/tags')) return reply(200, { models: [{ name: 'gemma-4-12b-it:latest' }] });
    if (url.endsWith(':11435/api/chat')) return reply(200, { message: { content } });
    return reply(404, {});
  };
  const m = makeLocalModel({ fetchFn, options: () => ({ num_ctx: 12288, num_gpu: 20, num_thread: 4, temperature: 0.2 }) });
  const r = await m.chatTools([{ role: 'user', content: 'lee notas.txt' }], [{ name: 'eolfi_read_file', description: 'lee' }]);
  assert.deepStrictEqual(calls.find(([url]) => url.endsWith(':11435/api/chat'))[1].options,
    { num_ctx: 12288, temperature: 0.2 });
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

test('integración Eolas: modelo exacto, sin cambiar en silencio de modelo ni de servidor', async () => {
  const { EOLAS_URL, EOLAS_MODEL } = require('../local-model');
  assert.strictEqual(EOLAS_URL, 'http://127.0.0.1:11435');
  assert.strictEqual(EOLAS_MODEL, 'gemma-4-12b-it:latest');
  const seen = [];
  const fetchFn = async (url) => {
    seen.push(url);
    if (url.endsWith(':11435/api/tags')) return reply(200, { models: [{ name: 'qwen3:4b' }] });
    if (url.endsWith(':8090/v1/models')) return reply(200, { data: [{ id: 'gemma-4' }] });
    return reply(404, {});
  };
  let starts = 0;
  const starter = { plan: () => ({ exe: 'x', model: 'y' }), start: async () => { starts++; return 'http://127.0.0.1:8090'; } };
  const m = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, starter, allowStart: async () => false });
  await assert.rejects(m.complete('x'), /gemma-4-12b-it:latest no está disponible: http:\/\/127\.0\.0\.1:11435 anuncia qwen3:4b/);
  assert.strictEqual(starts, 0);
  assert.ok(!seen.some((u) => u.includes(':8090') || u.includes(':8080')));
  assert.match(m.diagnose().error, /anuncia qwen3:4b/);
});

test('con modelo pedido, /v1/models no toma el primero que haya', async () => {
  const fetchFn = async (url) => (url.endsWith('/v1/models') ? reply(200, { data: [{ id: 'gemma-4' }] }) : reply(404, {}));
  const m = makeLocalModel({ endpoints: ['http://127.0.0.1:8090'], model: 'gemma-4-12b-it:latest', fetchFn });
  assert.strictEqual(await m.locate(), null);
  await assert.rejects(m.complete('x'), /8090 anuncia gemma-4/);
});

test('Eolas: razonamiento como «think» (revisión con review_reasoning, agente con reasoning)', async () => {
  const bodies = [];
  const fetchFn = async (url, opts = {}) => {
    if (url.endsWith('/api/tags')) return reply(200, { models: [{ name: 'gemma-4-12b-it:latest' }] });
    if (url.endsWith('/api/chat')) { bodies.push(JSON.parse(opts.body)); return reply(200, { message: { content: 'ok' } }); }
    return reply(404, {});
  };
  const options = ({ review } = {}) => ({ num_ctx: 12288, num_gpu: 20, temperature: 0.2, chat_template_kwargs: { enable_thinking: !review } });
  const m = makeLocalModel({ endpoints: ['http://127.0.0.1:11435'], model: 'gemma-4-12b-it:latest', fetchFn, options });
  await m.complete('revisa');
  await m.chatTools([{ role: 'user', content: 'hola' }], []);
  assert.strictEqual(bodies[0].think, false);
  assert.strictEqual(bodies[1].think, true);
  assert.deepStrictEqual(bodies[0].options, { num_ctx: 12288, temperature: 0.2 });
});
