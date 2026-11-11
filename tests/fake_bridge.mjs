// Pasarela real del puente con un adaptador simulado (para pruebas de Eolfi en Python).
// Uso: node tests/fake_bridge.mjs <bridge.json> <respuestas.json>
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const [bridgeFile, repliesFile] = process.argv.slice(2);
const { startBridgeServer } = await import(pathToFileURL(resolve('eolfi/bridge/server.mjs')).href);
const replies = JSON.parse(readFileSync(repliesFile, 'utf8'));
const seen = [];
const fake = (site) => ({
  status: async () => ({ ok: true, detail: `${site} simulado` }),
  send: async (prompt, _signal, conversation) => {
    seen.push({ site, conversation, length: prompt.length, first: prompt.slice(0, 40) });
    writeFileSync(repliesFile + '.seen.json', JSON.stringify(seen));
    return 'Claro, aquí tienes:\n```json\n' + JSON.stringify(replies.shift()) + '\n```';
  },
});
const token = 'f'.repeat(64), panelToken = 'e'.repeat(64);
const { port } = await startBridgeServer({
  adapters: { deepseek: async () => fake('deepseek'), gemini: async () => fake('gemini'), meta: async () => fake('meta') },
  // EOLFI_FAKE_BRIDGE_DENY=1 simula que el usuario deniega cada envío en el diálogo del puente.
  approve: async () => process.env.EOLFI_FAKE_BRIDGE_DENY !== '1', token, panelToken,
  screens: { meta: async () => Buffer.from([0xff, 0xd8, 0xff, 0xd9]) },
});
writeFileSync(bridgeFile, JSON.stringify({ url: `http://127.0.0.1:${port}`, token, panelToken }));
