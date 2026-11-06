# Estado de la sesión de desarrollo de Eolfi (2026-11-04)

Archivo para retomar el trabajo más adelante. Al empezar una sesión nueva, pide:
«lee D:\Eolfi\SESION.md y continúa con lo pendiente».

## Qué es Eolfi (v0.6.0)
Sistema local de ingeniería inversa y modelo de evidencias, en D:\Eolfi:
- Análisis de binarios (PE/ELF/Mach-O/DEX/APK con AXML y resources.arsc, Ghidra/capa/rizin),
  webs y repositorios. Exporta JSON/SARIF/STIX.
- `create`: genera proyectos NUEVOS verificados (instala, prueba y compila) a partir de una o varias fuentes.
  Hay 9 destinos: static, react, vue, svelte, next, fastapi, express, django y expo.
- FastAPI/Express aceptan `--db sqlite` (con migraciones `migrations/NNNN_*.sql`, `python -m app.migrate`
  o `npm run migrate`, con las opciones `status` y `new`) y `--auth`.
- Expo trae `eas.json` (preview = APK, production) y los identificadores `com.eolfi.<nombre>`.
  La compilación en EAS no está probada porque necesita una cuenta de Expo.
- Modo asistido por IA: Claude, Eolas, APIs y los chats web DeepSeek/Gemini/Meta a través del puente Electron/CDP,
  que usa tu navegador real. La IA solo puede crear migraciones nuevas, nunca editar las existentes.
- Panel web: `python -m eolfi serve`. Puente: `python -m eolfi bridge --browser chrome`.
  Para iniciar sesión una vez: `python -m eolfi bridge --login`.
- Pruebas: `python -m pytest -q` (84 pasan) y `cd eolfi/bridge && node --test test/*.test.mjs` (20 pasan).

## Hecho en esta última parte
- Chat del panel: el texto se borra al enviar; Intro envía y Mayús+Intro hace un salto de línea.
- Migraciones SQLite (FastAPI y Express), EAS para Expo, README y versión 0.6.0.

## En curso (sin terminar)
Arreglo de los fallos de las capturas del panel:
1. La sección «Analizar» (pestañas Web/Repositorio) no tiene botón «Analizar»: el botón decía «Ruta».
2. En «Crear proyecto nuevo» falla escribir «Alejandria» como fuente:
   «no es una URL, ruta ni objetivo conocido».

**Parche APLICADO** (pasan las 84 pruebas); falta probarlo en el panel y añadir pruebas propias. Lo que hace:
- Renombra el botón «Ruta» a «Analizar» y el de subir archivo a «Analizar archivo».
- Una fuente escrita solo con el nombre («Alejandria») se busca primero entre los objetivos ya analizados y,
  si no está, como carpeta en C:\, D:\, E:\, F:\, el inicio, el Escritorio y Documentos
  (solo se usa si coincide una única carpeta).
- Un mensaje de error más claro, que sugiere la ruta completa.
- Impide que la carpeta destino sea la de la fuente o la contenga: en la captura se usaban C:\Alejandria
  como fuente y c:\Alejandria como destino.
- Si el campo «Nombre» tiene una ruta, se usa solo el último componente.
Después: añadir pruebas en tests/test_flows.py, ejecutar pytest y probarlo en el panel.

Nota de uso: para auditar y planificar Alejandria encaja mejor «Analizar → Repositorio → C:\Alejandria»
que «Crear proyecto», porque «Crear» genera un proyecto nuevo y no modifica el original.

## Última actualización (límite de uso alcanzado)
- HECHO: se puede escribir en la carpeta de origen. Se hace siempre una copia de seguridad previa
  `<carpeta>.eolfi-backup-<fecha>`, sin node_modules/.venv/dist (`backup_folder` en eolfi/flows/create_flow.py).
  El resultado incluye `"backup"`. Se niega a escribir en la raíz de una unidad o en la carpeta personal.
- HECHO: el panel muestra `r.backup`; hay pruebas de la copia de seguridad y de `/api/fs/list` (86 pasan).
  Al escribir sobre el origen se omite la verificación automática (PLAN A4).
- HECHO: selector de carpetas 📁 (`/api/fs/list`) en «Analizar», «Fuentes» y «Carpeta destino», probado en el panel.
- HECHO: la auditoría está en **PLAN_CORRECCIONES.md**, con los informes del generador, servidor/panel/CLI y puente.
  Faltaban los de core+providers y sites+flows. SIGUIENTE: aplicar la Fase 1 (seguridad crítica) del plan.

## Fase 1 de seguridad (PLAN_CORRECCIONES.md)
- APLICADA: A1–A9, A11–A15. La tabla «Estado» del plan detalla cada una. Pasan las 96 pruebas de Python y las 24 de Node.
- Puente: bridge.json ahora tiene `panelToken`; el panel de Eolfi lo usa automáticamente.
- HECHO también A16–A20 (sites y flows). Pasan las 100 pruebas de Python y las 24 de Node.
- HECHA la Fase 2 (salvo M7 y parte de M19); ver tablas de PLAN_CORRECCIONES.md. Pasan 105 pruebas de Python y 24 de Node.
- HECHA la Fase 3 (B1–B12). Versión 0.7.0.
- NUEVO destino **desktop** (Windows, macOS y Linux, con Electron e instaladores); `auto` detecta el tipo de app
  (escritorio, móvil Android/iOS, web o backend) a partir de binarios y pilas. El usuario quiere que Eolfi cubra
  TODOS los sistemas operativos y tipos de app, no solo Android.
