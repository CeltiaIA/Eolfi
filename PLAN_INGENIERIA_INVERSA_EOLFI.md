# Hoja de ruta: Eolfi como sistema completo de ingeniería inversa

> Documento vivo. Las fases y objetivos se eliminan de este plan cuando se completan y su resultado queda cubierto por documentación, evidencia y verificación reproducible. No se marca un objetivo como hecho solo porque exista código con ese nombre.

## Propósito

Eolfi debe permitir estudiar un programa desde los artefactos y su comportamiento, aunque no se tenga delante su código fuente, formular una especificación sustentada por evidencias y construir una implementación nueva que reproduzca las funciones observadas. Debe cubrir desde la adquisición controlada del objetivo hasta la comparación y el informe final.

La reconstrucción será independiente: se documentan contratos, estados, entradas, salidas, formatos y comportamiento observable; no se copia ni se presenta como original el código que no se posee. Si una función no se puede demostrar o mejorar con evidencia suficiente, se conserva como incógnita y no se inventa una implementación.

## Criterios permanentes de calidad

- Cada afirmación importante enlaza con evidencia, indica su origen y distingue observación, derivación e hipótesis.
- La falta de código fuente no bloquea el análisis: se admiten ejecutables, paquetes, capturas, interfaces accesibles, tráfico autorizado y escenarios reproducibles.
- La especificación reconstruida describe comportamiento y restricciones, no solo una pila tecnológica o una apariencia.
- La reimplementación se valida frente al original con entradas equivalentes; las diferencias y los límites quedan visibles.
- Herramientas opcionales pueden faltar sin invalidar los resultados que sí se obtuvieron. Eolfi explica qué cubrió cada herramienta y qué quedó sin cubrir.
- Todo proyecto, cambio de código y artefacto que Eolfi construya debe pasar el validador que corresponda antes de considerarse terminado. Si falta el toolchain o la validación falla, el estado queda como «no verificado» o «fallido»; nunca verde por omisión. REA aporta análisis independiente cuando su proveedor cubre el tipo de artefacto, con cobertura/unknowns visibles.
- Las muestras y programas solo se ejecutan cuando existe autorización y un entorno aislado adecuado. La ejecución de una muestra no confiable no se considera segura por el mero hecho de estar limitada por un subproceso.
- Se prioriza mejorar una capacidad existente o cubrir una carencia comprobada. No se añade una función solo para aumentar el inventario.

## Punto de partida observado

El repositorio ya tiene una base considerable: modelo de evidencias e incógnitas, almacenamiento e importación/exportación, parsers para varios formatos, integraciones opcionales con Ghidra/rizin/capa, análisis de webs y repositorios, flujo diferencial, trabajos y panel, CLI, integración con VS Code y generación de proyectos para varias plataformas. README.md describe estas capacidades y SESION.md registra implementaciones y pruebas anteriores.

También hay planes históricos extensos: `PLAN_CORRECCIONES.md` y `PLAN_MEJORAS_2026-11-05.md`. La auditoría archivo por archivo y la verificación posterior están en `informes/auditoria-archivos-Eolfi-2026-11-06.md` e `informes/verificacion-auditoria-2026-11-06.md`. Esos documentos son antecedentes, no una certificación del árbol actual: al comenzar esta hoja de ruta hay numerosos cambios locales sin confirmar, incluidos cambios del agente de VS Code, la interfaz, servidor y pruebas. La primera fase revalidará su estado para no dar por buenos resultados anteriores que puedan haber quedado obsoletos.

La diferencia principal entre la base existente y el objetivo final no es acumular más parsers. Es cerrar y demostrar un flujo único de caja negra: observar una función en el programa original, describirla con precisión, implementarla de manera independiente y medir cuánto coincide.

## Fases pendientes

### Fase 0 — Rebaselinar el proyecto actual

- [x] Inventariar módulos, comandos, rutas de usuario y proveedores a partir del árbol actual; enlazar cada capacidad con su código, interfaz y evidencia de verificación.
- [x] Revisar las diferencias locales actuales frente a los informes de auditoría; confirmar, corregir o retirar hallazgos ya obsoletos y registrar los nuevos reproducibles.
- [x] Crear una matriz de cobertura por clase de objetivo: nativo, gestionado, móvil, escritorio, web, firmware y otros formatos que el proyecto afirme soportar.
- [x] Por cada fila, distinguir análisis estático, ejecución/observación, extracción de especificación, reconstrucción y verificación; «no disponible» debe ser explícito.
- [x] Establecer un conjunto base de fixtures sintéticos autorizados y reproducibles, con hashes, plataforma y pruebas de resultados esperados. Los binarios locales de procedencia desconocida quedan excluidos.
- [x] Consolidar los planes antiguos como historial; esta hoja de ruta es el backlog vigente.

