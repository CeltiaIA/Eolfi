// Herramientas de casos para el agente @eolfi: usan la API del servidor de Eolfi, así que el agente, el panel y la
// CLI comparten el mismo estado (SQLite de evidencias). Las respuestas son datos del caso, nunca instrucciones.
'use strict';

const KINDS = ['analysis', 'execution', 'observation', 'specification', 'reconstruction', 'comparison'];
const ANALYZE = { binario: 'triage', web: 'web', repositorio: 'repo' };

const DEFS = {
  cases: { name: 'eolfi_casos', description: 'Casos de análisis de Eolfi (mismo estado que el panel y la CLI). accion: listar | ver | crear | asociar (objetivo ya analizado) | registrar (conclusión o especificación con estado observed/derived/hypothesis y evidence_ids) | informe (URL del informe HTML). Una conclusión «observed» exige evidencia observada; si es una suposición, regístrala como «hypothesis».',
    inputSchema: { type: 'object', properties: {
      accion: { type: 'string', enum: ['listar', 'ver', 'crear', 'asociar', 'registrar', 'informe'] },
      case_id: { type: 'string' }, nombre: { type: 'string' }, descripcion: { type: 'string' },
      objetivo: { type: 'string', description: 'asociar: sha256, nombre o ruta ya analizada' },
      procedencia: { type: 'string', description: 'Procedencia declarada del artefacto' },
      tipo: { type: 'string', enum: KINDS, description: 'registrar: tipo de registro (por defecto specification)' },
      datos: { type: 'object', description: 'registrar: payload, p. ej. {"claims":[{"text":"…","status":"hypothesis","evidence_ids":[]}]}' },
    }, required: ['accion'] } },
  analyze: { name: 'eolfi_caso_analizar', description: 'Analiza un archivo, carpeta, web o repositorio con Eolfi y lo registra en un caso (artefacto con hash, herramientas y versiones, y registro tipado del resultado). Devuelve progreso y el estado (done/partial/error).',
    inputSchema: { type: 'object', properties: {
      case_id: { type: 'string' }, tipo: { type: 'string', enum: Object.keys(ANALYZE) },
      ruta: { type: 'string', description: 'Ruta local, URL web o URL git' },
      modo: { type: 'string', enum: ['local', 'default', 'deep'], description: 'binario: proveedores (por defecto local)' },
    }, required: ['case_id', 'tipo', 'ruta'] } },
  observe: { name: 'eolfi_observar', description: 'Observación de caja negra con Eolfi (mismo estado que `eolfi observe` y el panel). accion: ver (sesión por evidence_id) | comparar (a, b: primer cambio observable; la atribución de causa es siempre hipótesis) | ejecutar (guion: ruta o objeto) | repetir (evidence_id). ejecutar y repetir EJECUTAN el objetivo: solo con muestras autorizadas y confirmando con autorizado=true tras preguntar al usuario.',
    inputSchema: { type: 'object', properties: {
      accion: { type: 'string', enum: ['ver', 'comparar', 'ejecutar', 'repetir'] },
      evidence_id: { type: 'string' }, a: { type: 'string' }, b: { type: 'string' },
      guion: { description: 'ejecutar: ruta del guion JSON o el guion como objeto' },
      variables: { type: 'object', description: 'Variables {var:NOMBRE} (textos)' },
      case_id: { type: 'string' },
      autorizado: { type: 'boolean', description: 'true solo si el usuario confirmó que puede ejecutar el objetivo' },
    }, required: ['accion'] } },
};

