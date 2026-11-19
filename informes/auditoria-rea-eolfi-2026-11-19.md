# Auditoría de REA en Eolfi y plan de cierre

19 de noviembre de 2026 · Luis · Base Git `83964ee` · Windows, Python 3.12.10 y Node 24.22.1.

## Hallazgos reproducidos y correcciones

| Prioridad | Hallazgo | Cambio y criterio comprobado |
| --- | --- | --- |
| Alta | `python -m eolfi rea app-js eolfi/web` salía con código 1. El cliente enviaba `input_path` relativo y REA requería una ruta absoluta. | La operación compartida de CLI y chat resuelve la ruta para el proveedor y conserva el argumento original en el informe. La regresión prueba ambas representaciones. El mismo comando salió con código 0 con REA real. |
| Media | El lector Python dejaba a la petición esperando todo su plazo si el proveedor cerraba stdout. El constructor dejaba la limpieza pendiente si fallaba la negociación. | El lector comunica el cierre, el constructor cierra el proceso al fallar y cada petición usa un presupuesto monotónico para esperar respuestas. La prueba inicia un proceso de prueba que cierra stdout durante la negociación. |
| Media | Dos llamadas simultáneas podían consumir respuestas de la misma cola y descartar las destinadas a la otra petición. | Python serializa el intercambio en una sesión. La prueba llama 12 operaciones con cuatro hilos y comprueba todas las respuestas. |
| Media | Los dos clientes podían repetir indefinidamente `tools/list` si el proveedor devolvía siempre el mismo cursor. | Ambos detectan la repetición y devuelven un error. VS Code permite volver a pedir el catálogo después del fallo. |

La ruta estática de autorizaciones del panel se cotejó con los tres manejadores del servidor. Coinciden el listado, la decisión y la revocación. La comprobación HTTP en vivo queda pendiente.

## Evidencia REA

El cliente MCP de Python obtuvo 229 herramientas de `rea-agents 6.8.0`. La inspección utilizó `analyze_javascript_application` con `detail=summary`. El proveedor conserva el análisis detallado en la sesión y la salida revisada es su resumen.

| Objetivo | SHA-256 de la raíz según REA | Evidencia | Cobertura y trabajo pendiente |
| --- | --- | --- | --- |
| `eolfi/web` | `1703244a21b2f177b6747b70f838d710179259c93cf9c57a0b9234840828d078` | `ev_37450c5723e3f05d738e267dd2265a45f2ce15c65b949d89bbf5d062ebcb0187` | 12 archivos relevantes, 10 JavaScript analizados, 0 fallos de lectura, aplicación parcial y semántica desconocida. Quedan 7.403 incógnitas semánticas. |
| `eolfi/vscode-bridge` con `source_paths` igual a `["rea.js", "test/rea.test.js"]` | `f7875a541c3753b406f40063985f0d76be1374020366849b05d0121d01743d05` | `ev_7c0837bbfeb9804d8ef0a9d608634a96e6385710946cfa9f7d2907ff2f85f4cf` | 65 archivos inventariados, 2 analizados, 0 fallos de lectura, ambas coberturas parciales. Quedan 63 archivos fuera de selección, 63 incógnitas de aplicación y 1.412 semánticas. |

SHA-256 de los archivos seleccionados del puente: `95380ac2b96846c750293a460b69e9e22db7d9e52b60210f926811f1428e4ba7` para `rea.js` y `c5eb7ba0d080e3a82f68aee3d1bde8d4d2a039f888aa0b3dcdde6716f353931d` para su prueba. REA entregó 124 observaciones en el panel y 37 en el puente. Los recuentos corresponden al análisis estático y la reproducción en ejecución decide cuáles son defectos. El resumen no cuantificó truncamientos adicionales al alcance y cobertura indicados.

## Comprobaciones