**Fase 0 completada (2026-11-06):** [informe de estado y matriz](informes/estado-y-cobertura-eolfi-2026-11-06.md); instrucciones persistentes en `AGENTS.md`; validación local completa. CLI, API y panel ahora fuerzan la verificación al crear proyectos; la Fase 4 ampliará la calidad y cobertura específica de cada destino.

**Salida verificable:** informe de estado actual fechado, matriz de cobertura y lista corta de brechas priorizadas; referencias exactas a los informes anteriores que se mantienen válidos.

### Fase 1 — Caso de análisis de principio a fin

- [x] Definir un caso/proyecto de análisis persistente que agrupe artefactos, versiones, entorno, ejecuciones, observaciones, evidencias, incógnitas, especificación, reconstrucciones y comparaciones.
- [x] Hacer que toda entrada tenga identidad reproducible: hash, tamaño, formato detectado, procedencia declarada, herramientas y versiones usadas.
- [x] Permitir importar/exportar el caso completo con validación, integridad y referencias conservadas; no convertir hipótesis en hechos al compartirlo.
- [x] Unificar CLI, panel y agente de VS Code alrededor de los mismos flujos y del mismo estado, mostrando progreso, cancelación, errores y resultados parciales.
- [x] Generar un informe navegable que conecte cada conclusión con evidencia, incógnitas y límites.

**Fase 1 completada (2026-11-06):** [informe de cierre](informes/caso-de-analisis-fase-1-2026-11-06.md). `eolfi.core.cases` con identidad tipada (contenido/commit/descriptor/derivado), entorno y herramientas por artefacto y ejecución, registros de flujo tipados y conclusiones observada/derivada/hipótesis validadas al registrar e importar; triage, web, repo, diff, compare y create se enlazan con `case_id`/`--case`; API `/api/cases…`, pestaña «Casos» del panel y herramientas `eolfi_casos`/`eolfi_caso_analizar` del agente sobre el mismo estado; informe HTML navegable (`eolfi case report`, `/api/cases/{id}/report`). Pruebas: `tests/test_case_flows.py`, `tests/test_case_api.py`, `tests/test_cases.py`, `eolfi/vscode-bridge/test/case-tools.test.js`, e2e «casos» en `tests/e2e/panel.test.mjs`. Límites declarados: el agente no se verificó en un VS Code real (solo pruebas unitarias y de contrato HTTP), `diff` sigue siendo solo de CLI y las URL remotas tienen identidad de descriptor, no de contenido.

**Aceptación:** un analista puede iniciar un caso, procesar un objetivo, revisar y resolver incógnitas, continuar después de reiniciar, exportar el caso y reconstruir de dónde salió cada conclusión.

### Fase 2 — Observación de caja negra sin código fuente

- [x] Diseñar una sesión de observación reproducible: artefacto/versionado, SO, arquitectura, configuración, estado inicial, pasos, entradas, efectos, duración y limpieza.
- [ ] Cubrir entradas/salidas de procesos, archivos, registro/configuración, procesos hijos, errores, señales, estado persistente y llamadas relevantes según plataforma, siempre con el alcance de observación declarado.
- [ ] Añadir captura de escenarios de interfaz para escritorio y móvil, con acciones, pantallas, navegación, estados, accesibilidad y resultados observados.
- [x] Añadir observación de comportamiento web y APIs: solicitudes/respuestas autorizadas, eventos, almacenamiento y cambios visibles; enlazar trazas a la acción que las produjo.
- [x] Comparar ejecuciones entre versiones o entornos y localizar el primer cambio observable, manteniendo separados los hechos y la atribución causal.
- [x] Poder repetir una sesión a partir de un guion; marcar como no reproducibles los factores externos que no se pudieron fijar.

