# Auditoría del proyecto Eolas y plan de implementación (15/11/2026)

Solo auditoría: no se editó código, no hubo commits, no se cargó ningún modelo y no se ejecutó ningún binario objetivo.
Las únicas consultas al servicio fueron de lectura (`/api/version`, `/api/tags`, `/api/ps` en 11435; `/health`, `/v1/models` y `/slots` en 8090, sin clave).

## 1. Qué es «el proyecto Eolas»: los dos candidatos, y están acoplados

| Pieza | Fuentes | Qué hace |
|---|---|---|
| **Runtime Eolas (V1)** | `D:\celtiaia\Eolas Base` (Go, ~30 k líneas; `cmd/eolas`, `internal/*`) | API tipo Ollama en `127.0.0.1:11435`. Backend `llama`: lanza `D:\EOLAS-BASE\llama\llama-server.exe` por cada modelo. Lo arranca `D:\celtiaia\launch-eolas.ps1` (supervisor). |
| **Eolas V2 (Eolfi)** | `D:\Eolfi\eolfi\eolas_v2.py`, `eolfi/local_gpu.py`, `eolfi/generador/llm.py` (`eolas-v2`) | Eolfi gestiona su propio llama-server en 8090, con clave de API y perfiles GGUF. |
| **Integración** | `eolfi/vscode-bridge/local-model.js`, `llm.py` (`OllamaProvider`) | La extensión usa solo V1 (11435, `gemma-4-12b-it:latest`) y se niega a usarlo si V2 tiene la GPU. |

Audito los dos, porque comparten GPU (8 GB) y llama.cpp, y los defectos principales están en la frontera entre ambos.

## 2. Objetivos: identidad, cobertura y límites

| Objetivo | SHA-256 | Proveedor / versión | Evidencia |
|---|---|---|---|
| `D:\celtiaia\runtime\eolas\eolas.exe` (el que corre: PID 4472 en 11435) | `f5e8e1a40eca140bee8498937a1fa1fa6a2ba7d968596cf32866d0c012ba51bb` (16 719 360 B) | REA `go-build-info` v1: go1.27.0, `eolas-base v0.0.0-20261108161019-bea1f4d31914+dirty`, `vcs.modified=true`, CGO=1, trimpath | `ev_40e6ef34d94e5fa9584aefbfa206c74941cd0b0b46f018ad30d0e7f2eb9c6c71` |
| `D:\celtiaia\Eolas Base\eolas.exe` (copia distinta, no es la que corre) | `3db0116c7462ff51666d6fe76d2c47aa5efdcd35cedfcf68da347de421ab249d` | solo hash | — |
| `D:\EOLAS-BASE\llama\llama-server.exe` | `e339d7a3aad4bb0be10267a447e125db1f0a7db501eca08cddd8e4adcbadce08` (**9 216 B**: lanzador; el código está en `llama-server-impl.dll`) | REA `rea-pe-resources` v1: solo el manifiesto RT_MANIFEST; `llama-release.json`: tag `b11968`, CUDA 12.4 | `ev_31c88bade7af2700d603693b04211b7ff8cd0590df3b3708de2900c0d4a1cb8c` |
| `llama-server-impl.dll` / `llama.dll` / `ggml-cuda.dll` / `llama-common.dll` / `ggml-base.dll` | `33b4bf84…0f88` / `4a104d75…d128` / `47ccd40f…64c0` / `bee6bec2…85b0` / `fb09f458…ae291` | sha256sum | — |
| Almacén de modelos `D:/celtiaia/runtime/eolas/models` | manifiestos leídos como datos | — | — |

**Cobertura:** lectura de fuentes de `internal/server` (generate.go, server.go), `internal/prompt/parse.go`, `internal/sched` (parámetros), `cmd/eolas/config.go`; `local-model.js` completo; `llm.py` 200-415; `eolas_v2.py` 440-560 y 639-662; `local_gpu.py` 28-150; manifiestos y blobs pequeños del almacén.
**Límites:** no se revisó `internal/EolasV1` (runtime tensorial nativo), `agent`, `registry`, `store` ni la web CELTIAIA/Fios. REA solo leyó metadatos (build info Go y recursos PE); **no** decompiló ni analizó semántica de los DLL de llama.cpp. Desconocido: que el zip `b11968` sea el oficial (no hay checksum guardado y no abrí red), y el valor por defecto de `--slots` en ese build (la cadena es `default: %s`).

