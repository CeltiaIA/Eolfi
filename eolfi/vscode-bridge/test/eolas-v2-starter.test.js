'use strict';
// Eolas V2 como motor local de la extensión (15/11/2026): clave de API, perfil del eolas-v2.json y arranque con la
// CLI de Eolfi. Sin GPU ni modelos: servidor y procesos simulados.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { makeLocalModel } = require('../local-model');
const { makeEolasV2Starter, v2Target, v2AuthHeaders } = require('../eolas-v2-starter');

function sandbox(config, key) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolas-v2-'));
  const file = path.join(dir, 'eolas-v2.json');
  if (config) fs.writeFileSync(file, JSON.stringify(config));
  if (key) fs.writeFileSync(path.join(dir, 'eolas-v2.key'), key);
  return { EOLFI_EOLAS_V2_CONFIG: file, dir };
}

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });

test('perfil, alias y puerto salen de eolas-v2.json; la clave del archivo o de EOLAS_V2_API_KEY', () => {
  const env = sandbox({ port: 8091, active_profile: 'gemma', profiles: { gemma: { alias: 'gemma-4-12b-it-q5_k_m:latest' } } }, 'k1\n');
  assert.deepStrictEqual(v2Target({ env }), { profile: 'gemma', alias: 'gemma-4-12b-it-q5_k_m:latest', url: 'http://127.0.0.1:8091' });
  // Perfil pedido que el JSON no repite: alias por defecto de eolas_v2.py.
  assert.strictEqual(v2Target({ env, profile: 'gemma_q4' }).alias, 'gemma-4-12b-it-q4_k_m:latest');
  assert.deepStrictEqual(v2AuthHeaders({ env }), { Authorization: 'Bearer k1' });
  assert.deepStrictEqual(v2AuthHeaders({ env: { ...env, EOLAS_V2_API_KEY: 'k2' } }), { Authorization: 'Bearer k2' });
  assert.deepStrictEqual(v2AuthHeaders({ env: sandbox(null, null) }), {});
  assert.strictEqual(v2Target({ env: sandbox(null, null) }).url, 'http://127.0.0.1:8090');
});

test('la extensión habla con Eolas V2 por /v1 con la clave y sin la guardia de V1', async () => {
  const seen = [];
  const fetchFn = async (url, opts = {}) => {
    seen.push([url, opts.headers?.Authorization]);
    if (opts.headers?.Authorization !== 'Bearer s3cr3t') return reply(401, { error: 'Invalid API Key' });
    if (url.endsWith('/v1/models')) return reply(200, { data: [{ id: 'gemma-4-12b-it-q5_k_m:latest' }] });
    if (url.endsWith('/v1/chat/completions')) return reply(200, { choices: [{ message: { content: 'hecho', reasoning_content: 'pensé' } }] });
    return reply(404, {});
  };
  const m = makeLocalModel({ endpoints: ['http://127.0.0.1:8090'], model: 'gemma-4-12b-it-q5_k_m:latest', fetchFn,
    authHeaders: () => ({ Authorization: 'Bearer s3cr3t' }), gpuHolder: () => assert.fail('no aplica a V2') });
  assert.strictEqual(await m.complete('x'), 'hecho');
  const r = await m.chatTools([{ role: 'user', content: 'y' }], []);
  assert.strictEqual(r.content, 'hecho');
  assert.strictEqual(r.reasoning, 'pensé');
  assert.ok(seen.every(([, auth]) => auth === 'Bearer s3cr3t'));
});

test('sin V2 en marcha, el aviso dice cómo arrancarlo', async () => {
  const m = makeLocalModel({ endpoints: ['http://127.0.0.1:8090'], model: 'g', fetchFn: async () => { throw new Error('ECONNREFUSED'); },
    startHint: 'arranca Eolas V2 con «python -m eolfi eolas-v2 start»' });
  await assert.rejects(m.complete('x'), /eolas-v2 start/);
});

function fakeChild({ code = 0, stdout = '', stderr = '' } = {}) {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => {};
  setImmediate(() => { if (stdout) child.stdout.emit('data', stdout); if (stderr) child.stderr.emit('data', stderr); child.emit('close', code); });
  return child;
}

test('el arrancador usa «eolfi eolas-v2 start --profile» con PYTHONPATH de Eolfi y devuelve su URL', async () => {
  const env = sandbox({ active_profile: 'gemma_q4' }, 'k');
  const calls = [];
  const s = makeEolasV2Starter({ python: 'py.exe', cwd: 'D:/Eolfi', env, spawnFn: (cmd, args, opts) => {
    calls.push({ cmd, args, opts });
    return fakeChild({ stdout: JSON.stringify({ running: true, url: 'http://127.0.0.1:8090', pid: 4321 }) });
  } });
  assert.deepStrictEqual(s.plan(), { exe: 'py.exe', model: 'gemma-4-12b-it-q4_k_m:latest' });
  assert.strictEqual(await s.start(), 'http://127.0.0.1:8090');
  assert.deepStrictEqual(calls[0].args, ['-m', 'eolfi', 'eolas-v2', 'start', '--profile', 'gemma_q4']);
  assert.strictEqual(calls[0].opts.env.PYTHONPATH, 'D:/Eolfi');
  // Sin runtime.json vivo (lo paró el vigilante), running() es falso y la extensión vuelve a arrancarlo.
  assert.strictEqual(s.running(), false);
  fs.writeFileSync(env.EOLFI_EOLAS_V2_CONFIG.replace(/\.json$/, '.runtime.json'), JSON.stringify({ pid: process.pid }));
  assert.strictEqual(s.running(), true);
});

test('si la CLI falla, el error lleva su motivo', async () => {
  const s = makeEolasV2Starter({ env: sandbox(null, null), spawnFn: () => fakeChild({ code: 1, stderr: 'Eolas V1/CeltIA tiene cargado en la GPU gemma' }) });
  await assert.rejects(s.start(), /código 1.*tiene cargado en la GPU/);
});
