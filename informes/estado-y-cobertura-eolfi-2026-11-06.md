# Revisión de estado y cobertura de Eolfi — Fase 0

Fecha: 2026-11-06

## Resultado

Se completó el rebaselining del repositorio. El plan vigente es `PLAN_INGENIERIA_INVERSA_EOLFI.md`; `PLAN_CORRECCIONES.md` y `PLAN_MEJORAS_2026-11-05.md` se conservan como historial, no como backlog paralelo. La verificación local de este cierre terminó con Python 315 aprobadas y 2 omitidas, puente Node 50 aprobadas y 1 omitida, extensión VS Code 122 aprobadas y panel E2E 11 aprobadas.

El árbol ya ofrece análisis estático diverso y generación de proyectos, pero todavía no demuestra un circuito general de caja negra que describa el comportamiento completo de cualquier objetivo y valide equivalencia de la reconstrucción. Las capacidades de REA accesibles desde VS Code son complementarias y opcionales; no se deben atribuir a todos los flujos nativos de Eolfi.

## Inventario actual

- `eolfi/core`: evidencias inmutables, incógnitas, almacén SQLite, informes y exportación SARIF/STIX.
- `eolfi/providers`: triaje y parsers locales de PE/ELF/Mach-O, DEX/APK/IPA, .NET, Java/JAR, WASM y formatos relacionados; proveedores opcionales para capa, rizin/radare2 y Ghidra.
- `eolfi/sites`: inspección estática de webs y repositorios, carga de red limitada y detección de tecnologías.
- `eolfi/flows`: triaje, aprendizaje de webs/repositorios, comparación de versiones, generación y comparación diferencial de procesos.
- `eolfi/generador`: especificación de proyecto, plantillas multiplataforma, asistencia de IA y verificación por instalación/build/pruebas/humo.
- `eolfi/server.py`, `eolfi/web` y `eolfi/cli.py`: API/panel, trabajos persistentes, informes y comandos.
- `eolfi/bridge`: servidor local y puente con chats web; `eolfi/vscode-bridge`: agente, MCP local, auditoría, llamadas REA con confirmación por tipo de acción y acceso al workspace.
- `eolfi/security` y `tests`: resiliencia, parsers sintéticos y regresiones. `.github/workflows/ci.yml` ejecuta Python en Ubuntu, Windows y macOS, más suites Node y E2E.

Comandos principales descritos por el CLI y README: `doctor`, `triage`, `decompile`, `evidence`, `incognitas`, `resolve`, `export`, `import`, `report`, `web`, `repo`, `compare`, `diff`, `create`, `assist`, `resilience`, `bridge`, `mcp`, `serve` y `up`.

## Matriz de cobertura actual

| Clase de objetivo | Análisis estático de Eolfi | Observación de comportamiento sin fuentes | Especificación/reconstrucción | Verificación de equivalencia | Estado y límites |
|---|---|---|---|---|---|
| Nativo: PE, ELF, Mach-O | Sí, cabeceras, secciones, imports/exports y mitigaciones; Ghidra/rizin son opcionales. | Parcial: `diff` ejecuta referencia y candidato y compara salida/código de salida; no es un trazador general de procesos, archivos o llamadas. REA añade herramientas de runtime solo desde una sesión configurada y aprobada. | `create` puede inferir destino de escritorio/CLI y producir una plantilla; no recupera por sí solo todas las funciones del binario. | CLI/stdout/stderr/código de salida con corpus en `diff`; no cubre de forma general UI, estado ni efectos externos. | Parcial; no afirmar equivalencia global. |
| Gestionado: .NET y Java/JAR | Sí, metadatos, referencias, P/Invoke y estructuras disponibles según formato. | No hay trazado gestionado genérico propio documentado; REA externo es optativo. | Destinos .NET/CLI/backend y plantillas, guiadas por evidencias disponibles. | Verificación de generación compila/prueba el producto nuevo; no compara semántica frente al original automáticamente. | Parcial. |
| Android: APK/DEX y bibliotecas nativas | Sí, manifiesto, permisos, DEX, firmas y bibliotecas según proveedor. | Sin captura universal de sesiones/acciones/estado Android desde el flujo estándar de Eolfi. | Expo permite crear una app móvil nueva desde la especificación disponible. | Verificación del generado disponible según herramientas presentes; no hay equivalencia automática de app contra APK original. | Parcial; la compilación EAS/dispositivo depende del entorno/cuenta. |
| Apple: IPA/Mach-O | Sí, Info.plist, firma, entitlements y datos declarados. | Sin observación universal de una app iOS ejecutándose desde el flujo estándar. | Expo puede producir base móvil multiplataforma a partir de la especificación. | Sin comparación automatizada general de UI/estado original frente a reconstrucción. | Parcial; falta entorno Apple/dispositivo para validación real. |
| Web | Sí, HTML/CSS/JS estáticos, assets, cabeceras y pistas de pila; `fetch` limita la adquisición. | No se ejecuta todo el JavaScript del sitio en `analyze_web`; la captura dinámica de REA se ha usado para el panel de Eolfi, no valida cualquier web objetivo. | Blueprints de páginas/estilos y destinos web, con plantillas propias. | El verificador prueba el generado; no compara el comportamiento original y nuevo en todos los escenarios. | Parcial: la apariencia/base no equivale a funciones completas. |
| Repositorio con fuentes | Sí, inventario, manifiestos, lenguajes, dependencias, CI, pruebas y estructura; no ejecuta el repo analizado. | Las pruebas pueden ejecutarse explícitamente en flujos controlados, pero no es una observación de caja negra de la aplicación original. | Generación asistida por blueprint y plantillas; no es portado automático del código. | Verificación de build/pruebas del nuevo proyecto; faltan enlaces requisito→prueba y paridad automática completa. | Fuerte para inventario; parcial para reconstrucción conductual. |
| WebAssembly | Sí, secciones, imports/exports y productores disponibles en el parser. | No hay ejecución/instrumentación general de WASM en el flujo estándar. | Puede alimentar un blueprint, sin derivar toda la lógica original. | Solo las comparaciones genéricas que el usuario configure; sin comparador de interfaz WASM. | Parcial. |
| Firmware, protocolos, capturas, señales y formatos no declarados por Eolfi | Sin proveedor general de Eolfi en el flujo documentado. Algunas herramientas REA externas cubren dominios concretos. | REA puede inspeccionar capturas o runtimes si tiene proveedor/configuración compatible; cobertura no se hereda al producto Eolfi. | No hay reconstrucción integral nativa documentada para estas clases. | No hay aceptación equivalente genérica. | No soportado como flujo integral de Eolfi; no anunciarlo como tal. |

