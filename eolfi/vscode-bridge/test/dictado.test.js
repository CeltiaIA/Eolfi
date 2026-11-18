'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { segundosDictado, consultaDictado, dictar } = require('../dictado');

test('duración del dictado acotada a 1-30 s', () => {
  assert.equal(segundosDictado(8), 8);
  assert.equal(segundosDictado(0), 1);
  assert.equal(segundosDictado(99), 30);
  assert.equal(segundosDictado('x'), 8);
  assert.equal(segundosDictado(2.6), 3);
});

test('la consulta va a @eolfi o tal cual, siempre sin enviar', () => {
  assert.deepEqual(consultaDictado('  hola\n mundo '), { query: '@eolfi hola mundo', isPartialQuery: true });
  assert.deepEqual(consultaDictado('hola', false), { query: 'hola', isPartialQuery: true });
  assert.equal(consultaDictado('   '), null);
});

test('dictar pide la grabación a Eolfi y abre el chat con el texto', async () => {
  const pedidos = [];
  const abiertos = [];
  const client = { dictar: async (s, i) => { pedidos.push([s, i]); return { texto: 'analiza este archivo' }; } };
  const r = await dictar(client, { segundos: 50, idioma: 'es-ES', abrirChat: async (q) => abiertos.push(q) });
  assert.deepEqual(pedidos, [[30, 'es-ES']]);
  assert.equal(r.ok, true);
  assert.deepEqual(abiertos, [{ query: '@eolfi analiza este archivo', isPartialQuery: true }]);
  const vacio = await dictar({ dictar: async () => ({ texto: '' }) }, { abrirChat: async () => abiertos.push('no') });
  assert.equal(vacio.ok, false);
  assert.equal(abiertos.length, 1);
});

test('el comando de dictado está declarado y registrado', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  assert.ok(pkg.contributes.commands.some((c) => c.command === 'eolfi.dictar'));
  assert.ok(pkg.contributes.configuration.properties['eolfi.dictadoSegundos']);
  const ext = fs.readFileSync(path.join(__dirname, '..', 'extension.js'), 'utf8');
  assert.match(ext, /registerCommand\('eolfi\.dictar'/);
  const cli = fs.readFileSync(path.join(__dirname, '..', 'eolfi-client.js'), 'utf8');
  assert.match(cli, /\/api\/voz\/dictar/);
});
