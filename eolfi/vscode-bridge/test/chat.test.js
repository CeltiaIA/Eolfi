'use strict';
const test = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');
const { makeChatHandler, resolveTarget, HELP } = require('../chat');

function fakeStream() {
  const s = { md: '', progress: [], buttons: [] };
  s.markdown = (t) => { s.md += t; };
  s.progress_ = s.progress;
  return Object.assign(s, { progress: (m) => s.progress_.push(m), button: (b) => s.buttons.push(b) });
}

// VS Code falso con la Language Model API: cada modelo responde por rondas guionizadas
// (texto o llamadas a herramientas); `fail` simula un modelo reservado que rechaza la petición.
function fakeVscode({ answer = 'respuesta', rounds = null, models = null } = {}) {
  class TextPart { constructor(v) { this.value = v; } }
  class ToolCallPart { constructor(callId, name, input) { Object.assign(this, { callId, name, input }); } }
  class ToolResultPart { constructor(callId, content) { Object.assign(this, { callId, content }); } }
  const sent = [];
  const mk = (id, script, fail) => {
    let i = 0;
    return { id, name: id.toUpperCase(), family: id, maxInputTokens: 1000, sendRequest: async (msgs, opts) => {
      sent.push({ model: id, msgs: [...msgs], tools: (opts.tools || []).map((t) => t.name) });
      if (fail) return { stream: (async function* () { throw new Error(`Model ${id} is only available to VS Code core`); })() };
      const r = script[Math.min(i++, script.length - 1)];
      return { stream: (async function* () {
        if (r.text) yield new TextPart(r.text);
        for (const c of r.calls || []) yield new ToolCallPart(c.id, c.name, c.input || {});
      })() };
    } };
  };
  const list = models ? models.map(([id, fail]) => mk(id, rounds || [{ text: answer }], fail)) : [mk('gpt', rounds || [{ text: answer }])];
  return {
    sent,
    workspace: { workspaceFolders: [{ uri: { fsPath: os.tmpdir() } }] },
    window: { activeTextEditor: null },
    LanguageModelTextPart: TextPart, LanguageModelToolCallPart: ToolCallPart, LanguageModelToolResultPart: ToolResultPart,
    LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }), Assistant: (c) => ({ role: 'assistant', content: c }) },
    lm: { selectChatModels: async () => list },
  };
}

function fakeClient() {
  const calls = [];
  return {
    calls,
    analyze: async (kind, body, onLog) => { calls.push([kind, body]); onLog('paso 1'); return { subject: 'abc', summary: { format: 'pe' } }; },
    incognitas: async () => ({ incognitas: [{ severity: 'alta', question: '¿Qué hace X?', status: 'open' }, { severity: 'baja', question: 'resuelta', status: 'resolved' }] }),
    report: async () => '# Informe\nformato pe',
  };
}

const summarize = (rep, incs) => `Objetivo: ${rep.subject}\nIncógnitas abiertas: ${incs.filter((i) => i.status !== 'resolved').length}`;

test('resolveTarget: URL, carpeta, archivo, inexistente y archivo activo', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-chat-'));
  const f = path.join(dir, 'a.bin'); fs.writeFileSync(f, 'x');
  assert.deepStrictEqual(resolveTarget('https://ejemplo.es', null, dir), { kind: 'web', target: 'https://ejemplo.es' });
  assert.strictEqual(resolveTarget(dir).kind, 'folder');
  assert.strictEqual(resolveTarget('a.bin', null, dir).target, f);
  assert.strictEqual(resolveTarget('no-existe.bin', null, dir).kind, 'missing');
  assert.deepStrictEqual(resolveTarget('', f), { kind: 'file', target: f });
  assert.strictEqual(resolveTarget('', null), null);
});

test('sin sesión: pide iniciar sesión con un botón', async () => {
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => { throw new Error('sin sesión'); } });
  const s = fakeStream();
  await h({ prompt: 'hola' }, {}, s, {});
  assert.match(s.md, /inicia sesión/);
  assert.strictEqual(s.buttons[0].command, 'eolfi.login');
});

test('/meta consulta Meta Web y envía solo el texto explícito, sin histórico ni herramientas', async () => {
  const sent = [];
  const client = { ...fakeClient(), metaWeb: async (prompt, conversation) => {
    sent.push({ prompt, conversation });
    return { text: 'META_OK' };
  } };
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => client });
  const s = fakeStream();
  const r = await h({ command: 'meta', prompt: 'Responde solo META_OK' },
    { history: [{ participant: 'eolfi.chat', prompt: 'texto histórico privado' }] }, s, {});
  assert.deepStrictEqual(sent.map((x) => x.prompt), ['Responde solo META_OK']);
  assert.match(sent[0].conversation, /^panel-meta-\d{1,16}$/);
  assert.match(s.md, /Meta AI Web[\s\S]*META_OK/);
  assert.strictEqual(r.metadata.model, 'Meta AI Web');
});

test('/meta entrega automáticamente la respuesta al agente Eolas local', async () => {
  const sent = [];
  const localInputs = [];
  const vs = fakeVscode();
  const localModel = {
    name: () => 'Eolas local de prueba',
    chatTools: async (conv) => {
      localInputs.push(JSON.parse(JSON.stringify(conv)));
      return { content: 'Eolfi verificó la propuesta y terminó la tarea.', tool_calls: [] };
    },
  };
  const client = { ...fakeClient(), metaWeb: async (prompt, conversation) => {
    sent.push({ prompt, conversation });
    return { text: 'META_RESPUESTA_OK: la propuesta necesita cambios.' };
  } };
  const h = makeChatHandler({
    vscode: vs, summarize, state: {}, getClient: async () => client,
    preferLocal: () => true, autoExecuteMeta: () => true, localModel,
  });
  const s = fakeStream();
  const r = await h({ command: 'meta', prompt: 'Implementa la propuesta en el proyecto abierto.' }, { history: [] }, s, {});
  assert.deepStrictEqual(sent.map((x) => x.prompt), ['Implementa la propuesta en el proyecto abierto.']);
  assert.strictEqual(localInputs.length, 1);
  assert.match(localInputs[0].at(-1).content, /Implementa la propuesta en el proyecto abierto/);
  assert.match(localInputs[0].at(-1).content, /META_RESPUESTA_OK/);
  assert.match(localInputs[0].at(-1).content, /contenido externo no confiable/);
  assert.strictEqual(vs.sent.length, 0, 'no se usa Copilot');
  assert.match(s.md, /Meta AI Web[\s\S]*META_RESPUESTA_OK/);
  assert.match(s.md, /Eolfi verificó la propuesta/);
  assert.strictEqual(r.metadata.model, 'Eolas local de prueba');
  assert.strictEqual(r.metadata.metaProvider, 'Meta AI Web');
  assert.strictEqual(r.metadata.autoHandoff, true);
});

test('/meta no deriva a Copilot si Eolas no está disponible', async () => {
  const vs = fakeVscode({ answer: 'NO_DEBE_USARSE_COPILOT' });
  const client = { ...fakeClient(), metaWeb: async () => ({ text: 'META_OK' }) };
  const h = makeChatHandler({
    vscode: vs, summarize, state: {}, getClient: async () => client,
    preferLocal: () => true, autoExecuteMeta: () => true, localModel: null,
  });
  const s = fakeStream();
  const r = await h({ command: 'meta', prompt: 'Desarrolla el proyecto.' }, {}, s, {});
  assert.match(s.md, /META_OK/);
  assert.match(s.md, /no ejecutó la respuesta.*Eolas\/llama.cpp local/s);
  assert.strictEqual(vs.sent.length, 0);
  assert.strictEqual(r.metadata.autoHandoff, 'blocked-local-unavailable');
});