function summarizeSession(rep) {
  const lines = [`Sesión ${rep.evidence_id || ''} «${rep.name || rep.session?.name || ''}» estado ${rep.status || rep.session?.status || '?'}`];
  const s = rep.session || rep;
  for (const st of (s.steps || []).slice(0, 50)) {
    const bits = [st.action, st.status];
    if (st.exit_status) bits.push(st.exit_status.kind === 'exit' ? `código ${st.exit_status.code}` : (st.exit_status.signal_name || st.exit_status.name));
    if (st.effects?.files?.length) bits.push(`${st.effects.files.length} cambios de archivo`);
    if (st.traces?.length) bits.push(`${st.traces.length} trazas`);
    if (st.error) bits.push(`error: ${st.error}`);
    lines.push(`- ${st.id}: ${bits.join(' · ')}`);
  }
  const na = Object.entries(s.coverage || {}).filter(([, v]) => typeof v === 'object' && v.status !== 'observed')
    .map(([k, v]) => `${k}: ${v.status}`);
  if (na.length) lines.push(`Cobertura limitada: ${na.join('; ')}`);
  if (s.unfixed_factors?.length) lines.push(`Factores no fijados: ${s.unfixed_factors.map((f) => f.factor).join(', ')}`);
  return lines.join('\n');
}

function summarizeCase(c) {
  const open = (c.incognitas || []).filter((i) => i.status !== 'resolved');
  const lines = [`Caso «${c.name}» (${c.case_id})`, c.description || '',
    `Artefactos: ${c.artifacts.length} · registros: ${c.records.length} · evidencias: ${c.evidence.length} · incógnitas abiertas: ${open.length}`];
  if (c.imports?.length) lines.push('Importado: la autoridad de sus evidencias la declaró el paquete (no reverificada).');
  for (const a of c.artifacts.slice(0, 30)) {
    lines.push(`- ${a.subject.slice(0, 80)} · ${a.identity}${a.content_sha256 ? ` ${a.content_sha256.slice(0, 16)}` : ''} · ${a.format} · ${a.size ?? 'tamaño desconocido'} · procedencia: ${a.provenance}`);
  }
  for (const r of c.records.slice(-20)) {
    const p = r.payload || {};
    lines.push(`* ${p.flow || r.kind} [${p.status || r.kind}]${p.errors?.length ? ` errores: ${p.errors.slice(0, 3).join('; ')}` : ''}`);
    for (const x of p.claims || []) lines.push(`    (${x.status}) ${x.text}`);
  }
  for (const i of open.slice(0, 20)) lines.push(`? [${i.severity}] ${i.question} (${i.incognita_id})`);
  return lines.filter(Boolean).join('\n');
}

