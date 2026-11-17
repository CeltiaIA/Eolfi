# Auditoría de solo lectura de Eolas V1 para el VAS (Sistema Autónomo Verificable)

Fecha: 16/11/2026. Alcance: `D:\celtiaia` en la rama `main` (copia de trabajo con `launch-eolas.ps1` y un documento de auditoría modificados y sin commit), módulo anidado `D:\celtiaia\Eolas Base` (`module eolas-base`), registro del runner en `runtime\eolas\logs` (solo lectura con grep). No se modificó ningún archivo del repositorio, no se arrancó ni se paró ningún servidor, no se cargó ningún modelo y no se leyó `api.key`.

Binario desplegado: `runtime\eolas\eolas.exe`, SHA-256 `5d3b6dbd…6e96`, según `build.json` compilado desde `eda8fe5`. `git diff eda8fe5 HEAD -- "Eolas Base"` sale vacío, así que el código Go auditado coincide con el del binario en ejecución (PID 1852 en 127.0.0.1:11435, supervisor 16360, backend `llama`).

---

## 1. Mapa de arquitectura

### 1.1 Módulos

| Ruta | Función |
|---|---|
| `D:\celtiaia\go.mod` (`module celtiaia`) | Solo contiene `internal/tensor`. **No incluye Eolas Base**, que tiene su propio `go.mod` |
| `Eolas Base\cmd\eolas` | CLI y servidor: `serve`, `run`, `ps`, `plan`, `bench`, `doctor`, `create`, `pull`, `import`… Configuración por entorno en `config.go` y servicio de Windows en `service_windows.go` |
| `internal/server` | API HTTP: `/api/*` compatible con Ollama, `/v1/*` de OpenAI, `/v1/messages` de Anthropic, `/api/eolas/{gpus,plan,status}` y `/metrics`. Incluye middleware de Host, Origin y clave |
| `internal/sched` | Planificador de modelos: cola (`MaxQueue`), una sola carga a la vez (`loadGate`), `keep_alive`, expulsión LRU y clave de reutilización del runner |
| `internal/plan` | Estimación de VRAM y capas (`-ngl`), KV `auto` (f16 o q8_0) y `tensor-split` |
| `internal/gpu` | `nvidia-smi` con un tiempo límite de 5 s, más la simulación `EOLAS_GPU_VRAM_MB` |
| `internal/runner` | Proceso hijo `llama-server` en un puerto de loopback aleatorio. Comprobación `/health`, flujo SSE de `/completion` y lectura de buffers del registro (`memory.go`) |
| `internal/EolasV1` (paquete `tensor`) | Motor nativo en proceso (backend `eolas`). Con `Backend=llama` no se usa en las peticiones |
| `internal/eolas.cpp` | Worker experimental `eolas.cpp` (solo qwen3) |
| `internal/store`, `registry`, `modelfile`, `gguf`, `prompt`, `options`, `agent` | Catálogo y cuotas, registro remoto, Modelfile, lector GGUF, plantillas y análisis de herramientas, opciones y agente CLI |
| `launch-eolas.ps1` | Supervisor: Job de Windows de 9600 MiB (`JOB_OBJECT_LIMIT_JOB_MEMORY` 0x200 más `KILL_ON_JOB_CLOSE`), verificación del SHA del binario, clave de API, variables `EOLAS_*`, arranque de `eolas.exe serve` y de `node server.mjs` (web 5176-5185) y reinicio con un límite de 5 por cada 10 minutos |

### 1.2 Flujo de una petición (`/api/chat` desde la web o Fios)

