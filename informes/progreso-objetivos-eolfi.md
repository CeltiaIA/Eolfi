# Progreso de Objetivos Eolfi

## O1 + O2 — Política del puente Electron (`eolfi/bridge`)
- Estado: PENDIENTE
- Archivos:
- Pruebas:
- Resultado:

## O4 — Terminar el árbol de procesos (`eolfi/vscode-bridge/agent-tools.js`)
- Estado: PENDIENTE
- Archivos:
- Pruebas:
- Resultado:

## O5 — Lanzador Eolas configurable (`eolfi/vscode-bridge/eolas-starter.js`)
- Estado: PENDIENTE
- Archivos:
- Pruebas:
- Resultado:

## O10 — Imports sin uso (higiene)
- Estado: PENDIENTE
- Archivos:
- Pruebas:
- Resultado:

## O3 — Captura desktop sin contenido de otras ventanas (`eolfi/observe/uia_driver.ps1`)
- Estado: PENDIENTE
- Archivos:
- Pruebas:
- Resultado:

## Otros Objetivos
- O6: HECHO en su parte sin dependencias (2026-11-11); empaquetado con fusibles PENDIENTE de autorización
- O7: HECHO (2026-11-11)
- O8: HECHO (commit `34c50aa`, 2026-11-10)
- O9: PENDIENTE (fuera de esta ejecución)
- O11: PENDIENTE (fuera de esta ejecución)
- O12: HECHO (2026-11-11); decisión sobre mover `eolfi.db` PENDIENTE del titular
- O13: EN CURSO (2026-11-11): 2 guías nuevas con prueba en CI; faltan el puente, el agente VS Code y el laboratorio en VS Code real

## O1 + O2 — resultado (2026-11-09)

Registrado por la supervisión: Eolfi terminó la ronda con «EOLFI-OBJETIVOS-FIN», pero no añadió esta sección.

- Estado: **HECHO**. La política es estática y está probada con pruebas unitarias. El comportamiento en Electron real queda NO VERIFICADO.
- Cómo se hizo: Meta AI (`@eolfi /meta`) propuso `policy.mjs` y su prueba, y Eolfi (Gemma 4 12B local, modo automático) los escribió. Eolfi integró `main.mjs` con `eolfi_edit_file`: 3 ediciones por fragmento, 1 por rango de líneas y 1 de permisos.
- Archivos: `eolfi/bridge/policy.mjs` (nuevo), `eolfi/bridge/test/policy.test.mjs` (nuevo, 9 pruebas), `eolfi/bridge/main.mjs` (imports, sufijos por sitio, `allowedNavigation` → `policyAllowed`, `setPermissionRequestHandler`/`setPermissionCheckHandler` por partición).
- Pruebas (copia `D:\Eolfi-objetivos`, Python 3.12.10):
  - `node --check main.mjs`: OK
  - `node --test` en `eolfi/bridge`: tests 60, pass 59, fail 0, skipped 1
  - `node --test` en `eolfi/vscode-bridge`: tests 155, pass 155, fail 0
  - `python -m pytest -q`: 459 passed, 2 skipped
  - `npm test` en `tests/e2e`: tests 18, pass 18, fail 0
- REA (estático): `analyze_javascript_application` sobre `eolfi/bridge`, SHA-256 `18f15eda06e4e40efa5a3639f8fc1a6ca6f80be0f7cac737675144ec4c1ffbff`, evidencia `ev_497d4dd0f686dba28bb06b69b8029ee92b0fdfa1f4bbc72f1ab0e795c88e739e`. 10 JS analizados, 0 fallos de parseo, 3.701 incógnitas semánticas, 12 archivos fuera de selección.
- NO VERIFICADO: que Electron deniegue de verdad los permisos y la navegación cruzada (no se ejecutó el puente con motor Electron), y los inicios de sesión reales con la lista nueva.

## Cambios de herramientas hechos durante la supervisión (fuera del plan original)

