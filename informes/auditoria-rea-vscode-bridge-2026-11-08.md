# Auditoría e implementación de mejoras REA — 2026-11-08

## Alcance y método

Se inspeccionó el cliente MCP REA de `eolfi/vscode-bridge` y sus flujos de configuración, aprobación y llamadas. Se ejecutó `analyze_javascript_application` sobre `D:\Eolfi\eolfi\vscode-bridge`, formato `directory`, detalle `summary`. La operación fue estática: no ejecutó el JavaScript objetivo ni inició sesiones de depuración.

- SHA-256 del objetivo al analizarlo: `dea0affa6e683a8beeead52b2d405f5ed165b8c55627558fc693b2cae0f393c4`.
- Proveedor de análisis: REA, vista `rea-analysis-view` 1; evidencia de análisis padre `ev_be470dd914c62ab4e3aba7299ae222e68b19074fbe1f9abdecd1b11fd8415836`; vista resumen `ev_75677b577772568a819878a267096a05e52009c572a41d3f5f3cb0b940b4ffdb`.
- Plataforma/ruta observada: Windows, `D:\Eolfi\eolfi\vscode-bridge`.
- Cobertura: 42 archivos relevantes inventariados; 41 archivos JavaScript analizados, 68.725 nodos AST visitados, cero omisiones por parseo y cero fallos de parseo. La vista resume 424 elementos.
- Límites de REA: aplicación parcial, semántica desconocida, 16.378 incógnitas semánticas. No se interpretan los 612 hallazgos como defectos. Análisis inerte, sin prueba de ejecución ni cobertura de comportamiento dinámico.

## Hallazgos y cambios

### Prioridad alta — acumulación de stdout sin límite

**Evidencia:** `eolfi/vscode-bridge/rea.js:70-71` acumula los fragmentos de stdout hasta encontrar `\n`. El protocolo está orientado a líneas; un servidor defectuoso o hostil que no envíe el terminador podía hacer crecer `buf` sin límite y agotar memoria.

**Cambio:** límite de 1 MiB por trama. Si la línea excede el límite, el cliente registra el evento y cierra el proceso MCP; la gestión de salida existente rechaza solicitudes pendientes. Se aplica tanto a una trama incompleta como a una línea completa demasiado grande.

**Prueba:** prueba focalizada envía una trama sin salto de línea de más de 1 MiB y confirma que se rechaza la solicitud al cerrar el proceso.

### Prioridad media — errores de escritura a stdin

**Evidencia:** la llamada `stdin.write` no tenía callback ni captura de excepción (`rea.js`, antes de `request`). Si el pipe estaba cerrado, la excepción podía escapar y dejar la solicitud sin resolver hasta el timeout.

**Cambio:** se propaga el error del callback, se retira la solicitud pendiente y se cancela su temporizador; también se limpia el estado si `write` lanza sincrónicamente.

**Prueba:** callback de escritura simulado con `pipe cerrado`, verificado como rechazo inmediato.

## Verificación

- `node --test test/rea.test.js` en `eolfi/vscode-bridge`: 6 aprobadas, 0 fallidas.
- `node --test` en `eolfi/vscode-bridge`, primera pasada sandbox: 141 aprobadas y 5 fallos por `EACCES` en conexiones loopback de puertos temporales.
- Repetición del mismo `node --test` con ejecución local autorizada por el mecanismo del entorno: 146 aprobadas, 0 fallidas.
- SHA-256 posterior del archivo cambiado `rea.js`: `88a6075b2f549d7df1e48bd8df788133b89ca5e3fcd973dc97433495a63d13fc`.

## Pendiente / no verificado

La cobertura dinámica de REA sigue `NO VERIFICADO`: no se ejecutó el servidor REA de usuario ni el binario objetivo, y el análisis estático declara 16.378 incógnitas. No se revisaron individualmente los 612 hallazgos resumidos; su detalle no estaba en la vista resumen. La suite general de Python, bridge, E2E y compatibilidad funcional completa queda fuera de esta corrección acotada.

## Seguimiento — 8 de noviembre de 2026

### REA y ejecución dinámica

Se repitió REA después del cambio del cliente MCP y se hizo una pasada acotada con `source_paths=["rea.js","test/rea.test.js"]`.

- Objetivo completo: SHA-256 `5e6514aeb1ee20e85089880b893b8de0405f5f228c1fa991bb65cf01e3d804da`; proveedor `REA JavaScript application analyzer` 1.
- Alcance acotado: 2 archivos, 14.443 bytes, 2.507 nodos AST, 37 observaciones etiquetadas como hallazgos, cero errores de parseo. Los 40 archivos restantes quedaron expresamente fuera de esa selección.
- Cobertura: fuentes seleccionadas completas sintácticamente; grafo de aplicación parcial y semántica parcial con 1.108 incógnitas. REA advierte que no ejecuta JavaScript, que sus relaciones son candidatos estáticos y que el flujo de datos no resuelve alias dinámicos ni control de flujo general.
- La cifra “hallazgos” es la cantidad de observaciones que REA emite; no es un conjunto de defectos confirmados. No hay base para corregir 37/612 elementos individualmente como bugs sin inspeccionar la observación concreta y reproducirla.
- Se intentó ejecutar `capture_process_scenario` sobre la prueba del cliente. REA lo rechazó con `capability_unavailable`: su PTY de Windows no acredita limpieza de procesos descendientes. No se cambió ni reinstaló el proveedor.
- Ejecución local dinámica ya completada: `node --test` en `eolfi/vscode-bridge`, 146 aprobadas, 0 fallidas. Cubre las pruebas del puente, no todos los flujos posibles del producto ni sustituye la captura REA.