test('/meta comunica si Eolas falla después de recibir la respuesta', async () => {
  const vs = fakeVscode({ answer: 'NO_DEBE_USARSE_COPILOT' });
  const client = { ...fakeClient(), metaWeb: async () => ({ text: 'META_OK' }) };
  const h = makeChatHandler({
    vscode: vs, summarize, state: {}, getClient: async () => client,
    preferLocal: () => true, autoExecuteMeta: () => true,
    localModel: { name: () => 'Eolas local', chatTools: async () => { throw new Error('Eolas HTTP 500'); } },
  });
  const s = fakeStream();
  const r = await h({ command: 'meta', prompt: 'Ejecuta la propuesta.' }, {}, s, {});
  assert.match(s.md, /META_OK/);
  assert.match(s.md, /Eolas HTTP 500/);
  assert.strictEqual(vs.sent.length, 0);
  assert.strictEqual(r.metadata.autoHandoff, 'local-failed');
});

test('/meta permite desactivar el traspaso automático sin afectar la consulta', async () => {
  const client = { ...fakeClient(), metaWeb: async () => ({ text: 'META_OK' }) };
  const localCalls = [];
  const h = makeChatHandler({
    vscode: fakeVscode(), summarize, state: {}, getClient: async () => client,
    preferLocal: () => true, autoExecuteMeta: () => false,
    localModel: { name: () => 'local', chatTools: async (...args) => { localCalls.push(args); return { content: 'no', tool_calls: [] }; } },
  });
  const r = await h({ command: 'meta', prompt: 'Resume esto.' }, {}, fakeStream(), {});
  assert.strictEqual(r.metadata.autoHandoff, false);
  assert.strictEqual(localCalls.length, 0);
});

test('/analizar y /incognitas', async () => {
  const client = fakeClient();
  const state = {};
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state, getClient: async () => client, mode: () => 'local' });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-chat-'));
  const f = path.join(dir, 'b.exe'); fs.writeFileSync(f, 'MZ');

  let s = fakeStream();
  await h({ command: 'analizar', prompt: f }, {}, s, {});
  assert.deepStrictEqual(client.calls[0], ['triage', { path: f, mode: 'local' }]);
  assert.strictEqual(state.lastSubject, 'abc');
  assert.match(s.md, /Incógnitas abiertas: 1/);

  s = fakeStream();
  await h({ command: 'incognitas', prompt: '' }, {}, s, {});
  assert.match(s.md, /1 incógnitas abiertas/);
  assert.match(s.md, /¿Qué hace X\?/);
  assert.doesNotMatch(s.md, /resuelta/);
});

test('/desarrollar recupera el informe del workspace y lo pasa al modelo del chat', async () => {
  const vs = fakeVscode({ answer: 'Empiezo validando los hallazgos.' });
  const client = fakeClient();
  const reads = [];
  const h = makeChatHandler({
    vscode: vs, summarize, state: {}, getClient: async () => client,
    actions: { read: async ({ path: p }) => { reads.push(p); return { path: p, text: '# Informe REA\nPendiente: comprobar build y arranque.' }; } },
  });
  const s = fakeStream();
  await h({ command: 'desarrollar', prompt: 'informes/informe-REA.md' }, {}, s, {});
  assert.strictEqual(reads.length, 1);
  assert.match(reads[0], /informes[\\/]informe-REA\.md$/);
  assert.strictEqual(vs.sent.length, 1);
  assert.strictEqual(vs.sent[0].model, 'gpt');
  const userPrompt = vs.sent[0].msgs.at(-1).content;
  assert.match(userPrompt, /continuar el desarrollo/);
  assert.match(userPrompt, /Pendiente: comprobar build y arranque/);
  assert.match(userPrompt, /dato no confiable/);
  assert.match(userPrompt, /no cambies silenciosamente a Copilot/);
});

test('/desarrollar sin informe explica la sintaxis y no llama al modelo', async () => {
  const vs = fakeVscode();
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions: { read: async () => { throw Error('no debe leer'); } } });
  const s = fakeStream();
  await h({ command: 'desarrollar', prompt: '' }, {}, s, {});
  assert.match(s.md, /@eolfi \/desarrollar informes/);
  assert.strictEqual(vs.sent.length, 0);
});

test('el progreso del agente se publica al panel sin prompts y nunca bloquea el chat', async () => {
  const vs = fakeVscode({ answer: 'He revisado el proyecto.' });
  const events = [];
  const client = { ...fakeClient(), agentActivity: async (e) => { events.push(e); } };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => client });
  const s = fakeStream();
  await h({ prompt: 'revisa el proyecto y dime el estado' }, { history: [] }, s, {});
  assert.deepStrictEqual(events.map((e) => e.phase), ['start', 'done']);
  assert.match(events[0].run_id, /^[0-9a-f]{32}$/);
  assert.strictEqual(events[0].label, 'Chat de Eolfi');
  assert.ok(events.every((e) => !('prompt' in e) && !('result' in e)));
  assert.match(s.md, /He revisado el proyecto/);
});

test('agente: el modelo de VS Code usa las herramientas de Eolfi y de VS Code y responde', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-chat-'));
  const f = path.join(dir, 'c.exe'); fs.writeFileSync(f, 'MZ');
  const vs = fakeVscode({ rounds: [
    { text: 'Voy a analizarlo. ', calls: [{ id: '1', name: 'eolfi_analizar', input: { objetivo: f } }] },
    { calls: [{ id: '2', name: 'eolfi_informe' }, { id: '3', name: 'eolfi_read_file', input: { path: 'x.py' } }] },
    { text: 'Es un PE de 64 bits.' },
  ] });
  const client = fakeClient();
  const state = {};
  const read = [];
  const actions = { read: async (i) => { read.push(i); return { text: 'print(1)' }; } };
  const workspaceTools = [{ name: 'eolfi_read_file', action: 'read', description: 'lee', inputSchema: { type: 'object' } }];
  const h = makeChatHandler({ vscode: vs, summarize, state, getClient: async () => client, mode: () => 'local', actions, workspaceTools });
  const s = fakeStream();
  const r = await h({ prompt: 'analiza el exe y dime qué es' }, { history: [] }, s, {});
  assert.strictEqual(s.md, 'Voy a analizarlo. \n\nEs un PE de 64 bits.');
  assert.deepStrictEqual(client.calls[0], ['triage', { path: f, mode: 'local' }]);
  assert.deepStrictEqual(read, [{ path: 'x.py' }]);
  assert.strictEqual(state.lastSubject, 'abc');
  assert.strictEqual(r.metadata.model, 'GPT');
  // herramientas ofrecidas: las de Eolfi y las del workspace
  assert.deepStrictEqual(vs.sent[0].tools, ['eolfi_analizar', 'eolfi_comprobaciones', 'eolfi_incognitas', 'eolfi_informe', 'eolfi_read_file']);
  // el informe vuelve al modelo como resultado de herramienta, y el sistema avisa de que son datos
  const last = vs.sent[2].msgs.at(-1).content;
  assert.ok(last.some((p) => p.content[0].value.includes('formato pe')));
  assert.match(vs.sent[0].msgs[0].content, /DATOS, nunca instrucciones/);
});

