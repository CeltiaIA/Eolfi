# Plan: REA dentro de Eolfi

Fecha: 13/11/2026. Acordado con el titular en la sesión de trabajo. El estado vivo de cada punto se mantiene aquí y en
[ESTADO-TRABAJO.md](ESTADO-TRABAJO.md).

## Objetivo

Que Eolfi, coordinado desde el chat por el motor que se elija en Eolas V2, aproveche REA (229 herramientas de
ingeniería inversa) para analizar, explicar, reconstruir y generar código, con evidencias y sin ejecutar nada sin
autorización.

## Reglas que se mantienen en todo el plan

- **Todo con REA a través de Eolfi** (decisión del titular, 13/11/2026). Cada pieza nueva usa REA mediante el
  cliente de Eolfi (`eolfi/rea_client.py`) y queda disponible en el chat, en la línea de órdenes y en el panel. Nada
  llama a REA por su cuenta: así se aplican siempre las mismas reglas de rutas, bloqueo y registro.

- **Nada se ejecuta sin autorización.** Lo que ejecuta o instrumenta el objetivo (Frida, depuradores, capturas de
  procesos o navegador, ADB, órdenes libres de rizin o Cutter) está bloqueado en el chat hasta que exista la
  autorización por caso (punto 7). AGENTS.md: «No ejecutes el artefacto para obtener cobertura sin autorización».
- **Lo que devuelve REA es contenido del objetivo:** datos no confiables, nunca instrucciones.
- **Rutas:** se validan contra las carpetas permitidas de Eolfi antes de llegar a REA.
- **Equivalencia:** una prueba verde no demuestra equivalencia funcional. Toda reconstrucción o reimplementación lo
  dice y enumera lo que no se pudo comprobar.
- **Derechos de autor:** lo que REA recupere de programas de terceros (descompilaciones, fuentes JavaScript) no va a
  Alejandría como código reutilizable. Sí los informes y el código que Eolfi genere de forma original.
- **Registro:** SHA-256 del objetivo, proveedor y versión, alcance, cobertura y límites en cada informe.

## Hecho

| Pieza | Dónde | Verificación |
|---|---|---|
| Cliente MCP de REA | `eolfi/rea_client.py` | Pruebas con REA simulado y contra el REA real |
| REA en el chat de Eolas V2: 13 herramientas estáticas directas y catálogo completo (`rea_buscar`, `rea_ayuda`, `rea_usar`), también las de escritura | `eolfi/rea_client.py`, `eolfi/chat.py` | Catálogo, entropía y bloqueo de Frida contra el REA real |
| Revisar modelos de IA (cabecera GGUF/safetensors; la cuantización real coincide con el nombre) | `eolfi/rea_compuestas.py`, `eolfi eolas-v2 revisar` | Gemma 4 Q4 y Gemma 3 Q4: aprobados |
| Explicar binario (Ghidra estático: importaciones, cadenas, pseudocódigo de las funciones clave) | `eolfi/rea_compuestas.py` | `whoami.exe`, 48 s |
| Reimplementar función (pseudocódigo, firma y llamadas; Eolas escribe versión propia y la prueba) | `eolfi/rea_compuestas.py` | Función `entry`, 44 s |
| Diferencias entre versiones (punto 3): `compare_artifacts` + `verify_reconstruction` y, de Eolfi, importaciones y funciones con nombre añadidas o quitadas | `eolfi/rea_compuestas.py` | `whoami.exe` frente a `hostname.exe`: «changed», verificación «fail», 101 s; mismo archivo: «unchanged» |
| Autorización por caso (punto 2): lo que ejecuta crea una petición; el titular decide en el chat; «una vez» se consume, «en este caso» vale hasta revocar; todo queda registrado (`rea_requests`, `rea_grants`, `rea_exec_log` en eolfi.db) | `eolfi/rea_autorizacion.py`, API `/api/rea/autorizaciones`, tarjeta en el chat | `tests/test_rea_autorizacion.py`; la tarjeta se ve en el panel |
| Inventario de dependencias (punto 4): DLL e imphash, certificados y recursos de un PE; versión, módulo y dependencias de Go; dependencias de Rust si es «auditable»; lo que no aplica se dice | `eolfi/rea_compuestas.py`, `eolfi rea inventario`, `eolfi_inventario_dependencias` en el chat | `whoami.exe` (11 DLL, 3 s) y `docker.exe` (Go 1.26.5, firmado, 2 s) |
| Verificar comportamiento (punto 1): sin los permisos de los DOS lados no se ejecuta nada y no se gasta ningún «una vez» | `eolfi/rea_compuestas.py`, `eolfi_verificar_comportamiento` en el chat | `tests/test_rea_autorizacion.py` con REA simulado; NO VERIFICADO en vivo |
| Registro en el caso (punto 6): con un caso activo (chat) o `eolfi rea --caso`, el objetivo queda como artefacto, el resultado como evidencia «rea» y lo que REA no pudo establecer como incógnitas | `eolfi/rea_caso.py` | `tests/test_rea_caso.py`; REA real: inventario de whoami.exe registrado en un caso de prueba |
| Analizar app JavaScript (punto 5): estadísticas, superficie de Electron (ventanas, precargas, IPC, módulos nativos) y cobertura del grafo semántico, sin ejecutar | `eolfi/rea_compuestas.py`, `eolfi rea app-js`, `eolfi_analizar_app_js` | Panel de Eolfi (`eolfi/web`): 7 archivos JS, 791 relaciones de llamadas, 16 s. `recover_javascript_sources` necesita Linux x64 + Wakaru: no disponible en este Windows |
| Recuperar fuentes JavaScript (punto 5): Wakaru 1.14.0 vía el REA de WSL2 Ubuntu; la salida se crea en Ubuntu (REA exige propiedad que `/mnt/c` no da), se copia a Windows y se borra de Ubuntu | `tools/instalar-rea-wsl.sh` (Node v24.22.3, rea-agents@6.8.0 y Wakaru en `~/.local/eolfi-rea`, sin sudo, verificados por SHA-256), `eolfi/rea_client.py` (`wsl_rea_command`, `wsl_path`), `eolfi rea recuperar-js`, `eolfi_recuperar_fuentes_js` | `eolfi/web/runtime.js`: «complete», 1 módulo decompilado con mapa de fuentes, 9 s |
| Orden `eolfi rea` (revisar-modelo, explicar, reimplementar, comparar) y las cuatro en el chat | `eolfi/cli.py`, `eolfi/chat.py`, `eolfi/server.py` | Suite completa: 536 en verde |
| Herramientas instaladas para REA: Apktool 3.0.3, Wireshark 4.6.9 (tshark, capinfos); Frida viene integrado | `~/.eolfi/tools/apktool`, variables `REA_*` | `inspect-apktool-client`, `inspect-pcap-client`, `list-frida-devices` |

**Verificado en vivo (14/11/2026):**

