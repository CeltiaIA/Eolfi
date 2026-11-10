'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { inspectFile, archiveInfo, extractArchive, codeMap, compareFiles, findDuplicates, extractDocument } = require('../file-tools');

function zipOne(name, body) {
  const file = Buffer.from(name), data = Buffer.from(body);
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 8);
  local.writeUInt32LE(data.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(file.length, 26);
  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(0, 10);
  central.writeUInt32LE(data.length, 20); central.writeUInt32LE(data.length, 24); central.writeUInt16LE(file.length, 28);
  const offset = local.length + file.length + data.length;
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(1, 8); end.writeUInt16LE(1, 10); end.writeUInt32LE(central.length + file.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([local, file, data, central, file, end]);
}

test('inspecciona, compara, mapea código y localiza duplicados', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-files-'));
  const first = path.join(root, 'uno.py'), second = path.join(root, 'dos.py');
  fs.writeFileSync(first, 'import os\ndef hola():\n  return 1\n');
  fs.copyFileSync(first, second);
  assert.equal(inspectFile(first).format, 'text');
  assert.equal(compareFiles(first, second).equal, true);
  const map = codeMap(root);
  assert.ok(map.symbols.some((row) => row.name === 'hola'));
  assert.equal(findDuplicates(root).duplicates[0].files.length, 2);
});

test('lista y extrae un ZIP sin tocar rutas fuera del destino', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-files-'));
  const archive = path.join(root, 'muestra.zip');
  fs.writeFileSync(archive, zipOne('carpeta/dato.txt', 'contenido'));
  assert.equal(archiveInfo(archive).entries[0].name, 'carpeta/dato.txt');
  const result = extractArchive(archive);
  assert.equal(fs.readFileSync(path.join(result.output, 'carpeta', 'dato.txt'), 'utf8'), 'contenido');
});

test('extrae texto HTML y marca la extracción PDF como parcial', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-files-'));
  const html = path.join(root, 'texto.html'), pdf = path.join(root, 'texto.pdf');
  fs.writeFileSync(html, '<h1>Hola</h1><p>Mundo &amp; todos</p>');
  fs.writeFileSync(pdf, '%PDF-1.4\n(Hola PDF)');
  assert.match(extractDocument(html).text, /Hola Mundo & todos/);
  const extracted = extractDocument(pdf);
  assert.equal(extracted.partial, true);
  assert.match(extracted.text, /Hola PDF/);
});
