// Cliente del servidor de Eolfi (python -m eolfi serve) para usar Eolfi DESDE VS Code como herramienta de
// ingeniería inversa: analizar archivos y carpetas, ver evidencias, incógnitas e informes.
'use strict';
const http = require('node:http');

function request(base, method, path, body = null, timeoutMs = 30000, authToken = null) {
  return new Promise((resolve, reject) => {
    const u = new URL(path, base);
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const req = http.request(u, {
      method, timeout: timeoutMs,
      // El servidor exige X-Eolfi en las escrituras (anti-CSRF); el Host es el de loopback de la URL.
      // X-Eolfi-Client + token propio: el servidor rechaza a un cliente sin vincular o revocado (401).
      headers: { 'X-Eolfi': '1', 'X-Eolfi-Client': 'vscode',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {}) },
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let json = null;
        try { json = JSON.parse(text); } catch { /* informe en texto */ }
        if (res.statusCode >= 400) {
          const e = new Error((json && json.error) || `HTTP ${res.statusCode}`);
          e.status = res.statusCode;
          return reject(e);
        }
        resolve(json ?? text);
      });
    });
    req.on('timeout', () => req.destroy(new Error('el servidor de Eolfi no responde')));
    req.on('error', (e) => reject(e.code === 'ECONNREFUSED'
      ? new Error(`El servidor de Eolfi no está arrancado en ${base} (python -m eolfi serve)`) : e));
    if (data) req.write(data);
    req.end();
  });
}

function makeClient(base, authToken = null) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const req = (method, path, body = null, timeout = 30000) => request(base, method, path, body, timeout, authToken);
  return {
    base,
    // Canje del código de vinculación por un token (lo único que se hace sin token).
    exchange: (code, name) => request(base, 'POST', '/api/clients/token', { code, name }),
    health: () => req('GET', '/api/health'),
    // Análisis como trabajo en segundo plano, con progreso.
    async analyze(kind, body, onLog = () => {}, signal = null) {
      const { job_id: id } = await req('POST', '/api/jobs', { kind, body });
      let since = 0;
      for (;;) {
        if (signal?.isCancellationRequested) {
          await req('DELETE', `/api/jobs?id=${id}`).catch(() => {});
          throw new Error('Cancelado');
        }
        const d = await req('GET', `/api/jobs?id=${id}&since=${since}`);
        for (const l of d.log || []) onLog(l.msg);
        since = d.next;
        if (d.status === 'done') return d.result;
        if (d.status === 'error' || d.status === 'cancelled') throw new Error(d.error || d.status);
        await sleep(700);
      }
    },
    incognitas: (subject) => req('GET', `/api/incognitas?subject=${encodeURIComponent(subject)}`),
    report: (subject, format = 'md') => req('GET', `/api/report?format=${format}&subject=${encodeURIComponent(subject)}`),
    // Casos de análisis: el mismo estado que el panel y la CLI (eolfi case …).
    cases: () => req('GET', '/api/cases'),
    caseGet: (id) => req('GET', `/api/cases/${encodeURIComponent(id)}`),
    caseCreate: (name, description = '') => req('POST', '/api/cases', { name, description }),
    caseLink: (id, subject, provenance = '') => req('POST', `/api/cases/${encodeURIComponent(id)}/artifacts`, { subject, provenance }),
    caseRecord: (id, kind, payload) => req('POST', `/api/cases/${encodeURIComponent(id)}/records`, { kind, payload }),
    caseReportUrl: (id) => new URL(`/api/cases/${encodeURIComponent(id)}/report`, base).href,
    // Observación de caja negra (eolfi observe): run/replay ejecutan el objetivo y exigen authorized=true.
    observeGet: (id) => req('GET', `/api/observe/${encodeURIComponent(id)}`),
    observeRun: (body) => req('POST', '/api/observe/run', body),
    observeReplay: (body) => req('POST', '/api/observe/replay', body),
    observeCompare: (body) => req('POST', '/api/observe/compare', body),
  };
}

// Resumen legible de un análisis para el canal de salida de VS Code.
function summarize(rep, incognitas) {
  const lines = [`Objetivo: ${rep.subject}`];
  if (rep.providers_run) lines.push(`Proveedores: ${rep.providers_run.join(', ')}${rep.providers_failed?.length ? ` (fallaron: ${rep.providers_failed.join(', ')})` : ''}`);
  for (const [k, v] of Object.entries(rep.summary || {})) lines.push(`  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
  const open = (incognitas || []).filter((i) => i.status !== 'resolved');
  lines.push(`Incógnitas abiertas: ${open.length}`);
  for (const i of open.slice(0, 30)) lines.push(`  [${i.severity}] ${i.question}`);
  return lines.join('\n');
}

module.exports = { makeClient, summarize, request };
