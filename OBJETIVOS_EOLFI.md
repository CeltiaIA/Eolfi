# Objetivos para Eolfi (ejecución automática) — 2026-11-09

Plan completo con evidencias: [informes/plan-objetivos-rea-2026-11-09.md](informes/plan-objetivos-rea-2026-11-09.md).
Lleva el progreso en `informes/progreso-objetivos-eolfi.md`: un apartado por objetivo, con los archivos cambiados, las pruebas que has ejecutado y su resultado literal (aprobadas/fallidas/código de salida).

## Reglas (obligatorias)

1. Trabajas en la copia `D:\Eolfi-objetivos` (rama `objetivos-rea-2026-11-09`). No toques nada fuera de esta carpeta.
2. Lee `AGENTS.md` antes de empezar y cúmplelo.
3. No hagas commits ni push. No instales dependencias (`npm install`, `pip install`, …). No borres archivos. No uses la red salvo el modelo local.
4. Para cambiar un archivo, primero léelo. Haz cambios pequeños y conserva lo que ya funciona.
5. Después de cada objetivo, ejecuta la prueba específica y luego la suite del componente. No declares nada terminado sin ejecutar las pruebas. Si una prueba falla, corrígelo; si no puedes, anótalo como `FALLIDO` con la salida.
6. No debilites pruebas existentes ni borres aserciones para conseguir un verde.
7. Un objetivo cada vez, en el orden de abajo. Al acabar uno, actualiza el progreso y pasa al siguiente.

Comandos de prueba (desde `D:\Eolfi-objetivos`):
- Puente: `cd eolfi/bridge; node --test`
- Extensión: `cd eolfi/vscode-bridge; node --test`
- Python: `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q tests/test_observe.py` (y otras pruebas concretas)

## Objetivos de esta ejecución, en orden

### O1 + O2 — Política del puente Electron (`eolfi/bridge`)
- Crea `eolfi/bridge/policy.mjs` con funciones puras exportadas:
  - `allowedNavigation(site, url, authHosts)`: devuelve `true` solo si la URL es `https:` y su host es el origen del sitio, uno de `authHosts` o coincide con un `authHostSuffixes` **de ese sitio** (exacto, o sufijo que empieza por `.`). Sin sufijos globales (`.google.com`, `.deepseek.com`, `.meta.ai`) en el código: si algún sitio los necesita, van en `adapters/sites.json` dentro de su `authHostSuffixes`.
  - `permissionDecision(site, permission, requestingUrl)`: deniega por defecto. Si haces una excepción (por ejemplo `clipboard-sanitized-write`), que sea solo para el origen del sitio.
- En `eolfi/bridge/main.mjs`, usa `allowedNavigation` del módulo nuevo y registra para cada partición `persist:eolfi-<sitio>` `session.fromPartition(...).setPermissionRequestHandler` y `setPermissionCheckHandler` con `permissionDecision`.
- Pruebas nuevas en `eolfi/bridge/test/policy.test.mjs` (sin Electron), que cubran: navegación cruzada entre sitios denegada, `http:` denegado, `evilgoogle.com` y `google.com.evil.net` denegados, origen propio y hosts de inicio de sesión admitidos, permisos denegados por defecto.
- Verificación: `node --test` en `eolfi/bridge` sin fallos.

### O4 — Terminar el árbol de procesos (`eolfi/vscode-bridge/agent-tools.js`)
- Cuando `runShell` agote el tiempo o se cancele, en Windows termina el árbol completo (`taskkill /PID <pid> /T /F` con `spawnFn`), y en POSIX lanza con `detached: true` y mata el grupo con `process.kill(-pid)`.
- Prueba con un `spawnFn` falso que compruebe que se pide matar el árbol (añádela a la prueba existente de agent-tools en `eolfi/vscode-bridge/test/`).
- Verificación: `node --test` en `eolfi/vscode-bridge`.

### O5 — Lanzador Eolas configurable (`eolfi/vscode-bridge/eolas-starter.js`)
- Quita la ruta fija `D:\celtiaia\launch-eolas.ps1` como valor por defecto obligatorio. Si no hay lanzador configurado (`eolfi.fallback.eolasLauncher`), el autoarranque falla con un mensaje claro. Conserva la compatibilidad: documenta en el README la ruta antigua como ejemplo.
- Antes de ejecutar, calcula el SHA-256 del `.ps1` y regístralo. Si se configura `eolfi.fallback.eolasLauncherSha256` y no coincide, no ejecutes.
- Actualiza `package.json` de la extensión (los ajustes nuevos) y las pruebas.
- Verificación: `node --test` en `eolfi/vscode-bridge`.

### O10 — Imports sin uso (higiene)
- Retira solo los 5 imports sin uso que marca `ruff check --select F eolfi`: `eolfi/cli.py` (`struct`), `eolfi/server.py` (`HTTPStatus`), `eolfi/generador/generators_mobile.py` (`_pascal`), `eolfi/providers/strings.py` (`Path`), `eolfi/reconstruct/core.py` (`CaseStore`). Antes, comprueba con una búsqueda que no se usen.
- Añade una línea en `REGISTRO_LIMPIEZA.md` (LIM-009 → estado y fecha).
- Verificación: `ruff check --select F eolfi` sin avisos y `python -m pytest -q tests/test_reconstruct.py tests/test_server.py`.

### O3 — Captura desktop sin contenido de otras ventanas (`eolfi/observe/uia_driver.ps1`)
- Sustituye `CopyFromScreen` por `PrintWindow(hwnd, hdc, 2)` (PW_RENDERFULLCONTENT) sobre el HWND del objetivo. Si `PrintWindow` falla, devuelve `status = 'print_window_failed'` sin imagen; no vuelvas a `CopyFromScreen`.
- Añade `method = 'PrintWindow'` al resultado de la captura.
- Añade al final de `informes/avance-ui-desktop-2026-11-08.md` una corrección fechada (sin borrar el texto anterior): el método anterior podía incluir ventanas superpuestas.
- Verificación: `python -m pytest -q tests/test_observe.py`.

## Fuera de esta ejecución

O6, O7, O8, O9, O11, O12 y O13 necesitan decisiones del titular, dependencias nuevas o un entorno que no tienes (dispositivo móvil, Linux/macOS, VS Code real). No los implementes: anótalos en el progreso como `PENDIENTE (fuera de esta ejecución)`.

## Final

Cuando termines los cinco bloques, escribe en el progreso un resumen con cada objetivo y su estado: `HECHO (pruebas: …)`, `FALLIDO (motivo)` o `NO VERIFICADO (motivo)`. Termina tu respuesta con la línea exacta `EOLFI-OBJETIVOS-FIN`.
