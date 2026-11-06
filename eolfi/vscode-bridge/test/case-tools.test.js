'use strict';
const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const { makeCaseTools, combineTools, summarizeCase } = require('../case-tools');
const { makeClient } = require('../eolfi-client');

const CASE = {
  case_id: 'c1', name: 'Caso', description: 'd', imports: [{ source_name: 'p.json' }],
  artifacts: [{ subject: 'a'.repeat(64), identity: 'content', content_sha256: 'a'.repeat(64), format: 'elf', size: 10, provenance: 'propia' }],
  records: [{ record_id: 'r1', kind: 'analysis', payload: { flow: 'triage', status: 'partial', errors: ['proveedor boom falló'],
    tools: [{ name: 'eolfi.triage', version: '0.2', status: 'ran' }], claims: [{ text: 'quizá', status: 'hypothesis' }] } }],
  evidence: [{}], incognitas: [{ status: 'open', severity: 'medium', question: '¿qué hace?', incognita_id: 'i1' }],
};

function fakeClient(calls) {
  return {
    cases: async () => { calls.push(['cases']); return { cases: [{ case_id: 'c1', name: 'Caso', artifacts: 1, records: 1, open_incognitas: 1, last_record: { flow: 'triage', status: 'done' } }] }; },
    caseGet: async (id) => { calls.push(['get', id]); return CASE; },
    caseCreate: async (n, d) => { calls.push(['create', n, d]); return { case_id: 'c2', name: n }; },
    caseLink: async (id, s, p) => { calls.push(['link', id, s, p]); return { subject: s, identity: 'content', format: 'elf', created: true }; },
    caseRecord: async (id, k, p) => { calls.push(['record', id, k, p]); return { record_id: 'r9', kind: k }; },
    caseReportUrl: (id) => `http://127.0.0.1:8777/api/cases/${id}/report`,
    analyze: async (kind, body, onLog) => { calls.push(['analyze', kind, body]); onLog('paso'); return { subject: 'a'.repeat(64), case_record: 'r1', open_incognitas: 1 }; },
  };
}

test('eolfi_casos lista, ve, crea, asocia, registra e informa con el mismo estado del servidor', async () => {
  const calls = [];
  const tools = makeCaseTools({ client: async () => fakeClient(calls) });
  assert.deepStrictEqual(tools.names(), ['eolfi_casos', 'eolfi_caso_analizar', 'eolfi_observar']);
  const run = (input) => tools.run({ name: 'eolfi_casos', input }, null, null);
  assert.match(await run({ accion: 'listar' }), /Caso \(c1\).*último: triage done/);
  const shown = await run({ accion: 'ver', case_id: 'c1' });
  assert.match(shown, /parcial|partial/);
  assert.match(shown, /\(hypothesis\) quizá/);
  assert.match(shown, /no reverificada/);
  assert.match(await run({ accion: 'crear', nombre: 'N', descripcion: 'D' }), /c2/);
  assert.match(await run({ accion: 'asociar', case_id: 'c1', objetivo: 'x', procedencia: 'p' }), /identidad content/);
  await run({ accion: 'registrar', case_id: 'c1', tipo: 'bogus', datos: { claims: [] } });
  assert.deepStrictEqual(calls.find((c) => c[0] === 'record'), ['record', 'c1', 'specification', { claims: [] }]);
  assert.match(await run({ accion: 'informe', case_id: 'c1' }), /\/api\/cases\/c1\/report/);
  await assert.rejects(run({ accion: 'ver' }), /case_id/);
});

test('eolfi_caso_analizar envía case_id en el trabajo y resume estado, herramientas y errores', async () => {
  const calls = [];
  const progress = [];
  const tools = makeCaseTools({ client: async () => fakeClient(calls) });
  const out = await tools.run({ name: 'eolfi_caso_analizar', input: { case_id: 'c1', tipo: 'binario', ruta: 'C:\\x.exe' } },
    { progress: (m) => progress.push(m) }, null);
  assert.deepStrictEqual(calls[0], ['analyze', 'triage', { path: 'C:\\x.exe', mode: 'local', case_id: 'c1' }]);
  assert.match(out, /estado partial/);
  assert.match(out, /eolfi\.triage 0\.2 \(ran\)/);
  assert.match(out, /boom falló/);
  assert.ok(progress.includes('paso'));
  assert.match(await tools.run({ name: 'eolfi_caso_analizar', input: { case_id: 'c1', tipo: 'x', ruta: 'y' } }), /tipo/);
  assert.strictEqual(await tools.run({ name: 'otra', input: {} }), null);
});