- `eolfi/bridge/adapters/meta.mjs` (árbol principal `D:\Eolfi`): las respuestas de Meta con varios bloques de código llegaban recortadas («N líneas ocultas»). Se pulsa una vez el desplegable y cada bloque se lee con `textContent`; si no se puede recuperar, la marca se conserva. Prueba: `test/meta-hidden-lines.test.mjs` (3). Bridge principal: 53 pass, 1 skipped.
- `eolfi/vscode-bridge` (este worktree): herramienta `eolfi_edit_file` (por fragmento literal o por rango de líneas con `expect_start`), con diario y deshacer, y excluida del modo de solo lectura. Prueba: `test/workspace-edit.test.js` (9).
- Corregido (2026-11-09): el nombre en blanco en «Archivos cambiados» no es un fallo de Eolfi; el runner de supervisión no implementa `stream.anchor`, que es lo que pinta el enlace en VS Code (`chat.js:876`).

## O1 + O2 — resultado (verificado por la supervisión, 2026-11-09)

Implementado por Eolfi (Meta AI propuso el código; Gemma 4 12B local lo aplicó con `eolfi_write_file` y `eolfi_edit_file`). Eolfi no escribió esta sección: la completa la supervisión con lo ejecutado.

- Archivos: `eolfi/bridge/policy.mjs` (nuevo), `eolfi/bridge/test/policy.test.mjs` (nuevo, 9 pruebas), `eolfi/bridge/main.mjs` (imports, sufijos por sitio, `allowedNavigation` → `policyAllowed`, manejadores de permisos por partición).
- Suites en `D:\Eolfi-objetivos` (Python 3.12.10): `pytest -q` 459 aprobadas / 2 omitidas; `node --test` bridge 59 aprobadas / 1 omitida / 0 fallos; `node --test` vscode-bridge 155/155; `npm test` e2e 18/18. Todas con código 0.
- REA estático (fuentes propias del bridge): SHA-256 `18f15eda06e4e40efa5a3639f8fc1a6ca6f80be0f7cac737675144ec4c1ffbff`, evidencia `ev_497d4dd0f686dba28bb06b69b8029ee92b0fdfa1f4bbc72f1ab0e795c88e739e`; 10 JS, 0 fallos de parseo, 3.701 incógnitas semánticas.
- Prueba dinámica, motor Electron, ventana de DeepSeek (perfil temporal), por CDP:

| Prueba | Antes (HEAD) | Ahora |
|---|---|---|
| Notification.requestPermission | granted | denied |
| permiso geolocalización / notificaciones | granted / granted | denied / denied |
| getUserMedia (micrófono) | concedido | NotAllowedError |
| getCurrentPosition | concedido | denegado |
| navegar a https://www.meta.ai/ | permitido | bloqueado |

- Matriz de navegación antigua vs nueva (6 sitios × 25 URL): 0 URL ganadas; todas las perdidas son cruzadas entre sitios (p. ej. DeepSeek → *.google.com / *.meta.ai). Los hosts de inicio de sesión de `AUTH_HOSTS` y de cada `authHostSuffixes` siguen admitidos.
- Estado: **HECHO para el motor Electron**.

### NO VERIFICADO / pendiente
- **Motor Chrome (el predeterminado si hay Chrome instalado):** `engine/chrome.mjs` no aplica ni la política de permisos ni la de navegación. Prueba con Chrome de serie y perfil temporal: los permisos quedan en «prompt» (diálogo al usuario, no concesión silenciosa) y la navegación DeepSeek → meta.ai **sí** se permite. O2 sigue abierto en ese motor.
- Inicio de sesión real en cada sitio con cuentas del titular (requiere sus credenciales).

## O2 en el motor Chrome — resultado (2026-11-09, supervisión)

- Cambios: `engine/chrome.mjs` (opción `policy`: `Fetch.enable` en cada pestaña de sitio y cancelación `Aborted` de la navegación del marco principal hacia destinos no admitidos; cierre de ventanas emergentes abiertas por una pestaña de sitio hacia destinos no admitidos; `Browser.setPermission` denegado para `DENIED_PERMISSIONS`), `policy.mjs` (`DENIED_PERMISSIONS`), `main.mjs` (pasa la política al motor), prueba nueva `test/engine-policy.test.mjs` (Chrome real, `EOLFI_REAL_BROWSER=1`).
- `EOLFI_REAL_BROWSER=1 node --test test/engine-policy.test.mjs`: 3/3 (navegación cruzada bloqueada y la página se conserva; navegación propia admitida; emergente cerrada; geolocalización y notificaciones `denied`).
- Suites: bridge 59 aprobadas / 4 omitidas (laboratorio) / 0 fallos; vscode-bridge 155/155; e2e 18/18; pytest 458 aprobadas / 2 omitidas / **1 fallo** `test_hardening.py::test_hostile_html_and_css_finish_fast` (límite de 5 s, tardó 6,4 s con el equipo cargado: la suite tardó 12,9 min frente a 4,8). Repetido aislado: `tests/test_hardening.py` 17 aprobadas / 1 omitida. No se cambió ningún `.py`.
- Previo, no causado por este cambio: `test/engine.test.mjs` falla al borrar el perfil temporal (`EPERM`) también en `D:\Eolfi` sin cambios.

