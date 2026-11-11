'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const bench = require('../model-benchmark');

test('interpreta la salida JSON de llama-bench incluso con texto previo', () => {
  assert.deepEqual(bench.parseBenchmark('aviso\n{"benchmarks":[{"name":"pp"}]}'), { benchmarks: [{ name: 'pp' }] });
  assert.throws(() => bench.parseBenchmark('sin resultados'), /JSON válido/);
});

test('ejecuta un plan sin pasar argumentos al intérprete de comandos', async () => {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  let received;
  const running = bench.runBenchmark({ executable: 'llama-bench', args: ['-m', 'modelo.gguf'] }, {
    spawnFn: (exe, args, options) => { received = { exe, args, options }; process.nextTick(() => { child.stdout.emit('data', '{"ok":true}'); child.emit('close', 0); }); return child; },
  });
  const result = await running;
  assert.equal(received.exe, 'llama-bench');
  assert.deepEqual(received.args, ['-m', 'modelo.gguf']);
  assert.equal(received.options.windowsHide, true);
  assert.deepEqual(result.result, { ok: true });
});
