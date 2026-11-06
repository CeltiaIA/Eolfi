// Servidor MCP falso (stdio, JSON por líneas) para las pruebas del cliente de REA.
'use strict';
const rl = require('node:readline').createInterface({ input: process.stdin });
const tools = [
  { name: 'inspect_artifact', description: 'Inspecciona un artefacto\nmás texto', annotations: { readOnlyHint: true }, inputSchema: { type: 'object', properties: { path: { type: 'string' } } } },
  { name: 'start_frida_session', description: 'Lanza Frida contra un proceso', annotations: { readOnlyHint: false }, inputSchema: { type: 'object' } },
];
const send = (m) => process.stdout.write(`${JSON.stringify(m)}\n`);
rl.on('line', (line) => {
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  if (m.method === 'initialize') return send({ jsonrpc: '2.0', id: m.id, result: { protocolVersion: m.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'falso' } } });
  if (m.method === 'tools/list') return send({ jsonrpc: '2.0', id: m.id, result: m.params.cursor ? { tools: [tools[1]] } : { tools: [tools[0]], nextCursor: 'p2' } });
  if (m.method === 'tools/call') return send({ jsonrpc: '2.0', id: m.id, result: { content: [{ type: 'text', text: `ok ${m.params.name} ${JSON.stringify(m.params.arguments)}` }] } });
  send({ jsonrpc: '2.0', id: m.id, error: { code: -32601, message: 'no existe' } });
});