### NO VERIFICADO
- El puente completo en modo Chrome con el perfil real `~/.eolfi/browser-profile` (sesiones del titular): la política se probó en `ChromeEngine` con perfil temporal y servidores locales.
- Inicio de sesión real en cada sitio.
- La lista `DENIED_PERMISSIONS` es más estrecha que la denegación total de Electron (p. ej. no deniega `storage-access`, para no romper inicios de sesión con terceros).

## O3 — Captura desktop sin contenido de otras ventanas (2026-11-09, supervisión)

- Cambios: `eolfi/observe/uia_driver.ps1` (`PrintWindow` con PW_RENDERFULLCONTENT en lugar de `CopyFromScreen`; `print_window_failed` sin alternativa; `method`), `eolfi/observe/session.py` (texto de límites de la cobertura), `tests/observe_samples.py` (`WINFORMS_AT`, `OCCLUDER`), `tests/test_observe.py` (prueba nueva de ventana tapada; aserción de repetición ajustada y justificada), `informes/avance-ui-desktop-2026-11-08.md` (corrección fechada).
- Prueba nueva: la muestra tapada por una ventana magenta de otro proceso → capturas sin magenta (< 5 %).
- Inestabilidad previa, no causada por este cambio: `test_desktop_scenario_windows_uia` puede fallar si se teclea mientras corre (la ventana de prueba toma el foco: «uhola» en `D:\Eolfi` sin cambios).

## O4 — resultado (2026-11-09)

Registrado por la supervisión: Eolfi no añadió esta sección.

- Estado: **HECHO** (pruebas unitarias). Que `taskkill /T` mate de verdad los hijos de un proceso real queda NO VERIFICADO: la prueba usa un `spawn` falso.
- Cómo se hizo: Eolfi (Gemma 4 12B, modo automático) aplicó las 4 ediciones de `agent-tools.js` con `eolfi_edit_file`, en tres rondas. En la primera declaró «completado» sin haber creado ni ejecutado la prueba; en la segunda se quedó sin contexto. En la tercera creó la prueba con una orden de terminal (copiando las líneas 29-91 de `PROMPT_O4.md`) y ejecutó `node --test` (código 0). Borró el comentario «Mata el árbol completo» en vez de corregir su sangría (pendiente estético).
- Archivos: `eolfi/vscode-bridge/agent-tools.js` (`killFn` inyectable, `detached` en POSIX, `kill` con `taskkill /PID … /T /F` o grupo POSIX, sin repetir, sin matar tras `close`), `eolfi/vscode-bridge/test/agent-tools-kill.test.js` (3 pruebas; con el código anterior fallan 2).
- Pruebas (copia `D:\Eolfi-objetivos`, árbol completo en el momento de la ejecución):
  - `node --test test/agent-tools-kill.test.js`: pass 3, fail 0
  - `node --test` en `eolfi/vscode-bridge`: tests 158, pass 158, fail 0
  - `node --test` en `eolfi/bridge`: tests 63, pass 59, fail 0, skipped 4 (3 nuevas de Chrome real, con `EOLFI_REAL_BROWSER=1`)
  - `python -m pytest -q`: 460 passed, 2 skipped, 2 warnings (DeprecationWarning de Pillow `getdata` en `test_desktop_screenshot_excludes_overlapping_windows`)
  - `npm test` en `tests/e2e`: tests 18, pass 18, fail 0

## Cambios en paralelo que no hicieron Eolfi ni esta supervisión

