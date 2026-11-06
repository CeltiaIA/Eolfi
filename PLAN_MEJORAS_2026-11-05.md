# Eolfi: segunda auditoría y plan de correcciones, implementaciones y mejoras

> **Documento histórico:** conserva los hallazgos y cierres de la auditoría del 2026-11-05. El backlog activo está en [PLAN_INGENIERIA_INVERSA_EOLFI.md](PLAN_INGENIERIA_INVERSA_EOLFI.md); consulta este archivo como registro de correcciones anteriores.

Fecha: 2026-11-05. Seis agentes revisaron Eolfi carpeta por carpeta y archivo por archivo, en modo solo lectura.
Uno de ellos hizo además una comprobación funcional en vivo del panel con las herramientas REA. La primera
auditoría y sus correcciones están en `PLAN_CORRECCIONES.md`; aquí solo figura lo que queda o lo nuevo.

Prioridad: **A** alta · **M** media · **B** baja. Esfuerzo estimado entre paréntesis.

---

## Puente de chats (`eolfi/bridge`)

Estado: 27 pruebas superadas y 1 omitida (navegador real).

### Correcciones
- **A1. Una aprobación caducada todavía puede dar permiso.**
  - El diálogo sigue abierto tras los 2 min. Si luego se pulsa «Permitir 30 min», se activa `allowUntil` en silencio.
  - El proveedor queda `busy` (409) mientras el diálogo esté abierto.
  - → Pasar a `approve` un `AbortSignal` (cancelación más plazo) para cerrar el diálogo e ignorar las respuestas que llegan tarde.
- **A2. Los envíos pueden ir a la conversación equivocada.**
  - Ocurre si el usuario cerró la pestaña (al reabrirla `current` sigue igual) o si navegó a otro chat desde la vista en directo.
  - → En cada envío, comparar `getURL()` con la URL de la conversación y poner `current = null` al cambiar de pestaña.
- **A3. CRLF en los prompts.** En DeepSeek y Meta la comparación exacta del texto escrito falla con saltos `\r\n`.
  → Normalizar antes de enviar y comparar con `normalize()`.
- **A4. Errores que tumban el puente.** `spawn` del navegador no tiene `'error'` (EACCES o ENOENT tumban Electron) y
  `JSON.parse` de la tubería no tiene `try`.
- **M1. La vista en directo reabre lo que el usuario cerró.** `/v1/screen` y `/v1/input` reabren pestañas o Chrome.
  → Usar `peek` y responder 404 «ventana cerrada».
- **M2. Captura cara.**
  - Resolución completa según el DPR, sin escalar.
  - Una evaluación extra por fotograma.
  - Peticiones no agrupadas.
  - Búsqueda de `\0` cuadrática en la tubería.
  - → `clip.scale` o screencast, caché y búsqueda incremental.
- **M3. «Dudoso» permanente.** Un plazo agotado bloquea esa conversación para siempre.
  → `POST /v1/reset` o que llm.py rote de conversación; plazo configurable (DeepThink supera los 240 s).
- **M4. Detección del final de respuesta frágil.**
  - Gemini reconoce el botón de parar por un regex en es/en.
  - DeepSeek depende de una clase CSS.
  - → Varias señales: icono, estado del botón de enviar y texto estable.
- **M5. Listas virtualizadas.** En DeepSeek la fila con la referencia puede salir del DOM; en Gemini el id de reserva
  va por índice.
- **M6. Gemini guarda `/app` como URL de la conversación.** → Exigir `/app/<id>`.
- **M7. Errores mal reportados.**
  - El plazo de aprobación agotado se informa como «denegado» → usar 408.
  - El 413 destruye la conexión antes de responder.
- **M8. Arranque lento.** El servidor espera a abrir las 3 pestañas en serie antes de escuchar → escuchar primero y abrir en paralelo.
- **M9. «Permitir 30 min» vale para todo el proveedor.** No es visible ni revocable.
  → Limitarlo por conversación y mostrarlo en `/v1/status`.
- **B1–B7.**
  - B1: `panelToken` obligatorio, sin modo heredado.
  - B2: `/v1/input` lee con O(n²) y no comprueba `busy`.
  - B3: `KEYS.Enter` con `char` (riesgo de doble envío en Gemini) y `KEYS['__proto__']` → usar `Object.hasOwn`.
  - B4: los handlers de sesión no se quitan al cerrar.
  - B5: `status()` de Meta hace clic en la página.
  - B6: `app.exit(2)` no corta el módulo.
  - B7: `bridge.json` no se escribe de forma atómica ni tiene ACL.