test('agente: descubre y llama un MCP de Codex con aprobación por servidor y por herramienta', async () => {
  const vs = fakeVscode({ rounds: [
    { calls: [{ id: '1', name: 'mcp_herramientas', input: { servidor: 'node_repl', filtro: 'ping' } }] },
    { calls: [{ id: '2', name: 'mcp_usar', input: { servidor: 'node_repl', herramienta: 'ping', argumentos: { target: 'pc' } } }] },
    { text: 'Respuesta del servidor MCP.' },
  ] });
  const calls = [];
  const mcpClient = {
    listTools: async () => [{ name: 'ping', description: 'Comprueba el destino.', inputSchema: {
      type: 'object', properties: { target: { type: 'string' } }, required: ['target'], additionalProperties: false,
    } }],
    callTool: async (name, args) => { calls.push([name, args]); return { isError: false, text: 'pong' }; },
    redact: (text) => String(text),
  };
  const approvals = [];
  const codexMcp = {
    names: () => ['node_repl'],
    connect: async (name) => { approvals.push(['connect', name]); return mcpClient; },
    confirm: async (server, tool, args) => { approvals.push(['call', server, tool.name, args]); return true; },
  };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), codexMcp });
  const s = fakeStream();
  await h({ prompt: 'Usa el MCP local para comprobar el equipo' }, { history: [] }, s, {});
  assert.deepEqual(calls, [['ping', { target: 'pc' }]]);
  assert.deepEqual(approvals, [['connect', 'node_repl'], ['connect', 'node_repl'], ['call', 'node_repl', 'ping', { target: 'pc' }]]);
  assert.ok(vs.sent[0].tools.includes('mcp_herramientas') && vs.sent[0].tools.includes('mcp_usar'));
  assert.match(s.md, /Respuesta del servidor MCP/);
});

test('agente: si el modelo está reservado prueba el siguiente', async () => {
  const vs = fakeVscode({ answer: 'hola', models: [['reservado', true], ['bueno', false]] });
  vs.lm.selectChatModels = (async (orig) => (await orig()).map((m, i) => Object.assign(m, { maxInputTokens: 2000 - i })))
    .bind(null, vs.lm.selectChatModels);
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient() });
  const s = fakeStream();
  const r = await h({ prompt: '¿qué tal?' }, {}, s, {});
  assert.strictEqual(s.md, 'hola');
  assert.strictEqual(r.metadata.model, 'BUENO');
});

test('una carpeta o URL sola sin comando se analiza; texto vacío muestra la ayuda', async () => {
  const client = fakeClient();
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => client });
  await h({ prompt: 'https://ejemplo.es' }, {}, fakeStream(), {});
  assert.deepStrictEqual(client.calls[0], ['web', { source: 'https://ejemplo.es' }]);
  const s = fakeStream();
  const h2 = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => client });
  await h2({ prompt: '' }, {}, s, {});
  assert.strictEqual(s.md, HELP);
});

test('401 (revocado) pide volver a iniciar sesión', async () => {
  const client = fakeClient();
  client.analyze = async () => { const e = new Error('no'); e.status = 401; throw e; };
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => client });
  const s = fakeStream();
  await h({ command: 'analizar', prompt: 'https://x.es' }, {}, s, {});
  assert.match(s.md, /revocada/);
  assert.strictEqual(s.buttons[0].command, 'eolfi.login');
});

test('/ayuda muestra la ayuda del agente con botones', async () => {
  const { AGENT_HELP } = require('../chat');
  const h = makeChatHandler({ vscode: fakeVscode(), summarize, state: {}, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ command: 'ayuda', prompt: '' }, {}, s, {});
  assert.ok(s.md.startsWith(AGENT_HELP));
  assert.match(s.md, /llama.cpp local/);
  assert.match(s.md, /Lo que no hago/);
  assert.match(s.md, /Lo que no puedo hacer/);
  assert.match(s.md, /\/analizar/);
  assert.ok(s.buttons.some((b) => b.command === 'eolfi.openPanel'));
});

test('secretos: ni /analizar, ni la herramienta, ni botón para .env', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-chat-'));
  const env = path.join(dir, '.env'); fs.writeFileSync(env, 'GITHUB_TOKEN=ZZ-valor-42');
  const client = fakeClient();
  const vs = fakeVscode({ rounds: [
    { calls: [{ id: '1', name: 'eolfi_analizar', input: { objetivo: env } }] },
    { text: 'No puedo analizar .env.' },
  ] });
  vs.window.activeTextEditor = { document: { uri: { scheme: 'file', fsPath: env } } };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => client });
  let s = fakeStream();
  await h({ command: 'analizar', prompt: env }, {}, s, {});
  assert.match(s.md, /guarda secretos/);
  s = fakeStream();
  await h({ prompt: 'analiza mi .env' }, {}, s, {});
  assert.strictEqual(client.calls.length, 0);
  const toolResult = vs.sent[1].msgs.at(-1).content[0].content[0].value;
  assert.match(toolResult, /Bloqueado/);
  assert.ok(!JSON.stringify(vs.sent).includes('ZZ-valor-42'));
  s = fakeStream();
  await h({ command: 'ayuda', prompt: '' }, {}, s, {});
  assert.ok(!s.buttons.some((b) => b.command === 'eolfi.analyzeFile'));
});

test('ayuda informa que llama.cpp mantiene las herramientas, Meta Web se consulta con /meta y Copilot sigue desconectado', async () => {
  const vs = fakeVscode({ answer: 'no debería usar Copilot' });
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), preferLocal: () => true,
    localModel: { name: () => 'Gemma local', chatTools: async () => ({ content: 'ok', tool_calls: [] }) } });
  const s = fakeStream();
  await h({ command: 'ayuda', prompt: '' }, {}, s, {});
  assert.ok(s.md.includes('agente con herramientas usa llama.cpp local'));
  assert.ok(s.md.includes('/meta <mensaje>'));
  assert.match(s.md, /Copilot está desconectado/);
  assert.strictEqual(vs.sent.length, 0);
});

test('agente con REA: busca, usa las de solo lectura y confirma las demás; nunca con secretos', async () => {
  const { McpClient } = require('../rea');
  const client = new McpClient({ command: process.execPath, args: [path.join(__dirname, '..', 'fixtures', 'fake-mcp.js')], env: {} });
  const asked = [];
  const rea = { client, confirm: async (tool) => { asked.push(tool.name); return false; } };
  const vs = fakeVscode({ rounds: [
    { calls: [{ id: '1', name: 'rea_herramientas', input: { filtro: 'artefacto' } }] },
    { calls: [{ id: '2', name: 'rea_usar', input: { herramienta: 'inspect_artifact', argumentos: { path: 'a.exe' } } },
      { id: '3', name: 'rea_usar', input: { herramienta: 'start_frida_session', argumentos: {} } },
      { id: '4', name: 'rea_usar', input: { herramienta: 'inspect_artifact', argumentos: { path: 'D:/p/.env' } } }] },
    { text: 'Hecho.' },
  ] });
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), rea });
  try {
    const s = fakeStream();
    await h({ prompt: 'inspecciona a.exe con REA' }, {}, s, {});
    assert.strictEqual(s.md, 'Hecho.');
    assert.ok(vs.sent[0].tools.includes('rea_usar'));
    const found = vs.sent[1].msgs.at(-1).content[0].content[0].value;
    assert.match(found, /- inspect_artifact\(path\?\): /);
    const res = vs.sent[2].msgs.at(-1).content.map((p) => p.content[0].value);
    assert.strictEqual(res[0], 'ok inspect_artifact {"path":"a.exe"}');
    assert.match(res[1], /no permitió/);
    assert.match(res[2], /Bloqueado/);
    assert.deepStrictEqual(asked, ['start_frida_session']);
  } finally { client.dispose(); }
});

