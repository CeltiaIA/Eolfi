// Lógica del puente Eolfi ↔ modelos de VS Code, independiente de VS Code para poder probarla con un «vscode» falso.
//
// Seguridad:
// - Solo 127.0.0.1, Host de loopback y token aleatorio (Authorization: Bearer).
// - El modelo lo da la Language Model API: la PRIMERA petición hace que VS Code te pida permiso.
// - Herramientas: solo las que pongas en el ajuste «eolfi.allowedTools» Y la petición pida por nombre.
'use strict';
const { timingSafeEqual } = require('node:crypto');
const { TOOL_DEFS } = require('./workspace');

const MAX_BODY = 2 * 1024 * 1024;
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);
const MAX_TOOL_ROUNDS = 6;

function json(res, status, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': body.length, 'Cache-Control': 'no-store' });
  res.end(body);
}

function sameToken(given, token) {
  const a = Buffer.from(String(given || '')), b = Buffer.from(token);
  return a.length === b.length && timingSafeEqual(a, b);
}

function errorStatus(vscode, e) {
  const code = e && (e.code || e.name || '');
  if (vscode.LanguageModelError && e instanceof vscode.LanguageModelError) {
    if (/NoPermissions/i.test(code)) return [403, 'No has dado permiso a esta extensión para usar los modelos de IA (acéptalo en VS Code)'];
    if (/NotFound/i.test(code)) return [404, 'No hay ningún modelo de IA disponible en VS Code (¿sesión iniciada en el asistente?)'];
    if (/Blocked/i.test(code)) return [429, 'El modelo de IA ha limitado las peticiones: espera un poco'];
  }
  return [502, String((e && e.message) || e)];
}

// Modelos que ya fallaron por restricción («only available to VS Code core», «Auto mode…»): no se reintentan.
const REFUSED = new Set();
let LAST_GOOD = null;
const RESTRICTED = /only available to VS Code core|Auto mode needs|not (?:supported|available) for (?:extensions|tool)/i;

// Candidatos en orden: el pedido por nombre; si no, el último que funcionó y luego los generales de mayor contexto.
async function candidateModels(vscode, body) {
  const selector = { vendor: typeof body.vendor === 'string' ? body.vendor : 'copilot' };
  const models = await vscode.lm.selectChatModels(selector);
  if (!models.length) {
    const err = new Error('No hay modelos de IA disponibles (¿has iniciado sesión en el asistente de IA de VS Code?)');
    err.status = 404;
    throw err;
  }
  const want = typeof body.model === 'string' ? body.model.toLowerCase() : '';
  if (want) {
    const named = models.find((m) => [m.id, m.family, m.name].some((x) => String(x || '').toLowerCase() === want))
      || models.find((m) => [m.id, m.family, m.name].some((x) => String(x || '').toLowerCase().includes(want)));
    if (named) return [named];
  }
  // Fuera los de dictado de VS Code y «Auto» (no admite herramientas); «copilot-utility» (GPT-4.1) sí vale.
  const general = models.filter((m) => !/dictation|cleanup/i.test(`${m.id} ${m.family}`) && m.id !== 'auto');
  const ordered = [...(general.length ? general : models)].sort((a, b) => (b.maxInputTokens || 0) - (a.maxInputTokens || 0))
    .filter((m) => !REFUSED.has(m.id));
  const good = ordered.find((m) => m.id === LAST_GOOD);
  return good ? [good, ...ordered.filter((m) => m !== good)] : ordered.length ? ordered : models;
}

async function pickModel(vscode, body) {
  return (await candidateModels(vscode, body))[0];
}

function toMessages(vscode, messages) {
  const M = vscode.LanguageModelChatMessage;
  const text = (m) => (typeof m.content === 'string' ? m.content : JSON.stringify(m.content));
  const system = messages.filter((m) => m.role === 'system').map(text).join('\n\n');
  const rest = messages.filter((m) => m.role !== 'system');
  // La Language Model API no tiene rol «system»: va delante del primer mensaje (si es del usuario) o solo.
  const out = rest.map((m, i) => {
    if (m.role === 'assistant') return M.Assistant(text(m));
    return M.User(i === 0 && system ? `${system}\n\n${text(m)}` : text(m));
  });
  if (system && (!rest.length || rest[0].role === 'assistant')) out.unshift(M.User(system));
  return out;
}

