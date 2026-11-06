// Lee solo servidores MCP locales stdio configurados en Codex; no importa servicios HTTP ni credenciales de la cuenta.
'use strict';
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { safeEnv } = require('./rea');

const PYTHON = String.raw`
import json, sys, tomllib
with open(sys.argv[1], 'rb') as f:
    config = tomllib.load(f)
rows = {}
for name, server in (config.get('mcp_servers') or {}).items():
    if not isinstance(server, dict) or server.get('enabled') is False:
        continue
    command = server.get('command')
    if not isinstance(command, str) or not command.strip() or server.get('url'):
        continue
    args = server.get('args', [])
    env = server.get('env', {})
    env_vars = server.get('env_vars', [])
    if not isinstance(args, list) or any(not isinstance(x, str) for x in args):
        continue
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        continue
    if not isinstance(env_vars, list) or any(not isinstance(x, str) for x in env_vars):
        continue
    row = {'command': command, 'args': args, 'env': env, 'envVars': env_vars}
    if isinstance(server.get('cwd'), str): row['cwd'] = server['cwd']
    rows[name] = row
print(json.dumps(rows, separators=(',', ':')))
`;

function readCodexMcpServers({ python = 'python', configFile = path.join(os.homedir(), '.codex', 'config.toml') } = {}) {
  if (!fs.existsSync(configFile)) return {};
  try {
    const raw = execFileSync(python, ['-c', PYTHON, configFile], {
      encoding: 'utf8', timeout: 5000, maxBuffer: 1024 * 1024,
      windowsHide: true, env: safeEnv(process.env), stdio: ['ignore', 'pipe', 'ignore'],
    });
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    // No se incluyen stdout, stderr, rutas ni valores de configuración en mensajes de error o logs.
    throw new Error('No se pudo leer la configuración de servidores MCP de Codex con Python 3.11 o posterior.');
  }
}

module.exports = { readCodexMcpServers };
