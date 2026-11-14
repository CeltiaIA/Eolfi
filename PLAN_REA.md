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

**Pendiente de verificar en vivo:** `comparar` (necesita dos versiones de un mismo programa) y la verificación de
comportamiento (requiere aprobar la ejecución en los dos lados).

## Lo que crearemos, por orden

| # | Pieza | Qué combina | Qué da | Estado |
|---|---|---|---|---|
| 1 | **Cobertura de reconstrucción** | `build_reconstruction_obligation_ledger`, `evaluate_reconstruction_coverage`, `verify_reconstruction` | Qué parte del original cubre el proyecto que generó Eolfi y qué falta, con evidencias (fase 4) | Estructural hecha (con el punto 3). Comportamiento hecho: `verificar_comportamiento` ejecuta original y reconstrucción con el mismo escenario (`capture_process_scenario`), compara (`compare_process_captures`) y verifica afirmaciones `behavioral` (overall, terminal, exit), siempre con permiso del titular. Falta: probarlo en vivo (requiere tu aprobación en el chat) y el libro de obligaciones completo (`evaluate_reconstruction_coverage`) |
| 2 | **Autorización por caso en el chat** (hecho) | Petición del modelo y decisión del titular («una vez», «en este caso», «rechazar»), con registro y revocación | Habilita el análisis dinámico (Frida, gdb, capturas, `observe_*`) solo con permiso expreso | Hecho; falta probarlo en vivo con un modelo |
| 3 | **Diferencias entre versiones** (hecho) | `compare_artifacts`, `compare_functions`, `find_changed_behavior`, `compare_application_versions`, `compare_wasm_interfaces` | Informe «qué cambió entre A y B» | Pendiente |
| 4 | **Inventario de dependencias** (hecho) | `inspect_pe_imports`, `inspect_native_exports`, `inspect_go_binary`, `inspect_rust_binary`, `inspect_pe_certificates` | Librerías, versiones, firmas y certificados | Pendiente |
| 5 | **Apps JavaScript, Electron y web** (hecho, con recuperación de fuentes vía REA en WSL2) | `analyze_javascript_application`, `recover_javascript_sources`, `trace_javascript_semantics`, `compare_source_to_bundle` | Fuentes recuperadas y trazadas: base para regenerar la app | Pendiente |
| 6 | **Evidencias e incógnitas compartidas** (hecho, salvo exportar el paquete completo de REA) | `export_evidence_bundle`, `import_evidence_bundle`, `record_unknown`, `update_unknown` | Un mismo caso de Eolfi con lo analizado en VS Code, en el chat o por Claude | Pendiente |
| 7 | **De captura de red a API** | `inspect_pcap_capture`, `inspect_packet_fields` y Eolas | Especificación de API (estilo OpenAPI) y un cliente generado por Eolfi | Pendiente |
| 8 | **Mapa de la app en el panel** | `project_android_application_graph`, `get_call_graph`, `build_call_path` | Grafo visual: pantallas, clases y llamadas | Pendiente |
| 9 | **Móvil y código gestionado** | JADX, .NET, Unity IL2CPP, Flutter/Dart, Apple (Mach-O, plist, Swift) | Análisis por plataforma | Pendiente |
| 10 | **Firmware** | `extract_firmware`, `inspect_firmware_regions`, `inspect_devicetree` | Desglose de una imagen de firmware | Pendiente |
| 11 | **Entorno de agente de una web** | `export_environment_bundle` (AgentEnv) | Paquete para que un agente trabaje sobre una web capturada | Pendiente |

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