Entre las 12:17 y las 12:44 UTC aparecieron en este worktree cambios de otra sesión, probablemente el «Chat lateral» de esta familia de sesiones:
- O3: `uia_driver.ps1` usa `PrintWindow` (PW_RENDERFULLCONTENT) en vez de `CopyFromScreen`, con `method` y `print_window_failed`; además `session.py`, `tests/test_observe.py` (prueba de ventanas superpuestas), `tests/observe_samples.py` y una corrección en `informes/avance-ui-desktop-2026-11-08.md`.
- Motor Chrome del puente: `engine/chrome.mjs` aplica por CDP la misma política (permisos denegados, navegación del marco principal y ventanas emergentes), y hay ajustes en `main.mjs` y `test/engine-policy.test.mjs`.

Se conservan. Pasan las suites de arriba, pero esta supervisión no los ha revisado en detalle.


## O5 — resultado
**Archivos cambiados:**
- eolfi/vscode-bridge/eolas-starter.js
- eolfi/vscode-bridge/extension.js
- eolfi/vscode-bridge/package.json
- eolfi/vscode-bridge/test/eolas-starter-launcher.test.js

**Resultados de pruebas:**
ℹ tests 6
ℹ suites 0
ℹ pass 6
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 146.5417

### O5 — verificación de la supervisión (2026-11-09)

- Eolfi (Gemma 4 12B, contexto 32.768) aplicó O5 en 8 rondas de una sola edición cada una (98–148 s por ronda, sin bucles). La última ronda copió la prueba, ejecutó las pruebas y escribió la sección de arriba (504 s).
- Corrección: las cifras de arriba (tests 6) son de las pruebas concretas, no de la suite completa. Suites completas en esta copia:
  - `node --test test/eolas-starter-launcher.test.js test/eolas-starter.test.js`: tests 6, pass 6, fail 0
  - `node --test` en `eolfi/vscode-bridge`: tests 162, pass 162, fail 0
  - `node --test` en `eolfi/bridge`: tests 63, pass 59, fail 0, skipped 4
  - `python -m pytest -q`: 460 passed, 2 skipped, 2 warnings
  - `npm test` en `tests/e2e`: tests 18, pass 18, fail 0
- NO VERIFICADO: arrancar Eolas de verdad con el lanzador y el hash configurados.
- Efecto para el usuario: `eolfi.fallback.eolasLauncher` ya no tiene `D:\celtiaia\launch-eolas.ps1` por defecto. Para el autoarranque hay que configurarlo o definir `CELTIAIA_HOME`.
- Configuración local cambiada a petición del usuario: `~/.eolfi/llamacpp.json` pasa a ctx 32768 y gpu_layers 11 (antes 12288 y 17; copia en `llamacpp.json.bak-2026-11-09`).

## Revisión de conjunto antes de seguir (2026-11-09)

Revisados todos los diffs del worktree (rama `objetivos-rea-2026-11-09`) y `eolfi/bridge/adapters/meta.mjs` del árbol principal. Suites en verde (sección O5). REA estático sobre `eolfi/vscode-bridge` (6 fuentes cambiadas): SHA-256 `4cde0e3e10963f2855f8b37305e1a78ac01ea7dab5b8296cb15041cdb6b4b539`, evidencia `ev_544763c7c012a46bd907040b3b11642a8e3b2b35b89dd6b0b4ec2f74874f9cc2`, 0 fallos de parseo, 6.083 incógnitas semánticas. La familia `child-process` queda con 0 relaciones porque `spawn` llega inyectado (`spawnFn`): REA no ve esas llamadas, y esa parte la cubren solo las pruebas.

