# Fase 1 — Caso de análisis de principio a fin (cierre, 2026-11-06)

Hoja de ruta: [PLAN_INGENIERIA_INVERSA_EOLFI.md](../PLAN_INGENIERIA_INVERSA_EOLFI.md), Fase 1.
Entorno de verificación: Windows 11 Pro 10.0.26300 (AMD64), Python 3.12.10
(`C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`; el alias `python` resuelve a la misma versión),
Node v24.22.1, Chrome del sistema para la prueba e2e (playwright-core 1.64.1, axe-core 4.14.0).

## Qué cambió

| Área | Cambio | Código |
|---|---|---|
| Modelo de caso | Artefactos con identidad tipada: `content` (SHA-256 de los bytes), `git_commit` (commit fijado), `descriptor` (URL o carpeta cuyo contenido puede cambiar) y `derived` (comparación, proyecto, comando). Cada artefacto guarda tamaño (o desconocido), formato, versión, plataforma, procedencia declarada, herramientas+versiones y entorno (SO, versión, arquitectura, Python, Eolfi; sin nombre de equipo ni usuario). Migración automática del esquema v1 y lectura de paquetes v1. | `eolfi/core/cases.py` |
| Registros tipados | Nuevo tipo `analysis`. Los registros de flujo validan `flow`, `status` (`done`/`partial`/`error`/`cancelled`), herramientas, entorno, errores y marcas de tiempo. Orden estable por inserción (antes, dos registros en el mismo tic de reloj podían salir desordenados). | `eolfi/core/cases.py` |
| Conclusiones | `claims` con estado `observed` (exige evidencia de artefacto o reproducción controlada), `derived` (exige alguna evidencia) o `hypothesis`. Se valida al registrar y al importar: un paquete manipulado que convierta una hipótesis en «observada» sin evidencia observada se rechaza entero. | `eolfi/core/cases.py` |
| Enlace automático | `case_id`/`provenance` opcionales en `run_triage`, `run_web`, `run_repo`, `run_diff`, `compare` y `create_project`. El caso se comprueba antes de trabajar; si el flujo falla o se cancela queda un registro `error`/`cancelled` con lo ya identificado. `create` registra también el análisis de cada fuente y no marca verde un proyecto sin verificación. | `eolfi/flows/*.py` |
| CLI | `--case`/`--provenance` en `triage`, `web`, `repo`, `diff`, `compare`, `create`; `case link` (asocia un objetivo ya analizado) y `case report` (HTML/JSON). | `eolfi/cli.py` |
| API | `GET/POST /api/cases`, `GET /api/cases/{id}` (con trabajos vivos y su progreso), `POST …/artifacts`, `POST …/records`, `GET …/export`, `POST /api/cases/import`, `GET …/report` (CSP propia sin scripts). Los trabajos aceptan `case_id` y lo exponen. | `eolfi/server.py` |
| Panel | Pestaña «Casos»: crear, importar, caso activo (cada análisis/proyecto/comparación del panel se registra en él), vista con progreso, registros con estado, errores y resultados parciales, artefactos, incógnitas con «Resolver», informe y exportación. | `eolfi/web/cases.js`, `index.html`, `app.js`, `style.css` |
| Agente VS Code | Herramientas `eolfi_casos` (listar, ver, crear, asociar, registrar, informe) y `eolfi_caso_analizar`, sobre la misma API; cliente con rutas de casos; instrucciones del agente. | `eolfi/vscode-bridge/case-tools.js`, `eolfi-client.js`, `extension.js`, `agent/agents/eolfi.agent.md` |
| Informe | HTML autocontenido y navegable: cada conclusión enlaza evidencias, incógnitas, registro de origen y límites; las evidencias importadas y las hipótesis se señalan; sección de límites agregada. | `eolfi/core/case_report.py` |

## Comprobaciones ejecutadas

| Comando | Resultado |
|---|---|
| `python -m pytest -q` (Python 3.12.10, base inicial antes del cambio) | 321 passed, 2 skipped |
| `python -m pytest -q` (tras el cambio) | 332 passed, 2 skipped (ver resumen final de la ejecución) |
| `node --test` en `eolfi/vscode-bridge` | 127 pass, 0 fail |
| `node --test` en `eolfi/bridge` | 50 pass, 0 fail, 1 skipped (omisión preexistente de la suite) |
| `npm test` en `tests/e2e` (Chrome del sistema) | 12 pass, 0 fail (incluye la nueva prueba de casos con axe en la vista de caso y en el informe) |
| `ruff check --select F,E9` sobre los archivos tocados | 2 avisos preexistentes, ajenos al cambio (ver `REGISTRO_LIMPIEZA.md`, LIM-009) |
| Verificación manual en el navegador integrado | Crear caso → analizar `demo.elf` sintético con el caso activo → vista con registro «completado», herramientas con versión y entorno → informe HTML con estilos aplicados, 0 enlaces internos rotos, sin errores de consola |

Pruebas nuevas: `tests/test_case_flows.py` (9), `tests/test_case_api.py` (2), ajuste en `tests/test_cases.py`,
`eolfi/vscode-bridge/test/case-tools.test.js` (5) y la prueba e2e «casos: …» en `tests/e2e/panel.test.mjs`.

## Criterio de aceptación y evidencias

| Criterio | Evidencia reproducible |
|---|---|
| Iniciar un caso y procesar un objetivo | `test_triage_in_case_records_identity_tools_environment_and_survives_restart`, `test_case_api_end_to_end`, e2e «casos» |
| Revisar y resolver incógnitas | `test_resolving_incognitas_and_cancellation_are_reflected_in_the_case`; botón «Resolver» del panel sobre `/api/incognitas/{id}/resolve` |
| Continuar después de reiniciar | Reapertura de la SQLite en la primera prueba; trabajos con historial ya cubiertos por `test_fase_e` |
| Exportar/importar sin convertir hipótesis en hechos | `test_claims_keep_their_status_and_hypotheses_are_not_promoted`, `test_v1_schema_and_v1_package_are_upgraded`, importación idéntica/conflictiva en la API |
| Reconstruir de dónde salió cada conclusión | `test_html_report_links_conclusions_to_evidence_incognitas_and_escapes` (sin enlaces rotos, texto hostil escapado) y la comprobación de enlaces en el e2e |
| Progreso, errores, parciales y cancelación | Registros `partial`/`error`/`cancelled` en `test_triage_partial_and_error_are_recorded_with_partial_results` y la prueba de cancelación; progreso de trabajos en `GET /api/cases/{id}` |

## Límites y pendientes

- **Agente de VS Code: NO VERIFICADO dentro de un VS Code real.** Las herramientas se probaron con un cliente falso y el cliente HTTP contra un servidor de prueba (rutas, token y cabecera anti-CSRF); no se ejecutó el host de extensiones de VS Code.
- La verificación diferencial (`diff`) sigue disponible solo desde la CLI (ejecuta binarios); no se expuso en el panel ni en el agente.
- Las URL remotas tienen identidad `descriptor`: se registra el tamaño observado, no un hash de contenido. Las carpetas sin git, también `descriptor`.
- La autoridad de las evidencias importadas sigue siendo la declarada por el paquete; el informe lo indica, pero no se reverifica automáticamente.
- No se usó REA: el cambio es de código fuente del propio repositorio y no hay afirmaciones sobre artefactos empaquetados.
- Una prueba de Node (`chat.test.js`, «promesa sin hacer») falló transitoriamente durante el trabajo por un archivo vacío `x` que creé por error en `%TEMP%` (la prueba usa `os.tmpdir()` como workspace). Lo borré tras comprobar que era mío y la suite pasó completa.