| Comando o inspección | Resultado |
| --- | --- |
| `python -m pytest -q tests/test_rea_client.py tests/test_rea_compuestas.py tests/test_rea_autorizacion.py tests/test_rea_caso.py tests/test_rea_paquete.py tests/test_rea_unity.py` | 121 aprobadas. |
| `node --test test/rea.test.js` en `eolfi/vscode-bridge` | 7 aprobadas. |
| `node --test` en `eolfi/vscode-bridge` | 6 fallos por `EACCES` al conectar con `127.0.0.1`. |
| `python -m pytest -q` y diagnóstico `python -m pytest -q -x` | NO VERIFICADO. La suite completa se interrumpió tras acumular fallos. El diagnóstico terminó con 62 aprobadas y un fallo `WinError 10013` en la conexión de prueba de Eolas a loopback. |
| `node --test` en `eolfi/bridge` | NO VERIFICADO. Se interrumpió después de observar fallos en pruebas HTTP locales. |
| `npm.cmd test` en `tests/e2e` | NO VERIFICADO. 0 de 28 aprobadas. El panel no llegó a responder a la comprobación de arranque. |
| `git diff --check` | Sin errores de espacios en el parche. |
| Enlaces Markdown y HTML | Cero destinos inexistentes en enlaces relativos con sintaxis directa, sin espacios ni paréntesis, de los 77 Markdown rastreados al inicio. El parser de HTML tampoco detectó destinos locales ausentes en atributos literales relativos `src`, `href` o `poster` de los 7 HTML rastreados. Pendientes anclas, referencias, rutas absolutas servidas, diferencias de caja y destinos externos. |
| Duplicación exacta | SHA-256 de fuentes `.py`, `.js`, `.mjs`, `.css` y `.html` rastreadas: sólo coincidencias entre siete `__init__.py` vacíos. Comparación de cuerpos AST de funciones Python de nueve líneas o más en `eolfi/`: sin coincidencias exactas. Quedan similitud parcial y responsabilidades duplicadas. |

La política de aprobación del entorno rechazó el reintento con permisos elevados para las suites de Python, los puentes y e2e. El CLI tampoco pudo escribir el registro RSI bajo el perfil local, aunque el análisis del panel devolvió código 0. La prueba del puente se hizo por MCP mediante el cliente del repositorio porque la herramienta acepta un directorio o ASAR y rechaza un archivo JS suelto.

## Procedimiento de cierre, por orden

| Paso | Procedimiento | Criterio de aceptación |
| --- | --- | --- |
| 1. Validación base | En la copia real con loopback disponible, ejecutar los cuatro comandos de AGENTS.md. Revisar los primeros errores con su causa y repetir por archivo. Registrar versión de Python, Node y navegador, código de salida y recuentos. Comparar contra la misma revisión base y conservar los cambios previos del titular. | Las cuatro suites tienen un resultado reproducible o un bloqueo identificado por prueba. |
| 2. Contratos REA | Inventariar `tools/list` por proveedor y versión. Cruzar `required`, tipo y formato de los argumentos con las llamadas de `rea_compuestas.py`, las herramientas de chat y el cliente del puente. Validar primero una muestra estática propia por contrato. Probar ruta relativa, absoluta, con espacios, ausente, directorio y ASAR donde corresponda. | Cada operación estática tiene contrato, ruta pública, muestra, salida y regresión; cualquier proveedor ausente queda como NO VERIFICADO. |
| 3. Integración panel, CLI y chat | Seguir cada acción desde su control hasta el manejador y desde éste al proveedor. Comprobar listado, denegación, autorización, revocación, persistencia del caso, mensajes de error y auditoría RSI con datos de prueba. Ejecutar escenarios de sólo lectura donde la cobertura lo requiera. | Se comprueban HTTP, estado de UI y persistencia. Cada conexión dinámica ausente tiene un caso reproducible. |
| 4. Incógnitas REA | En una misma sesión conservar la evidencia por raíz SHA-256. Paginar vistas por archivo y familia, incluyendo rutas y límites de salida. Priorizar referencias sin resolver que cruzan módulos, red, configuración y ciclo de vida. Cotejar cada candidato con la fuente y una prueba dirigida. Ampliar la selección del puente a los módulos funcionales restantes. | Cada candidato dispone de evidencia, reproducción, impacto y estado. Registrar incógnitas y truncamientos residuales con recuento. |
| 5. Enlaces y recursos | Extraer enlaces con un parser de Markdown y HTML. Resolver referencias y anclas, cotejar rutas con el inventario Git respetando mayúsculas y comprobar recursos servidos por el panel. Revisar destinos externos cuando pueda consultarse el host. | Cada fallo identifica origen, destino, condición y prueba posterior. Los destinos inaccesibles quedan como NO VERIFICADO. |
| 6. Duplicación y mantenimiento | Comparar bloques normalizados y responsabilidades que comparten Python y JavaScript. Revisar las diferencias de configuración, protocolo, límites y ciclo de vida antes de proponer una extracción. Anotar archivos históricos, copias y temporales en el registro con su dependencia y evidencia. | Fusionar únicamente lógica cuyos consumidores y comportamiento estén cubiertos. Conservar candidatos hasta la revisión prevista en AGENTS.md. |
| 7. Entrega | Repetir las pruebas afectadas, las cuatro suites y el análisis REA de los archivos JS modificados. Revisar `git diff --check`, el alcance del diff y el mantenimiento del estado previo del titular. | Publicar el resultado por punto con comandos, códigos de salida, evidencia y todos los límites restantes. |