test('límite de pasos: resume sin herramientas y ofrece «Continuar»', async () => {
  const loop = { calls: [{ id: 'x', name: 'eolfi_incognitas' }] };
  const vs = fakeVscode({ rounds: [loop, loop, loop, { text: 'Resumen: hecho A; falta B.' }] });
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), maxSteps: () => 2 });
  const s = fakeStream();
  await h({ prompt: 'audita todo' }, {}, s, {});
  assert.match(s.md, /Resumen: hecho A; falta B\./);
  assert.match(s.md, /2 pasos usados/);
  assert.ok(s.buttons.some((b) => b.command === 'eolfi.chatContinue'));
  const last = vs.sent.at(-1);
  assert.deepStrictEqual(last.tools, []);                       // el resumen va sin herramientas
  assert.match(last.msgs.at(-1).content, /límite de 2 pasos/);
  assert.ok(s.progress_.some((m) => /Paso 1 de 2/.test(m)));
});

test('auditorías largas: recorta resultados antiguos para no pasarse del contexto', async () => {
  const big = 'x'.repeat(50000);
  const rounds = [];
  for (let i = 0; i < 10; i++) rounds.push({ calls: [{ id: String(i), name: 'eolfi_read_file', input: { path: `f${i}.py` } }] });
  rounds.push({ text: 'fin' });
  const vs = fakeVscode({ rounds });
  const actions = { read: async () => ({ text: big }) };
  const workspaceTools = [{ name: 'eolfi_read_file', action: 'read', description: 'lee', inputSchema: { type: 'object' } }];
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions, workspaceTools });
  const s = fakeStream();
  await h({ prompt: 'lee todo' }, {}, s, {});
  assert.strictEqual(s.md, 'fin');
  const lastMsgs = vs.sent.at(-1).msgs;
  const results = lastMsgs.filter((m) => Array.isArray(m.content) && m.content[0] && m.content[0].callId !== undefined && m.content[0].content);
  const texts = results.map((m) => m.content[0].content[0].value);
  assert.ok(texts.some((t) => /\[recortado: resultado antiguo/.test(t)), 'recorta los antiguos');
  assert.ok(texts.slice(-6).every((t) => !/recortado/.test(t)), 'conserva enteros los 6 últimos');
});

test('como Copilot: referencias de lo leído, lista de archivos cambiados y «Deshacer estos cambios»', async () => {
  const vs = fakeVscode({ rounds: [
    { calls: [{ id: '1', name: 'eolfi_read_file', input: { path: 'a.py' } }, { id: '2', name: 'eolfi_write_file', input: { path: 'a.py', content: 'x' } }] },
    { text: 'Listo.' },
  ] });
  vs.Uri = { file: (p) => ({ fsPath: p }) };
  const writes = [];
  const actions = {
    journal_start: async () => ({ journal: 'j1' }),
    read: async () => ({ path: '/p/a.py', text: 'y' }),
    write: async (i) => { writes.push(i); return { written: '/p/a.py' }; },
  };
  const workspaceTools = [
    { name: 'eolfi_read_file', action: 'read', description: 'lee', inputSchema: { type: 'object' } },
    { name: 'eolfi_write_file', action: 'write', description: 'escribe', inputSchema: { type: 'object' } },
  ];
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions, workspaceTools });
  const s = fakeStream();
  const refs = [];
  const anchors = [];
  s.reference = (u) => refs.push(u.fsPath);
  s.anchor = (u) => anchors.push(u.fsPath);
  const r = await h({ prompt: 'arregla a.py' }, {}, s, {});
  assert.deepStrictEqual(refs, ['/p/a.py']);
  assert.strictEqual(writes[0].journal, 'j1');           // la escritura va al diario de la petición
  assert.match(s.md, /Archivos cambiados \(1\)/);
  assert.deepStrictEqual(anchors, ['/p/a.py']);
  assert.ok(s.buttons.some((b) => b.command === 'eolfi.undoJournal' && b.arguments[0] === 'j1'));
  assert.deepStrictEqual(r.metadata.written, ['/p/a.py']);
});

test('modos: /auto y /manual cambian el modo; el modelo y la ayuda lo saben', async () => {
  let mode = 'manual';
  const vs = fakeVscode({ answer: 'ok' });
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(),
    workMode: () => mode, setWorkMode: async (m) => { mode = m; return true; } });
  let s = fakeStream();
  await h({ command: 'auto', prompt: '' }, {}, s, {});
  assert.strictEqual(mode, 'automatico');
  assert.match(s.md, /Modo automático/);
  await h({ prompt: 'haz algo' }, {}, fakeStream(), {});
  assert.match(vs.sent.at(-1).msgs[0].content, /MODO AUTOMÁTICO/);
  s = fakeStream();
  await h({ command: 'ayuda', prompt: '' }, {}, s, {});
  assert.match(s.md, /🚀 \*\*Modo automático\*\* \(sin pedir permisos\)/);
  s = fakeStream();
  await h({ command: 'manual', prompt: '' }, {}, s, {});
  assert.strictEqual(mode, 'manual');
  await h({ prompt: 'haz algo' }, {}, fakeStream(), {});
  assert.match(vs.sent.at(-1).msgs[0].content, /MODO MANUAL/);
  const h2 = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), setWorkMode: async () => false });
  s = fakeStream();
  await h2({ command: 'auto', prompt: '' }, {}, s, {});
  assert.match(s.md, /Modo sin cambiar/);
});

test('memoria: guarda cada petición, el modelo recibe lo último y puede buscar; /historial', async () => {
  const { makeHistory } = require('../history');
  const memory = makeHistory({ file: path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-mem-')), 'h.jsonl') });
  memory.add({ folder: os.tmpdir(), prompt: 'audita D:/Eolfi', response: 'Informe de mejoras: añadir caché' });
  const vs = fakeVscode({ rounds: [
    { calls: [{ id: '1', name: 'eolfi_historial', input: { consulta: 'audita' } }] },
    { text: 'Ayer auditamos Eolfi.' },
  ] });
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), memory });
  const s = fakeStream();
  await h({ prompt: '¿qué hicimos ayer?' }, {}, s, {});
  assert.strictEqual(s.md, 'Ayer auditamos Eolfi.');
  const sys = vs.sent[0].msgs[0].content;
  assert.match(sys, /NUNCA digas que\s+no puedes ver conversaciones anteriores/);
  assert.match(sys, /«audita D:\/Eolfi»/);                                   // lo último de esta carpeta
  assert.ok(vs.sent[0].tools.includes('eolfi_historial'));
  assert.match(vs.sent[1].msgs.at(-1).content[0].content[0].value, /Informe de mejoras: añadir caché/);
  const saved = memory.search({ consulta: 'hicimos ayer' })[0];
  assert.strictEqual(saved.response, 'Ayer auditamos Eolfi.');
  assert.deepStrictEqual(saved.tools, [{ name: 'eolfi_historial', arg: 'audita' }]);
  const s2 = fakeStream();
  await h({ command: 'historial', prompt: 'audita' }, {}, s2, {});
  assert.match(s2.md, /Historial \(«audita»\)/);
  assert.match(s2.md, /audita D:\/Eolfi/);
});

