# Mejoras de interfaz y auditoría REA — 6 de noviembre de 2026

## Resumen

Se reorganizó el panel lateral del frontend en tres pestañas: **Analizar**, **Objetivos** y **Crear proyecto**. El selector de fuente (Binario, Web, Repositorio) permanece dentro de Analizar. La lista compacta de proveedores queda plegada allí, mientras que la vista Proveedores del menú superior conserva sus opciones completas.

REA analizó estáticamente `eolfi/web` como directorio JavaScript. La inspección encontró dos archivos JavaScript parseados, 10.815 nodos AST visitados, 64 hallazgos y cero fallos de parseo. La cobertura semántica quedó incompleta: REA registró 2.590 incógnitas y marcó la cobertura de aplicación como parcial y la semántica como desconocida. Estos datos describen cobertura del análisis, no 64 defectos ni una evaluación de calidad.

## Cambios aplicados

- Se consolidaron las cuatro tarjetas laterales en un solo panel con navegación por pestañas.
- Cada panel usa `role="tab"` y `role="tabpanel"`, relaciones `aria-controls`/`aria-labelledby` y selección anunciada mediante `aria-selected`.
- Se añadieron controles de teclado con flechas izquierda/derecha y teclas Inicio/Fin, además de foco visible.
- Se mantuvieron los identificadores DOM existentes de formularios, objetivos, proveedores, comparación y análisis para conservar sus integraciones con el código actual.
- La disponibilidad de proveedores dejó de ocupar una tarjeta fija; ahora está plegada y se puede desplegar en Analizar.
- Se estrechó ligeramente la columna lateral y se mantuvo su adaptación móvil existente.
- En anchos de 360 px o menos, la navegación principal se distribuye en dos filas y el nombre del proyecto y la tecnología se apilan para que los controles no se compriman. Se simplificó el placeholder del nombre; el nombre accesible completo se conserva.
- La pestaña lateral elegida se guarda en `localStorage` (`eolfi.panel`) y se restaura tras recargar. Un valor inválido usa Analizar; un fallo de almacenamiento no bloquea el cambio de pestaña.
- Los errores se anuncian en una alerta accesible bajo las pestañas y permanecen visibles al cambiar de panel. El mensaje del análisis también queda junto al formulario que lo originó.
- Objetivos ahora ofrece búsqueda por nombre/formato y filtros por formato e incógnitas abiertas, con un contador anunciado de resultados.
- El formulario de creación deja visibles fuentes, tecnología, destino y la opción «instalar, compilar y probar». La petición y proveedor de IA, y las opciones de base de datos, inicio de sesión, reanálisis y modelo/URL personalizados, quedan en dos bloques plegables.

## Ejecución de REA

1. La consulta inicial de documentos activos respondió `target_unavailable` porque no había una aplicación abierta. No se abrió un ejecutable ni se inició una sesión de depuración.
2. Se ejecutó `analyze_javascript_application` sobre `D:\Eolfi\eolfi\web`, formato `directory`, con salida resumida. Una primera llamada fue rechazada porque `format=javascript` no pertenece al esquema; se corrigió a `format=directory` y la segunda llamada finalizó correctamente.
3. Identidad observada del directorio: SHA-256 `6ba70975f284905bef9ffa8017d19faaf01853b0014e1657308fc890c153b1ed`.
4. Cobertura observada: 49 elementos disponibles en la vista resumen; 3 archivos relevantes; 80.763 bytes de texto; 2 archivos JS analizados; 0 omitidos por error de parseo; 64 hallazgos; 2.590 incógnitas semánticas.
5. Límites declarados por REA: el análisis fue inerte y estático, no ejecutó el JavaScript ni el arranque del navegador, no demuestra rutas o relaciones dinámicas, y la cobertura semántica del grafo quedó como `unknown`.

## Mejoras recomendadas

### Prioridad alta

