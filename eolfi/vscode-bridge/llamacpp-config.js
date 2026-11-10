// Configuración común del modelo local llama.cpp (por defecto Gemma 4), la misma que usa Eolfi en Python
// (eolfi/llamacpp.py): ~/.eolfi/llamacpp.json o EOLFI_LLAMACPP_CONFIG. Se lee en cada petición, así que los cambios
// valen al momento (salvo «server», «model», «port», «ctx», «gpu_layers» y «threads», que reinician llama-server).
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DEFAULTS = {
  server: '', model: '', alias: 'gemma-4-12b-it:latest', port: 8090, ctx: 32768, gpu_layers: 99, threads: 0,
  reasoning: true, review_reasoning: false, show_reasoning: true,
  temperature: 0.2, top_p: 0.95, max_tokens: 4096, system: '', extra_args: [],
};
const GEMMA_CANDIDATES = [
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
  const options = { temperature: Number(cfg.temperature), top_p: Number(cfg.top_p), max_tokens: Number(cfg.max_tokens),
    num_ctx: Number(cfg.ctx) || DEFAULTS.ctx, num_gpu: Number(cfg.gpu_layers) };
  if (Number(cfg.threads) > 0) options.num_thread = Number(cfg.threads);
  options.chat_template_kwargs = { enable_thinking: !!think };
  return options;
}

module.exports = { loadConfig, configFile, requestOptions, DEFAULTS };
