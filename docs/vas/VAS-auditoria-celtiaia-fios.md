# VAS — Auditoría de solo lectura de CeltiaIA y Fios

Fecha: 2026-11-16. Repositorio `D:\celtiaia`, rama `main`, HEAD `4cb6b78e4d33cf19ab0626defbe0ba7ab6341730`.
Cambios sin commit del titular presentes y **no tocados**: `docs/audit/REA-BUNDLE-CONSOLIDADO-2026-11-05.md`, `launch-eolas.ps1` (el diff del lanzador hace configurables los límites de VRAM y añade `--cache-ram 1024`; equivale en parte a la PR #6).
Método: inspección de fuentes, `gh` de lectura y ejecución de las pruebas unitarias puras. No se arrancaron servidores, Electron ni modelos; no se leyó `runtime/eolas/api.key`; `runtime/` solo se listó en su primer nivel (y `runtime/eolas`). `git status` quedó idéntico antes y después.

---

## 1. Mapa de arquitectura

### 1.1 CeltiaIA (servidor web Node)

| Componente | Archivo | Función |
|---|---|---|
| Servidor HTTP | `server.mjs` (383 líneas, sin dependencias npm) | Escucha solo en `127.0.0.1:5176` (`server.mjs:11-12,371`). Comprueba Host/Origin (`:70-76`), cabeceras CSP/no-store (`:58-64`), cuerpo ≤100 KB (`:77-86`). |
| Autenticación owner | `scripts/owner-auth.mjs` | Una sola cuenta owner en `runtime/auth/owner.json` (scrypt N=2^15, `:14,29-47`). Sesiones en memoria (`Map`, `:58`), cookie `HttpOnly; SameSite=Strict` de 12 h (`:11,111-113`), bloqueo 60 s tras 5 fallos (`:12-13,74-81`). Alta con `npm run owner:create`. |
| Chat | `server.mjs:309-321` | `POST /api/chat` → Eolas `/api/chat` (estilo Ollama), `think:false`, `num_predict:768`, timeout 90 s; límite 30 peticiones/día (`runtime/usage.json`, `:18,135-149`). |
| Generador de prototipos («Fios web» premium) | `server.mjs:322-345` | `POST /api/fios/generate` pide al modelo un JSON {archivo: contenido}, lo valida (≤12 archivos, ≤24 KB c/u, ≤64 KB total, rutas seguras, `:36-56`) y se guarda en `projects/fios/<slug>` (`:233-250`). Vista previa con CSP `sandbox` (`:227-232,346-352`). Solo si `CELTIAIA_PREMIUM=1`. |
| Carga/descarga de modelo | `server.mjs:293-305` | `POST /api/models/load` usa `/api/generate` con `keep_alive`. |
| Integración Fios (escritorio) | `scripts/fios-service.mjs` | Arranca Electron (`scripts/fios`) como hijo bajo demanda, puerto loopback aleatorio, espera `FIOS_READY <url>#fios-token=<48 hex>` en stdout (`:69-86`) y hace de proxy HTTP/WS en `/fios/*` (`:93-137`). Exige sesión owner para el upgrade WS (`server.mjs:362-365`). |
| Lanzador/supervisor | `launch-eolas.ps1` | Arranca Eolas (`eolas.exe serve`, backend `llama` por defecto o `eolas` nativo) en `127.0.0.1:11435` y `node server.mjs`; crea/lee la clave `runtime\eolas\api.key` (`:134-149`); filtra variables secretas del entorno salvo `EOLAS_API_KEY` (`:48-60,201,205`). |
| Motor | `Eolas Base/` (Go + `eolas.cpp`), `internal/` (supervisor, tensor) | Fuera del alcance de detalle; CI ejecuta `go vet/test` de ambos. |

**Elección y llamada al motor (CeltiaIA):** URL fija por `CELTIAIA_EOLAS_URL` (por defecto `http://127.0.0.1:11435`), validada como HTTP loopback sin credenciales (`server.mjs:13-15`). Un único modelo `EOLAS_MODEL` (por defecto `gemma-4-12b-it:latest`, `:16`). Antes de cada generación `ensureReady` hace 3 llamadas (`/api/eolas/status`, `/api/tags`, `/api/eolas/gpus`) y exige backend `eolas|llama`, modelo presente, GPU CUDA y `EOLAS_DEVICE=cuda` (`:97-134,159-163`). La clave se envía como `Authorization: Bearer` si existe `EOLAS_API_KEY` (`:87-94`). Sin streaming, sin reintentos, un único trabajo a la vez (`busy`, `:34`).

**Almacenamiento:** `runtime/usage.json` (contador diario), `runtime/auth/owner.json` (hash), `projects/fios/<slug>/` (prototipos), `runtime/fios/` (datos de Fios integrado), `runtime/eolas/` (clave, logs, pid, `supervisor.json`, modelos). Todo `runtime/` y `projects/` está en `.gitignore`.

### 1.2 Fios (asistente/agente de escritorio Electron)

| Componente | Archivo | Función |
|---|---|---|
| Proceso principal | `scripts/fios/src/main/index.ts`, `gateway.ts` | Orquesta ventana, IPC, aprobaciones (`gateway.ts:66`), arranque de motores locales (`gateway.ts:547`). |
| Puente local | `src/main/localServer.ts` | HTTP/SSE/WS en `127.0.0.1:${FIOS_BRIDGE_PORT||5190}` (`:13,156`), token aleatorio de 24 bytes con `timingSafeEqual` (`:17,28-29`), comprobación de Host/Origin (`:118`). |
| Bucle de agente | `src/main/agent.ts` (776 l.) | Bucle de hasta `settings.maxSteps` (`:168`), herramientas (`read_file`, `write_file`, `edit_file`, `run_command`, `rea_analyze`, `web_search`, `web_fetch`…), `LoopGuard`, compactación, verificación antialucinación que reinyecta afirmaciones sin respaldo (`:243-262`). |
| Política de comandos | `src/main/commandPolicy.ts` | Bloqueos duros por regex (`:10-17`), avisos (`:47-68`), lista de solo lectura sin aprobación (`:71-89`); el resto pasa por diálogo de aprobación humana (`agent.ts:593-599`). PowerShell `-ExecutionPolicy Bypass`, timeout 10 min, salida ≤100 KB, `exit_code` primero (`agent.ts:634-669`). |
| Proveedores | `src/main/providers.ts` (985 l.), `shared/types.ts:3` | 15 proveedores (codex, openai, anthropic, gemini, *-web, xai, meta, deepseek, kimi, **ollama**, eolas, llamacpp, compatible). En `main` **sigue** `ollama`: la PR #7 que lo retira está abierta, no fusionada. |
| Motor local | `shared/types.ts:208`, `localProviderTarget.ts:12-24`, `localKeys.ts` | «eolas» = Eolas V1 `http://127.0.0.1:11435/v1`; «llamacpp» local = Eolas V2 de Eolfi en `127.0.0.1:8090`. `localProviderTarget` rechaza destinos no loopback. `localEngineKey` solo entrega clave a loopback (`localKeys.ts:49`): V1 desde `EOLAS_API_KEY` o `EOLAS_HOME\api.key` / `CELTIAIA_HOME\runtime\eolas\api.key`; V2 desde `EOLAS_V2_API_KEY` o `~/.eolfi/eolas-v2.key`. `eolasV2Guard` impide que Fios pare o reemplace el llama-server de Eolfi (`localKeys.ts:110-122`). Para Eolas usa la API nativa con `num_ctx` (`providers.ts:411-504`) y reintento sin herramientas/«thinking» si Gemma lo rechaza (`:349`). |
| Peticiones | `providers.ts:895-925` | Rechaza enviar claves por http no loopback, `redirect:'error'`, timeout de cabeceras 20 s (600 s si hay señal), mensajes de error legibles. |
| Bóveda de claves | `src/main/vault.ts`, `envelope.ts`, `hello.ts`, `native/fios_vault.cpp` | `keys.vault.json` AES-256-GCM (`envelope.ts:77,87`); la DEK sale de PIN (scrypt, `envelope.ts:45-66`) o de Windows Hello; bloqueo por inactividad 5 min (`vault.ts:9,78-82`). |
| Sala limpia / REA | `cleanRoom.ts`, `rea.ts`, `grounding.ts` | Las salidas REA son material de referencia; cada archivo escrito queda en `.fios/trace.jsonl` del espacio de trabajo (`cleanRoom.ts:272-276`). |
| Memoria | `projectMemory.ts`, `toolMemory.ts`, `conversations.ts` | Memoria persistente por proyecto y conversaciones guardadas. |

**DLL nativa `fios_vault.dll` (solo lectura del fuente, no ejecutada):** `native/fios_vault.cpp` (235 l.) exporta `fios_status` (¿hay KeyCredentialManager + Windows Hello?) y `fios_dek(hwnd, out, cap, err, errlen)`: pide verificación de Windows Hello para la ventana, abre o crea la credencial no exportable `Fios.ApiKeyWrap.v1`, firma el texto fijo `Fios.ApiKeyWrap.v1`, devuelve SHA-256 de la firma como DEK de 32 bytes con prefijo de longitud y borra buffers con `SecureZeroMemory`. Se carga con `koffi` desde `native/` o `resources` y se compara su SHA-256 con `fios_vault.sha256` del mismo directorio (`hello.ts:38-72`). Hash comprobado ahora: `native/` y `dist/` = `ebe374c6a6b129ad865ccd4759b6c0e6566d425b200fdaa6ca839cbfddfaaa80`, coincide con ambos `.sha256`. La DLL compilada **no** está versionada en git (solo el `.cpp`).

---

## 2. Verificación

| Comprobación | Comando | Resultado |
|---|---|---|
| Estado git | `git rev-parse HEAD; git status --short` | `4cb6b78…`; solo los 2 archivos del titular modificados (antes y después). |
| Pruebas raíz: inventario | `package.json` → `"test": "node --test"`; `ls test` | 13 archivos; 69 llamadas `test(` estáticas (algunas generan más en bucle). |
| Pruebas unitarias puras (sin `listen`, `spawn` ni red) | `node --test test/benchmark.test.mjs test/fios-editor-session.test.mjs test/fios-elf-discovery.test.mjs test/fios-elf-exports.test.mjs test/fios-ipc-guard.test.mjs test/fios-pe-exports.test.mjs test/fios-pe-imports.test.mjs test/fios-rea-output.test.mjs test/model-origin.test.mjs` (Node v24.22.1) | **72 pass, 0 fail, 0 skip**, 1,26 s. Incluye inspección PE de la DLL real sin cargarla. |
| `test/system.test.mjs` (16), `owner-auth.test.mjs` (7), `fios-integration.test.mjs` (2), `fios-concurrency.test.mjs` (1) | — | **NO VERIFICADO**: abren servidores loopback y/o procesos hijo. |
| Smokes de Fios (`scripts/fios/scripts/smoke-*.ts`, 30 archivos; `npm run smoke`) | — | **NO VERIFICADO**: lanzan `tsx`/PowerShell y algunos necesitan motor vivo o Docker. |
| `npm run typecheck`, `build:fios`, `go test` | — | **NO VERIFICADO** (compilación no ejecutada). |
| e2e vivos (`e2e:live:*`, `check:fios-ws`) | — | **NO VERIFICADO**: requieren servidor y modelo. |
| CI | `gh run list --repo CeltiaIA/CeltiaIA` | **Todas las ejecuciones recientes en `failure`**, incluidas `main@4cb6b78` y las PR #6-#10. `gh run view 43761896172`: el trabajo no llegó a arrancar porque fallaron los pagos de la cuenta o hay que subir el límite de gasto. Último verde: `main@9d9175e` (PR #4). Es decir, nada desde la PR #5 tiene verificación automática. |
| PR abiertas | `gh pr list --state open` | #6 caché RAM llama-server (+7), #7 retirar Ollama (23 archivos), #8 token de vista previa (+117), #9 capas desde el modelo mapeado (+88), #10 caché KV f16 (+22). Ninguna con CI efectiva. |

---

## 3. Riesgos (archivo:línea)

### Secretos
- **R1 (alto) — Clave de Eolas V1 en claro y sin ACL restringida.** `launch-eolas.ps1:139-147` crea `runtime\eolas\api.key` con `WriteAllText` (permisos heredados de la carpeta) y la exporta a los hijos. Cualquier proceso del usuario puede leerla; Fios la lee también del archivo (`scripts/fios/src/main/localKeys.ts:34-58`), por lo que quitar `EOLAS_API_KEY` del entorno del hijo (`scripts/fios-service.mjs:29`) no aísla nada.
- **R2 (alto) — Comandos «de solo lectura» que leen fuera del espacio de trabajo sin aprobación.** `commandPolicy.ts:79-89` acepta `Get-Content`/`cat`/`dir`… sin mirar rutas; `agent.ts:593` solo exige que el **cwd** esté dentro. La protección de secretos de `commandPolicy.ts:39` solo reconoce rutas con letra de unidad, así que `Get-Content $env:USERPROFILE\.ssh\id_ed25519` o `~\…` o `..\..\…` no pasaría ni por `protectedPath` ni por el diálogo, y la salida va al modelo (que puede ser remoto). Deducido del código; **NO VERIFICADO** por ejecución.
- R3 (medio) — Integridad de la DLL: el SHA-256 esperado está en un archivo vecino (`hello.ts:51-72`); quien pueda sustituir la DLL puede sustituir el `.sha256`. No hay firma Authenticode.
- R4 (bajo) — El proxy reenvía todas las cabeceras del navegador, incluida la cookie de sesión owner, al hijo Fios (`fios-service.mjs:105-107`); token WS por query y comparado con `!==` (`:118`).

### Exposición de puertos
- Bien: CeltiaIA 127.0.0.1:5176 con Host/Origin (`server.mjs:11,70-76`); Fios 127.0.0.1:5190 con token (`localServer.ts:13-29,156`); Eolas validado loopback (`server.mjs:14`, `localProviderTarget.ts:19`).
- R5 (medio) — `GET /` del puente Fios sin `Origin` redirige a la URL **con el token** (`localServer.ts:107-116`): cualquier proceso local (curl) obtiene el token y controla el agente (incluido lanzar comandos que el humano aprobaría por error). Puerto fijo por defecto 5190 cuando Fios corre fuera de CeltiaIA.
- R6 (medio) — Lanzador con `-NoApiKey` (`launch-eolas.ps1:1,138`) deja Eolas sin autenticación; cualquier proceso local puede borrar/crear/descargar modelos (lo reconoce el propio comentario `:134`).

### Manejo de errores del motor
- R7 (alto para VAS) — `server.mjs:87-94`: `response.json()` sin límite de tamaño ni validación de tipo; todo error HTTP se convierte en 502 genérico y se descarta el cuerpo; `engineStatus` traga toda excepción (`:127-133`) y no registra la causa. No hay registro (log) estructurado en el servidor: el único `console.log` es el de arranque (`:371`).
- R8 (medio) — `fios-service.mjs:77` descarta stderr de Electron: si Fios no arranca, el usuario ve «Ejecuta npm run build:fios» (`:112`) sin causa; timeout fijo 30 s (`:70`).
- R9 (medio) — `busy` global sin cola (`server.mjs:34,296,311,326`): una segunda petición recibe 429; `ensureReady` añade 3 llamadas por petición; no hay reintentos ni circuito.
- R10 (bajo) — Sesiones y contador de fallos en memoria (`owner-auth.mjs:58-60`): reinicio = cierre de sesión; el bloqueo es global, cualquier proceso local puede mantener bloqueado al owner con 5 intentos/min.

### Dependencias
- R11 (medio) — `scripts/fios/package.json`: rangos `^` en `electron ^45`, `vite ^8`, `typescript ^7`, `koffi ^3.3.5`; herramientas de build y `@types/*` en `dependencies` (se empaquetan). `rea-agents 6.8.0` sí está fijado. Hay `package-lock.json`, que mitiga en `npm ci`. `npm audit` **NO VERIFICADO** (sin red).
- R12 (alto para el proceso) — CI desactivada de facto por facturación (ver §2): las PR #5-#10 no tienen verificación automática.

---

## 4. Qué falta para que CeltiaIA + Fios formen parte de un sistema autónomo verificable (VAS)

| # | Mejora | Dónde | Métrica de aceptación |
|---|---|---|---|
| M1 | **Restablecer la CI** (facturación) o ejecutar `ci.yml` en un runner autoalojado Windows; bloquear la fusión sin verde. | `.github/workflows/ci.yml` | 100 % de PR y `main` con CI verde ejecutada (no «job not started»); tiempo medio < 45 min. |
| M2 | **Registro de acciones append-only** (JSONL con hash encadenado): cada llamada al motor (modelo, backend, latencia, tokens, código), cada herramienta del agente (nombre, args resumidos, cwd, exit_code, aprobación sí/no y quién), cada login. Hoy solo existe `.fios/trace.jsonl` para archivos escritos (`cleanRoom.ts:272`). | `server.mjs:87`, `agent.ts:581-604`, `owner-auth.mjs:74` | 100 % de acciones con efecto registradas; cadena de hashes verificable por un script; 0 secretos en el log (prueba con clave canaria). |
| M3 | **Permisos explícitos y deny-by-default**: rutas de lectura limitadas al espacio de trabajo (resolver variables, `~`, `..` y rutas relativas antes de decidir), perfil de permisos por tarea (lectura / escritura en workspace / comandos / red), ACL de usuario en `api.key` y token del puente fuera de `GET /`. | `commandPolicy.ts:39,79-89`, `agent.ts:593`, `launch-eolas.ps1:144`, `localServer.ts:107` | Batería de ≥30 comandos adversarios (incl. `$env:`, `~`, `..`, UNC): 0 lecturas fuera del workspace sin aprobación; `icacls api.key` solo el usuario. |
| M4 | **Tareas de agente medibles (banco de evaluación)**: conjunto fijo de tareas con oráculo (p. ej. «crea proyecto y pasa sus pruebas», «arregla prueba rota», «audita binario PE con cobertura declarada»), ejecutadas en copia limpia con Eolas V1 y V2, resultado JSON con pasos, exit codes y veredicto, siguiendo el patrón `verification` de Eolfi. | nuevo `scripts/eval-agent.mjs` + `test/` | Tasa de éxito por tarea y motor, mediana de pasos y de tiempo, % de afirmaciones sin respaldo detectadas por `grounding.ts`; umbral mínimo fijado y regresión bloqueante. |
| M5 | **Recuperación ante fallos y prueba de humo de extremo a extremo**: supervisión con reinicio y backoff de Eolas, servidor y Fios (registrando stderr), errores del motor tipados (sin conexión / no listo / timeout / respuesta inválida / sobrecarga) con causa en `/api/status`, cola en lugar de 429, sesiones persistentes firmadas; un `smoke:vas` que arranque todo en puertos aleatorios, haga login, una consulta mínima al modelo, abra `/fios`, ejecute una herramienta de solo lectura y pare limpio. | `launch-eolas.ps1`, `server.mjs:34,87-134`, `fios-service.mjs:69-90` | MTTR tras matar Eolas < 60 s sin intervención; smoke VAS verde ≥ 95 % en 20 ejecuciones; 0 procesos huérfanos tras `npm stop`. |

Otras pendientes: fusionar o cerrar las PR #6-#10 tras CI real (la #7 deja `main` todavía con Ollama); firmar la DLL o fijar su hash en código; mover herramientas de build a `devDependencies`; documentar en `CONTINUIDAD.md` qué pruebas son puras para el arnés VAS.

## 5. Límites de esta auditoría
- Revisión estática parcial: `providers.ts`, `agent.ts`, `gateway.ts`, `cleanRoom.ts`, `Eolas Base/` e `internal/` leídos solo en los fragmentos citados; `public/*.js` no revisado.
- R2 y R5 son conclusiones del código; no se ejecutaron para confirmarlos.
- No se ejecutaron: 4 archivos de pruebas con servidores, smokes de Fios, typecheck/build, Go, e2e vivos, `npm audit`.