- **Pruebas que faltan:**
  - `send()` con un DOM falso: dudoso, cancelación tras escribir, CRLF, cambio de pestaña.
  - Plazo de aprobación inyectable.
  - Tramas de `PipeConnection`.
  - `loadURL` con `loaderId`.
  - 413, 421 y `since` inválido.
  - Sacar `approve` y `getAdapter` de main.mjs a un módulo que se pueda probar.

### Mejoras e implementaciones
1. **Streaming de respuestas al panel** por SSE o eventos parciales; además evita plazos agotados (2-3 días).
2. **Adaptador declarativo** con selectores alternativos, autodiagnóstico `GET /v1/selftest` y modo «recalibrar» (3-4 días).
3. **Más chats: ChatGPT, Claude.ai, Copilot y Le Chat**, de 0,5 a 1 día por sitio sobre el punto 2.
4. **Comparativa multi-chat**: una sola aprobación, envíos en paralelo y vista lado a lado; útil para votar el JSON de la IA (2 días).
5. **Historial persistente** (`~/.eolfi/bridge-history.jsonl`) con el mapa de conversación a URL (1 día).
6. **Adjuntar archivos** (`DOM.setFileInputFiles`) con lista blanca y aprobación (2 días).
7. **Vista en directo por screencast** con ETag/304 (1 día).
8. **Permisos finos y revocables desde el panel** (0,5 días).

---

## Servidor, panel, CLI y empaquetado (`server.py`, `web/`, `cli.py`, `pyproject.toml`, `tests/`)

Estado: 154 pruebas superadas y 1 omitida.

### Correcciones
- **A1. `create --db memory|sqlite` pisa el `--db` global** (la ruta de la base de evidencias), porque los dos usan el
  mismo `dest`.
  - Las evidencias de `create` acaban en `D:\Eolfi\memory` o `D:\Eolfi\sqlite`, que ya existen, y el panel no las ve.
  - → Renombrar a `dest="backend_db"`, migrar esas dos bases a `eolfi.db` y añadir una prueba de `cli.main`.
- **A2. Respuestas desordenadas al elegir objetivos.** `selectSubject` no descarta las respuestas viejas: con dos
  clics rápidos, las evidencias de A pueden salir con el título de B. → Contador de petición o AbortController.
- **A3. Eventos del chat duplicados.** `pollBridge` puede quedar con dos bucles a la vez.
  → Bandera `inFlight` y deduplicar por `id`.
- **A4. La subida no usa trabajos.** `/api/upload` es síncrono y lee hasta 256 MB en RAM, sin progreso; además la
  zona de soltar permite subir dos veces. → Escritura por bloques con hash incremental y triaje como trabajo.
- **M1. Nombres de carpeta con caracteres no ASCII** («Árbol» pasa a «rbol»; «日本語» da un 409 confuso).
  → Normalizar con unicodedata y usar un nombre por defecto con fecha si queda vacío.
- **M2. Trabajos sin control.**
  - Sin límite de concurrencia, cancelación ni listado.
  - Esperas silenciosas cuando dos trabajos usan la misma clave.
  - `--reload` mata los trabajos en curso.
  - → Semáforo, estado «en cola», DELETE y aviso antes de reiniciar.
- **M3. `subjects()` lento.** Hace N+1 consultas, lee `index.json` por cada objetivo y `incognita` no tiene índice
  por `subject`. → Una consulta con GROUP BY y `idx_inc_subject`.
- **M4. Evidencias pesadas en el panel.**
  - Se pintan todas y se serializan los JSON aunque estén cerrados.
  - El filtro repinta en cada tecla.
  - La API no pagina.
  - → Cuerpo al abrir cada evidencia, filtro con retardo y `limit/offset/q`.
- **M5. `/api/providers` tarda.** Llama a `probe()` dos veces por preajuste y en serie; con el puente colgado puede
  tardar unos 2 min. → Una llamada por preajuste, en paralelo y con caché de unos 30 s.
- **M6. GET cross-site sin filtrar.**
  - `<img src=…/api/bridge/screen>` desde otra web dispara capturas.
  - No hay cabecera CORP.
  - `?token=` aparece en el registro.
  - → Rechazar `Sec-Fetch-Site: cross-site` también en GET, `CORP: same-origin`, quitar el token del log y redirigir.