Hallazgos:
1. **Riesgo de inicio de sesión (NO VERIFICADO, el más importante).** La política nueva quita los sufijos globales `.google.com`/`.deepseek.com`/`.meta.ai`. El motor Chrome (el que se usa por defecto) antes no restringía la navegación del marco principal y ahora sí (`Fetch.failRequest`). Un inicio de sesión de DeepSeek o Meta que pase por hosts de Google distintos de `accounts.google.com`/`myaccount.google.com` (por ejemplo `www.google.com` o `accounts.youtube.com`) quedaría bloqueado. Las sesiones guardadas siguen funcionando; el riesgo aparece al volver a iniciar sesión. Falta probar el inicio de sesión real en cada sitio, o ampliar `AUTH_HOSTS` con los hosts de OAuth que se observen.
2. **Electron: `setPermissionCheckHandler` deniega todo salvo `clipboard-sanitized-write`.** Incluye comprobaciones como `storage-access`, que algunos flujos de inicio de sesión de terceros pueden usar. Mismo riesgo y misma comprobación pendiente (solo motor Electron).
3. **`agent-tools.js`:** el `spawn` de `taskkill` no tiene manejador de `error`. Si `taskkill` no se pudiera lanzar, Node emitiría un `error` sin oyente y tumbaría el host de extensiones. Es improbable en Windows (System32), pero la corrección es de una línea. Tampoco hay alternativa si `taskkill` falla después de arrancar.
4. **`eolas-starter.js`:** entre calcular el SHA-256 y ejecutar el script pasa un instante (TOCTOU): un script cambiado justo entonces no se detectaría. Riesgo bajo en local; se documenta.
5. **Documentación:** el README no menciona `eolfi.fallback.eolasLauncherSha256` ni que el lanzador ya no tiene valor por defecto.
6. **O3 (otra sesión):** correcto. Una aserción de `test_desktop_scenario_windows_uia` pasó de `==` a `<=`, justificado y documentado: con `PrintWindow` la imagen puede repetirse idéntica. Quedan 2 avisos de Pillow (`getdata` está obsoleto).
7. **Integración:** la corrección de `adapters/meta.mjs` (líneas ocultas) y su prueba están **solo en el árbol principal** `D:\Eolfi`, no en este worktree; hay que llevarlas al integrar. `informes/plan-objetivos-rea-2026-11-09.md` está sin seguimiento en los dos sitios.
8. **Restos de la supervisión en el worktree** (no se deben confirmar): `OBJETIVOS_EOLFI.md`, `PROMPT_*.md`, `PROMPT_O5_package.json`, `PROMPT_O5_test.js`, `prompts-o5/` y la unión `tests/e2e/node_modules` → `D:\Eolfi\tests\e2e\node_modules` (ignorada por Git).
9. **Retirado:** el «nombre en blanco» de «Archivos cambiados» era del runner, no de Eolfi.

## O10 — resultado
**Archivos analizados:**
- eolfi/cli.py
- eolfi/server.py
- eolfi/generador/generators_mobile.py
- eolfi/providers/strings.py
- eolfi/reconstruct/core.py

**Salida de ruff:**
All checks passed!

**Salida de pytest:**
93 passed in 59.37s

### O10 — verificación de la supervisión (2026-11-09)

- **HECHO.** Eolfi quitó los 5 imports en 5 rondas de una edición (72–149 s cada una) y en la 6.ª ejecutó ruff y pytest (código 0) y escribió la sección de arriba. No añadió la línea de `REGISTRO_LIMPIEZA.md` ni puso la marca de fin; esa línea la añadió la supervisión (LIM-009 → RETIRADO).
- Correcciones de la supervisión hechas a la vez: manejador de `error` del `spawn` de `taskkill` con vuelta a `p.kill()` y prueba nueva (`agent-tools-kill.test.js`, 4/4); comentario «Mata el árbol completo» recuperado; apartado «Autoarranque de Eolas» en el README.
- Suites completas (worktree):
  - `ruff check --select F eolfi`: All checks passed!
  - `python -m pytest -q`: 460 passed, 2 skipped, 2 warnings
  - `node --test` en `eolfi/bridge`: tests 63, pass 59, fail 0, skipped 4
  - `node --test` en `eolfi/vscode-bridge`: tests 163, pass 163, fail 0
  - `npm test` en `tests/e2e`: tests 18, pass 18, fail 0

## Prueba en vivo de inicios de sesión con la política nueva (2026-11-09)

- Puente del worktree (motor Chrome, política nueva) con un **perfil temporal vacío**, aislado del perfil real `~/.eolfi/browser-profile` (`USERPROFILE`, `APPDATA` y `LOCALAPPDATA` en una carpeta temporal).
- Con el perfil vacío, DeepSeek, Gemini y Meta AI cargaron en «Inicia sesión» sin ninguna navegación ni ventana emergente bloqueada (0 líneas «bloqueada» en el registro).
- Dentro del navegador controlado, Google avisa de que «este navegador puede no ser seguro» y el captcha de DeepSeek no valida. **No lo causa la política**: es la detección de navegadores controlados por software, ya documentada en el README; por eso existe `eolfi bridge --login`.
- Con `python -m eolfi bridge --login` (Chrome normal sin control, mismo perfil temporal), el titular inició sesión en los tres sitios. El puente con la política nueva los reconoce: DeepSeek, Gemini y Meta AI «listo · con sesión» (`signedIn: true`), con 0 bloqueos en el registro.
- Conclusión: la política nueva no interfiere en el procedimiento de inicio de sesión (que pasa fuera del navegador controlado) ni en la recuperación de sesiones.
- NO VERIFICADO: enviar mensajes reales con el puente nuevo (navegaciones dentro de cada chat durante el uso) y el motor Electron.
- Cierre: puente de prueba y su Chrome cerrados; el perfil temporal con las sesiones de prueba se **borró** a petición del titular. Los registros, sin cookies, se conservan en la carpeta de trabajo de la supervisión (`scratchpad/logintest-logs`).