async function chat(vscode, body, allowedTools, cancelToken, log, actions = null) {
  if (!Array.isArray(body.messages) || !body.messages.length) {
    const e = new Error('messages debe ser una lista no vacía'); e.status = 400; throw e;
  }
  const candidates = await candidateModels(vscode, body);
  let model = candidates[0];
  const asked = Array.isArray(body.tools) ? body.tools.filter((t) => typeof t === 'string') : [];
  const denied = asked.filter((t) => !allowedTools.includes(t));
  if (denied.length) {
    const e = new Error(`herramientas no permitidas: ${denied.join(', ')} (añádelas a «eolfi.allowedTools» en VS Code)`);
    e.status = 403; throw e;
  }
  const tools = (vscode.lm.tools || []).filter((t) => asked.includes(t.name))
    .map((t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema }));
  // Herramientas propias del puente (leer, buscar, abrir y escribir en el workspace): las ejecuta el puente.
  // true = todas (escribir pide confirmación en VS Code); "read" = solo leer, listar, buscar y abrir.
  const own = !actions ? [] : body.workspace_tools === true ? TOOL_DEFS
    : body.workspace_tools === 'read' ? TOOL_DEFS.filter((d) => d.action !== 'write') : [];
  for (const d of own) tools.push({ name: d.name, description: d.description, inputSchema: d.inputSchema });
  const msgs = toMessages(vscode, body.messages);
  const calls = [];
  let text = '';
  const auto = body.auto_approve === true && own.some((d) => d.action === 'write');
  const journal = own.some((d) => d.action === 'write') && actions?.journal_start ? (await actions.journal_start()).journal : null;
  try {
  const options = { justification: 'Eolfi quiere usar el modelo de IA para analizar o generar código en tu equipo.', ...(tools.length ? { tools } : {}) };
  // Una petición completa (enviar y leer el flujo: el rechazo de un modelo puede llegar al leerlo).
  const ask = async (m) => {
    const res = await m.sendRequest(msgs, options, cancelToken);
    let t = '';
    const calls = [];
    for await (const part of res.stream) {
      if (vscode.LanguageModelTextPart && part instanceof vscode.LanguageModelTextPart) t += part.value;
      else if (vscode.LanguageModelToolCallPart && part instanceof vscode.LanguageModelToolCallPart) calls.push(part);
      else if (typeof part === 'string') t += part;
    }
    return [t, calls];
  };
  for (let round = 0; round <= MAX_TOOL_ROUNDS; round++) {
    let roundText, pending;
    if (round === 0) {
      // Primera ronda: si un modelo está restringido para extensiones, se prueba el siguiente.
      for (let i = 0; ; i++) {
        model = candidates[i];
        try { [roundText, pending] = await ask(model); LAST_GOOD = model.id; break; } catch (e) {
          if (!RESTRICTED.test(String(e && e.message)) || i + 1 >= candidates.length) throw e;
          REFUSED.add(model.id);
          log(`modelo ${model.id} no disponible para extensiones: se prueba ${candidates[i + 1].id}`);
        }
      }
    } else [roundText, pending] = await ask(model);
    text += roundText;
    if (!pending.length) break;
    if (round === MAX_TOOL_ROUNDS) { text += '\n[Eolfi: se alcanzó el máximo de rondas de herramientas]'; break; }
    msgs.push(vscode.LanguageModelChatMessage.Assistant([...(roundText ? [new vscode.LanguageModelTextPart(roundText)] : []), ...pending]));
    const results = [];
    for (const call of pending) {
      const ownDef = own.find((d) => d.name === call.name);
      if (ownDef) {
        try {
          log(`acción ${ownDef.action}`);
          const input = ownDef.action === 'write' ? { ...(call.input || {}), auto, journal } : (call.input || {});
          const r = await actions[ownDef.action](input);
          results.push(new vscode.LanguageModelToolResultPart(call.callId, [new vscode.LanguageModelTextPart(JSON.stringify(r).slice(0, 200000))]));
          calls.push({ name: call.name, ok: true });
        } catch (e) {
          results.push(new vscode.LanguageModelToolResultPart(call.callId, [new vscode.LanguageModelTextPart(`Error: ${e.message || e}`)]));
          calls.push({ name: call.name, ok: false, error: String(e.message || e).slice(0, 300) });
        }
        continue;
      }
      if (!asked.includes(call.name)) {   // el modelo pidió una herramienta que no se le ofreció
        results.push(new vscode.LanguageModelToolResultPart(call.callId, [new vscode.LanguageModelTextPart('Herramienta no permitida.')]));
        calls.push({ name: call.name, ok: false });
        continue;
      }
      try {
        log(`herramienta ${call.name}`);
        const r = await vscode.lm.invokeTool(call.name, { input: call.input, toolInvocationToken: undefined }, cancelToken);
        results.push(new vscode.LanguageModelToolResultPart(call.callId, r.content));
        calls.push({ name: call.name, ok: true });
      } catch (e) {
        results.push(new vscode.LanguageModelToolResultPart(call.callId, [new vscode.LanguageModelTextPart(`Error: ${e.message || e}`)]));
        calls.push({ name: call.name, ok: false, error: String(e.message || e).slice(0, 300) });
      }
    }
    msgs.push(vscode.LanguageModelChatMessage.User(results));
  }
  } catch (e) {
    // «Si todo va bien»: si la petición falla a medias, lo escrito en ella se deshace solo.
    if (journal) { try { const u = await actions.undo({ journal }); log(`deshecho: ${u.restored.length} archivos`); } catch { /* nada que deshacer */ } }
    throw e;
  }
  return { text, model: { id: model.id, family: model.family, name: model.name, vendor: model.vendor }, tool_calls: calls,
    ...(journal ? { journal, written: calls.filter((c) => c.name === 'eolfi_write_file' && c.ok).length } : {}) };
}