La cobertura global de repositorio y los recorridos dinámicos siguen **NO VERIFICADOS**.

Los candidatos de mantenimiento encontrados durante esta ronda están en el [registro de limpieza](../REGISTRO_LIMPIEZA.md).

## Segunda ronda de correcciones y comprobaciones

- **Go y Rust.** Con REA 6.8.0 en Windows, `inspect_go_binary` e `inspect_rust_binary` devolvieron `invalid_request` con una ruta relativa y aceptaron la ruta absoluta del mismo PE de prueba. Los dos adaptadores ahora envían la ruta resuelta al proveedor y conservan el nombre proporcionado en el resultado. Las regresiones cubren el nombre relativo con espacios.
- **Prueba con REA real.** Los comandos públicos `python -m eolfi rea go "fixture con espacios.exe"` y `python -m eolfi rea rust "fixture con espacios.exe"` terminaron con código 0. El PE sintético tiene SHA-256 `19584ebdb6c16ddfe939bc38533b87c01d0dafc8dccab0bf50247ba984730c16`. Alcance: selección del archivo e identificación PE sin ejecutar el objetivo. El fixture carece de metadatos Go y cargo-auditable, así que la extracción real de esos metadatos queda pendiente.
- **Capturas.** `python -m eolfi rea api "captura con espacios.pcap"` terminó con código 0 y devolvió 12 paquetes en el nivel básico. SHA-256 `a0c3dd5f676bc44567a84c21059aa9c0f3f18879f4a6abc534ab09ea2077adce`, muestra local sintética. El proveedor nativo devolvió `capability_unavailable` al pedir campos. El modo completo con tshark en WSL sigue NO VERIFICADO.
- **Esquemas.** Comparé 45 llamadas con herramienta y claves declaradas literalmente en `rea_compuestas.py` con los 229 esquemas devueltos por REA. Validé 18 argumentos literales con JSON Schema. Sin discrepancias en ese subconjunto. El cruce no cubre argumentos construidos en ejecución ni dependencias de otros proveedores.
- **Navegación.** El parser CommonMark examinó 72 enlaces o recursos en 78 documentos, incluido este informe. Los destinos locales de ese conjunto existen y las anclas Markdown comprobadas coinciden. Abrí los seis destinos web únicos encontrados por el parser, de GitHub, Hugging Face y Microsoft Learn. Las URL que aparecen como ejemplos de texto o código quedaron fuera. En el panel cotejé 5 recursos HTML, 7 destinos únicos de importaciones relativas, 3 rutas de exportación, 9 anclas y 15 entradas del mapa de recursos del servidor. La inspección estática encontró sus destinos. La navegación en navegador queda NO VERIFICADA.
- **Regresiones.** Las 7 pruebas REA de VS Code pasaron. La ejecución de las pruebas REA junto con `tests/test_cliente_api.py` terminó con 126 aprobadas y un fallo al conectar con la API de prueba por `WinError 10013`. El diagnóstico del conjunto Python `python -m pytest -q -x --tb=short` llegó a 62 aprobadas y reprodujo el mismo código en la primera integración HTTP.
- **Bloqueo de entorno.** Un socket de prueba de Python en `127.0.0.1` enlazó y escuchó, pero la conexión fue rechazada con `WinError 10013`. `wsl.exe --status`, `wsl.exe --list --verbose` y el intento de abrir un shell devolvieron código 1 y `Wsl/E_ACCESSDENIED`. La herramienta rechazó la elevación en ambos casos. Para cerrar las suites en cada plataforma, el primer criterio es que el sondeo de loopback funcione en ese entorno. Después se ejecutan los cuatro comandos de AGENTS.md en la copia real y se registra cada código de salida.