test('regresión: con un stream congelado como el de VS Code, responde y guarda el historial', async () => {
  const { makeHistory } = require('../history');
  const memory = makeHistory({ file: path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-mem-')), 'h.jsonl') });
  const h = makeChatHandler({ vscode: fakeVscode({ answer: 'hola' }), summarize, state: {}, getClient: async () => fakeClient(), memory });
  let md = '';
  const buttons = [];
  // Como en VS Code: métodos en el propio objeto, de solo lectura y no configurables, y el objeto congelado.
  const frozen = {};
  for (const [k, fn] of Object.entries({ markdown: (t) => { md += t; }, progress: () => {}, button: (b) => buttons.push(b), reference: () => {}, anchor: () => {} })) {
    Object.defineProperty(frozen, k, { value: fn, writable: false, configurable: false, enumerable: true });
  }
  Object.freeze(frozen);
  await h({ prompt: 'saluda' }, {}, frozen, {});
  assert.strictEqual(md, 'hola');
  assert.strictEqual(memory.search({ consulta: 'saluda' })[0].response, 'hola');
  await h({ command: 'ayuda', prompt: '' }, {}, frozen, {});
  assert.ok(buttons.some((b) => b.command === 'eolfi.openPanel'));
});

test('detecta cuando pregunta u ofrece opciones en vez de hacer (caso real del usuario)', () => {
  const { asksInsteadOfDoing } = require('../chat');
  const real = 'He encontrado varias herramientas de REA...\nPróximos Pasos\nSeleccionar herramientas específicas para ejecutar en los archivos encontrados.\n'
    + '¿Te gustaría que ejecute alguna herramienta específica en uno de los archivos encontrados? Si es así, indícame cuál archivo y qué herramienta deseas usar.';
  assert.ok(asksInsteadOfDoing(real));
  assert.ok(asksInsteadOfDoing('He listado los archivos. ¿Quieres que los analice?'));
  assert.ok(asksInsteadOfDoing('Puedo seguir con el resto si lo deseas.'));
  assert.ok(!asksInsteadOfDoing('Listo: informe guardado en informes/auditoria-2026-11-06.md con 42 hallazgos.'));
  assert.ok(!asksInsteadOfDoing('El binario es un PE de 64 bits sin empaquetar; importa 7 DLL.'));
  assert.ok(!asksInsteadOfDoing(''));
});

test('si se para a preguntar, se le ordena seguir y termina la tarea; como mucho 3 veces', async () => {
  const vs = fakeVscode({ rounds: [
    { text: 'He encontrado herramientas útiles. ¿Te gustaría que ejecute alguna?' },
    { calls: [{ id: '1', name: 'eolfi_incognitas' }] },
    { text: 'Hecho: analizados todos los archivos.' },
  ] });
  const h = makeChatHandler({ vscode: vs, summarize, state: { lastSubject: 'abc' }, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ prompt: 'analiza todo' }, {}, s, {});
  assert.match(s.md, /Hecho: analizados todos los archivos\./);
  assert.match(vs.sent[1].msgs.at(-1).content, /No me preguntes ni me des opciones/);
  assert.ok(s.progress_.includes('Sigo con la tarea sin preguntarte…'));

  const stubborn = fakeVscode({ rounds: [{ text: '¿Quieres que lo haga?' }] });
  const h2 = makeChatHandler({ vscode: stubborn, summarize, state: {}, getClient: async () => fakeClient() });
  await h2({ prompt: 'hazlo' }, {}, fakeStream(), {});
  assert.strictEqual(stubborn.sent.length, 4);          // 1 + 3 empujones y para (sin bucle infinito)

  const fine = fakeVscode({ answer: 'Es un PE de 64 bits.' });
  const h3 = makeChatHandler({ vscode: fine, summarize, state: {}, getClient: async () => fakeClient() });
  await h3({ prompt: '¿qué es?' }, {}, fakeStream(), {});
  assert.strictEqual(fine.sent.length, 1);              // una respuesta normal no se empuja
  assert.match(fine.sent[0].msgs[0].content, /EJECUTA, NO PREGUNTES/);
});

test('detecta «Sigo con…» sin hacerlo (caso real) y no confunde un final de verdad', () => {
  const { promisesWithoutDoing } = require('../chat');
  const real = 'Auditoría REA lanzada sobre D:\Eolfi:\n- El APK F-Droid.apk ha sido analizado.\n- Informe actualizado con los hallazgos y limitaciones.\n'
    + '- Sigo con el análisis archivo por archivo del código fuente y JS.\n\nResultados y limitaciones anotados en informes/auditoria-2026-11-06.md.';
  assert.ok(promisesWithoutDoing(real));
  assert.ok(promisesWithoutDoing('He leído 12 archivos. Voy a continuar con eolfi/sites.'));
  assert.ok(promisesWithoutDoing('Quedan por revisar 40 archivos de eolfi/web.'));
  const done = 'Auditoría completa terminada y el informe exhaustivo guardado en informes/auditoria-2026-11-06.md.\n'
    + '- Se analizaron todos los archivos relevantes.\n- Se documentaron 25 evidencias y 7 incógnitas abiertas.\n\nTarea finalizada.';
  assert.ok(!promisesWithoutDoing(done));
  assert.ok(!promisesWithoutDoing('El binario es un PE de 64 bits sin empaquetar.'));
});

test('promesa sin hacer: se le ordena seguir; en automático hasta 10 veces, en manual 3', async () => {
  const vs = fakeVscode({ rounds: [
    { text: 'Informe actualizado. Sigo con el análisis archivo por archivo.' },
    { calls: [{ id: '1', name: 'eolfi_incognitas' }] },
    { text: 'Terminado: 120 archivos revisados.' },
  ] });
  const h = makeChatHandler({ vscode: vs, summarize, state: { lastSubject: 'abc' }, getClient: async () => fakeClient(), workMode: () => 'automatico' });
  const s = fakeStream();
  await h({ prompt: 'audita todo' }, {}, s, {});
  assert.match(s.md, /Terminado: 120 archivos revisados\./);
  assert.match(vs.sent[1].msgs.at(-1).content, /Has dicho que sigues/);
  assert.ok(s.progress_.includes('Sigue: hago lo que había dicho…'));

  const lazyAuto = fakeVscode({ rounds: [{ text: 'Sigo con el resto.' }] });
  await makeChatHandler({ vscode: lazyAuto, summarize, state: {}, getClient: async () => fakeClient(), workMode: () => 'automatico' })({ prompt: 'x' }, {}, fakeStream(), {});
  assert.strictEqual(lazyAuto.sent.length, 11);         // 1 + 10 empujones
  const lazyManual = fakeVscode({ rounds: [{ text: 'Sigo con el resto.' }] });
  await makeChatHandler({ vscode: lazyManual, summarize, state: {}, getClient: async () => fakeClient() })({ prompt: 'x' }, {}, fakeStream(), {});
  assert.strictEqual(lazyManual.sent.length, 4);        // 1 + 3
});

test('«audita archivo por archivo» y /auditar continuar: la auditoría la dirige Eolfi', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  for (const n of ['a.py', 'b.py', 'c.js']) fs.writeFileSync(path.join(root, n), `# ${n}\nx = 1\n`);
  const vs = fakeVscode({ answer: '### `x`\n- **Mejoras:**\n  - [alta] algo' });
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  const appended = [];
  const opened = [];
  const actions = { append: async ({ path: p, content }) => { appended.push([p, content]); return { appended: p }; }, open: async (o) => { opened.push(o.path); } };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions });
  const s = fakeStream();
  await h({ prompt: `audita ${root} archivo por archivo y genera el informe` }, {}, s, {});
  assert.match(s.md, /3 archivos/);
  assert.match(s.md, /Auditoría terminada/);
  assert.ok(appended.every(([p]) => /^informes\/auditoria-archivos-/.test(p)));
  assert.strictEqual(opened.length, 1);
  assert.ok(vs.sent.length >= 2);                          // lotes + resumen, sin herramientas
  assert.ok(vs.sent.every((x) => x.tools.length === 0));
  const s2 = fakeStream();
  await h({ command: 'auditar', prompt: 'continuar' }, {}, s2, {});
  assert.match(s2.md, /3 archivos/);                       // la anterior acabó: empieza otra limpia
  delete process.env.EOLFI_AUDIT_DIR;
});

