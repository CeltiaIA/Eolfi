// Requisito de entorno de las pruebas HTTP de la extensión: conectar con 127.0.0.1 (19/11/2026).
// En sandboxes de agentes con la red restringida (Codex en Windows), el servidor escucha pero `connect` falla
// con EACCES y el resto de pruebas HTTP cae en cascada. Esta prueba lo nombra como bloqueo del entorno.
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');

test('entorno: 127.0.0.1 acepta conexiones (requisito de las pruebas HTTP locales)', async () => {
  const servidor = net.createServer((s) => s.end());
  await new Promise((ok, mal) => servidor.once('error', mal).listen(0, '127.0.0.1', ok));
  try {
    await new Promise((ok, mal) => {
      const cliente = net.connect(servidor.address().port, '127.0.0.1', () => { cliente.end(); ok(); });
      cliente.once('error', mal);
    });
  } catch (err) {
    assert.fail(`NO VERIFICADO: el entorno bloquea conexiones a 127.0.0.1 (${err.code || err.message}). `
      + 'Los fallos HTTP de esta suite son del sandbox, no del producto. Repite el mismo comando con ejecución '
      + 'local autorizada (en Codex, sandbox_permissions=require_escalated).');
  } finally {
    servidor.close();
  }
});
