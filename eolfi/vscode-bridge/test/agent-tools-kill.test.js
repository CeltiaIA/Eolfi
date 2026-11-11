'use strict';
// O4: al cortar o cancelar, la terminal del agente termina el árbol de procesos, no solo el shell.
const test = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const { EventEmitter } = require('node:events');
const { makeAgentTools } = require('../agent-tools');
const { isSecretPath } = require('../workspace');

const vscode = { workspace: { workspaceFolders: [{ uri: { fsPath: os.tmpdir() } }] } };
const resolveInside = (_vs, p) => (p === '.' ? os.tmpdir() : (() => { throw new Error('fuera'); })());
const stream = { progress: () => {} };

function setup(platform) {
  const spawned = [];
  const killed = [];
  let shell;
  const fakeSpawn = (bin, args, opts) => {
    spawned.push({ bin, args, opts });
    const p = new EventEmitter();
    p.stdout = new EventEmitter(); p.stderr = new EventEmitter();
    p.kill = () => killed.push('kill');
    if (!shell) { shell = p; p.pid = 4321; }
    return p;
  };
  let cancel = null;
  const token = { onCancellationRequested: (fn) => { cancel = fn; } };
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async () => 'session', spawnFn: fakeSpawn, platform,
    killFn: (pid, sig) => killed.push([pid, sig]) });
  const pending = t.run({ name: 'eolfi_terminal', input: { orden: 'npm test' } }, stream, token);
  return { spawned, killed, pending, cancel: () => cancel(), close: () => shell.emit('close', 1) };
}

test('Windows: cancelar lanza taskkill /T /F sobre el PID del shell, una sola vez', async () => {
  const s = setup('win32');
  await new Promise((r) => setImmediate(r));
  s.cancel(); s.cancel();
  const tk = s.spawned.filter((x) => x.bin === 'taskkill');
  assert.strictEqual(tk.length, 1);
  assert.deepStrictEqual(tk[0].args, ['/PID', '4321', '/T', '/F']);
  assert.strictEqual(s.spawned[0].opts.detached, false);
  s.close();
  assert.match(await s.pending, /código de salida 1/);
});

test('POSIX: el shell va en su propio grupo y se mata el grupo entero', async () => {
  const s = setup('linux');
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(s.spawned[0].opts.detached, true);
  s.cancel();
  assert.deepStrictEqual(s.killed, [[-4321, 'SIGKILL']]);
  s.close();
  await s.pending;
});

test('si el proceso ya terminó, cancelar no mata nada', async () => {
  const s = setup('win32');
  await new Promise((r) => setImmediate(r));
  s.close();
  await s.pending;
  s.cancel();
  assert.strictEqual(s.spawned.filter((x) => x.bin === 'taskkill').length, 0);
});

test('Windows: si taskkill no se puede lanzar, no tumba el proceso y cae a p.kill()', async () => {
  const spawned = [];
  const killed = [];
  let shell;
  const fakeSpawn = (bin, args, opts) => {
    spawned.push({ bin, args, opts });
    const p = new EventEmitter();
    p.stdout = new EventEmitter(); p.stderr = new EventEmitter();
    p.kill = () => killed.push('kill');
    if (!shell) { shell = p; p.pid = 4321; } else setImmediate(() => p.emit('error', new Error('spawn taskkill ENOENT')));
    return p;
  };
  let cancel = null;
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async () => 'session', spawnFn: fakeSpawn, platform: 'win32' });
  const pending = t.run({ name: 'eolfi_terminal', input: { orden: 'npm test' } }, stream, { onCancellationRequested: (fn) => { cancel = fn; } });
  await new Promise((r) => setImmediate(r));
  cancel();
  await new Promise((r) => setImmediate(r));
  assert.deepStrictEqual(killed, ['kill']);
  shell.emit('close', 1);
  await pending;
});