## Entorno de validación preparado

- Creé `D:\Eolfi\.venv\auditoria` mediante `python -m venv --system-site-packages --without-pip`. Reutiliza Python 3.12.10 y pytest 9.1.1 ya instalados. El módulo `eolfi` se importa desde `D:\Eolfi\eolfi`, la copia de trabajo real. Las 121 pruebas específicas de REA pasaron en este entorno.
- En `tests/e2e` se resolvieron Node 24.22.1, Playwright Core 1.64.1 y axe-core 4.14.0. Chrome 157.0.8103.52 está instalado. Estos datos acreditan disponibilidad de dependencias. El sondeo de loopback desde el Python nuevo volvió a dar `WinError 10013` antes de iniciar las suites HTTP.
- Docker 29.7.2 está instalado como cliente. `docker desktop start --timeout 35` falló inicialmente por una clave de registro ausente. Tras arrancar Docker Desktop, `docker version` y `docker info` devolvieron `permission denied` en `npipe:////./pipe/dockerDesktopLinuxEngine`. La herramienta rechazó la elevación para acceder al motor desde esta sesión. `wsl.exe --list --verbose` reprodujo `Wsl/E_ACCESSDENIED`.
- Actualicé `scripts/codex-entorno.sh` para aprovisionar el navegador propio que usa la CI, propagar fallos de instalación y comprobar loopback antes de anunciar disponibilidad. Ejecuté el bloque de diagnóstico del propio script y salió con código 1 y `NO VERIFICADO` en este host. Git Bash no llegó a ejecutar `bash -n` y devolvió `0xC0000142`. El aprovisionamiento completo de ese script queda **NO VERIFICADO** en un runner Bash.

## Código adjunto e índice de cambios

[Parche completo de las correcciones y sus pruebas](auditoria-rea-eolfi-2026-11-19-correcciones.patch), sobre `83964ee`. SHA-256 `bc004a32ee5f92925bf9b13179fc571ac830cc1dd6fa0700e9ff317c69614c54`. El parche cubre siete archivos de código, pruebas y aprovisionamiento. `git apply --check --reverse` devolvió código 0 sobre la copia de trabajo, confirmando que corresponde a los cambios presentes. Los cambios locales de voz y el registro documental quedan fuera del parche de código.

| Etiqueta | Código | Prueba o comprobación |
| --- | --- | --- |
| REA-01 · Ruta de aplicación JS | [`analizar_app_js` en rea_compuestas.py](../eolfi/rea_compuestas.py) | [Prueba de ruta relativa y salida](../tests/test_rea_compuestas.py). CLI con REA real sobre el panel. |
| REA-02 · Transporte Python | [`ReaClient` en rea_client.py](../eolfi/rea_client.py) | [Pruebas de concurrencia, negociación y proceso cerrado](../tests/test_rea_client.py). |
| REA-03 · Paginación MCP | [Cliente Python](../eolfi/rea_client.py) y [cliente VS Code](../eolfi/vscode-bridge/rea.js) | [Prueba Python de cursor repetido](../tests/test_rea_client.py) y [prueba de reintento en VS Code](../eolfi/vscode-bridge/test/rea.test.js). |
| REA-04 · Rutas de binarios Go y Rust | [`binario_go` y `binario_rust` en rea_compuestas.py](../eolfi/rea_compuestas.py) | [Pruebas de rutas relativas con espacios](../tests/test_rea_compuestas.py). Ambos comandos públicos pasaron con el PE sintético y REA real. |
| ENV-01 · Entorno de validación | [codex-entorno.sh](../scripts/codex-entorno.sh) | Diagnóstico de loopback comprobado. Aprovisionamiento completo NO VERIFICADO en Bash. |