1. **Verificación visual responsive (parcialmente completada).** Se revisó mediante Chromium controlado por REA en 320×720, 390×844, 640×900, 768×1024, 1024×768 y 1440×900. 640 px sirve como aproximación del espacio CSS disponible con zoom de escritorio alto, pero no se cambió el zoom real del navegador. Las tres vistas permanecen legibles; Crear proyecto y el área de detalle conservan espacio. En 320 px se apilan Nombre/Tecnología y la navegación principal usa dos filas; se activó «Trabajos» con la navegación visible en ese ancho.
2. **Prueba de teclado y lector de pantalla (parcialmente completada).** Se comprobó Flecha derecha, Fin e Inicio entre las pestañas y el estado `selected`/`tabpanel` en el árbol accesible de Chromium. También se confirmó que Tab desde el panel lleva a «Añadir carpeta» y el Tab siguiente a Fuentes, ambos con foco visible. Falta una prueba con lector de pantalla real y zoom de navegador real.
3. **Errores del análisis visibles junto al contexto (implementado y verificado).** Los fallos aparecen en `#workspace-alert`, debajo de las pestañas, y en el estado del panel Analizar; el aviso persiste aunque se abra Objetivos o Crear. Una ruta inexistente generó el mensaje esperado y el árbol accesible la anunció como alerta (`ev_8f70b02b8cc2977a544fc35fa31d40fa9e113c01e97fb12add47d1a66fa12bcb`).

### Prioridad media

4. **Persistir la última pestaña lateral (implementado y verificado).** Guarda Analizar/Objetivos/Crear en `localStorage` con la clave `eolfi.panel`; valores inválidos vuelven a Analizar y los errores de almacenamiento no impiden cambiar pestañas. REA seleccionó Objetivos, navegó a la URL de nuevo y observó Objetivos seleccionado tras la recarga (`ev_a70d5c16d49eb7f0e80a58b8deebbf8cb425fce2f75fd6952badcce6084d283a`).
5. **Resumen de objetivos más útil (implementado y verificado).** Búsqueda sin sensibilidad a mayúsculas ni tildes, formato dinámico e incógnitas abiertas/no abiertas. REA combinó `repo` + abiertas + «Eolfi» y obtuvo un objetivo de 46; el contador se anuncia con `role=status` (`ev_a6685714655e7ea1601657a715d871c1f524b2e6fed6fea6472c3ab7cc4d5b07`).
6. **Agrupar opciones avanzadas de creación (implementado y verificado).** La IA opcional tiene un bloque propio y los ajustes secundarios quedan en «Opciones avanzadas». Fuentes, nombre, tecnología, destino y la casilla de verificación siguen visibles. REA abrió ambos bloques a 390×844 y confirmó que mantienen sus controles (`ev_6aaf0afec9a602e236bbddb11a7db164e592fdee1162822e37bdfdd71ced2dc5`).
7. **Dividir el cliente de interfaz por áreas funcionales (implementado).** `runtime.js` contiene utilidades compartidas de DOM, API, trabajos y estado; `subjects.js` agrupa lista, búsqueda, filtros y selección de objetivos; `app.js` conserva la coordinación del panel, análisis, proveedores, trabajos, chat y VS Code. El servidor publica los dos módulos con rutas explícitas.

### Prioridad de mantenimiento

8. **Captura dinámica REA (completada para las pestañas).** Se usó Chromium temporal y aislado sobre `127.0.0.1:18777`, sin conectar al navegador del usuario ni modificar datos. Se verificaron los paneles y el teclado en 390×844 y 1440×900, y el diseño en 320×720, 640×900, 768×1024 y 1024×768. A 320 px también se activó la vista «Trabajos» y quedó visible en la navegación de dos filas. La pasada de foco a 640 px confirma Tab desde el panel hasta «Añadir carpeta» y después a Fuentes, con indicador visual. La persistencia pasó una recarga con navegación explícita. El aviso de error, los filtros de Objetivos y los detalles plegables se comprobaron con datos locales. Las acciones completaron con árboles accesibles y capturas completas; no se retuvieron eventos de consola o error de página. Evidencias REA adicionales: `ev_a70d5c16d49eb7f0e80a58b8deebbf8cb425fce2f75fd6952badcce6084d283a` (persistencia), `ev_a6685714655e7ea1601657a715d871c1f524b2e6fed6fea6472c3ab7cc4d5b07` (filtros), `ev_8f70b02b8cc2977a544fc35fa31d40fa9e113c01e97fb12add47d1a66fa12bcb` (error) y `ev_6aaf0afec9a602e236bbddb11a7db164e592fdee1162822e37bdfdd71ced2dc5` (IA/opciones). La secuencia Analizar → Flecha derecha → Fin → Inicio seleccionó Objetivos → Crear proyecto → Analizar. Evidencias anteriores de viewport/teclado: `ev_d3cc9d635a9a6ad53f78c5610337d61cab182f5031ada7ebc16922769f1f2b39` (390 px), `ev_67eadfd33ec1587bed6dfbb6f13f48bb74b9e18e2775e97f16f08d25f119c7c7` (1440 px), `ev_9b73c7e43288d0783b0c8aaab8bf7471b1e41661e999c72ad2a225745a326ee6` (pestañas con teclado), `ev_2f881aefc01ed15c6b6b55e55b979bdeb337f15ffa6ac0c671493991c4435826` (foco visible a 640 px), `ev_26a96267349c9ce6b4aa2108243e96b68037ba81a345b3d2b18f3eabc773180b` (320 px, antes del ajuste final), `ev_26da2a64d3eb99eb31400cd5503aa9078f3c321b86ee92d084f30d2d1a1d8421` (768 px), `ev_7551e480b8fa3e62a4866ed38c652cd2c0d94f7ad0c7698efe226f1def52ccab` (1024 px), `ev_2791b1a1ae317ac6278c92ef04dc09f27a54baca04bf03ed7a1af23ea3463eec` (320 px, pestañas tras el ajuste) y `ev_869c8a3fd3e2cb613b723b1768e8cbe8749c075414cae657259b6554268cda19` (Trabajos a 320 px). Las sesiones Chromium propias terminaron correctamente. Esto no es una comprobación del navegador local de Work.
9. **Revisar las 64 observaciones por clase y evidencia.** El resumen no expone el contenido individual de todos los hallazgos; deben consultarse desde la evidencia REA retenida antes de tratarlos como defectos.