**Avance Fase 2 (2026-11-07):** `eolfi/observe/` (guion validado, sesión con sandbox temporal y HOME/TEMP redirigidos, E/S, código/NTSTATUS/señal, hijos muestreados, efectos de archivos y registro declarados, pasos HTTP y de navegador con trazas enlazadas a la acción y hosts autorizados, pasos `desktop` con Windows UI Automation (ventanas y árbol de accesibilidad por acción), comparación con primer cambio y atribución como hipótesis, repetición con factores no fijados); CLI `eolfi observe run|replay|compare|show|check`; API `/api/observe/…` (run/replay solo en local y con `authorized=true`), vista del caso en el panel y herramienta `eolfi_observar` del agente de VS Code; flujos `observe`/`replay`/`observe_compare` en casos. Pruebas: `tests/test_observe.py` (30), `eolfi/vscode-bridge/test/case-tools.test.js`, e2e `tests/e2e/observe.test.mjs` (Chrome real) y «sesiones de observación» en `tests/e2e/panel.test.mjs`. Pendiente/NO VERIFICADO: rutas POSIX (señales, /proc, ps) no ejecutadas en Windows (las pruebas existen y correrán en la CI de Linux/macOS); llamadas al sistema no disponibles (declarado); interfaz móvil no implementada (sin dispositivo) e interfaz de escritorio solo en Windows; el agente no se probó en un VS Code real.

**Aceptación:** con un objetivo ejecutable autorizado y sin fuentes, Eolfi produce un registro repetible de escenarios, entradas, salidas y efectos, con cobertura y límites explícitos. Las capacidades no disponibles en el SO actual no se anuncian como verificadas.

### Fase 3 — Especificación de comportamiento sustentada

- [x] Convertir evidencias estáticas y dinámicas en una especificación versionada: funciones/casos de uso, entradas, salidas, errores, estados, persistencia, interfaces y requisitos no funcionales.
- [x] Enlazar cada requisito con evidencias concretas y grado de confianza; señalar contradicciones e incógnitas sin resolver.
- [x] Modelar secuencias y máquinas de estado cuando el programa tenga flujos, protocolos, formatos o interfaces con estado. *(2026-11-07: `spec.sequences` por guion y objetivo —estado persistente de archivos, registro y cookies HTTP tras cada paso— y máquinas de estado de interfaz browser/desktop; divergencias localizadas como contradicción. Límite: protocolos solo los ejercidos por pasos http/browser del guion; los formatos de archivo no se modelan como máquinas de estado.)*
- [x] Generar casos de prueba a partir de las observaciones, sin elevar automáticamente una inferencia de IA a observación confirmada.
- [x] Permitir revisión humana, cambios trazables y comparación de especificaciones entre versiones.

**Avance Fase 3 (2026-11-07):** `eolfi/spec/` y CLI `eolfi spec build|show|diff|review|tests --case`. Requisitos agrupados por entradas idénticas a partir de las sesiones de observación (casos de uso, interfaces, errores, persistencia, máquina de estados de pasos browser/desktop, duración máxima), con evidencias y confianza (high con ≥2 observaciones iguales); contradicciones abren incógnita y no generan pruebas; aspectos no reproducibles quedan «unstable»; hipótesis del caso aparte; versiones como registros «specification» con padre, revisión humana ligada a la huella de lo revisado y diff entre versiones; pruebas solo desde lo observado. Pruebas: `tests/test_spec.py` (5). Límites: lo estático se limita a la identidad del artefacto (formato, plataforma, tamaño); las máquinas de estado solo cubren flujos de interfaz (no protocolos ni formatos); las evidencias se reúnen por subject, así que un caso ve también sesiones del mismo objetivo hechas fuera de él; la aceptación (implementar desde la especificación) no está demostrada.

**Aceptación:** otra persona puede implementar una función a partir de la especificación sin consultar el código original, y puede identificar qué afirmaciones son seguras, inferidas o desconocidas.

### Fase 4 — Reconstrucción independiente

- [x] Separar el modelo de comportamiento del generador de código; no asumir que detectar un framework basta para reconstruir el producto.
- [x] Derivar módulos, límites, interfaces y datos de la especificación y de las evidencias, explicando decisiones y alternativas.
- [x] Generar una base ejecutable con comportamiento implementado por etapas, respetando el lenguaje y plataforma elegidos; declarar con claridad las funciones simuladas o pendientes.
- [ ] Aplicar mejoras solo cuando exista una razón verificable (seguridad, accesibilidad, rendimiento, compatibilidad o mantenibilidad) y mantener compatibilidad conductual donde sea requisito.
- [x] Registrar de qué requisito procede cada componente generado y permitir regenerar sin destruir cambios manuales no gestionados.