- **Chat con REA (gemma, Eolas V2):** inspeccionó `eolas-chat.js` con REA (rea_buscar → rea_ayuda → rea_usar
  `inspect_byte_entropy`); tamaño y SHA-256 iguales a los reales. Ante una herramienta que ejecuta algo
  (`capture_process_scenario`) creó la petición de autorización sin ejecutar nada; aprobada «una vez» en la tarjeta del
  chat, se ejecutó una sola vez y quedó en el registro (REA no soporta esa captura en Windows: «sin PTY»). Corregido
  por el camino: la instrucción y `rea_usar` decían «permitida» y el modelo descartaba sin buscarlas las que ejecutan.
- **`eolfi rea inventario`** sobre `whoami.exe` (5 s): 11 librerías, recuentos e imphash iguales a `objdump`.
- **`eolfi rea --caso <id> explicar`** (49 s, Ghidra): punto de entrada `0x140001cb0` igual al de la cabecera PE;
  registrado en el caso (artefacto y evidencia). Sus importaciones (121, símbolos externos de Ghidra) difieren de la
  tabla PE (127): ahora el informe lo dice en `fuente_cifras`. Corregido: `--caso` se comprueba antes del análisis.

- **`eolfi rea revisar-modelo`** (4–6 s, solo cabecera): Gemma 4 Q5 y Q4 aprobados, con la cuantización dominante
  (Q5_K, Q4_K) igual al `general.file_type` leído con un lector GGUF propio (17 y 15). Con el mismo Q4 enlazado con el
  nombre `…-Q8_0.gguf`, **no aprueba**: «la cuantización real coincide con el nombre (Q8_0)» falso, dominante Q4_K. Un
  GGUF recortado se rechaza: REA comprueba que los tensores quepan en el archivo.
- **`eolfi rea reimplementar whoami.exe entry`** (53 s): 18 bytes y llamadas a `0x1400021b4` y `0x140001af0` (esta
  como salto de cola), iguales al desensamblado de `objdump`.

- **`eolfi rea comparar`** con dos versiones reales de `whoami.exe` sacadas de WinSxS (10.0.26100.1 y .1882, 85 s):
  REA dice «changed», mismas importaciones y funciones con nombre, igual que `objdump`. Como REA no decía DÓNDE, Eolfi
  añade `bytes_cambiados`: 424 de 98 304 (277 en `.rsrc`, 76 de cabecera, 68 en `.rdata`, 2 en `.data`, 1 en `.text`),
  igual que `cmp`, con la dirección del byte de código (`0x1400073ba`): el desplazamiento de un `lea` a un dato que se
  movió 8 bytes, no lógica nueva.

- **Verificación de comportamiento** (aprobada por el titular, cada ejecución con su permiso «una vez» y registrada;
  REA de WSL, porque el de Windows no tiene PTY): original `/usr/bin/whoami` frente a una reconstrucción en Python
  (`pwd.getpwuid(os.geteuid())`) y un control que imprime otro nombre. Se encontraron dos fallos de medida:
  1. REA comparaba los milisegundos de cada fragmento del terminal: «mejil\r\n» a los 30 y a los 60 ms salía
     «changed». Corregido en Eolfi: el escenario pide `normalization.time_bucket_ms = 1000`.
  2. REA mete en `exit` el tiempo de cierre (`settlement.elapsed_ms`, de 79 a 93 ms), que no se normaliza: con el
     mismo código 0, `exit` sale «changed» unas veces y otras no (4 de 6 sin corregir). Es de REA. Eolfi añade
     `comprobacion_eolfi`: código, señal y motivo de salida y texto del terminal, sin tiempos.
  Resultado tras corregir (6 ejecuciones): Eolfi da «igual/igual» en las 5 iguales y «terminal distinto» en el
  control; REA sigue dando `exit` «fail» en 4 de 5 iguales y `terminal` «unknown» (incógnitas residuales de archivos
  y procesos, que no se observaron). NO VERIFICADO: archivos, procesos hijos, red y entorno; programas interactivos.
- **Programas de Windows** (14/11/2026): en el chat la verificación siempre fallaba, porque usaba el REA de Windows,
  que no tiene PTY. Ahora, en Windows, va por el REA de WSL: las rutas `X:\…` pasan a `/mnt/x/…` (los argumentos solo
  cuando el programa es de Linux) y los `.exe` corren por la interoperabilidad. ConPTY pregunta al arrancar la
  posición del cursor (`ESC[6n`) y, sin respuesta, `whoami.exe` se quedaba colgado hasta el tiempo límite; Eolfi le
  responde «1;1» a los 300 ms y termina con código 0. Los permisos se piden sobre el escenario traducido (lo que de
  verdad se ejecuta) y el REA de WSL solo arranca si ya están concedidos. `comprobacion_eolfi` quita las secuencias
  de control del terminal: con ConPTY, REA marca el terminal «fail» porque el título de la ventana lleva la ruta del
  programa. En vivo: `whoami.exe` frente a un script en el Python de Windows (`GetUserNameExW`) → Eolfi «igual/igual»
  (`celtia\mejil`); el control → «terminal distinto».
- **Libro de obligaciones** (14/11/2026): con `modulo` en la reconstrucción, Eolfi exporta el paquete de evidencias de
  la sesión (`export_evidence_bundle`), declara la obligación «se comporta como el original en este escenario» con su
  caso del original, el fixture y el verificador, y la ata a su propietario (archivo y SHA-256) con
  `build_reconstruction_obligation_ledger`. En vivo: libro `failed` (el verificador de REA falla por el título de
  ConPTY), cobertura `complete`, obligación «implemented» y 2 obligaciones que REA genera por cada captura, sin
  propietario. **Límite de REA:** como prueba de fixture y verificador solo admite un registro
  `rea.reconstruction-proof` (operación `verify_reconstruction_obligations`, confianza `observed`) que no genera
  ninguna de sus herramientas públicas. Eolfi no fabrica registros de evidencia, así que la obligación no pasa de
  «implemented».
- **Cobertura por frontera** (14/11/2026, `evaluate_reconstruction_coverage`, con el mismo paquete de evidencias):
  una superficie (la salida en el escenario), su propietario, una afirmación y un contrato de verificador por
  dimensión (terminal, exit) con el estado de `verify_reconstruction`. El resumen del contrato es el SHA-256 del JSON
  canónico RFC 8785 sin `contract_sha256` (sin espacios; con los separadores por defecto de Python REA lo rechaza).
  REA solo cuenta como comparable la evidencia `controlled-replay` con confianza `observed`, así que se citan las dos
  capturas además de la comparación y la verificación. Lo no demostrado se declara `unknown` (si el módulo se
  distribuye) y la frontera exige la prueba de independencia (ver abajo): no puede salir «ready». En vivo con `whoami.exe`: «failed» (el verificador de REA falla) con 5 razones y sus
  siguientes pruebas.
