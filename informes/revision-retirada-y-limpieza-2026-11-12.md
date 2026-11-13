# Revisión final: opciones a retirar y registro de limpieza — 2026-11-12

Cierre de la Fase 7 («retirar opciones que no puedan sostenerse o mantenerse») y revisión final de
`REGISTRO_LIMPIEZA.md`, como pide `AGENTS.md`. **No se ha borrado, movido ni retirado nada.** Esta lista sirve para
que el titular decida punto por punto. En cada punto constan la evidencia, el impacto y la recomendación.

Leyenda del riesgo de retirar: **bajo** (nada depende de ello), **medio** (hay referencias o usuarios
posibles), **alto** (se pierde información o una capacidad que se usa).

## A. Opciones de Eolfi que no se sostienen tal como están

| # | Opción | Evidencia | Impacto de retirarla | Recomendación | Riesgo |
|---|---|---|---|---|---|
| A1 | Proveedor `gemma` (`--provider gemma`) | En `eolfi/generador/llm.py`, `PRESETS["gemma"]` tiene la misma URL y el mismo modelo que `eolas`. El comentario lo declara «alias de compatibilidad». | Quien escriba `--provider gemma` tendría que usar `eolas`. Tiene 2 archivos de prueba y 5 de código. | Mantenerlo como alias oculto en la ayuda, o retirarlo avisando a quien lo use. | bajo |
| A2 | Proveedores de chat web sin calibrar: `chatgpt-web`, `copilot-web`, `lechat-web` | El código dice «selectores sin calibrar hasta que pasan el autodiagnóstico». Tienen 1 prueba cada uno y no hay ninguna verificación en vivo en los informes. Dependen del HTML de terceros, que cambia sin aviso. | Se pierde una vía que hoy no está demostrada. | Retirarlos de `--provider` hasta que pasen el autodiagnóstico en vivo, o marcarlos como experimentales. | bajo |
| A3 | Todos los proveedores `*-web` (`deepseek-web`, `gemini-web`, `meta-web` y los de A2) con el puente Electron (`eolfi bridge`) | Automatizan las interfaces de consumo de terceros, lo que es frágil y puede chocar con sus condiciones de uso. Tienen un tope de 14 000 bytes de contexto. Para `deepseek` y `gemini` ya existe acceso oficial por API (`PRESETS`). | Para quien usa las webs sin API de pago es la vía gratuita. | **Decisión del titular**: mantener solo los que use de verdad y documentarlos como «no soportados oficialmente». Revisar las condiciones de cada servicio. | medio |
| A4 | Tres formas distintas de levantar un modelo local: Eolas (`eolas`, puerto 11435), `eolfi llama` (`llamacpp.py`, puerto 8090) y `eolfi eolas-v2` (puerto 8090, perfiles Gemma/Mistral) | El 11 y el 12 de noviembre, dos procesos huérfanos en el 8090 cargaron un segundo modelo junto a Gemma en 8 GB de VRAM. Hubo «bad allocation» y el agente se volvió muy lento (`informes/laboratorio-vscode-2026-11-12.md`). `eolfi llama` no tiene pruebas de CLI. `eolas-v2` está en curso, con cambios sin confirmar en `D:\Eolfi`. | Hay flujos y pruebas que usan cada vía. | Unificar en una sola vía con **un único servidor a la vez**, por ejemplo Eolas, con perfiles conmutables. Hasta entonces, que la segunda vía se niegue a arrancar si la GPU ya tiene un modelo. **Requiere diseño con el titular.** | alto |
| A5 | Proveedor `openai` | Tiene 0 pruebas. El modelo por defecto es `""`: sin `OPENAI_MODEL` no funciona. | Es la puerta para cualquier API compatible con OpenAI. | Mantener. Añadir una prueba con un servidor simulado y un error claro cuando falta el modelo. | bajo |
| A6 | `eolfi decompile` (Ghidra) | Sin pruebas en `tests/`. La propia ayuda dice «lento». Necesita Ghidra instalado y no está en la CI. REA ya ofrece decompilación (`batch_decompile`, `procedure_pseudo_code`). | Quien lo use desde la CLI perdería la orden. | Mantener solo si el titular lo usa; si no, retirarlo en favor de REA. | medio |
| A7 | Tipos de proyecto del generador distintos de `static` (`react`, `vue`, `svelte`, `next`, `fastapi`, `express`, `django`, `expo`, `desktop`, `tauri`, `cli`, `dotnet`) | La CI solo verifica de principio a fin `static` (`create_project(..., do_verify=True)`). Del resto solo se comprueba el contenido de los archivos generados. Las dependencias se declaran como `"latest"` (`generators.py:385-387, 701-703`; `generators_backend.py:840`), así que una misma generación puede romperse otro día. | No se retiran: son la función de «Crear proyecto». | No retirarlos. **Fijar versiones** en lugar de `latest` y añadir verificación de principio a fin al menos para `react`, `fastapi` y `cli` en la CI. Los que no se puedan verificar (`expo`, `tauri` o `dotnet` sin su cadena de compilación) deben quedar como «no verificado» en la interfaz. | medio |
| A8 | Nivel de análisis «isolated» | Lo declara `security/levels.py`. Ningún flujo lo usa y el plan ya dice que no se presenta como activo. | Ninguno. | Mantener tal como está. | — |

## B. Registro de limpieza: decisión final por candidato

Origen: `REGISTRO_LIMPIEZA.md`. Ya resueltos: LIM-009 y LIM-011 retirados, LIM-010 incluido en el repositorio y
LIM-012 retirado.