**Avance Fase 4 (2026-11-07):** `eolfi/reconstruct/` y CLI `eolfi reconstruct --case ID --out DIR [--model]`. `build_model` deriva componentes (CLI, persistencia, API HTTP, interfaz), interfaces, datos y decisiones con alternativas desde la especificación y las evidencias, sin generador; `generate` produce una base Python por etapas (etapa 1: tabla de comportamiento observado, casos «simulado»/«pendiente», entradas no observadas → código 2) con manifiesto `.eolfi/trazabilidad.json` (archivo → requisitos → evidencias) y regeneración que no pisa archivos editados (`.nuevo`); `verify` ejecuta la base con las entradas observadas y la compara con la especificación, con evidencia y registro «reconstruction». Pruebas: `tests/test_reconstruct.py` (5). Límites: un solo destino (Python CLI); la etapa 1 no generaliza a entradas no observadas; efectos en archivos, API HTTP e interfaz quedan documentados pero no generados; la casilla de mejoras con razón verificable sigue pendiente.

**Aceptación:** se obtiene un proyecto nuevo que compila/arranca en el entorno declarado y mantiene trazabilidad desde los componentes hasta la especificación, sin copiar código fuente inaccesible.

### Fase 5 — Equivalencia y medición de cobertura

- [x] Ampliar el flujo diferencial para invocar el original y la reconstrucción bajo el mismo entorno controlado y corpus, comparando resultados estructurados además de stdout/códigos de salida.
- [x] Comparar interfaces: navegación, estados, contenido y accesibilidad; permitir tolerancias declaradas para diferencias visuales no funcionales. *(2026-11-07: `compare_sessions`/`eolfi observe compare --tolerate` y API `tolerances`: URL, texto visible, árbol de accesibilidad, peticiones, almacenamiento y ventanas de escritorio; las diferencias toleradas se listan pero no cuentan. e2e con Chrome real en `tests/e2e/observe.test.mjs`. Límite: sin comparación de imagen/píxeles; la tolerancia es por aspecto, no por región visual.)*
- [x] Comparar protocolos y efectos persistentes cuando se puedan capturar de manera fiable; ocultar secretos y datos personales en artefactos de prueba. *(2026-11-07: la equivalencia compara HTTP, cookies, archivos y registro; `eolfi/security/privacy.py` oculta por defecto correos, teléfonos, IBAN, tarjetas (Luhn), DNI/NIE, IP públicas, JWT y claves en el texto guardado de las sesiones, con huella para comparar y recuento en `coverage.personal_data`; desactivable solo declarándolo en el guion. Límite: nombres y direcciones postales no se detectan.)*
- [x] Añadir reducción de casos que fallan, generación de variaciones de entradas y repetición determinista, conservando la semilla y configuración. *(2026-11-07: `eolfi reconstruct --explore CANDIDATO --autorizo --seed --variants --max-runs`: variantes deterministas de stdin por requisito, original y candidato con el mismo paso, reducción ddmin de las que divergen, semilla/config/presupuesto en la evidencia; solo con el original intacto. Límite: solo entrada estándar de pasos run.)*
- [x] Calcular cobertura de requisitos y escenarios, severidad de divergencias y zonas no observadas. Un porcentaje nunca debe ocultar funciones sin probar.
- [x] Reabrir automáticamente una incógnita cuando una ejecución nueva contradiga la especificación o la equivalencia declarada.

**Avance Fase 5 (2026-11-07):** `eolfi/reconstruct/equivalence.py` y `eolfi reconstruct --case ID --equivalence CANDIDATO --autorizo [--tolerate ASPECTO]`: repite cada guion del caso cambiando solo el objetivo por el candidato (mismo sandbox, entorno y entradas) y compara resultados estructurados (estado, código/señal, stdout/stderr, procesos hijos, archivos, registro, HTTP, interfaz). Por requisito: equivalent/divergent/not_exercised con severidad por aspecto y tolerancias declaradas; cobertura con la lista explícita de requisitos sin ejercitar y zonas no observadas; la equivalencia total exige 0 divergencias y 0 sin ejercitar; incógnitas de equivalencia abiertas al divergir y cerradas al volver a coincidir. Pruebas: `tests/test_reconstruct.py`. Fase 5 completa salvo los límites declarados.

**Aceptación:** cada requisito tiene pruebas vinculadas; el informe muestra coincidencias, divergencias, cobertura, reproducibilidad y riesgos residuales. No se afirma equivalencia total con cobertura incompleta.

### Fase 6 — Seguridad, aislamiento y reproducibilidad