- **M7. Diferencias entre CLI y panel.**
  - El panel no tiene `max_assets`, `cross_origin`, `--save`, `--ignore-robots`, `--reanalyze`, `--model` ni
    `--base-url` (el servidor ignora `ai_base_url` y `reanalyze`).
  - Tampoco tiene `assist`, `diff`, `import`, `decompile` ni `resilience`.
  - A la IA del panel le falta `openai`.
  - La CLI no tiene `triage --providers` ni analiza carpetas como repositorio.
- **M8. Empaquetado.**
  - El extra `analysis` (capstone, angr) no se usa.
  - El puente usa `electron: latest`, sin lockfile en package-data.
  - `npm install` escribe en site-packages.
  - La versión está duplicada y faltan license, urls y classifiers.
  - `egg-info` está obsoleto.
- **M9. Documentación desactualizada.**
  - El README no recoge `/api/jobs`, `/api/fs/list`, `/api/bridge/*`, `providers`, el token remoto, `--root` ni
    los límites.
  - El docstring de cli.py no incluye `assist`, `bridge`, `corpus` ni `serve --root`.
- **B1. Accesibilidad.**
  - `h2.focus()` sin `tabindex`.
  - El selector de carpetas no se cierra con Esc ni mueve el foco.
  - Los puntos de estado del chat solo se distinguen por color.
  - Las pestañas no tienen `tabpanel`.
  - Destello del tema al cargar: aplicarlo desde `<head>`.
- **B2.** La confirmación depende del texto «Confirmación necesaria» → campo `needs_confirm`.
- **B3.** Una selección de proveedores guardada no se ve en «Analizar» y, si es obsoleta, da 400 sin opción de restablecerla.
- **B4. Otros.**
  - URL `0.0.0.0` impresa con el token.
  - `D:\Alejandria` fijo en la CLI.
  - `index.json` no atómico.
  - `cursor: progress` en todos los botones desactivados y `.small-btn` duplicado.
- **Pruebas que faltan:**
  - `cli.main`.
  - e2e del panel y axe en CI (con axe-core fijado).
  - Cookie del token.
  - `/api/providers`.
  - Subida con `providers`.
  - Expulsión de trabajos.
  - Pruebas que dependen de la carpeta actual o de las unidades del equipo.
  - Sondeos de hasta 20 s.

### Mejoras e implementaciones
1. **Evidencias paginadas con búsqueda en servidor** (FTS5) y filtros por confianza y autoridad (1-2 días).
2. **Pestaña «Trabajos»**: cola con concurrencia, cancelación, historial en SQLite y repetir (2 días).
3. **Informe exportable por objetivo**: HTML autocontenido y PDF; SARIF, STIX y JSON filtrados (1-2 días).
4. **Gráficos SVG propios**: entropía por sección, evidencias por proveedor, línea temporal y diferencias (M).
5. **Igualar CLI y panel**: opciones avanzadas, `assist` sobre proyectos existentes, importar paquete y `triage --providers`, con una tabla de opciones compartida (M).
6. **Atajos de teclado** y navegación por hash con el botón Atrás (medio día).
7. **i18n es/en** en el panel, los mensajes de la API y la CLI (3 días).
8. **Empaquetado e instalador**: versión única, Electron fijado, puente en `~/.eolfi`, pipx o PyInstaller con acceso directo, `eolfi update --check` y CI completa (M-L).

---

## Comprobación funcional en vivo con REA (panel)

Método:
- 4 escenarios Playwright reales (`capture_browser_scenario`).
- Manejadores de eventos revisados con `inspect_web_event_listeners`.
- Lectura de `app.js`/`index.html` y peticiones GET.

Reglas que se respetaron: no se envió nada a los chats, no se pulsó «Resolver» y no se creó ningún proyecto.

**Resultado: 0 errores de consola, 0 errores de página y 0 peticiones fallidas.**
- Funcionan bien:
  - las pestañas;
  - «Analizar archivo» sin archivo;
  - los 3 selectores 📁;
  - «Crear» con fuentes vacías;
  - Proveedores (presets y tema);
  - el tema de la cabecera;
  - Chats web (estado, vista en directo, pestañas, «Nueva conversación»);
  - las 3 exportaciones (200, menos de 65 ms).
- La API responde en menos de 35 ms; `/api/providers` es lo más lento (155–180 ms).

### Fallos
- **M10. El clic se pierde con un selector de carpetas abierto.** El selector se cierra en `mousedown`, el contenido sube
  y el `click` cae en otro sitio: «Crear» no hace nada.
  → Cerrar con `click` en fase de captura o `position:absolute`, y cerrar con Esc.
