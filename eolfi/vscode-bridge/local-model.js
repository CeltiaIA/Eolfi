// Modelo local de respaldo con llama.cpp (sin límites de peticiones y sin que el código salga del equipo):
//   1) Eolas (CeltIA): llama-server de D:\EOLAS-BASE\llama detrás de launch-eolas.ps1, en 127.0.0.1:11435.
//   2) Un llama-server propio (API compatible con OpenAI), por defecto en 127.0.0.1:8080.
// Solo direcciones de este equipo. Se usa cuando todos los modelos de Copilot están en su límite de peticiones.
'use strict';

const DEFAULT_ENDPOINTS = ['http://127.0.0.1:11435', 'http://127.0.0.1:8080'];
const PREFERRED = [/gemma-?4/i, /coder/i, /phi-?4/i, /gemma/i, /qwen/i, /llama/i, /mistral/i];
const NOT_FOR_REVIEW = /embed|rerank|vision|whisper|tts/i;

function safeJson(v) {
  if (v && typeof v === 'object') return v;
  try { return JSON.parse(String(v || '{}')); } catch { return {}; }
}

function isLoopback(url) {
  try { const u = new URL(url); return u.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname); } catch { return false; }
}

function pickModel(names, wanted = '') {
  if (wanted) return names.find((n) => n === wanted || n.split(':')[0] === wanted || n.includes(wanted)) || null;
  const ok = names.filter((n) => !NOT_FOR_REVIEW.test(n));
  for (const re of PREFERRED) { const hit = ok.find((n) => re.test(n)); if (hit) return hit; }
  return ok[0] || null;
}

async function getJson(fetchFn, url, ms = 3000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try { const r = await fetchFn(url, { signal: ctrl.signal }); return r.ok ? await r.json() : null; } catch { return null; } finally { clearTimeout(t); }
}

// fetch mínimo con node:http: el fetch de Node corta a los 5 minutos si no llegan las cabeceras, y un modelo local
// grande puede tardar más en revisar un lote.
function httpFetch(url, { method = 'GET', headers = {}, body, signal } = {}) {
  const http = require('node:http');
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method, headers: { ...headers, ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}) } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        resolve({ ok: res.statusCode < 400, status: res.statusCode, json: async () => JSON.parse(text), text: async () => text });
      });
    });
    req.on('error', reject);
    if (signal) {
      if (signal.aborted) req.destroy(new Error('cancelado'));
      signal.addEventListener?.('abort', () => req.destroy(new Error('cancelado')));
    }
    if (body) req.write(body);
    req.end();
  });
}