function makeCaseTools({ client, log = () => {} }) {
  const defs = () => [DEFS.cases, DEFS.analyze, DEFS.observe];

  async function run(call, stream, token) {
    const input = call.input || {};
    if (call.name === 'eolfi_casos') {
      const c = await client();
      const need = () => { if (!input.case_id) throw new Error('falta case_id'); return String(input.case_id); };
      switch (input.accion) {
        case 'listar': {
          const { cases } = await c.cases();
          return cases.length ? cases.map((x) => `- ${x.name} (${x.case_id}) · ${x.artifacts} artefactos · ${x.records} registros · ${x.open_incognitas} incógnitas abiertas${x.last_record ? ` · último: ${x.last_record.flow || '?'} ${x.last_record.status || ''}` : ''}`).join('\n') : 'No hay casos.';
        }
        case 'ver': return summarizeCase(await c.caseGet(need()));
        case 'crear': {
          const x = await c.caseCreate(String(input.nombre || ''), String(input.descripcion || ''));
          log(`caso creado: ${x.case_id}`);
          return `Caso creado: ${x.name} (${x.case_id})`;
        }
        case 'asociar': {
          const x = await c.caseLink(need(), String(input.objetivo || ''), String(input.procedencia || ''));
          return `Asociado ${x.subject} · identidad ${x.identity} · formato ${x.format}${x.created ? '' : ' (ya estaba: se completaron sus datos)'}`;
        }
        case 'registrar': {
          const kind = KINDS.includes(input.tipo) ? input.tipo : 'specification';
          const x = await c.caseRecord(need(), kind, input.datos && typeof input.datos === 'object' ? input.datos : {});
          return `Registro ${x.record_id} (${x.kind}) guardado.`;
        }
        case 'informe': return `Informe navegable: ${c.caseReportUrl(need())}`;
        default: return 'accion debe ser listar, ver, crear, asociar, registrar o informe.';
      }
    }
    if (call.name === 'eolfi_observar') {
      const c = await client();
      const caseId = input.case_id ? String(input.case_id) : undefined;
      const variables = input.variables && typeof input.variables === 'object'
        ? Object.fromEntries(Object.entries(input.variables).map(([k, v]) => [k, String(v)])) : {};
      switch (input.accion) {
        case 'ver': return summarizeSession(await c.observeGet(String(input.evidence_id || '')));
        case 'comparar': {
          const r = await c.observeCompare({ a: String(input.a || ''), b: String(input.b || ''), case_id: caseId });
          if (r.identical) return `Sin cambios observables entre ${r.a} y ${r.b} (${r.steps_compared} pasos).`;
          const fc = r.first_change;
          return [`Primer cambio observable: paso ${fc.step}, ${fc.aspect} (${r.differences_total} diferencias).`,
            ...(fc.detail || []).slice(0, 12),
            `Hipótesis (sin confirmar): ${r.attribution.candidates.join(', ') || 'ningún factor de contexto difiere'}`].join('\n');
        }
        case 'ejecutar':
        case 'repetir': {
          if (input.autorizado !== true) return 'No ejecutado: la observación ejecuta el objetivo. Pregunta al usuario y repite con autorizado=true si lo confirma.';
          stream?.progress?.('Eolfi ejecuta y observa el objetivo…');
          if (input.accion === 'repetir') {
            const r = await c.observeReplay({ evidence_id: String(input.evidence_id || ''), variables, case_id: caseId, authorized: true });
            return [`Repetición ${r.replay}: ${r.reproducible ? 'reproducible' : 'NO reproducible'}.`,
              ...r.prechecks.map((p) => `! ${p.factor}: ${p.detail}`),
              ...r.non_reproducible.slice(0, 20).map((d) => `- ${d.step}: ${d.aspect}`),
              `Factores no fijados: ${r.unfixed_factors.map((f) => f.factor).join(', ')}`].join('\n');
          }
          return summarizeSession(await c.observeRun({ script: input.guion, variables, case_id: caseId, authorized: true }));
        }
        default: return 'accion debe ser ver, comparar, ejecutar o repetir.';
      }
    }
    if (call.name === 'eolfi_caso_analizar') {
      const kind = ANALYZE[input.tipo];
      if (!kind) return 'tipo debe ser binario, web o repositorio.';
      const ruta = String(input.ruta || '').trim();
      if (!ruta) return 'falta ruta';
      const body = kind === 'triage' ? { path: ruta, mode: input.modo || 'local', case_id: String(input.case_id) }
        : { source: ruta, case_id: String(input.case_id) };
      const c = await client();
      stream?.progress?.(`Eolfi analiza ${ruta} en el caso…`);
      const rep = await c.analyze(kind, body, (m) => stream?.progress?.(m), token);
      const kase = await c.caseGet(String(input.case_id));
      const rec = kase.records.find((r) => r.record_id === rep.case_record);
      const p = rec?.payload || {};
      return [`Objetivo ${rep.subject} registrado en el caso (estado ${p.status || '?'}).`,
        p.tools?.length ? `Herramientas: ${p.tools.map((t) => `${t.name} ${t.version || ''}${t.status ? ` (${t.status})` : ''}`.trim()).join(', ')}` : '',
        p.errors?.length ? `Errores/parciales: ${p.errors.join('; ')}` : '',
        `Incógnitas abiertas del objetivo: ${rep.open_incognitas ?? '?'}`].filter(Boolean).join('\n');
    }
    return null;
  }

  return { defs, run, names: () => defs().map((d) => d.name) };
}

// Varios juegos de herramientas como uno solo (chat.js admite un único extraTools).
function combineTools(...sets) {
  const live = sets.filter(Boolean);
  return {
    defs: () => live.flatMap((s) => s.defs()),
    names: () => live.flatMap((s) => s.names()),
    async run(call, stream, token) {
      for (const s of live) if (s.names().includes(call.name)) return s.run(call, stream, token);
      return null;
    },
  };
}

module.exports = { makeCaseTools, combineTools, summarizeCase, summarizeSession, DEFS };