## Cierre de los últimos pendientes

- La separación de módulos quedó implementada en `eolfi/web/runtime.js` y `eolfi/web/subjects.js`; el HTML carga `app.js` como módulo ES. Se añadieron ambas rutas a la lista estática del servidor y a la prueba de MIME en `tests/test_server.py`. La prueba específica pasó. REA cargó la aplicación en Chromium y devolvió árbol accesible completo, sin errores de consola ni de página (`ev_1e59cb92e8566b29d525872ebf9c4a25fda32727a317f00dbd7f1c54dfa52f68`).
- Verificación de regresión: Node, **121 aprobadas, 0 fallidas**; Python, **315 aprobadas y 2 omitidas**. La prueba HTTP de los dos nuevos módulos pasó después del cambio. Se verificó la sintaxis de los tres módulos como ES modules. El Python 3.12.10 instalado está en `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`; `python` en PATH apunta al alias de Microsoft Store y no arranca.
- Zoom: sigue sin prueba concluyente. REA envió Ctrl+Mayús+= a Chromium headless; la captura resultó idéntica a la línea base (SHA-256 `9b7fe31755f935c01fa177771f86eb9aa62f3fd8a3b06291814ab89c35d697f9`), así que la combinación no cambió el zoom del navegador en este modo. Las vistas responsive sí se han comprobado en varios anchos CSS; eso no sustituye al zoom real.
- Lector de pantalla: sigue pendiente una pasada con Narrador o NVDA. La evidencia REA verifica árbol accesible, semántica de pestañas, estados y foco de teclado, pero no ejecuta la lectura hablada de un lector instalado.

## Alcance y verificación

El cierre posterior amplió los cambios al módulo de objetivos y utilidades, el mapa de recursos estáticos del servidor y su prueba HTTP; la revisión dinámica de REA confirmó que la aplicación modular inicia correctamente.

La modificación de interfaz se limitó a `eolfi/web/index.html`, `eolfi/web/app.js`, `eolfi/web/style.css` y este informe. El análisis estático de REA se limitó a `eolfi/web`; no se auditó aquí el backend, la extensión VS Code, el puente, las dependencias completas ni los binarios empaquetados. La suite completa de `eolfi/vscode-bridge` quedó en **121 aprobadas, 0 fallidas**. La suite Python terminó con **315 aprobadas y 2 omitidas**; las 14 pruebas de servidor pasan. Se actualizó `tests/test_fase_e.py::test_licencia_propietaria` para comprobar el titular que declara la licencia actual, sin cambiar el texto legal. La vista, el teclado y el foco de las pestañas se ejercitaron en Chromium de REA; el diseño se capturó en seis tamaños de 320 a 1440 px. 640×900 aproxima espacio CSS de zoom alto, pero no se alteró el zoom real. El árbol accesible confirmó pestañas/paneles y se retuvieron cero eventos de consola o error de página. Work mantiene deshabilitado su navegador local, por lo que la captura se hizo en Chromium temporal propio de REA. Se corrigió además el log del servidor para ignorar desconexiones normales al escribir respuestas. El lanzador `scripts/test.js` quedó ajustado para descubrir `test/*.test.js` al ejecutarlo sin argumentos.
