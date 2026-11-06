'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fsp = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeActions, resolveInside } = require('../workspace');

// «vscode» falso respaldado por el disco real (una carpeta temporal hace de workspace).
function fake(root, { confirmAnswer = 'Permitir', settings = {} } = {}) {
  const asked = [];
  const U = (p) => ({ fsPath: p });
  const vscode = {
    Uri: { file: U },
    FileType: { File: 1, Directory: 2 },
    Position: class { constructor(l, c) { this.line = l; this.character = c; } },
    Range: class { constructor(a, b) { this.start = a; this.end = b; } },
    Selection: class { constructor(a, b) { this.anchor = a; this.active = b; } },
    WorkspaceEdit: class {
      constructor() { this.ops = []; }
      createFile(u) { this.ops.push(['create', u.fsPath]); }
      delete(u) { this.ops.push(['delete', u.fsPath]); }
      deleteFile(u) { this.ops.push(['deleteFile', u.fsPath]); }
      insert(u, _p, text) { this.ops.push(['insert', u.fsPath, text]); }
    },
    window: {
      activeTextEditor: null, visibleTextEditors: [],
      showWarningMessage: async (msg) => { asked.push(msg); return confirmAnswer; },
      showTextDocument: async () => ({ revealRange() {} }),
    },
    commands: { executeCommand: async (...a) => { asked.push(`cmd:${a[0]}`); return 42; } },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: root } }],
      getConfiguration: () => ({ get: (k) => settings[k], update: async (k, v) => { settings[k] = v; } }),
      fs: {
        stat: async (u) => { const st = fsp.statSync(u.fsPath); return { size: st.size, type: st.isDirectory() ? 2 : 1 }; },
        readFile: async (u) => fsp.readFileSync(u.fsPath),
      },
      findFiles: async (glob) => {
        const out = [];
        const walk = (d) => { for (const e of fsp.readdirSync(d, { withFileTypes: true })) {
          const p = path.join(d, e.name);
          if (e.isDirectory()) { if (e.name !== 'node_modules') walk(p); } else if (glob === '**/*' || p.endsWith(glob.replace('**/*', ''))) out.push(U(p));
        } };
        walk(root);
        return out;
      },
      openTextDocument: async (u) => ({ getText: () => (fsp.existsSync(u.fsPath) ? fsp.readFileSync(u.fsPath, 'utf8') : ''),
        positionAt: (n) => n, save: async () => true }),
      applyEdit: async (edit) => {
        for (const [op, p, text] of edit.ops) {
          if (op === 'create' || op === 'delete') { fsp.mkdirSync(path.dirname(p), { recursive: true }); fsp.writeFileSync(p, ''); }
          if (op === 'deleteFile') fsp.rmSync(p, { force: true });
          if (op === 'insert') fsp.writeFileSync(p, text);
        }
        return true;
      },
    },
  };
  return { vscode, asked };
}

function ws() {
  const root = fsp.mkdtempSync(path.join(os.tmpdir(), 'eolfi-ws-'));
  fsp.mkdirSync(path.join(root, 'src'));
  fsp.writeFileSync(path.join(root, 'src', 'app.py'), 'def hola():\n    return "hola mundo"\n');
  fsp.writeFileSync(path.join(root, 'README.md'), '# Demo\n');
  return root;
}

test('leer, listar y buscar solo dentro del workspace', async () => {
  const root = ws();
  const { vscode } = fake(root);
  const a = makeActions(vscode);
  assert.equal((await a.read({ path: 'src/app.py' })).lines, 3);
  assert.equal((await a.read({ path: 'src/app.py', start_line: 2, end_line: 2 })).text.trim(), 'return "hola mundo"');
  assert.ok((await a.list({ glob: '**/*.py' })).files.some((f) => f.endsWith('app.py')));
  assert.deepEqual((await a.find({ text: 'hola mundo' })).matches.map((m) => m.line), [2]);
  await assert.rejects(a.read({ path: '../fuera.txt' }), /fuera de las carpetas/);
  await assert.rejects(a.read({ path: path.join(os.homedir(), '.ssh', 'id_rsa') }), /fuera de las carpetas/);
  assert.throws(() => resolveInside(vscode, ''), /ruta inválida/);
});