test('auditoría interrumpida por un error: dice dónde se quedó y ofrece continuar', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  for (let i = 0; i < 12; i++) fs.writeFileSync(path.join(root, `m${i}.py`), `x = ${i}\n`);
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  let n = 0;
  vs.lm.selectChatModels = async () => [{ id: 'm', name: 'M', family: 'm', sendRequest: async () => {
    if (++n === 2) throw new Error('se cortó la conexión');
    return { stream: (async function* () { yield new vs.LanguageModelTextPart('### `x`\n- ok'); })() };
  } }];
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.match(s.md, /Auditoría interrumpida en el archivo 6 de 12:\*\* se cortó la conexión/);
  assert.ok(s.buttons.some((b) => b.command === 'eolfi.chatAuditContinue'));
  const s2 = fakeStream();
  await h({ command: 'auditar', prompt: 'continuar' }, {}, s2, {});
  assert.match(s2.md, /Sigo la auditoría por el archivo \*\*6 de 12\*\*/);
  assert.match(s2.md, /Auditoría terminada/);
  delete process.env.EOLFI_AUDIT_DIR;
});

const RATE_MSG = "Sorry, you've exceeded your rate limit for utility models. Please review our Terms of Service.";
function modelsWith(vs, spec) {   // spec: [[id, falla?]] — falla: 'rate' | null
  const used = [];
  vs.lm.selectChatModels = async () => spec.map(([id, fail]) => ({ id, name: id.toUpperCase(), family: id, maxInputTokens: 1000,
    sendRequest: async () => {
      used.push(id);
      if (typeof fail === 'function' ? fail() : fail === 'rate') throw new Error(RATE_MSG);
      return { stream: (async function* () { yield new vs.LanguageModelTextPart(`### \`x\`\n- revisado por ${id}`); })() };
    } }));
  return used;
}

test('límite de peticiones (caso real): la auditoría usa Auto primero y cambia de modelo si uno se limita', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  for (let i = 0; i < 8; i++) fs.writeFileSync(path.join(root, `m${i}.py`), `x = ${i}\n`);
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  let autoCalls = 0;
  const used = modelsWith(vs, [['copilot-utility', 'rate'], ['auto', () => ++autoCalls > 1], ['gpt-4o-mini', null]]);
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const state = {};
  const h = makeChatHandler({ vscode: vs, summarize, state, getClient: async () => fakeClient(), actions });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.match(s.md, /Auditoría terminada/);
  assert.strictEqual(used[0], 'auto');                       // Auto primero
  assert.ok(used.includes('gpt-4o-mini'));                  // al limitarse Auto, otro modelo
  assert.ok(!used.includes('copilot-utility') || used.indexOf('copilot-utility') > 0);
  assert.ok(s.progress_.some((m) => /AUTO ha llegado a su límite de peticiones: pruebo otro modelo/.test(m)));
  delete process.env.EOLFI_AUDIT_DIR;
});

test('límite de peticiones: si todos están limitados espera, reintenta y si sigue, pausa con aviso', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  process.env.EOLFI_RATE_WAIT_SCALE = '0.0001';
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  fs.writeFileSync(path.join(root, 'a.py'), 'x = 1\n');
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  let n = 0;
  modelsWith(vs, [['auto', () => ++n < 3], ['copilot-utility', 'rate']]);   // se recupera tras la 1.ª espera
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.ok(s.progress_.some((m) => /Todos los modelos están en su límite de peticiones: espero 60 s/.test(m)));
  assert.match(s.md, /Auditoría terminada/);

  const vs2 = fakeVscode();
  vs2.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  modelsWith(vs2, [['auto', 'rate'], ['copilot-utility', 'rate']]);
  const h2 = makeChatHandler({ vscode: vs2, summarize, state: {}, getClient: async () => fakeClient(), actions });
  const s2 = fakeStream();
  await h2({ command: 'auditar', prompt: root }, {}, s2, {});
  assert.match(s2.md, /Auditoría interrumpida.*todos los modelos siguen en su límite de peticiones/s);
  delete process.env.EOLFI_AUDIT_DIR;
  delete process.env.EOLFI_RATE_WAIT_SCALE;
});

test('agente: si su modelo llega al límite a mitad de la tarea, sigue con otro', async () => {
  const vs = fakeVscode();
  let round = 0;
  const used = [];
  const mk = (id, fn) => ({ id, name: id, family: id, maxInputTokens: id === 'grande' ? 2000 : 1000, sendRequest: async () => { used.push(id); return fn(); } });
  vs.lm.selectChatModels = async () => [
    mk('grande', () => { if (++round === 2) throw new Error(RATE_MSG); return { stream: (async function* () { yield new vs.LanguageModelToolCallPart('1', 'eolfi_incognitas', {}); })() }; }),
    mk('otro', () => ({ stream: (async function* () { yield new vs.LanguageModelTextPart('Terminado con otro modelo.'); })() })),
  ];
  const h = makeChatHandler({ vscode: vs, summarize, state: { lastSubject: 'abc' }, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ prompt: 'mira las incógnitas' }, {}, s, {});
  assert.strictEqual(s.md, 'Terminado con otro modelo.');
  assert.deepStrictEqual(used, ['grande', 'grande', 'otro']);
  assert.ok(s.progress_.some((m) => /grande ha llegado a su límite de peticiones: sigo con otro/.test(m)));
});

test('Copilot limitado: la auditoría sigue con el modelo local llama.cpp antes de esperar', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  fs.writeFileSync(path.join(root, 'a.py'), 'x = 1\n');
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  modelsWith(vs, [['auto', 'rate'], ['copilot-utility', 'rate']]);
  const local = [];
  const localModel = { complete: async (p) => { local.push(p.length); return '### `a.py`\n- revisado en local'; }, name: () => 'gemma-4-12b-it (llama.cpp local)' };
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions, localModel });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.match(s.md, /Auditoría terminada/);
  assert.ok(local.length >= 1);                             // revisión de lotes; el resumen ahora es determinista
  assert.ok(s.progress_.some((m) => /Copilot está en su límite de peticiones: sigo con gemma-4-12b-it \(llama\.cpp local\)/.test(m)));
  assert.ok(!s.progress_.some((m) => /espero 60 s/.test(m)));   // no hace falta esperar
  delete process.env.EOLFI_AUDIT_DIR;
});

const NET_MSG = 'Please check your firewall rules and network connection then try again. Error Code: net::ERR_CONNECTION_RESET.';