| Candidato | Situación | Recomendación | Riesgo de borrar |
|---|---|---|---|
| LIM-001: `.eolfi-browser-check.out.log` y `.err.log` (1 KB y 4 KB, 06/11) | Evidencia de una comprobación local del panel, ya recogida en los informes. | Borrar. | bajo |
| LIM-002: `eolfi-modo-agente.patch` (112 KB, 06/11) | Respaldo del modo agente/MCP, ya incorporado al historial en gran parte. No se aplica limpiamente. | Conservar hasta comparar cada cambio con el historial, o archivarlo fuera del repositorio (por ejemplo en `backups/`). | medio |
| LIM-003: `backups/` (1,9 MB, 11/11) | Copias de recuperación, ignoradas por Git. | Conservar. Inventariar su contenido antes de cualquier decisión. | alto |
| LIM-004: `generated/nuevo-proyecto/` (**404 MB**, 04/11) | Salida de una prueba de «Crear proyecto», ignorada por Git. Casi todo el tamaño son dependencias instaladas. | Borrar si el titular no la usa como demo. | bajo |
| LIM-005: `PLAN_CORRECCIONES.md` y `PLAN_MEJORAS_2026-11-05.md` | Planes históricos. | Conservar como historia, o moverlos a `docs/historico/`. | bajo |
| LIM-006: `samples/index.json` y el APK sin procedencia | El índice apunta a muestras que no existen. El APK no tiene licencia documentada. | Corregir el índice. Documentar o retirar el APK. | medio |
| LIM-007: scripts o módulos obsoletos | No se ha demostrado ninguno. Los candidatos de la parte A son opciones, no código muerto. | Cerrar sin acción. | — |
| LIM-008: compatibilidad con casos v1 | La base local ya usa el esquema actual. No se sabe si hay paquetes v1 compartidos fuera del equipo. | Conservar si el titular compartió paquetes v1; si no, retirar. | medio |
| LIM-013: `eolfi.db` antiguo en la raíz (1,5 MB; ya no hay `-wal`/`-shm`) | Contiene `client_tokens`. La ruta actual es `~/.eolfi/eolfi.db`, ya migrada. | Comprobar que la base nueva tiene los datos y entonces borrar la antigua con borrado seguro. | medio |

## C. Candidatos nuevos de esta sesión, fuera del repositorio

| Ruta | Evidencia | Recomendación | Riesgo |
|---|---|---|---|
| `D:\Eolfi-fases34` | Worktree de las ramas de esta sesión, ya fusionadas (PR #2 a #6). | Quitarlo con `git worktree remove`. | bajo |
| `D:\Eolfi-sim34` | Worktree desacoplado de una simulación previa. Sus cambios ya están en `main`. | Quitarlo con `git worktree remove`. | bajo |
| `D:\Eolfi-objetivos` | Worktree de la rama `fusion-avance-2-3` (`68f625e`), ya fusionada en `main`. Puede contener archivos de supervisión de otra sesión. | Revisar si queda algo sin confirmar y quitarlo. | medio |
| `D:\Eolfi-supervision` | Carpeta, no worktree. Por el nombre, parece de supervisión de otra sesión; no se ha inspeccionado. | Decisión del titular. | — |
| `D:\Eolfi\.pytest-tmp-*` (8 carpetas) | Temporales de ejecuciones anteriores de pytest con `--basetemp`. | Borrar. | bajo |
| `D:\Eolfi\.eolfi-server.err.log` y `.out.log` (584 KB y 1 KB, 09/11) | Registro de un servidor del panel arrancado en segundo plano. | Borrar si no hace falta como evidencia. | bajo |
| `~/.eolfi/*.vsix` | 32 paquetes de versiones antiguas de la extensión (1,7 MB). Solo hace falta el último. | Borrar todas menos la última. | bajo |
| Extensión instalada 0.6.11 | Más antigua que `main` aunque tiene el mismo número de versión: le faltan `file-tools.js` y `lm-provider.js`. | Reinstalarla con `python -m eolfi vscode --install` y **subir el número de versión** en cada cambio, para que no vuelvan a coincidir. | — |
| `~/.eolfi/eolas-v2.runtime.json` y el proceso del 8090 | El proceso ya está parado (`eolas-v2 stop`). | Nada; ver A4. | — |
| `D:\Tools\platform-tools` | Herramienta instalada a petición del titular (adb). | Conservar. | — |

## D. Archivos sin confirmar del titular en `D:\Eolfi` (no los ha tocado esta sesión)

Son trabajo en curso, no residuos. Los listo para que el titular decida si se confirman, se mueven o se retiran:
`eolfi/arithmetic.py`, `tools/creation_benchmark.py`, `tools/profile_local_models.py`, `informes/model-timings.json`,
`PLAN_NEMO_MOE_ACTIVO.md`, `REGISTRO_NEMO_MOE.md`, `.fuse_hidden0000002d00000001` (temporal de un sistema de
archivos FUSE, probablemente residuo) y los cambios en `cli.py`, `eolas_v2.py`, `llamacpp.py`, `server.py`,
`web/app.js` y `web/index.html`. Los archivos de supervisión (`OBJETIVOS_EOLFI.md`, `PROMPT_*`, `prompts-o*`,
`plan-v2/`) **no se confirman nunca**, por regla.

## Qué hace falta del titular

1. **A4: DECIDIDA (2026-11-12): guardia común.** Eolas para el uso diario; eolas-v2 con guardia en los dos sentidos y vigilante de inactividad; `eolfi llama start` retirado. PR #8, `informes/guardia-modelo-local-2026-11-12.md`. **A3** sigue pendiente como decisión de producto.
2. **A2, A6 y la parte B:** marcar en cada fila «retirar», «conservar» o «más adelante».
3. Con esa lista, una PR retirará solo lo marcado, con la suite completa y la entrada correspondiente en
   `REGISTRO_LIMPIEZA.md`.