test('escribir pide confirmación y se puede negar', async () => {
  const root = ws();
  const no = fake(root, { confirmAnswer: null });   // el usuario cierra el diálogo
  await assert.rejects(makeActions(no.vscode).write({ path: 'nuevo.txt', content: 'x' }), /no permitió/);
  assert.equal(fsp.existsSync(path.join(root, 'nuevo.txt')), false);
  const yes = fake(root);
  const r = await makeActions(yes.vscode).write({ path: 'nuevo.txt', content: 'hola', reason: 'prueba' });
  assert.equal(r.created, true);
  assert.equal(fsp.readFileSync(path.join(root, 'nuevo.txt'), 'utf8'), 'hola');
  assert.match(yes.asked[0], /quiere crear/);
  const auto = fake(root, { settings: { autoApproveEdits: true } });
  await makeActions(auto.vscode).write({ path: 'nuevo.txt', content: 'adiós' });
  assert.equal(auto.asked.length, 0);
});

test('comandos solo de la lista permitida; abrir otra carpeta pide confirmación', async () => {
  const root = ws();
  const f = fake(root, { settings: { allowedCommands: ['workbench.action.files.saveAll'] } });
  const a = makeActions(f.vscode);
  await assert.rejects(a.command({ command: 'workbench.action.terminal.new' }), /no permitido/);
  assert.equal((await a.command({ command: 'workbench.action.files.saveAll' })).result, 42);
  const other = fsp.mkdtempSync(path.join(os.tmpdir(), 'eolfi-otra-'));
  await a.open({ path: other });
  assert.ok(f.asked.some((m) => /abrir la carpeta/.test(m)));
  assert.equal((await a.open({ path: path.join(root, 'README.md') })).kind, 'file');
});

test('modo automático: un solo permiso para la sesión, diario y deshacer', async () => {
  const root = ws();
  const f = fake(root, { confirmAnswer: 'Permitir en esta sesión' });
  const a = makeActions(f.vscode);
  const { journal } = await a.journal_start();
  await a.write({ path: 'src/app.py', content: 'cambiado', auto: true, journal });
  await a.write({ path: 'nuevo.py', content: 'x = 1', auto: true, journal });
  await a.write({ path: 'src/app.py', content: 'cambiado otra vez', auto: true, journal });
  assert.equal(f.asked.length, 1, 'el permiso se pide UNA vez');
  assert.match(f.asked[0], /AUTOMÁTICO/);
  const u = await a.undo({ journal });
  assert.equal(u.restored.length, 2);
  assert.equal(fsp.readFileSync(path.join(root, 'src', 'app.py'), 'utf8'), 'def hola():\n    return "hola mundo"\n');
  assert.equal(fsp.existsSync(path.join(root, 'nuevo.py')), false);
  await assert.rejects(a.undo({ journal }), /no encontrado/);
});

test('modo automático denegado: vuelve a preguntar archivo por archivo', async () => {
  const root = ws();
  const f = fake(root, { confirmAnswer: null });
  await assert.rejects(makeActions(f.vscode).write({ path: 'x.txt', content: 'x', auto: true }), /no permitió/);
  assert.equal(f.asked.length, 2);   // primero el modo automático, luego el archivo
});

test('«Permitir siempre» deja activado el ajuste', async () => {
  const root = ws();
  const settings = {};
  const f = fake(root, { confirmAnswer: 'Permitir siempre', settings });
  await makeActions(f.vscode).write({ path: 'y.txt', content: 'y', auto: true });
  assert.equal(settings.autoApproveEdits, true);
});