1. `server.middleware` (`server.go:93-131`) comprueba la cabecera Host (protección contra DNS rebinding), el Origin y la clave (`Authorization: Bearer` o `X-Api-Key`, comparada con `subtle.ConstantTimeCompare`).
2. `generate.go:267 run()` fusiona las opciones (por defecto, Modelfile y petición) y llama a `Sched.Acquire` (`generate.go:284`).
3. `sched.Acquire` (`sched.go:258`) controla la cola, reutiliza el runner si coincide la clave (`sched.go:250-255`: num_ctx, parallel, num_gpu, kv, fa, spec, mmap, mlock, main_gpu, batch, threads) y, si no coincide, ejecuta `load()`.
4. `sched.load` (`sched.go:342`) toma `loadGate`, expulsa modelos inactivos, llama a `s.GPUs()` (es decir, `gpu.Discover` sin límite) y después a `plan.Estimate`. Si el modelo no cabe entero, expulsa otros modelos y vuelve a planificar. Por último crea `runner.Config` y llama a `runner.Start`.
5. `runner.Start` (`runner.go:127`) lanza `llama-server -m … --host 127.0.0.1 --port <libre> -c <ctx*np> -ngl <plan> -fa on -ctk/-ctv …` más `EOLAS_LLAMA_ARGS` (incluye `--cache-ram 1024`) y sondea `/health` cada 150 ms hasta `LoadTimeout` (5 minutos).
6. `Completion` (`runner.go:313`) hace POST a `/completion` con `stream:true` y `cache_prompt:true` y reenvía los fragmentos. Las métricas por petición (`eval_count` y `eval_duration`) salen de `timings`.
7. `release()` aplica `keep_alive`: con 0 descarga el modelo, con un valor negativo lo mantiene indefinidamente y con un valor positivo programa un temporizador.

### 1.3 Configuración efectiva (lanzador y `config.go`)

