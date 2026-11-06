'use strict';
// Carpetas del workspace por su nombre: «@eolfi audita celtiaia» con la carpeta CeltIA-IA abierta no debe decir
// que no existe (fallo real del 2026-11-06).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { resolveInside, findFolderByName, isSecretPath } = require('../workspace');
const { resolveTarget } = require('../chat');

function ws(folders) {
  return { workspace: { workspaceFolders: folders.map((f) => ({ name: f.name, uri: { fsPath: f.path } })) } };
}

test('una carpeta abierta se encuentra por su nombre, sin mayúsculas ni guiones', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-folders-'));
  try {
    const celtia = path.join(base, 'CeltIA-IA');
    const otra = path.join(base, 'Eolfi');
    fs.mkdirSync(path.join(celtia, 'agentes'), { recursive: true });
    fs.mkdirSync(path.join(otra, 'docs'), { recursive: true });
    const vs = ws([{ name: 'Eolfi', path: otra }, { name: 'CeltIA-IA', path: celtia }]);
    assert.equal(findFolderByName(vs, 'celtiaia'), celtia);
    assert.equal(findFolderByName(vs, 'CELTIA_IA'), celtia);
    assert.equal(resolveInside(vs, 'celtiaia'), celtia);
    assert.equal(resolveInside(vs, 'celtiaia/agentes'), path.join(celtia, 'agentes'));
    // relativa que solo existe en la segunda carpeta abierta
    assert.equal(resolveInside(vs, 'agentes'), path.join(celtia, 'agentes'));
    // subcarpeta de primer nivel por nombre
    assert.equal(findFolderByName(vs, 'Docs'), path.join(otra, 'docs'));
    assert.equal(findFolderByName(vs, 'noexiste'), null);
    // resolveTarget con la búsqueda del handler
    const lookup = (t) => { try { return resolveInside(vs, t); } catch { return null; } };
    assert.deepEqual(resolveTarget('celtiaia', null, otra, lookup), { kind: 'folder', target: celtia });
    assert.equal(resolveTarget('celtiaia', null, otra).kind, 'missing');
    // y nunca sale de las carpetas abiertas
    assert.throws(() => resolveInside(vs, '../..'), /fuera de las carpetas/);
  } finally { fs.rmSync(base, { recursive: true, force: true }); }
});

test('rutas de secretos de Windows también se reconocen en cualquier sistema', () => {
  assert.equal(isSecretPath('D:\\p\\secrets.json'), true);
  assert.equal(isSecretPath('C:\\Users\\x\\.ssh\\config'), true);
  assert.equal(isSecretPath('D:\\p\\.env.example'), false);
});