- **Prueba de independencia** (14/11/2026, `prueba_independencia`, `kind: authority-independence`): ¿la
  reconstrucción llama al original? Dos partes y las dos tienen que salir limpias para «pass»: (1) estática, el
  módulo (Python por AST, JavaScript por patrones) no tiene primitivas para lanzar programas (`subprocess`, `os.system`,
  `os.exec*`, `ctypes`, `child_process`…), ni código dinámico (`eval`, `exec`, `getattr` con nombre construido), ni
  importa código fuera de la biblioteca estándar, y es lo que se ejecuta en el escenario; (2) en ejecución, en el
  muestreo de procesos de REA de la reconstrucción no aparece el original y el muestreo no es parcial. «fail» si se
  ve el original, si la reconstrucción tiene el mismo SHA-256 que el original o si el módulo tiene primitivas y
  nombra al original; todo lo demás, «unknown». La prueba cita la captura observada de la reconstrucción (REA solo
  admite `shipped-artifact` o `live-observation`) y fija `authority_route` del propietario. En vivo: `whoami` contra
  `whoami_rec.py` → «pass» y REA deja de pedir la independencia; contra una reconstrucción que hace
  `subprocess.run(["whoami"])` → «fail» por la parte estática, porque **el muestreo de REA no vio el hijo** (dura
  muy poco): el muestreo solo no basta para dar «pass»; `whoami.exe` contra Python de Windows con `ctypes` →
  «unknown» (primitiva nativa y, desde WSL, no se ven los hijos de un programa de Windows). Con una reconstrucción
  ajena, escrita fuera de Eolfi sin ver las anteriores (con `os.geteuid` + `pwd`; procedencia, probablemente asistida
  por IA, pendiente de confirmar), el 14/11: comportamiento «igual» e independencia «pass». Siguen sin «ready»:
  la distribución del módulo (`owner-distribution-unknown`) y el verificador de REA, que falla en `exit` por el
  tiempo de cierre. NO VERIFICADO: red y servicios (solo procesos), módulos en otros lenguajes, rutas construidas
  dentro de la biblioteca estándar.

## Lo que crearemos, por orden

| # | Pieza | Qué combina | Qué da | Estado |
|---|---|---|---|---|
| 1 | **Cobertura de reconstrucción** | `build_reconstruction_obligation_ledger`, `evaluate_reconstruction_coverage`, `verify_reconstruction` | Qué parte del original cubre el proyecto que generó Eolfi y qué falta, con evidencias (fase 4) | Estructural hecha (con el punto 3). Comportamiento hecho: `verificar_comportamiento` ejecuta original y reconstrucción con el mismo escenario (`capture_process_scenario`), compara (`compare_process_captures`) y verifica afirmaciones `behavioral` (overall, terminal, exit), siempre con permiso del titular. Probado en vivo el 14/11 (ver arriba), también con programas de Windows vía el REA de WSL. Libro de obligaciones hecho (`build_reconstruction_obligation_ledger`, con propietario), limitado a «implemented» por REA. Cobertura por frontera hecha (`evaluate_reconstruction_coverage`). Prueba de independencia hecha (estática + muestreo de procesos; en vivo «pass», «fail» y «unknown»). Falta: cómo se distribuye el módulo, para que la cobertura pueda salir «ready» |
| 2 | **Autorización por caso en el chat** (hecho) | Petición del modelo y decisión del titular («una vez», «en este caso», «rechazar»), con registro y revocación | Habilita el análisis dinámico (Frida, gdb, capturas, `observe_*`) solo con permiso expreso | Hecho; falta probarlo en vivo con un modelo |
| 3 | **Diferencias entre versiones** (hecho) | `compare_artifacts`, `compare_functions`, `find_changed_behavior`, `compare_application_versions`, `compare_wasm_interfaces` | Informe «qué cambió entre A y B» | Hecho (ver «Hecho») |
| 4 | **Inventario de dependencias** (hecho) | `inspect_pe_imports`, `inspect_native_exports`, `inspect_go_binary`, `inspect_rust_binary`, `inspect_pe_certificates` | Librerías, versiones, firmas y certificados | Hecho (ver «Hecho») |
| 5 | **Apps JavaScript, Electron y web** (hecho, con recuperación de fuentes vía REA en WSL2) | `analyze_javascript_application`, `recover_javascript_sources`, `trace_javascript_semantics`, `compare_source_to_bundle` | Fuentes recuperadas y trazadas: base para regenerar la app | Hecho (ver «Hecho») |
| 6 | **Evidencias e incógnitas compartidas** (hecho, salvo exportar el paquete completo de REA) | `export_evidence_bundle`, `import_evidence_bundle`, `record_unknown`, `update_unknown` | Un mismo caso de Eolfi con lo analizado en VS Code, en el chat o por Claude | Hecho, salvo exportar el paquete completo de REA |
| 7 | **De captura de red a API** | `inspect_pcap_capture`, `inspect_packet_fields` y Eolas | Especificación de API (estilo OpenAPI) y un cliente generado por Eolfi | Borrador hecho (`api_desde_captura`: básico con el REA de Windows, OpenAPI 3 con tshark en WSL). Cliente hecho (14/11/2026, `eolfi/cliente_api.py`, `eolfi rea api <captura> --cliente cliente.py`): una función por operación observada, solo biblioteca estándar, sin excepciones por código HTTP y con `observado` en cada respuesta; con el nivel básico no se genera (faltan los métodos) y nunca sobrescribe. Falta: probarlo con una captura real y autenticación más allá de cabeceras fijas |
| 8 | **Mapa de la app en el panel** | `project_android_application_graph`, `get_call_graph`, `build_call_path` | Grafo visual: pantallas, clases y llamadas | Mapa Android hecho en datos (14/11/2026, `mapa_app_android`, `eolfi rea mapa-app <apk>`): paquete y SDK, permisos (los peligrosos aparte), componentes por tipo, lanzadores, exportados sin permiso (proveedores, servicios y receptores primero) y estructura del APK (DEX, nativas por ABI, familias de ejecución, puentes). En vivo con Appium ApiDemos 6.0.18 (SHA-256 `a9eecf37…f686`): 355 componentes, 9 permisos peligrosos, 13 DEX, `dalvik-art`. Falta: el grafo visual en el panel y las llamadas (`get_call_graph`, `build_call_path`) |
| 9 | **Móvil y código gestionado** | JADX, .NET, Unity IL2CPP, Flutter/Dart, Apple (Mach-O, plist, Swift) | Análisis por plataforma | Pendiente |
| 10 | **Firmware** | `extract_firmware`, `inspect_firmware_regions`, `inspect_devicetree` | Desglose de una imagen de firmware | Hecho el desglose (14/11/2026, `firmware_regiones`, `eolfi rea firmware <imagen>`): firmas de Binwalk 3.1.0 (REA de WSL) con desplazamiento, tamaño declarado y confianza, más los huecos sin firma (relleno 0xFF, ceros o datos) que calcula Eolfi y la sugerencia de `inspect_devicetree` si aparece un DTB. En vivo con una imagen sintética: gzip, ZIP y PNG en sus desplazamientos exactos. Binwalk se compila desde el commit auditado con `tools/instalar-binwalk-wsl.sh` (sin sudo). Falta: extracción (`extract_firmware` necesita Unblob 26.6.x) y una imagen real |
| 11 | **Entorno de agente de una web** | `export_environment_bundle` (AgentEnv) | Paquete para que un agente trabaje sobre una web capturada | Hecho (14/11/2026, `entorno_agente`, `eolfi rea entorno <captura.har> <destino> [--nombre] [--escribir]`): ensayo por defecto; con `--escribir`, carpeta nueva con README, manifiesto, evidencias, Dockerfile, verificador y tarea de humo. En vivo con un HAR sintético de una tienda: 3 herramientas (`get_items`, `get_items_by_id`, `post_items`), 2 lecturas desde el estado y la creación servida. NO VERIFICADO: arrancar el entorno (Docker + `rea environment-serve`) y HAR reales |
| 12 | **Automejora recursiva (RSI), acotada** | Observaciones de `eolfi rea`, `create --ai` y el juez funcional; reglas síntoma → propuesta; banco «tareas»; registro encadenado | Eolfi mejora su propia configuración con pruebas repetidas y el titular decide qué se adopta | Hecho (16/11): `eolfi/rsi.py`, `eolfi/rsi_banco.py`, `eolfi rsi`, lecciones de V2, observación del chat y tarjeta en el panel. Falta: evaluación en vivo con el banco |

