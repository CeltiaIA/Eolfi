'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { makeLlamaStarter, findGguf } = require('../llama-starter');
const { makeLocalModel } = require('../local-model');

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });

function fakeServer() {
  const spawned = [];
  let healthy = false;
  const spawnFn = (exe, args) => {
    const p = new EventEmitter();
    p.exitCode = null;
    p.kill = () => { p.exitCode = 0; p.emit('exit', 0); };
    spawned.push({ exe, args, p });
    setTimeout(() => { healthy = true; }, 20);
    return p;
  };
  const fetchFn = async (url, opts = {}) => {
    const port = Number(new URL(url).port);
    if (!spawned.some((s) => s.args.includes(String(port)))) throw new Error('ECONNREFUSED');
    if (url.endsWith('/health')) return healthy ? reply(200, { status: 'ok' }) : reply(503, {});
    if (url.endsWith('/api/tags')) return reply(404, {});
    if (url.endsWith('/v1/models')) return reply(200, { data: [{ id: 'qwen3.5-4b-Q4_K_M' }] });
    if (url.endsWith('/v1/chat/completions')) return reply(200, { choices: [{ message: { content: `revisado en ${port}: ${JSON.parse(opts.body).messages[0].content}` } }] });
    return reply(404, {});
  };
  return { spawned, spawnFn, fetchFn };
}

test('elige el GGUF para código: familia y cuantización; descarta imagen, vocabularios y pequeños', () => {
  // Archivos pequeños (umbral bajado solo en la prueba) y la carpeta se borra al acabar: antes cada ejecución
  // dejaba ~2,9 GB en Temp.
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'gguf-'));
  try {
    const mk = (rel, kb) => { const p = path.join(d, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, Buffer.alloc(kb * 1024)); };
    const opts = { minBytes: 500 * 1024 };
    mk('qwen3.5-4b/qwen3.5-4b-Q8_0.gguf', 600);
    mk('qwen3.5-4b/qwen3.5-4b-Q4_K_M.gguf', 520);
    mk('image-models/qwen-image-Q4_K_M.gguf', 700);
    mk('vocab/ggml-vocab-llama.gguf', 600);
    mk('tiny/qwen-tiny-Q4_K_M.gguf', 10);
    assert.strictEqual(path.basename(findGguf([d], opts)), 'qwen3.5-4b-Q4_K_M.gguf');
    mk('coder/qwen2.5-coder-7b-Q4_K_M.gguf', 510);
    assert.strictEqual(path.basename(findGguf([d], opts)), 'qwen2.5-coder-7b-Q4_K_M.gguf');
  } finally {
    fs.rmSync(d, { recursive: true, force: true });
  }
});

test('sin servidor en marcha: pide permiso, arranca llama-server en 127.0.0.1 (salta puertos ocupados) y lo usa', async () => {
  const f = fakeServer();
  const starter = makeLlamaStarter({ server: 'C:/llama/llama-server.exe', gguf: 'D:/m/qwen3.5-4b-Q4_K_M.gguf', spawnFn: f.spawnFn,
    fetchFn: f.fetchFn, portFreeFn: async (p) => p !== 8080, readyMs: 5000 });
  const asked = [];
  const lm = makeLocalModel({ fetchFn: f.fetchFn, starter, allowStart: async (plan) => { asked.push(plan); return true; } });
  const out = await lm.complete('hola');
  assert.strictEqual(out, 'revisado en 8081: hola');
  assert.strictEqual(asked.length, 1);
  assert.deepStrictEqual(f.spawned[0].args.slice(0, 7), ['-m', 'D:/m/qwen3.5-4b-Q4_K_M.gguf', '--host', '127.0.0.1', '--port', '8081', '-c']);
  assert.ok(f.spawned[0].args.includes('--jinja'));                 // plantillas: llamadas a herramientas
  assert.match(lm.name(), /arrancado por Eolfi/);
  await lm.complete('otra');
  assert.strictEqual(f.spawned.length, 1);                 // reutiliza el que arrancó
  lm.stop();
  assert.strictEqual(f.spawned[0].p.exitCode, 0);          // al cerrar VS Code se para
});