- [x] Definir niveles claros de análisis: estático, ejecución observada con autorización y ejecución aislada; las acciones con efectos requieren consentimiento explícito. *(2026-11-07: `eolfi/security/levels.py`: niveles static/observed/isolated por flujo; todo flujo que ejecuta declara su consentimiento (`--autorizo` también en `diff`); «isolated» no lo usa ningún flujo y no se presenta como activo.)*
- [ ] Diseñar integración opcional con VM/contenedor y restricciones de red, filesystem, credenciales, recursos y persistencia; si no hay aislamiento, impedir que la interfaz sugiera seguridad de sandbox.
- [ ] Eliminar secretos de entornos, logs, capturas e informes; redactar datos sensibles por defecto.
- [x] Fijar y registrar versiones, hashes y parámetros de proveedores/herramientas externos para repetir resultados. *(2026-11-07: las evidencias de proveedores externos guardan ruta y SHA-256 del ejecutable junto a su versión y parámetros; `eolfi doctor --pin ARCHIVO` fija Python, Node.js y herramientas externas, y `--check-pin` lista lo que cambió (código 6). Límite: el navegador y los modelos de IA no entran en el archivo de bloqueo; la versión del navegador sí queda en cada sesión.)*
- [ ] Hacer pruebas de resiliencia sobre parsers, importación y paquetes hostiles, y revisar de forma continua los límites de recursos.
- [x] Documentar permisos, datos capturados, ubicación y borrado de cada sesión. *(2026-11-07: `eolfi observe plan` muestra sin ejecutar programas, hosts, alcance, entorno, datos capturados y no capturados, ubicación y borrado; cada sesión guarda `data_handling`; `eolfi observe forget ID --confirmo` borra la sesión y sus derivadas con `secure_delete`. Límite: copias exportadas fuera de la base no se borran.)*

**Aceptación:** una ejecución puede repetirse o explicar por qué no, y el operador puede ver qué permisos se usarán, qué se ejecutará y dónde quedan los datos.

### Fase 7 — Cierre por plataformas y experiencia operativa

- [ ] Validar la matriz de formatos y plataformas de forma real en Windows, Linux y macOS, y Android/iOS donde haya dispositivos o herramientas disponibles.
- [ ] Mantener una ruta útil cuando falte una herramienta externa, sin declarar cobertura equivalente.
- [ ] Simplificar el recorrido principal para pasar de objetivo a especificación, implementación y comparación sin cambiar de modelo de datos.
- [ ] Publicar guías, ejemplos autorizados y criterios de aceptación por flujo; retirar opciones que no puedan sostenerse o mantenerse.
- [ ] Integrar en CI los escenarios reproducibles que no requieren binarios ni credenciales externos; separar pruebas de laboratorio opcionales.

**Aceptación final:** una persona puede completar el flujo con una muestra propia desde CLI o interfaz, sin leer código fuente del objetivo, obtener una reconstrucción independiente y revisar con evidencias dónde coincide y dónde no.

## Orden de trabajo recomendado

1. Fase 0: confirmar el estado real del árbol y eliminar deuda de planes duplicados.
2. Fases 1 y 2: fijar el modelo del caso y registrar comportamiento verificable sin fuentes.
3. Fase 3: convertir observaciones en una especificación trazable.
4. Fases 4 y 5: construir y medir la reconstrucción, cerrando el ciclo funcional.
5. Fases 6 y 7: endurecer y ampliar cobertura según los vacíos demostrados por la matriz.

No se debe expandir primero el número de formatos o destinos de generación si el ciclo observación → especificación → reconstrucción → comparación sigue sin estar demostrado.

## Cómo mantener este plan

- Trabajar una fase cada vez y actualizar las casillas solo con evidencia verificable.
- Mantener `REGISTRO_LIMPIEZA.md` durante todas las fases: anotar candidatos a código obsoleto, scripts antiguos y artefactos con ruta, evidencia y comprobaciones pendientes. No retirar candidatos hasta completar la hoja de ruta y revisar la lista con el usuario.
- Al cerrar una fase, añadir aquí una línea breve con fecha, resultado y referencias a las pruebas/informes; después retirar del backlog los objetivos cumplidos, dejando el historial de cierres.
- Si cambia el alcance, registrar el motivo y actualizar criterios de aceptación antes de añadir nuevas tareas.
- No copiar aquí listas de bugs menores: van en incidencias o auditorías específicas y se elevan a esta hoja solo si bloquean un criterio de aceptación.
- En cada revisión, informar qué está completo, qué sigue y qué depende de una plataforma, muestra o herramienta aún no disponible.
