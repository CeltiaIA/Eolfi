// Memoria del agente @eolfi entre sesiones: cada petición (qué se pidió, qué respondió, qué herramientas usó y qué
// archivos cambió) se guarda en ~/.eolfi/agent-history.jsonl, solo en este equipo. El agente puede buscar en ella
// (eolfi_historial) y recibe un resumen de lo último hecho en la misma carpeta.
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const MAX_FILE = 20 * 1024 * 1024;   // al pasar de 20 MB se quedan las entradas más recientes
const MAX_TEXT = 6000;

function makeHistory({ file = process.env.EOLFI_HISTORY_FILE || path.join(os.homedir(), '.eolfi', 'agent-history.jsonl'), keepDays = () => 365, now = () => Date.now() } = {}) {
  function readAll() {
    let text;
    try { text = fs.readFileSync(file, 'utf8'); } catch { return []; }
    const out = [];
    for (const line of text.split('\n')) {
      if (!line.trim()) continue;
      try { out.push(JSON.parse(line)); } catch { /* línea dañada */ }
    }
    return out;
  }

  function compact() {
    const days = Math.max(1, Number(keepDays()) || 365);
    const limit = now() - days * 86400000;
    let keep = readAll().filter((e) => Date.parse(e.t) >= limit);
    let body = keep.map((e) => JSON.stringify(e)).join('\n');
    while (body.length > MAX_FILE * 0.7 && keep.length > 10) {
      keep = keep.slice(Math.floor(keep.length / 4));
      body = keep.map((e) => JSON.stringify(e)).join('\n');
    }
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, body ? `${body}\n` : '');
    fs.renameSync(tmp, file);
  }

  function add(entry) {
    const e = {
      id: require('node:crypto').randomBytes(5).toString('hex'),
      t: new Date(now()).toISOString(),
      folder: entry.folder || null,
      prompt: String(entry.prompt || '').slice(0, 2000),
      command: entry.command || null,
      response: String(entry.response || '').slice(0, MAX_TEXT),
      tools: (entry.tools || []).slice(0, 80),
      written: entry.written || [],
      model: entry.model || null,
      mode: entry.mode || null,
    };
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, `${JSON.stringify(e)}\n`);
    try { if (fs.statSync(file).size > MAX_FILE) compact(); } catch { /* sin compactar */ }
    return e;
  }

  // Búsqueda: todas las palabras (sin mayúsculas ni tildes) en lo pedido, la respuesta, los archivos o las herramientas.
  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  function search({ consulta = '', dias = 0, limite = 15, carpeta = null } = {}) {
    const words = norm(consulta).split(/\s+/).filter(Boolean);
    const since = Number(dias) > 0 ? now() - Number(dias) * 86400000 : 0;
    const folder = carpeta ? norm(carpeta) : null;
    return readAll().reverse().filter((e) => {
      if (since && Date.parse(e.t) < since) return false;
      if (folder && !norm(e.folder).startsWith(folder)) return false;
      const hay = norm(`${e.command ? `/${e.command} ${e.command}` : ''} ${e.prompt} ${e.response} ${(e.written || []).join(' ')} ${(e.tools || []).map((x) => `${x.name} ${x.arg || ''}`).join(' ')}`);
      return words.every((w) => hay.includes(w));
    }).slice(0, Math.max(1, Math.min(Number(limite) || 15, 100)));
  }

  function recent(folder, n = 5) {
    return search({ carpeta: folder, limite: n });
  }

  function format(entries, { full = false } = {}) {
    if (!entries.length) return 'No hay nada en el historial que coincida.';
    return entries.map((e) => {
      const when = e.t.replace('T', ' ').slice(0, 16);
      const files = (e.written || []).length ? `\n  archivos cambiados: ${e.written.join(', ')}` : '';
      const tools = (e.tools || []).length ? `\n  herramientas: ${[...new Set(e.tools.map((x) => x.name))].join(', ')}` : '';
      const resp = full ? e.response : e.response.replace(/\s+/g, ' ').slice(0, 500);
      return `- [${when}] (${e.mode || 'manual'}) «${e.prompt || `/${e.command}`}»${files}${tools}\n  respuesta: ${resp}`;
    }).join('\n');
  }

  function clear() { try { fs.rmSync(file, { force: true }); } catch { /* ya estaba vacío */ } }

  return { add, search, recent, format, clear, file };
}

module.exports = { makeHistory };
