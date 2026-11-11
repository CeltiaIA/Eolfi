Tarea O4 en D:\Eolfi-objetivos: que la terminal del agente termine el ÁRBOL de procesos al cortar por tiempo o cancelación (en Windows p.kill() solo mata powershell.exe y deja vivos sus hijos).
Archivo: eolfi/vscode-bridge/agent-tools.js. Tu contexto es pequeño: NO leas el archivo entero ni listes carpetas. Haz exactamente estas 4 llamadas a eolfi_edit_file con path "eolfi/vscode-bridge/agent-tools.js", copiando old_text y new_text tal cual:

1) old_text: platform = process.platform, runInTerminal = null }) {
   new_text: platform = process.platform, runInTerminal = null, killFn = (pid, sig) => process.kill(pid, sig) }) {

2) old_text: const p = spawnFn(bin, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
   new_text: const p = spawnFn(bin, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], detached: platform !== 'win32' });

3) old_text: const kill = () => { try { p.kill(); } catch { /* ya terminó */ } };
   new_text (11 líneas, con 6 espacios de sangría como el original):
      // Mata el árbol completo: en Windows p.kill() solo termina powershell.exe y deja vivos sus hijos.
      let killed = false;
      const kill = () => {
        if (killed) return;
        killed = true;
        try {
          if (platform === 'win32' && p.pid) spawnFn('taskkill', ['/PID', String(p.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
          else if (p.pid) killFn(-p.pid, 'SIGKILL');
          else p.kill();
        } catch { try { p.kill(); } catch { /* ya terminó */ } }
      };

4) old_text: p.on('close', (code) => { clearTimeout(timer);
   new_text: p.on('close', (code) => { killed = true; clearTimeout(timer);

Después crea con eolfi_write_file el archivo nuevo "eolfi/vscode-bridge/test/agent-tools-kill.test.js" con este contenido exacto:

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

Luego ejecuta en la terminal: cd D:\Eolfi-objetivos\eolfi\vscode-bridge; node --check agent-tools.js; node --test
Si algo falla, corrígelo con eolfi_edit_file (sin debilitar pruebas).
Por último, con eolfi_informe_anadir, añade a informes/progreso-objetivos-eolfi.md una sección «O4 — resultado» con los archivos cambiados y el resultado literal de node --test (líneas «tests», «pass», «fail»).
Termina con la línea EOLFI-OBJETIVOS-FIN.
