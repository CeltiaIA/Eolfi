'use strict';
const readline = require('node:readline');

function send(message) { process.stdout.write(`${JSON.stringify(message)}\n`); }
readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let message;
  try { message = JSON.parse(line); } catch { return; }
  if (message.method === 'initialize') {
    send({ jsonrpc: '2.0', id: message.id, result: { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'fake-mcp-env', version: '1' } } });
  } else if (message.method === 'tools/list') {
    send({ jsonrpc: '2.0', id: message.id, result: { tools: [{ name: 'read_env', inputSchema: { type: 'object', properties: {} }, annotations: { readOnlyHint: true } }] } });
  } else if (message.method === 'tools/call') {
    send({ jsonrpc: '2.0', id: message.id, result: { content: [{ type: 'text', text: `${process.env.MCP_CONFIG_TOKEN}|${process.env.EOLFI_TEST_SECRET}|${process.env.EOLFI_UNDECLARED_TOKEN}` }] } });
  } else if (message.id !== undefined) {
    send({ jsonrpc: '2.0', id: message.id, result: {} });
  }
});