- **M11. Navegación entre vistas incoherente.**
  - De Proveedores a Chats, la cabecera solo muestra «Análisis».
  - Con Proveedores abierto, al elegir un objetivo se ven las dos vistas a la vez.
  - → Una única función `showView('content'|'chats'|'providers'|'empty')`.
- **B5.** `#chat-live` sigue anunciando el último mensaje de Meta tras cambiar a Gemini → vaciarlo en `selectChat()`.
- **B6. Accesibilidad.**
  - Las 14 casillas de objetivos se llaman todas igual → incluir el nombre del objetivo.
  - La zona de soltar no tiene `role=button`.
  - «Resolver» no dice qué incógnita resuelve.
  - El emoji 📁 se lee como parte del nombre → `aria-hidden`.
- **B7.** «Analizar» con la ruta vacía no avisa. El placeholder inicial de `#path` no coincide con el de la pestaña Binario.
- **B8.** La vista en directo (1,5 s por imagen) y el sondeo siguen activos con la pestaña del navegador en segundo plano
  → pausar con `document.visibilityState`.

### Mejoras de uso
1. Aviso con los campos vacíos y desactivar «Analizar» y «Crear» mientras falten datos.
2. Recordar la última vista y pestaña (hash) y llevar el foco al título al cambiar de vista.
3. En el selector de carpetas: Esc para cerrar, Intro para elegir y empezar en la última carpeta usada.
4. Aviso al exportar y opción de exportar solo el objetivo seleccionado.
5. Nota «(elegido en Proveedores)» junto al selector de IA de «Crear».

---

## Core, providers y security (parsers y modelo de evidencias)

Estado: 154 pruebas superadas. `[V]` = el agente lo reprodujo con scripts propios.

### Correcciones
- **A5 [V]. ARSC sparse.** El índice se lee contra el archivo entero y no contra su chunk. Unos 0,1 s por chunk:
  1 MB tarda unos 15 min, y el tope de 64 MB, horas. → Exigir `index+4*count ≤ off+csize` y un presupuesto global
  de iteraciones.
- **A6 [V]. String pool AXML/ARSC.** La tabla de offsets no se comprueba dentro del pool: muchos pools pequeños con
  `header_size` grande dan 7,8 s con 800 KB, y los aciertos de memo no consumen presupuesto.
  → `header_size+4*count ≤ strings_start ≤ size` y un presupuesto global de entradas por documento.
- **A7 [V]. Evasión del manifiesto.** Si `raw` apunta a una cadena se usa aunque haya un valor tipado; Android usa el
  tipado. Con `debuggable` = true y raw "false", Eolfi informa «false» y oculta `debuggable`, `exported` y
  `usesCleartextTraffic`. → Usar raw solo si `dtype==0x03` y registrar la discrepancia como «manifiesto manipulado».
- **A8. Timeout de Ghidra o capa en Windows.** Solo se mata el `.bat`; la JVM sigue viva y queda la copia
  `<sha256>.bin`. → `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F` (en POSIX, `killpg`).
- **M12 [V]. Mach-O universal arm64 + arm64e.** Se indexa por `cpu` y una arquitectura pisa a la otra
  → clave `cpu[/subtipo]#i`.
- **M13. Presupuesto de entropía multiplicado.** Se crea uno por slice: un fat de 16 slices tiene 16× el presupuesto
  → un único presupuesto compartido.
- **M14 [V]. Evidencias enormes de cadenas.** La muestra guarda cadenas completas (20 cadenas de 1 MB = una evidencia
  de 19 MB) → truncar cada cadena y poner un tope total.
- **M15 [V]. Importaciones PE sin tope total.** 256 descriptores compartidos dan 366 000 nombres (5,9 MB)
  → tope global, deduplicar y cachear `rva_to_off`.
- **M16 [V]. Fechas inválidas al importar.** `created_at=1e300` hace caer STIX; `NaN` se guarda como NULL y el recuento
  miente. → `isfinite` y rango; validar `links` y los tipos.
- **M17 [V]. Paquetes anidados o enormes.** `import_package` da `RecursionError` con JSON muy anidado y no limita el
  tamaño → tope de bytes y capturar como `ValueError`.
- **M18. Incoherencias del modelo al importar.**
  - Las evidencias importadas no pasan por el cruce de confianza.
  - Las incógnitas importadas que ya existen no se fusionan.
  - Puede haber referencias a ids inexistentes.