- HECHOS los destinos **tauri** (Rust), **dotnet** (C# + Avalonia) y **cli** (Python); todos verificados de verdad. Versión 0.8.0.
  El .NET SDK 10.0.403 se instaló con winget (C:\Program Files\dotnet; puede no estar en el PATH de shells ya abiertas).
- HECHA A10: el puente controla Chrome por tubería privada (sin puerto TCP). Al cerrar el puente se cierra su Chrome;
  las sesiones siguen en ~/.eolfi/browser-profile. Probado en vivo con los tres chats.
- HECHA la Fase 4: tests/test_phase4.py (34 pruebas) y bridge/test/engine-concurrency.test.mjs. 148 pruebas Python + 28 Node.
  Encontró y se corrigió un fallo real en fetch (plazo total con read1).
- HECHA la Fase 5: /api/jobs con progreso, --root/EOLFI_ROOTS, verificación en copia limpia, axe sin infracciones
  (tools/axe-audit.mjs). 151 pruebas Python + 28 Node.
- HECHA (petición del usuario): pestaña «Proveedores» (elegir IA y proveedores de análisis) y tema automático/claro/oscuro.
  153 pruebas Python + 28 Node. Auditoría a11y: tools/axe-audit.mjs (necesita axe-core: npm install --prefix tools axe-core).
- HECHA M19: DeepSeek y Meta ya no dependen del idioma de la interfaz (probado en vivo).
- Instalado `pip install -e "D:\Eolfi[ai]"` (anthropic 2.5.0): el proveedor Claude aparece disponible; para usarlo
  falta la credencial (ANTHROPIC_API_KEY o `ant auth login`).
- ALEJANDRÍA (D:\Alejandria): auditada; plan en D:\Alejandria\docs\PLAN-AUDITORIA-E-INTEGRACION-EOLFI-2026-11-05.md.
  Eolfi comparte la biblioteca: config/fuentes.json (Force + Eolfi); el mantenimiento horario lo importa;
  `python -m eolfi corpus` lo hace al momento. corpus/codigo/Eolfi y corpus/texto/Eolfi creados.
- HECHO en Alejandría: módulo común (config única + exclusiones con comodines + detector de secretos), parser Babel
  propio en tools/, auditoría de .force con caché. Corrección importante: nunca se borran copias cuyo origen ya no
  existe (17 copias únicas de D:\Forge\_backup-2026-10-29). Auditoría limpia, 0 secretos.
- HECHO en Alejandría: M2 (Export-Alejandria.ps1, antiguos a docs/historico), M3 (rotación mensual), I2+I5 (paso
  Eolfi horario: eolfi.db, eolfi-evidencias.json, eolfi.sarif), B2 (21 pruebas en scripts/tests). Probado con
  Windows PowerShell 5.1 (BOM en scripts; stderr de Python ya no corta el mantenimiento).
- PANEL reparado tras una revisión del usuario y prueba e2e botón por botón:
  - la columna izquierda ya no se desborda;
  - «Analizar» con una carpeta en la pestaña Binario la analiza como repositorio (antes: «no existe el archivo»);
  - se corrigió el error «reading 'length'» con web/repo;
  - sin estilos en línea bloqueados por la CSP (clase .bad), favicon, 503 en vez de 500 si el puente se reinicia;
  - bridge/engine incluido en package-data.
- Alejandría, decisiones del usuario: el espejo force-source SE MANTIENE; la tarea debe correr SIN SESIÓN.
  REGISTRADA (2026-11-05 04:01, con permiso explícito del usuario y su UAC): Alejandria-Mantenimiento como
  CELTIA\mejil, S4U, Limited, cada hora, -Python con la ruta real. Ejecución de prueba: resultado 0, auditoría y
  archivos de Eolfi regenerados.
- Plan de Alejandría completo. Mantener la prueba e2e del panel al añadir botones.
- Nombre: ya no se usa «forge». La carpeta es **eolfi/generador** (módulo `eolfi.generador`).
  Las evidencias nuevas usan el subject `proyecto:<ruta>` y las operaciones project_generated, project_verification y project_assist.
  Los datos antiguos (`forge:`, `forge_*`) se siguen leyendo.

## Pendiente después
- Pedido por el usuario: ejecutar los agentes REA o de revisión sobre Eolfi, carpeta por carpeta y
  archivo por archivo, y escribir un plan de correcciones e implementaciones (p. ej. PLAN_CORRECCIONES.md).
  Carpetas: eolfi/core, providers, sites, flows, generador, bridge (Node), web, cli.py, server.py, tests.
- Probar una compilación real en EAS (necesita `npx eas-cli login` del usuario).

## Normas acordadas
- Responder en español. No hacer git init ni commits sin pedirlo.
- Nunca escribir credenciales del usuario. De las cookies, mirar solo los nombres, nunca los valores.
- Los envíos automáticos por el puente necesitan aprobación; los escritos desde el panel no.
- El modo login solo cierra procesos que usan el perfil de Eolfi, nunca el Chrome personal.
- En los avisos de cookies, elegir «Rechazar todo».

## Segunda auditoría (2026-11-05)
- 6 agentes (5 por carpetas + 1 comprobación funcional en vivo con REA), en solo lectura.
- Plan: **PLAN_MEJORAS_2026-11-05.md**: 22 altas, unas 50 medias y bajas agrupadas, más mejoras por área y una hoja
  de ruta (Fases A–E).
- Lo más urgente (Fase A):
  - git ejecuta programas del repo analizado (gpg.program).
  - El código de la IA se verifica con tu HOME.
  - Escritura sobre el origen sin copia si la fuente es un objetivo por nombre.
  - Inyección con comillas tipográficas en corpus.py.
  - verify se cuelga en POSIX.
  - Regex cuadráticas.
  - ARSC y string pool.
  - `create --db` pisa la base de evidencias: existen D:\Eolfi\memory y D:\Eolfi\sqlite, que hay que migrar a eolfi.db.
- Fase A aplicada: ver la sección siguiente.

## Fase A aplicada (2026-11-05)
- git aislado (`safe_git` en sites/repo.py): un .git/config hostil ya no ejecuta nada (probado con control negativo).
- Escritura sobre el origen: también se detecta si la fuente es un objetivo por nombre; siempre con copia.
- corpus.py: los datos van en JSON por variable de entorno; el comando de PowerShell es fijo.
- verify: mata el árbol de procesos (POSIX y Windows) y el código de la IA se verifica con HOME temporal.
- Regex lineales (JS, CSS, go.mod, Gemfile, Dockerfile) y plazo total real en las descargas (también la cabecera).
- Parsers Android: índices de ARSC dentro de su bloque, tabla del string pool acotada, presupuesto global de
  cadenas, y el valor TIPADO del manifiesto manda (si el texto dice otra cosa: hallazgo «Manifiesto manipulado»).
- Herramientas externas (Ghidra, rizin, capa): al agotar el plazo se mata el árbol de procesos.
- CLI: `create --db memory|sqlite` ya no pisa la base de evidencias (dest `backend_db`, alias `--backend-db`).
  Migradas a eolfi.db las bases sueltas `memory` y `sqlite` (49 evidencias nuevas; ahora 135). Copias en
  backups/migracion-db-2026-11-05. De paso: importar un paquete con un resultado en lista fallaba; corregido.
- Puente: la aprobación caduca de verdad (cierra el diálogo; una respuesta tardía no concede nada), cada envío
  comprueba que la pestaña está en la conversación correcta, CRLF normalizado, y ni un fallo al lanzar el
  navegador ni un JSON roto en la tubería lo tumban.
- Código generado: CSP y cabeceras de seguridad en static, react, vue, svelte, next, fastapi y express; errores
  JSON en Express; límite por IP y mapas con tope en la auth; Django sin DEBUG por defecto (manage.py lo activa
  para desarrollo) y SECURE_* en producción; contraste AA en la paleta; nombres de paquete que no tapan nada.
- Pruebas: suite Python 187 pasan (1 omitida); puente 30 pasan (1 omitida, necesita navegador real).
- Verificación real (instalar + compilar + pruebas generadas): static, fastapi (sqlite), express (sqlite y
  memoria), django y vue, todas OK; el build de vue lleva la CSP en su index.html.
- Fase B aplicada: ver la sección siguiente.

## Fase B aplicada (2026-11-05)
- Servidor:
  - Trabajos con cola (3 a la vez), cancelación (DELETE /api/jobs?id=) y listado (GET /api/jobs).
  - Subida por bloques a disco (/api/upload?store=1) y triaje como trabajo.
  - Objetivos con una sola consulta e índice de incógnitas; evidencias paginadas (limit/offset/q).
  - Proveedores en paralelo y con caché de 30 s.
  - GET de otros sitios rechazado, CORP same-origin, token fuera del registro y cambiado por cookie con redirección.
  - Nombres de carpeta con acentos o sin letras latinas.
- Panel: una sola función de vistas, respuestas viejas descartadas, sondeo del puente sin duplicados, evidencias que se
  pintan al abrirlas, filtro con retardo, selector de carpetas que no se traga el clic y se cierra con Esc.
- Generador:
  - IA: respuesta validada y archivos restaurados pase lo que pase (también con Ctrl+C); auth y pruebas de
    seguridad protegidas; reintentos ante 429/5xx (nunca en el puente) y presupuesto de tokens.
  - Las rondas de IA ya no reinstalan ni publican en dotnet, desktop, expo y tauri.
  - Electron: interfaz por app:// (no file://), sin https: en connect-src y fusibles al empaquetar (comprobado
    en el .exe real: RunAsNode, NODE_OPTIONS e --inspect desactivados; arranca bien).
- Puente:
  - La vista en directo no reabre ventanas cerradas (404).
  - Capturas escaladas en el navegador; tubería sin búsqueda cuadrática.
  - POST /v1/reset levanta el «dudoso»; plazo de respuesta configurable con EOLFI_BRIDGE_REPLY_MS.
  - Gemini guarda solo /app/<id>; aprobación caducada = 408; 413 legible.
  - Escucha antes de abrir las pestañas; «Permitir 30 min» por conversación, visible en /v1/status y revocable
    (POST /v1/revoke).
  - Pendiente: M4 y M5 (calibrar contra las webs reales).
- Parsers e importación:
  - Mach-O universal sin pisar arquitecturas y con un solo presupuesto de entropía.
  - Topes en cadenas e importaciones PE.
  - Paquetes importados: fechas, tipos, tamaño y anidamiento validados; cruce de confianza; incógnitas
    fusionadas; referencias colgantes quitadas.
  - STIX tolerante; APK con entradas duplicadas o rutas ../ señalado; proveedores copiados por ejecución.
- Sites y flows:
  - Cookies bien atribuidas; clones de más de 7 días borrados (solo los de Eolfi); lecturas y recorridos acotados.
  - diff compara la salida entera (hasta 64 MB) y mata al pasarse.
  - Detección de pila corregida: .NET, Gradle/Android, Flutter, Hugo/Jekyll, subcadenas, examples/ e implies.
  - summarize y compare tolerantes.
- Pruebas: Python 215 pasan (1 omitida); puente 34 pasan (1 omitida).
- Nota: el servidor `serve --reload` y el puente que estaban en marcha se pararon al reiniciarse la sesión.
  El puente necesita reiniciarse para usar el código nuevo.
- Fase C aplicada: ver la sección siguiente.

