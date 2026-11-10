# Estado del trabajo — resumen para retomar desde cualquier chat

> Archivo vivo. Se actualiza después de cada paso. Última actualización: **2026-11-10 (Europa/Madrid)**.
> Orden de lectura para retomar: este archivo → `D:\celtiaia-v2\plan-v2\PLAN-CELTIA-V2.md` → `D:\Eolfi-objetivos\informes\progreso-objetivos-eolfi.md`.

## 1. En curso ahora

**CeltIA V2 (Mistral redacta → Gemma revisa)**, ejecutado por **Eolfi en modo automático, paso a paso**, en una copia aislada de CeltIA:

- Worktree: `D:\celtiaia-v2`, rama `celtia-v2-compositor` (desde `main` `9d9175e` de `D:\celtiaia`). El CeltIA en marcha no se toca.
- Plan completo: `D:\celtiaia-v2\plan-v2\PLAN-CELTIA-V2.md`. Encargos: `plan-v2\paso-01.md` … `paso-14.md`.
- Fases: **A** código y API `POST /api/chat/v2` (pasos 01–08) → **B** casilla en la web, lanzador y comprobación de que Mistral está en Eolas (09–14) → **C** importar Mistral 7B en Eolas (`eolas create`) → **D** prueba en vivo con los dos modelos e informe.
- Estado: fase A en ejecución. Cadena automática ya lanzada: **A (01–08) → B (09–14) → O14 (o14-1…5) → C+D (15–18)**. Cada fase arranca sola cuando termina la anterior; la B solo si la suite de la A queda sin fallos.
- Fase B validada en simulación: 108 pruebas, 105 aprobadas, 0 fallos, 3 omitidas.
- Fase C: `plan-v2\Modelfile.mistral` + `eolas create mistral-7b-instruct-v0.3:latest` (copia el GGUF de 4,4 GB al almacén de Eolas).
- Fase D: `scripts/e2e-live-v2.mjs` levanta una instancia aislada contra el Eolas real, llama a `/api/chat/v2` y vigila `/api/ps` (orden Mistral → Gemma y nunca dos modelos a la vez). Informe en `runtime\e2e\v2-live-*.json`.

