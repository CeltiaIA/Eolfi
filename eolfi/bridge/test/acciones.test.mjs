// B8 en el puente: cadena compatible con eolfi/acciones.py y eventos del servidor y de la aprobación.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { anotar, anotarSeguro, canon, digest, huella, limpio, CERO, SCHEMA } from '../acciones.mjs';
import { startBridgeServer } from '../server.mjs';
import { createApprover } from '../approval.mjs';

const tmpEnv = () => {
  const dir = mkdtempSync(join(tmpdir(), 'eolfi-acc-'));
  return { EOLFI_ACCIONES_FILE: join(dir, 'acciones.jsonl') };
};
const leer = (env) => readFileSync(env.EOLFI_ACCIONES_FILE, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));

function verificar(env) {
  let prev = CERO;
  return leer(env).every((e, i) => {
    const ok = e.schema === SCHEMA && e.seq === i + 1 && e.prev === prev && digest(e) === e.sha256;
    prev = e.sha256;
    return ok;
  });
}

test('JSON canónico igual que json.dumps(sort_keys, separators, ensure_ascii=False)', () => {
  // Valor esperado calculado con Python: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
  const v = { b: [1, true, null], a: 'ñ «x»\n\t"q"\\', c: { z: 'é', y: -3 } };
  assert.equal(canon(v), '{"a":"ñ «x»\\n\\t\\"q\\"\\\\","b":[1,true,null],"c":{"y":-3,"z":"é"}}');
  assert.throws(() => canon({ x: 1.5 }), /enteros/);
});

test('huella: SHA-256 y bytes UTF-8, sin el texto', () => {
  const h = huella('añadir');
  assert.equal(h.bytes, 7);
  assert.equal(h.sha256, createHash('sha256').update('añadir', 'utf8').digest('hex'));
  assert.equal(huella(null), null);
});

test('limpio corta textos por puntos de código y acota profundidad', () => {
  assert.equal(Array.from(limpio('😀'.repeat(400))).length, 301);
  assert.deepEqual(limpio({ a: { b: { c: { d: 1 } } } }), { a: { b: { c: '…' } } });
});

test('anotar encadena y la cadena se verifica; editar una línea la rompe', () => {
  const env = tmpEnv();
  const e1 = anotar('puente.chat', { params: { provider: 'x' }, env });
  const e2 = anotar('puente.revocar', { params: { provider: 'x' }, resultado: { revocados: 1 }, env });
  assert.equal(e1.seq, 1); assert.equal(e1.prev, CERO);
  assert.equal(e2.seq, 2); assert.equal(e2.prev, e1.sha256);
  assert.equal(e1.origen, 'puente');
  assert.ok(verificar(env));
  const txt = readFileSync(env.EOLFI_ACCIONES_FILE, 'utf8').replace('"revocados":1', '"revocados":2');
  writeFileSync(env.EOLFI_ACCIONES_FILE, txt);
  assert.equal(verificar(env), false);
  assert.equal(existsSync(env.EOLFI_ACCIONES_FILE + '.lock'), false);
});

test('EOLFI_ACCIONES=0 desactiva y un fallo de escritura solo avisa', () => {
  assert.equal(anotar('x', { env: { ...tmpEnv(), EOLFI_ACCIONES: '0' } }), null);
  const avisos = [];
  const orig = process.env.EOLFI_ACCIONES_FILE;
  process.env.EOLFI_ACCIONES_FILE = join(tmpEnv().EOLFI_ACCIONES_FILE, '\0malo');
  try { assert.equal(anotarSeguro('x', {}, (m) => avisos.push(m)), null); } finally {
    if (orig === undefined) delete process.env.EOLFI_ACCIONES_FILE; else process.env.EOLFI_ACCIONES_FILE = orig;
  }
  assert.match(avisos[0], /no se pudo registrar/);
});

test('el servidor registra chat aprobado, denegado y revocación sin el prompt', async () => {
  const eventos = [];
  let allow = true;
  const fake = { status: async () => ({ ok: true }), send: async (p) => `respuesta a ${p.length}` };
  const { server, port } = await startBridgeServer({
    adapters: { deepseek: async () => fake }, token: 'a'.repeat(64), panelToken: 'p'.repeat(64),
    approve: async () => allow, revoke: () => 2, audit: (op, d) => eventos.push([op, d]),
  });
  const call = (path, body) => fetch(`http://127.0.0.1:${port}${path}`, { method: 'POST', body: JSON.stringify(body),
    headers: { Authorization: `Bearer ${'a'.repeat(64)}` } });
  try {
    assert.equal((await call('/v1/chat', { provider: 'deepseek', prompt: 'secreto del usuario', conversation: 'c1' })).status, 200);
    allow = false;
    assert.equal((await call('/v1/chat', { provider: 'deepseek', prompt: 'otro' })).status, 403);
    assert.equal((await call('/v1/revoke', { provider: 'deepseek', conversation: 'c1' })).status, 200);
  } finally { server.close(); }
  assert.deepEqual(eventos.map(([op, d]) => [op, d.ok !== false, d.resultado?.decision ?? null]), [
    ['puente.chat', true, 'aprobado'], ['puente.chat', false, 'denegado'], ['puente.revocar', true, null]]);
  const [, chat] = eventos[0];
  assert.deepEqual(chat.params.prompt, huella('secreto del usuario'));
  assert.equal(chat.resultado.respuesta.sha256, huella('respuesta a 19').sha256);
  assert.ok(!JSON.stringify(eventos).includes('secreto del usuario'));
  assert.equal(eventos[2][1].resultado.revocados, 2);
});

test('«Permitir 30 minutos» queda registrado; «Permitir» una vez no', async () => {
  const eventos = [];
  let response = 0;
  const a = createApprover({ showMessageBox: async () => ({ response }), audit: (op, d) => eventos.push([op, d]) });
  assert.equal(await a.approve('deepseek', 'x', undefined, 'c'), true);
  response = 1;
  assert.equal(await a.approve('deepseek', 'x', undefined, 'c'), true);
  assert.deepEqual(eventos, [['puente.permiso', { params: { provider: 'deepseek', conversation: 'c', minutos: 30 } }]]);
});