## Fase C aplicada (2026-11-05)
- Panel:
  - Tema aplicado desde <head> (theme.js, sin destello); pestañas con tabpanel; el estado de cada chat
    también en texto (no solo por color).
  - Casillas y botones con nombre propio («Resolver: …»); 📁 oculto al lector de pantalla; zona de soltar con
    role=button; aviso con la ruta vacía.
  - Vista en directo y sondeo en pausa con la pestaña oculta.
  - Selección de proveedores obsoleta limpiada y visible en «Analizar».
  - Opciones que faltaban: web (recursos, otros dominios, ignorar robots), crear (reanalizar, modelo y URL
    de la IA) y OpenAI en la lista.
- Servidor: needs_confirm como campo (no por texto), index.json atómico, URL imprimible con 0.0.0.0.
- CLI: biblioteca Alejandría sin ruta fija (EOLFI_LIBRARY, ~/Alejandria o D:/Alejandria si existe).
- Empaquetado:
  - Versión única (dynamic desde eolfi/__init__.py); clasificadores; sin el extra «analysis» que no se usaba.
  - Electron fijado (^45.2.2) y package-lock incluido.
  - Si site-packages no admite escritura, el puente se instala en ~/.eolfi/bridge-app.
  - Comprobado: el wheel se construye e incluye theme.js y el lockfile.
- Puente:
  - panelToken obligatorio; /v1/input sin O(n²); teclas con Object.hasOwn y un solo evento por pulsación.
  - Manejadores de sesión quitados al cerrar; el estado de Meta ya no pulsa nada.
  - Sale de verdad ante un error de arranque; bridge.json atómico y con permisos solo para el usuario (icacls).
- Core y parsers:
  - ZIP enorme rechazado antes de cargar su directorio; límites de archive_inventory al día.
  - Load commands de Mach-O acotados por su cmdsize.
  - _last_json tolerante; copia en vez de enlace duro; solo los .bat pasan por la comprobación de cmd.exe.
  - Ghidra y capa con tipos validados; resiliencia por huella, por bloques y sin carpetas huérfanas.
  - Triaje reconoce Mach-O big-endian y fat64.
  - Incógnitas de «no disponible» que se cierran y de «falló» que no se duplican.
  - ASLR solo si hay relocalizaciones; los <provider> antiguos, exportados por defecto.
- Generador y sites:
  - Formulario de ejemplo honesto, «Saltar al contenido» y aria-pressed en el tema.
  - Dirección del puente validada con urlsplit; FreeBSD sin KeyError al publicar.
  - robots.txt inaccesible = no rastrear; se respeta <meta charset>.
  - diff: entradas con & copiadas para .bat y el candidato ya no se ejecuta si falla la referencia.
  - Un stat por archivo; dependencias clave en monorepos.
  - Fuentes locales ya analizadas se reutilizan; sin bloqueos por unidades de red.
- Documentación: README con la API completa (trabajos, paginación, subida, puente, --root, modo remoto,
  límites) y docstring de la CLI con assist, bridge, corpus y serve --root.
- Pruebas: Python 233 pasan (1 omitida); puente 36 pasan (1 omitida).
- Siguen pendientes: M4 y M5 del puente (calibrar contra las webs reales, con permiso para enviar mensajes) y
  la carpeta eolfi.egg-info antigua (se puede borrar; pip install -e la regenera).
- Fase D aplicada: ver la sección siguiente.

## Fase D aplicada (2026-11-05)
- tests/test_fase_d.py (19):
  - ARSC denso, sparse y OFFSET16 (el fixture build_arsc acepta flags); cadenas que cruzan bloques.
  - _slim_functions con tamaños raros (y corregido: ya no falla al ordenar); fuzz_file sin carpetas huérfanas.
  - SARIF/STIX con un paquete hostil; fuzz dirigido a estructuras repetidas (AXML, ARSC, Mach-O).
  - CLI triage → export → import → evidence; subida con selección de proveedores y expulsión de trabajos.
  - guess_folder sin depender del equipo; backup_folder; pin_nuget con salida larga; _kill_tree en POSIX.
  - Parsers de go.mod, csproj, gradle y pubspec; DiskLoader; 5 MB de saltos de línea.
- Puente:
  - approve sacado de main.mjs a approval.mjs (probado sin Electron).
  - test/fase-d.test.mjs (9): aprobación por conversación; send() con navegador falso (CRLF, cancelación
    tras escribir → «dudoso» hasta reset, cambio de chat); tramas de la tubería; manejadores al cerrar;
    loadURL con loaderId; 421 y since inválido.
- e2e del panel (tests/e2e, playwright-core 1.64.1 + axe-core 4.14.0 fijados; usa el Chrome instalado):
  carga sin errores, axe en claro/oscuro/detalle/proveedores, subida → trabajo → objetivo, cuerpo perezoso,
  vistas, avisos, selector con teclado, pestañas con flechas.
  - axe encontró dos fallos reales y quedaron corregidos: #analysis-choice sin rol (grave) y
    <label role=button> en la zona de soltar (ahora un div con su clic).
- CI: .github/workflows/ci.yml (Python en Windows/macOS/Linux con 3.10 y 3.12, puente y e2e). No se ha
  ejecutado: el proyecto no está en git ni en GitHub.
- Borrada la carpeta build/ que dejó la prueba del wheel de la Fase C.
- Pruebas: Python 251 pasan (2 omitidas); puente 45 pasan (1 omitida); e2e 4 pasan.
- Fase E (grupo 1) aplicada: ver la sección siguiente.

## Fase E, grupo 1 (mejoras rápidas) aplicado (2026-11-05)
- Ya estaban de fases anteriores: safe_git, evidencias paginadas, CSP en los destinos web, IA robusta.
- Pestaña Trabajos: estado, cancelar, repetir (POST /api/jobs/<id>/repeat) y «Ver» el objetivo; historial en
  la tabla job_history de eolfi.db (500 como mucho); contador de trabajos activos en la cabecera.
