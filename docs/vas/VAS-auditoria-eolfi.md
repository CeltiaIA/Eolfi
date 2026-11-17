# Auditoría VAS (Sistema Autónomo Verificable) de Eolfi — 16/11/2026

Auditoría de **solo lectura**. No se modificó ningún archivo del repositorio ni el estado de git, no se arrancaron servidores ni modelos y no se leyó `eolfi.db` ni `~/.eolfi`. La referencia es `origin/main` = `1d766da`, extraída con `git archive` a una carpeta temporal del scratchpad (`...\scratchpad\om`), sin cambiar de rama. Los números de línea son de `origin/main` salvo que se indique otra rama.

> El `D:\Eolfi` de trabajo está en `higiene-ruff-f` (`ca05ef4`), **12 commits por detrás y 6 por delante** de `origin/main`. Además, 2 de esos commits (`007550f`, `ca05ef4`) no están en `origin/higiene-ruff-f`. Según ESTADO-TRABAJO, `007550f` quedó superado por la PR #40. **No analices calidad sobre el árbol de trabajo actual:** le faltan autofix (#38), el motor local compartido (#41) y las mejoras de Eolas.

## 0. Comprobaciones ejecutadas

| Comando | Resultado |
|---|---|
| `git rev-list --left-right --count origin/main...HEAD` | `12  6` |
| `gh pr list --repo CeltiaIA/Eolfi --state open` | 21 PR abiertas: #19-#33, #35, #39, #43-#46 |
| `git merge-tree --write-tree` (cada PR contra su base, y por pares) | Ver §2. Comando de solo lectura: solo escribe objetos, sin ref ni índice |
| `python -m ruff check eolfi --select F` (copia de origin/main) | **2 avisos**: F841 `eolas_v2.py:2032` (`code_cases` sin usar, inocuo) y F401 `server.py:444` (`eolas_v2` importado sin usar) |
| `python -m ruff check eolfi` (copia de origin/main, configuración global de ruff 0.16.8; el repositorio no tiene `[tool.ruff]`) | 239 avisos, 118 corregibles. Los principales: FURB167 36, I001 32, PLW1510 31 (`subprocess.run` sin `check`), ISC004 26, UP035 23, TRY004 16, RUF100 15, BLE001 9, B023 9 y S110 5 |
| `python -m ruff check eolfi --select F` (árbol de trabajo, `higiene-ruff-f`) | 0 avisos |
| `python -m pytest --collect-only -q` (copia de origin/main) | **678 pruebas recogidas** en 5,5 s |
| `python -m pytest --collect-only -q` (árbol de trabajo) | 664 pruebas recogidas |
| La suite completa | **NO EJECUTADA**, por petición expresa. No se afirma que esté en verde |

## 1. Arquitectura y flujo

### 1.1 `create --ai` (cli.py:818 → flows/create_flow.py:120 → generador/assist.py:240)

```
cli create ──► create_project (case_run, evidencias)
   ├─ analizar fuentes → spec.py → generators*.py (plantillas por destino, 13 destinos)
   ├─ verify(out) [verify.py:159]  instalar/compilar/pruebas de la PLANTILLA
   ├─ si falla y autofix: run_autofix → assist.autofix (≤3 rondas IA, verificación aislada, restaurar si no verde)
   └─ si --ai: run_assist → assist.assist
          ├─ (si no hay node_modules/.venv) verify con instalación
          ├─ collect_context(llm.context_bytes)  [60 000 B para eolas-v2, llm.py:49]
          └─ _rounds  (MAX_ROUNDS=3, assist.py:30)
               ronda n: llm.complete(JSON schema estricto) → _apply (rutas permitidas, sin manifiestos,
               auth protegida, pruebas sin perder aserciones) → verify(sandbox=True, install=False)
               ├─ verde → ok
               └─ rojo  → se añade la respuesta COMPLETA + cola del error (4000 car.) a la conversación
          si no hay verde: _restore (todo vuelve atrás), exit 6
proveedor eolas-v2: EolasEngineProvider (llm.py:344) → eolas_v2.inference_profile (cerrojo exclusivo,
   cambia de modelo si hace falta) → POST llama-server :8090 /v1/chat/completions (_post, llm.py:160)
celtia-v2: dos llamadas encadenadas (redactor → revisor) con cambio de modelo entre ambas (llm.py:436)
```

