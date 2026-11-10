'use strict';
// O5: el lanzador de Eolas no tiene ruta fija y se comprueba su SHA-256 antes de ejecutarlo.
const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { makeEolasStarter, DEFAULT_LAUNCHER } = require('../eolas-starter');

function tempLauncher() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-eolas-launcher-'));
  const script = path.join(dir, 'launch-eolas.ps1');
  fs.writeFileSync(script, '# lanzador sintético\n');
  return { dir, script, sha: crypto.createHash('sha256').update(fs.readFileSync(script)).digest('hex') };
}

function spawnSpy() {
  const calls = [];
  const spawnFn = (exe, args) => {
    calls.push({ exe, args });
    const child = new EventEmitter();
    child.kill = () => {};
    setImmediate(() => child.emit('close', 0));
    return child;
  };
  return { calls, spawnFn };
}

const ready = async () => ({ ok: true, json: async () => ({ models: [{ name: 'gemma-4-12b-it:latest' }] }) });

test('sin ruta fija de otra máquina en el valor por defecto', () => {
  assert.ok(!/celtiaia/i.test(DEFAULT_LAUNCHER) || process.env.CELTIAIA_HOME, DEFAULT_LAUNCHER);
});

test('sin lanzador configurado: error claro y no ejecuta nada', async () => {
  const s = spawnSpy();
  const starter = makeEolasStarter({ launcher: '', spawnFn: s.spawnFn, fetchFn: ready, readyMs: 5, pollMs: 1 });
  await assert.rejects(starter.start(), /sin lanzador: configura «eolfi\.fallback\.eolasLauncher»/);
  assert.strictEqual(s.calls.length, 0);
});

test('SHA-256 distinto del configurado: no ejecuta el lanzador', async () => {
  const tmp = tempLauncher();
  try {
    const s = spawnSpy();
    const starter = makeEolasStarter({ launcher: tmp.script, expectedSha256: '0'.repeat(64), spawnFn: s.spawnFn, fetchFn: ready, readyMs: 5, pollMs: 1 });
    await assert.rejects(starter.start(), /no coincide con el SHA-256 configurado/);
    assert.strictEqual(s.calls.length, 0);
  } finally { fs.rmSync(tmp.dir, { recursive: true, force: true }); }
});

test('SHA-256 coincidente (en mayúsculas): ejecuta y deja el hash en el registro', async () => {
  const tmp = tempLauncher();
  try {
    const s = spawnSpy();
    const logs = [];
    const starter = makeEolasStarter({ launcher: tmp.script, expectedSha256: tmp.sha.toUpperCase(), log: (m) => logs.push(m),
      spawnFn: s.spawnFn, fetchFn: ready, readyMs: 50, pollMs: 1 });
    await starter.start();
    assert.strictEqual(s.calls.length, 1);
    assert.ok(logs.some((m) => m.includes(tmp.sha)), logs.join('\n'));
  } finally { fs.rmSync(tmp.dir, { recursive: true, force: true }); }
});
