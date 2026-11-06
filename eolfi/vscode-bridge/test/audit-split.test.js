'use strict';
const test = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const path = require('node:path');
const { reviewBatch, splitPiece } = require('../audit');

const CONTEXT_ERROR = 'modelo local gemma-4: HTTP 400 {"error":{"message":"request (20207 tokens) exceeds the available context size (16384 tokens)"}}';

test('si un lote no cabe en el contexto del modelo (caso real: 20 207 > 16 384 tokens) se parte en dos y sigue', async () => {
  const calls = [];
  const complete = async (prompt) => {
    const files = [...prompt.matchAll(/===== ARCHIVO: (\S+)/g)].map((m) => m[1]);
    calls.push(files.length);
    if (prompt.length > 1700) throw new Error(CONTEXT_ERROR);
    return files.map((f) => `### \`${f}\`\n- ok`).join('\n\n');
  };
  const root = os.tmpdir();
  const mk = (n, lines) => ({ path: path.join(root, `${n}.py`), text: Array.from({ length: lines }, (_, i) => `x${i} = ${i}`).join('\n'), from: 1 });
  const progress = [];
  const out = await reviewBatch([mk('a', 4), mk('b', 4), mk('c', 4), mk('d', 60)], root, '', complete, null, (m) => progress.push(m));
  for (const f of ['a.py', 'b.py', 'c.py', 'd.py']) assert.ok(out.includes(`### \`${f}\``), f);
  assert.strictEqual(calls[0], 4);                         // primero todo junto
  assert.ok(progress.some((m) => /no cabe en el contexto del modelo: lo parto en dos/.test(m)));
});

test('un archivo que no cabe solo se parte por la mitad conservando el número de línea', () => {
  const p = { path: '/p/e.py', text: Array.from({ length: 10 }, (_, i) => `l${i}`).join('\n'), from: 1 };
  const [h1, h2] = splitPiece(p);
  assert.strictEqual(h1.from, 1);
  assert.strictEqual(h2.from, 6);
  assert.strictEqual(`${h1.text}\n${h2.text}`, p.text);
});

test('otros errores no se tapan partiendo el lote', async () => {
  const p = { path: path.join(os.tmpdir(), 'f.py'), text: 'x = 1\ny = 2', from: 1 };
  await assert.rejects(reviewBatch([p], os.tmpdir(), '', async () => { throw new Error('otra cosa'); }, null), /otra cosa/);
});
