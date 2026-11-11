'use strict';
// eolfi_edit_file: cambiar una parte de un archivo existente sin reescribirlo entero.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fsp = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeActions, TOOL_DEFS } = require('../workspace');

function fake(root, { confirmAnswer = 'Permitir', settings = {} } = {}) {
  const asked = [];
  const U = (p) => ({ fsPath: p });
  const vscode = {
    Uri: { file: U },
    FileType: { File: 1, Directory: 2 },
    Position: class { constructor(l, c) { this.line = l; this.character = c; } },
    Range: class { constructor(a, b) { this.start = a; this.end = b; } },
    WorkspaceEdit: class {
      constructor() { this.ops = []; }
      createFile(u) { this.ops.push(['create', u.fsPath]); }
      delete(u) { this.ops.push(['delete', u.fsPath]); }
      deleteFile(u) { this.ops.push(['deleteFile', u.fsPath]); }
      insert(u, _p, text) { this.ops.push(['insert', u.fsPath, text]); }
    },
    window: { activeTextEditor: null, visibleTextEditors: [], showWarningMessage: async (msg) => { asked.push(msg); return confirmAnswer; } },
    commands: { executeCommand: async () => undefined },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: root } }],
      getConfiguration: () => ({ get: (k) => settings[k], update: async (k, v) => { settings[k] = v; } }),
      fs: {
        stat: async (u) => { const st = fsp.statSync(u.fsPath); return { size: st.size, type: st.isDirectory() ? 2 : 1 }; },
        readFile: async (u) => fsp.readFileSync(u.fsPath),
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

function ws(files) {
  const root = fsp.mkdtempSync(path.join(os.tmpdir(), 'eolfi-edit-'));
  for (const [rel, text] of Object.entries(files)) {
    fsp.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fsp.writeFileSync(path.join(root, rel), text);
  }
  return root;
}

const SRC = "import { a } from './a.mjs';\n\nfunction uno() {\n  return 1;\n}\n\nfunction dos() {\n  return 1;\n}\n";

test('eolfi_edit_file está declarada como herramienta con old_text o rango de líneas', () => {
  const def = TOOL_DEFS.find((d) => d.name === 'eolfi_edit_file');
  assert.equal(def.action, 'edit');
  assert.deepEqual(def.inputSchema.required, ['path', 'new_text']);
  assert.ok(def.inputSchema.properties.old_text && def.inputSchema.properties.start_line && def.inputSchema.properties.expect_start);
});

test('sustituye solo el fragmento indicado y deja el resto intacto', async () => {
  const root = ws({ 'src/m.mjs': SRC });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  const r = await a.edit({ path: 'src/m.mjs', old_text: "import { a } from './a.mjs';", new_text: "import { a } from './a.mjs';\nimport { b } from './b.mjs';" });
  assert.equal(r.line, 1);
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), SRC.replace("'./a.mjs';", "'./a.mjs';\nimport { b } from './b.mjs';"));
});

test('rechaza un fragmento ausente o repetido sin tocar el archivo', async () => {
  const root = ws({ 'src/m.mjs': SRC });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  await assert.rejects(a.edit({ path: 'src/m.mjs', old_text: 'no existe', new_text: 'x' }), /no aparece/);
  await assert.rejects(a.edit({ path: 'src/m.mjs', old_text: '  return 1;', new_text: '  return 2;' }), /más de una vez/);
  await assert.rejects(a.edit({ path: 'src/m.mjs', old_text: '', new_text: 'x' }), /vacío/);
  await assert.rejects(a.edit({ path: 'src/nuevo.mjs', old_text: 'x', new_text: 'y' }), /no existe/);
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), SRC);
});

test('respeta CRLF del archivo aunque el modelo copie con \\n', async () => {
  const crlf = SRC.replace(/\n/g, '\r\n');
  const root = ws({ 'w.mjs': crlf });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  await a.edit({ path: 'w.mjs', old_text: 'function dos() {\n  return 1;', new_text: 'function dos() {\n  return 2;' });
  assert.equal(fsp.readFileSync(path.join(root, 'w.mjs'), 'utf8'), crlf.replace('function dos() {\r\n  return 1;', 'function dos() {\r\n  return 2;'));
});