- **M19 [V]. Exportación STIX frágil.** Cae con `attack` que no son cadenas y con `names[subject]==[]`.
- **M20. APK con entradas duplicadas o rutas `../`** (tipo Janus): Eolfi lee una y Android otra → hallazgo de seguridad.
- **M21. Proveedores compartidos entre análisis paralelos.** Son instancias globales con `self.version` mutable: una
  evidencia puede quedar con la versión de otra ejecución.
- **B9–B16.**
  - B9: la limitación de `archive_inventory` está desactualizada y el directorio central se carga entero antes del tope.
  - B10: el Reader de Mach-O cubre el archivo entero y no el slice; LC_MAIN/LC_UUID leen más allá de `cmdsize`;
    hay variables sombreadas.
  - B11: `_last_json` sin respaldo; `check_cmd_safe` rechaza `%TEMP%` con `(` o `&` también para capa y rizin;
    `os.link` comparte inodo.
  - B12: falta `isinstance(doc, dict)` en Ghidra y hay namespaces de capa no hashables.
  - B13: resilience usa `Path.name` como subject, carga el archivo 3× en memoria, el patrón `base64,` da muchos
    falsos positivos y deja carpetas huérfanas.
  - B14: triage no reconoce Mach-O big-endian ni fat64.
  - B15: la incógnita «proveedor no disponible» no se cierra nunca y la de «falló» se duplica en cada ejecución.
  - B16: ASLR marcado aunque falten las relocalizaciones; los `provider` con targetSdk < 17 son exportados por defecto.
- **Pruebas que faltan:**
  - `fuzz_file`, `prompt_injection_scan`, cadenas que cruzan bloques, `_last_json` y `_slim_functions`.
  - Fat Mach-O con varias arquitecturas, ARSC sparse y OFFSET16, y STIX/SARIF con paquetes hostiles.
  - Regresiones de A5–A7, M12, M14–M16.
  - Un fuzz dirigido a estructuras repetidas: el de mutación no encuentra estos casos.

### Mejoras e implementaciones
1. **Authenticode PE** (firmante, emisor, digest), imphash, Rich header, TLS y VERSIONINFO (2-3 días).
2. **.NET/CLR**: metadatos, AssemblyRef, runtime, ofuscadores y single-file/R2R (3-4 días).
3. **IPA/iOS**: Info.plist, firma de código (entitlements, Team ID), mobileprovision y `cryptid` (3 días).
4. **Java class/JAR**: constant pool, MANIFEST y Spring Boot (2 días).
5. **ELF de Android dentro del APK** (`lib/<abi>/*.so`): JNI, exports `Java_*`, alineación de 16 KB y build-id (1-2 días).
6. **WebAssembly**: secciones, imports/exports, `name` y producers (1-2 días).
7. **Firma APK v2/v3/v4** y DEX completo (3 días).
8. **`ParseBudget` común** (bytes, iteraciones y tiempo) y proveedores locales en subproceso con límites de memoria y tiempo (2 días).

---

## Generador de proyectos (`eolfi/generador`)

El agente generó los 13 destinos (con `--auth` y `--db sqlite`) en una carpeta temporal. `[V]` = reproducido.

### Correcciones
- **A9. Verify se cuelga en Linux y macOS.** `_kill_tree` solo mata al hijo directo; el nieto (node, vite…) mantiene
  las tuberías abiertas y `communicate()` espera para siempre.
  → `start_new_session=True` + `killpg`, y `communicate(timeout=5)` después de matar.
- **A10. El código que escribe la IA se ejecuta con acceso a tu disco y a la red.** HOME sigue apuntando a tu
  carpeta: una inyección de prompt podría leer `~/.eolfi/bridge.json` o `~/.ssh` desde una prueba.
  → Mostrar el diff y pedir confirmación antes de verificar; HOME, APPDATA y USERPROFILE temporales; modo contenedor
  sin red.
- **A11. Sin cabeceras de seguridad en los destinos web.** No hay CSP, nosniff, frame-ancestors ni Referrer-Policy en
  static, react, vue, svelte, next, fastapi ni express. → Middleware propio, `headers()` en Next, `<meta>` CSP y
  pruebas generadas que lo comprueben.
- **A12 [V]. Nombres de paquete inválidos o que chocan.** En CLI, `--name class` da SyntaxError y `--name json` tapa
  el `json` estándar. En .NET, `System` o `Avalonia` chocan con el framework.
  → Rechazar palabras clave y módulos de la librería estándar (prefijo `app_`).