| Paso | Estado | Tiempo | Comprobación |
|---|---|---|---|
| A-01 copiar `scripts/composite-v2.mjs` | hecho | 212 s | idéntico al preparado; `node --check` OK |
| A-02 copiar y ejecutar `test/composite-v2.test.mjs` | hecho | 174 s | idéntico; 6/6 |
| A-03 `server.mjs`: importar `handleChatV2` | hecho | 159 s | edición exacta; `node --check` OK |
| A-04 `server.mjs`: constante `V2_DRAFTER` | hecho | 184 s | edición exacta; `node --check` OK |
| A-05 `server.mjs`: ruta `POST /api/chat/v2` | hecho | 286 s | línea larga copiada exacta; `node --check` OK |
| A-06 prueba de sistema + suites afectadas | hecho | 266 s | system + composite-v2: 23/23 |
| A-07 copiar la especificación | falló (Eolas reinició su Gemma por el relanzamiento del trabajo del otro agente); se repite al inicio de la fase B | 11 s | — |
| A-08 `node --test` + `CONTINUIDAD.md` | hecho | 489 s | suite 106 pruebas, 103 aprobadas, 0 fallos, 3 omitidas; entrada en CONTINUIDAD con cifras literales |
| **Fase A** | **hecha** | | suite completa sin fallos → fase B lanzada automáticamente |
| A-07 (repetición) copiar la especificación | hecho | 184 s | `docs/spec/celtia-v2-composite.md` idéntico |
| B-09 módulo con comprobación de Mistral en Eolas + pruebas | hecho | 216 s | idénticos; 7/7 |
| B-10 casilla V2 en `public/index.html` | hecho | 163 s | edición exacta |
| B-11 `public/app.js` usa `/api/chat/v2` con la casilla | hecho | 164 s | edición exacta; `node --check` OK |
| B-12 lanzador: parámetro `-V2Drafter` | falló (Gemma se cayó dentro de Eolas al empezar la ronda; sin relanzamientos externos); se repite tras B-14 | 11 s | — |
| B-13 lanzador: exportar `CELTIAIA_V2_DRAFTER` | falló (Gemma llamó a la edición sin ruta); se repite en una sola línea (`paso-13b`) | 281 s | sin cambios en el archivo |
| B-14 prueba de sistema de la casilla y el lanzador + suite | hecho (prueba añadida); su prueba del lanzador falla hasta repetir 12 y 13 | 195 s | — |
| Repetición B-12 (parámetro `-V2Drafter`) | hecho | 164 s | `launch-eolas.ps1` se analiza sin errores |
| Repetición B-13b | falló (3.ª caída de Gemma en Eolas, ya con 16k/16 capas); sin cambios | 121 s | — |
| B-13b (reanudado) lanzador exporta `CELTIAIA_V2_DRAFTER` | hecho | 259 s | PS1 sin errores; system 18/18 |
| B-14b suite completa | hecho | 137 s | 108 pruebas, 105 aprobadas, 0 fallos, 3 omitidas |
| **Fase B** | **hecha** | | igual que la simulación |
| O14-1 `package.json`: `languageModelChatProviders` «eolas» | hecho | 148 s | JSON válido |
| O14-2 `extension.js`: `require('./lm-provider')` | hecho | 82 s | edición exacta (el módulo se copia en O14-4) |
| O14-3, O14-4 (1.er intento) | fallaron en 5 s: tras O14-2 la extensión pedía `lm-provider.js`, que no se copiaba hasta O14-4, y la extensión de Eolfi no arrancaba (error de orden de los pasos, de la supervisión) | | La supervisión copió `lm-provider.js` (el mismo archivo de O14-4) y reanudó: O14-3 → O14-4 → O14-5 → C+D (`resume2-driver.sh`) |
| O14-3 registrar el modelo en `extension.js` | hecho | 174 s | línea exacta; `node --check` OK |
| O14-4 copiar módulo y prueba + suites | hecho en el 2.º intento (el 1.º cayó por la 4.ª caída de Gemma) | 214 s | idénticos; vscode-bridge 168/168 |
| O14-5 progreso en `informes/progreso-objetivos-eolfi.md` | hecho | 245 s | sección O14 escrita |
| **O14** | **hecho e instalado** (2026-11-10): extensión 0.6.11 instalada en el VS Code del usuario desde `D:\Eolfi-objetivos` | | vscode-bridge 168/168; e2e en VS Code real 11/11 (la pregunta sin Copilot la responde el modelo local por Eolas); archivos instalados idénticos salvo `__metadata` |
| C-15 importar Mistral en Eolas (`eolas create`) | hecho | 337 s | Eolas lista `mistral-7b-instruct-v0.3:latest` (4,07 GiB) junto a Gemma (7,84 GiB) |
| D-16 copiar `scripts/e2e-live-v2.mjs` | hecho | 158 s | idéntico; `node --check` OK |
| D-17 prueba en vivo con los dos modelos | hecho (comprobado 2026-11-10 al retomar) | 84 s el chat | `runtime\e2e2-live-2026-11-09T23-41-13-547Z.json`: 6/6 OK; cargas Gemma → Mistral → Gemma, nunca dos a la vez |
| D-18 cierre en `CONTINUIDAD.md` | hecho (2026-11-10, por la supervisión) | | sección «CeltIA V2 — interfaz, Mistral y prueba en vivo»; línea RESULTADO reconstruida del JSON (la salida de consola no se conservó) |
| **Fase D / CeltIA V2** | **hecha y confirmada** | | commit `c9342b5` en `celtia-v2-compositor` (sin `plan-v2/`); suite 108/105/0/3 |
| **Corte de sesión (2026-11-10 ~00:00)** | la cadena se paró; se reanudó con `scratchpad/auto/resume-driver.sh`: B-13b → B-14b → O14 → C+D | | |

> Caídas de Gemma en Eolas: 2 (23:18 y 23:39). Eolas lo relanza solo; el reintento funciona. Las cadenas pendientes usan `scratchpad/auto/run-steps.sh`, que reintenta una vez cualquier paso que caiga por esto.

