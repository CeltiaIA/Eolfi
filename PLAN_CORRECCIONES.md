# Plan de correcciones e implementaciones de Eolfi

> **Documento histórico:** su estado corresponde a las fases de auditoría de noviembre de 2026. El backlog activo está en [PLAN_INGENIERIA_INVERSA_EOLFI.md](PLAN_INGENIERIA_INVERSA_EOLFI.md); consulta este archivo como registro de correcciones anteriores.

Auditoría del 2026-11-04, hecha carpeta por carpeta y archivo por archivo por 5 agentes de revisión en modo solo lectura.
Prioridad: **A** = alta (seguridad o datos), **M** = media, **B** = baja. `[V]` = fallo reproducido por el agente.
Cada fase debe acabar con `python -m pytest -q` y `node --test` en verde.

## Estado (actualizado)
**Fase 1 aplicada** (salvo A10). Pasan las 100 pruebas de Python y las 24 del puente. Lo he comprobado de verdad:
he generado Express y FastAPI con un título hostil, y he probado la reconexión del puente con tu Chrome.

| Id | Corrección aplicada |
|----|---------------------|
| A1, A2 | `safe_title` / `safe_resource` / `safe_font` en spec.py: título con lista blanca de caracteres; recursos que sean identificadores válidos, no reservados y deduplicados. |
| A3 (+B5) | verify.py: `safe_env()` solo pasa las variables del sistema, de proxy y de certificados, sin claves de API. Con timeout mata el árbol de procesos (`taskkill /T`). |
| A4 | Al escribir sobre el origen se hace copia de seguridad y se omite la verificación. Pendiente: verificar en una copia limpia. |
| A5 | Fuera de loopback, la API exige un token de arranque (cookie HttpOnly SameSite=Strict, `?token=` la primera vez). |
| A6 | `X-Eolfi`, `Origin` y `Sec-Fetch-Site` se comprueban antes de leer el cuerpo. Límite de 4 MB en JSON (256 MB solo en `/api/upload`). |
| A7, A8 | Puente: `panelToken` propio para el panel. Con el token de Eolfi, `/v1/screen` y `/v1/input` dan 403 y `source:"panel"` sigue pidiendo aprobación. |
| A9 (+M13, M15) | El puente no envía nada si se cancela durante la aprobación. La aprobación caduca a los 2 min. Un proveedor ocupado da 409. `abortCheck` antes de escribir y de pulsar Intro. `await` en sendInputEvent. |
| A11 | Al reconectar se comprueba que el id de `/json/version` coincide con DevToolsActivePort del perfil de Eolfi. |
| A12 | String pool de AXML/ARSC: las cadenas deben quedar dentro del pool, memo por offset y presupuesto 4× del tamaño. |
| A13 | `EntropyBudget`: caché por (off, len) y presupuesto de 2× el archivo + 16 MB. Mach-O valida `nsects` contra `cmdsize`. |
| A14 | capa, rizin y Ghidra analizan una copia `<sha256>.bin` en una carpeta temporal. `check_cmd_safe`; los nombres a decompilar van con lista blanca. Se valida el tipo del JSON de rizin (M26). |
| A15 (+M20) | Los errores al leer una entrada de APK (cifrado falso, compresión no soportada…) ya no tumban el inventario. `@0x` se valida con regex. |
| A16 | PageParser: como mucho 32 capturas abiertas, un contador de longitud por captura y una pila de 512. Encontrar el nodo padre ya es O(1). 90 000 etiquetas sin cerrar tardan menos de 1 s (antes, 18 KB tardaban 36 s). |
| A17 | Los comentarios CSS se quitan con un escaneo lineal (`strip_css_comments`), con un tope de 5 MB por archivo. |
| A18 (+B10, M30) | fetch: la IP se resuelve una vez, se valida y se conecta a ella (y se comprueba `getpeername`). Se bloquean las IP no globales (CGNAT y IPv4 mapeada). Un host que no resuelve cuenta como privado. Un 5xx en robots.txt = no rastrear. Se conservan los Set-Cookie repetidos. Sin proxy. |
| A19 (+M28, M29) | clone: solo https/ssh, host público, `protocol.allow=never` salvo https/ssh, `http.followRedirects=false`, `GIT_CONFIG_NOSYSTEM`. Carpeta única por clon, limpieza si hay timeout o error. `_git_info` sin fsmonitor, pager ni sshCommand. |
| A20 | Cada manifiesto va en su propio try (cualquier excepción queda en `errors`). manifest.json, source maps y JSON-LD se validan por tipo y toleran RecursionError. |
| — | Nuevas pruebas: tests/test_hardening.py, tests/test_server.py (token, cross-site, 413) y eolfi/bridge/test/panel.test.mjs. |