Observaciones del flujo:

- **El autofix solo actúa cuando la plantilla falla, antes de la IA.** Cuando fallan las rondas de `assist`, no hay autofix: se restaura todo y se pierde el mejor intento parcial (`assist.py:280-285 y 357-362`).
- **El criterio de éxito de `assist` es `verify().ok`** (`assist.py:430`). En `static` eso es `node --test` (`verify.py:331-332`) sobre pruebas que puede haber escrito el propio modelo. En `origin/main` no se comprueba la sintaxis del JS del navegador (la PR #45 lo añade) y **en ningún destino se ejecuta la app en un navegador ni se comprueban los requisitos del encargo**.
- **Evidencia (ESTADO-TRABAJO, rama `estado-2026-11-15-noche`, competición V1/V2):** «La verificación de Eolfi aprobó los cuatro, también los que no funcionan en el navegador». Los resultados del juez fueron 1/4, 9/9, 8/9 y 1/4.
- **Inferencia del código (`rsi_banco.py:51-55`, rama `rea-automejora`):** un `create` con salida ≠ 0 puntúa 0. Por tanto las muestras 7/9, 5/9 y 1/9 salieron con salida 0, es decir, **con verificación verde**. La varianza está entera en lo que la verificación no mide.

### 1.2 Chat con herramientas (chat.py:292 `agent_turn`)

- Hasta 8 rondas (`MAX_ROUNDS`, chat.py:25), con un plazo de 600 s por petición (chat.py:235). Peor caso: unos 80 min.
- En cada ronda se envían todas las herramientas permitidas: 6 `CHAT_TOOLS`, las de la app, las 14 `STATIC_TOOLS` de REA más 3 meta (`rea_buscar`, `rea_ayuda`, `rea_usar`) y `ejecutar_python`. Eso suma unas 30 definiciones con esquemas completos en cada petición a un 12B con 16k de contexto.
- Salida de cada herramienta: 6000 caracteres como máximo (chat.py:24).
- Si se agotan las rondas, se pide una respuesta final sin herramientas.
- Control de seguridad correcto: `ejecutar_python` solo corre en Docker sin red (`eolas_v2.py:1065-1089`) y REA aplica autorización por caso.
- **Falta un criterio objetivo de «respuesta correcta»:** la observación del RSI solo registra `ok` y error por herramienta.

### 1.3 Dónde se pierde tiempo

1. **Reintentos ciegos por plazo.** En `origin/main`, `_post` reintenta 3 veces ante `TimeoutError` (llm.py:157 y 187-190) con un plazo de 1800 s (llm.py:361 y 433). El peor caso son 4 × 30 min por llamada, y en celtia-v2 el doble. Esto ya anuló la primera competición V1/V2 (cancelada a los 30 min). Lo corrige la PR #43, **sin fusionar**.
2. **Generación de archivos completos.** El esquema obliga a devolver cada archivo entero (`OUTPUT_SCHEMA`, assist.py:54). En cada ronda de reparación se reenvía la respuesta anterior completa como turno del asistente (assist.py:433), así que crecen tanto la entrada como la salida.
3. **Carga y cambio de modelo.** `inference_profile` (eolas_v2.py:706) puede parar y arrancar llama-server. Con celtia-v2 cambia de modelo dos veces por ronda (llm.py:440-456).
4. **Razonamiento activado por defecto** (`"reasoning": True`, eolas_v2.py:143) y `max_tokens` 4096. La PR #43 lo deja en false y 8192.
5. **Desglose sin medir:** de los ~13 min por muestra del banco «tareas», solo se conocen los tiempos de la competición: 101 s para V2 Q4 en una ronda. Cada ronda guarda `generation_seconds`, `verification_seconds` y `provider_timings` (assist.py:411-417), pero `rsi_banco.py` no los registra. Por eso **no se sabe qué parte es carga del modelo, generación, verificación o el juez de Chrome**.

### 1.4 Dónde falla la calidad

- **Oráculo débil:** las pruebas son del propio modelo y no hay prueba funcional en navegador (§1.1).
- **Muestreo no determinista:** `temperature` 0.2 y `top_p` 0.95 (eolas_v2.py:140-141, llamacpp.py:190), **sin `seed`**. Con la misma configuración salen 7/9, 5/9 y 1/9.
- **Presupuesto de contexto incoherente tras la PR #43:** el perfil queda con `ctx` 16384 y `max_tokens` 8192, lo que deja unos 8k tokens de entrada. Sin embargo, `collect_context` admite 60 000 bytes (≈15-20k tokens). `max_tokens` solo se limita a `ctx` (llm.py:393), no a `ctx - prompt`. En proyectos medianos o grandes, o en la ronda 2 o 3, el prompt puede desbordarse o la salida cortarse (`finish_reason=length` → LLMError, llm.py:402).
- **Los fallos conocidos de la competición** (`\n` literal en el JS, «sin lógica JS») son justo los que no detecta la verificación.

## 2. Deuda

### 2.1 PR abiertas (comprobado con `gh` y `git merge-tree`)

| PR | Rama → base | Creada | Tamaño | Contra su base | Conflictos con otras PR |
|---|---|---|---|---|---|
| #19 | higiene-ruff-f → main | 14/11 | +98/-14 | **CONFLICTO** (ESTADO-TRABAJO.md, REGISTRO_LIMPIEZA.md) | — |
| #20 | prueba-independencia | 14/11 | +295/-14 | limpio | ninguno |
| #21 | cliente-api | 14/11 | +370/-1 | limpio | cli.py o PLAN_REA con #22-#31 y #46 |
| #22-#31 | firmware-rea, entorno-agente, mapa-app, grafo-llamadas, dotnet, android-clases, flutter, apple, devicetree, firmware-extraer | 14/11 | 153-838 líneas | limpias | **todas chocan entre sí** en `cli.py`, `rea_compuestas.py`, `tests/test_rea_compuestas.py` y `PLAN_REA.md`: todas añaden en los mismos puntos |
| #32 | wasm-rea | 14/11 | +444/-3 | limpio (gh: UNKNOWN) | rea_compuestas o tests con #22-#31; cli.py con #35 y #46 |
| #33 | swift-rea → **apple-rea** | 14/11 | +834/-1 | limpio | apilada sobre #29 |
| #35 | rea-kuna-wsl | 15/11 | +220/-31 | limpio | cli.py o rea_client con #22, #26, #31, #32 y #46 |
| #39 | eolas-vigilante | 15/11 | +165/-23 | **CONFLICTO** (eolas_v2, local_gpu, local-model.js y pruebas) | — **probablemente superada:** `origin/main` ya tiene `/slots` con clave e `idle_watchdog_pid` (local_gpu.py:170-183, eolas_v2.py:533 y 729) y `num_predict` en local-model.js (#40 y #41) |
| #43 | eolas-plazo-local | 15/11 | +152/-33 | limpio, 0 por detrás | ninguno |
| #44 | estado-2026-11-15-noche | 16/11 | +75/-3 (solo documentos) | limpio | ninguno |
| #45 | verificar-js-static | 16/11 | +46/-1 | limpio | ninguno |
| #46 | rea-automejora (RSI) | 16/11 | +1155/-14 | limpio | cli.py o PLAN_REA con #21-#24, #31, #32 y #35 |

**Orden recomendado de fusión:**

1. **#43** (plazo sin reintentos y reglaje de V2), **#45** (sintaxis JS) y **#20**. Ninguna choca con nada y todas tocan la calidad o el tiempo del bucle. Tras #43, revisa el presupuesto de contexto (§1.4).
2. **#44** (registro). Es solo documentación y choca con #19 en ESTADO y REGISTRO, así que conviene fusionarla antes de rehacer #19.
3. **#39:** compara su diff con main y **ciérrala si está superada**. No la fusiones a ciegas: tiene conflictos de código.
4. **#19:** rebásala o recréala desde main. Lo único que queda en conflicto son los documentos, y ESTADO-TRABAJO.md debería tener un solo dueño.
5. **REA #21-#32, #33 y #35:** fusiónalas en una **rama de integración** única (`rea-integracion`), una por una y resolviendo los añadidos en `cli.py`, `rea_compuestas.py`, `test_rea_compuestas.py` y `PLAN_REA.md`. Pasa la suite tras cada una y abre una sola PR, o bien fusiónalas en serie con rebase obligatorio. Orden sugerido: #21, #23, #24, #25, #26, #27, #28, #29, #33 (después de #29), #30, #22, #31, #32 y #35. Firmware y WSL van al final porque tocan `.gitattributes` y `rea_client.py`.
6. **#46 (RSI), la última:** choca con `cli.py` y `PLAN_REA.md` de las REA, y su evaluador necesita las correcciones estadísticas de §4 antes de adoptar nada de forma automática.

### 2.2 Ramas y worktrees

- 22 ramas remotas sin fusionar en `origin/main`, y 26 de 57 ramas locales.
- **31 worktrees:**
  - `D:\Eolfi-sim34` está desacoplado y es temporal según ESTADO;
  - `go-rust-rea`, `pyc-rea` y `senales-rea` comparten el commit `a9d2e5e` y no tienen PR abierta;
  - `avance-fases-2-3` no tiene PR abierta.
- Son candidatos para `REGISTRO_LIMPIEZA.md`. **No se ha borrado nada.**

### 2.3 Código duplicado y deuda técnica

- **Cuatro clientes HTTP distintos para el mismo llama-server**, cada uno con sus propios plazos, reintentos y autenticación:
  - `llm._post` (llm.py:160);
  - `chat._request` (chat.py:234, 600 s y sin reintentos);
  - las cargas útiles del banco en `eolas_v2.py` (1118 y 1515, `temperature` 0, `urlopen` con 300 s);
  - `local_gpu._get_json`.
- `_NoRedirect` está duplicado en `generador/llm.py` y en `sites/fetch.py`. `_read_json` y `_write_json` están repartidos entre `eolas_v2` y `rsi`.
- **Módulos monolíticos:** `eolas_v2.py` (2463 líneas: servidor, perfiles, cerrojos, bancos, lecciones), `server.py` (2099) y `cli.py` (1638).
- `tools/creation_benchmark.py:37` usa `ai_provider: 'nemo-moe'`, retirado el 14/11 (llm.py:12): **el banco está roto**. Tampoco repite muestras ni hace estadística. Es candidato a LIM, reemplazado por `rsi_banco.py`.
- **Avisos de ruff con riesgo real:**
  - PLW1510 (31): `subprocess.run` sin `check`, que hay que revisar uno a uno;
  - B023 (9): variable de bucle en clausuras;
  - BLE001 y S110 (14): `except` ciego o `pass`.

## 3. Verificación

- **Suite:** 678 pruebas recogidas en origin/main, en 66 archivos de `tests/`. Además hay e2e Playwright (`panel`, `observe`, `bridge-chat`, `live`) y 45 archivos de pruebas Node en los dos puentes.
- **CI (`.github/workflows/ci.yml`):**
  - pytest en {ubuntu, windows} × {3.10, 3.12};
  - `node --test` de bridge y vscode-bridge en ubuntu y windows;
  - e2e más axe en ubuntu.
- **Huecos de la CI:**
  - no ejecuta ruff (F ni nada);
  - no hace ninguna comprobación de calidad generativa;
  - no hay macOS;
  - no tiene caché de pip ni npm.
- **Sin ninguna referencia en `tests/`** (según `grep` de imports):
  - `generador/generators_backend.py` (1040 líneas), `generators_more.py` (1227), `generators_mobile.py`, `generators_desktop.py` y `generators_tauri.py`. Probablemente se ejercitan de forma indirecta vía `generators.py` y `create`, pero no tienen pruebas propias;
  - `observe/script.py` (401), `providers/java.py`, `providers/wasm.py` y `spec/contract.py`.
- **Partes críticas sin prueba significativa:**
  1. La calidad funcional del resultado de `create --ai`: no hay prueba que ejecute la app generada en un navegador. El juez `tools/rsi/juez-tareas.mjs` solo existe en la rama #46 y no está en la CI.
  2. El comportamiento de `_post` ante plazo agotado frente a errores 5xx (lo cambia la #43).
  3. El presupuesto prompt + salida frente a `ctx`.
  4. La reproducibilidad: ninguna prueba fija la semilla ni compara dos ejecuciones.
  5. `celtia-v2` con su perfil Mistral borrado (ESTADO: «el compuesto deja de funcionar»), que sigue en las `choices` de la CLI (cli.py:330, 339 y 347, `choices` de `--provider`).
  6. La estadística del evaluador RSI (`rsi.evaluar`) con bancos ruidosos.

## 4. Qué falta para que sea «autónomo verificable» (VAS)

| Pieza | Estado actual | Qué falta |
|---|---|---|
| Planificar | No hay plan: el encargo va directo a «archivos completos» | Fase de plan con criterios de aceptación explícitos y comprobables, en forma de checklist ejecutable, antes de generar |
| Generar | JSON con archivos completos y 3 rondas | Ediciones parciales o diffs; contexto ajustado a `ctx - max_tokens`; semilla fija |
| Verificar | `verify()` = instalar, compilar y pruebas propias (+ sintaxis JS con #45) | **Oráculo funcional independiente:** smoke en navegador (carga sin errores de consola, DOM esperado) para static, react, vue, svelte y next, y pruebas de aceptación derivadas del encargo, divididas en visibles y ocultas para no sobreajustar |
| Corregir | Error → misma conversación; si no hay verde, todo se pierde | Reparación con el fallo del oráculo funcional; quedarse con el **mejor intento** por puntuación, no todo o nada; autofix también tras `assist` |
| Bancos | «tareas» con n=3 y criterio «media +0,05 y mín. ≥ mín.» (`rsi.py:31-32, 356`) | Con σ≈0,3 por muestra (1/9-7/9) y n=3, la diferencia de medias tiene un error típico ≈0,25: **un margen de 0,05 aprueba por ruido** (~40 % de falsos positivos, estimado). Hace falta reducir la varianza (seed y `temperature` 0), usar pruebas pareadas con las mismas semillas, puntuar por comprobación, usar intervalos (bootstrap o Wilson) y mantener una batería de 5-10 encargos pequeños |
| Observabilidad | Tiempos por ronda en el informe de `assist`, sin agregar | Traza por fase (carga del modelo, prompt, generación, tok/s, verificación, juez) por muestra, guardada en JSONL y con un panel con p50/p90 |
| Memoria de casos | Lecciones por motor (`eolas-v2-lecciones.json`); evidencias en el store | Indexar los casos fallidos y corregidos (encargo, fallo del oráculo, parche que lo arregló) y recuperarlos como ejemplos en el prompt; medir el efecto con el banco |
| Motor V1/V2 | Selector manual `motor-local` (#41); competición de una sola muestra por motor | Elección por datos: el mismo banco repetido por motor y perfil, con la tasa de aprobados del oráculo, el tiempo p50 y su IC; enrutado por tamaño del encargo |

### Cinco mejoras de mayor impacto

| # | Mejora | Métrica |
|---|---|---|
| 1 | **Oráculo funcional en el bucle.** Integra el juez de Chrome (o un smoke de Playwright: consola sin errores, DOM y acciones del encargo) como paso de `verify` en los destinos web, y su fallo como error para la reparación | Brecha «verificación verde ↔ juez completo»: en la competición fue 2 de 4. **Objetivo: 0 % de falsos verdes en el banco** |
| 2 | **Determinismo y presupuesto:** `seed` fijo y `temperature` 0 en `assist`, y `max_tokens` + prompt ≤ `ctx` | Desviación típica de la puntuación del banco «tareas» con la misma configuración. Hoy ≈0,30; objetivo ≤0,10. También la tasa de `finish_reason=length` |
| 3 | **Evaluación estadística del RSI y de la elección V1/V2:** pares por semilla, ≥5 encargos × ≥3 semillas, IC 95 % por bootstrap, y adoptar solo si el límite inferior de la mejora es mayor que 0 | Tasa de falsos positivos del evaluador, estimada con una prueba A/A (la misma configuración contra sí misma). **Objetivo: ≤5 %** |
| 4 | **Telemetría por fase** en `rsi_banco` y `assist` (carga, generación, tok/s, verificación, juez), en JSONL | Tiempo por muestra p50 y p90, y desglose. Hoy ~13 min sin desglosar. Objetivo: conocer el 100 % del tiempo y bajar el p50 de 13 a ≤5 min (tras #43, reasoning false, sin cambios de modelo) |
| 5 | **Reparación con conservación del mejor intento** (puntuación del oráculo por ronda), autofix también tras `assist`, y memoria de casos corregidos como ejemplos | Puntuación media del banco y tasa de «a la primera» frente a «tras reparar». Objetivo: media ≥8/9 con IC estrecho |

### Cinco riesgos principales

1. `eolfi/generador/llm.py:157` y `:187-190`, junto con `:361`: hasta 3 reintentos tras un plazo de 1800 s, lo que da un peor caso de 2 h por llamada (4 h en celtia-v2). Mitigado en la #43, que sigue sin fusionar.
2. `eolfi/generador/assist.py:430` y `eolfi/generador/verify.py:331-332`: el éxito de la IA se decide con pruebas que escribe la propia IA y sin ejecutar la app. La competición dio 2 de 4 «verdes» rotos en el navegador.
3. `eolfi/llamacpp.py:190` y `eolfi/eolas_v2.py:140`: muestreo con `temperature` 0.2 y sin semilla, con una varianza de 1/9 a 7/9 con la misma configuración. Así cualquier comparación es ruido.
4. `eolfi/rsi.py:356` (rama `rea-automejora`, PR #46): el evaluador adopta si «media +0,05 y mínimo no peor» con n=3. Con el ruido actual aprobaría cambios inútiles o dañinos.
5. `eolfi/generador/assist.py:268`, junto con `llm.py:49` y `llm.py:393`: un contexto de 60 KB más el historial de rondas frente a ctx 16384 y `max_tokens` 8192 (tras la #43). Riesgo de desbordamiento o corte por longitud en la ronda 2-3 o en proyectos medianos.

Otros riesgos:

- `celtia-v2` sigue ofrecido (cli.py:330, 339 y 347, `choices` de `--provider`) con el redactor Mistral borrado.
- `tools/creation_benchmark.py:37` usa un proveedor retirado.
- En el árbol de trabajo `D:\Eolfi` hay commits sin subir y queda 12 commits por detrás de main.
- 31 worktrees vivos.