## O14 — Eolas como modelo de VS Code

- **Motivo**: sin un modelo registrado, el chat de VS Code da «Language model unavailable» y no llega a @eolfi si no hay sesión de Copilot
- **Archivos**: `eolfi/vscode-bridge/lm-provider.js`, `test/lm-provider.test.js`, `extension.js`, `package.json`
- **Estado**: pruebas unitarias en verde (168/168); e2e en VS Code real 11/11 —sin Copilot, la pregunta libre la responde el modelo local por Eolas—; **instalada** en el VS Code del usuario (0.6.11, 2026-11-10). La comprobación de la e2e se actualizó: acepta la respuesta del modelo local en vez de exigir el aviso de «sin modelo».

## O6 — Motor de reserva Electron: aviso de cookies sin cifrar (2026-11-11)

- Estado: **HECHO** en la parte que no necesita instalar nada. No se instaló `@electron/fuses` (requiere autorización expresa, `AGENTS.md`).
- Archivos: `eolfi/bridge/policy.mjs` (función pura `electronEngineWarning(engine, packaged)`), `eolfi/bridge/main.mjs` (muestra el aviso al arrancar con el motor Electron sin empaquetar), `eolfi/bridge/test/policy.test.mjs` (1 prueba nueva), `README.md` (sección del puente).
- Verificación: `node --check main.mjs` OK; `node --test` en `eolfi/bridge`: 67 pruebas, 63 aprobadas, 0 fallos, 4 omitidas (Linux, sin Electron).
- NO VERIFICADO: el aviso en un arranque real de Electron; R5 sobre un ejecutable empaquetado (no existe).

## O12 — Datos locales y registro de limpieza (2026-11-11)

- Estado: **HECHO**. `REGISTRO_LIMPIEZA.md`: nueva LIM-013 (`eolfi.db*`, `CONSERVAR`) y LIM-008 actualizada con el esquema de R6. No se borró ni movió nada.
- Pendiente del titular: decidir si `eolfi.db` pasa a `~/.eolfi/`.

## O7 — Fase 4: generación de la API HTTP observada (2026-11-11)

- Estado: **HECHO**. Hecho directamente por la supervisión, sin Eolfi en automático.
- `eolfi/reconstruct/core.py`: componente `http_api` con casos por requisito (método, ruta con consulta, cuerpo de la petición tomado del guion, estado, tipo de contenido y cuerpo de la respuesta, archivos capturados). Nuevo destino `python-http` (`server.py` + `api.json` + `tests/test_server.py`, solo biblioteca estándar). La lógica de archivos capturados se extrajo a `_file_effects` y se comparte con la CLI. Sin `--target`, se elige la CLI si se observó y, si no, la API HTTP.
- Sin inventar: solo se generan rutas, métodos, códigos y cuerpos observados. Lo no observado responde **501** con `X-Eolfi-Estado: no-especificado`, y lo pendiente **503** con `X-Eolfi-Estado: pendiente`. Pasan a pendientes las respuestas que cambian entre peticiones iguales (contradicción, estado no modelado), los cuerpos truncados o no UTF-8, los cuerpos con datos personales ocultados o con `{var:…}`, y las peticiones sin respuesta. Las cookies (solo se conocen por nombre) y las redirecciones dejan el caso en «parcial».
- Trazabilidad: `.eolfi/trazabilidad.json` lleva `route`, requisito y evidencias por caso.
- Verificador: arranca un servidor por caso en una carpeta vacía y compara `respuesta[*].estado`, `respuesta[*].cuerpo`, `respuesta[*].cabeceras` (tipo de contenido) y `archivos`; no da verde solo por el código. `equivalent_on_observed` exige 0 diferencias y 0 parciales, como en la CLI; los pendientes se cuentan aparte (`pending`) y dejan la reconstrucción en «partial» (código 4 de la CLI). Corregido el 2026-11-11: antes aquí decía que también exigía 0 pendientes.
- `eolfi reconstruct --target` admite `python-cli` y `python-http` (por defecto, automático).
- Verificación (Linux, Python 3.13, copia del árbol): `tests/test_reconstruct.py` 15/15 (3 nuevas: modelo y trazabilidad + pruebas generadas en verde; 501/503 y detección de un cambio de cuerpo como `respuesta[*].cuerpo`; `reconstruct` con evidencia y errores de destino). Suite completa: 453 aprobadas, 10 omitidas y 4 fallos que **también fallan sin estos cambios** en ese entorno (sin red ni procesos de Windows): `test_fase_a::test_cli_create_db_flag_does_not_replace_evidence_store`, `test_fase_b_sites::test_old_clones_are_pruned_but_foreign_folders_are_kept`, `test_fase_e::test_clone_privado_sin_token_explica_que_hacer` y `test_observe::test_timeout_kills_process_tree`.
- NO VERIFICADO: la suite en Windows tras este cambio; equivalencia general (por definición); cabeceras de la petición, cookies, redirecciones y transiciones de estado entre peticiones.