test('combineTools reparte las llamadas entre juegos de herramientas', async () => {
  const a = { defs: () => [{ name: 'a' }], names: () => ['a'], run: async () => 'A' };
  const b = { defs: () => [{ name: 'b' }], names: () => ['b'], run: async () => 'B' };
  const both = combineTools(a, null, b);
  assert.deepStrictEqual(both.names(), ['a', 'b']);
  assert.strictEqual(await both.run({ name: 'b' }), 'B');
  assert.strictEqual(await both.run({ name: 'z' }), null);
});

test('summarizeCase muestra identidad e incógnitas abiertas', () => {
  const s = summarizeCase(CASE);
  assert.match(s, /content aaaaaaaaaaaaaaaa · elf · 10/);
  assert.match(s, /\? \[medium\] ¿qué hace\? \(i1\)/);
});

test('el cliente usa las rutas de casos de la API con token y cabecera anti-CSRF', async () => {
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      seen.push({ method: req.method, url: req.url, body: body ? JSON.parse(body) : null, auth: req.headers.authorization, csrf: req.headers['x-eolfi'] });
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const c = makeClient(base, 'tok');
    await c.cases();
    await c.caseGet('c 1');
    await c.caseCreate('N', 'D');
    await c.caseLink('c1', 'sub', 'prov');
    await c.caseRecord('c1', 'specification', { claims: [] });
    assert.deepStrictEqual(seen.map((s) => `${s.method} ${s.url}`), ['GET /api/cases', 'GET /api/cases/c%201', 'POST /api/cases',
      'POST /api/cases/c1/artifacts', 'POST /api/cases/c1/records']);
    assert.deepStrictEqual(seen[3].body, { subject: 'sub', provenance: 'prov' });
    assert.ok(seen.every((s) => s.auth === 'Bearer tok' && s.csrf === '1'));
    assert.strictEqual(c.caseReportUrl('c1'), `${base}/api/cases/c1/report`);
  } finally { server.close(); }
});

test('eolfi_observar: ver, comparar y no ejecutar sin autorización explícita', async () => {
  const calls = [];
  const session = { evidence_id: 'e1', name: 'g', status: 'partial', steps: [
    { id: 'arranque', action: 'run', status: 'ok', exit_status: { kind: 'exit', code: 0 }, effects: { files: [{}, {}] } },
    { id: 'ui', action: 'browser', status: 'unavailable', error: 'sin Node', effects: { files: [] } }],
    coverage: { system_calls: { status: 'not_available' }, process_io: 'observed' }, unfixed_factors: [{ factor: 'reloj' }] };
  const client = { ...fakeClient(calls),
    observeGet: async (id) => { calls.push(['oget', id]); return { evidence_id: id, session }; },
    observeCompare: async (b) => { calls.push(['ocmp', b]); return { a: b.a, b: b.b, identical: false, differences_total: 2,
      first_change: { step: 'arranque', aspect: 'stderr', detail: ['-aviso v1', '+aviso v2'] },
      attribution: { status: 'hypothesis', candidates: ['objetivo (sha256)'] } }; },
    observeRun: async (b) => { calls.push(['orun', b]); return { evidence_id: 'e2', ...session }; },
    observeReplay: async (b) => { calls.push(['orep', b]); return { replay: 'e3', reproducible: false, prechecks: [],
      non_reproducible: [{ step: 'azar', aspect: 'stdout' }], unfixed_factors: [{ factor: 'reloj' }] }; } };
  const tools = makeCaseTools({ client: async () => client });
  const run = (input) => tools.run({ name: 'eolfi_observar', input }, null, null);
  const shown = await run({ accion: 'ver', evidence_id: 'e1' });
  assert.match(shown, /arranque: run · ok · código 0 · 2 cambios de archivo/);
  assert.match(shown, /ui: browser · unavailable · error: sin Node/);
  assert.match(shown, /system_calls: not_available/);
  assert.match(shown, /Factores no fijados: reloj/);
  const cmp = await run({ accion: 'comparar', a: 'x', b: 'y', case_id: 'c1' });
  assert.match(cmp, /Primer cambio observable: paso arranque, stderr/);
  assert.match(cmp, /Hipótesis \(sin confirmar\): objetivo \(sha256\)/);
  assert.match(await run({ accion: 'ejecutar', guion: 'g.json' }), /No ejecutado/);
  assert.match(await run({ accion: 'repetir', evidence_id: 'e1', autorizado: 'true' }), /No ejecutado/);
  assert.ok(!calls.some((c) => c[0] === 'orun' || c[0] === 'orep'));
  await run({ accion: 'ejecutar', guion: 'g.json', autorizado: true, variables: { port: 8 } });
  assert.deepStrictEqual(calls.find((c) => c[0] === 'orun')[1], { script: 'g.json', variables: { port: '8' }, case_id: undefined, authorized: true });
  assert.match(await run({ accion: 'repetir', evidence_id: 'e1', autorizado: true }), /NO reproducible[\s\S]*azar: stdout/);
});
