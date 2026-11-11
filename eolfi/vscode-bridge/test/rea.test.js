'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { reaConfig, McpClient, isReadOnly, needsConfirm, stringsIn } = require('../rea');

const FAKE = { command: process.execPath, args: [path.join(__dirname, '..', 'fixtures', 'fake-mcp.js')], env: {} };

test('reaConfig lee «rea» de la configuración MCP o usa el comando dado', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-rea-'));
  const f = path.join(dir, 'mcp-config.json');
  fs.writeFileSync(f, JSON.stringify({ mcpServers: { rea: { type: 'stdio', command: 'cmd.exe', args: ['/c', 'npx', 'rea-agents', 'mcp'], env: { A: '1' } } } }));
  assert.deepStrictEqual(reaConfig({ configFile: f }), { command: 'cmd.exe', args: ['/c', 'npx', 'rea-agents', 'mcp'], env: { A: '1' } });
  assert.strictEqual(reaConfig({ configFile: path.join(dir, 'no.json') }), null);
  assert.deepStrictEqual(reaConfig({ command: 'rea', args: ['mcp'] }), { command: 'rea', args: ['mcp'], env: {} });
});

test('cliente MCP: inicializa, pagina tools/list y llama herramientas', async () => {
  const c = new McpClient(FAKE);
  try {
    const tools = await c.listTools();
    assert.deepStrictEqual(tools.map((t) => t.name), ['inspect_artifact', 'start_frida_session']);
    assert.ok(isReadOnly(tools[0]) && !isReadOnly(tools[1]));
    const r = await c.callTool('inspect_artifact', { path: 'x.exe' });
    assert.strictEqual(r.text, 'ok inspect_artifact {"path":"x.exe"}');
  } finally { c.dispose(); }
});

test('cliente MCP: gestiona fallos stdin y limita tramas stdout por bytes UTF-8', async () => {
  const { EventEmitter } = require('node:events');
  const { PassThrough } = require('node:stream');
  const c = new McpClient(FAKE, { timeoutMs: 100 });
  const proc = new EventEmitter();
  proc.stdout = new PassThrough();
  proc.stderr = new PassThrough();
  proc.stdin = { write: (_data, cb) => cb(new Error('pipe cerrado')) };
  proc.kill = () => proc.emit('exit', 1);
  c.proc = proc;
  await assert.rejects(c.request('tools/list'), /pipe cerrado/);
  // El límite se ejercita en el listener real instalado al arrancar; un frame gigante
  // debe cerrar el proceso y limpiar solicitudes pendientes.
  for (const frame of ['x'.repeat(1024 * 1024 + 1), 'é'.repeat(1024 * 512 + 1)]) {
    const oversized = new McpClient(FAKE);
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.stdin = { write: () => {} };
    child.kill = () => child.emit('exit', 1);
    oversized.spawnFn = () => child;
    const pending = oversized.listTools();
    await new Promise((resolve) => setImmediate(resolve));
    child.stdout.write(frame);
    await assert.rejects(pending, /REA se cerró/);
    oversized.dispose();
  }
});

test('stringsIn recoge todas las cadenas de unos argumentos', () => {
  assert.deepStrictEqual(stringsIn({ a: 'x', b: [1, 'y', { c: 'z' }] }), ['x', 'y', 'z']);
});

test('needsConfirm: confirma lo que ejecuta o toca procesos; inspeccionar y anotar no', () => {
  const t = (name, a) => ({ name, annotations: a });
  assert.strictEqual(needsConfirm(t('list_unknowns', { readOnlyHint: true, destructiveHint: false })), false);
  assert.strictEqual(needsConfirm(t('inspect_artifact', { readOnlyHint: false, destructiveHint: false, openWorldHint: true })), false);
  assert.strictEqual(needsConfirm(t('set_comment', { destructiveHint: true, openWorldHint: false })), false);
  assert.strictEqual(needsConfirm(t('instrument_with_frida', { destructiveHint: true, openWorldHint: true })), true);
  assert.strictEqual(needsConfirm(t('start_frida_session', { destructiveHint: false, openWorldHint: true })), true);
  assert.strictEqual(needsConfirm(t('install_adb_package', {})), true);
  assert.strictEqual(needsConfirm(undefined), true);
});

test('REA: entorno sin secretos y lo que ejecuta algo se confirma aunque se declare de solo lectura', () => {
  const { safeEnv, needsConfirm } = require('../rea');
  const env = safeEnv({ PATH: 'x', JAVA_HOME: 'j', GHIDRA_INSTALL_DIR: 'g', GITHUB_TOKEN: 't', OPENAI_API_KEY: 'k', DB_PASSWORD: 'p' });
  assert.deepStrictEqual(Object.keys(env).sort(), ['GHIDRA_INSTALL_DIR', 'JAVA_HOME', 'PATH']);
  assert.strictEqual(needsConfirm({ name: 'instrument_with_frida', annotations: { readOnlyHint: true } }), true);
  assert.strictEqual(needsConfirm({ name: 'inspect_artifact', annotations: { readOnlyHint: true } }), false);
});
