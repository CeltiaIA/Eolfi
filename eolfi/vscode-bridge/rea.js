// Cliente MCP stdio para REA y servidores locales elegidos por el usuario. Los servidores externos arrancan solo
// después de que Eolfi los confirme y se cierran con VS Code.
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PROTOCOL = '2025-06-18';
const MAX_RESULT = 100000;

// { command, args, env } del servidor REA, o null si no hay ninguno configurado.
function reaConfig({ command, args, configFile } = {}) {
  if (command) return { command, args: Array.isArray(args) ? args : [], env: {} };
  const files = configFile ? [configFile] : [path.join(os.homedir(), '.copilot', 'mcp-config.json')];
  for (const f of files) {
    try {
      const d = JSON.parse(fs.readFileSync(f, 'utf8'));
      const s = (d.mcpServers || d.servers || {}).rea;
      if (s && s.command && (!s.type || s.type === 'stdio')) {
        return { command: s.command, args: Array.isArray(s.args) ? s.args : [], env: s.env && typeof s.env === 'object' ? s.env : {} };
      }
    } catch { /* sin configuración */ }
  }
  return null;
}

// Entorno heredado sin credenciales. Los valores sensibles solo se reañaden si el servidor los declaró en env/env_vars.
const SECRET_ENV = /(API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|PRIVATE[_-]?KEY|AUTH)/i;
function safeEnv(env) {
  return Object.fromEntries(Object.entries(env).filter(([k]) => !SECRET_ENV.test(k)));
}

class McpClient {
  constructor(cfg, { log = () => {}, timeoutMs = 600000, spawnFn = spawn } = {}) {
    this.cfg = cfg;
    this.log = log;
    this.timeoutMs = timeoutMs;
    this.spawnFn = spawnFn;
    this.proc = null;
    this.ready = null;
    this.pending = new Map();
    this.nextId = 1;
    this.tools = null;
    const inherited = (cfg.envVars || []).map((k) => process.env[k]);
    const configured = Object.values(cfg.env || {});
    this.secretValues = [...new Set([...inherited, ...configured].filter((v) => typeof v === 'string' && v.length >= 8))];
  }

  redact(text) {
    let value = String(text);
    for (const secret of this.secretValues) value = value.split(secret).join('[credencial redactada]');
    return value;
  }

  start() {
    if (this.ready) return this.ready;
    this.ready = (async () => {
      const { command, args, env } = this.cfg;
      const inherited = safeEnv(process.env);
      for (const key of this.cfg.envVars || []) {
        if (Object.hasOwn(process.env, key)) inherited[key] = process.env[key];
      }
      this.proc = this.spawnFn(command, args, { env: { ...inherited, ...env }, cwd: this.cfg.cwd || undefined,
        stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
      let buf = '';
      this.proc.stdout.setEncoding('utf8');
      this.proc.stdout.on('data', (chunk) => {
        buf += chunk;
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (!line) continue;
          let msg;
          try { msg = JSON.parse(line); } catch { continue; }
          const p = msg.id !== undefined && this.pending.get(msg.id);
          if (p) {
            this.pending.delete(msg.id);
            clearTimeout(p.timer);
            if (msg.error) p.reject(Object.assign(new Error(msg.error.message || 'error de REA'), { code: msg.error.code }));
            else p.resolve(msg.result);
          }
        }
      });
      this.proc.stderr.on('data', (d) => this.log(`MCP: ${this.redact(String(d).trim()).slice(0, 300)}`));
      const died = (why) => {
        for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error(`REA se cerró (${why})`)); }
        this.pending.clear();
        this.proc = null;
        this.ready = null;
        this.tools = null;
      };
      this.proc.on('exit', (code) => died(`código ${code}`));
      this.proc.on('error', (e) => died(e.message));
      await this.request('initialize', { protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: 'eolfi', version: '1' } }, 180000);
      this.notify('notifications/initialized');
      this.log('REA conectado');
    })();
    this.ready.catch(() => {
      try { this.proc?.kill(); } catch { /* cleanup best-effort */ }
      this.proc = null;
      this.ready = null;
      this.tools = null;
    });
    return this.ready;
  }

  notify(method, params) {
    this.proc?.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method, ...(params ? { params } : {}) })}\n`);
  }

  request(method, params, timeoutMs = this.timeoutMs) {
    if (!this.proc) return Promise.reject(new Error('REA no está arrancado'));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`REA no respondió a ${method} en ${Math.round(timeoutMs / 1000)} s`)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.proc.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params: params || {} })}\n`);
    });
  }

  async listTools() {
    await this.start();
    if (this.tools) return this.tools;
    const all = [];
    let cursor;
    do {
      const r = await this.request('tools/list', cursor ? { cursor } : {});
      all.push(...(r.tools || []));
      cursor = r.nextCursor;
    } while (cursor);
    this.tools = all;
    return all;
  }

  async callTool(name, args) {
    await this.start();
    const r = await this.request('tools/call', { name, arguments: args || {} });
    const text = this.redact((r.content || []).map((c) => (c.type === 'text' ? c.text : `[${c.type}]`)).join('\n'));
    return { isError: r.isError === true, text: text.slice(0, MAX_RESULT) + (text.length > MAX_RESULT ? '\n[recortado]' : '') };
  }

  dispose() {
    try { this.proc?.kill(); } catch { /* ya cerrado */ }
    this.proc = null;
    this.ready = null;
  }
}

