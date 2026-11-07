// Configuración común del modelo local llama.cpp (por defecto Gemma 4), la misma que usa Eolfi en Python
// (eolfi/llamacpp.py): ~/.eolfi/llamacpp.json o EOLFI_LLAMACPP_CONFIG. Se lee en cada petición, así que los cambios
// valen al momento (salvo «server», «model», «port», «ctx» y «gpu_layers», que necesitan reiniciar llama-server).
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DEFAULTS = {
  server: '', model: '', alias: 'gemma-4', port: 8090, ctx: 32768, gpu_layers: 99,
  reasoning: true, review_reasoning: false, show_reasoning: false,
  temperature: 0.2, top_p: 0.95, max_tokens: 4096, system: '', extra_args: [],
};
const GEMMA_CANDIDATES = [
  path.join(os.homedir(), '.eolfi', 'models', 'gemma-4-E4B-it-Q4_K_M.gguf'),
  'D:\\LMStudio\\models\\lmstudio-community\\gemma-4-E4B-it-GGUF\\gemma-4-E4B-it-Q4_K_M.gguf',
  'D:\\AI\\Hydra\\gguf\\gemma-4-12b-it-Q5_K_M.gguf',
];

function configFile() {
  return process.env.EOLFI_LLAMACPP_CONFIG || path.join(os.homedir(), '.eolfi', 'llamacpp.json');
}

function loadConfig({ create = true, findServer = null } = {}) {
  const f = configFile();
  let user = {};
  try { user = JSON.parse(fs.readFileSync(f, 'utf8').replace(/^\uFEFF/, '')); } catch {
    if (create) {
      user = { ...DEFAULTS, server: (findServer && findServer()) || '', model: GEMMA_CANDIDATES.find((p) => fs.existsSync(p)) || '' };
      try { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, `${JSON.stringify(user, null, 2)}\n`); } catch { /* sin escribir */ }
    }
  }
  const cfg = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (user[k] !== undefined) cfg[k] = user[k];
  if (!cfg.model) cfg.model = GEMMA_CANDIDATES.find((p) => fs.existsSync(p)) || '';
  cfg.port = Number(cfg.port) || DEFAULTS.port;
  return cfg;
}

// Parámetros de cada petición a llama-server (API de OpenAI). review = revisión de la auditoría (más rápida).
function requestOptions(cfg, { review = false } = {}) {
  const think = review ? cfg.review_reasoning : cfg.reasoning;
  return { temperature: Number(cfg.temperature), top_p: Number(cfg.top_p), max_tokens: Number(cfg.max_tokens),
    chat_template_kwargs: { enable_thinking: !!think } };
}

module.exports = { loadConfig, configFile, requestOptions, DEFAULTS };