- **A13 [V]. Contraste insuficiente.** Texto blanco sobre el primario observado: con #fde047 sale 1,3:1. El foco da
  2,1:1. → Elegir el color del texto por luminancia, oscurecer el primario y el acento, y una prueba.
- **M22. Respuestas de la IA no validadas.** Si el JSON tiene tipos inválidos o hay una excepción o Ctrl+C, no se
  restauran los archivos. → Validar con el esquema y `try/finally: _restore`.
- **M23. Cada ronda de IA repite toda la instalación.** `install=False` se ignora en dotnet, desktop, expo y tauri:
  cada ronda vuelve a instalar, compilar y publicar.
- **M24. La IA puede debilitar las pruebas de seguridad.** Hoy puede editar las pruebas de seguridad, `auth.js` o
  `auth.py`. → Ponerlos en solo lectura o rechazar respuestas que borren aserciones.
- **M25. LLM frágil y sin control de coste.**
  - Sin reintentos ante 429, 5xx ni timeout.
  - Sin presupuesto de tokens o coste.
  - `read()` sin límite de tamaño.
- **M26. Versiones NuGet y pip sin fijar en silencio.** `pin_nuget_versions` y `pip freeze` parsean una salida
  recortada a 2 500 caracteres; si se pasa, no fijan nada y no avisan.
- **M27. Pruebas de humo sin control de tiempo.** En dotnet, el plazo no mata el árbol de procesos y lanza un
  traceback; en tauri no hay plazo.
- **M28. Auth generada.**
  - El mapa `failures` crece sin límite.
  - No hay límite por IP en /register ni en /login (cada petición cuesta un PBKDF2).
  - → Límite por IP con ventana deslizante y LRU.
- **M29. Django inseguro por defecto.** `DEBUG=1` por defecto y sin `SECURE_*` (SSL, HSTS, cookies Secure) en producción.
- **M30. Express sin manejador de errores.** Un JSON mal formado devuelve HTML con la traza.
- **M31. Electron.** `loadFile` sobre file://, `connect-src https:` innecesario y sin `@electron/fuses`.
  → `protocol.handle("app")` y fuses.
- **B17–B20.**
  - B17: un nombre con «:» se trata como ruta («Test: app» → «app»).
  - B18: el formulario de contacto dice «¡Gracias!» sin enviar nada; falta «Saltar al contenido» y `aria-pressed`
    en el botón de tema.
  - B19: `llm.py` acepta `http://127.0.0.1:80@evil.com` como dirección del puente → `urlsplit` y exigir el host.
  - B20: `>=` en requirements.txt sin lock; KeyError en FreeBSD y StopIteration si falta el .csproj.
- **Pruebas que faltan:**
  - `_kill_tree` en POSIX y `pin_nuget_versions` con salida larga.
  - Respuesta de IA inválida y reintentos.
  - Nombres que son palabras clave o módulos estándar.
  - Contraste de la paleta y cabeceras de seguridad.

### Mejoras e implementaciones
1. **CSP y cabeceras de seguridad en los 13 destinos**, con pruebas generadas (1-2 días).
2. **Sandbox de verificación**: HOME temporal, diff revisable y Docker sin red (3 días).
3. **Pruebas e2e generadas** con Playwright y axe-core (web, desktop y expo web) (3-4 días).
4. **Despliegue**: Dockerfile multi-stage sin root, fly.toml o vercel.json y healthcheck (2 días).
5. **i18n es/en y PWA** en los destinos web (3 días).
6. **IA robusta**: reintentos, presupuesto, caché de prompt, vista previa del diff y validación (2 días).
7. **Observabilidad** en los backends: logs JSON con request-id, `/api/metrics` y OpenTelemetry opcional (1-2 días).
8. **Backends Go y Rust** y `eolfi sync` (vuelve a analizar las fuentes y propone un diff con merge a tres bandas) (1-2 semanas).

---

## Sites, flows y corpus (`eolfi/sites`, `eolfi/flows`, `eolfi/corpus.py`)

`[V]` = el agente lo reprodujo con pruebas de concepto propias.

### Correcciones
- **A14 [V]. Ejecución de código al analizar un repo local.** Con `log.showSignature=true` y `gpg.program=<malicioso>`
  en el `.git/config` del repo, `git log -1` ejecuta el programa del atacante (llegó a crear `pwned.txt`).
  → `-c log.showSignature=false --no-show-signature -c gpg.program=false…`; mejor aún, leer HEAD y refs sin git.
