'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { splitTextFile, mergeTextParts, inspectTextParts } = require('../file-splitter');

test('divide un UTF-8 por líneas, conserva el original y registra hashes', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-parts-'));
  const source = path.join(root, 'grande.txt');
  const text = Array.from({ length: 80 }, (_, i) => `línea ${i} ñ\n`).join('');
  fs.writeFileSync(source, text, 'utf8');
  const result = splitTextFile(source, 4);
  assert.equal(fs.readFileSync(source, 'utf8'), text);
  assert.equal(result.parts.length, 4);
  const joined = Buffer.concat(result.parts.map((part) => fs.readFileSync(path.join(result.output, part.file))));
  assert.equal(joined.toString('utf8'), text);
  const manifest = JSON.parse(fs.readFileSync(result.manifest, 'utf8'));
  assert.equal(manifest.source.sha256, crypto.createHash('sha256').update(Buffer.from(text)).digest('hex'));
  assert.equal(manifest.parts.length, 4);
});

test('rechaza binarios y no crea una carpeta de salida', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-parts-'));
  const source = path.join(root, 'binario.dat');
  fs.writeFileSync(source, Buffer.from([0, 1, 2]));
  assert.throws(() => splitTextFile(source, 2), /texto UTF-8/);
  assert.equal(fs.existsSync(`${source}.eolfi-parts`), false);
});

test('reúne partes verificadas en un archivo nuevo', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-parts-'));
  const source = path.join(root, 'original.txt');
  const text = 'primera línea\nsegunda línea\ntercera línea\n';
  fs.writeFileSync(source, text);
  const split = splitTextFile(source, 2);
  const merged = mergeTextParts(split.manifest);
  assert.equal(fs.readFileSync(merged.output, 'utf8'), text);
  fs.appendFileSync(path.join(split.output, split.parts[0].file), 'alterado');
  assert.throws(() => mergeTextParts(split.manifest, { outputFile: path.join(root, 'otro.txt') }), /SHA-256/);
});

test('informa si se puede reanudar y detecta partes alteradas', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-parts-status-'));
  try {
    const source = path.join(dir, 'largo.txt');
    fs.writeFileSync(source, 'uno\ndos\ntres\ncuatro\n', 'utf8');
    const split = splitTextFile(source, 2);
    assert.equal(inspectTextParts(split.manifest).ready, true);
    fs.appendFileSync(path.join(split.output, split.parts[0].file), 'cambio');
    const state = inspectTextParts(split.manifest);
    assert.equal(state.ready, false);
    assert.equal(state.parts[0].status, 'alterada');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