- Navegación por hash (#analisis, #chats, #proveedores, #trabajos, #objetivo/<sha>) con botón Atrás; atajos
  Alt+1..4, «/» y «?» (diálogo de ayuda).
- Informes: eolfi/core/report.py (HTML autocontenido sin scripts, con CSP, todo escapado; Markdown; JSON);
  `eolfi report … --fail-on high` para CI; GET /api/report; enlaces en el detalle del panel.
- Django: middleware propio con CSP y cabeceras de seguridad + prueba generada (verificado de verdad: OK).
- ParseBudget (binfmt.parse_budget): presupuesto común de bytes leídos y tiempo para todo Reader.
  Proveedores locales en subproceso (eolfi/providers/isolated.py, run_triage(isolate=True)); el servidor
  aísla siempre (EOLFI_ISOLATE=0 lo quita). Coste medido: unos 0,4 s por análisis (mshtml.dll, 22 MB: 2,9 → 3,4 s).
  En Windows no hay límite de memoria (solo plazo); en Linux/macOS, RLIMIT_AS de 2 GB.
- Pruebas: Python 260 pasan (2 omitidas); puente 45 (1 omitida); e2e 6 (Trabajos, atajos, Atrás e informe con axe).
- Grupo 2 aplicado: ver la sección siguiente.

## Fase E, grupo 2 (formatos nuevos) aplicado (2026-11-05)
- Módulos nuevos en eolfi/providers: der.py (DER/X.509/PKCS#7), pe_extra.py, dotnet.py, java.py, wasm.py,
  apksig.py y apple.py. Versiones de proveedor: eolfi.binfmt 0.3.0 y eolfi.archive 0.3.0.
- PE: Authenticode con comprobación del resumen (probado con node.exe y dotnet.exe reales; un byte cambiado da
  «NO COINCIDE» e incógnita alta), imphash, Rich, TLS (node.exe tiene 2 callbacks) y VERSIONINFO.
- .NET: probado con System.dll (P/Invoke a kernel32), Microsoft.Build.dll del SDK (ReadyToRun, .NETCoreApp 10)
  y un ejecutable single-file publicado antes (202 archivos).
- Java: probado con una clase y un JAR reales compilados con javac 21; Spring Boot con fixture.
- WebAssembly: probado con resvg.wasm (Rust + wasm-bindgen, versiones de rustc) y otros de node_modules.
- APK: firma v2/v3 con un certificado de prueba generado con openssl (tests/fixtures.TEST_CERT_DER, sin clave
  privada); la huella coincide con la de openssl. .so con alineación de 16 KB y JNI; DEX con APIs sensibles.
- IPA: fixture con Info.plist binario, firma de código (Team ID, entitlements), mobileprovision y cryptid.
- Hallazgos nuevos → incógnitas (firma que no coincide, ofuscación .NET, iOS) y en los informes; fichas nuevas
  en el resumen del panel.
- Fuzz de mutación sobre todos los formatos nuevos: solo halló un caso previo (ZIP con «versión necesaria»
  imposible → NotImplementedError), ya contenido.
- Pruebas: Python 280 pasan (2 omitidas); puente 45; e2e 7 (incluye un binario firmado real en Windows).
- No validado: cadenas de confianza ni firmas criptográficas (RSA/ECDSA): fuera de la stdlib. Para eso:
  signtool/osslsigncode, apksigner y codesign.
- Grupo 3 aplicado: ver la sección siguiente.

## Fase E, grupo 3 (puente) aplicado (2026-11-05)
- Streaming: waitReply avisa del texto parcial (onPartial), el servidor del puente lo publica en /v1/events
  («partials») y el panel lo pinta mientras se escribe (sondeo a 600 ms en ese momento).
- Plazo por INACTIVIDAD (EOLFI_BRIDGE_REPLY_MS) con tope total (EOLFI_BRIDGE_MAX_REPLY_MS, 30 min). Eolfi y el
  panel esperan hasta 1900 s.
- M4 (parcial): «completa» exige además el mismo texto en dos lecturas seguidas, en los tres adaptadores clásicos.
- Adaptador declarativo (adapters/declarative.mjs + sites.json): ChatGPT, Copilot y Le Chat. Selectores SIN
  CALIBRAR con una sesión real. GET /v1/selftest y botón «Autodiagnóstico» (no escribe nada); recalibrar con
  ~/.eolfi/bridge-sites.json (solo selectores de chats conocidos). EOLFI_BRIDGE_CHATS elige qué ventanas abrir.
  Claude.ai no se incluye a propósito: Eolfi ya usa la API oficial de Claude.
- Comparativa: POST /v1/compare (2–6 chats, una sola aprobación «a+b»), proxy /api/bridge/compare y vista en el
  panel con las respuestas lado a lado. Pestañas de chat dinámicas según lo que anuncia el puente.
- Pruebas: tests/e2e/bridge-chat.test.mjs maneja un chat SIMULADO en local con Chrome real (autodiagnóstico,
  streaming, URL de conversación, comparativa); bridge/test/fase-e.test.mjs (plazo por inactividad, texto estable,
  recalibración segura). Python 282 pasan (2 omitidas); puente 49; e2e 10.
- Para usarlo: reiniciar el puente (python -m eolfi bridge). Calibrar los chats nuevos exige abrirlos con tu sesión
  y pulsar «Autodiagnóstico» (no envía nada); enviar mensajes de prueba reales necesita tu permiso.
- SIGUIENTE (a elegir): grupo 4 (producto) o 5 (largo plazo). Siguen pendientes M5 (listas virtualizadas) y la
  calibración real de M4 y de los chats nuevos.

## Calibración real de los chats nuevos (2026-11-05)
- Autodiagnóstico con modo «descubrir» (GET /v1/selftest?discover=1 y botón del panel): lista editores, botones y
  atributos «de mensaje» de la página, nunca el texto de los mensajes. Probado con el chat simulado.
- Puente viejo (03:14) cerrado con permiso del usuario; puente nuevo con EOLFI_BRIDGE_CHATS=chatgpt,copilot,lechat.
- ChatGPT (modo invitado): editor nuevo textarea[name='prompt'] / #mobile-composer-prompt → OK; se envía con Intro
  (el botón de enviar no existe hasta que hay texto).
- Le Chat (con sesión): editor [data-chat-input-bar] [contenteditable] → OK; se envía con Intro.
- Copilot: redirige a «Sign into Copilot»; hace falta iniciar sesión con cuenta de Microsoft antes de calibrar.
- Sin confirmar en ninguno: selectores de mensajes (usuario/asistente), botón de parar e identidad de los mensajes.
  Necesitan una conversación en pantalla: abrir una existente o enviar un mensaje de prueba (con permiso).
- sites.json guarda «verified» por chat con lo comprobado y la fecha.
- Mensajes de prueba reales («Responde solo con la palabra OK»), con permiso del usuario:
  - ChatGPT (invitado): mensajes con data-message-role=user/assistant y fin con data-message-complete
    (completeAttr). Responde «OK» en 3,2 s.
  - Le Chat (con sesión): la respuesta es la parte [data-message-part-type=answer] (la de «pensando» se ignora) y
    termina cuando aparece su botón «Like» (completeWithin). Responde «OK» en 5,8 s. Las conversaciones están en
    /work/<id>. Hubo que cerrar un aviso de bienvenida («Hemos integrado Chat en Work») y su tour; los diálogos
    de Radix abiertos ([role=dialog][data-state=open]) cuentan ahora como bloqueo.
  - Se enviaron 2 mensajes a ChatGPT y 3 a Le Chat (los primeros fallaron por selectores y sirvieron para
    corregirlos); quedan en el historial de esas webs.
  - Pendiente: botón de parar y respuestas largas (solo se probó una respuesta corta); Copilot (iniciar sesión).
- Adaptador declarativo: opciones nuevas completeAttr y completeWithin (también recalibrables, con validación).
- Le Chat como proveedor web por defecto: se abre al arrancar el puente, está en el desplegable de IA de «Crear»
  y en el orden del proveedor automático «web» (gemini, meta, deepseek, lechat).
- Puente en marcha con la configuración por defecto: DeepSeek, Gemini, Meta y Le Chat listos y con sesión.
- Pruebas: puente 50; e2e del chat simulado 4.

## IA de VS Code como proveedor (2026-11-05)
- Extensión eolfi/vscode-bridge (JS sin dependencias): servidor en 127.0.0.1 con token y archivo
  ~/.eolfi/vscode-bridge.json. Language Model API: /v1/models, /v1/chat (con herramientas). /v1/tools lista las
  64 herramientas de tu VS Code. /v1/tool usa una permitida.
- Acciones de Eolfi en VS Code (/v1/workspace/<acción>; CLI `eolfi vscode-do`; Python eolfi.vscode_tools):
  workspace, list, read, find, open, write, command. Solo dentro del workspace. Escribir y abrir otra carpeta
  piden confirmación modal en VS Code. Comandos y herramientas solo en lista blanca (ajustes eolfi.*).
- Proveedor «copilot-vscode» (EOLFI_COPILOT_MODEL, EOLFI_COPILOT_TOOLS, EOLFI_COPILOT_WORKSPACE=read|write|off),
  en la CLI, en el desplegable de «Crear» y en `eolfi vscode` (ventana de desarrollo sin instalar; --install para
  dejarla instalada).
- Probado con VS Code 1.145 real (ventana de desarrollo, carpeta D:\Eolfi): workspace, find, read y open
  funcionan; leer ~/.ssh/config se rechaza (403).
- Con la sesión de Copilot iniciada (7 modelos) y el permiso aceptado en VS Code, PROBADO DE VERDAD:
  - «Responde OK» → «OK» (modelo Auto).
  - Con herramientas de solo lectura: Copilot usó eolfi_find_text y eolfi_read_file por su cuenta y explicó
    run_triage (triage_flow.py, línea 113, parámetro isolate) en 13 s.
  - Proveedor completo con esquema JSON: GPT-4.1 respondió el JSON pedido (vscode_tools.py, línea 21) en 50 s.
- Modelos: «Auto» no admite peticiones con herramientas y GPT-5.6 Luna está reservado para VS Code («only
  available to VS Code core»). El puente prueba los candidatos en orden (mayor contexto primero, sin los de
  dictado) y recuerda el que funciona; aquí GPT-4.1. EOLFI_COPILOT_MODEL fija otro.
- Pruebas: extensión 6 (vscode falso); Python 3 nuevas (puente simulado).

## VS Code: modo automático, ingeniería inversa, VS Code integrado y sesión (2026-11-05)
- EOLFI_COPILOT_WORKSPACE=auto: un único permiso modal («esta sesión» / «siempre» → eolfi.autoApproveEdits).
  Diario por chat (máx. 30) con el contenido original; /v1/workspace/undo restaura o borra lo creado. Si el chat
  falla se deshace solo; assist llama a rollback() si el resultado no está en verde. PROBADO DE VERDAD: un
  permiso, la 2.ª escritura sin preguntar y el deshacer borró el archivo de prueba.
- Comandos de ingeniería inversa en la extensión (analizar archivo/carpeta/web, abrir panel, último informe) como
  trabajos del servidor con progreso y cancelación (eolfi-client.js).
- VS Code integrado: eolfi/vscode_web.py lanza `code serve-web` (127.0.0.1, puerto libre, token, sin telemetría,
  datos en ~/.eolfi/vscode-web). La licencia solo se acepta con la casilla del panel (se recuerda en
  ~/.eolfi/vscode-web-license); sin ella 412. CSP con frame-src http://127.0.0.1:*. Vista #vscode en el panel.
  SIN PROBAR DE VERDAD: falta que el usuario acepte la licencia.
- Inicio de sesión obligatorio: /api/clients/pair (solo el panel) → código; /api/clients/token lo canjea por un
  token ect_ (sha256 en client_tokens). Peticiones con X-Eolfi-Client sin token válido → 401; DELETE /api/clients
  revoca. La extensión guarda el token en SecretStorage y sin él no arranca ni el puente ni los comandos.
  Comprobado: sin sesión el puente no arranca. SIN PROBAR DE VERDAD: el canje desde VS Code (lo hace el usuario).
- Pruebas: Python 289 (2 omitidas); extensión 11; e2e 11.
- E2E contra el servidor real (cliente de la extensión): 401 sin sesión, código malo/reusado 403, canje, triaje
  de un .exe (23 s), informe y revocación → 401. Todo OK.
- Chat «@eolfi» en el Chat de VS Code (chat.js): /analizar <archivo|carpeta|URL>, /incognitas, /informe y
  preguntas libres (el modelo del chat recibe el informe y las incógnitas como datos). Se abre solo al iniciar
  sesión («Eolfi: abrir el chat»). E2E con el servidor real OK; pruebas de la extensión 16.
- `eolfi vscode --install` ahora crea un VSIX propio (build_vsix, sin vsce) y lo instala con `code --install-extension`:
  la extensión de desarrollo solo vivía en su ventana y desaparecía al recargar. Instalada la 0.2.0. Python 290.
- Extensión 0.2.1: enlace vscode://eolfi.eolfi-vscode-bridge/login?code=… (y /chat); el panel lo ofrece junto al
  código. El chat se abre en modo «Ask» (en «Agent» no salen los @participantes). PROBADO DE VERDAD: enlace →
  sesión «VS Code (CeltIA)» → puente arriba con 7 modelos.

## Licencia y vinculación sin código visible (2026-11-05)
- LICENSE: software propietario y privado, © 2026 Luis Manuel Cousido Hermida y CeltIA (Celtia IA), todos los
  derechos reservados. pyproject (license, authors, «License :: Other/Proprietary License», «Private :: Do Not
  Upload»: PyPI rechaza subirlo), package.json de bridge y vscode-bridge (UNLICENSED + author), __license__ y
  LICENSE.txt dentro del VSIX. Cabecera en README.
- Vinculación sin mostrar el código: botón «Vincular este VS Code» en el panel, `eolfi vscode --login` y cuadro de
  VS Code con password:true. Extensión 0.2.2 instalada. Python 292.
- Sin el nombre «Copilot» en textos visibles (extensión «Eolfi» 0.2.3, barra «Eolfi», panel «IA: VS Code», CLI y
  mensajes). Los identificadores internos (copilot-vscode, EOLFI_COPILOT_*, vendor de la API) no cambian.
- Extensión 0.2.4: botón «Eolfi» (barra de estado, editor/title y explorador) → chat con «@eolfi /ayuda».
  @eolfi como agente: el modelo del chat (o el primero de mayor contexto que acepte herramientas; «Auto» y los
  reservados se saltan) usa eolfi_analizar / eolfi_incognitas / eolfi_informe y las herramientas del workspace,
  con historial de la conversación y hasta 8 rondas. Pruebas de la extensión 19. PROBADO DE VERDAD: el usuario
  confirma que el botón abre el chat y el agente funciona.

## Secretos en .env (2026-11-05)
- eolfi/dotenv.py (sin dependencias): carga .env (EOLFI_ENV_FILE, carpeta del proyecto, carpeta actual,
  ~/.eolfi/.env) al empezar la CLI; no pisa variables ya definidas; devuelve solo nombres. EOLFI_NO_DOTENV=1
  la desactiva (tests/conftest.py la pone).
- .gitignore: .env, .env.*, !.env.example, *.pem, *.key, *.db-shm/-wal, backups/, node_modules/, *.vsix.
- .env.example con los nombres (GITHUB_TOKEN y claves de IA) sin valores; .env creado vacío para el usuario.
- GitHub Models: RETIRADO por GitHub el 2026-07-30 (la API ya no responde); no se implementa.
- Pruebas: Python 295 (2 omitidas).
- Repos privados: repo.github_auth_env() mete GITHUB_TOKEN como http.https://github.com/.extraHeader en
  GIT_CONFIG_COUNT/KEY/VALUE del proceso de git (no en argv ni en .git/config; solo github.com por https, puerto
  443, sin usuario en la URL, sin redirecciones). safe_git_env descarta GIT_CONFIG_* heredados. Error de clon de
  un privado → pista sobre GITHUB_TOKEN sin mostrar el token. Python 297. SIN PROBAR con un repo privado real.
- Extensión 0.2.5: @eolfi no toca secretos (isSecretPath: .env salvo .example/.sample/.template/.dist, claves,
  credenciales, .ssh/.aws/…; read/find/write y /analizar los rechazan; sin botón «Analizar .env»). /ayuda
  ordenada: Qué hago / Cómo pedírmelo / Lo que no hago / Lo que no puedo hacer, un párrafo por línea. El agente
  conoce sus límites y responde «No puedo… / por qué / qué hacer en su lugar». Modelo: recuerda el último que
  funcionó y salta los que rechazan a extensiones (antes /ayuda anunciaba GPT-5.6 Luna, reservado). Pruebas 21.
- Extensión 0.2.6: REA en @eolfi. rea.js = cliente MCP stdio propio (initialize, tools/list paginado, tools/call)
  con el servidor «rea» de ~/.copilot/mcp-config.json (npx -y rea-agents@6.8.0 mcp) o eolfi.rea.command/args;
  arranca al primer uso. VS Code no lo exponía: su servidor MCP de REA nunca había arrancado. El modelo recibe
  2 herramientas (rea_herramientas para buscar, rea_usar para ejecutar). Confirmación solo para runtime
  (needsConfirm: destructiva + mundo abierto, o start_/instrument_/frida/gdb/rizin/capture_/adb/install…):
  38 de 229. Argumentos con rutas de secretos → bloqueados. PROBADO DE VERDAD: 229 herramientas en 4 s e
  inspect_analysis_settings respondió. Pruebas de la extensión 26 (servidor MCP falso en fixtures/).
- Extensión 0.2.7: terminal e internet en @eolfi (agent-tools.js): eolfi_terminal (PowerShell/bash, cwd dentro
  del workspace, 120 s por defecto, máx. 600, salida 100 KB), eolfi_web_leer (anti-SSRF por DNS, sin seguir
  redirecciones, 2 MB, 30 s, HTML a texto) y eolfi_web_buscar (DuckDuckGo HTML). Permiso por sesión o una vez;
  borrar (rm/del/Remove-Item/git clean/reset --hard) siempre confirma; bloqueados: formatear/particiones, apagar,
  registro HKLM/ExecutionPolicy/Defender/firewall, rm -rf de unidad o HOME, volcar entorno, git push --force,
  credenciales de git y rutas de secretos. Registro en ~/.eolfi/agent-log.jsonl. PROBADO DE VERDAD: PowerShell
  (git y python), bloqueo de «type .env», example.com y búsqueda real. Pruebas de la extensión 30.
- Extensión 0.2.8: el usuario pidió una auditoría de D:\Eolfi y el agente se cortó a los 8 pasos sin texto
  («máximo de pasos alcanzado»). Ahora: eolfi.agent.maxSteps (40 por defecto, 1–200); al límite, una ronda sin
  herramientas con resumen (hecho / hallazgos / pendiente) y botón «Continuar» (eolfi.chatContinue); progreso
  «Paso n de N»; trimContext recorta resultados antiguos (conserva los 6 últimos) a ~2,5 caracteres por token del
  modelo; guía de auditoría en el sistema (plan, eolfi_analizar de la carpeta, lectura selectiva, informe en
  informes/). Pruebas de la extensión 32. PROBADO DE VERDAD: el usuario confirma que la auditoría funciona.
- Extensión 0.2.9 («no funciona como Copilot» → el usuario eligió mejorar @eolfi): diff con proveedor de
  documentos «eolfi-propuesta» + vscode.diff y Aplicar/Descartar (sin API, diálogo modal como antes); diario por
  petición, «Archivos cambiados» con stream.anchor y botón «Deshacer estos cambios» (eolfi.undoJournal con un solo
  makeActions compartido); terminal integrada «Eolfi» con shellIntegration.executeCommand + read() y
  onDidEndTerminalShellExecution (fallback a proceso aparte); stream.reference de lo leído; progreso con verbo.
  Pruebas de la extensión 35. PROBADO DE VERDAD: el usuario confirma que funciona en VS Code.
- Extensión 0.3.0: modos de trabajo. eolfi.agent.mode = manual (por defecto) | automatico. Automático: sin diff ni
  diálogos para escribir/abrir carpetas, terminal, web, borrar y REA; siguen bloqueados lo peligroso y los secretos;
  pasar a automático pide una confirmación (modal). Interruptor «$(shield) Manual / $(rocket) Auto» en la barra de
  estado, comandos eolfi.toggleMode/modeAuto/modeManual y /auto, /manual en el chat; el modelo recibe el modo en el
  sistema y /ayuda lo muestra. Pruebas de la extensión 37. PROBADO DE VERDAD: el usuario confirma los dos modos.
- Extensión 0.3.1: memoria entre sesiones (el agente decía «No puedo buscar conversaciones anteriores»).
  history.js: ~/.eolfi/agent-history.jsonl (fecha, carpeta, petición, respuesta ≤6000, herramientas con su
  argumento, archivos cambiados, modelo, modo); búsqueda sin tildes/mayúsculas por palabras, días y carpeta; recorte
  por días (365) y a 20 MB. El chat guarda cada petición (Proxy sobre el stream), da al modelo las 5 últimas de la
  carpeta y la herramienta eolfi_historial, y /historial. Pruebas de la extensión 40.
- Extensión 0.3.2: FALLO REAL de la 0.3.1 («Falla algo»): el stream de VS Code está congelado y el Proxy que
  capturaba markdown rompía sus invariantes (TypeError «'get' on proxy: property 'markdown' is a read-only and
  non-configurable…»): @eolfi no respondía y no se guardaba historial. Ahora un envoltorio normal. Prueba de
  regresión con un stream congelado (las pruebas usaban un objeto normal y no lo vieron). Pruebas de la extensión 41.
- Extensión 0.3.3 (el usuario pegó respuestas vacías de @eolfi): su ventana seguía con la 0.3.1 (sin recargar) y
  el servidor de Eolfi estaba apagado. E2E REAL nuevo dentro de VS Code (e2e/run.js + e2e/launch.js, npm run e2e):
  perfil temporal, historial temporal (EOLFI_HISTORY_FILE), login con código, manejador del chat (exportado por
  activate) con stream congelado, /ayuda, /analizar contra el servidor real (25-40 s), /incognitas, pregunta sin
  modelo, /historial, secretos, logout y revocación: 13/13 OK. Destapó y se corrigió: /historial no encontraba
  comandos sin texto (/ayuda) y /analizar de un .env inexistente decía «No encuentro» en vez de bloquearlo.
  Limitación: en un perfil temporal el Chat no tiene modelo (sin sesión del asistente) y no envía la petición, así
  que el e2e llama al manejador directamente. Pruebas de la extensión 42.
- Extensión 0.3.4 (el usuario: «tantas preguntas, sin hacer lo ordenado»): el modelo terminaba enumerando
  herramientas y «Próximos pasos» y preguntando «¿Te gustaría que ejecute…?», sin llamar a herramientas, y el bucle
  lo daba por acabado. Ahora: instrucción «EJECUTA, NO PREGUNTES» en el sistema y, si una ronda sin herramientas
  acaba preguntando u ofreciendo opciones (asksInsteadOfDoing), se le ordena seguir (NUDGE) hasta 3 veces.
  Prueba con el texto real del usuario. Pruebas de la extensión 44; e2e real OK. PROBADO DE VERDAD: el usuario
  confirma que ya hace lo pedido sin preguntar.
- Extensión 0.3.5 (el usuario: «mejora sus habilidades de análisis y adjúntale las herramientas»). La auditoría real
  falló en REA por argumentos inventados (apk_path/binary_path) y el informe era superficial (30 líneas). Ahora:
  rea_herramientas da la firma compacta (path*, detail?=complete|summary), checkArgs no llama a REA con argumentos
  que no cuadran y devuelve el esquema; guías de análisis por tipo en el sistema; eolfi_informe_anadir (append a
  .md/.txt, un permiso por informe en manual, diario) y abrir el informe al terminar. Pruebas de la extensión 45.
- Herramientas (con permiso explícito del usuario, «instálalos todos… en el path»): descargadas de GitHub con
  SHA-256 verificado contra la API (y el .sha256 de jadx): jadx-headless-mcp-0.7.1-all.jar (el que exige REA),
  capa v10.0.0 y rizin v0.9.1 (shared64) en ~/.eolfi/tools; PATH de usuario + capa y rizin/bin; variable de usuario
  REA_JADX_MCP_JAR; pip install bandit (1.9.4). Eolfi busca también en ~/.eolfi/tools (tools_dir_find,
  EOLFI_TOOLS_DIR). VERIFICADO: eolfi doctor (capa 10.0.0, rizin 0.9.1, Ghidra 12.1.4), rea doctor (jadx healthy),
  triage real de electron.exe con capa y rizin sin fallos (capa: 0 capacidades en ese binario de 200 MB).
  test_resolve_flow ahora simula que no están. Python 298.
- Extensión 0.3.6 (el usuario: «Falla algo»; historial real revisado): la auditoría paró a los 10 pasos con
  «Sigo con el análisis archivo por archivo…» sin llamar a herramientas; el empujón solo cubría preguntas. Ahora
  promisesWithoutDoing detecta anuncios («sigo con», «voy a…», «a continuación», «quedan por revisar»…) y envía
  NUDGE_PROMISE; en automático hasta 10 empujones (manual 3). El historial guarda los nombres de los archivos
  cambiados (anchor). Pruebas con los textos reales; extensión 47; e2e real OK.
- 0.3.6 PROBADO DE VERDAD: la auditoría llegó al final (REA/jadx en el APK, entropía en binarios, patrones
  peligrosos, ruff, 298 pruebas) y abrió el informe. Revisión del informe (150 líneas): mezcla secciones de tres
  ejecuciones, solo 3 de ~97 archivos de código tienen sección propia (no es archivo por archivo), y lo de «.env
  versionado» es falso (no hay repositorio git y .gitignore excluye .env). Siguiente mejora propuesta: auditoría
  archivo por archivo dirigida por Eolfi (inventario + lotes + progreso reanudable) en vez de dejarla al modelo.
- Extensión 0.4.0: auditoría archivo por archivo dirigida por Eolfi (audit.js): inventory (SKIP_DIRS incluye samples,
  generated, backups, informes, node_modules…; locks/minificados/secretos/binarios/vacíos fuera), pieces (archivos
  >60 000 caracteres por partes con su línea inicial), lotes ≤5 archivos / 45 000 caracteres, plantilla fija con
  líneas numeradas, append por lote, estado en ~/.eolfi/audits (EOLFI_AUDIT_DIR) para pausar/continuar, resumen
  con las [alta] y lista de omitidos; abre el informe. /auditar, /auditar continuar, botón «Continuar la
  auditoría» y la frase «audita … archivo por archivo». Inventario real de D:\Eolfi: 129 archivos. Pruebas 52.
- FALLO MÍO corregido: la e2e escribía y borraba ~/.eolfi/vscode-bridge.json del usuario (login/logout en la
  instancia de prueba). Ahora usa EOLFI_VSCODE_BRIDGE_FILE temporal. El usuario debe recargar VS Code para que su
  puente vuelva a escribir el archivo.
- 0.4.0 PROBADO DE VERDAD («Sí, funciona»): /auditar en D:\Eolfi revisó 23 de 129 archivos con buenas secciones
  (propósito, seguridad, errores, calidad, mejoras con líneas) y se cortó sin avisar (estado next=23 guardado).
  0.4.1: si la auditoría se interrumpe (error del modelo, corte) dice en qué archivo y por qué y ofrece «Continuar
  la auditoría»; /auditar continuar sigue por ese archivo. Pruebas de la extensión 53.
- Extensión 0.4.2 («Se vuelve a cortar»): la causa era «you've exceeded your rate limit for utility models» de
  GitHub: GPT-4.1 (copilot-utility) y GPT-4o mini cuentan como «utility» y la auditoría hace decenas de peticiones.
  Auto (familia claude-fable-5.1) sí responde sin herramientas y no gasta ese cupo. Ahora complete() (auditoría)
  usa Auto primero, marca 15 min los modelos limitados y cambia de modelo; si todos lo están espera 60/120/240 s y
  reintenta antes de pausar. El agente cambia de modelo si el suyo se limita (en la 1.ª ronda o a mitad). PROBADO DE
  VERDAD: auditoría de eolfi/security con Auto por el puente (37 s, plantilla correcta). Pruebas 56; e2e OK.
  No se pueden quitar los límites de GitHub (son de la cuenta, en sus servidores); propuesta: usar Eolas local o
  Claude por API cuando Copilot esté limitado.
- Extensión 0.4.3: respaldo local llama.cpp (el usuario: «los modelos de llama.cpp mejor, no quiero ollama»).
  local-model.js: Eolas (llama-server de su lanzador, API /api/* en 11435) o llama-server propio (API OpenAI /v1/*
  en 8080); solo loopback; sin «modo pensar» (chat_template_kwargs.enable_thinking=false, max_tokens 6000); peticiones
  con node:http (el fetch de Node corta a los 5 min sin cabeceras). complete() lo usa cuando Copilot está limitado
  (también si todos ya estaban marcados) antes de esperar. PROBADO DE VERDAD: llama-server temporal
  (D:\HYDRA-BASE\llama, qwen3.5-4b Q4_K_M) revisó eolfi/dotenv.py con la plantilla en 4 s. Pruebas 61; e2e OK.
  Aviso: al consultar `ollama list` se arrancó Ollama sin querer; el clasificador de permisos no me dejó cerrarlo.
- Extensión 0.4.4 («Sí, que lo arranque»): llama-starter.js busca llama-server.exe (~/.eolfi/tools/llama,
  D:/HYDRA-BASE/llama, D:/HYDRA/runtime/llama-bin, D:/EOLAS-BASE/llama, PATH) y el GGUF más adecuado para código
  (*coder*, gemma-4, qwen3.5… en Q4_K_M; sin imagen/vocab/<500 MB); lo arranca en 127.0.0.1 (primer puerto libre
  desde 8080), espera /health, lo reutiliza y lo para al cerrar VS Code o tras 15 min sin uso; solo para el suyo.
  Permiso modal una vez por sesión en manual; sin preguntar en automático. PROBADO DE VERDAD: sin nada en 8080,
  arrancó D:/HYDRA-BASE/llama/llama-server.exe + qwen3.5-4b-Q4_K_M, revisó history.js con la plantilla (96 s con
  la carga) y lo paró (8080 libre). Pruebas de la extensión 65; e2e OK.
- Extensión 0.4.5 (la auditoría llegó a 65/129 y se cortó por «net::ERR_CONNECTION_RESET»): los fallos de red
  pasajeros (TRANSIENT: ECONNRESET, ERR_CONNECTION_RESET, timeouts, fetch failed, 502/503/504…) se reintentan con el
  mismo modelo a los 2, 5 y 15 s; si sigue, ese modelo descansa 2 min y se pasa al siguiente y al llama.cpp local.
  El agente reintenta igual si la red falla antes de que el modelo escriba nada. El aviso «The MCP servers … Start
  them now?» es de VS Code, no de Eolfi. Pruebas de la extensión 68; e2e OK.
- Extensión 0.4.6 («Eolfi: Sorry, you've exceeded your rate limit for utility models»): el usuario escribió
  «auditar continuar. Retoma en el archivo 66.» sin la barra, así que fue al agente con herramientas; sus modelos
  (GPT-4.1, GPT-4o mini) son «utility» y estaban limitados, y Auto sigue rechazando herramientas desde extensiones
  («Auto mode needs a prompt or a command to route a request», comprobado por el puente). Ahora: «auditar
  continuar» / «continúa|retoma|sigue la auditoría» sin barra van a la auditoría; el agente, si todos sus modelos
  están limitados, espera 60/120/240 s y reintenta y, si no, explica qué pasa y que /auditar sí sigue. Pruebas 70.
- AUDITORÍA COMPLETA (usuario): «129 archivos revisados uno a uno, 69 mejoras de prioridad alta» en
  informes/auditoria-archivos-Eolfi-2026-11-06.md.
- Extensión 0.4.7: el agente con herramientas sigue con llama.cpp local si todos sus modelos de Copilot están
  limitados (antes de esperar). local-model.chatTools (API OpenAI de llama-server con tools/tool_choice y API de
  Eolas), llama-starter añade --jinja, runLocalAgent en chat.js (mismas herramientas, historial corto, recorte a
  60 000 caracteres, empujones). Afinado ASKS: ya no cuenta como pregunta al usuario una cita que acaba en «?».
  PROBADO DE VERDAD: llama-server arrancado por Eolfi, qwen3.5-4b llamó a eolfi_read_file(eolfi/dotenv.py) y lo
  resumió; se paró al terminar. Pruebas de la extensión 74; e2e OK.

## Verificación de la auditoría archivo por archivo (2026-11-06)
- 69 mejoras [alta] verificadas contra el código: ~20 reales; el resto falsos positivos o diseño (títulos y recursos
  ya saneados por build_spec; Reader con límites y presupuesto + fuzzer; panel sin innerHTML; isolated.py ya limita
  módulos; core.js auto_approve lo concede el usuario; external.py ya pasa check_cmd_safe…).
- Grupo 1 HECHO (Python, pruebas en tests/test_verificacion_auditoria.py): .gitignore.extra se fusiona en .gitignore
  (antes se borraba: .NET sin bin/obj ignorados; CLI sin build/*.spec); _check_spec en generate(); servidor estático
  con root+sep; diff_flow con _safe_input también en la repetición de determinismo y tope de 256 MB por entrada;
  vinculación: al 5.º fallo se anulan los códigos pendientes; subproceso aislado sin variables secretas; assist
  comprueba la contención lo primero. Python 302.
- Grupos 2 y 3 HECHOS (extensión 0.5.1): terminal sin Ctrl+C tardío; workspace con realpath (uniones); estado de la
  auditoría validado; fetch.py allow_private solo con localhost/IP privada explícita y para ese host; agent-tools
  pinnedFetch (IP validada, sin re-resolver DNS, tope de lectura); rea.js safeEnv y confirmación por nombre
  primero; tope de descompresión ZIP (apksig 4 MB, apple 8 MB); pruebas débiles corregidas (test_fase_a,
  panel.test, e2e/run.js). Veredicto de los 69 en informes/verificacion-auditoria-2026-11-06.md. Python 306;
  extensión 81; e2e real 11/11; panel e2e 7.

## llama.cpp con Gemma 4 local, configurable y con razonamiento (2026-11-06)
- GPU RTX 3060 Ti 8 GB: por defecto Gemma 4 E4B Q4_K_M (D:/LMStudio/models/lmstudio-community, 5 GB, entera en GPU);
  la 12B Q5_K_M (D:/AI/Hydra/gguf, 8 GB) no cabe entera. llama-server D:/HYDRA-BASE/llama (build 11968).
- eolfi/llamacpp.py + vscode-bridge/llamacpp-config.js: configuración común ~/.eolfi/llamacpp.json (se crea con
  Gemma 4), arranque/parada (pid y log junto al JSON), request_options (temperature, top_p, max_tokens,
  chat_template_kwargs.enable_thinking). Proveedor «gemma» (LlamaCppProvider: json_schema, last_reasoning,
  instrucciones `system`), CLI `eolfi llama [status|start|stop|config]`, opción en «Crear».
- Extensión 0.5.0: eolfi.agent.model (copilot|local) y `/modelo`; con local el agente va directo a Gemma (sin pasar
  por Copilot) y la auditoría también; razonamiento en «> 💭 Razonamiento» si show_reasoning; eolfi.agent.instructions
  para cualquier modelo; sin Copilot (sin sesión) también usa el local; llama-starter lee la configuración (puerto,
  ctx, -ngl, alias, --reasoning-format deepseek, extra_args); comando «Eolfi: configurar el modelo local».
- PROBADO DE VERDAD: con/sin razonamiento (6,8 s / 0,9 s); proveedor gemma desde Python con JSON (8 s); por el camino
  de la extensión, arranque solo con la configuración, razonamiento + llamada a eolfi_read_file + respuesta y parada.
  Gemma razona en inglés aunque responda en español. Python 304; extensión 77; e2e OK.
- Extensión 0.5.2 (el usuario: que la auditoría filtre lo que no son fallos): audit.js carga el contexto del proyecto
  (<carpeta>/.eolfi/auditoria.md) en cada lote y, al terminar, verifyHighlights pasa cada [alta] con el fragmento
  real que cita (líneas ±10) al modelo → REAL / FALSO / DISEÑO con motivo (JSON; dudoso = REAL). El informe añade
  «Verificación…» y «Descartadas al verificar»; el resumen solo con las reales; se recuerda al reanudar. Escrito
  D:/Eolfi/.eolfi/auditoria.md con las salvaguardas y decisiones de hoy. Prueba real con Gemma 4 E4B sobre las 69
  del informe viejo contra el código ya corregido: 7 REAL, 58 FALSO, 4 DISEÑO en 128 s (muchos FALSO porque ya
  están arreglados; la E4B es indulgente y algún motivo es pobre: mejor Auto para verificar). Extensión 83 pruebas.

## Espacio en C: (2026-11-06, tras reiniciar)
- C: tenía 11 GB libres. Causa principal MÍA: la prueba «elige el GGUF» (test/llama-starter.test.js) creaba ~2,9 GB
  de .gguf falsos en Temp y no los borraba: 15 carpetas gguf-* = 43 GB. Borradas (verificadas una a una: solo los 6
  .gguf de la prueba) → C: 54,3 GB libres. La prueba usa ahora archivos pequeños (findGguf minBytes) y borra su
  carpeta; `npm test` corre con un TEMP propio que se borra (scripts/test.js); e2e/launch.js borra su perfil.
- Quedan ~830 MB de restos de pruebas viejas en Temp (eolfi-e2e-*, tmp.*, eolfi-*): el clasificador de permisos no
  dejó barrerlos por patrón; los puede borrar el usuario (Liberador de espacio o a mano).
- Claude-Data (21,8 GB) NO se mueve ni se borra a mano (lo prohíbe su README y el almacenamiento de la app): Claude →
  Ajustes → Este equipo → Almacenamiento → Borrar caché.
- Auditoría verificada: se paró en 27/137 (VS Code se cerró al reiniciar y el respaldo Gemma dio HTTP 400: el lote real
  medía 20 207 tokens y el contexto era 16 384). Arreglo: ctx 32768 por defecto y en ~/.eolfi/llamacpp.json, y
  reviewBatch parte en dos los lotes que no caben (TOO_BIG). Comprobado con el lote real: HTTP 200. Extensión 0.5.3,
  87 pruebas. La auditoría puede seguir con `@eolfi /auditar continuar` (estado guardado en 27/137).

## Migración de @eolfi al modo agente y panel modernizado (2026-11-06, Claude en la nube)
- Motivo: VS Code avisa «Replace Chat Participant» (los participantes están obsoletos y el harness de Copilot no los
  admite) y @eolfi decía que «celtiaia» no existía estando abierta en la ventana.
- Python: eolfi/mcp_server.py + `eolfi mcp` (stdio, JSON-RPC, protocolo 2025-06-18): 10 herramientas, stdout solo
  protocolo, rutas limitadas a --root/EOLFI_ROOTS, resultados marcados como DATOS y recortados a 60 000 caracteres.
  tests/test_mcp_server.py (6).
- Extensión 0.6.0 (engines ^1.101): lm-integration.js registra el servidor MCP (mcpServerDefinitionProviders) y 5
  languageModelTools (eolfi_carpetas, eolfi_auditar, eolfi_historial, rea_herramientas, rea_usar) con la lógica de
  chat.js (handler.lmTool); confirmación para auditar y REA salvo en modo automático. Agente y prompt files en
  vscode-bridge/agent/ → comando «Eolfi: instalar el agente en este workspace». Ajustes nuevos: eolfi.chatParticipant,
  eolfi.python, eolfi.mcp.enabled|db|restrictToWorkspace.
- Carpetas por nombre: workspace.js findFolderByName/pickRelative (nombre del workspace, de la carpeta o subcarpeta de
  primer nivel; sin mayúsculas, tildes ni separadores); resolveTarget y /auditar lo usan; el prompt del agente lista
  las carpetas abiertas. isSecretPath reconoce rutas con «\» en cualquier sistema. Pruebas: folders.test.js,
  lm-integration.test.js; extensión 94.
- Panel web: barra superior fija con vistas siempre visibles (aria-current), menú «Exportar», estado vacío con
  pistas, sistema visual nuevo (tokens, tarjetas, pestañas segmentadas, foco visible, [hidden] siempre gana, sin
  transiciones de color para no romper el contraste al cambiar de tema), móvil revisado. Mismos ids: app.js casi igual.
  e2e del panel: la prueba de subir un binario espera a las evidencias (antes contaba de inmediato y fallaba a veces).
- Pendiente de probar en Windows: la extensión dentro de VS Code real (registro MCP y herramientas) y e2e completas.
- Extensión 0.6.1 (revisión de la auditoría de D:\celtiaia del 2026-11-06): el informe del agente decía «falta
  package-lock.json» (el package.json raíz no tiene dependencias; las reales están en scripts/fios, con lock), usó
  «node --test --json» (no existe), pasó Bandit sobre node_modules/frida, probó solo uno de los dos módulos Go y no
  avisó de que git no tenía commits. Nuevo checks.js + herramienta eolfi_comprobaciones: encuentra todos los
  subproyectos (sin node_modules ni lo ignorado por .gitignore), el estado de git y las órdenes exactas por carpeta
  (npm audit solo con dependencias, npm test / node --test, go test por módulo, bandit/ruff/semgrep con exclusiones)
  y reglas de alcance («NO EVALUADA», no concluir «sin vulnerabilidades» sin cobertura). Prompt de auditoría
  actualizado. Pruebas de la extensión 101 (7 nuevas). Copia previa en backups/antes-comprobaciones-2026-11-06.
  Pendiente: probarlo de verdad en VS Code con /auditar sobre D:\celtiaia.
- Extensión 0.6.2 («se cortó a los 13» en D:\celtiaia): /auditar paraba en el archivo 13 de 2151 con «Message exceeds
  token limit.». Causas: docs/audit/rea/force-main-preload-static.json (55 MB en UNA línea) entraba entero porque
  MAX_FILE no se aplicaba y pieces() solo partía por líneas; TOO_BIG no reconocía ese mensaje de Copilot, así que no
  se partía el lote; y si no cabía ni partido, se paraba toda la auditoría. Además el inventario no miraba .gitignore
  (runtime/ aportaba ~1600 de los 2151). Ahora: .gitignore de la raíz respetado (carpetas, globs, negaciones),
  archivos >2 MB omitidos, líneas enormes troceadas, TOO_BIG con «token limit»/413 (sin confundir el rate limit), lo
  que no cabe se anota como omitido y sigue, y al continuar se recalcula lo pendiente (D:\celtiaia: 479 archivos).
  Pruebas de la extensión 108.
- Extensión 0.6.3 (revisión del informe de D:\celtiaia): el informe mezclaba tres ejecuciones (la de 2151 cortada, el
  resumen del agente y una nueva de 479). Causas: «d:\celtiaia» y «D:\celtiaia» se trataban como carpetas distintas
  (comparación sensible a mayúsculas: se empezaba de cero) y una auditoría nueva se añadía al informe del día ya
  existente. Ahora se comparan sin mayúsculas en Windows y una auditoría nueva usa otro archivo (-HHMM). El plan de
  eolfi_comprobaciones pide commit (git rev-parse HEAD), versiones de herramientas y reglas: orden y resultado por
  sección, npm audit por paquete con versión corregida, códigos de regla de Bandit/Ruff sin inventar el tipo de fallo
  (B310 ≠ path traversal demostrado), git status fechado. Pruebas 110 (1 solo en Windows).
- Extensión 0.6.4 («@eolfi sigue consumiendo de GitHub»): con /modelo local, si Eolas fallaba (HTTP 500 sin motivo),
  complete() pasaba a Copilot sin preguntar. Ahora reintenta en local una vez y, si sigue fallando, para la auditoría
  con el motivo (no gasta de Copilot); un error de tamaño sube para que se parta el lote. El error de Eolas incluye el
  cuerpo de la respuesta. Pruebas 113.
- Extensión 0.6.5 (Eolas con Gemma por llama-server): las llamadas a herramientas de Gemma llegaban como texto
  («<|tool_call>call:nombre{...}<tool_call|>») y el razonamiento se colaba en la respuesta. local-model.js las convierte
  en llamadas reales y quita el razonamiento; los encabezados del informe se normalizan a «### `ruta`». Prueba e2e en
  vivo (e2e/local-eolas-live.js): Eolfi usa Eolas y Copilot no se llama (8/8).
- Extensión 0.6.6: pie «Modelo: X · en tu equipo, sin Copilot» en las respuestas del agente y «Modelos usados» en las
  auditorías (ajuste eolfi.agent.showModel, activo por defecto). Licencia: titular único Luis Manuel Cousido Hermida;
  nuevo LICENCIAS-TERCEROS.md. Pruebas 117 (1 solo en Windows).