**Fase 2 aplicada** (salvo M7; M19 completada después). Pasan las 105 pruebas de Python (1 omitida: crear enlaces
simbólicos exige permisos en Windows) y las 24 del puente. Verificado de verdad:
- FastAPI y Express con SQLite y login, Django y React, generados de nuevo.
- Puente en vivo: DeepSeek y Gemini responden «OK».
- Chrome del puente detectado por perfil exacto.

| Id | Corrección aplicada |
|----|---------------------|
| M1 | assist: igualdad exacta en archivos sueltos y prefijo con «/» en carpetas. `conftest.py` prohibido. Las migraciones Django existentes no se reescriben. |
| M2 | Migraciones: número repetido = error; checksum sin CRLF/LF; BEGIN/COMMIT prohibidos en el .sql. assist exige el número siguiente al último. |
| M3 | FastAPI+SQLite: un único `RLock` compartido por almacén y auth; `conn()` se inicializa bajo lock. |
| M4 | Auth (FastAPI y Express): registro sin enumeración (201 siempre), 429 tras 5 fallos en 15 min, `POST /api/auth/logout`, purga de tokens caducados, PBKDF2 asíncrono en Node, `timingSafeEqual` con comprobación de longitud, email normalizado igual. Con pruebas generadas. |
| M5 | Django: sin `DJANGO_SECRET_KEY` y con DEBUG=0 no arranca (comprobado). |
| M6 | CI `npm ci \|\| npm install`; Dockerfile con `npm ci` solo si hay lock. |
| M8 | CLI: se compara el valor exacto de `--user-data-dir` (no coincide con `browser-profile2`) y se captura `TimeoutExpired`. |
| M9, M34 | Servidor: los análisis largos corren en paralelo (un lock por fuente o destino); SQLite con WAL y `busy_timeout`. |
| M10 | Panel: objetivos como `<button>`, zona de soltar con teclado, pestañas con flechas y `aria-controls`, el lector de pantalla solo anuncia el último mensaje del chat. |
| M11 | `max_assets` entre 1 y 200. |
| M12 | Puente: `start()` y `page()` deduplicados; el adaptador se conserva al reconectar (solo cambia la pestaña). |
| M14 | `loadURL` sin fugas: `off()`, el temporizador se limpia y se filtra por `loaderId` del marco principal. |
| M16 | Una segunda instancia sale de verdad; bridge.json solo se borra si el pid coincide. |
| M17 | El diálogo de aprobación muestra el principio, el final y «N caracteres ocultos». |
| M18 | Se comprueba el origen justo antes de escribir (`assertOrigin`). |
| M19 (parcial) | Gemini: el botón «detener» se detecta solo por aria-label/title que empiece por stop/detener/parar. Los textos de DeepSeek y Meta siguen dependiendo del idioma. |
| M21, M23 | Importación: authority, confidence, status, JSON e ids validados. Las evidencias importadas llevan la marca «declaradas por el paquete». |
| M22 | Un conflicto repetido fusiona las evidencias y reabre la incógnita si estaba resuelta. |
| M24 | AXML: atributos dentro de su elemento, presupuesto global y error explícito si hay más de 100 000 nodos. |
| M25 | strings por bloques de 8 MB sin guardar todas las cadenas; DEX con tope de tamaño; AXML lee solo 16 MB. |
| M27 | Repos locales: no se siguen enlaces simbólicos ni junctions (ni carpetas ni archivos). |
| M31 | `_save`: colisiones `/a` y `/a/b.css` y nombres CON/NUL sin abortar. |
| M32 | diff: nombre relativo al corpus; salida a archivo temporal con tope; árbol de procesos eliminado al agotar el tiempo. |
| M33 | Escribir sobre el origen exige confirmación explícita: el panel pregunta y la CLI pide `--force`. La copia de seguridad usa `symlinks=True`. |

**Pendiente de la Fase 2:**
- **M7:** no se aplica `--ignore-scripts`, porque rompería esbuild, sharp, etc. Se sigue confiando en las dependencias oficiales.
- **M19:** selectores de DeepSeek y Meta que dependen del idioma.

**Fase 3 aplicada.** Pasan las 109 pruebas de Python y las 24 del puente.