// Solo lectura según las anotaciones MCP de la herramienta (sin anotación = puede cambiar algo → se confirma).
function isReadOnly(tool) {
  return tool?.annotations?.readOnlyHint === true && tool?.annotations?.destructiveHint !== true;
}

// Pide confirmación lo que ejecuta algo o toca procesos, dispositivos o el sistema: depuradores, Frida, comandos de
// rizin/Cutter, capturas en vivo, adb, instalar… (anotación destructiva + mundo abierto, o por el nombre).
// Inspeccionar, descompilar, listar o anotar el análisis propio de REA no pregunta.
const RUNTIME = /^(start_|stop_|resume_|install_|uninstall_|push_|pull_adb|collect_adb|capture_|observe_(native|javascript|web_execution|web_session)|instrument_|load_frida|unload_frida|close_(frida|gdb|rizin)|gdb_|rizin_debug|execute_rizin|cutter_command|trace_native_values|trace_native_ui_action)/;
function needsConfirm(tool) {
  if (!tool) return true;
  if (RUNTIME.test(tool.name)) return true;   // por su nombre ejecuta algo: se confirma aunque diga «solo lectura»
  if (isReadOnly(tool)) return false;
  const a = tool.annotations || {};
  return (a.destructiveHint === true && a.openWorldHint === true) || RUNTIME.test(tool.name);
}

// Todas las cadenas de unos argumentos (para no dejar pasar rutas de secretos).
function stringsIn(v, out = []) {
  if (typeof v === 'string') out.push(v);
  else if (Array.isArray(v)) v.forEach((x) => stringsIn(x, out));
  else if (v && typeof v === 'object') Object.values(v).forEach((x) => stringsIn(x, out));
  return out;
}

// Firma compacta de una herramienta: «path*, detail=complete|summary, max?» (* = obligatorio).
function signature(tool) {
  const s = tool?.inputSchema || {};
  const req = new Set(Array.isArray(s.required) ? s.required : []);
  const props = s.properties || {};
  const parts = Object.entries(props).map(([k, v]) => {
    const en = Array.isArray(v?.enum) ? `=${v.enum.slice(0, 6).join('|')}` : '';
    return `${k}${req.has(k) ? '*' : '?'}${en}`;
  });
  return parts.length ? parts.join(', ') : '(sin argumentos)';
}

// Comprueba los argumentos antes de llamar: faltan obligatorios / sobran claves no admitidas.
function checkArgs(tool, args) {
  const s = tool?.inputSchema || {};
  const props = s.properties || {};
  const given = args && typeof args === 'object' ? Object.keys(args) : [];
  const missing = (Array.isArray(s.required) ? s.required : []).filter((k) => !given.includes(k));
  const extra = s.additionalProperties === false ? given.filter((k) => !(k in props)) : [];
  if (!missing.length && !extra.length) return null;
  return `Argumentos incorrectos para ${tool.name}: ${missing.length ? `faltan ${missing.join(', ')}` : ''}${missing.length && extra.length ? '; ' : ''}`
    + `${extra.length ? `no admite ${extra.join(', ')}` : ''}. Firma: ${signature(tool)}. Esquema: ${JSON.stringify(s).slice(0, 1500)}. Corrige y vuelve a llamar.`;
}

module.exports = { reaConfig, McpClient, isReadOnly, needsConfirm, stringsIn, signature, checkArgs, safeEnv };