## O13 — Guías por flujo ejecutadas en la CI (2026-11-11, parcial)

- Nuevas, con el patrón de `tests/test_guia_caja_negra.py` (la prueba ejecuta los mismos comandos que la guía y comprueba cada criterio de aceptación):
  - `ejemplos/api-http/` (`servidor.py`, API de notas sintética, y `guion.json`) → `tests/test_guia_api_http.py`: plan, observación con `--var port`, especificación (6 requisitos, 2 de error, 1 contradicción), reconstrucción `python-http` (5 simulados y 1 pendiente, 5 coinciden y 0 difieren, código 4), pruebas generadas en verde, 501/503 y el informe del caso.
  - `ejemplos/triaje-y-diff/` (`muestra.wasm` de 42 bytes, `referencia.py`, `candidato.py` con un fallo deliberado, `corpus/`) → `tests/test_guia_triaje_diff.py`: triaje `--local`, evidencia `wasm_module`, informe Markdown con `--fail-on high`, `diff` sin `--autorizo` (no ejecuta), con divergencia (código 4, incógnita abierta) y tras corregir (código 0, incógnita cerrada).
- Defecto encontrado al escribir la guía y corregido: el filtro de datos personales tomaba la fecha del informe («2026-11-11 00:33») por un teléfono y la ocultaba. `eolfi/security/privacy.py` excluye ahora las fechas con hora, y `tests/test_privacy.py` tiene 2 casos nuevos.
- Verificación (Linux, Python 3.13): las 3 guías 5/5; suite completa 459 aprobadas, 10 omitidas y los mismos 4 fallos del entorno que en O7.
- Pendiente: guías de web, repo, crear proyecto, puente y agente VS Code; laboratorio del agente en un VS Code real; lista de opciones candidatas a retirar para revisarla con el titular.

### O13 — guía de web, repo y crear proyecto (2026-11-11)

- `ejemplos/web-y-repo/` (`sitio/`, estático de notas; `repo/`, paquete Python sin licencia a propósito) → `tests/test_guia_web_repo.py` (3 pruebas; la de `create` se omite si no hay Node.js, que la CI sí tiene): `web` sin framework atribuido, con esqueleto, tokens, `/api/notas`, `fetch` y `localStorage` leídos del JS sin ejecutarlo; `repo` con lenguajes, `pyproject.toml` (script `notas`), pruebas e incógnita «Sin licencia detectada»; `create` con destino `static` y verificación en verde.
- **Hallazgo para la revisión de opciones (no se cambia sin el titular):** `create` añade por defecto las secciones `Hero` y `Features` aunque la fuente no las tenga (`eolfi/generador/spec.py`, «if "Hero" not in secs»), y `eolfi.spec.json` no distingue lo observado de lo añadido. La guía lo advierte y la prueba lo fija para que cualquier cambio sea deliberado.
- Verificación (Linux): las 4 guías, 8/8.