test('si no se permite, no arranca nada', async () => {
  const f = fakeServer();
  const starter = makeLlamaStarter({ server: 'x.exe', gguf: 'm.gguf', spawnFn: f.spawnFn, fetchFn: f.fetchFn, portFreeFn: async () => true });
  const lm = makeLocalModel({ fetchFn: f.fetchFn, starter, allowStart: async () => false });
  await assert.rejects(lm.complete('x'), /no hay modelo local/);
  assert.strictEqual(f.spawned.length, 0);
});

test('sin llama-server ni modelo: no lo intenta; tras inactividad se para solo', async () => {
  const f = fakeServer();
  const none = makeLlamaStarter({ spawnFn: f.spawnFn, fetchFn: f.fetchFn, findServerFn: () => null, findGgufFn: () => null });
  const lm = makeLocalModel({ fetchFn: f.fetchFn, starter: none });
  await assert.rejects(lm.complete('x'), /no hay modelo local/);
  const s = makeLlamaStarter({ server: 'x.exe', gguf: 'm.gguf', spawnFn: f.spawnFn, fetchFn: f.fetchFn, portFreeFn: async () => true, idleMs: 30, readyMs: 5000 });
  await s.start();
  assert.ok(s.running());
  await new Promise((r) => setTimeout(r, 80));
  assert.ok(!s.running());
});

test('arranca con la configuración común (llamacpp.json): Gemma 4, puerto, contexto, GPU y razonamiento separado', async () => {
  const f = fakeServer();
  const cfg = { server: 'D:/llama/llama-server.exe', model: 'D:/m/gemma-4-12b-it-Q5_K_M.gguf', port: 8090, ctx: 16384,
    gpu_layers: 20, threads: 4, alias: 'gemma-4', extra_args: ['--flash-attn', 'on'] };
  const s = makeLlamaStarter({ config: () => cfg, spawnFn: f.spawnFn, fetchFn: f.fetchFn, portFreeFn: async () => true, readyMs: 5000 });
  assert.deepStrictEqual(s.plan(), { exe: cfg.server, model: cfg.model });
  await s.start();
  const a = f.spawned[0].args;
  assert.strictEqual(f.spawned[0].exe, cfg.server);
  for (const [k, v] of [['--port', '8090'], ['-c', '16384'], ['-ngl', '20'], ['--threads', '4'],
    ['--threads-batch', '4'], ['--alias', 'gemma-4'], ['--reasoning-format', 'deepseek']]) {
    assert.strictEqual(a[a.indexOf(k) + 1], v, k);
  }
  assert.ok(a.includes('--jinja') && a.includes('--flash-attn'));
  s.stop();
});

test('configuración común: valores por defecto, la crea si falta y opciones por petición', () => {
  const { loadConfig, requestOptions, DEFAULTS } = require('../llamacpp-config');
  assert.strictEqual(DEFAULTS.show_reasoning, false);
  assert.strictEqual(DEFAULTS.temperature, 0.2);
  process.env.EOLFI_LLAMACPP_CONFIG = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'llcfg-')), 'llamacpp.json');
  const c = loadConfig({ findServer: () => 'X:/llama-server.exe' });
  assert.ok(fs.existsSync(process.env.EOLFI_LLAMACPP_CONFIG));
  assert.strictEqual(c.server, 'X:/llama-server.exe');
  assert.strictEqual(c.port, 8090);
  assert.strictEqual(c.show_reasoning, false);
  assert.strictEqual(c.temperature, 0.2);
  fs.writeFileSync(process.env.EOLFI_LLAMACPP_CONFIG, JSON.stringify({ temperature: 0.2, reasoning: false, review_reasoning: true, max_tokens: 900 }));
  const c2 = loadConfig();
  assert.deepStrictEqual(requestOptions(c2), { temperature: 0.2, top_p: 0.95, max_tokens: 900, num_ctx: 32768, num_gpu: 99,
    chat_template_kwargs: { enable_thinking: false } });
  assert.strictEqual(requestOptions(c2, { review: true }).chat_template_kwargs.enable_thinking, true);
  delete process.env.EOLFI_LLAMACPP_CONFIG;
});