test('modo manual: pide confirmación y, si se niega, no cambia nada', async () => {
  const root = ws({ 'src/m.mjs': SRC });
  const no = fake(root, { confirmAnswer: null });
  await assert.rejects(makeActions(no.vscode).edit({ path: 'src/m.mjs', old_text: 'function uno', new_text: 'function una' }), /no permitió/);
  assert.equal(no.asked.length, 1);
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), SRC);
});

test('queda en el diario y «Deshacer» restaura el original', async () => {
  const root = ws({ 'src/m.mjs': SRC });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  const { journal } = await a.journal_start();
  await a.edit({ path: 'src/m.mjs', old_text: 'function uno', new_text: 'function una', journal });
  await a.edit({ path: 'src/m.mjs', old_text: 'function dos', new_text: 'function doses', journal });
  assert.match(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), /function una[\s\S]*function doses/);
  const u = await a.undo({ journal });
  assert.equal(u.restored.length, 1);
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), SRC);
});

test('no edita archivos de secretos ni fuera del workspace', async () => {
  const root = ws({ '.env': 'CLAVE=1\n' });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  await assert.rejects(a.edit({ path: '.env', old_text: 'CLAVE=1', new_text: 'CLAVE=2' }), /secretos/);
  await assert.rejects(a.edit({ path: path.join(os.tmpdir(), 'fuera.txt'), old_text: 'a', new_text: 'b' }), /fuera/);
  assert.equal(fsp.readFileSync(path.join(root, '.env'), 'utf8'), 'CLAVE=1\n');
});

test('por rango de líneas: sustituye, borra y exige expect_start de la línea inicial', async () => {
  const root = ws({ 'src/m.mjs': SRC });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  const r = await a.edit({ path: 'src/m.mjs', start_line: 3, end_line: 5, expect_start: 'function uno', new_text: 'const uno = () => 1;' });
  assert.deepEqual(r.lines, [3, 5]);
  assert.equal(r.replaced, 'function uno() {\n  return 1;\n}');
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), SRC.replace('function uno() {\n  return 1;\n}', 'const uno = () => 1;'));
  // Número desfasado: no sustituye y dice dónde está.
  await assert.rejects(a.edit({ path: 'src/m.mjs', start_line: 3, end_line: 5, expect_start: 'function dos', new_text: 'x' }), /aparece en la línea 5/);
  await assert.rejects(a.edit({ path: 'src/m.mjs', start_line: 5, end_line: 7, new_text: 'x' }), /expect_start obligatorio/);
  await assert.rejects(a.edit({ path: 'src/m.mjs', start_line: 5, end_line: 99, expect_start: 'function dos', new_text: 'x' }), /rango inválido/);
  await a.edit({ path: 'src/m.mjs', start_line: 3, end_line: 3, expect_start: 'const uno', new_text: '' });
  assert.equal(fsp.readFileSync(path.join(root, 'src/m.mjs'), 'utf8'), "import { a } from './a.mjs';\n\n\nfunction dos() {\n  return 1;\n}\n");
});

test('por rango de líneas conserva CRLF', async () => {
  const crlf = SRC.replace(/\n/g, '\r\n');
  const root = ws({ 'w.mjs': crlf });
  const a = makeActions(fake(root, { settings: { autoApproveEdits: true } }).vscode);
  await a.edit({ path: 'w.mjs', start_line: 4, end_line: 4, expect_start: 'return 1', new_text: '  return 3;' });
  assert.equal(fsp.readFileSync(path.join(root, 'w.mjs'), 'utf8'), crlf.replace('  return 1;\r\n}\r\n\r\nfunction dos', '  return 3;\r\n}\r\n\r\nfunction dos'));
});
