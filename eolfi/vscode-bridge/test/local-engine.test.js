'use strict';
// 15/11/2026: la extensión trabaja con Eolas V1 o Eolas V2, con la misma elección que la CLI y el panel.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { localEngine, v1AuthHeaders, v1KeyFiles, makeFreeForEolas } = require('../local-engine');
const { makeLocalModel, EOLAS_URL, EOLAS_MODEL } = require('../local-model');
const { makeEolasStarter } = require('../eolas-starter');

const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function tmpDir() { return fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-motor-')); }

test('motor: ajuste, después EOLFI_LOCAL_ENGINE, después motor-local.json, si no eolas-v2', () => {
  const dir = tmpDir();
  const file = path.join(dir, 'motor-local.json');
  const env = { EOLFI_MOTOR_LOCAL_FILE: file };
  assert.strictEqual(localEngine({ env }), 'eolas-v2');
  fs.writeFileSync(file, JSON.stringify({ engine: 'eolas-v1' }));
  assert.strictEqual(localEngine({ env }), 'eolas-v1');
  assert.strictEqual(localEngine({ env: { ...env, EOLFI_LOCAL_ENGINE: 'v2' } }), 'eolas-v2');
  assert.strictEqual(localEngine({ setting: 'eolas-v2', env }), 'eolas-v2');
  assert.strictEqual(localEngine({ setting: '', env }), 'eolas-v1');
  fs.writeFileSync(file, '{roto');
  assert.strictEqual(localEngine({ env }), 'eolas-v2');
  assert.strictEqual(localEngine({ env: { EOLFI_HOME: dir } }), 'eolas-v2');
});

test('clave de Eolas V1: variable o runtime/eolas/api.key de CELTIAIA, leída en cada petición', () => {
  const dir = tmpDir();
  const env = { CELTIAIA_HOME: dir };
  assert.deepStrictEqual(v1AuthHeaders({ env }), {});
  assert.deepStrictEqual(v1KeyFiles(env, 'linux'), [path.join(dir, 'runtime', 'eolas', 'api.key')]);
  fs.mkdirSync(path.join(dir, 'runtime', 'eolas'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'runtime', 'eolas', 'api.key'), 'k1\n');
  assert.deepStrictEqual(v1AuthHeaders({ env }), { Authorization: 'Bearer k1' });
  assert.deepStrictEqual(v1AuthHeaders({ env: { ...env, EOLAS_API_KEY: ' k2 ' } }), { Authorization: 'Bearer k2' });
});

test('ruta V1 de la extensión: la clave va en /api/tags y en /api/chat, también al autoarrancar', async () => {
  const seen = [];
  const fetchFn = async (url, init = {}) => {
    seen.push({ url, auth: init.headers?.Authorization });
    if (init.headers?.Authorization !== 'Bearer k1') return reply({ error: 'unauthorized' }, 401);
    if (url.endsWith('/api/tags')) return reply({ models: [{ name: EOLAS_MODEL }] });
    return reply({ message: { content: 'listo' } });
  };
  const lm = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, gpuHolder: () => null,
    authHeaders: () => ({ Authorization: 'Bearer k1' }) });
  const r = await lm.chatTools([{ role: 'user', content: 'hola' }], []);
  assert.strictEqual(r.content, 'listo');
  assert.ok(seen.length >= 2 && seen.every((s) => s.auth === 'Bearer k1'));
  // El arrancador de V1 comprueba el modelo con la misma clave.
  const starter = makeEolasStarter({ launcher: 'x', endpoint: EOLAS_URL, model: EOLAS_MODEL, fetchFn,
    authHeaders: () => ({ Authorization: 'Bearer k1' }) });
  assert.ok(starter.plan().model);
});

test('P1-5: con Eolas V2 ocioso en la GPU, la ruta V1 lo libera antes; si está respondiendo, explica el motivo', async () => {
  const fetchFn = async (url) => (url.endsWith('/api/tags') ? reply({ models: [{ name: EOLAS_MODEL }] }) : reply({ message: { content: 'ok' } }));
  let holder = { pid: 7, profile: 'gemma', port: 8090 };
  const frees = [];
  const lm = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, gpuHolder: () => holder,
    freeGpu: async () => { frees.push(1); holder = null; return { ok: true, freed: ['eolas-v2'] }; } });
  assert.strictEqual((await lm.chatTools([{ role: 'user', content: 'x' }], [])).content, 'ok');
  assert.strictEqual(frees.length, 1);

  holder = { pid: 8, profile: 'gemma', port: 8090 };
  const busy = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, gpuHolder: () => holder,
    freeGpu: async () => ({ ok: false, error: 'Eolas V2 está respondiendo una petición' }) });
  await assert.rejects(busy.chatTools([{ role: 'user', content: 'x' }], []), /No se pudo parar: Eolas V2 está respondiendo/);
});

test('makeFreeForEolas llama a la guardia de la CLI y lee su JSON', async () => {
  const calls = [];
  const ok = makeFreeForEolas({ python: 'py', cwd: 'C:/eolfi', env: {}, execFileFn: (exe, args, opts, cb) => {
    calls.push({ exe, args, pythonpath: opts.env.PYTHONPATH });
    cb(null, '{"freed": ["eolas-v2"]}\n');
  } });
  assert.deepStrictEqual(await ok(), { ok: true, freed: ['eolas-v2'] });
  assert.deepStrictEqual(calls[0], { exe: 'py', args: ['-m', 'eolfi.local_gpu', 'free-for-eolas'], pythonpath: 'C:/eolfi' });
  const busy = makeFreeForEolas({ env: {}, execFileFn: (e, a, o, cb) => cb(Object.assign(new Error('exit 3'), { code: 3 }), '{"error": "ocupado"}') });
  assert.deepStrictEqual(await busy(), { ok: false, error: 'ocupado' });
});

test('sin la clave, el error dice que falta la clave (401) y no «sin respuesta»', async () => {
  const fetchFn = async () => reply({ error: 'unauthorized' }, 401);
  const lm = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, gpuHolder: () => null });
  await assert.rejects(lm.chatTools([{ role: 'user', content: 'x' }], []), /rechaza la petición \(401\): falta su clave de API/);
});