test('fallo de red pasajero (caso real ERR_CONNECTION_RESET): la auditoría reintenta y sigue', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  process.env.EOLFI_RATE_WAIT_SCALE = '0.0001';
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  for (let i = 0; i < 7; i++) fs.writeFileSync(path.join(root, `m${i}.py`), `x = ${i}\n`);
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  let n = 0;
  const used = modelsWith(vs, [['auto', () => { n++; if (n === 2 || n === 3) throw new Error(NET_MSG); return false; }]]);
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.match(s.md, /Auditoría terminada/);
  assert.doesNotMatch(s.md, /interrumpida/);
  assert.ok(s.progress_.some((m) => /Fallo de red con AUTO .*reintento en 2 s/.test(m)));
  assert.ok(used.length >= 4);
  delete process.env.EOLFI_AUDIT_DIR;
  delete process.env.EOLFI_RATE_WAIT_SCALE;
});

test('fallo de red persistente: pasa a otro modelo y luego al local antes de rendirse', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  process.env.EOLFI_RATE_WAIT_SCALE = '0.0001';
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  fs.writeFileSync(path.join(root, 'a.py'), 'x = 1\n');
  const vs = fakeVscode();
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  modelsWith(vs, [['auto', () => { throw new Error(NET_MSG); }], ['copilot-utility', () => { throw new Error(NET_MSG); }]]);
  const localModel = { complete: async () => '### `a.py`\n- revisado en local', name: () => 'qwen (llama.cpp local)' };
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions, localModel });
  const s = fakeStream();
  await h({ command: 'auditar', prompt: root }, {}, s, {});
  assert.match(s.md, /Auditoría terminada/);
  assert.ok(s.progress_.some((m) => /AUTO sigue sin responder: pruebo otro modelo/.test(m)));
  assert.ok(s.progress_.some((m) => /sigo con qwen \(llama\.cpp local\)/.test(m)));
  delete process.env.EOLFI_AUDIT_DIR;
  delete process.env.EOLFI_RATE_WAIT_SCALE;
});

test('agente: fallo de red antes de escribir nada, reintenta el mismo modelo', async () => {
  process.env.EOLFI_RATE_WAIT_SCALE = '0.0001';
  const vs = fakeVscode();
  let n = 0;
  vs.lm.selectChatModels = async () => [{ id: 'm', name: 'M', family: 'm', maxInputTokens: 1000, sendRequest: async () => {
    if (++n === 1) throw new Error(NET_MSG);
    return { stream: (async function* () { yield new vs.LanguageModelTextPart('hecho'); })() };
  } }];
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ prompt: 'hola' }, {}, s, {});
  assert.strictEqual(s.md, 'hecho');
  assert.ok(s.progress_.some((m) => /Fallo de red .*reintento en 2 s/.test(m)));
  delete process.env.EOLFI_RATE_WAIT_SCALE;
});

test('«auditar continuar. Retoma en el archivo 66.» sin barra (caso real) sigue la auditoría', async () => {
  process.env.EOLFI_AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-dir-'));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-proj-'));
  fs.writeFileSync(path.join(root, 'a.py'), 'x = 1\n');
  fs.writeFileSync(path.join(process.env.EOLFI_AUDIT_DIR, 'ultima.json'), JSON.stringify({ root, report: 'informes/x.md' }));
  const vs = fakeVscode({ answer: '### `a.py`\n- ok' });
  vs.workspace.workspaceFolders = [{ uri: { fsPath: root } }];
  const actions = { append: async ({ path: p }) => ({ appended: p }), open: async () => {} };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), actions });
  for (const prompt of ['auditar continuar. Retoma en el archivo 66.', 'continúa la auditoría', 'retoma la auditoría por donde iba']) {
    const s = fakeStream();
    await h({ prompt }, {}, s, {});
    assert.match(s.md, /Auditoría (archivo por archivo|terminada)/, prompt);
    assert.ok(vs.sent.every((x) => x.tools.length === 0), 'no pasa por el agente con herramientas');
  }
  delete process.env.EOLFI_AUDIT_DIR;
});