## Punto 12: automejora recursiva (RSI)

Pedido por el titular el 16/11/2026 («incluye e implementa en el plan de REA un sistema recursive-self-improvement»).
Eolfi aprende de sus propios resultados con REA y con la IA local, pero solo dentro de límites que no se pueden
mejorar a sí mismos.

**Ciclo** (`eolfi/rsi.py`, orden `eolfi rsi`):

1. **Observar.** `eolfi rea …` y `create --ai` anotan cada resultado: fuente, operación, éxito y **síntomas**
   (salida cortada por longitud, plazo de REA agotado, plazo local, sintaxis JS del sitio). No se guarda el contenido
   analizado ni el código: lo que devuelve REA es del objetivo.
2. **Proponer** (`eolfi rsi proponer`). Una regla convierte un síntoma repetido en un cambio concreto sobre una
   **superficie** declarada; hay como mucho una propuesta abierta por regla.
3. **Evaluar** (`eolfi rsi evaluar ID --proveedor …`). La línea base y la candidata pasan el mismo banco en al menos
   5 pares alternados (base, candidata) con la misma semilla por par; la candidata solo se aplica durante sus
   muestras, y el valor anterior se restaura siempre, también si el banco falla. Se aprueba solo si la prueba exacta
   de signos sobre las diferencias da p < 0,05, el límite inferior del intervalo al 95 % (bootstrap de los pares) es
   > 0 y la mejora media es ≥ 0,05 (fase 1.3 de `PLAN_VAS.md`). Con 4 pares o menos es imposible aprobar (p ≥ 1/16).
   **A/A** del evaluador: `eolfi rsi aa --proveedor … [--simulada DESVIACION]`; la real queda en el registro como
   evento `aa`. Simulada con la desviación medida del banco (0,3), 400 repeticiones: 2,5 % de falsos positivos con
   5 pares, frente al 37,75 % de la regla anterior (media + 0,05 y peor muestra) con 3. **A/A real** (16/11, 14:01–17:14, V2
   `gemma_q4`, 5 pares): A 5/9, 5/9, 7/9, 1/9, 5/9; B 5/9, 7/9, 7/9, 5/9, 1/9; diferencia +0,04, intervalo
   [−0,22, +0,31], p = 0,5 → no aprueba, sin falso positivo. Es una sola corrida.
   **Juez dentro de `verify` y semilla** (`PLAN_DEFINITIVO.md`, B1 y B2): el banco crea el proyecto con
   `create --juez tools/rsi/criterios-tareas.json` (10 comprobaciones declaradas), así que `verify` prueba la app en
   Chrome, un proyecto que no funciona ya no sale en verde y cada ronda de reparación recibe qué comprobación falla.
   El modelo no puede escribir `eolfi.juez.json`. La semilla del par llega a la generación por `EOLFI_SEMILLA`
   (semilla y `temperature` 0 en los motores locales). Sin verde, la muestra puntúa 0 y se anota el mejor intento.
   **Corrida real** (16/11, V2 `gemma_q4`, dos muestras con la misma semilla): una abortó a los 23 min por una
   respuesta cortada por longitud; la otra sacó **9/9** en 11,7 min (primera nota máxima del banco). El juez funciona
   con el modelo; la semilla NO hace iguales dos corridas. Corregido después: un corte por longitud es una ronda
   fallida (se pide una respuesta más corta), no el fin del trabajo, y el banco anota por qué falló `create`.
   **NO VERIFICADO** en vivo tras esa corrección. **Causa del no determinismo:** la caché de prompt de
   llama-server. Medido con la misma petición, semilla 0 y temperatura 0: con la caché sale un texto en frío y otro
   en caliente; con `cache_prompt: false` sale idéntico en frío, en caliente y tras reiniciar (7 de 7). Con
   `EOLFI_SEMILLA`, Eolas V2 y llama.cpp ya envían `cache_prompt: false`. Eolas V1 (`/api/chat`) no: pendiente.
   **Más encargos** (`PLAN_DEFINITIVO.md`, B5): además de «tareas», «contador» y «filtro» en `tools/rsi/bancos/`,
   cada uno con `fuente/`, `encargo.txt`, `criterios.json` (los ve el proyecto) y `juez.json` (el evaluador, que el
   proyecto no ve y comprueba más casos). `--banco todos` reparte los encargos por semilla. Jueces validados con
   apps de referencia: la correcta saca la nota máxima y una página inerte, 1 de 8. **NO VERIFICADO** con un modelo.
   **Mejor intento** (B6): el bucle guarda la ronda con mejor nota del juez; si una ronda empeora, vuelve a
   esa versión y se lo dice al modelo; sin verde, conserva el mejor intento marcado como parcial (`ok` sigue
   en falso) y el banco lo puntúa con el evaluador en vez de dar 0. **NO VERIFICADO** con un modelo.
   Banco «tareas» (`eolfi/rsi_banco.py`):
   el encargo de la competición V1/V2, juzgado en Chrome por `tools/rsi/juez-tareas.mjs` (puntuación = comprobaciones
   superadas / totales; si la creación falla, 0).
4. **Decidir.** El titular aprueba (`eolfi rsi aprobar ID --por …`), que solo es posible con la evaluación aprobada,
   o rechaza. Al aplicar se guarda el valor anterior; `eolfi rsi revertir` lo restaura.

**Recursivo en dos niveles:** (a) el banco crece: cada fallo con síntomas y huella nueva queda en `casos.jsonl` como
caso de regresión; (b) el mejorador se ajusta a sí mismo: una regla con tres rechazos o reversiones y ninguna
adopción pide una repetición más antes de volver a proponer (hasta 10), y una adopción la devuelve a 2. Cada ajuste
queda como evento `meta`.