## 3. Comprobaciones ejecutadas (esta sesión)

| Comando | Resultado |
|---|---|
| `python -m pytest -q tests/test_eolas_v2.py tests/test_local_gpu.py` (D:\Eolfi, Python 3.12.10) | 61 passed |
| `node --test test/local-model.test.js test/eolas-starter.test.js test/eolas-starter-launcher.test.js` (vscode-bridge) | 17/17 |
| `go vet ./...` (Eolas Base, go1.27.0) | código de salida 0 |
| `go test ./internal/{prompt,server,sched,options,store,runner}/...` | 6/6 ok |
| `curl http://127.0.0.1:8090/slots` sin clave | **HTTP 401 Invalid API Key** |

No se ejecutó la suite completa de cierre de AGENTS.md (ni `pytest` entero, ni bridge entero, ni e2e): **NO VERIFICADO** para este informe, que no cambia código.

## 4. Plan priorizado

Esfuerzo: S ≤ 1 h, M ≤ 1 día, L > 1 día.

### P0: defectos presentes

**P0-1. Eolas V2 huérfano ocupando la GPU desde hace ~44 h: bloquea la extensión.**
- Evidencia: `llama-server` PID 10280 en 8090 (Gemma Q5, `-c 32000 -ngl 8`), creado el 13/11/2026 20:32:59; su padre (PID 11816) ya no existe; working set 6,5 GB, privada ~10 GB. `~/.eolfi/eolas-v2.runtime.json` apunta a él y **no** hay ningún proceso `eolfi.local_gpu watch`. `local-model.js:179-185` lanza un error si `eolasV2Holder()` ve el PID vivo, así que **@eolfi en VS Code no puede usar Eolas ahora mismo**. Si algún cliente carga Gemma en 11435 sin pasar por esa guardia, se repite el «bad allocation» del 11-12/11.
- Acción inmediata (operativa; necesita el visto bueno del titular): `python -m eolfi eolas-v2 stop`, y comprobar luego que 8090 no escucha y que `runtime.json` desaparece.
- Impacto: alto. Esfuerzo: S.

**P0-2. El vigilante de inactividad no puede ver la actividad: `/slots` sin clave.**
- Evidencia: `local_gpu.py:78` llama a `_get_json(f"http://127.0.0.1:{port}/slots")` y `_get_json` (`local_gpu.py:36-41`) no envía `Authorization`. El servidor se arranca con `--api-key-file`, y `/slots` responde 401 (comprobado hoy). Resultado: `slots=[]`, `busy=False` y `tasks=()` siempre, así que `watch()` (`local_gpu.py:129-144`) para el servidor 15 min después de arrancar, haya uso o no. Al tomar el candado (`eolas_v2.py:641`) espera a que termine la inferencia en curso, pero corta las conversaciones.
- Corrección: usar `eolas_v2.auth_headers()` en esa petición; si `/slots` no está disponible, actuar a ciegas de forma explícita (registrar y no parar, o parar con aviso, según decida el titular).
- Comprobación de cierre: prueba unitaria con un servidor falso que exija Bearer en `/slots`; en vivo, `curl -H "Authorization: Bearer …" /slots` → 200, y el vigilante no para el servidor durante una conversación de más de 15 min.
- Impacto: alto. Esfuerzo: S.

**P0-3. El vigilante muere con la sesión que lo lanzó; el servidor no.**
- Evidencia: el servidor se lanza con `CREATE_BREAKAWAY_FROM_JOB` (`eolas_v2.py:486-491`); el vigilante, sin él (`local_gpu.py:121-125`). Un Job Object con kill-on-close (sesión de agente o terminal de VS Code, ya documentado en CONTINUIDAD del 06/11) mata al vigilante y deja vivo el llama-server. Esto encaja con lo observado en P0-1 (padre muerto, sin vigilante): es PLAUSIBLE, no reproducido.
- Además, `_start_locked` sale pronto si el servidor ya corre (`eolas_v2.py:464-466`) y nunca vuelve a armar un vigilante perdido; `runtime.json` no guarda el PID del vigilante (`eolas_v2.py:493-494` frente a `:509-510`).
- Corrección: el mismo `breakaway` en el vigilante; guardar `idle_watchdog_pid` en `runtime.json`; volver a armarlo en `_start_locked`/`status()` si falta.
- Comprobación: prueba con `popen` simulado que verifique los flags; en vivo, arrancar V2 desde una terminal, cerrar la terminal y comprobar que el vigilante sigue y para a los 15 min.
- Impacto: alto. Esfuerzo: S-M.

