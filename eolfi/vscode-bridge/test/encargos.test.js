'use strict';
// Encargos del chat de Eolfi a @eolfi (18/11/2026): ruta /v1/encargo del puente y aviso con Aprobar/Rechazar contra
// un VS Code y un servidor de Eolfi SIMULADOS (nada sale de 127.0.0.1).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const { makeHandler } = require('../core');
const { validEncargo, describe, makeEncargoHandler } = require('../encargos');

const T = 'k'.repeat(64);
const ID = 'a'.repeat(32);
const CARPETA = path.resolve('/proyectos/ws/mi-web');
const ENCARGO = { id: ID, nombre: 'Mi Web', descripcion: 'una web', carpeta: CARPETA,
  riesgos: ['escribir archivos nuevos', 'ejecutar comandos', 'instalar dependencias y usar la red'] };

function fakeVscode(answer) {
  const seen = { avisos: [], info: [], comandos: [], progreso: [] };
  const vscode = {
    ProgressLocation: { Notification: 15 },
    Uri: { file: (p) => ({ fsPath: p }) },
    workspace: { workspaceFolders: [{ uri: { fsPath: path.resolve('/proyectos/ws') } }] },
    commands: { executeCommand: async (...a) => { seen.comandos.push(a); } },
    window: {
      showWarningMessage: async (msg, opts, ...botones) => { seen.avisos.push({ msg, opts, botones }); return answer; },
      showInformationMessage: async (msg, ...botones) => { seen.info.push({ msg, botones }); return botones[0]; },
      withProgress: async (_o, fn) => fn({ report: (x) => seen.progreso.push(x.message) }),
    },
  };
  return { vscode, seen };
}

function fakeClient(estados) {
  const calls = [];
  return { calls,
    encargoDecidir: async (id, accion) => { calls.push([id, accion]); return { id, nombre: 'Mi Web', carpeta: CARPETA,
      estado: accion === 'aprobar' ? 'aprobado' : 'rechazado', job_id: 'j1' }; },
    encargos: async () => ({ encargos: [estados.length > 1 ? estados.shift() : estados[0]] }),
  };
}

test('validEncargo exige id, nombre, carpeta absoluta y riesgos', () => {
  assert.equal(validEncargo(ENCARGO).id, ID);
  for (const malo of [{ ...ENCARGO, id: 'x' }, { ...ENCARGO, nombre: '' }, { ...ENCARGO, carpeta: 'relativa' },
    { ...ENCARGO, riesgos: [] }]) {
    assert.throws(() => validEncargo(malo), (e) => e.status === 400);
  }
});

test('el puente acepta el encargo (202) y lo muestra aparte; sin token, 401', async () => {
  const recibidos = [];
  const handler = makeHandler({ vscode: {}, token: T, encargo: { validate: validEncargo, handle: async (e) => { recibidos.push(e); } } });
  const srv = http.createServer(handler);
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${srv.address().port}`;
  const post = (body, token = T) => fetch(`${base}/v1/encargo`, { method: 'POST', headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(body) });
  try {
    assert.equal((await post(ENCARGO, 'malo')).status, 401);
    assert.equal((await post({ ...ENCARGO, carpeta: 'rel' })).status, 400);
    const r = await post(ENCARGO);
    assert.equal(r.status, 202);
    assert.deepEqual(await r.json(), { recibido: ID });
    await new Promise((res) => setTimeout(res, 20));
    assert.equal(recibidos.length, 1);
    assert.equal(recibidos[0].nombre, 'Mi Web');
  } finally { srv.close(); }
  const sin = http.createServer(makeHandler({ vscode: {}, token: T }));
  await new Promise((r) => sin.listen(0, '127.0.0.1', r));
  try {
    const r = await fetch(`http://127.0.0.1:${sin.address().port}/v1/encargo`, { method: 'POST', headers: { Authorization: `Bearer ${T}` }, body: '{}' });
    assert.equal(r.status, 501);
  } finally { sin.close(); }
});

test('aprobar en VS Code: muestra los riesgos, decide en Eolfi, sigue el progreso y ofrece el resultado', async () => {
  const { vscode, seen } = fakeVscode('Aprobar');
  const client = fakeClient([
    { id: ID, nombre: 'Mi Web', carpeta: CARPETA, estado: 'en_curso', trabajo: { progreso: ['paso generar: create'] } },
    { id: ID, nombre: 'Mi Web', carpeta: CARPETA, estado: 'hecho', proyecto: { verificado: true } },
  ]);
  const on = makeEncargoHandler({ vscode, getClient: async () => client, pollMs: 1 });
  assert.equal(await on(ENCARGO), 'aprobar');
  const aviso = seen.avisos[0];
  assert.match(aviso.msg, /Mi Web/);
  assert.equal(aviso.opts.modal, true);
  for (const r of ENCARGO.riesgos) assert.ok(aviso.opts.detail.includes(r), r);
  assert.deepEqual(aviso.botones, ['Aprobar', 'Rechazar']);
  assert.deepEqual(client.calls, [[ID, 'aprobar']]);
  assert.ok(seen.progreso.includes('paso generar: create'));
  assert.match(seen.info[0].msg, /creado y verificado/);
  assert.deepEqual(seen.info[0].botones, ['Mostrar en el explorador']);   // dentro de la carpeta abierta
  assert.equal(seen.comandos[0][0], 'revealInExplorer');
});

test('rechazar no arranca nada y cerrar el aviso lo deja pendiente', async () => {
  const r = fakeVscode('Rechazar');
  const client = fakeClient([{ estado: 'rechazado' }]);
  assert.equal(await makeEncargoHandler({ vscode: r.vscode, getClient: async () => client })(ENCARGO), 'rechazar');
  assert.deepEqual(client.calls, [[ID, 'rechazar']]);
  assert.equal(r.seen.progreso.length, 0);
  const c = fakeVscode(undefined);
  const nadie = { encargoDecidir: () => assert.fail('sin decisión no se llama al servidor') };
  assert.equal(await makeEncargoHandler({ vscode: c.vscode, getClient: async () => nadie })(ENCARGO), null);
});

test('describe da el estado real, también el fallo', () => {
  assert.match(describe({ nombre: 'A', carpeta: CARPETA, estado: 'fallido', trabajo: { error: 'verificación fallida' } }),
    /no quedó verificado: verificación fallida/);
  assert.match(describe({ nombre: 'A', estado: 'pendiente' }), /pendiente/);
});