test('como Copilot: el cambio se revisa en un diff y se aplica o descarta desde ahí', async () => {
  const root = ws();
  for (const [answer, applied] of [['Aplicar', true], ['Descartar', false]]) {
    const f = fake(root);
    const diffs = [];
    let provided = null;
    f.vscode.Uri.from = (o) => ({ ...o, toString: () => `${o.scheme}:${o.path}` });
    f.vscode.workspace.registerTextDocumentContentProvider = (scheme, p) => { provided = p; return { dispose() {} }; };
    f.vscode.commands.executeCommand = async (cmd, left, right, title) => {
      diffs.push({ cmd, title, right: provided.provideTextDocumentContent(right), left: left.fsPath || provided.provideTextDocumentContent(left) });
    };
    f.vscode.window.showInformationMessage = async (msg) => { f.asked.push(msg); return answer; };
    const a = makeActions(f.vscode);
    const write = a.write({ path: 'src/app.py', content: `version ${answer}`, reason: 'arreglo' });
    if (applied) {
      await write;
      assert.equal(fsp.readFileSync(path.join(root, 'src', 'app.py'), 'utf8'), 'version Aplicar');
    } else {
      await assert.rejects(write, /no permitió/);
      assert.equal(fsp.readFileSync(path.join(root, 'src', 'app.py'), 'utf8'), 'version Aplicar');
    }
    assert.equal(diffs[0].cmd, 'vscode.diff');
    assert.match(diffs[0].title, /app\.py ↔ cambio propuesto por Eolfi/);
    assert.equal(diffs[0].right, `version ${answer}`);
    assert.equal(diffs[0].left, path.join(root, 'src', 'app.py'));
    assert.match(f.asked.at(-1), /Eolfi propone cambiar app\.py: arreglo/);
  }
});

test('modo automático: escribe y abre carpetas sin pedir permiso; manual pregunta', async () => {
  const root = ws();
  const auto = fake(root, { confirmAnswer: null, settings: { 'agent.mode': 'automatico' } });
  await makeActions(auto.vscode).write({ path: 'auto.txt', content: 'sin preguntar' });
  assert.equal(fsp.readFileSync(path.join(root, 'auto.txt'), 'utf8'), 'sin preguntar');
  assert.deepEqual(auto.asked, []);
  const manual = fake(root, { confirmAnswer: null, settings: { 'agent.mode': 'manual' } });
  await assert.rejects(makeActions(manual.vscode).write({ path: 'manual.txt', content: 'x' }), /no permitió/);
  assert.equal(manual.asked.length, 1);
  await assert.rejects(makeActions(auto.vscode).write({ path: '.env', content: 'X=1' }), /secretos/);   // bloqueado en los dos
});

test('informe incremental: crea, añade secciones, pide permiso una vez y se puede deshacer', async () => {
  const root = ws();
  const f = fake(root);
  const a = makeActions(f.vscode);
  const { journal } = await a.journal_start();
  await a.append({ path: 'informes/audit.md', content: '# Auditoría', journal });
  await a.append({ path: 'informes/audit.md', content: '## src/app.py\n- sin pruebas', journal });
  assert.equal(fsp.readFileSync(path.join(root, 'informes', 'audit.md'), 'utf8'), '# Auditoría\n\n## src/app.py\n- sin pruebas\n');
  assert.equal(f.asked.length, 1);                                       // una sola confirmación por informe
  await assert.rejects(a.append({ path: 'src/app.py', content: 'x' }), /solo se añaden secciones/);
  await assert.rejects(a.append({ path: '.env', content: 'X=1' }), /secretos/);
  await a.undo({ journal });
  assert.ok(!fsp.existsSync(path.join(root, 'informes', 'audit.md')));   // deshacer borra el informe creado
});

test('un enlace (unión) dentro del workspace que apunta fuera no sirve para salir', async () => {
  const root = ws();
  const outside = fsp.mkdtempSync(path.join(os.tmpdir(), 'eolfi-fuera-'));
  fsp.writeFileSync(path.join(outside, 'secreto.txt'), 'no deberías leerme');
  try { fsp.symlinkSync(outside, path.join(root, 'atajo'), 'junction'); } catch { return; }   // sin permiso para enlaces: no aplica
  const f = fake(root);
  const a = makeActions(f.vscode);
  await assert.rejects(a.read({ path: 'atajo/secreto.txt' }), /fuera de las carpetas abiertas/);
  await assert.rejects(a.write({ path: 'atajo/nuevo.txt', content: 'x' }), /fuera de las carpetas abiertas/);
  assert.ok(!fsp.existsSync(path.join(outside, 'nuevo.txt')));
  assert.match((await a.read({ path: 'src/app.py' })).text, /hola mundo/);   // lo de dentro, igual que antes
});