test('agente con todos los modelos limitados (caso real): espera, reintenta y si no, explica qué hacer', async () => {
  process.env.EOLFI_RATE_WAIT_SCALE = '0.0001';
  const vs = fakeVscode();
  let n = 0;
  modelsWith(vs, [['copilot-utility', () => ++n < 3], ['gpt-4o-mini', 'rate']]);
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ prompt: 'explícame cli.py' }, {}, s, {});
  assert.match(s.md, /revisado por copilot-utility/);                  // se recuperó tras esperar
  assert.ok(s.progress_.some((m) => /espero 60 s y sigo/.test(m)));

  const vs2 = fakeVscode();
  modelsWith(vs2, [['copilot-utility', 'rate'], ['gpt-4o-mini', 'rate']]);
  const s2 = fakeStream();
  await makeChatHandler({ vscode: vs2, summarize, state: {}, getClient: async () => fakeClient() })({ prompt: 'hola' }, {}, s2, {});
  assert.match(s2.md, /Todos los modelos de Copilot que pueden usar herramientas.*@eolfi \/auditar` sí sigue/s);
  delete process.env.EOLFI_RATE_WAIT_SCALE;
});

test('agente: Copilot limitado → sigue con llama.cpp local usando las mismas herramientas', async () => {
  const vs = fakeVscode();
  modelsWith(vs, [['copilot-utility', 'rate'], ['gpt-4o-mini', 'rate']]);
  const seen = [];
  const replies = [
    { content: '', tool_calls: [{ id: 'c1', name: 'eolfi_incognitas', arguments: {} }] },
    { content: 'Hay 1 incógnita abierta: ¿Qué hace X?', tool_calls: [] },
  ];
  const localModel = { name: () => 'qwen3.5-4b (llama.cpp local)', complete: async () => '',
    chatTools: async (conv, tools) => { seen.push({ conv: JSON.parse(JSON.stringify(conv)), tools: tools.map((t) => t.name) }); return replies.shift(); } };
  const h = makeChatHandler({ vscode: vs, summarize, state: { lastSubject: 'abc' }, getClient: async () => fakeClient(), localModel });
  const s = fakeStream();
  const r = await h({ prompt: '¿qué incógnitas hay?' }, {}, s, {});
  assert.strictEqual(s.md, 'Hay 1 incógnita abierta: ¿Qué hace X?');
  assert.ok(s.progress_.some((m) => /sigo con qwen3\.5-4b \(llama\.cpp local\)/.test(m)));
  assert.ok(seen[0].tools.includes('eolfi_incognitas'));
  assert.strictEqual(seen[0].conv[0].role, 'system');
  const toolMsg = seen[1].conv.find((m) => m.role === 'tool');
  assert.match(toolMsg.content, /¿Qué hace X\?/);           // el resultado de la herramienta vuelve al modelo local
  assert.strictEqual(seen[1].conv.find((m) => m.tool_calls).tool_calls[0].function.name, 'eolfi_incognitas');
  assert.strictEqual(r.metadata.model, 'qwen3.5-4b (llama.cpp local)');
  assert.deepStrictEqual(r.metadata.tools.map((t) => t.name), ['eolfi_incognitas']);
});

test('agente local: si promete seguir sin hacerlo se le empuja; si falla, lo explica', async () => {
  const vs = fakeVscode();
  modelsWith(vs, [['copilot-utility', 'rate']]);
  const replies = [{ content: 'Sigo con el resto de archivos.', tool_calls: [] }, { content: 'Terminado.', tool_calls: [] }];
  const seen = [];
  const localModel = { name: () => 'local', complete: async () => '', chatTools: async (conv) => { seen.push(conv.at(-1).content); return replies.shift(); } };
  const s = fakeStream();
  await makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), localModel, workMode: () => 'automatico' })({ prompt: 'audita' }, {}, s, {});
  assert.match(s.md, /Terminado\./);
  assert.match(seen[1], /Has dicho que sigues/);

  const vs2 = fakeVscode();
  modelsWith(vs2, [['copilot-utility', 'rate']]);
  const broken = { name: () => 'local', complete: async () => '', chatTools: async () => { throw new Error('no hay modelo local llama.cpp'); } };
  const s2 = fakeStream();
  await makeChatHandler({ vscode: vs2, summarize, state: {}, getClient: async () => fakeClient(), localModel: broken })({ prompt: 'hola' }, {}, s2, {});
  assert.match(s2.md, /El modelo local tampoco pudo seguir: no hay modelo local llama\.cpp/);
});

test('una respuesta que cita una pregunta (incógnita) no se toma como pregunta al usuario', () => {
  const { asksInsteadOfDoing } = require('../chat');
  assert.ok(!asksInsteadOfDoing('Hay 1 incógnita abierta: ¿Qué hace X?'));
  assert.ok(!asksInsteadOfDoing('La duda principal es: ¿por qué abre el puerto 8080?'));
  assert.ok(asksInsteadOfDoing('He terminado la primera parte. ¿Quieres que siga con el resto?'));
});

test('modelo principal local (Gemma 4): /modelo, herramientas locales e instrucciones; oculta razonamiento privado', async () => {
  let local = true;
  const vs = fakeVscode({ answer: 'no debería usar Copilot' });
  const seen = [];
  const localModel = { name: () => 'gemma-4 (llama.cpp local)', complete: async () => '',
    chatTools: async (conv) => { seen.push(conv[0].content); return { content: 'Respuesta de Gemma.', reasoning: 'Primero miro el archivo.\nLuego respondo.', tool_calls: [] }; } };
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient(), localModel,
    preferLocal: () => local, setPreferLocal: async (v) => { local = v; },
    localConfig: () => ({ model: 'D:/m/gemma-4-12b-it-Q5_K_M.gguf', reasoning: true, show_reasoning: false, temperature: 0.2, system: 'Habla como un pirata.' }),
    instructions: () => 'Responde con viñetas.' });
  let s = fakeStream();
  await h({ command: 'modelo', prompt: 'local' }, {}, s, {});
  assert.ok(local);
  assert.match(s.md, /Modelo principal: local.*gemma-4-12b-it-Q5_K_M\.gguf.*razonamiento activado \(oculto\)/s);
  s = fakeStream();
  const r = await h({ prompt: 'explica cli.py' }, {}, s, {});
  assert.strictEqual(vs.sent.length, 0);                                   // Copilot ni se toca
  assert.doesNotMatch(s.md, /Razonamiento|Primero miro el archivo/);
  assert.match(s.md, /Respuesta de Gemma\.$/);
  assert.match(seen[0], /Habla como un pirata\./);                          // instrucciones del modelo local
  assert.match(seen[0], /INSTRUCCIONES DEL USUARIO.*Responde con viñetas\./s);  // instrucciones para cualquier modelo
  assert.strictEqual(r.metadata.model, 'gemma-4 (llama.cpp local)');
  assert.match(seen[0], /REGLA DE VERACIDAD/);
  assert.match(seen[0], /NO VERIFICADO/);
  s = fakeStream();
  await h({ command: 'modelo', prompt: 'copilot' }, {}, s, {});
  assert.ok(local);
  assert.match(s.md, /Copilot está desconectado de Eolfi hasta nueva orden/);
});

test('no empuja cuando ya respondió y solo ofrece trabajo extra (laboratorio VS Code 2026-11-12)', async () => {
  const { asksInsteadOfDoing, offersExtraAfterAnswer } = require('../chat');
  // Respuesta real de Gemma local tras el triaje de muestra.wasm: la tarea está hecha y solo ofrece más.
  const real = 'Evidencias:\n- Formato: WebAssembly (wasm).\n- Hash SHA-256: ed2bf44b34f0c3c7c84cc25227cb80bc071f6725d108fe97dba5b6df453d84e4.\n'
    + '- Capacidades: No se detectaron capacidades específicas mediante las herramientas de triaje inicial.\n'
    + 'Inferencias:\n- Al ser un archivo .wasm, es un binario compilado diseñado para ejecutarse en entornos WebAssembly.\n'
    + 'Incógnitas:\n- No hay incógnitas abiertas en este momento según el análisis inicial.\n'
    + '¿Deseas que realice un análisis más profundo con las herramientas de REA (como descompilación o inspección de funciones)?';
  assert.ok(asksInsteadOfDoing(real));                       // sigue pareciendo una pregunta…
  assert.ok(offersExtraAfterAnswer(real, true));              // …pero es una oferta extra tras responder
  assert.ok(!offersExtraAfterAnswer(real, false));            // sin haber usado herramientas, no hay respuesta
  assert.ok(!offersExtraAfterAnswer('He listado los archivos. ¿Quieres que los analice?', true));   // pide permiso para la tarea
  assert.ok(!offersExtraAfterAnswer('He encontrado varias herramientas de REA... ¿Te gustaría que ejecute alguna herramienta específica?', true));

  const vs = fakeVscode({ rounds: [{ calls: [{ id: '1', name: 'eolfi_incognitas' }] }, { text: real }] });
  const h = makeChatHandler({ vscode: vs, summarize, state: { lastSubject: 'abc' }, getClient: async () => fakeClient() });
  const s = fakeStream();
  await h({ prompt: 'analiza ejemplos/triaje-y-diff/muestra.wasm' }, {}, s, {});
  assert.match(s.md, /análisis más profundo/);
  assert.strictEqual(vs.sent.length, 2);                      // no hubo una tercera ronda empujada
  assert.ok(!s.progress_.includes('Sigo con la tarea sin preguntarte…'));
});

test('el empujón prohíbe simular resultados', () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'chat.js'), 'utf8');
  assert.match(src, /No simules ni inventes resultados/);
});

test('los archivos adjuntos llegan al modelo en el mensaje del usuario (laboratorio 2026-11-12)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-adj-'));
  const file = path.join(dir, 'referencia.py');
  fs.writeFileSync(file, 'def total(a, b):\n    return a + b\n');
  const vs = fakeVscode({ answer: 'Recibido: referencia.py' });
  vs.workspace.getWorkspaceFolder = () => ({ uri: { fsPath: dir } });
  vs.workspace.asRelativePath = (u) => path.relative(dir, u.fsPath);
  const h = makeChatHandler({ vscode: vs, summarize, state: {}, getClient: async () => fakeClient() });
  await h({ prompt: '¿Qué archivos te he adjuntado?', references: [{ id: 'f', value: { scheme: 'file', fsPath: file, path: file } }] },
    {}, fakeStream(), {});
  const user = vs.sent[0].msgs.at(-1).content;
  assert.match(user, /^¿Qué archivos te he adjuntado\?/);
  assert.match(user, /ARCHIVOS ADJUNTOS POR EL USUARIO[\s\S]*referencia\.py — contenido completo:[\s\S]*def total\(a, b\)/);
});
