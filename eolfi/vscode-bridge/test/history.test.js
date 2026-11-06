'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeHistory } = require('../history');

const tmpFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-hist-')), 'h.jsonl');

test('guarda, busca sin tildes ni mayúsculas, por carpeta y por días', () => {
  let t = Date.parse('2026-11-01T10:00:00Z');
  const h = makeHistory({ file: tmpFile(), now: () => t });
  h.add({ folder: 'D:/Eolfi', prompt: 'Audita el repositorio', response: 'Hallazgo: falta caché', written: ['D:/Eolfi/informes/a.md'], tools: [{ name: 'eolfi_analizar', arg: 'D:/Eolfi' }] });
  t += 86400000 * 3;
  h.add({ folder: 'D:/otro', prompt: 'Arregla la autenticación', response: 'Cambiado login.py' });
  assert.strictEqual(h.search({ consulta: 'AUDITA cache' }).length, 1);           // sin mayúsculas ni tildes
  assert.strictEqual(h.search({ consulta: 'audita caché' }).length, 1);
  assert.strictEqual(h.search({ consulta: 'autenticacion' }).length, 1);
  assert.strictEqual(h.search({ consulta: 'informes/a.md' }).length, 1);           // por archivo cambiado
  assert.strictEqual(h.search({ consulta: 'eolfi_analizar' }).length, 1);         // por herramienta
  assert.deepStrictEqual(h.recent('D:/Eolfi').map((e) => e.prompt), ['Audita el repositorio']);
  assert.strictEqual(h.search({ dias: 1 }).length, 1);
  assert.strictEqual(h.search({}).at(0).prompt, 'Arregla la autenticación');      // lo más reciente primero
  assert.match(h.format(h.search({})), /archivos cambiados: D:\/Eolfi\/informes\/a\.md/);
});

test('la memoria persiste entre «sesiones» y se recorta por antigüedad', () => {
  const file = tmpFile();
  let t = Date.parse('2025-01-01T00:00:00Z');
  makeHistory({ file, now: () => t }).add({ prompt: 'muy antiguo' });
  t = Date.parse('2026-11-01T00:00:00Z');
  const h2 = makeHistory({ file, now: () => t, keepDays: () => 30 });   // otra sesión, mismo archivo
  h2.add({ prompt: 'reciente' });
  assert.deepStrictEqual(h2.search({}).map((e) => e.prompt), ['reciente', 'muy antiguo']);
  fs.appendFileSync(file, 'línea rota\n');
  assert.strictEqual(h2.search({}).length, 2);                           // tolera líneas dañadas
});

test('los comandos sin texto (/ayuda) se encuentran por su nombre', () => {
  const h = makeHistory({ file: tmpFile() });
  h.add({ command: 'ayuda', prompt: '', response: 'Soy Eolfi' });
  assert.strictEqual(h.search({ consulta: 'ayuda' }).length, 1);
  assert.strictEqual(h.search({ consulta: '/ayuda' }).length, 1);
});