function makeHandler({ vscode, token, getAllowedTools = () => [], log = () => {}, actions = null }) {
  if (!token || token.length < 32) throw new Error('token demasiado corto');
  return (req, res) => {
    const raw = String(req.headers.host || '').toLowerCase();
    const host = raw.startsWith('[') ? raw.slice(0, raw.indexOf(']') + 1) : raw.split(':')[0];
    if (!LOOPBACK.has(host)) return json(res, 421, { error: 'Host no permitido' });
    if (!sameToken((req.headers.authorization || '').replace(/^Bearer\s+/i, ''), token)) return json(res, 401, { error: 'token inválido' });
    const url = new URL(req.url, 'http://127.0.0.1');
    const fail = (e) => { const [st, msg] = e.status ? [e.status, e.message] : errorStatus(vscode, e); if (!res.headersSent) json(res, st, { error: msg }); };

    if (req.method === 'GET' && url.pathname === '/v1/status') {
      Promise.resolve(vscode.lm.selectChatModels({ vendor: 'copilot' })).then((ms) => json(res, 200, {
        ok: ms.length > 0, vscode: vscode.version, models: ms.length, allowed_tools: getAllowedTools(),
      })).catch(fail);
      return;
    }
    if (req.method === 'GET' && url.pathname === '/v1/models') {
      Promise.resolve(vscode.lm.selectChatModels({ vendor: url.searchParams.get('vendor') || 'copilot' })).then((ms) => json(res, 200, {
        models: ms.map((m) => ({ id: m.id, name: m.name, family: m.family, vendor: m.vendor, version: m.version, max_input_tokens: m.maxInputTokens })),
      })).catch(fail);
      return;
    }
    if (req.method === 'GET' && url.pathname === '/v1/tools') {
      const allowed = getAllowedTools();
      return json(res, 200, { tools: (vscode.lm.tools || []).map((t) => ({ name: t.name, description: String(t.description || '').slice(0, 300),
        tags: t.tags || [], allowed: allowed.includes(t.name) })) });
    }
    if (req.method === 'POST' && url.pathname === '/v1/chat') {
      const chunks = [];
      let size = 0;
      req.on('data', (c) => { size += c.length; if (size <= MAX_BODY) chunks.push(c); });
      req.on('end', async () => {
        if (size > MAX_BODY) return json(res, 413, { error: 'petición demasiado grande' });
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        const cts = new vscode.CancellationTokenSource();
        res.on('close', () => { if (!res.writableEnded) cts.cancel(); });
        try {
          const out = await chat(vscode, body || {}, getAllowedTools(), cts.token, log, actions);
          json(res, 200, out);
        } catch (e) { fail(e); } finally { cts.dispose?.(); }
      });
      return;
    }
    // Acciones directas sobre VS Code: workspace, list, read, find, open, write, command; y herramientas permitidas.
    const m = url.pathname.match(/^\/v1\/workspace\/(workspace|list|read|find|open|write|command|journal_start|undo)$/);
    if (req.method === 'POST' && (m || url.pathname === '/v1/tool')) {
      if (!actions && m) return json(res, 501, { error: 'acciones de workspace no disponibles' });
      const chunks = [];
      let size = 0;
      req.on('data', (c) => { size += c.length; if (size <= MAX_BODY) chunks.push(c); });
      req.on('end', async () => {
        if (size > MAX_BODY) return json(res, 413, { error: 'petición demasiado grande' });
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        try {
          if (m) return json(res, 200, await actions[m[1]](body || {}));
          if (typeof body.name !== 'string' || !getAllowedTools().includes(body.name)) {
            return json(res, 403, { error: `herramienta no permitida: ${body.name} (añádela a «eolfi.allowedTools»)` });
          }
          const cts = new vscode.CancellationTokenSource();
          const r = await vscode.lm.invokeTool(body.name, { input: body.input || {}, toolInvocationToken: undefined }, cts.token);
          const text = (r.content || []).map((x) => (x && typeof x.value === 'string' ? x.value : JSON.stringify(x))).join('\n');
          return json(res, 200, { name: body.name, text: text.slice(0, 200000) });
        } catch (e) { fail(e); }
      });
      return;
    }
    json(res, 404, { error: 'ruta no encontrada' });
  };
}

module.exports = { makeHandler, chat, toMessages, pickModel, MAX_BODY };