function makeLocalModel({ endpoints = DEFAULT_ENDPOINTS, model = '', fetchFn = httpFetch, timeoutMs = 20 * 60 * 1000, options = null,
  starter = null, allowStart = async () => true } = {}) {
  let found = null;   // { url, api: 'eolas' | 'openai', model }
  const opts = (o) => (options ? options(o) || {} : {});   // temperatura, longitud y razonamiento de la configuración
  let started = false;

  async function locate() {
    if (found) return found;
    const at = await probe(endpoints);
    if (at || !starter) return at;
    // Ninguno en marcha: se arranca un llama-server (si el usuario lo permite) y se usa ese.
    const plan = starter.plan();
    if (!plan.exe || !plan.model || !(await allowStart(plan))) return null;
    const url = await starter.start();
    started = true;
    return probe([url]);
  }

  async function probe(list) {
    for (const url of list.filter(isLoopback)) {
      // Eolas expone su API en /api/* (con el backend llama.cpp); llama-server, la de OpenAI en /v1/*.
      const tags = await getJson(fetchFn, `${url}/api/tags`);
      if (tags && Array.isArray(tags.models)) {
        const m = pickModel(tags.models.map((x) => x.name || x.model).filter(Boolean), model);
        if (m) { found = { url, api: 'eolas', model: m }; return found; }
      }
      const v1 = await getJson(fetchFn, `${url}/v1/models`);
      if (v1 && Array.isArray(v1.data)) {
        const m = pickModel(v1.data.map((x) => x.id).filter(Boolean), model) || v1.data[0]?.id || 'local';
        found = { url, api: 'openai', model: m };
        return found;
      }
    }
    return null;
  }

  async function ready() {
    let at = await locate();
    if (!at) throw new Error('no hay modelo local llama.cpp (arranca Eolas con launch-eolas.ps1 o un llama-server en 127.0.0.1:8080)');
    if (started && starter && !starter.running()) { found = null; at = await locate(); }   // se paró por inactividad: otra vez
    if (started) starter?.touch();
    return at;
  }

  // Una ronda de conversación con herramientas. messages en formato OpenAI (system/user/assistant con tool_calls/tool).
  // Devuelve { content, tool_calls: [{ id, name, arguments }] }.
  async function chatTools(messages, tools, token) {
    const at = await ready();
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    token?.onCancellationRequested?.(() => ctrl.abort());
    const fns = tools.map((x) => ({ type: 'function', function: { name: x.name, description: x.description, parameters: x.inputSchema || { type: 'object', properties: {} } } }));
    try {
      let endpoint, body;
      if (at.api === 'eolas') {
        // API de Eolas (como la de Ollama): argumentos como objeto y resultados de herramienta sin id.
        const msgs = messages.map((m) => (m.tool_calls ? { role: 'assistant', content: m.content || '', tool_calls: m.tool_calls.map((c) => ({ function: { name: c.function.name, arguments: safeJson(c.function.arguments) } })) }
          : m.role === 'tool' ? { role: 'tool', content: m.content, tool_name: m.name } : m));
        [endpoint, body] = [`${at.url}/api/chat`, { model: at.model, stream: false, messages: msgs, tools: fns, options: { num_ctx: 32768, temperature: opts().temperature ?? 0.2 } }];
      } else {
        [endpoint, body] = [`${at.url}/v1/chat/completions`, { model: at.model, stream: false, messages, tools: fns, tool_choice: 'auto',
          temperature: 0.2, max_tokens: 4000, chat_template_kwargs: { enable_thinking: false }, ...opts() }];
      }
      const r = await fetchFn(endpoint, { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) {
        const detail = typeof r.text === 'function' ? (await r.text()).slice(0, 200) : '';
        throw new Error(`modelo local ${at.model}: HTTP ${r.status}${/tool|jinja/i.test(detail) ? ' (arranca llama-server con --jinja para usar herramientas)' : ''} ${detail}`);
      }
      const d = await r.json();
      const msg = d.message || d.choices?.[0]?.message || {};
      const calls = (msg.tool_calls || []).map((c, i) => ({ id: c.id || `local-${Date.now()}-${i}`, name: c.function?.name || c.name,
        arguments: safeJson(c.function?.arguments ?? c.arguments) }));
      return { content: String(msg.content || ''), reasoning: String(msg.reasoning_content || msg.thinking || ''), tool_calls: calls.filter((c) => c.name) };
    } finally { clearTimeout(t); }
  }

  async function complete(prompt, token) {
    const at = await ready();
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    token?.onCancellationRequested?.(() => ctrl.abort());
    try {
      const messages = [{ role: 'user', content: prompt }];
      const [endpoint, body] = at.api === 'eolas'
        ? [`${at.url}/api/chat`, { model: at.model, stream: false, messages, options: { num_ctx: 32768, temperature: 0.2 } }]
        // Sin «modo pensar» (qwen3, gemma…): la revisión va directa y no se dispara el tiempo.
        : [`${at.url}/v1/chat/completions`, { model: at.model, stream: false, messages, temperature: 0.2, max_tokens: 6000,
          chat_template_kwargs: { enable_thinking: false }, ...opts({ review: true }), ...(opts({ review: true }).max_tokens ? { max_tokens: Math.max(6000, opts({ review: true }).max_tokens) } : {}) }];
      const r = await fetchFn(endpoint, { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(`modelo local ${at.model}: HTTP ${r.status}`);
      const d = await r.json();
      return String(d.message?.content ?? d.choices?.[0]?.message?.content ?? d.response ?? '');
    } finally { clearTimeout(t); }
  }

  return { locate, complete, chatTools, name: () => (found ? `${found.model} (llama.cpp local${started ? ', arrancado por Eolfi' : ''})` : 'modelo local llama.cpp'),
    reset: () => { found = null; }, stop: () => { if (started) starter?.stop(); started = false; found = null; } };
}

module.exports = { makeLocalModel, pickModel, isLoopback, DEFAULT_ENDPOINTS, httpFetch };