- **A15 [V]. DoS cuadrático por `^\s*` con `re.M`** con miles de saltos de línea.
  - JS: 40 000 «\n» tardan 12,8 s.
  - go.mod: 31 s.
  - Gemfile: 4,3 s.
  - Dockerfile: 10,6 s.
  - → Usar `^[ \t]*`.
- **A16 [V]. Regex `_VAR_DEF` casi cuadrática.** 2 MB de «-» tardan 5,7 s → lookbehind o `str.find`.
- **A17 [V]. El plazo total no cubre las cabeceras.** Un servidor que envía una cabecera byte a byte alargó la
  petición a 8 s con un plazo de 3 s → controlar el plazo en cada `recv` o un watchdog.
- **A18. Escritura sobre el origen sin copia de seguridad.** Si la fuente se resolvió por nombre de objetivo
  («Alejandria» → `repo:D:\Alejandria`), no se detecta que coincide con el destino; con `force` se escribe sin copia y
  se verifica allí. → Sacar la ruta del subject; con `force` y verify, verificar siempre en una copia limpia.
- **M32 [V]. Cookies mal atribuidas.** `fetch` une los Set-Cookie con « | » y el informe los separa por comas, así que
  los atributos de una cookie se atribuyen a otra → guardar una lista.
- **M33. Clones sin límite.** No hay tope de tamaño ni limpieza global de `samples/repos` → `--filter=blob:limit` y TTL.
- **M34. Clon por SSH con tu entorno** (~/.ssh/config, agente y claves) frente a hosts arbitrarios
  → `GIT_SSH_COMMAND="ssh -F none -o BatchMode=yes -o IdentitiesOnly=yes…"`.
- **M35. Lecturas sin límite en sitios locales.**
  - `DiskLoader.load` lee el archivo entero.
  - `rglob("*.html")` y `_collect_corpus` recorren todo el árbol (incluido `node_modules`).
  - → Leer con tope y recorrer con poda.
- **M36. diff da «equivalente» por error.** Solo compara los primeros 4 MB y los temporales no tienen tope
  → hash en streaming, marca `truncated` y matar al pasar de N MB.
- **M37 [V]. Detección de pila con fallos.**
  - go.mod: no detecta `require` en una sola línea.
  - csproj: no detecta UseWPF/UseWindowsForms/UseMaui, Sdk.Web ni CPM.
  - gradle: no detecta `libs.*` ni el plugin Android.
  - Flutter móvil sale como «Flutter Web».
  - `config.toml` se toma por Hugo y `_config.yml` por Jekyll.
  - Subcadenas que dan falsos positivos («echo», «junit», «jquery» en comentarios).
  - Se leen manifiestos de `examples/` y `fixtures/`.
  - `implies` no es transitivo.
- **M38. `summarize` del triaje sin protección.** Una evidencia importada incompleta tumba los triajes siguientes con
  KeyError.
- **M39. compare.** `sorted()` falla con tipos mezclados y `_dict_diff` copia listas enteras sin tope.
- **M40. Inyección en corpus.py.** PowerShell también cierra cadenas con las comillas tipográficas ‘ ’, así que una
  ruta con ’ permite inyectar comandos. Además, Audit solo recibe la primera fuente.
  → `-File` con argumentos en lista, sin `-Command`.
- **B21–B24.**
  - B21: un fallo de red en robots.txt se trata como «permitir todo»; se ignora `<meta charset>`.
  - B22: en diff, un nombre de entrada con `&` lo interpreta cmd.exe si el candidato es un `.bat`; además se ejecuta
    el candidato aunque falle la referencia.
  - B23: doble `stat` en repos grandes y monorepos sin `key_dependencies`.
  - B24: `resolve_subject` no reutiliza fuentes locales y `guess_folder` puede bloquearse con unidades de red.
- **Pruebas que faltan:**
  - Detección de pila y parsers de go.mod, csproj, gradle y pubspec.
  - `_headers_report`, DiskLoader, `guess_folder` y `backup_folder`.
  - `_git_info` con config hostil y solape origen/destino con un subject.
  - Tope del diff, plazo de cabeceras y regresiones con 5 MB de «\n».

### Mejoras e implementaciones
1. **Análisis de SPA renderizadas** con Chrome headless por tubería, sin perfil, con anti-SSRF por intercepción: DOM
   final, XHR reales, detección de frameworks y capturas (4-6 días).
2. **Sitemaps y crawling limitado** (N páginas, BFS), con inventario de plantillas de página (2-3 días).
3. **Más pilas y `app_kind` ponderado** con confianza: Rust, Go, Java/Kotlin/Android, .NET (Blazor, MAUI, WPF),
   Flutter por plataformas, Swift, Capacitor, Unity y Godot (3 días).
