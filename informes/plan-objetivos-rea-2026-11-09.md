# Plan de objetivos a partir del análisis REA — 2026-11-09

> Plan de trabajo, no informe de cierre. Ningún objetivo de este documento está implementado. Las cifras de «hallazgos» de REA son observaciones estáticas, **no** defectos; los defectos que aquí se proponen se apoyan en la lectura del código fuente señalado y quedan pendientes de reproducir con una prueba.

## 1. Estado de partida comprobado

- Repositorio `D:\Eolfi`, rama `avance-fases-2-3`, HEAD `5e05056`. `git status --short` vacío: los cambios que el traspaso del 08/11 describía como «sin confirmar» (observe, vscode-bridge, pruebas, informes) ya están en los commits `ece54d0` y `3aefa33`. La rama está al día con `origin/avance-fases-2-3` (`git log origin/avance-fases-2-3..HEAD` vacío); el brief que hablaba de «5 commits por delante» se había quedado antiguo.
- Remoto `CeltiaIA/Eolfi`: `gh run list` muestra la CI `success` en los dos últimos push de esta rama (runs 42535914183 y 42535654068, 08/11). Es decir, la CI ya funciona en el repositorio nuevo.
- Contexto leído: `AGENTS.md`, `PLAN_INGENIERIA_INVERSA_EOLFI.md`, `REGISTRO_LIMPIEZA.md`, [auditoría REA vscode-bridge](auditoria-rea-vscode-bridge-2026-11-08.md), [avance UI desktop](avance-ui-desktop-2026-11-08.md), [traspaso](traspaso-objetivo-eolfi-2026-11-08.md). Casillas abiertas de la hoja de ruta: Fase 2 (UI desktop/móvil), Fase 4 (mejoras con razón verificable / generación más allá de la CLI observada) y Fase 7 (guías por flujo y retirada de opciones).

## 2. Análisis REA ejecutados en esta sesión

REA es el servidor MCP `rea`. Todos los análisis fueron **estáticos**: no se ejecutó ningún objetivo. Plataforma: Windows 11 Pro (10.0.26300), x86-64.