| Id | Corrección aplicada |
|----|---------------------|
| B1 | Fuente del CSS ajeno con lista blanca (`safe_font`, ya en la fase 1). |
| B2 | Valores de atributo escapados en JSX/Vue/Svelte (en Svelte también `{}`) y nombres de atributo validados; las directivas de Vue no se tocan. |
| B3 | Con clave de API: solo https (o http a 127.0.0.1/localhost) y sin seguir redirecciones. |
| B4 | `com.eolfi.<x>` evita las palabras reservadas de Java. El cliente Expo avisa de que el APK bloquea http en claro. |
| B5 | Verify mata el árbol de procesos al agotar el tiempo (fase 1). |
| B6 | Se valida el modo antes de guardar la subida; sin doble `unquote`; un cuerpo que no es objeto o un número inválido dan 400. Con `--host 0.0.0.0` y token, se admite cualquier Host. |
| B7 | `renderSummary` con try/catch; «Analizar» se desactiva durante el análisis; la comparación devuelve su `subject`; la vista en directo no solapa cargas y espera más tras un error. |
| B8 | Origen exacto (`new URL().origin`, fase 2). Meta marca «enviado» solo tras el clic. login.lock guarda el pid y se borra si está huérfano o tiene más de 6 h. Historial de 200 eventos. `since` inválido da 400. |
| B9 | Mach-O emite `symbol_errors` (y baja la confianza); limitación de dex corregida; rizin/radare2 registra la herramienta real; STIX sin SCO duplicados y con bundle determinista; SARIF con índice O(1). |
| B10 | fetch: no se baja de https a http; robots.txt también para el destino de las redirecciones; plazo total de descarga; los recursos que redirigen fuera del origen se descartan. (IP global, robots 5xx y Set-Cookie ya en la fase 1.) |
| B11 | Recuento de líneas por bloques con presupuesto de 400 MB (después, estimación). |
| B12 | Orden estable (`created_at, rowid`); `_set_diff` y los resúmenes toleran tipos raros; subject de comparación sin colisiones (`compare:a..b#hash`); `classify` ignora la query de la URL. |

**Nuevo (petición del usuario): todos los sistemas operativos y tipos de app.**
- Destino `desktop`: Electron endurecido para Windows, macOS y Linux, con instaladores (NSIS, DMG, AppImage/deb) y CI en los tres sistemas.
  Verificado de verdad: instalación, pruebas, arranque real (smoke) y `.exe` de Windows empaquetado que arranca.
- `auto` elige según el tipo de app:
  - PE, ELF, Mach-O o JAR, o Electron/Tauri/Qt/WPF/Avalonia/GTK/wxPython → escritorio.
  - APK, IPA, React Native, Flutter o MAUI → móvil (Android e iOS).
- `platforms` y `source_platforms` en la especificación.

**Nuevos destinos (petición del usuario).** Pasan las 114 pruebas de Python y las 24 del puente.
Cada destino se ha verificado de verdad en este equipo (Windows 11):
- `cli` (Python): instala el comando, pasa pytest y ejecuta `--json info`.
- `tauri` (Rust 1.98 + Tauri 2.12): pruebas de configuración, iconos, compilación y arranque real (smoke).
- `dotnet` (.NET SDK 10.0.403, instalado con winget a petición del usuario; Avalonia 12.1.5):
  restore, build con avisos = errores, xUnit, ventana nativa abierta de verdad y `BibliotecaNet.exe` autocontenido.
- La detección `auto` distingue consola, .NET, Tauri/nativo, Electron, móvil y web.
- Verify usa `CI=true` (la CLI de Tauri rechaza `CI=1`).

**A10 aplicada: control de Chrome por tubería privada** (`--remote-debugging-pipe`).
- Ya no hay puerto de depuración: verificado en vivo, el Chrome de Eolfi (14 procesos) tiene 0 puertos TCP en escucha y no hay `DevToolsActivePort`.
- Una conexión CDP por la tubería del proceso; las pestañas van por sesiones (`Target.attachToTarget` con flatten).
- Migración automática: si queda un Chrome antiguo con puerto, se cierra con `Browser.close` y se relanza por tubería.
- Modo login: cierra el Chrome del puente de forma normal (WM_CLOSE / SIGTERM) y solo fuerza si no responde.
- Verificado: prueba del navegador real por tubería y DeepSeek, Gemini y Meta responden en vivo con las sesiones conservadas.
- Cambio de comportamiento: al cerrar el puente se cierra su Chrome (antes quedaba abierto). Las sesiones siguen en el perfil.

**Fase 1 completa** (A10 hecha arriba). Riesgo residual de A19: git resuelve el DNS por su cuenta (TOCTOU), mitigado porque se impiden las redirecciones y solo se acepta un host público.

---