4. **Fusión de varias fuentes con autoridad** (el repo manda en la pila y la web en el diseño) y el origen de cada
   decisión (2 días).
5. **Informes HTML/Markdown** por análisis y comparación, con `--fail-on` para CI (1-2 días).
6. **Presupuesto común para el análisis de texto**: regex revisadas y fuzz de regresión (1 día).
7. **Source maps embebidos y manifiestos de build** (asset-manifest, `_next/build-manifest`, Vite) para obtener las rutas reales (1 día).
8. **`safe_git()` único y aislado** (0,5-1 día).

---

# Hoja de ruta propuesta

**Fase A: seguridad y bloqueos (primero)**
> **Estado (2026-11-05): HECHA.** Todos los puntos de abajo están aplicados, con pruebas de regresión en
> `tests/test_fase_a.py` (33) y `eolfi/bridge/test/fase-a.test.mjs` (3). Ver SESION.md para el detalle.
- **Ejecución de código ajeno y escritura sin copia:**
  - A14: git ejecuta un programa del repo analizado.
  - A10: el código de la IA se ejecuta con acceso a tu disco.
  - A18: escritura sobre el origen sin copia.
  - M40: inyección en corpus.py.
  - A12: nombres de paquete que tapan módulos estándar.
- **Cuelgues y DoS:**
  - A9: verify se cuelga en POSIX.
  - A15–A17: regex cuadráticas y plazo de cabeceras.
  - A5–A6: ARSC y string pool.
  - A8: Ghidra/capa en Windows.
- **Datos que se pierden o mienten:**
  - A1 servidor: `--db` de `create` (y migrar `memory` y `sqlite`).
  - A7: manifiesto manipulado.
  - A1–A3 puente: aprobación caducada, conversación equivocada y CRLF.
  - A4 puente: errores que lo tumban.
- **Seguridad del código generado:**
  - A11: CSP y cabeceras.
  - A13: contraste.
  - M28–M30: auth, Django y Express.

**Fase B: robustez**
> **Estado (2026-11-05): HECHA, salvo M4 y M5 del puente** (detectar el final de la respuesta y las listas
> virtualizadas): hay que calibrarlos contra las webs reales enviando mensajes, con tu permiso. Del servidor,
> M7 queda a medias (el servidor ya acepta `ai_base_url`, `reanalyze` e `ignore_robots`; el panel aún no los
> muestra) y M8–M9 (empaquetado y documentación) pasan a la Fase C. Pruebas: `tests/test_fase_b.py`,
> `tests/test_fase_b_sites.py` y `eolfi/bridge/test/fase-b.test.mjs`.
- **Servidor y panel:** A2–A4, M1–M7, M10, M11 y la comprobación REA.
- **Generador:** M22–M27, M31.
- **Puente:** M1–M9.
- **Parsers e importación:** M12–M21.
- **Sites y flows:** M32–M39.

**Fase C: detalles** (HECHA el 2026-11-05: todas las B, M7 del panel, M8 y M9; ver SESION.md) — todas las B y la documentación (M9 del servidor).

**Fase D: pruebas** (HECHA el 2026-11-05; ver SESION.md) — los huecos de pruebas de cada sección, más e2e del panel y axe en CI.

**Fase E: mejoras e implementaciones** — por valor y esfuerzo.
> **Estado (2026-11-05):** grupos 1, 2 y 3 HECHOS (mejoras rápidas, formatos nuevos y puente). Grupos 4–5 pendientes. Los selectores de ChatGPT, Copilot y Le Chat quedan sin calibrar.
1. Rápidas y de mucho valor:
   - `safe_git`.
   - Presupuesto común (`ParseBudget`) para parsers y texto.
   - Pestaña «Trabajos».
   - Evidencias paginadas.
   - Informes HTML.
   - Atajos.
   - CSP en los 13 destinos.
   - IA robusta.
2. Formatos nuevos: Authenticode, .NET, IPA, JAR, `.so` de Android, WebAssembly y firma APK.
3. Puente: streaming, adaptador declarativo, más chats (ChatGPT, Claude.ai, Copilot, Le Chat) y comparativa multi-chat.
4. Producto: SPA renderizadas, crawling, más pilas, fusión con autoridad, e2e generadas, despliegue, i18n/PWA, empaquetado e instalador.
5. Largo plazo: backends Go/Rust y `eolfi sync`.