| # | Objetivo | Herramienta / proveedor | SHA-256 del objetivo | Alcance y cobertura | Evidencia |
|---|---|---|---|---|---|
| R1 | `eolfi/vscode-bridge` (directorio) | `analyze_javascript_application`, analizador JS de REA v1, vista `rea-analysis-view` v1 | `f26ee654313cd467a4740e5c35684171c6bbcd08511537031fd0ffbf3d1d2c68` | 42 archivos relevantes, 41/41 JS parseados, 69.062 nodos AST, 0 fallos de parseo. Grafo de aplicación `partial`, semántica `unknown`, 13 fuentes con semántica desconocida, **16.474 incógnitas semánticas** (sin truncar). 617 observaciones. | padre `ev_63b1f70e0bf9be2f679f05934375185443a8dbe4742c954bd4e44b6cca24bb6b`, resumen `ev_2f1b9772974185ca8e2dd25e183eef9c9f6349a8350032d8ab916c7b23209870` |
| R2 | `eolfi/bridge` completo (incluye `node_modules/electron`) | ídem | `06ac3037f5a22d379c81e4b914200477f80381e00e9b414542c84876b1cc8501` | 431 archivos, 391 JS (379 completos, 12 recuperados), 381.705 nodos AST. Semántica `partial` y **truncada** en `max_semantic_nodes=100000`; 40.320 incógnitas semánticas, 1 de aplicación; un script en línea de `default_app.asar/index.html` sin analizar. 5.021 observaciones, casi todas de dependencias. | padre `ev_cacb7202f39533940bdbe957ebe7b3e767d135d9f4200255d9b2fede4c84714d`, resumen `ev_2d86e0acd61c2a3c0d6baf8766e2b40a84b03e7473354e327bcebdde0c5b679c` |
| R3 | `eolfi/bridge`, fuentes propias (`main.mjs`, `server.mjs`, `approval.mjs`, `engine/chrome.mjs`, `adapters/*.mjs`, `sites.json`, `package.json`) | ídem con `source_paths` | ídem R2 | 9 JS completos, 13.972 nodos AST, 0 fallos. 420 archivos fuera de la selección, explícitamente. 8.106 incógnitas semánticas, 411 de aplicación (en su mayoría, la parte no seleccionada). 152 observaciones. 1 `BrowserWindow` (`main.mjs:80-83`) con `webPreferences` explícitas y 1 observación de validación de remitente. | padre `ev_721c80709dcb11ce948770c8d62bbde3e3263d0f26de129be0af9cd6476ff167`, resumen `ev_80ff3abb4aed20749887ed5902e4207e61078d8156c3bb25577ccacc4a7a13fc`, hechos de `main.mjs` `ev_dc7715b5923d18c9b68659068c1542a26e88dc9b97445d276d74806484265eb0` |
| R4 | `eolfi/observe/browser_driver.mjs` | ídem con `source_paths` | carpeta `eolfi/observe`: `6900c44e6b506551f812d9c450f8a51b644eaf15750266353906baf0ff005b91` | 1 JS, 1.517 nodos AST, 0 fallos; semántica `unknown`, 457 incógnitas. 11 observaciones. | padre `ev_cf35b63bb62aa63a85b9494db4bfc5fe6d9b2bc11858659f684a19242a024c65`, resumen `ev_ced3ab71a6ea6061697d22be896d66beffd7c73b7e1ea0e552a6b11f25763145` |
| R5 | `eolfi/bridge/node_modules/electron/dist/electron.exe` (Electron 45.2.2, PE x86-64, 249.469.440 bytes) | `inspect_electron_fuses`, REA Electron fuse reader v1 | `f59256ea0a26a2ea6f5ab266e34ba8a58c89045c5a4e285b3a9ff26e2896e50d` | Centinela completo (9 fusibles). Habilitados: `RunAsNode`, `EnableNodeOptionsEnvironmentVariable`, `EnableNodeCliInspectArguments`, `GrantFileProtocolExtraPrivileges`, `WasmTrapHandlers`. Deshabilitados: `EnableCookieEncryption`, `EnableEmbeddedAsarIntegrityValidation`, `OnlyLoadAppFromAsar`, `LoadBrowserProcessSpecificV8Snapshot`. | `ev_3eb7ff3600636adc84ef494b5013edd2201b061a62040641051388bab76ffbc1` |
| R6 | `eolfi.db` + `eolfi.db-wal` (SQLite local, ignorado por Git) | `inspect_sqlite_database`, SQLite 3.53.4; solo esquema, sin filas | db `6bd0d097acda83b1a6665f6d75d0b9a80486b2a61c491956fd174164ef578bd8`, WAL `1692776abb4249ab35a7a195fb44db0c307f491d8a4f727c3a7d3a821613e7c7` | Esquema completo: 9 tablas (`meta`, `evidence`, `incognita`, `job_history`, `client_tokens`, `cases`, `case_artifacts`, `case_records`, `case_imports`), 14 índices, 0 vistas/disparadores. Límite: copia no atómica de una base posiblemente activa (WAL de 4 MB, modificado el 08/11). | `ev_59184dd1ee489e014d9334b8b227be13b2206daca616478768880992d0bf05a8` |

**Lo que REA no cubrió y por qué (según `AGENTS.md`):**

- `eolfi/observe/uia_driver.ps1`: REA no tiene analizador de PowerShell. Se revisó como fuente normal (sección 3).
- Paquete Python `eolfi/` (80 módulos versionados): es código fuente completo, así que corresponde la inspección del repositorio y no REA. Los `.pyc` de `__pycache__` son derivados locales y no aportan nada que no esté en la fuente. Se pasó `ruff 0.16.8` (ya instalado) en modo lectura con `--select F,B`.
- Ejecución/cobertura dinámica REA: **NO VERIFICADO**. `capture_process_scenario` ya devolvió `capability_unavailable` en Windows (informe del 08/11) y no se volvió a intentar.
- Las 617 + 152 + 11 observaciones no se revisaron una por una. La muestra de la clase `endpoint` de R1 (50 filas) son, en su mayoría, literales de prueba (`"x.py"`, `".env"`, `"tools/list"`) clasificados como candidatos. Esto confirma que el recuento no mide defectos.
- En R3, REA tomó la expresión `.some((h) => …)` de `main.mjs:73` como referencia `require:` sin resolver (`state: inferred`, `confidence: low`). Es un falso candidato del extractor y no indica ningún problema en Eolfi.

### Trabajo pendiente que se debe contar (incógnitas y truncados)