### O14 — Eolas como modelo de VS Code (aprobado por el titular)
- Problema: en el VS Code del usuario, `@eolfi` da «Language model unavailable» porque VS Code exige un modelo y no hay sesión de Copilot.
- Prototipo comprobado en un VS Code limpio sin Copilot: con el proveedor registrado, `@eolfi /ayuda` llega a la extensión con el modelo `eolas/gemma-4-12b-it`.
- Implementación preparada y validada en simulación (`D:\Eolfi-objetivos\prompts-o14\`): `lm-provider.js` + 5 pruebas; vscode-bridge 168/168.
- Ejecución por Eolfi encadenada después de la fase B (pasos `o14-1` … `o14-5`). Después: empaquetar la extensión `.vsix` e instalarla en el VS Code del usuario (aprobado).

## 2. Hecho hoy (2026-11-09)

### Plan de objetivos REA para Eolfi
- Informe: `D:\Eolfi\informes\plan-objetivos-rea-2026-11-09.md` (REA sobre vscode-bridge, bridge, observe, fusibles de Electron y SQLite; 13 objetivos).
- Implementado por Eolfi en automático en el worktree **`D:\Eolfi-objetivos`** (rama `objetivos-rea-2026-11-09`), **sin confirmar en Git**:
  - **O1+O2:** política de navegación y permisos del puente (`eolfi/bridge/policy.mjs`, `main.mjs`). La otra sesión añadió la misma política al motor Chrome (`engine/chrome.mjs`).
  - **O3:** captura de escritorio con `PrintWindow` (hecha por otra sesión).
  - **O4:** la terminal del agente mata el árbol de procesos (`agent-tools.js`).
  - **O5:** el lanzador de Eolas sin ruta fija y con SHA-256 (`eolas-starter.js`, ajustes `eolfi.fallback.eolasLauncher*`).
  - **O10:** 5 imports sin uso retirados (LIM-009 → RETIRADO).
  - Herramienta nueva **`eolfi_edit_file`** (por fragmento o por rango de líneas).
  - Verificación final: pytest 460/2 omitidas; bridge 59/0/4 omitidas; vscode-bridge 163/163; e2e 18/18; ruff F limpio.
  - Inicios de sesión probados en vivo con la política nueva: DeepSeek, Gemini y Meta «con sesión» y 0 bloqueos (con `eolfi bridge --login`).
  - Detalle: `D:\Eolfi-objetivos\informes\progreso-objetivos-eolfi.md`.
- En el árbol principal `D:\Eolfi`, sin confirmar: corrección de `eolfi/bridge/adapters/meta.mjs` (Meta pliega el código: «N líneas ocultas») y su prueba `test/meta-hidden-lines.test.mjs`.

### Configuración cambiada
- `~/.eolfi/llamacpp.json`: contexto 32768 y 11 capas en GPU (antes 12288 y 17; copia en `llamacpp.json.bak-2026-11-09`). Con 32k, Gemma deja de entrar en bucles; va a unos 3 tokens/s.

## 3. Cómo hacer que Eolfi trabaje solo (lo aprendido)

- Gemma 12B local con 12k de contexto se atasca (relee archivos en bucle). Con 32k y **una edición por ronda**, cada paso tarda 1–2,5 min y sale bien.
- Encargos grandes → falla o declara «hecho» sin pruebas. Siempre: un paso por ronda, texto exacto que sustituir, y comprobación de la supervisión después de cada paso.
- Para crear archivos largos: prepararlos y que Eolfi los copie con una orden de terminal.
- Runner de supervisión (VS Code con perfil temporal y `@eolfi` en automático): `scratchpad/auto/launch.js` + `runner.js`. Necesita el panel `python -m eolfi serve` en `127.0.0.1:8777` y Eolas en `11435`. **No cerrar ni recargar la ventana de VS Code que abre.**

## 4. Pendientes y avisos

- Confirmado en Git el 2026-11-10 a nombre de Luis Manuel Cousido Hermida: `D:\celtiaia-v2` commit `c9342b5` (rama `celtia-v2-compositor`) y `D:\Eolfi-objetivos` commit `57ecbbc` (rama `objetivos-rea-2026-11-09`; pytest 460, bridge 59, vscode-bridge 168, e2e 18). Publicado el 2026-11-10: CeltIA V2 como primer commit (`5be3c2c`, sin historia previa, mismo contenido que `c9342b5`) en `main` del repositorio privado https://github.com/CeltiaIA/CeltiaIA-V2; la rama de objetivos (11 commits) en `CeltiaIA/Eolfi` con la PR https://github.com/CeltiaIA/Eolfi/pull/1 (sin fusionar; CI en curso al abrirla). Siguen sin confirmar los archivos de supervisión. La corrección de `meta.mjs` (líneas ocultas de Meta) quedó confirmada en `D:\Eolfi`, rama `avance-fases-2-3`, commit `7cdaaa5`, publicado en `origin/avance-fases-2-3` el 2026-11-10 (no está en la PR #1, que sale de `objetivos-rea-2026-11-09`). Al integrar, no confirmar los archivos de supervisión: `OBJETIVOS_EOLFI.md`, `PROMPT_*`, `prompts-o5/`, `prompts-o10/` (en `D:\Eolfi-objetivos`) ni `plan-v2/` (en `D:\celtiaia-v2`).
- Uniones creadas para las pruebas (ignoradas por Git): `D:\Eolfi-objetivos\tests\e2e\node_modules`, `D:\Eolfi-objetivos\eolfi\bridge\node_modules` y `D:\celtiaia-v2\scripts\fios\node_modules`.
- El puente de chats web de Eolfi no está en marcha: `python -m eolfi bridge`.
- El trabajo «CeltIA V2 Composite» de otro agente (web Next.js genérica en `D:\a1\celtia-v2-eolfi-generated`) se paró a petición del titular el 2026-11-09 a las 22:55; la carpeta generada se conserva.