**Superficies (lo único que puede cambiar):** `eolas_v2.max_tokens` (1024–32768),
`eolas_v2.perfil.<perfil>.ctx` (2048–131072) y `.gpu_layers` (0–999), `eolas_v2.leccion.<perfil>.<categoría>`
(activa o no; solo lecciones que ya existen), y `rea.timeout`, el plazo de REA en la CLI (60–7200 s, en
`~/.eolfi/rsi/ajustes.json`). Reglas actuales: `salida_cortada_v2` (duplica `max_tokens`), `rea_plazo` (duplica el
plazo de REA) y `reactivar_leccion` (el motor sigue fallando por una causa cuya lección desactivó el titular).

**Dónde se observa:** `eolfi rea …`, `create --ai`, las herramientas REA del chat (`in_case` del servidor) y las
lecciones de la batería de código de V2. **Panel:** «Automejora (RSI)» en el chat lista las propuestas con su
evaluación; «Aprobar y aplicar» solo aparece si la evaluación mejora, «Revertir» si está aplicada, y una pendiente
muestra la orden `eolfi rsi evaluar` (la evaluación carga modelos y no se lanza desde el panel). API `/api/rsi`,
`/api/rsi/proponer` y `/api/rsi/propuestas/<id>/(aprobar|rechazar|revertir)`; un cliente vinculado (VS Code) no
puede decidir. En el chat, `eolfi_automejora` es solo lectura.

**Invariantes:** no toca código, autorizaciones de REA, rutas permitidas, AGENTS.md, el juez ni el banco; nada se
aplica sin evaluación aprobada y decisión del titular; registro en `~/.eolfi/rsi/registro.jsonl` encadenado por
SHA-256 (`eolfi rsi verificar` detecta cualquier edición, borrado o reordenación); `EOLFI_RSI=0` lo apaga.

**Verificado:** `tests/test_rsi.py` (16 pruebas, incluidas la regla de lecciones, la API del panel y la observación del chat) y la tarjeta
en `tests/e2e/panel.test.mjs` (Chrome real, axe sin problemas graves); antes, 13 pruebas: registro y manipulación, superficies cerradas, propuestas con
repetición, evaluación con restauración y margen, aprobación y reversión, ajuste del umbral, ganchos de la CLI y banco
con juez simulado). El juez funcional da 9/9 y 8/9 sobre los proyectos reales de V1 Q5 y V2 Q4 de la competición.
**Evaluación real (16/11/2026, titular: «haz la evaluacion R.S.I»):** aislada (registro propio y copia de
`eolas-v2.json` en el scratchpad; dos observaciones de salida cortada sembradas y marcadas para crear la propuesta),
banco «tareas» con Eolas V2 `gemma_q4`, 3 muestras por lado, 11:33–12:50 (unos 13 min por muestra). Propuesta
`eolas_v2.max_tokens` 8192 → 16384: base 7/9, 5/9, 1/4 (media 0,53); candidata 5/9, 1/4, 5/9 (0,45) → **suspendida**,
no aprobable; el valor se restauró (8192) y el registro verifica (10 eventos). Lecciones:
- El ruido del modelo domina (7/9 a 1/4 con la MISMA configuración): 3 muestras no bastan para cambios pequeños.
  Resuelto con el evaluador estadístico (punto 3).
- El juez contaba solo las comprobaciones ejecutadas (una página rota daba 1/4 = 0,25). Corregido: siempre sobre 9
  (`total` fijo y `ejecutadas` aparte). Con ese criterio la evaluación da 0,48 frente a 0,41: misma conclusión.
- La salida no se cortaba a 8192 tokens en esta tarea, así que duplicar `max_tokens` no podía ayudar: el RSI lo
  rechazó por evidencia, que es lo que debe hacer.

**Siguiente:** capas y contexto de V1 por petición como superficie (cuando se fusione la rama `eolas-plazo-local`),
reglas a partir del juez funcional y de las incógnitas de REA, y la evaluación en vivo cuando el titular reanude las
pruebas.

## Lo que se aprendió de REA al construir

- `verify_reconstruction` evalúa afirmaciones de tres tipos: `structural-artifact` (sale de `compare_artifacts`),
  `structural-function` (de `compare_functions` sobre `analyze_function`) y `behavioral` (de comparar capturas de
  procesos, que exigen EJECUTAR). Aprobar cubre solo lo declarado, no la equivalencia global.
- `compare_artifacts` no recibe rutas: recibe los inventarios que devuelve `inspect_artifact` de cada archivo abierto.
- `evaluate_reconstruction_coverage` exige once estructuras enlazadas (artefactos, superficies, propietarios,
  afirmaciones, contratos y resultados de verificadores, incógnitas residuales…). Se construirá cuando existan las
  afirmaciones de comportamiento.
- Con el mismo archivo a ambos lados, REA dice «unchanged» pero la verificación queda «unknown»: el inventario solo
  cubre los bytes raíz. «unknown» significa sin evidencia suficiente, nunca igualdad.

## Herramientas que faltan instalar

| Herramienta | Qué desbloquea | Licencia | Estado |
|---|---|---|---|
| WABT 1.0.42 | Análisis completo de WASM (`inspect_wasm_artifact`, `compare_wasm_interfaces`) | Libre | Instalado el 14/11/2026 (ver «Módulos WebAssembly») |
| Npcap | Captura de red en vivo (ahora solo se leen capturas) | Libre | Pendiente; instala un controlador de sistema |
| sigrok | Grabaciones de señales | Libre | Pendiente |
| Cutter | Interfaz visual de rizin | Libre | Pendiente |
| JEB, IDA | Descompiladores alternativos | Comerciales | Solo si el titular lo decide |

## Módulos WebAssembly (14/11/2026)

WABT 1.0.42 descargado con permiso del titular («descarga wabt») de la publicación oficial
(github.com/WebAssembly/wabt, release 1.0.42 del 15/09/2026), con el SHA-256 igual al publicado: Windows x64
(`62f1eb2b…8c88`) en `~/.eolfi/tools/wabt-1.0.42` y Linux x64 (`84895407…b131`) en `~/.local/eolfi-rea/wabt-1.0.42`
de Ubuntu. Instaladores con el hash fijo: `tools/instalar-wabt.ps1` y `tools/instalar-wabt-wsl.sh` (probados también
descargando en una carpeta temporal). REA exige la versión exacta y la carpeta `bin` en `REA_WABT_BIN_DIRECTORY`, con
`wasm-validate`, `wasm-objdump` y `wasm2wat`; `rea_env` la pasa sola si está instalado.

`eolfi rea wasm <módulo> [--frente <otra versión>]` (y `eolfi_modulo_wasm` en el chat): validez, secciones,
importaciones y exportaciones; con `--frente`, `compare_wasm_interfaces` (añadidas, quitadas y cambiadas, con su firma
legible). Siempre pide el resumen (`detail: summary`): la respuesta completa lleva el WAT entero y no cabe en la
respuesta de REA. Cada orden de WABT tiene 120 s en vez de los 30 s de REA.

