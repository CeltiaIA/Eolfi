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

// Gemma 4 a través de Eolas: la llamada a herramienta y el razonamiento llegan como texto en content
// («<|channel>thought…<channel|>» y «<|tool_call>call:nombre{clave:<|"|>valor<|"|>}<tool_call|>»).
const GEMMA_THOUGHT = /<\|channel>(?:thought)?([\s\S]*?)<channel\|>/g;
const GEMMA_CALL = /<\|tool_call>call:([\w.-]+)(\{[\s\S]*?\})<tool_call\|>/g;

function gemmaArgs(s) {
  const strs = [];
  let t = s.replace(/<\|"\|>([\s\S]*?)<\|"\|>/g, (_, v) => { strs.push(v); return `"\u0000${strs.length - 1}\u0000"`; });
  t = t.replace(/([{,]\s*)([A-Za-z_][\w-]*)\s*:/g, '$1"$2":');
  t = t.replace(/"\u0000(\d+)\u0000"/g, (_, i) => JSON.stringify(strs[+i]));
  return safeJson(t);
}

// A veces solo llega el cierre «<channel|>» (el marcador de apertura se pierde): lo anterior es razonamiento.
function stripThought(text, reasoning = []) {
  const s = String(text || '').replace(GEMMA_THOUGHT, (_, r) => { reasoning.push(r.trim()); return ''; });
  const k = s.lastIndexOf('<channel|>');
  if (k < 0) return s;
  reasoning.push(s.slice(0, k).trim());
  return s.slice(k + '<channel|>'.length);
}

function splitGemma(text) {
  const reasoning = [];
  const calls = [];
  let content = stripThought(String(text || '').replace(GEMMA_THOUGHT, (_, r) => { reasoning.push(r.trim()); return ''; }), reasoning);
  content = content.replace(GEMMA_CALL, (_, name, args) => { calls.push({ name, arguments: gemmaArgs(args) }); return ''; });
  return { content: content.trim(), reasoning: reasoning.join('\n'), calls };
}

// Eolas gestiona su llama.cpp (capas en GPU, hilos y límite de VRAM en launch-eolas.ps1): Eolfi no le impone
// num_gpu ni num_thread de ~/.eolfi/llamacpp.json, que son de su llama-server propio. El contexto sí se pide:
// sin num_ctx, Eolas carga con 2048 tokens y las peticiones del agente no caben.
function eolasOptions(runtime = {}) {
  return { num_ctx: Number(runtime.num_ctx) || 32768, temperature: runtime.temperature ?? 0.2 };
}

// Razonamiento de Gemma 4 en Eolas: «think» en la petición (equivale a enable_thinking de llama-server). Sin él,
// Eolas razona por defecto: una revisión breve pasa de ~130 a ~590 tokens y el pensamiento llega dentro de content.
function eolasThink(runtime = {}) {
  const t = runtime.chat_template_kwargs?.enable_thinking;
  return typeof t === 'boolean' ? { think: t } : {};
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

  // Diagnóstico del último sondeo: qué respondió cada endpoint (para decir el primer punto de fallo).
  let lastProbe = [];

  async function probe(list) {
    lastProbe = [];
    for (const url of list.filter(isLoopback)) {
      // Eolas expone su API en /api/* (con el backend llama.cpp); llama-server, la de OpenAI en /v1/*.
      const tags = await getJson(fetchFn, `${url}/api/tags`);
      if (tags && Array.isArray(tags.models)) {
        const names = tags.models.map((x) => x.name || x.model).filter(Boolean);
        const m = pickModel(names, model);
        if (m) { found = { url, api: 'eolas', model: m }; return found; }
        lastProbe.push({ url, api: 'eolas', models: names });
        continue;
      }
      const v1 = await getJson(fetchFn, `${url}/v1/models`);
      if (v1 && Array.isArray(v1.data)) {
        const names = v1.data.map((x) => x.id).filter(Boolean);
        // Con un modelo pedido no se cambia en silencio a otro: si no está, este endpoint no vale.
        const m = pickModel(names, model) || (model ? null : names[0] || 'local');
        if (m) { found = { url, api: 'openai', model: m }; return found; }
        lastProbe.push({ url, api: 'openai', models: names });
        continue;
      }
      lastProbe.push({ url, api: null, models: [] });
    }
    return null;
  }

  function notFound() {
    const seen = lastProbe.filter((p) => p.api);
    if (model && seen.length) {
      return `el modelo local ${model} no está disponible: ${seen.map((p) => `${p.url} anuncia ${p.models.length ? p.models.join(', ') : 'ningún modelo'}`).join('; ')}`;
    }
    const where = endpoints.filter(isLoopback).join(', ') || 'ningún endpoint loopback';
    return `no hay modelo local llama.cpp: sin respuesta en ${where} (arranca Eolas con launch-eolas.ps1)`;
  }

  async function ready() {
    let at = await locate();
    if (!at) throw new Error(notFound());
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
      const runtime = opts() || {};
      const { num_ctx, num_gpu, num_thread, ...requestOptions } = runtime;
      if (at.api === 'eolas') {
        // API de Eolas (como la de Ollama): argumentos como objeto y resultados de herramienta sin id.
        const msgs = messages.map((m) => (m.tool_calls ? { role: 'assistant', content: m.content || '', tool_calls: m.tool_calls.map((c) => ({ function: { name: c.function.name, arguments: safeJson(c.function.arguments) } })) }
          : m.role === 'tool' ? { role: 'tool', content: m.content, tool_name: m.name } : m));
        [endpoint, body] = [`${at.url}/api/chat`, { model: at.model, stream: false, messages: msgs, tools: fns, ...eolasThink(runtime), options: eolasOptions(runtime) }];
      } else {
        [endpoint, body] = [`${at.url}/v1/chat/completions`, { model: at.model, stream: false, messages, tools: fns, tool_choice: 'auto',
          temperature: 0.2, max_tokens: 4000, chat_template_kwargs: { enable_thinking: false }, ...requestOptions }];
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
      const g = splitGemma(msg.content);
      if (!calls.length) g.calls.forEach((c, i) => calls.push({ id: `local-${Date.now()}-${i}`, ...c }));
      return { content: g.content, reasoning: String(msg.reasoning_content || msg.thinking || g.reasoning || ''), tool_calls: calls.filter((c) => c.name) };
    } finally { clearTimeout(t); }
  }

  async function complete(prompt, token) {
    const at = await ready();
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    token?.onCancellationRequested?.(() => ctrl.abort());
    try {
      const messages = [{ role: 'user', content: prompt }];
      // Revisión: el mismo perfil (review_reasoning) con Eolas y con llama-server.
      const runtime = opts({ review: true }) || {};
      const [endpoint, body] = at.api === 'eolas'
        ? [`${at.url}/api/chat`, { model: at.model, stream: false, messages, ...eolasThink(runtime), options: eolasOptions(runtime) }]
        // Sin «modo pensar» (qwen3, gemma…): la revisión va directa y no se dispara el tiempo.
        : (() => { const o = opts({ review: true }) || {}; const { num_ctx, num_gpu, num_thread, ...requestOptions } = o;
          return [`${at.url}/v1/chat/completions`, { model: at.model, stream: false, messages, temperature: 0.2, max_tokens: 6000,
            chat_template_kwargs: { enable_thinking: false }, ...requestOptions, ...(o.max_tokens ? { max_tokens: Math.max(6000, o.max_tokens) } : {}) }]; })();
      const r = await fetchFn(endpoint, { method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) {
        let detail = '';
        try { detail = typeof r.text === 'function' ? String(await r.text()).replace(/\s+/g, ' ').slice(0, 300) : ''; } catch { /* sin cuerpo */ }
        const e = new Error(`modelo local ${at.model}: HTTP ${r.status}${detail ? ` · ${detail}` : ''}`);
        e.status = r.status;
        throw e;
      }
      const d = await r.json();
      return stripThought(String(d.message?.content ?? d.choices?.[0]?.message?.content ?? d.response ?? '')).trim();
    } finally { clearTimeout(t); }
  }

  return { locate, complete, chatTools, diagnose: () => ({ endpoints: [...endpoints], model, probe: lastProbe.map((p) => ({ ...p })), error: found ? null : notFound() }),
    name: () => (found ? `${found.model} (llama.cpp local${started ? ', arrancado por Eolfi' : ''})` : 'modelo local llama.cpp'),
    reset: () => { found = null; }, stop: () => { if (started) starter?.stop(); started = false; found = null; } };
}

// Integración acordada: Eolas (llama.cpp gestionado por Eolas) con un único modelo Gemma 4 12B.
const EOLAS_URL = 'http://127.0.0.1:11435';
const EOLAS_MODEL = 'gemma-4-12b-it:latest';

module.exports = { makeLocalModel, pickModel, isLoopback, DEFAULT_ENDPOINTS, EOLAS_URL, EOLAS_MODEL, httpFetch };