| Variable | Valor del lanzador | Uso real en el código |
|---|---|---|
| `EOLAS_BACKEND` | `llama` | `config.go:220` |
| `EOLAS_HOST` | `127.0.0.1:11435` | `config.go:48`. Fuera de loopback exige clave (`config.go:40`) |
| `EOLAS_API_KEY` | `runtime\eolas\api.key` (salvo con `-NoApiKey`) | `main.go:250,254` |
| `EOLAS_VRAM_LIMIT_MB` | 5200 por defecto (cambio sin commit) | **Solo en `settingsFor` para elegir el perfil (`config.go:212`). No llega al planificador de carga.** Ver R1 |
| `EOLAS_GPU_OVERHEAD_MB` | 512 | `Settings.Overhead` → `plan.Request.Overhead` |
| `EOLAS_VRAM_MARGIN` | 0.15 | `plan.go:260` (se aplica sobre la VRAM libre real) |
| `EOLAS_CONTEXT_LENGTH` | 32768 | `NumCtx`. Además, `server.mjs` envía `num_ctx` con el mismo valor |
| `EOLAS_KV_CACHE_TYPE` | (sin fijar) → perfil `rtx3060ti` = `auto` | `plan.go:116` |
| `EOLAS_LLAMA_ARGS` | `--cache-ram 1024` (sin commit en main; es el PR #6) | `config.go:215` |
| `EOLAS_MAX_LOADED_MODELS`, `NUM_PARALLEL`, `MAX_QUEUE`, `KEEP_ALIVE` | 1, 1, 8, 5m | sched |
| `EOLAS_FLASH_ATTENTION`, `SPEC_TYPE` | true, none | sched y runner |
| `EOLAS_DEVICE`, `EOLAS_GPU_STREAM` | cuda, 1 | Solo para el motor nativo (`EolasV1`) |
| `EOLAS_LOAD_TIMEOUT` | (5 min) | `runner.go:157` |

### 1.4 Puntos de fallo

- Que `nvidia-smi` falle o tarde más de 5 s: se planifica sin GPU (R4).
- Que `llama-server` agote memoria al cargar (cudaMalloc del KV) o en ejecución (`bad allocation` y `GGML_ASSERT`). Ambos casos están en el registro (sección 3).
- Que `llama-server` muera con el modelo cargado: solo se detecta en el siguiente `Acquire` mediante `Alive()`, y la petición en curso falla sin reintento.
- Que `eolas.exe` muera: lo reinicia el supervisor, con un máximo de 5 veces en 10 minutos (`launch-eolas.ps1:227-243`). Después el supervisor se rinde y el bloque `finally` mata todo.
- Que el Job supere 9600 MiB, sumando eolas, llama-server, node y la caché de prompts de llama.
- Thrashing de recargas cuando dos clientes envían opciones distintas (R6).

---

## 2. Calidad y verificación

### 2.1 Comandos ejecutados (Go 1.27.0 windows/amd64, `GOPROXY=off`, sin red)

| Comando | Directorio | Resultado |
|---|---|---|
| `go vet ./...` | `D:\celtiaia` | **FALLA (exit 1)**: `malformed import path "celtiaia/runtime/eolas/respaldo-2026-11-15/copias-sin-seguimiento/Eolas Base/internal/prompt": invalid char ' '`. La copia de seguridad dentro de `runtime/` (con un espacio en la ruta) rompe `./...` del módulo raíz. Es un fallo de entorno o higiene, no del código del producto |
| `go test ./...` | `D:\celtiaia` | **FALLA (exit 1)** por el mismo motivo (`setup failed`). `celtiaia/internal/tensor` sale **ok** |
| `go vet ./internal/...` | `D:\celtiaia` | ok (exit 0) |
| `go vet ./...` | `D:\celtiaia\Eolas Base` | **ok (exit 0)** |
| `go test -count=1 ./...` | `D:\celtiaia\Eolas Base` | **ok (exit 0)**: 23 paquetes en verde (`tools/fakellama` no tiene pruebas) |
| `go test -count=1 -v ./...` | `Eolas Base` | 344 pruebas de nivel superior en PASS, **14 en SKIP** y 0 en FAIL |
| `go test -race -count=1 ./internal/{sched,runner,server,plan}` | `Eolas Base` | **ok (exit 0)**, con CGO y el gcc de WinLibs |
| `go test -cover …` | `Eolas Base` | plan 81,7 %, runner 89,6 %, sched 76,0 %, server 75,0 %, cmd/eolas 51,0 %, gpu 83,9 %, options 100 % |

Conclusión: **el módulo Eolas Base está VERIFICADO con pruebas unitarias y de contrato que usan dobles** (fakellama y GPU simulada). El comando literal pedido, `go vet/test ./...` desde `D:\celtiaia`, **falla por el entorno** (la copia de seguridad en `runtime/`) y no cubre Eolas Base, porque es un módulo anidado. La CI o el procedimiento deben ejecutar `go test ./...` **dentro de `Eolas Base`**. **NO VERIFICADO**: el comportamiento con GPU real y llama-server real, porque las 14 pruebas que se saltan son justo las de GPU, modelo real y velocidad (`TestRealDecodeSpeed`, `TestGemma4ChatEndToEnd`, `TestGPUGEMVBandwidth`, etc.) y no se cargaron modelos por restricción.

### 2.2 Recuento de pruebas en las partes críticas

| Parte | Funciones `Test*` | Huecos de cobertura (`go tool cover -func`) |
|---|---|---|
| Planificador `internal/plan` | 10 | No hay pruebas de ventana deslizante (SWA) ni de modelos Gemma 4. `KVBytesPerElement` al 57 % |
| Scheduler `internal/sched` | 17 | `load` 65,4 %, `Usage` 38,5 %, `New` 28,6 % (el arranque real del backend no se prueba), `checkBackend` 54,5 %, `RunnerName` y `Device` 0 % |
| Supervisor del runner `internal/runner` | 13 | `Memory()` 0 % en la ruta real, `wrap` 66,7 %. El análisis de buffers solo se prueba con líneas sintéticas que **no aparecen** en el registro real de b11968 (R7) |
| Límites de memoria `cmd/eolas` (`config.go`) | 41 en el paquete | `limitGPUMemory` se prueba aislada (`settings_test.go:119-139`), pero **`serveWithContext` está al 0 %**: ninguna prueba comprueba que el límite llegue al scheduler, y por eso el defecto R1 pasó desapercibido |
| Autenticación con `api.key` | 4 referencias en las pruebas de server más `upload_auth_test.go` | Cubre que se exija la clave. No hay prueba de que el runner de llama-server sea accesible sin clave (R3) ni del lanzador con `-NoApiKey` |
| Supervisor PowerShell `launch-eolas.ps1` | Solo comprobaciones de texto en `test/system.test.mjs:93` (que además busca la cadena literal `$env:EOLAS_VRAM_LIMIT_MB='5200'`, ya inexistente tras el cambio sin commit, así que esa prueba de Node probablemente falle; **NO VERIFICADO**, no se ejecutó) | La política de reinicio y la detección de caída no tienen pruebas de ejecución |

---

## 3. Riesgos concretos (archivo:línea)

Evidencia de ejecución tomada del registro `runtime\eolas\logs\runner-gemma-4-12b-it.log` (25 500 líneas, de solo lectura):
- `bad allocation` seguido de `GGML_ASSERT(batch.slot_batched …) failed` (caída de llama-server) en las líneas 3848-3849, 9108-9112, 14714-14718 y 20749-20753, y `failed to allocate memory for prompt cache state` en las líneas 14238 y 19544.
- `cudaMalloc failed: out of memory` al reservar el KV (480 MiB) con `n_gpu_layers already set by user to 49` en las líneas 13884-13886 y 13901-13903.
- Rendimiento: `n_ctx_slot = 2048` → 6,18 t/s; `n_ctx_slot = 32768` → **3,02 t/s** (300 tokens en 98,98 s, la última tarea).

### Memoria y planificador

- **R1 (alta). `EOLAS_VRAM_LIMIT_MB` no se aplica en la carga.** `config.go:212` aplica `limitGPUMemory` solo dentro de `settingsFor` (elección del perfil). `main.go:239` descarta esa lista limitada para la planificación y `main.go:253` crea `sched.New(set)`, cuyo `GPUs` es `gpu.Discover` sin límite (`sched.go:193`). Por tanto `load()` (`sched.go:388`) y `/api/eolas/plan` (`sched.go:627`) planifican con la VRAM libre real. `doctor_extra.go:127` y `server.mjs:29,126` muestran el límite como si estuviera activo. Lo mismo ocurre en todas las ramas locales y remotas revisadas. Consecuencia: la hipótesis «13 capas por `EOLAS_VRAM_LIMIT_MB=5200`» **no se sostiene con este código**. Las 13 capas se explican mejor por R2 junto con la VRAM libre real del escritorio (**NO VERIFICADO**: hace falta un `POST /api/eolas/plan` en vivo para confirmarlo).
- **R2 (alta). El planificador ignora la atención con ventana deslizante (SWA) de Gemma 4.** `plan.go:168-178` calcula el KV de **todas** las capas con el contexto completo (32768) y con `key_length` global. Gemma 4 alterna capas locales con `attention.sliding_window` y `key_length_swa` (lo usa el motor nativo en `EolasV1/gemma4.go:187-199`), y llama.cpp reserva para ellas una caché de tamaño ventana. Con 32K de contexto, el KV estimado es varias veces el real, el auto-KV cae a q8_0 (`plan.go:116-122`) y se cargan pocas capas. Encaja con los 3,0 t/s a 32K frente a los 6,2 t/s a 2K.
- **R3 (media).** Con `num_gpu` explícito no hay ajuste: `plan.go:320-322` usa `num_gpu` sin comprobar si cabe y, en el modo auto, `p.FullOffload = Layers > nLayer` da por buena la f16 (`plan.go:118`) aunque no quepa. Además, llama.cpp desactiva su propio ajuste (`common_fit_params … already set by user`). El resultado es el OOM del KV en las líneas 13884/13901. El PR #10 lo aborda **solo en la parte de KV**.
- **R4 (media).** Se ignora el error de `nvidia-smi`: `gpus, _ := s.GPUs(ctx)` en `sched.go:388`, `410` y `627`. Si `nvidia-smi` agota su tiempo de 5 s (`gpu.go:65`) o falla, `plan.go:323-324` decide «no GPU: CPU only» y el modelo se carga con `-ngl 0` durante todo el `keep_alive` sin avisar.
- **R5 (media).** No hay tratamiento de OOM ni reintento. `runner.go:164-165` devuelve «exited while loading» con la cola del registro, y `sched.load` (`sched.go:431-433`) lo propaga como HTTP 500 (`server.go:224`). No hay clasificación (`cudaMalloc failed`, `bad allocation`) ni reintento con menos capas, KV q8_0 o menos `num_ctx`. Si llama-server muere a mitad de una generación, `Completion` devuelve error (`runner.go:395-398`) sin reintentar, y la siguiente petición recarga el modelo (`sched.go:285`).

### Concurrencia y reutilización

- **R6 (media).** La clave del runner incluye `num_ctx`, `num_batch`, `num_thread`, etc. (`sched.go:250-255`). Con `MaxLoaded=1` (`launch-eolas.ps1:179`), dos clientes con opciones distintas (por ejemplo, la web con `num_ctx:32768` en `server.mjs:316` y Fios u otro cliente con otro valor) provocan descargas y recargas alternas (`sched.go:285-287`) de unos 4-11 s cada una, o esperas mientras el otro tiene `refs>0` (`sched.go:320-327`). No hay métrica de recargas.
- El scheduler supera `-race` en las pruebas. `freePort()` (`runner.go:463-470`) tiene una carrera TOCTOU: libera el puerto antes de que llama-server lo ocupe (impacto bajo).

### Tiempos límite

- **R7 (media).** Ni el cliente HTTP del runner ni el servidor tienen tiempo límite. `runner.go:136` usa `&http.Client{}` sin `Timeout`, y `Completion` (`runner.go:360-394`) no vigila la inactividad: si llama-server se cuelga sin morir, la petición queda abierta hasta que el cliente cancele. `main.go:258` solo fija `ReadHeaderTimeout` (sin `ReadTimeout` ni `IdleTimeout`), y `decode` acepta cuerpos de 256 MiB (`server.go:237`).
- Desajuste con los clientes: `server.mjs:332` pide `num_predict:3072` con un `timeout` de 180 s. A unos 3,1 t/s eso requiere unos 990 s, así que la web aborta antes y la petición nunca termina con éxito. `server.mjs:316` pide 768 tokens en 90 s, unos 250 s a 3 t/s.
- La lectura de memoria está rota con b11968: `memory.go:21` busca `… buffer size = N MiB`, pero el registro real (verbosidad 3) tiene **0 coincidencias** de `buffer size`. `memory_measured` depende solo de la diferencia en `nvidia-smi` (`sched.go:437-440`, `126-128`).

### Seguridad del API

- **R8 (media).** El runner llama-server no tiene clave. `runner.go:51` lo lanza en `127.0.0.1:<puerto aleatorio>` sin `--api-key`, y el propio registro avisa de `no API key is set and CORS allows all origins`. Cualquier proceso local puede descubrir el puerto y usar `/completion` o `/slots`, saltándose la clave de Eolas (`server.go:118-127`). Además, `exec.Command` (`runner.go:137`) hereda `EOLAS_API_KEY` en el entorno del hijo.
- La clave es opcional. `-NoApiKey` (`launch-eolas.ps1:138`) y una `EOLAS_API_KEY` vacía en loopback (`config.go:41`) dejan **todas** las rutas abiertas, incluidas `DELETE /api/delete`, `pull` y `create`. Con la clave desactivada, `allowedOrigin` acepta orígenes `file://`, `vscode-webview://*`, `app://*` y `tauri://*` (`server.go:147-150`).
- Lo que está bien: bind a loopback por defecto (`config.go:51`), clave obligatoria fuera de loopback (`config.go:40-45`), comparación en tiempo constante, protección contra DNS rebinding (`server.go:159-179`) y filtrado de secretos del entorno en el lanzador (`launch-eolas.ps1:48-60`). Detalle menor: `TrimPrefix("Bearer ")` distingue mayúsculas (`server.go:119`).

### Reintentos y supervisión

- **R9 (media).** El supervisor solo vigila `eolas.exe` y la web (`launch-eolas.ps1:238-248`), no llama-server ni la salud de Eolas (la espera de arranque de `launch-eolas.ps1:214-218` solo comprueba `http://127.0.0.1:<web>/api/status`). Tras 5 caídas en 10 minutos lanza una excepción y el `finally` lo mata todo (`launch-eolas.ps1:230,255-261`): sin estado degradado ni notificación.
- **R10 (baja).** `go test ./...` en la raíz falla por `runtime/eolas/respaldo-2026-11-15/copias-sin-seguimiento/Eolas Base`. Es candidato para `REGISTRO_LIMPIEZA.md` (no se ha tocado).

---

## 4. Qué falta para que V1 sea «autónomo verificable»

| # | Mejora | Dónde | Métrica de aceptación |
|---|---|---|---|
| M1 | **Planificador SWA-aware** para Gemma 2/3/4: KV de ventana `min(ctx, sliding_window)` para las capas locales según `sliding_window_pattern` y `key_length_swa` | `plan.go:168-178` y una prueba con GGUF sintético en `plan_test.go` | Capas en GPU para gemma-4-12b con 32K: pasar de 13 a ≥ 30 (objetivo: las máximas que quepan). tokens/s de generación ≥ 6 a 32K. Error de VRAM estimada frente a medida ≤ 10 % |
| M2 | **Aplicar de verdad `EOLAS_VRAM_LIMIT_MB`** (envolver `sc.GPUs` con `limitGPUMemory` en `main.go:253`) o eliminar la variable y su documentación. Añadir una prueba de cableado de `serveWithContext` | `main.go:239-253`, `config.go:276` | Prueba: `GET /api/eolas/gpus` y `/api/eolas/plan` reflejan el techo. Cobertura de `serveWithContext` > 0 %. `doctor` indica si el límite es efectivo |
| M3 | **Métricas expuestas** en `/metrics` y `/api/eolas/status`: `eolas_eval_tokens_per_second` (último valor y media móvil), `eolas_prompt_tokens_per_second`, `eolas_gpu_layers{model}`, `eolas_total_layers`, `eolas_kv_cache_type`, `eolas_context_length`, `eolas_vram_free_bytes`, `eolas_vram_planned_bytes` frente a medidos, `eolas_runner_restarts_total`, `eolas_runner_oom_total`, `eolas_model_reloads_total`, `eolas_queue_depth` y `eolas_load_seconds` | `server/eolas.go:74-91`, `generate.go:426-434` (los datos ya existen en `ev.Metrics`) | Una lectura de `/metrics` tras una petición permite calcular tokens/s, capas y VRAM sin leer registros. Una prueba de contrato fija los nombres |
| M4 | **Autodiagnóstico y recuperación de OOM**: clasificar la salida del runner (`cudaMalloc failed`, `bad allocation`, `GGML_ASSERT`), reintentar la carga una vez con un plan degradado (−20 % de capas, después KV q8_0 y después `num_ctx` menor) y registrar el motivo. Tratar el error de `nvidia-smi` (`sched.go:388`) como reintento o error, nunca como modo solo CPU. Añadir un vigía de llama-server con un tiempo límite de inactividad en `Completion` | `runner.go:164`, `sched.go:388-433`, `runner.go:360` | Prueba con fakellama que simule el OOM y compruebe que la carga termina con éxito y menos capas. 0 caídas `GGML_ASSERT` en 100 peticiones de 7000 tokens dentro del Job de 9600 MiB. Tiempo de recuperación < 30 s |
| M5 | **Prueba de humo reproducible y verificable**: un script (`eolas bench` ya existe en `cmd/eolas/bench.go`) que arranque con un puerto privado, haga 1 petición corta y 1 de 7000 tokens, y guarde un JSON con el SHA-256 del binario y del modelo, la GPU y el driver, la VRAM libre, el plan (capas, KV, contexto), los tokens/s de prompt y de generación, el pico de memoria del Job y los códigos de salida. Debe fallar si los tokens/s caen bajo un umbral o si las capas no coinciden con el plan | `tools/` más CI local (no en la nube: requiere GPU) | Resultado reproducible: dos ejecuciones con la misma configuración dan las mismas capas y una diferencia de tokens/s ≤ 10 %. El informe JSON se archiva por commit |
| M6 | Elección automática de capas y contexto por petición: si el prompt (tokenizado) y `num_predict` caben en menos contexto, usar un `num_ctx` escalonado (8K, 16K o 32K) para ganar capas; y unificar `num_ctx` entre la web y Fios para evitar R6 | `sched.params` (`sched.go:229`), `server.mjs:300-332` | Recargas por hora ≈ 0 con uso mixto web y Fios. Tokens/s de las peticiones cortas ≥ 6 |
| M7 | Seguridad del runner: `--api-key` aleatoria por proceso para llama-server, pasada solo al cliente interno, y `cmd.Env` sin `EOLAS_API_KEY` | `runner.go:51,137` | Un `POST` sin clave al puerto del runner recibe 401 |
| M8 | Tiempos límite del cliente y del servidor coherentes con los tokens/s medidos (en `server.mjs`, el tiempo límite debería derivarse de `num_predict / tps`) e `IdleTimeout` en `main.go:258` | `server.mjs:316,332`, `main.go:258` | 0 abortos por tiempo límite en las peticiones de 3072 tokens de la prueba de humo |

Pasos inmediatos sin riesgo: (1) un `POST /api/eolas/plan` en vivo con las opciones de la web, para confirmar R1 y R2 con datos; (2) ejecutar `go test ./...` dentro de `Eolas Base` en la CI; (3) registrar el respaldo de `runtime/` en `REGISTRO_LIMPIEZA.md`.

## 5. Límites de esta auditoría

- Estática más pruebas unitarias. No se arrancó ningún servidor ni se cargaron modelos: las cifras de capas y tokens/s salen del registro existente, no de mediciones nuevas.
- No se leyó el GGUF de Gemma 4 (parámetros exactos de SWA y capas), así que el tamaño del efecto de R2 queda **NO VERIFICADO**.
- No se ejecutaron las pruebas de Node (`test/system.test.mjs`) ni las de e2e.
- No se revisó el contenido de los PR #6, #9 y #10 más allá de los mensajes de commit de sus ramas locales (`2ab224e`, `f3b7b4e`, `aaf34ff`).