### Lectura transversal del ciclo

| Etapa | Situación actual |
|---|---|
| Identificar y analizar un artefacto | Implementado para varias familias, con evidencias e incógnitas. |
| Observar comportamiento real sin fuentes | Parcial: la comparación diferencial puede ejercitar procesos con un corpus; UI/red/estado/procesos no forman una sesión universal de análisis. |
| Especificar el comportamiento observado | Parcial: `eolfi.spec.json` y blueprints son una base para generar aplicaciones; no son aún una especificación funcional completa enlazada a cada evidencia. |
| Crear una implementación independiente | Parcial: generadores multiplataforma crean proyectos estructurados. |
| Validar el producto generado | `create_project` y los caminos públicos CLI/API/panel ejecutan `verify` obligatoriamente. Instala/restaura, compila, prueba y hace smoke según destino; la falta de toolchain genera `verification.ok=false`. `--verify` se conserva por compatibilidad y el API ignora el antiguo `verify:false`. |
| Probar equivalencia con el original | Parcial: `diff` compara stdout/stderr/código de salida con corpus; no calcula cobertura general de requisitos ni valida UI, red, persistencia y efectos en conjunto. |

## Estado de auditorías y cambios locales

- El informe de auditoría por archivo contiene una revisión histórica de 150 archivos elegibles y anexos para las incorporaciones posteriores. Su cabecera inicial de 129 archivos es antigua; el propio anexo actualiza el recuento.
- La verificación posterior de prioridades altas documenta hallazgos confirmados/corregidos, falsos positivos y decisiones aceptadas. No se reabrieron los errores ya probados como corregidos.
- El informe REA de interfaz documenta captura dinámica en Chromium del panel de Eolfi y límites de zoom/lector de pantalla. No cubre la aplicación externa general.
- Las diferencias locales actuales incluyen cambios de CLI/arranque, servidor, panel, agente VS Code/MCP, auditoría incremental, pruebas y metadatos. Se contrastaron con esos informes y las pruebas actuales. No se modificaron ni descartaron esos cambios durante esta fase.
- El estado de Git tiene 51 rutas modificadas o no rastreadas y `HEAD` es `94cf454c847b7548cecf2f13b075a6cde8aae1d4`; los informes no representan un árbol limpio/commiteado.
- El inventario REA nuevo identificó 474 archivos relevantes dentro de `eolfi/`, incluidos un ASAR anidado; leyó 11.968.280 bytes y analizó 432 JavaScript: 420 completos, 12 recuperados, 0 fallos de parseo. Evidencia REA `ev_66b4bcd343c3f3670833122fb0546b992f4297cbaca2971dec5bb7c7e827780b`; SHA-256 de la carpeta analizada `2199875e585c4c921f4a09be1b348450bb40a2ebb5ab3399816876871a98ce95`.
- REA registró 5.636 observaciones; este número no es un recuento de defectos. La cobertura semántica es parcial, alcanzó el límite de 100.000 nodos y conserva 40.320 incógnitas semánticas. Hubo una fuente embebida del Electron default_app.asar no analizada. Fue análisis estático inerte: no arrancó la aplicación ni prueba enforcement, reachability ni comportamiento.
- Una pasada enfocada anterior en `vscode-bridge` revisó estáticamente nueve archivos cambiados de 38 relevantes y no tuvo errores de parseo; se conserva como alcance parcial, no como evidencia adicional de defectos.
- `.github/workflows/ci.yml` ahora ejecuta las suites del puente y la extensión en Ubuntu, Windows y macOS; la matriz de Python ya cubría esos tres sistemas. El E2E del navegador permanece en Ubuntu.
- Pendiente de validación en VS Code real: registro MCP y herramientas en una instalación interactiva. Esto ya aparece en `SESION.md`; las pruebas de Node con un VS Code simulado no lo sustituyen.