### P1: correcciones importantes

**P1-1. Los modelos Gemma del almacén fijan `num_ctx: 2048`: esta es la causa real de que `num_ctx` sea obligatorio.**
- Evidencia: los manifiestos `gemma-4-12b-it/latest` y `gemma-4-12b-it/q5_k_m` incluyen la capa `application/vnd.ollama.image.params` `sha256:b413499b7c17…`, cuyo contenido es `{"num_ctx":2048,"temperature":0.2}`. En `generate.go:269`, `options.Merge(defaults, j.Model.Params, j.Options)` deja que esa capa gane al valor del servidor (`EOLAS_CONTEXT_LENGTH=32768`, `launch-eolas.ps1:154`; `sched.go:230`). Mistral no tiene esa capa. No encontré el Modelfile de origen: es una incógnita.
- Impacto: cualquier cliente que omita `num_ctx` (CELTIAIA/Fios, `eolas run`, herramientas de terceros) trabaja con 2048 y recorta historial (`fitContextImages`).
- Corrección: recrear las dos etiquetas con `PARAMETER num_ctx 32768`, o quitar el parámetro; mantener el envío explícito en los clientes.
- Comprobación: `POST /api/show` sin `num_ctx` en `parameters`; tras una carga autorizada sin `num_ctx`, `/api/ps` debe indicar un contexto de 32768. **NO VERIFICADO**: exige cargar el modelo.
- Esfuerzo: S.

**P1-2. El binario en servicio no es reproducible y Eolas Base tiene dos historiales.**
- Evidencia: REA `ev_40e6ef34…` muestra `vcs.modified=true` sobre `bea1f4d`, y `runtime/eolas/build.json` registra `sourceDirty: true`. `Eolas Base` tiene su propio `.git` (HEAD `bea1f4d`, con `internal/EolasV1/mappedfile_windows.go` modificado y sin confirmar) y, a la vez, `D:\celtiaia` sigue 555 archivos de esa carpeta. Ese mismo arreglo ya está confirmado en celtiaia como `63623ce` («go vet unsafeptr»). Hay además dos `eolas.exe` distintos (ver la tabla del §2).
- Corrección: elegir una sola fuente (submódulo o repo único), confirmar el arreglo en esa fuente, recompilar desde un árbol limpio y actualizar `build.json` con el SHA nuevo.
- Comprobación: `inspect_go_binary` con `vcs.modified=false` y la revisión esperada; `go vet` y `go test ./...` en verde.
- Esfuerzo: M.

**P1-3. `think_budget` cierra el razonamiento de Gemma 4 con `</think>`.**
- Evidencia: `generate.go:434` define `thinkBudgetClose = "…</think>\n\n"` y `generate.go:367-382` lo añade al prompt de continuación. Gemma 4 abre con `<|channel>thought` y cierra con `<channel|>` (`parse.go:12-13`). El analizador de Eolas acepta las dos formas, pero el modelo recibe un cierre que no es el suyo: puede seguir razonando o mezclarlo en la respuesta. PLAUSIBLE.
- Corrección: elegir el cierre según el marcador de apertura detectado (`tp`).
- Comprobación: una prueba unitaria en `internal/server` con un backend falso que reciba `<channel|>`; una prueba en vivo con `think_budget` (NO VERIFICADO: exige carga).
- Esfuerzo: S.

