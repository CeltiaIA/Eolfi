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
  distribuye y si llama al original) y la frontera exige la prueba de independencia, que Eolfi aún no genera: no
  puede salir «ready». En vivo con `whoami.exe`: «failed» (el verificador de REA falla) con 5 razones y sus
  siguientes pruebas.

## Lo que crearemos, por orden

| # | Pieza | Qué combina | Qué da | Estado |
|---|---|---|---|---|
| 1 | **Cobertura de reconstrucción** | `build_reconstruction_obligation_ledger`, `evaluate_reconstruction_coverage`, `verify_reconstruction` | Qué parte del original cubre el proyecto que generó Eolfi y qué falta, con evidencias (fase 4) | Estructural hecha (con el punto 3). Comportamiento hecho: `verificar_comportamiento` ejecuta original y reconstrucción con el mismo escenario (`capture_process_scenario`), compara (`compare_process_captures`) y verifica afirmaciones `behavioral` (overall, terminal, exit), siempre con permiso del titular. Probado en vivo el 14/11 (ver arriba), también con programas de Windows vía el REA de WSL. Libro de obligaciones hecho (`build_reconstruction_obligation_ledger`, con propietario), limitado a «implemented» por REA. Cobertura por frontera hecha (`evaluate_reconstruction_coverage`). Falta: la prueba de independencia (que la reconstrucción no llama al original) |
| 2 | **Autorización por caso en el chat** (hecho) | Petición del modelo y decisión del titular («una vez», «en este caso», «rechazar»), con registro y revocación | Habilita el análisis dinámico (Frida, gdb, capturas, `observe_*`) solo con permiso expreso | Hecho; falta probarlo en vivo con un modelo |
| 3 | **Diferencias entre versiones** (hecho) | `compare_artifacts`, `compare_functions`, `find_changed_behavior`, `compare_application_versions`, `compare_wasm_interfaces` | Informe «qué cambió entre A y B» | Hecho (ver «Hecho») |
| 4 | **Inventario de dependencias** (hecho) | `inspect_pe_imports`, `inspect_native_exports`, `inspect_go_binary`, `inspect_rust_binary`, `inspect_pe_certificates` | Librerías, versiones, firmas y certificados | Hecho (ver «Hecho») |
| 5 | **Apps JavaScript, Electron y web** (hecho, con recuperación de fuentes vía REA en WSL2) | `analyze_javascript_application`, `recover_javascript_sources`, `trace_javascript_semantics`, `compare_source_to_bundle` | Fuentes recuperadas y trazadas: base para regenerar la app | Hecho (ver «Hecho») |
| 6 | **Evidencias e incógnitas compartidas** (hecho, salvo exportar el paquete completo de REA) | `export_evidence_bundle`, `import_evidence_bundle`, `record_unknown`, `update_unknown` | Un mismo caso de Eolfi con lo analizado en VS Code, en el chat o por Claude | Hecho, salvo exportar el paquete completo de REA |
| 7 | **De captura de red a API** | `inspect_pcap_capture`, `inspect_packet_fields` y Eolas | Especificación de API (estilo OpenAPI) y un cliente generado por Eolfi | Hecho: `eolfi rea api`, `eolfi_api_desde_captura` (OpenAPI completo si hay tshark en WSL) |
| 8 | **Mapa de la app en el panel** | `project_android_application_graph`, `get_call_graph`, `build_call_path` | Grafo visual: pantallas, clases y llamadas | Pendiente |
| 9 | **Móvil y código gestionado** | JADX, .NET, Unity IL2CPP, Flutter/Dart, Apple (Mach-O, plist, Swift) | Análisis por plataforma | Pendiente |
| 10 | **Firmware** | `extract_firmware`, `inspect_firmware_regions`, `inspect_devicetree` | Desglose de una imagen de firmware | Pendiente |
| 11 | **Entorno de agente de una web** | `export_environment_bundle` (AgentEnv) | Paquete para que un agente trabaje sobre una web capturada | Pendiente |
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
   **NO VERIFICADO** en vivo tras esa corrección. Banco «tareas» (`eolfi/rsi_banco.py`):
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
| WABT 1.0.42 | Análisis completo de WASM (`inspect_wasm_artifact`, `compare_wasm_interfaces`) | Libre | Pendiente |
| Npcap | Captura de red en vivo (ahora solo se leen capturas) | Libre | Pendiente; instala un controlador de sistema |
| sigrok | Grabaciones de señales | Libre | Pendiente |
| Cutter | Interfaz visual de rizin | Libre | Pendiente |
| JEB, IDA | Descompiladores alternativos | Comerciales | Solo si el titular lo decide |

## Registros de REA en los agentes

Actualizados: Codex y VS Code. Cursor: restaurado a su estado anterior a petición del titular. Sin tocar: GitHub
Copilot CLI y Grok Build. Claude Code: lo actualiza el titular (`rea setup --client claude_code --yes`). Claude
Desktop: REA no reconoce la identidad del paquete instalado.
