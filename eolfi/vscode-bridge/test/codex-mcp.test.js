'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { readCodexMcpServers } = require('../codex-mcp');
const { McpClient } = require('../rea');
const { pythonCommand } = require('../lm-integration');

function python() {
  return pythonCommand({ workspace: { getConfiguration: () => ({ get: () => '' }) } });
}

test('importa solo servidores stdio habilitados y valida sus campos', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-codex-mcp-'));
  const config = path.join(dir, 'config.toml');
  fs.writeFileSync(config, [
    '[mcp_servers.node_repl]',
    "command = 'node'",
    "args = ['--version']",
    "env_vars = ['CODEX_TEST_TOKEN']",
    "[mcp_servers.node_repl.env]",
    "SERVICE_TOKEN = 'a-literal-token-123456'",
    '[mcp_servers.remote]',
    "url = 'https://example.test/mcp'",
    '[mcp_servers.disabled]',
    'enabled = false',
    "command = 'node'",
    '[mcp_servers.invalid]',
    "command = 'node'",
    'args = [1, 2]',
  ].join('\n'), 'utf8');
  try {
    const servers = readCodexMcpServers({ python: python(), configFile: config });
    assert.deepEqual(Object.keys(servers), ['node_repl']);
    assert.deepEqual(servers.node_repl, {
      command: 'node', args: ['--version'], env: { SERVICE_TOKEN: 'a-literal-token-123456' }, envVars: ['CODEX_TEST_TOKEN'],
    });
    assert.deepEqual(readCodexMcpServers({ python: python(), configFile: path.join(dir, 'missing.toml') }), {});
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('pasa solo env_vars declaradas al proceso MCP y redacta valores de entorno de resultados', async () => {
  const previous = {
    EOLFI_TEST_SECRET: process.env.EOLFI_TEST_SECRET,
    EOLFI_UNDECLARED_TOKEN: process.env.EOLFI_UNDECLARED_TOKEN,
  };
  process.env.EOLFI_TEST_SECRET = 'shell-secret-value-987654';
  process.env.EOLFI_UNDECLARED_TOKEN = 'must-not-reach-child-123456';
  let childEnv;
  const fixture = path.join(__dirname, '..', 'fixtures', 'fake-mcp-env.js');
  const client = new McpClient({ command: process.execPath, args: [fixture],
    env: { MCP_CONFIG_TOKEN: 'literal-config-token-123456' }, envVars: ['EOLFI_TEST_SECRET'] }, {
    spawnFn: (command, args, options) => { childEnv = options.env; return spawn(command, args, options); },
  });
  try {
    assert.deepEqual((await client.listTools()).map((t) => t.name), ['read_env']);
    assert.equal(childEnv.MCP_CONFIG_TOKEN, 'literal-config-token-123456');
    assert.equal(childEnv.EOLFI_TEST_SECRET, 'shell-secret-value-987654');
    assert.equal(Object.hasOwn(childEnv, 'EOLFI_UNDECLARED_TOKEN'), false);
    const result = await client.callTool('read_env', {});
    assert.doesNotMatch(result.text, /literal-config-token-123456|shell-secret-value-987654|must-not-reach-child-123456/);
    assert.equal((result.text.match(/\[credencial redactada\]/g) || []).length, 2);
  } finally {
    client.dispose();
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
});