**P1-4. La extensión no limita la generación con Eolas.**
- Evidencia: `eolasOptions` (`local-model.js:49-51`) solo envía `num_ctx` y `temperature`; `max_tokens` se descarta (`:201`, `:238`), y el valor por defecto del servidor es `num_predict: -1` (`generate.go:26`). Sin `enable_thinking` en la configuración, `eolasThink` no envía `think`, y Gemma razona por defecto, que es lento (`local-model.js:53-58`). Con llama-server propio sí se limita (`max_tokens` 4000/6000).
- Corrección: mapear `max_tokens` → `options.num_predict`, y usar `think:false` por defecto en `complete()` (revisión), salvo que se configure otra cosa.
- Comprobación: pruebas en `local-model.test.js` sobre el cuerpo enviado; medir tiempos en vivo (NO VERIFICADO).
- Esfuerzo: S.

**P1-5. La extensión se niega a usar Eolas en lugar de liberar un V2 ocioso.**
- Evidencia: `llm.py:220-228` llama a `free_for_eolas()`, que para V2 si está ocioso (`local_gpu.py:101-113`); `local-model.js:179-185` solo lanza el error. Por eso P0-1 deja la extensión inutilizable.
- Corrección: el mismo comportamiento (parar V2 ocioso consultando `/slots` con clave, o llamar a `python -m eolfi eolas-v2 stop`), tras decisión del titular.
- Esfuerzo: M. Depende de P0-2.

### P2: mejoras y deuda

| Id | Hallazgo y evidencia | Acción | Comprobación | Esf. |
|---|---|---|---|---|
| P2-1 | Eolas 11435 sin clave: cualquier proceso local puede `DELETE /api/delete`, `/api/create`, `/api/pull` (`server.go:64-71`). El soporte existe (`server.go:118-126`, comparación en tiempo constante) y Host/Origin están protegidos (`:96-107`). | Activar `EOLAS_API_KEY` y enviarla desde `local-model.js`, `llm.py` y la web (**corregido el 15/11:** el launcher no la filtraba de la web, que ya la conservaba; el que no la recibía era el proceso de Eolas, así que el servidor nunca la exigía). | 401 sin clave, 200 con clave, e2e 8/8 | M |
| P2-2 | La procedencia de llama.cpp `b11968` no es verificable: `llama-release.json` no guarda el hash del zip. | Guardar el SHA-256 del zip y de los binarios, y compararlo con la publicación oficial (necesita red autorizada). | Hash igual al publicado | S |
| P2-3 | Comprobaciones de vida por PID, expuestas a la reutilización de PID (`local-model.js:103-111`, `eolas_v2._pid_alive`). | Contrastar también la salud del puerto, la línea de órdenes o la hora de inicio. | Prueba con `runtime.json` caducado y PID reutilizado | S |
| P2-4 | `inference_profile` retiene el candado exclusivo durante toda la inferencia (`eolas_v2.py:639-649`; timeout 1800 s en `llm.py:361`): `stop`, `switch` y el vigilante esperan hasta 30 min. | Documentarlo o mostrarlo en la interfaz («esperando a que termine»); valorar un candado de lectura. | — | M |
| P2-5 | El análisis de llamadas Gemma en `local-model.js:16-44` posiblemente sobra: el runtime ya analiza `<|tool_call>` (`internal/prompt/gemma_toolcall.go`, en el historial desde `ab7a107`, que precede a `bea1f4d`). El comentario de la línea 16 se refiere al binario del 03/11. | Conservar el respaldo y corregir el comentario; verificar en vivo que `message.tool_calls` llega estructurado. | NO VERIFICADO (exige carga) | S |
| P2-6 | Manifiestos: la capa Q4 se refiere a sí misma (`"from":"gemma-4-12b-it:latest"`); las configuraciones dicen `"os":"linux"` en Windows; `q5_k_m` y `latest` comparten la misma capa de parámetros (ligado a P1-1). | Normalizar al recrear las etiquetas (P1-1). | `/api/show` coherente | S |
| P2-7 | Hay pruebas, pero no cubren los fallos de P0: los tests simulan `/slots` sin exigir clave y no comprueban los flags de Popen. | Añadir pruebas de regresión para P0-2 y P0-3. | pytest en verde con las nuevas pruebas | S |
| P2-8 | Dos copias de llama.cpp (`D:\HYDRA-BASE\llama`, `D:\EOLAS-BASE\llama`) y configuración antigua en 8090 (LIM-027, `~/.eolfi/llamacpp.json`); 8090 lo usa también V2. | Decidir con el registro de limpieza; no borrar ahora. | — | S |

