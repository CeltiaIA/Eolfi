'use strict';
// 18/11/2026 (titular): cambiar de modelo no debe obligar a tocar la extensión. El modelo sale de eolas-v2.json.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { eolasV1Model, EOLAS_MODEL } = require('../local-model');
const { v2Target } = require('../eolas-v2-starter');
const { makeEolasProvider } = require('../lm-provider');

function config(data) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-modelo-'));
  const file = path.join(dir, 'eolas-v2.json');
  if (data) fs.writeFileSync(file, JSON.stringify(data));
  return { EOLFI_EOLAS_V2_CONFIG: file };
}

test('el modelo de Eolas V1 sale de eolas-v2.json; EOLAS_MODEL manda y sin archivo queda el respaldo', () => {
  assert.strictEqual(eolasV1Model({ env: config({ eolas_v1_model: 'qwen3-14b:latest' }) }), 'qwen3-14b:latest');
  assert.strictEqual(eolasV1Model({ env: { ...config({ eolas_v1_model: 'a:latest' }), EOLAS_MODEL: 'b:latest' } }), 'b:latest');
  assert.strictEqual(eolasV1Model({ env: config(null) }), EOLAS_MODEL);
});

test('sin perfil activo en eolas-v2.json la extensión no elige uno: arranca el que diga Eolfi', () => {
  assert.strictEqual(v2Target({ env: config(null) }).profile, '');
  const env = config({ active_profile: 'mi_modelo', profiles: { mi_modelo: { alias: 'mi-modelo:latest' } } });
  assert.deepStrictEqual(v2Target({ env }), { profile: 'mi_modelo', alias: 'mi-modelo:latest', url: 'http://127.0.0.1:8090' });
});

test('el nombre del modelo en VS Code es el del modelo en uso, no una marca fija', async () => {
  const p = makeEolasProvider({ vscode: {}, localModel: {}, modelId: 'qwen3-14b:latest' });
  const [info] = await p.provideLanguageModelChatInformation();
  assert.strictEqual(info.name, 'qwen3-14b:latest · Eolas (local)');
  assert.strictEqual(info.family, 'qwen3');
});