| Origen | Incógnitas | Truncado | Fuera de alcance |
|---|---|---|---|
| R1 vscode-bridge | 16.474 semánticas | no | 0 |
| R2 bridge completo | 40.320 semánticas + 1 de aplicación | **sí** (nodos semánticos, 100.000) | 1 script en línea de `default_app.asar` |
| R3 bridge propio | 8.106 semánticas + 411 de aplicación | no | 420 archivos no seleccionados |
| R4 browser_driver | 457 semánticas | no | resto de `observe/` (Python/PS1, sin analizador JS aplicable) |
| R5 fusibles | 0 (centinela completo) | no | no prueba que la app active Inspector por otras vías |
| R6 SQLite | — | no | filas no muestreadas; atomicidad base/WAL no garantizada |

## 3. Hallazgos que justifican los objetivos

Cada fila combina evidencia REA (R#) con una lectura concreta del código. «Sospecha» significa que todavía no se ha reproducido.

| H | Hallazgo | Evidencia |
|---|---|---|
| H1 | El puente Electron no registra `session.setPermissionRequestHandler` ni `setPermissionCheckHandler`. Si no hay manejador, Electron concede por defecto los permisos que pidan las páginas remotas cargadas (DeepSeek, Gemini, Meta AI): notificaciones, medios, geolocalización, etc. **Sospecha de seguridad**. | R3 (BrowserWindow `main.mjs:80-83`: `partition persist:eolfi-<sitio>`, `contextIsolation`, `sandbox`, `nodeIntegration:false`); `grep setPermissionRequestHandler eolfi/bridge/*.mjs` → 0 resultados |
| H2 | `allowedNavigation` (`main.mjs:69-75`) acepta para **cualquier** sitio los sufijos globales `.google.com`, `.deepseek.com` y `.meta.ai`, además de los `authHostSuffixes` de cada sitio en `sites.json`. Así, la ventana de DeepSeek puede navegar a `*.meta.ai` y viceversa. La lista está duplicada entre código y `sites.json`, y no tiene pruebas: `grep allowedNavigation eolfi/bridge/test` → 0. | R3; lectura de `main.mjs:35,69-75`, `adapters/sites.json:7,70,125` |
| H3 | Electron 45.2.2 de serie tiene `EnableCookieEncryption` deshabilitado, y `RunAsNode`, `NODE_OPTIONS` e `--inspect` habilitados. En el motor de reserva Electron (cuando no se encuentra Chrome: `main.mjs:42-48`), las cookies de sesión de las particiones `persist:eolfi-*` se guardan sin el cifrado del fusible. Esto no aplica al motor Chrome, que usa `--remote-debugging-pipe` y un perfil propio (`engine/chrome.mjs:9,414-416`). | R5; `main.mjs:42-48` |
| H4 | El terminal del agente de VS Code corta por tiempo con `p.kill()` sobre `powershell.exe`/`bash` (`agent-tools.js:131-140`). En Windows eso no termina los procesos hijo que lance el comando. El lado Python ya tiene `_kill_tree` (`eolfi/flows/diff_flow.py`, reutilizado en `observe/session.py`). **Sospecha**: no reproducido. | R1 (familia `child-process`, 4 relaciones, 4 incógnitas); lectura de `agent-tools.js` |
| H5 | `eolas-starter.js:6` fija `DEFAULT_LAUNCHER = 'D:\\celtiaia\\launch-eolas.ps1'` y lo ejecuta con `-ExecutionPolicy Bypass`. Es una ruta absoluta de una máquina concreta, fuera del workspace, y no se comprueba la identidad del script (hash/firma) antes de ejecutarlo. | R1 (familia `configuration`: 46 relaciones, 10 incógnitas); lectura |
| H6 | `uia_driver.ps1` toma la imagen con `Graphics.CopyFromScreen` sobre el rectángulo de la ventana (`CaptureWindow`). Si otra ventana tapa al objetivo, la captura incluye contenido **de otros procesos**. El [informe desktop](avance-ui-desktop-2026-11-08.md) dice «captura únicamente la primera ventana del proceso objetivo», y eso no está garantizado. Además: solo se capturan ventanas de nivel superior del PID (no las de procesos hijo) y el árbol se corta a 300 elementos. | Inspección de fuente (REA no aplicable); `uia_driver.ps1` funciones `CaptureWindow`, `Windows`, `Snapshot` |
| H7 | `ruff --select F,B eolfi`: 16 avisos. 5 F401 (imports sin uso: `cli.py:926 struct`, `server.py:27 HTTPStatus` (ya en LIM-009), `generators_mobile.py:13 _pascal`, `providers/strings.py:5 Path`, `reconstruct/core.py:29 CaseStore`). 6 B023: revisados `explore.py:132-139`, `core.py:425` y `generators_desktop.py:212`; los cierres se llaman dentro de la misma iteración, así que **no son defectos** en el uso actual. Además 2 B007, 2 B905 y 1 B904. | Salida de ruff (sección 6) |
| H8 | `eolfi.db` (en la raíz del repo, ignorado por Git) contiene `client_tokens` y la WAL se modificó el 08/11. La copia que analizó REA no es atómica. LIM-008 (migración v1 de casos) ya se puede decidir: el esquema actual tiene las 4 tablas de casos. | R6; `git check-ignore -v eolfi.db` → `.gitignore:3:*.db` |
| H9 | Brechas abiertas de la hoja de ruta sin evidencia nueva que las cierre: UI móvil (sin adb/SDK/dispositivo), UI desktop fuera de Windows, generación de la Fase 4 limitada a la CLI Python, agente de VS Code nunca probado en un VS Code real, guías de la Fase 7 salvo caja negra. | Plan, Fases 2/4/7; traspaso del 08/11 |
| H10 | La cobertura REA del puente es estructuralmente parcial: semántica `unknown`, más de 16k incógnitas, y R2 truncado por dependencias. Repetir el análisis completo sin acotar no aporta nada; lo útil es el análisis acotado de las fuentes propias (R3) junto con pruebas específicas. | R1, R2, R3 |

## 4. Objetivos priorizados

Prioridad: **P1** seguridad o veracidad de lo que se afirma; **P2** robustez y portabilidad; **P3** higiene y documentación. En todos los objetivos la verificación de cierre es la de `AGENTS.md`: `python -m pytest -q`, `node --test` en `eolfi/bridge` y en `eolfi/vscode-bridge`, y `npm test` en `tests/e2e`, además de las pruebas específicas que se indican.

### P1

**O1 — Política de permisos explícita en el puente Electron** (H1)
- Archivos: `eolfi/bridge/main.mjs`, un módulo nuevo y puro (p. ej. `eolfi/bridge/policy.mjs`), `eolfi/bridge/test/`.
- Aceptación: cada partición `persist:eolfi-*` registra `setPermissionRequestHandler` y `setPermissionCheckHandler` y deniega por defecto. Si hace falta alguna excepción (p. ej. portapapeles), queda documentada y limitada al origen del sitio. La función de decisión es pura y tiene pruebas sin Electron.
- Verificación: prueba unitaria nueva en `node --test` (bridge) y suite completa. Repetir R3 con las mismas `source_paths` y registrar el SHA nuevo. Comprobar en Electron real que se deniega: **NO VERIFICADO** hasta que se ejecute el puente con autorización.

**O2 — Lista de navegación por sitio y con pruebas** (H2)
- Archivos: `eolfi/bridge/main.mjs`, `eolfi/bridge/adapters/sites.json`, el módulo de política de O1 y sus pruebas.
- Aceptación: `allowedNavigation(name, url)` solo admite el origen del sitio, `AUTH_HOSTS` y los `authHostSuffixes` de **ese** sitio; los sufijos globales desaparecen del código. Hay pruebas de: navegación cruzada entre sitios (denegada), `http:` (denegado), sufijo engañoso (`evilgoogle.com`, `google.com.evil.net`: denegados) y los dominios de inicio de sesión reales que ya están en `sites.json` (admitidos).
- Verificación: `node --test` (bridge). Antes de quitar ningún sufijo, revisar con el usuario qué flujos de inicio de sesión dependen de ellos. Validar el login real en vivo: **NO VERIFICADO**, porque requiere cuentas del usuario.

**O3 — Corregir la afirmación sobre la captura desktop y acotar el riesgo** (H6)
- Archivos: `eolfi/observe/uia_driver.ps1`, `eolfi/observe/session.py`, `informes/avance-ui-desktop-2026-11-08.md` (añadir corrección fechada sin borrar el texto original), `README.md` si repite la afirmación.
- Aceptación: o se captura con `PrintWindow` (`PW_RENDERFULLCONTENT`) sobre el HWND del objetivo, o se comprueba antes de cada captura que la ventana está en primer plano y no tapada, y si no, se devuelve `status: occluded` sin imagen. La cobertura de la sesión declara el método usado. La documentación deja de afirmar «solo la ventana del objetivo» si no está garantizado.
- Verificación: `tests/test_observe.py::test_desktop_scenario_windows_uia` (solo Windows) más una prueba nueva con una ventana que tapa al objetivo. Suite pytest completa. En Linux/macOS la prueba se omite y eso se declara.

**O4 — Matar el árbol de procesos en el terminal del agente** (H4)
- Archivos: `eolfi/vscode-bridge/agent-tools.js` y su prueba (`test/agent-tools*.test.js`).
- Aceptación: al agotarse el tiempo, en Windows se termina el árbol completo (`taskkill /PID <pid> /T /F` o equivalente) y en POSIX el grupo (`detached` + `process.kill(-pid)`). Hay una prueba con un `spawnFn` falso que comprueba la orden de terminación del árbol y otra, de laboratorio, que lanza un hijo real y comprueba que desaparece.
- Verificación: `node --test` (vscode-bridge). Probar en un VS Code real: **NO VERIFICADO**.

### P2

**O5 — Lanzador Eolas configurable y comprobado** (H5)
- Archivos: `eolfi/vscode-bridge/eolas-starter.js`, `package.json` de la extensión (ajuste `eolfi.eolas.launcher`), pruebas.
- Aceptación: sin ruta fija a `D:\celtiaia`. El lanzador sale de la configuración y, si falta, el arranque automático queda desactivado con un mensaje claro. Se registra el SHA-256 del `.ps1` antes de ejecutarlo y, si se configura un hash esperado, cualquier diferencia bloquea la ejecución. Se decide con el usuario si se mantiene `-ExecutionPolicy Bypass`.
- Verificación: `node --test` (vscode-bridge). Arranque real de Eolas: **NO VERIFICADO** (depende de `D:\celtiaia` y del modelo local).

**O6 — Motor de reserva Electron: cookies y fusibles** (H3)
- Archivos: `eolfi/bridge/main.mjs`, `README.md` (sección del puente) y, si se empaqueta, la configuración de empaquetado.
- Aceptación: mientras el puente se ejecute con `electron .` sin empaquetar, el README y el arranque avisan de que en el motor Electron las sesiones se guardan sin cifrado de cookies del fusible y de que el motor recomendado es Chrome. Si se decide empaquetar, se usa `@electron/fuses` (`EnableCookieEncryption` activado, `RunAsNode`, `NODE_OPTIONS` e `--inspect` desactivados) y `inspect_electron_fuses` se repite sobre el ejecutable empaquetado.
- Verificación: R5 repetido sobre el artefacto resultante. **Instalar `@electron/fuses` requiere autorización expresa** (`AGENTS.md`: no instalar dependencias sin autorización).

**O7 — Fase 4: generación más allá de la CLI observada, sin inventar** (H9)
- Archivos: `eolfi/reconstruct/core.py`, `eolfi/reconstruct/equivalence.py`, `tests/test_reconstruct.py`.
- Aceptación: el siguiente destino es la API HTTP observada (pasos `http` del guion). Solo se generan rutas, métodos, códigos y cuerpos observados; lo no observado responde «pendiente» con un código distinto. La trazabilidad lleva requisito → evidencia por ruta. El verificador compara efectos (respuesta + archivos capturados) y no da verde solo por el código de salida. Las transiciones de estado entre ejecuciones se siguen declarando parciales.
- Verificación: pruebas sintéticas nuevas de generación, ejecución y equivalencia, y suite completa. Equivalencia general: **NO VERIFICADO** por definición.

**O8 — Captura UI desktop fuera de Windows** (H9)
- Archivos: `eolfi/observe/` (nuevo controlador AT-SPI en Linux; AX en macOS), CI.
- Aceptación: o se implementa con un proveedor real y una prueba en CI, o la matriz y la `coverage` de la sesión lo declaran `not_available` por SO, sin pasos simulados.
- Verificación: CI Linux/macOS (`.github/workflows/ci.yml`, sin reducir cobertura). En Windows local: **NO VERIFICADO**.

**O9 — UI móvil** (H9)
- Aceptación: sin dispositivo, emulador ni `adb`, el objetivo se queda bloqueado y documentado. No se implementa nada que no se pueda ejecutar.
- Verificación: **NO VERIFICADO**; requiere entorno.

### P3

**O10 — Higiene estática** (H7, LIM-009, LIM-011)
- Archivos: los 5 con F401, `generators.py:519`, `generators_mobile.py:273`, `generador/spec.py:91`, `sites/webpage.py:791`, `server.py:371`.
- Aceptación: `ruff check --select F eolfi` sin avisos. Los B023 quedan justificados (comentario o enlace de argumentos por defecto) y los `zip()` llevan `strict` donde las longitudes deban coincidir. Se registra en `REGISTRO_LIMPIEZA.md` antes de tocar nada (LIM-009 ya cubre 2 de los 5 imports) y se respeta la regla de no limpiar hasta la revisión final.
- Verificación: ruff y suite pytest completa.

**O11 — Reducir lo desconocido de REA en el puente con análisis acotados repetibles** (H10)
- Archivos: este informe, `informes/auditoria-rea-vscode-bridge-2026-11-08.md` (seguimiento).
- Aceptación: tras cada cambio en el puente se repiten R1/R3 acotados con las mismas `source_paths` y se registran SHA, evidencia, incógnitas y truncados. Cada objetivo P1 cierra con evidencia REA nueva sobre su archivo (p. ej. un BrowserWindow con manejadores de permisos observados) y con su prueba específica. No se persigue bajar el recuento de incógnitas como fin en sí mismo.
- Verificación: comparar evidencias anteriores y nuevas (`compare_source_to_bundle`/vistas de hechos). Dinámica: **NO VERIFICADO**.

**O12 — Datos locales y registro de limpieza** (H8)
- Aceptación: `REGISTRO_LIMPIEZA.md` incluye una entrada para `eolfi.db*` en la raíz (contiene `client_tokens`; ¿mover a `~/.eolfi`?), con estado `CONSERVAR` hasta decidirlo con el titular. LIM-008 se actualiza con el esquema observado en R6. No se borra ni se mueve nada.
- Verificación: revisión con el usuario.

**O13 — Guías por flujo de la Fase 7 y prueba del agente en VS Code real** (H9)
- Aceptación: una guía por flujo (triaje, web, repo, diff, crear proyecto, puente, agente VS Code), cada una con una muestra autorizada y criterios por paso, ejecutada en CI donde no necesite binarios externos (patrón `tests/test_guia_caja_negra.py`). Una sesión de laboratorio documentada del agente en un VS Code real. Lista de opciones candidatas a retirar para revisarla con el usuario.
- Verificación: pruebas de guía en pytest. VS Code real: laboratorio, **NO VERIFICADO** hasta que se ejecute.

## 5. Orden recomendado

1. O1 + O2 (mismo módulo de política del puente, una sola PR).
2. O3 (veracidad de un informe ya publicado y riesgo de privacidad).
3. O4, después O5.
4. O7 (avance real de la Fase 4); O6 cuando se decida si se empaqueta.
5. O10–O13 al ritmo de la hoja de ruta; O8/O9 según el entorno disponible.

## 6. Verificación ejecutada en esta sesión

Python: `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe` (3.12.10).

Suites de referencia sobre HEAD `5e05056`, árbol limpio, sin cambios de código (este informe es el único archivo nuevo). Sirven de línea base para los objetivos:

| Comando | Directorio | Resultado | Código |
|---|---|---|---|
| `python -m pytest -q` | raíz | **459 aprobadas, 2 omitidas** (299,84 s) | 0 |
| `node --test` | `eolfi/bridge` | **50 aprobadas, 1 omitida** (51) | 0 |
| `node --test` | `eolfi/vscode-bridge` | **146 aprobadas** | 0 |
| `npm test` | `tests/e2e` | **18 aprobadas** (dependencias ya instaladas, sin instalar nada) | 0 |

Que estas suites pasen verifica los escenarios que cubren; no demuestran que H1–H6 estén ausentes (ninguna prueba los ejercita).

- `ruff check --select F,B eolfi --output-format concise` → 16 avisos (H7); `ruff check --select F eolfi --statistics` → 5 F401.
- `gh run list -R CeltiaIA/Eolfi -L 5` → últimos runs de CI `success`.

### Verificado

- Identidades y cobertura de R1–R6 (las devolvió REA; los SHA y los ID de evidencia figuran arriba).
- Estado de Git y de la CI remota.
- Lectura de las líneas de código citadas en H1–H7.

### NO VERIFICADO

- Ningún objetivo está implementado.
- H1, H4 y H6 son sospechas fundadas en la lectura del código: no se han reproducido en ejecución.
- Cobertura dinámica REA (Windows PTY `capability_unavailable`); no se ejecutó el puente, ni Electron, ni la extensión en un VS Code real, ni Eolas.
- Observaciones REA individuales (780 en total en R1+R3+R4) sin revisar una por una; las incógnitas se mantienen abiertas.
- Atomicidad de la instantánea de `eolfi.db`.
- UI móvil y UI desktop fuera de Windows.