**Fase 5 aplicada (implementaciones propuestas).** Pasan las 151 pruebas de Python y las 28 del puente.
1. **Trabajos en segundo plano con progreso**: `POST /api/jobs {kind, body}` → `job_id`; `GET /api/jobs?id=&since=` devuelve estado, registro incremental y resultado o error. El panel lo usa para Crear y Analizar y muestra el progreso en vivo. Se conservan los últimos 50 trabajos.
2. **Carpetas permitidas**: `eolfi serve --root CARPETA` (repetible) o `EOLFI_ROOTS`. Se aplican a archivos a analizar, fuentes locales, carpeta destino y selector de carpetas. En modo remoto sin `--root`, solo `samples/` y `generated/`.
3. **Verificación aislada**: al escribir sobre el origen, el proyecto se genera y se verifica en una carpeta temporal limpia y luego se copia, con versiones fijadas y lockfiles. Completa A4. Junto con `safe_env()` (fase 1), las pruebas no ven claves ni restos del proyecto original.
4. **Accesibilidad con axe-core 4.14**: 0 infracciones en modo claro y oscuro (vista inicial, pestaña Web y detalle de objetivo). Se corrigió el contraste de avisos, del texto secundario y del texto sobre botones en modo oscuro, y el rol de la zona de soltar. Auditoría repetible: `tools/axe-audit.mjs`.

**M19 completada (selectores sin dependencia del idioma).** Se inspeccionó la estructura real de las páginas
(atributos y roles, sin textos de conversación ni cookies):
- Meta: enviar con `button[data-testid="composer-send-button"]` y editor con `data-testid="composer-input"`.
- DeepSeek: editor con `textarea[name="search"]` / `#chat-input`. Respuesta terminada = aparece su barra de ≥4 botones
  de acción (`.ds-button--iconLabelTertiary`), en lugar del aria-label «Leer en voz alta».
- Los textos en español e inglés quedan solo como respaldo. Verificado en vivo: DeepSeek y Meta responden «OK».

**Petición del usuario: pestaña «Proveedores» y tema.** Pasan las 153 pruebas de Python.
- Pestaña «Proveedores» en el panel:
  - IA: elige el proveedor (los 9 presets, con su disponibilidad) y queda sincronizado con «Crear».
  - Análisis: casillas para los 7 proveedores (triage, binfmt, archive, strings, capa, rizin, Ghidra) y atajos Local, Por defecto y Profundo.
  - La selección sustituye al modo y el servidor la valida (`providers` en `/api/triage` y `/api/upload`).
- Tema automático (sistema), claro u oscuro, desde la cabecera o desde la pestaña; se guarda en el navegador.
- axe: 0 infracciones también en la nueva pestaña, en claro y oscuro.