## Corpus reproducible y procedencia

El corpus base autorizado para parsers es sintético y se genera en memoria con constructores propios del repositorio. No ejecuta las muestras. Los resultados esperados los afirman pruebas de parsers (`tests/test_formatos.py`, `tests/test_learn_and_generador.py` y relacionadas). SHA-256 calculado directamente sobre los bytes generados en Windows, Python 3.12.10:

| Fixture sintético | Constructor | Tamaño | SHA-256 | Plataforma de fixture |
|---|---|---:|---|---|
| Java `.class` | `tests/formats.py::build_class` | 175 B | `fdc8aa0428c4630839116717d716056e1e1af9920a3ed33aba8e733afea17640` | Independiente de SO |
| WebAssembly | `tests/formats.py::build_wasm` | 196 B | `6e0b8a63dbe4ba24835669d48cd62ab5fb5d807d8ae983fd5d875da93b844b74` | Independiente de SO |
| Android ELF `.so` | `tests/formats.py::build_android_so` | 608 B | `eef149e0cadbcdf7ab9d715b8743cd72c7765ec5aedac003e2173721bf9f065b` | Independiente de SO; AArch64 declarado en fixture |
| DEX | `tests/formats.py::build_dex_with_methods` | 326 B | `938ec10c1fffad79014e7a84e9774fabd3d0f6d8d998aa3bdd6d8873f32986ea` | Independiente de SO |
| iOS Mach-O | `tests/formats.py::build_ios_macho` | 1.428 B | `fda790f65c86e55031239c0841f5a83ee7b8d99865bbc0462e5a0b9ac27a11f4` | Independiente de SO; ARM64 declarado en fixture |
| Mach-O | `tests/fixtures.py::build_macho64` | 1.024 B | `2f78a314bbcc3a81865743f8897e44370da43d051ea23d995fed9fa44d2a5e3b` | Independiente de SO |

Los resultados observados al regenerar estos seis fixtures se comparan con estos hashes. `samples/` contiene además dos semillas binarias de 128/256 bytes y `samples/apk/F-Droid.apk` (12.569.951 bytes, SHA-256 `19d51fad482239f6df6a99120e34513667e9a86d136dafdc4a211a68c3327b52`). Son datos locales ignorados por Git. El origen/licencia del APK no figura en su índice y se excluye de validación/reconstrucción hasta documentar su autorización. `samples/index.json` hace referencia a elementos locales que no están presentes; no es todavía un manifiesto fiable del corpus dinámico.

## Validación del cierre

Ejecución local en Windows, Python 3.12.10 y Node 24.22.1:

- `python -m pytest -q` (usando la ruta directa al Python 3.12 porque el alias `python` de Windows está roto): **317 aprobadas, 2 omitidas**.
- `node --test` en `eolfi/bridge`: **50 aprobadas, 1 omitida** (requiere navegador real).
- `node --test` en `eolfi/vscode-bridge`: **122 aprobadas**.
- `npm test` en `tests/e2e`: **11 aprobadas**, incluida la prueba de accesibilidad axe.
- La primera pasada dentro del sandbox no pudo crear temporales ni enlazar servidores loopback (`EACCES`) y Playwright devolvió `ERR_NETWORK_ACCESS_DENIED`. Se repitió con permisos locales; las cuatro suites terminaron bien. La limitación de sandbox no se atribuye al producto.
- Esta validación no ejecutó builders de los 13 destinos ni probó REA en todos los formatos. La matriz separa esos límites.

## Brechas priorizadas para la siguiente fase

1. Ampliar las verificaciones por destino con comprobaciones de smoke/conducta que falten y confirmar la matriz multiplataforma en CI remoto; la exigencia de verificación ya se aplica en CLI/API/panel.
2. Unificar el caso persistente y asociar versiones/artefactos, escenarios, evidencias, especificación y pruebas.
3. Añadir observación reproducible de caja negra de procesos, UI, red autorizada y estado, más allá de `diff` de salida.
4. Elevar los blueprints a especificaciones conductuales versionadas y trazables.
5. Extender la equivalencia a resultados estructurados, UI y estado persistente.
6. Registrar una muestra propia autorizada para pruebas dinámicas reales. El corpus sintético actual solo cubre parsers.
7. Añadir e2e de VS Code real y confirmar en CI remoto Node/extensión en Windows/macOS además de Linux.