## Última ronda de comprobaciones

**REA-02.** El primer error al recibir el cierre de stdout consumía la señal de cierre. El cliente ahora conserva ese estado durante la sesión y el reintento da el mismo diagnóstico sin volver a enviar datos ni agotar el plazo. La prueba lanza un proceso MCP de prueba que negocia la sesión y termina al leer la primera consulta. Se verifican ambos intentos.

| Comprobación | Resultado |
| --- | --- |
| `python -m pytest -q tests/test_rea_client.py tests/test_rea_compuestas.py tests/test_rea_autorizacion.py tests/test_rea_caso.py tests/test_rea_paquete.py tests/test_rea_unity.py` con `.venv/auditoria` | 122 aprobadas, código 0. |
| `node --test test/adapters.test.mjs test/engine-concurrency.test.mjs test/meta-hidden-lines.test.mjs test/policy.test.mjs` en `eolfi/bridge` | 25 aprobadas, código 0. |
| La misma selección del puente añadiendo `test/fase-b.test.mjs` | 25 aprobadas, 4 fallos, código 1. Tres conexiones de prueba dieron `EACCES` en loopback. La cuarta registró conexión cortada y no pudo comprobar el HTTP 413. |
| `node --test test/rea.test.js` en `eolfi/vscode-bridge` | 7 aprobadas, código 0. |
| `git diff --check` | Código 0. Git avisó de su conversión de finales de línea al volver a tocar los archivos correspondientes. |

**Vista de rutas del panel con REA.** Con REA 6.8.0 en Windows, ejecuté `analyze_javascript_application` sobre la raíz del panel del apartado de evidencias y consulté `inspect_analysis_view` en esa misma sesión. En `javascript-routes` se consultaron `summary`, `routes`, `occurrences`, `sources` y `unknowns`. Las colecciones paginadas se agotaron sin recorte de bytes. La vista analizó 10 fuentes, enumeró cero patrones y cero ocurrencias y registró cuatro lagunas. Digest de la vista resumen `5b62468f9cb76472d24974c16b516fdcdead154ca984c050896a398391652537`. REA marcó la enumeración como parcial y el conjunto de rutas como desconocido. La comparación de anclas, importaciones y manejadores documentada arriba sigue siendo la evidencia estática disponible para el enrutador del panel. Su alcance en navegador y por HTTP queda NO VERIFICADO.

### Repetición del cierre en un entorno habilitado

1. Confirmar que el entorno tiene acceso al checkout con los cambios de esta auditoría. Si se prepara un checkout limpio del mismo `83964ee`, revisar el parche con `git apply --check` antes de aplicarlo. En la copia actual se comprobó en sentido inverso porque los cambios ya están presentes.
2. Comprobar el acceso al motor Docker si se usa un contenedor y ejecutar dentro del entorno el sondeo de loopback de [codex-entorno.sh](../scripts/codex-entorno.sh). Registrar plataforma, versión de Python, Node y navegador, y el código de salida.
3. Desde la raíz ejecutar `python -m pytest -q`. Desde `eolfi/bridge` y `eolfi/vscode-bridge`, ejecutar por separado `node --test`. Desde `tests/e2e`, ejecutar `npm test`. Conservar stdout, stderr y el estado de cada ejecución.
4. Ante un fallo, registrar la primera reproducción aislada y distinguir un bloqueo del entorno de una respuesta errónea del producto. Repetir la prueba dirigida tras corregirla y volver a pasar la suite pertinente. La cobertura completa sigue NO VERIFICADA hasta obtener los cuatro resultados.