En vivo (REA de Windows): `webp_codec.wasm` de Playwright (SHA-256 `164cd958…4b79`) «valid», 11 secciones, 5
importaciones y 8 exportaciones, igual que `wasm-objdump -h` y `wasm-validate` a mano. Comparación de dos módulos
propios compilados con `wat2wasm`: añadidas `multiplicar` y la importación `env.now`, quitada `restar`, `sumar`
cambiada de `(i32, i32) -> i32` a `(i64, i64) -> i64`, y `memory` y `env.log` sin cambios: exactamente lo escrito.

Con `--js <cargador>` (repetible; `js` en el chat, con las rutas comprobadas como las demás) REA busca en ese
JavaScript, sin ejecutarlo, los literales que nombran un .wasm y dice cómo se asocian: «la ruta apunta a este
archivo», «solo coincide el nombre» o «sin archivo local». En vivo con `evmole` (dependencia del propio REA): módulo
«valid», 30 importaciones y 21 exportaciones (igual que `wasm-objdump -h`); en `evmole_node.mjs` el literal
`../dist/evmole_bg.wasm`, línea 4, columna 21, «solo coincide el nombre» (la copia no está en `../dist`). Es una
asociación estática: no prueba que el módulo se cargue.

Límite de REA, sin solución en esta versión: si la salida de WABT pasa de 32 MiB (fijo), el análisis falla. Le pasa a
`tree-sitter-javascript.wasm` (~650 KB): Eolfi lo dice en vez de mostrar el error de REA. NO VERIFICADO: el REA de WSL
con WABT (instalado, pero sin conectar en `wsl_rea_command`, que cambia en la PR #22) y módulos con nombres de
depuración.

## Registros de REA en los agentes

Actualizados: Codex y VS Code. Cursor: restaurado a su estado anterior a petición del titular. Sin tocar: GitHub
Copilot CLI y Grok Build. Claude Code: lo actualiza el titular (`rea setup --client claude_code --yes`). Claude
Desktop: REA no reconoce la identidad del paquete instalado.

## Grafo de llamadas (14/11/2026)

`grafo_llamadas` (`eolfi rea llamadas <binario> <función> [--atras] [--profundidad N] [--max-nodos N]`) completa las
«llamadas» del punto 8: resuelve la función por nombre o dirección (`list_procedures`), pide `get_call_graph` hacia
delante o hacia atrás, lo recorta por niveles y nodos (dice cuántos omite), pone nombres a las direcciones, agrupa las
APIs externas por DLL (también los «thunks» `DLL::función`) y da un Mermaid `graph LR` con las etiquetas saneadas. En
vivo con `whoami.exe` (SHA-256 `23240ef9…6cd3`): desde `entry`, 238 nodos en REA; a dos niveles, KERNEL32 (`Sleep`,
`GetTickCount`…) y MSVCRT (`exit`, `_cexit`, `_initterm`, `_amsg_exit`); hacia atrás, `Sleep` ← `FUN_140001af0` ←
`entry`. Límite: solo llamadas resueltas por Ghidra; las indirectas o calculadas no aparecen.

## Código gestionado .NET (14/11/2026)

Punto 9, primera parte: `eolfi rea dotnet <ensamblado>` (compuesto `ensamblado_dotnet`, REA de WSL2 porque las herramientas gestionadas solo aceptan rutas POSIX). Resume sin cargar ni ejecutar el ensamblado: identidad (nombre, versión, token de clave pública, MVID), cabecera CLI (solo IL, nombre seguro, ReadyToRun, modo mixto), referencias, recursos, tipos con su número de métodos, cadenas literales (`ldstr`) y la frontera nativa (módulos, declaraciones P/Invoke e implementaciones nativas). Cada lista está acotada por `--limite` y lleva el total que declara REA.

Verificado en vivo con dos ensamblados del Framework 4 de Windows copiados al área temporal: `InstallUtil.exe` (cobertura completa: 8 tipos, 7 cadenas, sin P/Invoke) y `System.Data.dll` (modo mixto, 158 P/Invoke, 319 implementaciones nativas). En `System.Data.dll` REA corta los miembros por su presupuesto fijo de 64 MiB por inspección (`dist/dotnet/ManagedDecodeBudget.js`, sin ajuste ni variable `REA_*`). El compuesto no modifica REA: particiona con `type_names` en lotes adaptativos (150 tipos, partidos por la mitad si se pasan; `<Module>` va solo), suma los recuentos por tipo sin duplicar y une las cadenas por token. Así recupera 14.072 métodos, 9.096 campos, 64.372 aristas y 3.865 cadenas en 9 inspecciones, y los totales cuadran con la tabla de tipos. `cobertura_miembros` indica la partición, los lotes parciales y los tipos que no cupieran ni solos. REA marcaba `<Module>` como «partial» sin motivo. Al revisar sus 101 métodos, 31 son código nativo de C++/CLI («CIL decoding is unavailable for native…») y 2 son P/Invoke sin cuerpo (RVA 0). Un lote parcial solo por eso cuenta como completo y lo anota en `metodos_sin_cil`; cualquier otro cuerpo que falte lo deja parcial. Con eso, `System.Data.dll` sale «complete». `--salida <nuevo.json>` vuelca todos los tipos, métodos, cadenas y P/Invoke. Decisiones y evidencia: `D:\Alejandria\docs\REA-DOTNET-PARTICION-2026-11-14.md`.

NO VERIFICADO: proyectos .NET Core/5+ con `TargetFramework` (la lista `marcos_objetivo` salió vacía en ambos), ensamblados ReadyToRun y ofuscados. Siguen pendientes Unity IL2CPP, Flutter/Dart y Apple.

## Clases y métodos Android con JADX (14/11/2026)

Punto 9, parte JADX: `eolfi rea clase <apk> <consulta> [--metodo M] [--sobrecarga N]` (compuesto `clase_android`; REA de Windows, que tiene JADX configurado). Funciona sin instalar ni ejecutar la app:
- Si la consulta coincide con varias clases, las lista.
- Si coincide con una sola, o una coincide exacta, da sus métodos (firma y prototipo DEX), campos (tipo y valor estático) y clases internas.
- Con `--metodo`, descompila ese método e indica si REA recurrió a smali, sus marcas y si la fuente salió recortada (12.000 caracteres).
- Si el método tiene varias sobrecargas, las lista y pide `--sobrecarga`.

Verificado en vivo con ApiDemos 6.0.18 (SHA-256 `6e5eacf5…ff75`, 2.876 clases, JADX headless 0.7.1), unos 10 s por llamada, en cinco casos: varias coincidencias, clase única, `onCreate` de `ReversingAnimation`, `getData` de `ApiDemos` y una consulta sin resultados.

NO VERIFICADO: APK ofuscados (R8/ProGuard), métodos que fallan en JADX y caen a smali, y paquetes .aab/.xapk.

## Apps Flutter/Dart (14/11/2026)

Punto 9, parte Flutter: `eolfi rea flutter <apk> [--abi A]` (compuesto `app_flutter`, REA de Windows). Funciona sin instalar ni ejecutar la app.
- Por cada ABI da `libapp.so` (Dart AOT) con su hash de snapshot, y `libflutter.so` (el motor) con su build-id y toolchain.
- Del snapshot de una ABI da sus secciones, los paquetes Dart agrupados desde las URI `package:` y las librerías del SDK (`dart:`). Los nombres mal formados que dejan los patrones de bytes se filtran.

Verificado en vivo con Flutter Gallery 2.9.2 (APK oficial de `flutter-team-archive/gallery`, 117.817.550 bytes, SHA-256 `659b5fc6…0e29`; la release no publica hash y el tamaño coincide con el de GitHub). Resultado:
- 3 ABI con el mismo hash de snapshot `65817c30…`.
- Snapshot de tipo 3 (Dart 2.14 FullAOT).
- 201 URI `dart:`.

Límite de REA: devuelve 500 de al menos 756 URI `package:`, aparentemente por orden alfabético. Por eso faltan paquetes del final, entre ellos el de la propia app, y el resultado lo marca con `paquetes_incompletos`.

NO VERIFICADO: snapshots unificados (`_kDartSnapshotData`/`_kDartSnapshotText`), que REA no admite, la versión del SDK a partir del hash (necesita una tabla externa) y la recuperación de clases y funciones (necesita un analizador por versión del SDK).

## Apps de Apple (14/11/2026)

Punto 9, parte Apple: `eolfi rea apple <.app|.zip|.ipa|.dmg>` (compuesto `mapa_app_apple`, REA de Windows). Funciona sin ejecutar la app.
- **REA** (inventario + `project_apple_application_graph`) da los bundles con su papel según la ruta (app, framework, app anidada, servicio XPC, ayudante privilegiado), los ejecutables Mach-O con su hash, las firmas presentes, los plists de launchd, las familias de ejecución y los puentes.
- **Eolfi** lee con `plistlib` el Info.plist de cada bundle directamente del .zip/.ipa o de la carpeta .app, sin extraer nada. Da identificador, versión, sistema mínimo, permisos de privacidad (`NS…UsageDescription`), esquemas URL, excepciones de transporte (ATS) y canal de actualizaciones (Sparkle). REA solo parsea plist y Mach-O en macOS: lo dice el propio error, «Native macOS utilities require macOS».

Verificado en vivo con Maccy 2.8.0 (`Maccy.app.zip` de la release oficial `p0deje/Maccy`, SHA-256 `e684e1ce…27e0`, igual al publicado). Resultado:
- 8 bundles: la app, Sparkle 2.10.0 con su `Updater.app`, 2 servicios XPC y 3 de recursos.
- 6 ejecutables Mach-O universales.
- macOS mínimo 14.0, sin icono en el Dock y feed de actualizaciones en GitHub.

NO VERIFICADO:
- `.ipa` y `.dmg` (en un `.dmg` el Info.plist no se lee: necesita montarse).
- La validez de las firmas (solo se ve que existen).
- Los tipos Swift y el detalle Mach-O: necesitan macOS, o Ghidra sobre el ejecutable extraído.

## Devicetree (14/11/2026)

Punto 10, parte devicetree: `eolfi rea devicetree <.dtb> [--filtro texto]` (compuesto `devicetree_hw`, REA de Windows). Es análisis puro del archivo, sin herramientas externas. Primero comprueba la cabecera FDT; después REA da el árbol completo y Eolfi resume:
- la placa (modelo, compatible, bootargs y consola), los alias, las CPU y la memoria;
- la memoria reservada y los dispositivos (nodos con `compatible`) con dirección y estado activo/desactivado;
- el recuento por fabricante y las referencias resueltas.

REA no decodifica algunas cadenas, como `device_type`; Eolfi las saca del hex cuando son texto imprimible terminado en NUL.

Verificado en vivo con `bcm2711-rpi-4-b.dtb`: 56.431 bytes, SHA-256 `9b572c00…d8fb`, descargado de `raspberrypi/firmware` (rama `master`) con el hash de blob de git igual al del repositorio. Resultado:
- Raspberry Pi 4 Model B, FDT v17, 325 nodos y 1.753 propiedades.
- 4 Cortex-A72.
- 119 dispositivos: 63 activos y 56 desactivados.
- La memoria va a 0, porque la fija el cargador al arrancar, y el resultado lo indica.

NO VERIFICADO: overlays (`.dtbo`), devicetrees dentro de una imagen de firmware (hace falta extraerlos; `extract_firmware` necesita Unblob, que no está instalado) y referencias específicas de cada binding.

## Extracción de firmware con Unblob (14/11/2026)

Punto 10, extracción: `eolfi rea firmware <imagen> --extraer <carpeta nueva> [--profundidad N]` (compuesto `extraer_firmware`, REA de WSL con Unblob 26.6.4). No monta nada ni ejecuta lo extraído: REA publica solo archivos regulares, sin permiso de ejecución.

Instalación: `tools/instalar-unblob-wsl.sh` (autorizada por el titular), en el espacio del usuario y sin sudo.
- Entorno virtual con `unblob==26.6.4` de PyPI.
- Extractores sacados de los paquetes oficiales de Ubuntu con `apt-get download` + `dpkg -x`, sin instalarlos en el sistema, con las librerías que les faltan.
- `sasquatch` del .deb de onekey-sec, verificado con el SHA-256 publicado.
- Un lanzador, `eolfi-unblob`, que pone todo eso en PATH/LD_LIBRARY_PATH. `rea_client` lo pasa en `REA_UNBLOB_COMMAND`.

Con todo ello Unblob ve sus 15 extractores. Se corrigió el `/usr/bin/7z` de Ubuntu, que llamaba por ruta absoluta a `/usr/lib/7zip/7z`.

Unblob exige ser dueño del destino, y en `/mnt` (los discos de Windows) no puede: REA responde «Could not establish owner access to output directory». Con un destino de Windows, Eolfi:
1. extrae en `~/.local/eolfi-rea/salidas` de Ubuntu;
2. lo copia al destino;
3. borra esa carpeta temporal solo si la copia sale bien. Si falla, la conserva y lo indica en `copia_a_windows`.

Además, `revisar_rootfs` lee del sistema de archivos extraído la distribución, las cuentas (con shell, UID 0 y contraseña vacía en shadow, sin mostrar hashes), los servicios de `/etc/init.d`, la arquitectura de los ELF y las rutas de claves privadas (sin su contenido).

Verificado en vivo con OpenWrt 25.12.6 para TP-Link Archer C7 v2 (`openwrt-25.12.6-ath79-generic-tplink_archer-c7-v2-squashfs-sysupgrade.bin`, 7.405.859 bytes, SHA-256 `fb5b9e9c…34ce`, igual al de `sha256sums` de downloads.openwrt.org). En 164 s:
- **Extraído:** 1.193 archivos y 32 MB, entre ellos el núcleo LZMA (18 MB) y el squashfs (1.185 archivos).
- **Binarios:** 162 ELF, todos MIPS de 32 bits BE.
- **No extraído:** 214 enlaces simbólicos no publicados, 5 trozos sin manejador y una rama cortada por profundidad.
- **Copia a Windows:** correcta.
- **Revisión del rootfs:** OpenWrt r33311 `ath79/generic`; root con la contraseña vacía en la imagen, como es habitual en OpenWrt; 24 servicios (`dropbear`, `uhttpd`, `dnsmasq`…); ninguna clave privada.

NO VERIFICADO:
- Imágenes cifradas.
- UBI, JFFS2 o EROFS reales (los extractores están, pero sin muestra).
- Nombres que NTFS no admite al copiar.
- El análisis de los ELF extraídos con Ghidra.

Exposición de red en OpenWrt: `revisar_rootfs` lee la configuración UCI de la imagen (`/etc/config`):
- `uhttpd`: direcciones de escucha HTTP/HTTPS y redirección a HTTPS;
- `dropbear`: puerto, interfaz y si admite contraseña o root con contraseña;
- `firewall`: política de entrada, zonas con NAT, reglas y redirecciones;
- `network` y `wireless`: interfaces, SSID y cifrado.

Los valores secretos (`key`, `password`, `psk`, `*_key`…) salen como `<oculto>`. En la imagen de OpenWrt 25.12.6:
- web en `0.0.0.0:80/443` y `[::]:80/443` sin redirección a HTTPS;
- SSH en el 22 con contraseña y root con contraseña;
- WAN con entrada REJECT y NAT, LAN con ACCEPT, 9 reglas;
- `network` y `wireless` no vienen en la imagen: los generan `/etc/board.d` y `uci-defaults` al arrancar, y el resultado lo indica en `generada_al_arrancar`.

Los fallos de extractor ya dicen su tipo: en esta imagen, 7 entradas duplicadas en el `.tar` de scripts de paquetes, que Unblob resolvió quedándose con la más reciente.

## Tipos Swift de apps de Apple (14/11/2026)

`eolfi rea swift <.app|.zip|.ipa|Mach-O> [--arquitectura A]` (compuesta `tipos_swift_apple`). No necesita macOS.
- **Eolfi** saca el ejecutable principal (`CFBundleExecutable` del Info.plist), lee las arquitecturas de la cabecera universal y separa la porción elegida (arm64 por defecto) en un temporal que borra al acabar.
- **REA con Ghidra en WSL**: el Ghidra del REA de Windows solo abre PE, así que se usa el REA de WSL con la misma instalación de Ghidra 12.1.4 vista desde `/mnt` (trae el descompilador de Linux) y Java 21 en el espacio del usuario (`tools/instalar-java-wsl.sh`, sin sudo). `wsl_rea_ghidra_command` comprueba Java, `analyzeHeadless` y el descompilador.
- Pide `analyze_swift_types`, `get_objc_classes` y las secciones de `binary_overview`. REA devuelve nombres de procedimientos, no tipos: Eolfi lee el contexto nominal del mangling (moderno `$s…` y antiguo `_TtC…`) y agrupa por módulo y tipo. La sección decide el origen: `__text` es código del ejecutable (la app y los paquetes enlazados estáticamente) y `__stubs`, llamadas a frameworks del sistema; los protocolos de otros módulos en `__text` son conformidades de la app.
- **swift-demangle de Linux** (Swift 6.4.2 oficial en WSL, `tools/instalar-swift-demangle-wsl.sh` con verificación GPG; `rea_client.wsl_swift_demangle`): `eolfi rea swift` le pasa los nombres que el lector de Eolfi no entiende y devuelve `sin_resolver_descifrados` (cuántos, por módulo y una muestra). El `demangle_swift` de REA sigue necesitando macOS.
- Frameworks del sistema: un módulo al que se llama por `__stubs` (SwiftUI, Foundation, Combine…), la biblioteca estándar, lo importado de Objective-C y los overlays de C (Darwin, `os`…) no cuentan como paquetes incluidos aunque tengan especializaciones genéricas en `__text`; sus protocolos siguen como implementados.
- Plazo, memoria y respuesta de Ghidra en la orden de WSL: `REA_GHIDRA_STARTUP_TIMEOUT_MS` a 60 min, `GHIDRA_MAXMEM` a 6 GB y `REA_MCP_MAX_RESPONSE_BYTES` a 64 MiB. Con los valores de REA (330 s, 2 GB, 10 MiB) no se analiza el ejecutable de 21,7 MB de Feather.

Verificado en vivo con Maccy 2.8.0 (porción arm64, SHA-256 `d2fa9a71…dfef`), unos 4 minutos:
- tipos de la app: `About`, `AppDelegate`, `Clipboard`, `LargeTextView.Coordinator` y `LargeTextView.EditorState` (los que ve Objective-C: el binario no lleva símbolos y el resto de su código no tiene nombre);
- paquetes incluidos: Settings (5 tipos), KeyboardShortcuts, Defaults y Sauce;
- protocolos implementados: 8 de SwiftUI (`View`, `PreferenceKey`, `NSViewRepresentable`…) y `PersistentlyIdentifiable` de AppIntents;
- frameworks Swift usados: SwiftUI (139 tipos), Foundation, AppIntents, SwiftData y Combine; clases Objective-C importadas de AppKit, Foundation, Vision, UserNotifications, Sparkle…;
- 1065 nombres Swift: 1028 con tipo, 37 globales (funciones y variables de módulo) y 0 sin resolver; Eolfi decodifica sustituciones estándar (`SS`, `Sc…`), módulos `s`/`So`, palabras comprimidas (`0A…`), extensiones y nombres privados (`P33_…`), con lo que salen también `DragSourceView` y `MouseMovedViewModifier.Coordinator`.

Verificado en vivo con dos releases oficiales más:
- SwiftFormat 0.64.7 (`swiftformat.zip`, Mach-O universal suelto, SHA-256 `e82e2243…4038`), porción arm64: 1351 nombres Swift, 0 sin resolver, módulo `SwiftFormat` con 77 tipos (49 enumeraciones, 8 estructuras, 2 clases…).
- Feather 2.9.0 (`Feather.ipa`, SHA-256 `833c57d3…30ea`; ejecutable arm64 de 21,7 MB), unos 24 min con 6 GB: 115.035 procedimientos y 17.202 nombres Swift (305 globales, 22 sin resolver que `swift-demangle` descifra todos: Builtin y Swift). Módulo `Feather` con 13 tipos (`AppDelegate`, `DownloadManager`, `SigningHandler`, `CertificateReader`…), 49 paquetes incluidos (NIOCore, Vapor, NIOHTTP2, Nuke, SWCompression, ZsignSwift…), 60 protocolos implementados y frameworks usados: Swift, SwiftUI (212 tipos), Foundation, Network, Combine, CryptoKit…

NO VERIFICADO:
- `demangle_swift`, `list_architectures` e `inspect_macho` de REA: necesitan macOS (comprobado: REA los rechaza en WSL con «Native macOS utilities require macOS»).
- Nombres en punycode y la firma completa de cada función (solo se lee el contexto del tipo).
- Apps con símbolos completos (con ellas saldrían muchos más tipos propios).