### Pendientes ya registrados que siguen abiertos
- `ESTADO-TRABAJO.md:51`: un proyecto real con la IA real de Eolas, sin probar (**NO VERIFICADO**).
- CONTINUIDAD (06/11): el backend nativo `eolas` rechaza herramientas con Gemma («Gemma template does not support tools or thinking»); decisión pendiente sobre el límite de 9600 MiB del Job y el error CUDA 208 en modo nativo.
- `ESTADO-TRABAJO.md:199, 217`: caídas de Gemma dentro de Eolas («Eolas lo relanza solo») sin causa raíz.
- CONTINUIDAD (08/11): subrecursos del iframe de vista previa con `SameSite=Strict`, sin verificar en navegador.
- REGISTRO_LIMPIEZA: LIM-025 (`makeLlamaStarter`), LIM-026 (textos de `package.json`) y LIM-027 (configuración en 8090) tocan esta integración.

## 5. NO VERIFICADO en esta auditoría
- Cualquier comportamiento de inferencia: carga, contexto efectivo, `think`, `think_budget` y llamadas a herramientas estructuradas. Exige cargar un modelo, y no estaba autorizado.
- La causa de P0-3 (Job Object): inferida de la evidencia de procesos, no reproducida.
- La autenticidad de llama.cpp `b11968` frente a la publicación oficial (no abrí red).
- El origen de la capa `num_ctx: 2048` (no encontré el Modelfile).
- La suite de cierre completa de AGENTS.md (pytest entero, bridge entero, e2e).
- `internal/EolasV1`, `agent`, `registry`, la web CELTIAIA y Fios: fuera de la cobertura de esta pasada.

## 6. Orden recomendado
1. P0-1 (parar el huérfano, con OK del titular). 2. P0-2 + P0-3 + P2-7 en una PR de Eolfi. 3. P1-4 + P1-5 en la extensión. 4. P1-1 (recrear etiquetas, con carga autorizada para comprobar). 5. P1-2 + P1-3 en Eolas Base, con recompilación limpia. 6. P2 según prioridad comercial (P2-1 primero).

## 7. Estado al cierre (15/11/2026, noche)