Por tanto, el estado global de cobertura REA continúa **NO VERIFICADO como completo**. La ejecución de pruebas sí verifica los escenarios cubiertos; las incógnitas semánticas permanecen abiertas hasta que exista una prueba o evidencia específica que las resuelva. No se marcaron como resueltas artificialmente.

### Progreso de hoja de ruta — Fase 4

`build_model` ahora incluye `requirements` y `evidence_ids` en cada decisión, para que el motivo de reconstrucción tenga trazabilidad hasta la especificación observada. La prueba `test_model_is_independent_and_explains_decisions` comprueba que los enlaces existen y pertenecen a las evidencias de requisitos. Validación focalizada con Python 3.12.10 (`C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`): 1 aprobada, código 0. La suite completa `tests/test_reconstruct.py` pasó después de repetir con seguimiento del proceso: 11 aprobadas, código 0 (Python 3.12.10). En el primer intento el proceso seguía activo tras 30 s; se esperó su salida final.

La aceptación de Fase 4 permanece abierta: el generador todavía se limita a CLI observada y declara como pendientes los efectos que no puede reproducir.


### Verificación final de esta iteración

- `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q`: **455 passed, 2 skipped**, código 0 (228,72 s). Primer recorrido: 454 pasaron y falló `test_proveedor_gemma`; se determinó que la prueba conservaba el contrato anterior de llama.cpp mientras el cambio local de `gemma` ya lo dirigía a Eolas. Se actualizó la prueba para exigir el contrato `/api/chat` de Eolas y que no arranque llama.cpp; `tests/test_llamacpp.py`: 2/2 y repetición completa: 455/2 omitidas.
- `node --test` en `eolfi/bridge`: **50 aprobadas, 1 omitida**, código 0. El primer intento sin permiso local se bloqueó/no progresó por pruebas HTTP locales; la repetición autorizada pasó.
- `node --test` en `eolfi/vscode-bridge`: **146 aprobadas**, código 0.
- `npm test` en `tests/e2e`: **18 aprobadas**, código 0; dependencias ya instaladas, sin instalar paquetes.
- REA `capture_process_scenario` sigue no disponible en Windows por la limitación reportada del PTY. Las pruebas anteriores son ejecución dinámica en Node/Playwright, no una captura de procesos emitida por REA.

Las incógnitas semánticas REA y la aceptación final de Fase 4 siguen abiertas; esta iteración mejora trazabilidad, pero no amplía el generador a APIs, archivos, UI ni casos no observados.

### REA — análisis completo del árbol actual (2026-11-08)

Se volvió a analizar estáticamente `D:\Eolfi\eolfi\vscode-bridge` como `directory`, `detail=summary`, después de los cambios de esta iteración. El SHA-256 informado para el árbol objetivo es `f26ee654313cd467a4740e5c35684171c6bbcd08511537031fd0ffbf3d1d2c68`. Evidencia de análisis padre: `ev_63b1f70e0bf9be2f679f05934375185443a8dbe4742c954bd4e44b6cca24bb6b`; vista resumen: `ev_2f1b9772974185ca8e2dd25e183eef9c9f6349a8350032d8ab916c7b23209870`.

- 42 archivos relevantes inventariados; 41/41 JavaScript parseados; 69.062 nodos AST visitados; cero fallos/omisiones de parseo.
- El grafo de aplicación es `partial`; la cobertura semántica es `unknown`, con 16.474 incógnitas. 13 fuentes tienen semántica desconocida y las 41 entradas tienen aplicabilidad Electron desconocida. Los 617 hallazgos son observaciones, no defectos confirmados.
- El análisis leyó las fuentes como texto inerte y no ejecutó bootstrap ni aplicación. Persisten límites en flujo de datos con control de flujo, propiedades dinámicas, resolución de rutas/imports y relaciones de ejecución. La cobertura dinámica REA permanece **NO VERIFICADO**.

### Captura/reconstrucción — revisión de seguridad (2026-11-08)

La revisión encontró que se rechazaba un enlace simbólico en el archivo final, pero no se examinaban los directorios intermedios. Se ajustó `capture_file_contents` para rechazar enlaces y reparse points en cada componente antes de abrir el archivo. Se añadió una prueba que crea una junction de directorio Windows apuntando fuera de la raíz declarada y confirma que la captura devuelve `symlink_not_captured` sin leer el archivo externo. Validación focalizada: 3 aprobadas, 0 omitidas. Esta protección reduce el riesgo de escape por enlaces; no convierte el subproceso del objetivo en un sandbox de seguridad.

### REA tras el ajuste del límite UTF-8

Se repitió el análisis acotado sobre el árbol final de esta iteración. SHA-256 de la carpeta objetivo: `5389a95e1613691d71d7efcf3af6419682024a9b6dc68c2cd948ccadd804e7b2`; evidencia `ev_21f6e31430a27ba097e1130a334eca833415b8de823e2794e2e29af4bb65f1cb`. Dos fuentes seleccionadas, 2.529 nodos AST, 37 observaciones y cero errores de parseo. La cobertura del grafo sigue parcial: 1.113 incógnitas semánticas y 40 fuentes fuera de la selección. No se atribuye a ellas condición de defecto.

Verificación final después del cambio de límite: `node --test` en `eolfi/vscode-bridge` volvió a pasar 146/146; `pytest -q` pasó 455 con 2 omitidas; `node --test` en `eolfi/bridge` pasó 50 con 1 omitida; `npm test` en `tests/e2e` pasó 18/18. Todos los comandos terminaron con código 0.