**Fase 4 aplicada (pruebas que faltaban).** Pasan 148 pruebas de Python (+34 en `tests/test_phase4.py`) y 28 del puente
(27 + 1 con navegador real por tubería).
- Título hostil (`"""`, `{{ }}`, `{% %}`, `<img onerror>`, `${}`, comillas invertidas, `\`) en los **13 destinos**:
  ningún delimitador llega al código; todo el Python generado compila (`ast.parse`) y todo el JSON es válido.
- Fuzz por mutación (300 casos por formato) de Mach-O, DEX, AXML, ARSC y ELF: solo `ParseError` y menos de 2 s por entrada.
- fetch: robots.txt con 503 bloquea; conexión a IP privada bloqueada con página pública; plazo total con servidor
  «a cuentagotas»; redirección https→http rechazada.
  **Encontró un fallo real:** `read(64 KB)` esperaba el bloque entero y se saltaba el plazo total. Ahora usa `read1`.
- Servidor: Host `127.0.0.1`, `localhost`, `[::1]` aceptados y `evil.example`/`*.nip.io` rechazados;
  cuerpos `[]`, `"x"`, `42`, `null` dan 400; `/api/repo`, `/api/web` y `/api/compare` (también con objetivo inexistente).
- Panel: prueba estática sin `innerHTML`, `insertAdjacentHTML`, `outerHTML`, `document.write`, `eval` ni `new Function`.
- Migraciones generadas: CRLF no cuenta como edición; números repetidos y BEGIN/COMMIT rechazados.
- Puente: tres `page()` simultáneos abren una sola ventana, un fallo no bloquea reintentos y `start()` arranca una sola vez.
- Pendiente: la prueba de enlaces simbólicos se omite en Windows sin permisos de desarrollador.

---

## Fase 1: Seguridad crítica (hacer primero)

### Generador de proyectos de Eolfi (código en eolfi/generador)
- **A1 [V] Inyección de código por el título del proyecto.** El nombre se mete sin escapar en docstrings de Python
  (generators_backend.py:395, generators_more.py:644), en JSX/Vue/Svelte/Next/Expo (React ejecuta `{…}`) y en las plantillas de Django (SSTI con `{{ }}` o `{% %}`).
  → Sanear en `build_spec`: título con lista blanca de caracteres. Ponerlo en `content.ts`/`content.py` y renderizarlo como dato, nunca interpolarlo en el código.
- **A2 [V] Nombres de recurso peligrosos.** `auth` y `app` tapan módulos de main.py, y las palabras clave (`class`, `import`) causan SyntaxError.
  Además, `foo-bar` y `foo_bar` acaban en la misma tabla.
  → Validarlos en spec.py: identificador válido, que no sea palabra reservada de Python/JS/SQL ni `auth/app/health/static`, y deduplicados por `_ident`. Importar los routers con alias.
- **A3 Claves de API filtradas a las pruebas.** verify.py ejecuta los tests con todo `os.environ` (ANTHROPIC_API_KEY…).
  Las pruebas pueden haberlas escrito una IA a partir de datos no confiables.
  → Pasar un entorno mínimo (PATH, HOME/USERPROFILE, TEMP, SYSTEMROOT).
- **A4 Verificar sobre la carpeta de origen ejecuta código ajeno.** Al escribir sobre el origen, quedan su conftest.py, tests, .npmrc y node_modules, y pytest o npm los ejecutan.
  → Al escribir en origen: generar en una carpeta limpia, verificar allí y después copiar al origen (la copia de seguridad ya existe).
  Si no, desactivar la verificación en ese modo.

### Servidor del panel (server.py)
- **A5 `--allow-remote` sin autenticación.** Desde la LAN se podría leer cualquier archivo (triage), escribir en cualquier carpeta (create con force) o usar tus chats.
  → Un token aleatorio en cada arranque (cookie HttpOnly SameSite=Strict) cuando el host no sea loopback, o eliminar `--allow-remote`.
- **A6 Agotar la memoria con el cuerpo de la petición.** Se leen hasta 256 MiB en RAM antes de comprobar `X-Eolfi`, así que una web externa podría lanzar varias peticiones a la vez.
  → Comprobar `X-Eolfi`, `Origin` y `Sec-Fetch-Site` antes de leer. Límite de 1-4 MB para JSON; la subida, por streaming a disco.

### Puente de chats (eolfi/bridge)
- **A7 Saltarse la aprobación con `source:"panel"`.** Eolfi y el panel comparten token, así que una inyección de prompt podría enviar sin diálogo.
  → Credencial distinta para el panel; `panel`, `/v1/input` y `/v1/screen` solo con ella.
- **A8 `/v1/input` también se salta la aprobación**: basta con escribir un texto y pulsar Intro.
  También permite clics en cualquier sitio. → Lo mismo que A7.
- **A9 Se envía aunque la petición se cancele.** Si Eolfi aborta durante el diálogo, el texto se escribe igualmente.
  → `abortCheck(signal)` tras `approve` y antes de escribir y de pulsar Intro, en los tres adaptadores. Poner un límite de tiempo a `approve()`.
- **A10 El puerto CDP no tiene autenticación.** Cualquier proceso local puede leer las cookies de Google, Meta y DeepSeek.
  → `--remote-debugging-pipe` (exige rediseñar la reconexión) y ACL restrictiva en `~/.eolfi`.
- **A11 Reconexión a un puerto ajeno.** Si otro proceso ocupa el puerto de DevToolsActivePort, se le entregarían los prompts.
  → Comprobar el PID o `/json/version` antes de reconectar.

---

## Fase 2: Robustez y bugs (M)

### Generador de proyectos de Eolfi
- M1 [V] Rutas de assist: `startswith` sin límite de segmento (`index.htmlx/evil.js`, `App.tsx2/a.ts`). Además se pueden editar `tests/conftest.py` y migraciones Django existentes.
  → Igualdad exacta en archivos sueltos y prefijo con `/` en carpetas. Bloquear `core/migrations/` salvo archivos nuevos.
- M2 Migraciones:
  - Dos archivos con el mismo número (`0002_a` y `0002_b`) chocan, y assist acepta `0001_otra.sql`.
  - Con CRLF y LF el checksum cambia y la migración parece editada.
  - Un `BEGIN`/`COMMIT` dentro del .sql rompe la atomicidad.
  → Rechazar números duplicados, exigir en assist el número siguiente al último y normalizar los saltos de línea antes del hash.
- M3 SQLite en FastAPI: store y auth usan dos locks distintos sobre una misma conexión, y `conn()` se inicializa sin lock. → Un lock compartido.
- M4 Auth generada:
  - Express bloquea el event loop con `pbkdf2Sync`. → Usar `crypto.pbkdf2` asíncrono.
  - Sin límite de intentos. → Rate limit.
  - El 409 de `/register` permite enumerar correos. → Respuesta genérica.
  - No hay logout. → Añadirlo y purgar los tokens caducados.
  - `timingSafeEqual` lanza una excepción con longitudes distintas. → Comprobar la longitud antes.
  - El email no se normaliza igual en Python y en Express. → Igualarlos.
- M5 Django: `SECRET_KEY` fija por defecto con DEBUG=0 en Docker, y la API es `csrf_exempt` y sin auth. → Abortar si falta `DJANGO_SECRET_KEY` en producción.
- M6 [V] El CI usa `npm ci`, pero sin `--verify` no hay package-lock, así que el CI falla siempre. → Usar `npm install` si no hay lock.
- M7 `npm install` y pip ejecutan scripts de terceros sin aislar. → `--ignore-scripts` cuando sea posible y un entorno aislado.

### Servidor, panel y CLI
- M8 cli.py `_profile_browsers`: la comparación por subcadena también mata `browser-profile2`. Además no se captura el TimeoutExpired.
  → Extraer `--user-data-dir`, normalizarlo y compararlo exacto. Volver a comprobar el PID antes de matar.
- M9 Un único `self.lock` cubre los análisis largos (Ghidra), así que el resto del panel se queda colgado. → Bloquear solo las escrituras en SQLite y ejecutar los análisis en segundo plano.
- M10 Accesibilidad:
  - Los objetivos son `<li onclick>` sin teclado.
  - La zona de soltar archivos no recibe foco.
  - `#chat-log` relee todo el historial cada 2 s.
  - Las pestañas no tienen `aria-controls`.
- M11 `max_assets` no tiene tope. → `min(..., 200)`.

### Puente
- M12 Carrera al reconectar: `getAdapter`, `page()` y `start()` no deduplican, así que pueden quedar dos ventanas o dos Chrome. Al reconectar se pierde el estado del adaptador.
  → Una promesa en curso por proveedor y un adaptador persistente.
- M13 `busy` es solo informativo. → Devolver 409 si el proveedor está ocupado.
- M14 Fuga de listeners en `loadURL`: falta `off`, el timeout no se limpia y no se filtra por `loaderId`.
- M15 `sendInputEvent` sin `await` (deepseek y gemini).
- M16 Segunda instancia: `app.quit()` no corta el código y puede borrar bridge.json de la primera. → `app.exit(0)` y borrar solo si el PID coincide.
- M17 El diálogo de aprobación muestra solo los primeros 600 caracteres; «Permitir 30 min» cubre todo el proveedor.
  → Avisar de los «N caracteres ocultos» y limitar el permiso a la conversación.
- M18 El origen no se vuelve a comprobar justo antes de escribir (redirección a accounts.google.com).
- M19 Selectores frágiles:
  - Dependen del idioma (DeepSeek «Leer en voz alta», Meta «Enviar»).
  - En Gemini, el regex `stop|detener|cancelar` coincide con cualquier botón.
  - En Gemini, el id de reserva depende del índice.

---

## Fase 3: Detalles (B)
- B1 La fuente del CSS ajeno se mete en tokens.css sin lista blanca (templates.py:247).
- B2 `render_jsx/vue/svelte` no escapan los atributos (hoy son literales).
- B3 llm.py: `--base-url` envía la clave a cualquier host, incluso por http y en redirecciones.
- B4 `com.eolfi.<slug>` puede ser una palabra reservada de Java. El APK no permite HTTP en claro hacia la LAN.
- B5 El timeout de verify no mata a los procesos nietos en Windows (npm.cmd → node). → `taskkill /T`.
- B6 server.py:
  - Se guarda la subida antes de validar `mode`.
  - Doble `unquote`.
  - Un cuerpo que no es objeto da 500.
  - Con 0.0.0.0, los clientes remotos reciben 421.
- B7 app.js:
  - `renderSummary` sin try/catch.
  - `#path-go` permite envíos dobles.
  - La comparación localiza su resultado por subcadena.
  - Recargas de la captura solapadas.
- B8 Puente:
  - Se acepta `t.url.startsWith(origin)`. → Usar `new URL().origin`.
  - `submitted` se marca antes del clic en Meta.
  - /v1/screen reabre ventanas.
  - login.lock huérfano.
  - Hasta 35 MB de historial.
  - `since=NaN` no da error.

---

## Fase 4: Pruebas que faltan
- Prueba paramétrica de «nombres hostiles» (título y recursos) en los 9 destinos. Debe comprobar que `ast.parse`, `tsc` y `manage.py check` pasan.
- Migraciones con número duplicado o CRLF. Límites de prefijo en `_allowed` de assist.
- Auth: enumeración de usuarios, fuerza bruta y caducidad real del token.
- cli.py: `_profile_browsers` con una salida de PowerShell simulada (incluido `browser-profile2`).
- Servidor:
  - 413, Host `[::1]`, cuerpo que no es objeto.
  - `/api/compare`, `/api/repo`, `/api/fs/list`.
  - Copia de seguridad al escribir en origen.
- Puente: saltar la aprobación con `source:"panel"` y con /v1/input, envío tras abortar, `page()` concurrente.
- Panel: prueba estática que falle si aparece `innerHTML` en app.js.

## Fase 5: Implementaciones propuestas
1. Tareas largas (triage deep, create, verify) en segundo plano con id y progreso por SSE.
2. Raíces permitidas configurables para `/api/triage` y `/api/create`.
3. Verify y assist aislados: env mínimo, carpeta limpia y, si se puede, un contenedor.
4. Separar capacidades en el puente: token de Eolfi solo para chat con aprobación y credencial del panel para la entrada directa.
5. Pasada de accesibilidad (axe) sobre el panel.

---

## Core y providers (parsers y modelo de evidencias)
Estos puntos también van en la Fase 1 (A) y la Fase 2 (M):
- **A12 [V] Bomba de memoria en el string pool de AXML/ARSC** (axml.py:56-74). Muchas entradas apuntan a la misma cadena enorme:
  608 KB → 600M de caracteres y, en el peor caso, unos 60 GB.
  → Cada cadena debe quedar dentro del chunk; memoizar por offset y fijar un presupuesto de bytes decodificados.
- **A13 [V] DoS de CPU por la entropía de secciones solapadas.**
  - Mach-O: `nsects` no se valida contra `cmdsize`; 273 KB tardan 7 s.
  - ELF: 1 MB tarda 20 s.
  → Validar `nsects`, poner un tope global de secciones, cachear por (off, len) y fijar un presupuesto de bytes hasheados.
- **A14 Inyección de comandos en Windows** (external.py).
  - `analyzeHeadless.bat` pasa por cmd.exe, que interpreta `& | ^ %` (BatBadBut).
  - Con capa/rizin, un archivo cuyo nombre empieza por `-` se toma como opción.
  → Analizar una copia `<sha256>.bin` con ruta absoluta, sin .bat, y validar los argumentos.
- **A15 [V] Un APK con el bit de cifrado falso tumba el inventario** (dex.py:142, 269): RuntimeError, NotImplementedError o EOFError sin capturar.
  → Capturarlas por entrada y marcarla como `encrypted/unsupported`.
- M20 [V] Un `@0xZZZZ` en el manifiesto da ValueError en arsc.py:149. → Regex `^@0x[0-9a-fA-F]{8}$`.
- M21 El `evidence_id` no cubre authority, confidence, limitations ni provider_version, así que un paquete importado puede subir la autoridad.
  → Incluirlos en el hash y validar los enums.
- M22 `incognita_id` solo usa (subject, question): un conflicto repetido no reabre una incógnita resuelta. → Fusionar y reabrir.
- M23 Las incógnitas y evidencias importadas no se validan, lo que rompe la exportación a SARIF/STIX.
- M24 AXML: los atributos no se comprueban contra `csize`, y el corte por MAX_NODES es silencioso con confianza «high». → Añadir un flag `truncated`.
- M25 dex.py y strings.py leen el archivo entero en memoria, sin límite. → Límite de tamaño y mmap.
- M26 external.py: un JSON que no es dict ni lista da AttributeError, y no se comprueba el returncode de rizin.
- B9:
  - `symbol_errors` de Mach-O nunca se emite.
  - El texto de limitations de dex es obsoleto.
  - Rizin firma igual aunque se use radare2.
  - En binarios fat, las lecturas pueden salirse del slice.
  - En STIX salen SCO duplicados y el id del bundle no es determinista.
  - Código muerto.
  - `sarif.py` es O(n²).
  - Hay un commit por cada evidencia.
- Pruebas: fuzz con límites de tiempo y memoria en todos los formatos (Mach-O fat, DEX, AXML, ARSC, ZIP cifrado), con los PoC como regresión.
  Faltan también pruebas de import/export de paquetes hostiles.
- Mejora: un Reader común con presupuesto (bytes e iteraciones) y un esquema `errors/truncated` que baje la confianza.

## Sites y flows (descargas web, repos, diff, compare, create)
- **A16 [V] DoS cuadrático en PageParser**: con `<button>`/`<label>` sin cerrar, 18 KB tardan 36 s (webpage.py:146-150, 203-206).
  → Tope de capturas abiertas y contador de longitud por captura.
- **A17 [V] Regex de comentarios CSS cuadrática**: 30 KB de `/*a` tardan 1,5 s (webpage.py:260). → Escanear con `str.find` y limitar el tamaño.
- **A18 DNS rebinding / TOCTOU en fetch**: se resuelve el nombre para comprobarlo y luego urllib lo vuelve a resolver.
  → Resolver una vez y conectar a esa IP fijada (Host/SNI originales), o comprobar `getpeername()`.
- **A19 `clone` sin anti-SSRF**: acepta `http://169.254.169.254/...` y git sigue redirecciones.
  → Solo https/ssh, validar el host como en fetch, `http.followRedirects=false` y protocolos en lista blanca.
- **A20 [V] Un manifiesto hostil tumba el análisis**: `dependencies` como lista, JSON muy anidado o composer.json en forma de lista.
  → `isinstance` y `try/except` por manifiesto, registrándolo en `errors`.
- M27 Los symlinks de archivos en carpetas locales se siguen fuera de la raíz (README.md → ~/.ssh) y no se comprueban las junctions. → Saltarlos o exigir `resolve()` dentro de la raíz.
- M28 `_git_info` ejecuta git con el `.git/config` del repo analizado. → `-c core.fsmonitor=false`, `GIT_CONFIG_NOSYSTEM=1`, o leer HEAD a mano.
- M29 Clonado: destino fijo (dos análisis a la vez se pisan), `TimeoutExpired` sin capturar y sin límite de tamaño. → `mkdtemp`, limpieza y `--filter=blob:limit`.
- M30 Se pierden los `Set-Cookie` repetidos. → `get_all`.
- M31 [V] `_save` falla con `/a` y `/a/b.css`, y acepta CON/NUL. → Capturar `OSError` y renombrar.
- M32 diff_flow: la incógnita usa la clave `inp.name`, así que se mezclan entradas de distintas carpetas; además `capture_output` no tiene tope. → Ruta relativa, Popen con límite y matar el árbol de procesos.
- M33 create_flow:
  - Con `guess_folder` un nombre suelto («src») puede resolver a `D:\src` y escribir encima.
  - `copytree` sigue symlinks.
  → Confirmación explícita al escribir en el origen y `copytree(symlinks=True)`.
- M34 `learn` mantiene el lock del servidor durante clonados de hasta 600 s (igual que M9).
- B10 fetch:
  - `gaierror` se trata como «no privado» y CGNAT 100.64/10 no se bloquea. → Usar `not ip.is_global`.
  - Un 5xx en robots.txt se toma como «permitir todo».
  - Las redirecciones no se validan.
  - No hay plazo total por petición.
- B11 Rendimiento con repos grandes: los archivos se leen enteros solo para contar líneas y se hace `stat` doble.
- B12 compare/triage:
  - El orden «más reciente» no tiene desempate.
  - `_set_diff` falla con elementos no hashables y `summarize` lanza KeyError.
  - Colisión por truncar el subject a 24 caracteres.
  - `classify` toma una query con «github.com/» por un repositorio.
- Pruebas que faltan:
  - fetch: redirección a IP privada, rebinding, robots 5xx y timeouts.
  - Git: URLs hostiles.
  - Archivos: symlinks y `_save` con colisiones.
  - Entradas: manifiestos malformados y HTML/CSS patológico (debe terminar en menos de 2 s).

## Ya hecho en esta sesión (fuera de la auditoría)
- Botón «Analizar» en el panel. Las fuentes por nombre («Alejandria») se resuelven a la carpeta.
- Escribir en la carpeta de origen está permitido con copia de seguridad automática `<carpeta>.eolfi-backup-<fecha>`.
  Mitigación de A4 ya aplicada: en ese modo se omite la verificación automática. Queda pendiente la solución completa: verificar en una copia limpia.
- Selector desplegable de carpetas (📁) en «Analizar», en «Fuentes» (añade una línea) y en «Carpeta destino». Endpoint `/api/fs/list`.