| Punto | Estado | Dónde / prueba |
|---|---|---|
| P0-1 | Hecho | Huérfano parado (PID 10280) con OK del titular. |
| P0-2, P0-3, P2-7 | Hecho | Eolfi PR #40 (216f65e): `/slots` con clave, breakaway del Job, re-armado con testigo; pruebas de regresión. En vivo: el vigilante paró V2 solo. |
| P1-1 | Hecho | Etiquetas `latest` y `q5_k_m` recreadas con `num_ctx` 32768. En vivo: `context_length` 32768 sin `num_ctx`. |
| P1-2 | Hecho | Fuente única en celtiaia (`Eolas Base`, historial propio renombrado y conservado); `eolas.exe` reconstruido de eda8fe5, `vcs.modified=false`, SHA-256 `5d3b6dbd…6c96`. |
| P1-3 | Hecho | celtiaia eda8fe5: cierre con `<channel|>`. En vivo: `think_budget` corta y la respuesta llega aparte. |
| P1-4 | Hecho | Eolfi 57a7fba (PR #41): `num_predict` desde `max_tokens`. En vivo con `max_tokens` 32. |
| P1-5 | Hecho | Eolfi PR #41 (`c52528e`): la extensión llama a `python -m eolfi.local_gpu free-for-eolas` antes de usar V1; si V2 está respondiendo, explica el motivo. Pruebas JS y pytest. |
| P2-1 | Hecho | celtiaia PR #5 (`4cb6b78`, con b21d026: launcher crea `runtime\eolas\api.key` y la pasa a Eolas; Fios `localKeys.ts`); Eolfi (CLI, generador, guardia de GPU, extensión). En vivo: 401 sin clave o con clave mala (también `DELETE /api/delete`), 200 con clave, `/` abierto; web, Fios (`smoke live`), generador y extensión responden con clave. |
| P2-2 | Hecho | Release oficial ggml-org/llama.cpp b11968 (28/10/2026) descargada el 15/11. Los zip `llama-b11968-bin-win-cuda-12.4-x64.zip` (`10edd9e2…6fcd`) y `cudart-llama-bin-win-cuda-12.4-x64.zip` (`8c79a9b2…e1d6`) coinciden con el digest de GitHub. Sus 56 archivos son idénticos, por SHA-256, a los 57 de la lista de celtiaia `docs/audit/llama-b11968-win-cuda-12.4-x64.sha256`; el 57.º es `llama-release.json`, el registro local de la instalación. Las copias de EOLAS-BASE y HYDRA-BASE son, por tanto, las oficiales. |
| P2-3 | Hecho | Eolfi 57a7fba: PID con hora de inicio (`pid_started`). |
| P2-4 | Hecho | Eolfi 57a7fba: candado con propósito; el vigilante no muere con `EolasBusy`. |
| P2-5 | Hecho | Comentario corregido; en vivo `tool_calls` llega estructurado. |
| P2-6 | Documentado, sin cambio | `os: linux` es el formato tipo Ollama de `store.CreateFromLayers`; `from` es procedencia informativa. Ver celtiaia `docs/audit/EOLAS-V1-V2-2026-11-15.md`. |
| P2-8 | Registrado | LIM-030 (copia `D:\HYDRA-BASE\llama`, idéntica) junto a LIM-027. Fios ya no pisa Eolas V2 en 8090. Nada borrado. |

**Motor elegido:** los dos quedan operativos. El predeterminado del código es Eolas V2 (no depende de CELTIAIA). En este
equipo se fija Eolas V1 (`python -m eolfi motor-local eolas-v1`, archivo `~/.eolfi/motor-local.json`): una sola cola
y un solo modelo para la web, Fios y Eolfi, ahora reparado y con clave. Se cambia con `python -m eolfi motor-local eolas-v2`.

**Siguen abiertos:** los pendientes de la sección 4 que no son de esta auditoría (proyecto real con la IA de Eolas, backend
nativo con herramientas, caídas de Gemma sin causa raíz, iframe `SameSite`), y nada más de llama.cpp: ya se comparó con la release oficial.

**Actualización (16/11/2026):**
- Caídas de Gemma: causa (caché de prompts en RAM contra el Job de 9600 MiB) corregida con `--cache-ram 1024` (CeltiaIA#6), verificada en vivo; sin caídas en las ejecuciones de la competición.
- Backend nativo: con el binario actual, la llamada a herramientas y el error CUDA 208 no se reproducen dentro del Job. La memoria fijada sin límite se corrige en CeltiaIA#9 (`EOLAS_PINNED_HOST_MB` y caída a copias desde el mapeo). El Job sigue en 9600 MiB.
- Iframe `SameSite`: corregido con un token en la ruta (CeltiaIA#8); E2E en vivo 14/14.
- Caché KV auto: con `num_gpu` explícito elegía f16 aunque no cupiera (CeltiaIA#10); 27,7 → 34,2 tok/s en Gemma Q4.
- Competición V1/V2 (mismo encargo, 16k, 8192 tokens): V2 Q4_K_M 41,6 tok/s y 101 s; V1 Q5 9/9 en el juez funcional. Detalle en `ESTADO-TRABAJO.md`.

**Publicación (15/11, 22:10):**
- Eolfi https://github.com/CeltiaIA/Eolfi/pull/41 fusionada (`c52528e`), CI en verde.
- celtiaia https://github.com/CeltiaIA/CeltiaIA/pull/5 fusionada (`4cb6b78`, commits eda8fe5 y b21d026). Su CI de Windows **no se ejecutó**: GitHub no arrancó el job por pagos fallidos o límite de gasto de la cuenta. Está respaldada solo por las pruebas locales (`npm test`, typecheck y smoke de Fios, Go). Cuando se resuelva la facturación: `gh run rerun 43761896172 --repo CeltiaIA/CeltiaIA`.
- `D:\celtiaia` (el que se ejecuta) tiene los mismos archivos que `origin/main`, como cambios sin commit; falta actualizar ese árbol (ver ESTADO-TRABAJO).
