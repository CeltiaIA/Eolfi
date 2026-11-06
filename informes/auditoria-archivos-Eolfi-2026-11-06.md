# Auditoría archivo por archivo — Eolfi

- Carpeta: `d:\Eolfi`
- Fecha: 2026-11-06
- Archivos a revisar: 129
- Omitidos: 2 (dependencias, compilados, muestras, minificados o secretos)

## Revisión por archivo

### `.claude/launch.json`
- **Propósito:** Configuración de lanzamiento para ejecutar Eolfi en modo servidor usando Python en el puerto 8777.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Archivo claro y conciso; nombres descriptivos.
- **Mejoras:**  
  - [baja] L2: Actualizar el campo "version" si se cambia el formato.

---

### `.github/workflows/ci.yml`
- **Propósito:** Definir la integración continua: pruebas de Python, puente Node y pruebas end-to-end con accesibilidad.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Bien estructurado, comentarios útiles, matrices para OS y versiones de Python, pasos claros.
- **Mejoras:**  
  - [media] L27, L54: Añadir comprobación de errores tras la instalación de dependencias.
  - [baja] L1: Actualizar comentarios si cambian los pasos.

---

### `.vscode/extensions.json`
- **Propósito:** Recomendar la extensión "eolfi-vscode-bridge" para el entorno de desarrollo.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Archivo simple y correcto.
- **Mejoras:**  
  - [baja] L3: Añadir más recomendaciones si el flujo lo requiere.

---

### `eolfi/__init__.py`
- **Propósito:** Define metadatos del paquete Eolfi y su propósito.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Docstring claro, metadatos bien definidos.
- **Mejoras:**  
  - [baja] L11: Revisar licencia si cambia el modelo de distribución.

---

### `eolfi/__main__.py`
- **Propósito:** Punto de entrada para ejecutar Eolfi desde la línea de comandos.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Código mínimo y claro.
- **Mejoras:**  
  - [baja] L4: Añadir manejo de excepciones si `main()` puede lanzar errores no controlados.

### `eolfi/bridge/adapters/core.mjs`
- **Propósito:** Utilidades comunes para adaptadores de chat web, incluyendo control de abortos, espera de respuestas, validación de origen y manipulación de URLs.
- **Seguridad:**  
  - Uso de `process.env` para configuración (L20, L106): Sin validación estricta, pero bajo control del entorno.
  - `evaluateIn` ejecuta scripts en el contexto de la página solo si el origen coincide (L69): bien protegido contra inyección y SSRF.
  - No se detectan rutas inseguras, secretos ni uso de eval/exec fuera del contexto controlado.
  - Si un archivo contiene órdenes para el auditor, se ignoran (L1, comentario).
- **Errores y robustez:**  
  - Manejo correcto de señales de aborto y excepciones (L3, L31, L33, L41, L55-56, L59).
  - Recursos temporales (timers) correctamente limpiados (L72).
  - Control de condiciones de carrera en espera de respuestas (L30-47).
  - Sin hallazgos de recursos sin cerrar ni excepciones tragadas relevantes.
- **Calidad:**  
  - Código modular y legible.
  - Nombres descriptivos.
  - Comentarios claros.
  - No se detecta código muerto ni duplicación significativa.
  - No hay pruebas en este archivo, pero es utilitario.
- **Mejoras:**  
  - [media] Validar que los valores de entorno sean números válidos antes de usarlos (L20, L106).
  - [baja] Añadir pruebas unitarias para funciones utilitarias.

---

### `eolfi/bridge/adapters/declarative.mjs`
- **Propósito:** Adaptador declarativo para chats web configurables mediante selectores, permitiendo recalibración sin modificar el código.
- **Seguridad:**  
  - Lee archivos de configuración del usuario (L12, L22): riesgo bajo, solo claves conocidas y listas de cadenas aceptadas (L25-33).
  - `evaluateIn` usado para ejecutar scripts en el contexto de la página, protegido por comprobación de origen (L61, L90, L116, L174, L182).
  - No se detectan inyecciones, SSRF, secretos ni uso inseguro de rutas.
  - Ignora órdenes para el auditor si aparecen en archivos de datos (comentario L1).
- **Errores y robustez:**  
  - Manejo adecuado de errores y señales de aborto (L174, L179, L206, L209).
  - Excepciones correctamente propagadas y recursos gestionados.
  - Control de condiciones de carrera en espera de elementos y respuestas (L147-151, L188-198).
  - Sin hallazgos de recursos sin cerrar.
- **Calidad:**  
  - Código bien estructurado y comentado.
  - Funciones de longitud razonable.
  - Nombres descriptivos.
  - No se detecta código muerto ni duplicación relevante.
  - Faltan pruebas unitarias.
- **Mejoras:**  
  - [media] Añadir pruebas unitarias para los métodos principales.
  - [baja] Validar más exhaustivamente los datos de configuración del usuario (L22-33).

---

### `eolfi/bridge/adapters/deepseek.mjs`
- **Propósito:** Adaptador para DeepSeek web, interactuando solo con la interfaz visible y gestionando el flujo de mensajes.
- **Seguridad:**  
  - `evaluateIn` ejecuta scripts solo si el origen es el esperado (L115).
  - No se detectan inyecciones, SSRF, secretos ni rutas inseguras.
  - Uso de `randomUUID` para referencias técnicas (L53): seguro.
  - Ignora órdenes para el auditor si aparecen en archivos de datos (comentario L1).
- **Errores y robustez:**  
  - Manejo correcto de abortos y errores (L71, L76, L99-102).
  - Control de condiciones de carrera en espera de elementos y respuestas (L105-112, L79-91).
  - Sin recursos sin cerrar ni excepciones tragadas relevantes.
- **Calidad:**  
  - Código claro y modular.
  - Nombres descriptivos.
  - Comentarios útiles.
  - No hay código muerto ni duplicación significativa.
  - Faltan pruebas unitarias.
- **Mejoras:**  
  - [media] Añadir pruebas unitarias para los métodos principales.
  - [baja] Validar que los selectores y referencias técnicas no puedan ser manipulados externamente.

---

### `eolfi/bridge/adapters/gemini.mjs`
- **Propósito:** Adaptador para Gemini web, gestionando el envío y recepción de mensajes mediante la interfaz visible.
- **Seguridad:**  
  - `evaluateIn` ejecuta scripts solo si el origen es el esperado (L176).
  - No se detectan inyecciones, SSRF, secretos ni rutas inseguras.
  - Ignora órdenes para el auditor si aparecen en archivos de datos (comentario L1).
- **Errores y robustez:**  
  - Manejo correcto de abortos y errores (L84, L99, L131-134).
  - Control de condiciones de carrera en espera de elementos y respuestas (L137-144, L146-157, L159-167).
  - Sin recursos sin cerrar ni excepciones tragadas relevantes.
- **Calidad:**  
  - Código modular y bien comentado.
  - Nombres descriptivos.
  - No hay código muerto ni duplicación significativa.
  - Faltan pruebas unitarias.
- **Mejoras:**  
  - [media] Añadir pruebas unitarias para los métodos principales.
  - [baja] Mejorar la validación de los datos leídos del DOM para mayor robustez.

### `eolfi/bridge/adapters/meta.mjs`
- **Propósito:** Adaptador para interactuar con la web de Meta AI desde el puente Eolfi, simulando acciones de usuario y extrayendo mensajes.
- **Seguridad:** Sin hallazgos. No hay uso de subprocess, eval, rutas, ni secretos. Las evaluaciones en la web se restringen al origen de Meta AI y no exponen datos sensibles.
- **Errores y robustez:** Sin hallazgos. Maneja bien estados de sesión, errores de navegación, y condiciones de concurrencia (L52, L53, L102, L105).
- **Calidad:** Código legible y modular. Nombres descriptivos. No hay duplicación ni funciones excesivamente largas. Cobertura de errores adecuada.
- **Mejoras:**
  - [media] Añadir pruebas unitarias para métodos críticos como `send` y `readState` (L50, L121).
  - [baja] Documentar mejor los posibles valores de retorno de `readState` (L121).

---

### `eolfi/bridge/adapters/sites.json`
- **Propósito:** Configuración de selectores, rutas y parámetros para los sitios soportados por el puente (ChatGPT, Copilot, Le Chat).
- **Seguridad:** Sin hallazgos. No contiene secretos ni rutas peligrosas. Es solo datos de configuración.
- **Errores y robustez:** Sin hallazgos. Estructura JSON válida y clara.
- **Calidad:** Bien estructurado, nombres claros, comentarios útiles. No hay duplicación.
- **Mejoras:**
  - [baja] Añadir ejemplos de uso o referencias cruzadas a los adaptadores que consumen estos datos (L1).

---

### `eolfi/bridge/approval.mjs`
- **Propósito:** Gestiona la aprobación de envíos automáticos del puente, mostrando diálogos de confirmación y recordando permisos temporales.
- **Seguridad:** Sin hallazgos. No hay subprocess, eval, ni manejo de rutas o secretos.
- **Errores y robustez:** Sin hallazgos. Maneja bien expiración de permisos y señales de cancelación.
- **Calidad:** Código claro, funciones cortas y bien nombradas. No hay duplicación ni código muerto.
- **Mejoras:**
  - [baja] Añadir pruebas unitarias para `approve` y `revoke` (L33, L19).

---

### `eolfi/bridge/engine/chrome.mjs`
- **Propósito:** Motor para controlar navegadores Chromium reales mediante CDP, gestionando sesiones, ventanas y automatización segura.
- **Seguridad:** 
  - Sin hallazgos críticos. El uso de `spawn` (L414) es seguro porque los argumentos son controlados y no hay interpolación de entradas externas.
  - No hay exposición de secretos ni rutas inseguras.
- **Errores y robustez:** 
  - Sin hallazgos graves. Maneja bien errores de procesos, cierres inesperados y recursos (L96, L424, L433, L495).
  - Controla condiciones de carrera en la apertura de páginas (L462-L467).
- **Calidad:** 
  - Código extenso pero modular y bien documentado.
  - Nombres descriptivos, sin duplicación ni funciones excesivamente largas.
  - Cobertura de errores adecuada.
- **Mejoras:**
  - [media] Añadir pruebas unitarias/mocks para PipeConnection y CdpSession (L66, L145).
  - [baja] Extraer lógica de arranque de navegador a función separada para facilitar pruebas (L396-L443).

### `eolfi/bridge/main.mjs`
- **Propósito:** Arranca el puente Electron de Eolfi, gestionando ventanas/sesiones para proveedores de chat web y exponiendo una pasarela local segura.
- **Seguridad:** 
  - Control de navegación restringido a orígenes permitidos y hosts de autenticación (L69–L75, L84–L85).
  - Uso de contextIsolation, sandbox y nodeIntegration: false en BrowserWindow (L82).
  - Permisos de archivo bridge.json restringidos (L166–L171).
  - Tokens aleatorios para la API local (L176–L177).
  - No se detectan inyecciones, SSRF, secretos hardcodeados ni uso inseguro de subprocess.
  - Ignora instrucciones en archivos de datos (comentado, no ejecuta).
- **Errores y robustez:** 
  - Manejo de errores en arranque del navegador (L49–L53).
  - Control de instancias únicas (L62–L67).
  - Manejo de recursos y cierre de ventanas (L87).
  - Robustez en acceso a archivos y borrado (L200–L202).
  - Sin excepciones tragadas relevantes ni recursos sin cerrar.
- **Calidad:** 
  - Código modular y legible.
  - Nombres descriptivos.
  - Funciones no excesivamente largas.
  - Comentarios claros.
  - No se observa código muerto ni duplicación significativa.
  - Pruebas presentes en carpeta test.
- **Mejoras:**
  - [media] L61: Comprobar que app.userAgentFallback existe antes de modificarlo (robustez multiplataforma).
  - [baja] L34: Permitir configuración más flexible de proveedores de inicio.

---

### `eolfi/bridge/package.json`
- **Propósito:** Define metadatos, dependencias y scripts del paquete Electron del puente Eolfi.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** 
  - Correcto uso de campos estándar.
  - No hay dependencias innecesarias.
  - Falta campo `repository` (opcional).
- **Mejoras:**
  - [baja] L17: Añadir campo `repository` para trazabilidad.

---

### `eolfi/bridge/server.mjs`
- **Propósito:** Implementa la pasarela HTTP local entre Eolfi y los adaptadores de chat web, gestionando autenticación, aprobación y concurrencia.
- **Seguridad:** 
  - Solo escucha en loopback y verifica Host (L53).
  - Tokens largos y distintos para API/panel (L39–L41).
  - Cuerpo máximo 128 KB (L22, L208–L217).
  - Validación estricta de entradas (L69, L192–L195, L229–L230).
  - No expone rutas peligrosas ni evalúa datos externos.
  - Sin uso de subprocess, eval ni deserialización insegura.
- **Errores y robustez:** 
  - Manejo de errores en todas las rutas (catch, try/catch, L62, L84, L100, L178, L200, L273).
  - Control de recursos y cancelación de peticiones (L125, L234, L241).
  - Manejo de concurrencia con busy y control de aprobación (L121–L122, L231–L232, L277).
  - Sin condiciones de carrera aparentes.
- **Calidad:** 
  - Código modular y bien comentado.
  - Funciones largas pero justificadas por lógica de servidor.
  - Nombres descriptivos.
  - Sin duplicación relevante.
  - Pruebas presentes en carpeta test.
- **Mejoras:**
  - [media] L284: Documentar explícitamente el objeto devuelto por la promesa (para claridad de uso).
  - [baja] L43: Limitar tamaño de partials para evitar crecimiento no controlado en memoria.

---

### `eolfi/bridge/test/adapters.test.mjs`
- **Propósito:** Pruebas unitarias para verificar que los adaptadores de chat web compilan y gestionan correctamente el estado de sesión.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** 
  - Pruebas claras y cubren casos de sesión/invitado y protección por origen.
  - Nombres descriptivos.
  - Sin duplicación ni código muerto.
- **Mejoras:**
  - [baja] L37: Añadir pruebas para casos de error en executeJavaScript.

---

### `eolfi/bridge/test/engine-concurrency.test.mjs`
- **Propósito:** Pruebas unitarias para la concurrencia y robustez del motor ChromeEngine (apertura única, reintentos, arranque único).
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** 
  - Pruebas bien estructuradas y cubren casos de concurrencia y fallo.
  - Nombres descriptivos.
  - Sin duplicación ni código muerto.
- **Mejoras:**
  - [baja] L41: Añadir prueba para cierre y reapertura tras fallo de arranque.

### `eolfi/bridge/test/engine.test.mjs`
- **Propósito:** Pruebas de integración del motor Chrome CDP con un navegador real, validando operaciones de ventana y entrada.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Código claro y bien estructurado. Las pruebas cubren casos relevantes, aunque podrían añadirse más pruebas negativas.
- **Mejoras:**
  - [media] Añadir pruebas para errores de inicialización del motor (L22).
  - [baja] Comentar mejor los pasos de la prueba principal (L32-L51).

---

### `eolfi/bridge/test/fase-a.test.mjs`
- **Propósito:** Pruebas de caducidad de aprobación, navegación entre conversaciones y normalización de saltos de línea.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Buen uso de funciones auxiliares y casos de prueba claros. Cobertura adecuada de los escenarios descritos.
- **Mejoras:**
  - [baja] Añadir pruebas de error para `ensureConversation` (L39).
  - [baja] Comentar el propósito de cada bloque de prueba (L9, L36, L52).

---

### `eolfi/bridge/test/fase-b.test.mjs`
- **Propósito:** Pruebas de robustez del puente: manejo de ventanas cerradas, reset de estado, revocación y límites de tamaño.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Pruebas concisas y bien organizadas. Cobertura de casos límite y errores esperados.
- **Mejoras:**
  - [baja] Añadir comentarios explicativos en cada test (L27, L35, L41, L47).
  - [baja] Probar respuestas a tokens inválidos (L24).

---

### `eolfi/bridge/test/fase-c.test.mjs`
- **Propósito:** Pruebas de arranque del puente sin panelToken y validación de teclas soportadas.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Pruebas directas y específicas. Cobertura suficiente para los casos tratados.
- **Mejoras:**
  - [baja] Añadir comentarios sobre el motivo de los tests (L7, L12).

---

### `eolfi/bridge/test/fase-d.test.mjs`
- **Propósito:** Pruebas adicionales del puente: aprobación granular, normalización de entradas, manejo de cancelaciones, tramas CDP y validaciones HTTP.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Pruebas exhaustivas y bien organizadas. Uso adecuado de mocks y controladores.
- **Mejoras:**
  - [baja] Comentar brevemente cada bloque de pruebas para facilitar la navegación (L12, L27, L65, L72, L81, L97, L113, L124, L143).

### `eolfi/bridge/test/fase-e.test.mjs`
- **Propósito:** Prueba los plazos de espera y la estabilidad de respuestas. También comprueba la recalibración segura de sitios declarativos.
- **Seguridad:** Sin hallazgos. Las cadenas con origen malicioso y sintaxis sospechosa son datos de prueba (L43-L44, L61).
- **Errores y robustez:** Las pruebas temporizadas dependen de pausas y del reloj, por lo que pueden ser inestables bajo carga (L14-L20, L24-L26, L35). Los directorios temporales no se eliminan (L40-L42, L57-L59).
- **Calidad:** Buena cobertura de casos de espera y validación; faltan comprobaciones de limpieza de recursos temporales.
- **Mejoras:**
  - [media] Sustituir las esperas sensibles al tiempo por temporizadores controlados o márgenes menos estrictos (L14-L20, L24-L26, L35).
  - [baja] Eliminar los directorios temporales al terminar cada prueba (L40-L42, L57-L59).

### `eolfi/bridge/test/panel.test.mjs`
- **Propósito:** Verifica la separación de credenciales del panel, el bloqueo de proveedores ocupados y la cancelación durante la aprobación.
- **Seguridad:** Sin hallazgos. Las credenciales son valores de prueba (L6).
- **Errores y robustez:** Las pausas fijas para sincronizar las pruebas pueden fallar bajo carga (L45-L48, L54-L60). `release` podría no estar asignada si la solicitud no alcanza la aprobación a tiempo (L16, L58). El cierre del servidor no se espera (L22).
- **Calidad:** Las pruebas cubren rutas relevantes, pero dependen de estado global compartido (`approvals`, `sent`, `release`) (L7-L10).
- **Mejoras:**
  - [media] Sincronizar las pruebas mediante señales explícitas en vez de pausas fijas (L45-L48, L54-L60).
  - [media] Asegurar la asignación de `release` antes de invocarla y esperar el cierre del servidor (L22, L58).
  - [baja] Aislar o reiniciar el estado compartido entre pruebas (L7-L10).

### `eolfi/bridge/test/server.test.mjs`
- **Propósito:** Prueba autenticación, envío de mensajes, eventos, cancelación, capturas e ingreso remoto.
- **Seguridad:** Sin hallazgos. La ruta de conversación con `../` y el tipo `exec` se usan para probar el rechazo de entradas (L53, L108).
- **Errores y robustez:** La prueba de cancelación depende de un temporizador fijo (L57-L62). El cierre de ambos servidores no se espera (L21, L112). `allow` puede quedar alterado si una aserción falla antes de restaurarlo (L45-L48, L71-L75, L93-L95).
- **Calidad:** Buena cobertura de rutas y validaciones; varias pruebas dependen de estado global mutable (L7, L17).
- **Mejoras:**
  - [media] Usar sincronización explícita para la prueba de cancelación y esperar el cierre de servidores (L21, L57-L62, L112).
  - [media] Restaurar `allow` mediante limpieza garantizada, incluso si falla una aserción (L45-L48, L71-L75, L93-L95).
  - [baja] Reducir la dependencia del estado global compartido entre pruebas (L7, L17).

### `eolfi/cli.py`
- **Propósito:** Define los comandos y argumentos de Eolfi y despacha las operaciones de análisis, exportación, servidor, navegador y VS Code.
- **Seguridad:** L96-L105 y L270-L274 permiten ejecutar comandos de referencia y candidato sobre entradas del corpus; la CLI no valida esos comandos y la seguridad depende de `run_diff`. L196-L205 y L760-L775 exponen acciones de VS Code, incluidos `command` y `tool`, con argumentos suministrados por quien ejecuta la CLI; aquí no se ve una autorización adicional. L126-L131 y L298-L299 aceptan URLs y habilitan descargas de assets; no se puede verificar en este archivo la protección contra SSRF. L626 instala dependencias npm, que pueden ejecutar scripts de instalación. Sin secretos en código ni instrucciones dirigidas al auditor.
- **Errores y robustez:** L465-L466 puede esperar indefinidamente a que se cierre el navegador. L552 ejecuta `taskkill` sin timeout. L431 crea el archivo de bloqueo sin adquisición atómica, por lo que procesos simultáneos podrían interferir. L765 descarta valores falsy, como `--line 0` o texto vacío, aunque se hayan proporcionado.
- **Calidad:** `_dispatch` concentra muchas responsabilidades y ramas (L231-L392); convendría separar el despacho por comando. No hay pruebas visibles para esta CLI, especialmente para los flujos de navegador, VS Code y servidor.
- **Mejoras:**
  - [alta] L196-L205, L760-L775: limitar y validar las acciones y argumentos de VS Code; confirmar que los controles de autorización están implementados en la extensión.
  - [alta] L96-L105, L270-L274: documentar y reforzar las restricciones de ejecución de `diff`; validar corpus, comandos y límites numéricos.
  - [media] L126-L131, L298-L299: comprobar que la descarga web bloquea destinos internos y aplica límites de redirección y tamaño.
  - [media] L626: instalar con dependencias bloqueadas y configuración reproducible, y revisar si se necesitan scripts de instalación.
  - [media] L431, L465-L466, L552: hacer atómico el bloqueo y añadir límites de espera y timeout al cierre de procesos.
  - [baja] L765: conservar valores proporcionados aunque sean falsy; extraer el despacho en funciones por comando.

### `eolfi/core/evidence.py`
- **Propósito:** Guarda evidencias e incógnitas en SQLite. Exporta e importa paquetes JSON, validando sus registros y detectando discrepancias entre evidencias.
- **Seguridad:** Sin hallazgos de inyección SQL: las consultas usan parámetros y las columnas importadas se limitan a listas permitidas (L20-L35, L277-L282). El tamaño de importación está limitado a 256 MiB (L221-L223), aunque ese límite aún permite un consumo considerable de memoria.
- **Errores y robustez:** La comprobación de discrepancias y la inserción se hacen separadamente, por lo que operaciones concurrentes pueden observar el mismo estado y producir conflictos o excepciones (L89-L104, L106-L123). La importación confirma la transacción antes de procesar discrepancias y fusionar incógnitas existentes; un fallo en ese procesamiento deja cambios ya confirmados (L253-L274). Además, la validación de incógnitas no restringe `severity` (L352-L372).
- **Calidad:** La lógica de importación concentra validación, referencias, transacción y fusión en una función extensa (L215-L275). El argumento `table` de `_insert` se interpola, aunque sus usos visibles emplean nombres constantes (L277-L282).
- **Mejoras:**
  - [media] Hacer atómicas también las verificaciones y fusiones posteriores a la importación (L253-L274).
  - [media] Validar `severity` y los tipos de todos los campos de texto importados (L289-L303, L352-L372).
  - [media] Añadir pruebas de importaciones concurrentes y de fallos durante la fusión (L89-L104, L253-L274).

### `eolfi/core/models.py`
- **Propósito:** Define los modelos de evidencia e incógnita, sus enumeraciones y la serialización canónica usada para calcular identificadores.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `Evidence` es congelada, pero sus diccionarios y listas siguen siendo mutables; modificarlos puede cambiar `evidence_id` tras crear el objeto (L41-L66). `_canonical` permite valores no estándar como NaN (L37-L38), y los modelos no validan los tipos ni rangos de sus campos (L41-L55, L79-L89).
- **Calidad:** `result: Any` ofrece flexibilidad, pero deja errores de serialización para el momento de calcular el identificador o crear la fila (L48-L50, L57-L75). La incógnita tampoco es inmutable.
- **Mejoras:**
  - [media] Validar campos y rechazar valores JSON no estándar antes de calcular identificadores (L37-L38, L41-L55).
  - [media] Evitar mutabilidad indirecta en `params` y `links` (L41-L55).
  - [baja] Añadir pruebas para mutaciones posteriores a la creación y para valores no serializables (L57-L75).

### `eolfi/core/report.py`
- **Propósito:** Construye informes de evidencias e incógnitas y los renderiza en Markdown o HTML para revisión o uso en CI.
- **Seguridad:** El HTML escapa los valores insertados (L139-L159), pero el Markdown solo escapa barras verticales y saltos de línea; contenido hostil puede introducir HTML o sintaxis Markdown activa al abrir el informe (L110-L123).
- **Errores y robustez:** `_findings` presupone formas concretas para datos importados; valores con tipos inesperados en `security_findings`, `zip_anomalies` o `findings` pueden provocar excepciones (L27-L36, L46-L57). Si hay varias evidencias de una operación, `by_op` conserva solo la última para los hallazgos (L73-L78).
- **Calidad:** `_findings` combina varias fuentes y casos especiales en una sola función (L27-L64). No se muestran pruebas del escape de Markdown ni de estructuras importadas malformadas.
- **Mejoras:**
  - [alta] Escapar HTML y sintaxis activa en los campos del Markdown, o documentar que solo es seguro en visores confiables (L110-L123).
  - [media] Comprobar tipos y estructuras antes de recorrer los hallazgos importados (L27-L36, L46-L57).
  - [baja] Definir cómo combinar evidencias repetidas por operación en lugar de sobrescribirlas (L73-L78).

### `eolfi/core/sarif.py`
- **Propósito:** Exporta evidencias e incógnitas a SARIF 2.1.0, organizándolas por proveedor y vinculando los artefactos conocidos.
- **Seguridad:** Sin hallazgos de inyección. Las rutas aportadas se convierten en URI `file:` y pueden revelar rutas locales en el SARIF exportado (L27-L33); el resultado y los parámetros completos se incluyen en el documento (L100-L106).
- **Errores y robustez:** JSON corrupto en la base de datos provoca una excepción durante la exportación, sin manejo local (L87-L106, L111-L127). El archivo de artefacto puede cambiar entre el cálculo de su hash y su uso posterior por el visor (L29-L32).
- **Calidad:** La construcción de resultados está concentrada en `build_sarif` (L83-L133). No se muestra validación del documento generado contra el esquema SARIF.
- **Mejoras:**
  - [media] Manejar datos JSON inválidos y reportar qué registro impide exportar (L87-L106, L111-L127).
  - [media] Advertir o permitir omitir URI locales y datos completos potencialmente sensibles (L27-L33, L100-L106).
  - [baja] Añadir pruebas de conformidad con SARIF 2.1.0 (L69-L80, L83-L133).

### `eolfi/core/stix.py`
- **Propósito:** Exporta evidencias e incógnitas como un bundle STIX 2.1, con objetos por objetivo y referencias a técnicas ATT&CK detectadas.
- **Seguridad:** Sin hallazgos de ejecución o SSRF: las URI ATT&CK se construyen a partir de identificadores que pasan un patrón fijo (L114-L124). El contenido de evidencias se incluye en el bundle (L94-L105), por lo que puede exponer datos al compartirlo.
- **Errores y robustez:** El comentario promete exportaciones idénticas para la misma base, pero `now` se incorpora en objetos de ATT&CK y agrupaciones y cambia entre ejecuciones (L67-L72, L119-L126, L143-L153). Los `json.loads` de resultados y parámetros pueden hacer fallar la exportación si la base contiene JSON inválido (L90-L93, L105-L106).
- **Calidad:** La detección ATT&CK está integrada en el recorrido de evidencias (L109-L127). Los identificadores son deterministas, pero el contenido del bundle no lo es por las marcas de tiempo variables (L151-L153).
- **Mejoras:**
  - [media] Usar marcas de tiempo deterministas si se requiere que el bundle completo sea reproducible (L67-L72, L119-L126, L143-L153).
  - [media] Manejar JSON inválido con un error que identifique el registro afectado (L90-L93, L105-L106).
  - [baja] Añadir pruebas de validación del bundle generado contra STIX 2.1 (L67-L153).

### `eolfi/corpus.py`
- **Propósito:** Carga la configuración de fuentes de una biblioteca Alejandría y ejecuta sus scripts de organización y auditoría.
- **Seguridad:** L59–60 ejecutan scripts PowerShell externos; L64 usa `-ExecutionPolicy Bypass`. El comando es fijo y los argumentos viajan como JSON, lo que reduce el riesgo de inyección, pero la biblioteca y sus scripts deben ser de confianza.
- **Errores y robustez:** L64–65 no establece tiempo límite; un script bloqueado puede dejar la operación esperando indefinidamente.
- **Calidad:** La carga de configuración y la orquestación de procesos están concentradas en pocas funciones.
- **Mejoras:** [alta] L59–60, L64: validar la procedencia de los scripts y evitar eludir la política de ejecución cuando no sea imprescindible. [media] L64–65: añadir un tiempo límite y manejar errores de ejecución.

### `eolfi/dotenv.py`
- **Propósito:** Lee archivos `.env` candidatos y carga variables que todavía no estén definidas, sin devolver sus valores.
- **Seguridad:** L42–44 acepta una ruta explícita mediante `EOLFI_ENV_FILE` y carga su contenido en el entorno; debe confiarse en esa ruta y protegerse el archivo de permisos indebidos.
- **Errores y robustez:** L61–63 captura errores de sistema de archivos, pero no errores de decodificación como `UnicodeDecodeError`.
- **Calidad:** El formato admitido es intencionalmente sencillo; no implementa toda la sintaxis habitual de archivos `.env`.
- **Mejoras:** [media] L61–63: manejar errores de decodificación con un mensaje claro. [baja] L54–68: añadir pruebas para comillas, comentarios y archivos con valores duplicados.

### `eolfi/flows/compare_flow.py`
- **Propósito:** Compara evidencias de dos objetivos, resume los cambios y registra el resultado como evidencia `version_diff`.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** L23 puede fallar si un resultado almacenado no es JSON válido. L33–38 y L84–92 presuponen ciertas formas de datos; resultados mal formados pueden causar excepciones.
- **Calidad:** L118–140 concentra reglas específicas en lambdas, lo que dificulta depurarlas. L31–38 y L46–53 limitan partes de la salida, pero no necesariamente el coste de procesar entradas grandes.
- **Mejoras:** [media] L23: manejar resultados JSON inválidos e indicar qué evidencia falló. [media] L84–92: validar tipos y estructuras antes de comparar. [baja] L118–140: extraer las lambdas complejas a funciones con nombre.

### `eolfi/flows/create_flow.py`
- **Propósito:** Analiza fuentes, construye una especificación y genera un proyecto; opcionalmente lo verifica y solicita asistencia de IA.
- **Seguridad:** L149–157 deriva fuentes de web, repositorios y archivos a flujos de análisis; la validación de destinos y protocolos debe estar garantizada por esos flujos. L207–217 y L243–246 invocan verificación que puede ejecutar pasos del proyecto; tratar el código y sus dependencias como no confiables.
- **Errores y robustez:** L114–116 puede fallar si ya existe la ruta de copia de seguridad. L172–194 comprueba rutas y luego escribe o respalda, dejando una posible ventana de carrera ante cambios concurrentes.
- **Calidad:** `create_project` (L120–265) reúne análisis, generación, copias de seguridad, verificación y registro de evidencias; conviene dividirla.
- **Mejoras:** [alta] L207–217, L243–246: ejecutar verificaciones en un entorno aislado y con límites de recursos. [media] L172–194: reducir la ventana entre validar rutas y escribir, y gestionar colisiones de copias de seguridad. [media] L120–265: separar las etapas de creación en funciones comprobables.

### `eolfi/flows/diff_flow.py`
- **Propósito:** Ejecuta referencia y candidato sobre un corpus y compara sus resultados. Registra evidencias e incógnitas por discrepancias.
- **Seguridad:** L72 ejecuta comandos configurables con los permisos del proceso; no usa `shell=True`, pero sigue siendo ejecución arbitraria por diseño. L253 omite `_safe_input` al repetir la referencia: con un `.bat`/`.cmd` y una ruta con metacaracteres puede reabrirse el riesgo de inyección que se mitiga en L155-L167. L164 conserva parte de la extensión original, que puede contener metacaracteres. L323-L325 persiste los argumentos de los comandos, con posible exposición de credenciales incluidas en ellos.
- **Errores y robustez:** L232 carga cada archivo completo en memoria sin límite por tamaño. L82-L84 deja de vigilar cuando termina el proceso padre; sus descendientes podrían seguir ejecutándose. L253 no trata explícitamente errores o timeout de la ejecución repetida de determinismo. L206-L207 no valida que `threshold` esté en un rango útil.
- **Calidad:** La lógica de ejecución, comparación y persistencia está concentrada en `run_diff` (L192-L346). La protección especial para `.bat` no se aplica de forma uniforme (L242, L251, L253).
- **Mejoras:**
  - [alta] Aplicar `_safe_input` también a la repetición de determinismo y neutralizar completamente el nombre de archivo temporal (L155-L167, L253).
  - [alta] Limitar el tamaño de cada entrada antes de leerla completa (L225, L232).
  - [media] Asegurar la terminación de descendientes aunque el proceso padre finalice antes (L82-L84).
  - [media] Validar `threshold` y clasificar explícitamente los errores de la repetición determinista (L206-L207, L253-L257).
  - [media] Evitar persistir argumentos que puedan contener secretos o permitir su redacción (L323-L325).

### `eolfi/flows/learn_flow.py`
- **Propósito:** Coordina el análisis de páginas web y repositorios, registra evidencias y genera resúmenes.
- **Seguridad:** L16-L24 acepta una fuente web y permite `cross_origin`; la protección contra SSRF no se ve en este archivo y debe verificarse en `Fetcher` y `analyze_web`. L19-L24 delega la descarga y el guardado de recursos a esas funciones.
- **Errores y robustez:** L23-L24 y L56 no capturan errores de análisis, descarga o acceso al repositorio; estos pueden abortar el flujo antes de registrar resultados.
- **Calidad:** La extracción de resúmenes es concisa, pero agrupa datos mediante diccionarios dinámicos (L26-L33, L58-L65); faltan validaciones explícitas de la forma de los resultados.
- **Mejoras:**
  - [alta] Verificar y aplicar controles contra SSRF, incluidos destinos locales y redirecciones (L16-L24).
  - [media] Manejar fallos de análisis y registrar el estado parcial sin perder los resultados disponibles (L23-L25, L56-L57).
  - [baja] Validar la estructura de `findings` antes de indexar sus campos (L26-L33, L58-L65).

### `eolfi/flows/triage_flow.py`
- **Propósito:** Ejecuta proveedores de análisis sobre un archivo, registra sus evidencias y resume los resultados. Continúa el triaje cuando falla un proveedor.
- **Seguridad:** L99 hereda todas las variables de entorno al subproceso aislado, lo que puede exponer secretos a código que procese archivos no confiables. L90-L110 ejecuta proveedores en un subproceso, pero el aislamiento mostrado no elimina por sí solo el acceso al entorno ni constituye una sandbox. L118-L119 deja el aislamiento desactivado por defecto.
- **Errores y robustez:** L108 analiza `stdout` completo como JSON sin un límite visible aquí; una salida excesiva puede consumir memoria. L160-L174 captura fallos de proveedores, pero los resultados de ese proveedor se pierden y el triaje continúa.
- **Calidad:** `run_triage` concentra la ejecución, el manejo de errores y el registro de hallazgos (L113-L198). La lógica de resumen accede a estructuras anidadas con supuestos sobre su forma (L220-L252), aunque parte de los errores se captura en L214-L216.
- **Mejoras:**
  - [alta] Filtrar las variables heredadas y limitar los privilegios del subproceso de análisis (L90-L110).
  - [media] Aplicar un límite de tamaño a la salida del proceso antes de decodificarla como JSON (L101-L108).
  - [media] Considerar habilitar aislamiento por defecto para archivos no confiables (L113-L119).
  - [baja] Separar la ejecución de proveedores del registro y resumen para reducir la responsabilidad de `run_triage` (L135-L198).

### `eolfi/generador/assist.py`
- **Propósito:** Envía contexto del proyecto a un proveedor de IA, aplica sus cambios en rutas permitidas y verifica el resultado. Si la verificación falla, intenta reparar o restaura los archivos.
- **Seguridad:** Riesgo de inyección de instrucciones: la petición y los archivos se insertan sin escape en etiquetas XML-like antes de enviarse al proveedor (L142-L162). `collect_context` puede leer archivos externos si una ruta editable es un enlace simbólico, pues no comprueba que la ruta resuelta permanezca bajo `root` (L130-L137). En `_apply`, la comprobación de contención ocurre después de algunas lecturas de destino, y `_restore` escribe mediante rutas no resueltas; enlaces simbólicos podrían provocar lecturas o escrituras fuera del proyecto (L208-L214, L221-L227). La comprobación de aserciones no garantiza que las pruebas existentes sigan verificando el comportamiento (L208-L212).
- **Errores y robustez:** La lectura y decodificación de `eolfi.spec.json`, así como el acceso a `spec["target"]`, pueden fallar sin convertirse en `AssistError` (L241-L242). El presupuesto de tokens solo se comprueba entre rondas, por lo que una respuesta puede superarlo (L296-L299). La restauración puede fallar y ocultar la excepción original (L267-L270, L221-L227).
- **Calidad:** `assist` y `_apply` concentran varias responsabilidades. La validación de la respuesta no comprueba tipos completos ni rechaza campos adicionales (L171-L181); tampoco evita rutas duplicadas en una misma respuesta. No se incluyen pruebas para este módulo.
- **Mejoras:**
  - [alta] Comprobar la contención de rutas resueltas antes de cualquier lectura o escritura y hacer que la restauración aplique la misma protección (L194-L214, L221-L227).
  - [alta] Delimitar o escapar el contenido no confiable del prompt y tratarlo explícitamente como datos (L142-L162).
  - [media] Endurecer `validate_reply` y rechazar rutas duplicadas y respuestas incompletas (L171-L181).
  - [media] Validar la especificación y el presupuesto antes de procesar el proyecto y tras cada respuesta (L241-L242, L296-L307).
  - [baja] Separar la coordinación de rondas, la aplicación de cambios y la restauración en funciones más pequeñas (L230-L277).

### `eolfi/generador/generators_backend.py`
- **Propósito:** Genera backends FastAPI y Express con almacenamiento en memoria o SQLite, autenticación opcional, migraciones y pruebas.
- **Seguridad:** La especificación se interpola sin escapar en código y rutas generadas: `r` aparece en prefijos y etiquetas FastAPI (L425-L430), nombres de archivo y rutas Express (L868-L874), y `spec["title"]` en un docstring (L469). Si la especificación no se valida antes, puede permitir inyección de código o traversal. Las migraciones ejecutan SQL desde archivos (L114-L115, L596-L597 del código generado en L384); deben tratarse como contenido confiable. Sin otras vulnerabilidades evidentes en este archivo.
- **Errores y robustez:** El backend Express SQLite captura cualquier error al crear usuario y lo interpreta como duplicado (L811-L814); el registro igualmente responde éxito (L746-L753). No se cierran explícitamente las conexiones SQLite (L97-L101, L659-L670). `_ident` puede producir nombres inválidos o colisiones para recursos distintos (L25-L26, L425-L431).
- **Calidad:** Archivo extenso que mezcla lógica del generador, plantillas de dos lenguajes y pruebas. Las pruebas generadas cubren solo el primer recurso (L505-L506, L935-L936); `latest` en la dependencia de Express hace las instalaciones menos reproducibles (L837-L841).
- **Mejoras:**
  - [alta] Validar y escapar título y recursos antes de interpolarlos en código o rutas, y comprobar que `Writer` impide traversal (L425-L430, L469, L868-L874).
  - [media] En Express SQLite, distinguir errores de unicidad de fallos de base de datos y devolver el estado correspondiente (L811-L814, L746-L753).
  - [media] Cerrar conexiones SQLite y añadir pruebas de múltiples recursos, nombres inválidos y colisiones (L97-L101, L659-L670, L505-L506, L935-L936).
  - [baja] Fijar una versión de Express en vez de usar `latest` (L840).

### `eolfi/generador/generators_cli.py`
- **Propósito:** Genera una CLI Python con almacenamiento JSON, pruebas y configuración para empaquetar el proyecto.
- **Seguridad:** El título de la especificación se inserta sin escape en código Python y en TOML; un valor controlado podría inyectar contenido o romper los archivos generados (L261, L263, L275). Los nombres de recursos se normalizan antes de usarse como archivo, sin traversal evidente (L256, L73).
- **Errores y robustez:** Datos JSON con elementos que no sean diccionarios con `id` pueden provocar excepciones en lectura, consulta o borrado (L82, L96, L102, L106). Si falla la escritura o el reemplazo, puede quedar un temporal sin limpiar (L86-L89). Añadir elementos concurrentemente puede asignar IDs repetidos o perder cambios (L94-L98).
- **Calidad:** La cobertura no prueba JSON malformado, fallos de escritura ni concurrencia. Hay una línea excesivamente larga (L27).
- **Mejoras:**
  - [alta] Escapar el título según el contexto de Python y TOML antes de generar archivos (L261, L263, L275).
  - [media] Validar la estructura y los tipos de los datos leídos antes de operar sobre ellos (L82, L96, L102, L106).
  - [media] Limpiar temporales ante errores y definir cómo evitar pérdidas por escrituras concurrentes (L86-L98).
  - [baja] Añadir pruebas para datos dañados y errores de almacenamiento (L199-L249).

### `eolfi/generador/generators_desktop.py`
- **Propósito:** Genera una aplicación Electron multiplataforma, con interfaz estática, configuración de seguridad, pruebas y empaquetado.
- **Seguridad:** La comprobación de ruta del protocolo es léxica; no resuelve enlaces simbólicos que podrían apuntar fuera de `renderer/` (L109-L113). La prueba de humo desactiva el sandbox de Chromium en Linux (L283), aunque solo en ese proceso de prueba.
- **Errores y robustez:** Una URL con codificación porcentual inválida puede hacer fallar `decodeURIComponent` dentro del manejador del protocolo (L108-L109). Las dependencias se piden como `latest`, por lo que las versiones pueden cambiar entre instalaciones (L235).
- **Calidad:** Las pruebas comprueban principalmente patrones y configuración, no el confinamiento del protocolo ante enlaces simbólicos ni URLs malformadas (L143-L190). El manejo de errores de `loadURL` no se comprueba (L85).
- **Mejoras:**
  - [alta] Comprobar la ruta real resuelta y gestionar errores de decodificación en el protocolo (L108-L113).
  - [media] Fijar versiones de dependencias y añadir un archivo de bloqueo (L235).
  - [media] Añadir pruebas de rutas, URLs inválidas y fallos de carga (L85, L108-L113, L143-L190).
  - [baja] Evitar `--no-sandbox` en pruebas salvo que sea imprescindible y aislar explícitamente ese caso (L283).

### `eolfi/generador/generators_dotnet.py`
- **Propósito:** Genera una aplicación de escritorio C# con Avalonia, contenido derivado de la especificación y pruebas xUnit.
- **Seguridad:** El título se interpola directamente en XML; contenido especialmente construido podría inyectar nodos o dejar inválido el proyecto (L89). Las referencias NuGet con versión `*` no fijan dependencias y permiten cambios de versión entre restauraciones (L94, L203).
- **Errores y robustez:** La extracción recursiva de contenido no limita la profundidad de diccionarios anidados, por lo que una especificación muy profunda puede causar `RecursionError` (L44-L53). La salida de humo inserta el título sin escape JSON; ciertos títulos producen una salida no válida (L149).
- **Calidad:** Las pruebas validan contenido básico, pero no la generación de XML, la salida de humo ni especificaciones anidadas (L210-L230).
- **Mejoras:**
  - [alta] Escapar el título como texto XML antes de interpolarlo (L89).
  - [media] Fijar versiones NuGet y añadir una estrategia reproducible de restauración (L94, L203).
  - [media] Limitar la profundidad o iterar de forma segura al recorrer contenido (L44-L53).
  - [baja] Escapar correctamente el título al producir JSON en la prueba de humo (L149).

### `eolfi/generador/generators_mobile.py`
- **Propósito:** Genera el esqueleto de una app Expo con páginas, componentes, configuración de API y pruebas.
- **Seguridad:** L294 y L314 interpolan `spec["title"]` directamente en código JSX; un título con sintaxis JSX puede inyectar contenido o romper el código generado. L229 incorpora `resource` en una URL sin codificar; valores con `/`, `?` o `#` pueden alterar la ruta solicitada.
- **Errores y robustez:** L243-L246 no cancela la petición al desmontar el componente ni evita respuestas obsoletas si cambia `name`. L231 confía en que el JSON recibido sea `ApiItem[]`; una respuesta inesperada puede causar errores al renderizar. L288 falla si `pages` está vacío.
- **Calidad:** `gen_expo` concentra mucha lógica y plantillas (L58-L361). `_pascal` (L13) y `path` (L273) no se usan. Las pruebas generadas no cubren la API y la prueba del formulario puede fallar si el formulario no aparece en la página inicial (L339-L350).
- **Mejoras:**
  - [alta] Escapar el título al emitir JSX en L294 y L314.
  - [media] Codificar `resource` como segmento de URL y validar la respuesta en L229-L231.
  - [media] Cancelar peticiones obsoletas y normalizar errores en L243-L246.
  - [media] Manejar explícitamente el caso de `pages` vacío en L288.
  - [baja] Eliminar importación y variable sin uso, y dividir `gen_expo` en funciones menores (L13, L58, L273).

### `eolfi/generador/generators_more.py`
- **Propósito:** Genera proyectos Svelte, Next.js y Django a partir de una especificación. También crea páginas, API de demostración y pruebas.
- **Seguridad:** La API CRUD de Next.js no implementa autenticación ni límites de tamaño de petición (L542-L549, L559-L573); la API de Django permite operaciones sin autenticación y desactiva CSRF (L848-L880). Si los valores de `spec` o los recursos no se validan antes de llegar aquí, se interpolan sin escape en código, HTML, rutas y nombres de archivo, con riesgo de inyección o traversal (L191-L192, L455-L456, L536-L537, L900-L908). La CSP de Next permite `unsafe-inline` en producción (L286-L288).
- **Errores y robustez:** Las API de demostración no limitan el tamaño del cuerpo; en Django, `_parse` solo captura `JSONDecodeError` (L834-L845). Los formularios de API no manejan errores de envío y la carga traga la causa del error (L129-L143, L356-L364). El router Svelte no libera el listener de `popstate` y puede intentar interceptar enlaces externos (L73-L80, L95-L99).
- **Calidad:** Módulo extenso y acoplado a helpers privados de otros módulos (L13-L15); repite lógica de API y temas entre destinos. Las pruebas generadas no cubren identificadores maliciosos, límites de entrada ni acceso no autorizado (L577-L631, L950-L998).
- **Mejoras:**
  - [alta] Validar y escapar todos los valores de `spec` y recursos antes de interpolarlos en código, rutas y HTML (L191-L192, L455-L456, L536-L537, L900-L908).
  - [alta] Proteger las operaciones CRUD con autenticación y autorización; revisar la exención CSRF de Django (L848-L880; L542-L549, L564-L573).
  - [media] Limitar el tamaño de las peticiones y manejar explícitamente errores de decodificación JSON en Django (L834-L845).
  - [media] Manejar los errores de envío y mostrar información útil sin ocultar fallos de carga (L129-L143, L356-L364).
  - [baja] Desregistrar el listener del router y procesar solo enlaces internos elegibles (L73-L80, L95-L99).

### `eolfi/generador/generators_tauri.py`
- **Propósito:** Genera el esqueleto de una aplicación de escritorio Tauri, incluidos configuración, permisos, pruebas e icono.
- **Seguridad:** L126 inserta `spec['title']` directamente en una cadena TOML; comillas o saltos de línea en el título pueden alterar el manifiesto generado. L74 incorpora la URL sin escape JSON; puede producir una salida de humo inválida.
- **Errores y robustez:** L70 permite que `APP_SMOKE=1` cierre la aplicación al terminar la carga, incluso en producción. L79 aborta el arranque con `expect` si falla Tauri.
- **Calidad:** Las pruebas de L91-L115 verifican algunos invariantes, pero no cubren la generación de manifiestos con entradas especiales. L182 usa `latest`, lo que reduce la reproducibilidad de las dependencias.
- **Mejoras:**
  - [alta] L126: escapar el título con un serializador TOML, en vez de interpolarlo directamente.
  - [media] L74: serializar la URL como JSON antes de imprimirla.
  - [media] L182: fijar una versión compatible de `@tauri-apps/cli`.
  - [baja] L91-L115: añadir pruebas para títulos con comillas y saltos de línea.

### `eolfi/generador/generators.py`
- **Propósito:** Genera proyectos para distintas pilas, junto con archivos de configuración, pruebas, CI, Docker y documentación.
- **Seguridad:** [Alta] `_writer` concatena rutas sin comprobar que permanezcan dentro de `out` (L49-L51); los slugs también determinan nombres de archivo (L320-L322). [Alta] El servidor estático confía en un prefijo de ruta para limitar el acceso y sigue enlaces simbólicos, por lo que puede servir archivos fuera de la raíz (L301-L309). [Media] El servidor no restringe métodos ni archivos servidos; podría exponer archivos sensibles presentes en el directorio (L301-L309). [Media] El servidor escucha sin indicar una interfaz local, aunque el comentario anuncia `localhost` (L313). [Media] Los recursos se insertan sin escapar en atributos HTML (L167-L168). [Media] El token de autenticación se guarda en `sessionStorage`, accesible para scripts ejecutados en la página (L266, L280). [Media] Dependencias declaradas como `latest` reducen la reproducibilidad y aumentan el riesgo de cambios de cadena de suministro (L5-L6, L364-L366).
- **Errores y robustez:** [Alta] Si ya existe `.gitignore.extra`, se elimina y luego `written.remove(...)` lanza `ValueError`, porque el archivo no se añadió a esa lista en esta ejecución (L85-L88). [Media] Errores de lectura del servidor se convierten todos en 404, ocultando fallos distintos (L307-L312). [Media] Las escrituras no son atómicas; un error puede dejar la salida parcial (L48-L52, L64-L93). [Media] Las llamadas a la API del frontend no gestionan de forma consistente fallos de red o respuestas no exitosas (L254-L258, L462-L468, L787-L792). [Baja] Acceder a `localStorage` o `sessionStorage` puede lanzar excepciones en entornos que bloqueen el almacenamiento (L266, L280, L546, L549, L861, L864).
- **Calidad:** Archivo monolítico de más de 1.200 líneas con numerosos generadores y plantillas embebidas. La lógica de manejo de errores de API se repite entre destinos. Hay pruebas generadas para algunos destinos, pero no se aprecia cobertura equivalente para todos.
- **Mejoras:**
  - [alta] Validar y resolver las rutas de salida para impedir escapes del directorio, incluidos enlaces simbólicos (L49-L51, L301-L309).
  - [alta] Corregir el manejo de `.gitignore.extra` para no borrar archivos ajenos ni llamar a `remove` sobre una entrada inexistente (L85-L88).
  - [alta] Escapar y validar los valores de recursos antes de insertarlos en atributos HTML (L167-L168).
  - [media] Restringir el servidor a `127.0.0.1`, aceptar solo métodos apropiados y limitar los archivos servibles (L301-L313).
  - [media] Gestionar explícitamente errores y estados HTTP en las operaciones de API (L254-L258, L462-L468, L787-L792).
  - [media] Sustituir `latest` por versiones fijadas y documentar el proceso de actualización (L5-L6, L364-L366).
  - [baja] Separar generadores, plantillas y configuración CI/Docker en módulos distintos (L64-L1205).

### `eolfi/generador/llm.py`
- **Propósito:** Implementa proveedores de modelos por API, puente local y VS Code. Convierte sus respuestas en objetos JSON y gestiona disponibilidad y reintentos.
- **Seguridad:** `base_url` admite destinos configurables y `_post` envía allí la clave de API cuando corresponde; un destino HTTPS malicioso podría recibirla (L285-L311). El proveedor Ollama también acepta una URL configurable sin restricción de host, lo que puede permitir solicitudes a servicios internos si la URL no es confiable (L260-L273). Si la respuesta web no es JSON, se guarda sin límite ni protección especial de permisos; `write_text` puede seguir un enlace simbólico preexistente (L359-L364).
- **Errores y robustez:** `read_bridge` y `read_vscode_bridge` no capturan `UnicodeDecodeError` al leer archivos con codificación inválida (L102-L107, L390-L398). El rollback ignora fallos y luego borra todos los diarios, impidiendo reintentar los deshacer fallidos (L466-L473). Las respuestas de API solo se comprueban parcialmente antes de acceder a sus campos, por lo que estructuras inesperadas pueden causar excepciones (L312-L319, L455-L457).
- **Calidad:** La asignación dinámica de `rollback` a la clase dificulta seguir la interfaz (L460-L477). La validación y conversión de respuestas está repartida entre proveedores; faltan pruebas visibles para respuestas malformadas, límites y rollback.
- **Mejoras:**
  - [alta] Restringir o confirmar los destinos de `base_url` antes de enviar claves o solicitudes a servicios internos (L260-L273, L285-L311).
  - [media] Guardar respuestas con permisos restrictivos, límite de tamaño y protección contra enlaces simbólicos (L362-L363).
  - [media] Conservar los diarios cuyo rollback falle y exponer el error para permitir reintentos (L466-L473).
  - [baja] Validar explícitamente tipos y campos de respuestas y capturar errores de decodificación de los archivos de configuración (L102-L107, L312-L319, L390-L398).

### `eolfi/generador/spec.py`
- **Propósito:** Combina evidencias de fuentes para crear una especificación de proyecto. Elige plataforma, páginas, secciones, diseño y recursos de API.
- **Seguridad:** L340 conserva endpoints observados sin validarlos; si contienen datos sensibles o se interpolan sin escape en etapas posteriores, pueden filtrarse o provocar inyección. No se observa ejecución de código ni acceso a red en este archivo.
- **Errores y robustez:** L44 puede propagar errores de JSON inválido. L403-405 acepta cadenas con varios puntos que pueden hacer fallar `float()`. L245-263 y L287-288 presuponen estructuras y claves concretas en las evidencias; datos incompletos pueden causar `KeyError` o `TypeError`.
- **Calidad:** `build_spec` concentra muchas responsabilidades (L193-347) y hay una expresión difícil de leer en L319. No se ven pruebas de entradas malformadas ni de selección de recursos.
- **Mejoras:**
  - [media] Validar y normalizar los endpoints antes de incluirlos en la salida (L274-275, L340).
  - [media] Rechazar breakpoints que no se puedan convertir a número y manejar evidencias malformadas (L44, L403-405).
  - [baja] Extraer de `build_spec` funciones para procesar cada tipo de fuente (L211-300).

### `eolfi/generador/templates.py`
- **Propósito:** Define secciones con un DSL sencillo y las renderiza como HTML, JSX, Vue, Svelte o plantillas Django. También genera CSS común para los proyectos.
- **Seguridad:** L426 inserta nombres y valores de atributos Django sin escape; sería un vector de inyección si el DSL admite datos externos. L235 inserta directamente valores de directivas Vue. L264-285 inserta valores de `spec` en CSS sin validarlos; entradas no confiables podrían inyectar contenido en la salida. Los datos de texto sí se escapan en HTML en L163.
- **Errores y robustez:** Los renderizadores presuponen nodos, atributos y colecciones con formatos válidos (L160-175, L190-217, L220-247); datos malformados pueden causar excepciones o salida inválida. `tokens_css` y `base_css` también presuponen que `spec` contiene todas las claves esperadas (L261-267, L296-298).
- **Calidad:** La lógica de recorrido se repite en varios renderizadores (L160-175, L190-217, L220-247, L390-415, L418-433). El parámetro `loop` de `render_vue` no se usa (L220).
- **Mejoras:**
  - [alta] Escapar y validar nombres y valores de atributos antes de generar plantillas Django (L426).
  - [alta] Validar los valores de `spec` antes de interpolarlos en CSS y validar expresiones de directivas Vue (L235, L264-285).
  - [media] Comprobar la estructura del DSL y los datos de bucle al renderizar (L160-175, L220-247).
  - [baja] Reducir la duplicación entre renderizadores y eliminar el parámetro no usado (L220, L390-433).

### `eolfi/generador/verify.py`
- **Propósito:** Instala dependencias, compila y ejecuta pruebas según el tipo de proyecto. Puede verificar en un entorno con carpeta personal temporal.
- **Seguridad:** Ejecuta código del proyecto y scripts de instalación de npm/pip, además de pruebas y binarios generados (L202-L210, L239-L243, L260-L274, L285-L290, L305-L320, L351-L374). `sandbox=True` no aísla procesos ni limita acceso al sistema; comparte cachés y conserva variables de proxy (L42-L69). No usa shell, pero esto no constituye un sandbox de ejecución.
- **Errores y robustez:** La lectura de `package.json` y archivos instalados puede propagar errores de JSON o de E/S (L143-L155). El parseo de NuGet asume la estructura JSON esperada (L125-L136). `requirements.txt` se reescribe tratando cada elemento como requisito, lo que puede alterar comentarios, opciones o restricciones (L362-L368).
- **Calidad:** La lógica está muy concentrada en `_verify`, con ramas por plataforma y resultado agregado al final. Las versiones `^` de npm y `>=` de Python no fijan versiones exactas (L153, L367).
- **Mejoras:**
  - [alta] Ejecutar código generado bajo aislamiento real de procesos y limitar acceso a red, sistema de archivos y recursos (L42-L69, L239-L243).
  - [media] No propagar variables de proxy con posibles credenciales al código verificado, o filtrarlas explícitamente (L29, L36).
  - [media] Validar la forma de los JSON y gestionar errores de lectura/escritura en los fijadores de versiones (L125-L136, L143-L155).
  - [media] Parsear y reescribir `requirements.txt` conservando su sintaxis, y usar restricciones reproducibles si ese es el objetivo (L362-L368).

### `eolfi/providers/apksig.py`
- **Propósito:** Extrae metadatos de certificados y esquemas de firma APK v1, v2, v3 y v3.1. También detecta la presencia de un archivo `.idsig`.
- **Seguridad:** El propio módulo indica que no verifica firmas criptográficas ni resúmenes (L4-L5); los datos extraídos no deben tratarse como prueba de autenticidad. La lectura de entradas ZIP con `zf.read` no limita el tamaño descomprimido (L119), lo que permite consumo excesivo de memoria ante APK maliciosos. La presencia de `.idsig` solo se comprueba por nombre (L141-L142).
- **Errores y robustez:** `signing_block` puede lanzar `struct.error` en lecturas truncadas (L63-L69), pero `apk_signature` solo captura `ParseError` en esa llamada (L125-L129). El EOCD se identifica buscando la última firma sin validar completamente sus campos (L42-L49).
- **Calidad:** `_seq` y el recorrido del bloque limitan elementos a 64, pero pueden omitir datos restantes sin indicarlo (L34-L39, L72-L78). Solo se procesa la primera entrada de firma v1 encontrada (L115-L124).
- **Mejoras:**
  - [alta] Limitar el tamaño descomprimido de las entradas ZIP y manejar de forma uniforme los errores de datos truncados (L119, L125-L129).
  - [media] Validar los límites y la coherencia del EOCD y del bloque antes de desempaquetar campos (L42-L49, L63-L76).
  - [media] Aclarar en los resultados que la detección de v4 no verifica el `.idsig` y que los certificados no autentican el APK (L4-L5, L141-L142).
  - [baja] Informar si se alcanzan los límites de elementos y considerar todas las entradas de firma v1 pertinentes (L34-L39, L115-L124).

### `eolfi/providers/apple.py`
- **Propósito:** Extrae metadatos de IPA: `Info.plist`, perfil de aprovisionamiento, ejecutable Mach-O, firma y entitlements.
- **Seguridad:** El módulo declara que no verifica criptográficamente la firma ni el perfil (L4, L102-L105); los datos extraídos no acreditan autenticidad. Las lecturas de `Info.plist`, perfil y ejecutable no limitan el tamaño descomprimido del ZIP (L126, L143, L152), lo que puede consumir memoria excesiva con archivos maliciosos.
- **Errores y robustez:** Se asumen tipos concretos en campos del plist; valores malformados pueden provocar errores al llamar a `.get` o `len` (L108-L115, L127-L138). `code_signature` no comprueba que la tabla de índices quepa en el SuperBlob antes de leerla (L68-L74); el llamador captura `struct.error`, pero no todos los posibles errores de datos (L163-L168, L175-L176).
- **Calidad:** La extracción y el análisis de firmas están reunidos en funciones largas. No hay pruebas visibles en este archivo para datos plist, ZIP o SuperBlob malformados.
- **Mejoras:**
  - [alta] Limitar los tamaños descomprimidos antes de leer entradas del IPA (L126, L143, L152).
  - [media] Validar tipos y estructura de los campos del plist antes de usarlos (L108-L115, L127-L138).
  - [media] Comprobar límites de offsets, longitudes e índices del SuperBlob antes de desempaquetar o extraer datos (L68-L89).
  - [media] Distinguir claramente metadatos leídos de firmas verificadas criptográficamente (L4, L102-L105).

### `eolfi/providers/arsc.py`
- **Propósito:** Analiza `resources.arsc` y resuelve identificadores de recursos y alias usados en otros datos.
- **Seguridad:** Procesa datos binarios potencialmente no confiables. Hay límites para chunks y cadenas (L25, L55-L67), pero las entradas de recursos no siempre se validan contra el límite del chunk antes de leerse (L129-L142), por lo que datos malformados pueden producir resultados incorrectos o errores.
- **Errores y robustez:** En entradas no compactas, `e + size` se usa para leer el valor sin comprobar que permanezca dentro del bloque actual (L137-L142). `resolve_refs` recorre recursivamente objetos sin límite de profundidad ni detección de ciclos (L156-L165).
- **Calidad:** `_type_chunk` concentra interpretación de formatos y validación; parte de sus parámetros no tiene anotaciones de tipos (L102-L103). No hay pruebas visibles en este archivo para chunks truncados o configuraciones dispersas.
- **Mejoras:**
  - [alta] Verificar que la entrada completa y su valor quedan dentro del chunk antes de leerlos (L129-L142).
  - [media] Limitar profundidad y detectar ciclos en el recorrido de objetos (L156-L165).
  - [media] Añadir pruebas para offsets, longitudes y tablas de índices malformados (L102-L142).
  - [baja] Añadir anotaciones de tipos a `_type_chunk` y separar validación de decodificación (L102-L103).

### `eolfi/providers/axml.py`
- **Propósito:** Decodifica XML binario de Android y resume datos del manifiesto, componentes y señales de seguridad.
- **Seguridad:** La validación de cabeceras no comprueba que `chsize` quepa en `csize` antes de leer campos de `START_EL` (L152-L167); un archivo malformado puede provocar lecturas fuera del chunk o errores. El mapa de recursos se asigna sin límite específico (L158-L159), lo que puede consumir memoria proporcional al tamaño de una entrada hostil.
- **Errores y robustez:** El tamaño total declarado se recorta al tamaño disponible en vez de rechazar truncamientos (L140), por lo que podría aceptarse un manifiesto incompleto. No se valida que las etiquetas de cierre correspondan a las de apertura; la profundidad solo se decrementa y se limita a cero (L184-L185).
- **Calidad:** La lógica combina decodificación y análisis del manifiesto en una función extensa (`summarize_manifest`, L196-L285). No se muestran pruebas para entradas truncadas, chunks malformados ni valores límite.
- **Mejoras:**
  - [alta] Validar tamaños mínimos y límites de cada tipo de chunk antes de leer sus campos (L152-L167).
  - [media] Rechazar tamaños declarados mayores que los datos disponibles y validar la estructura de apertura/cierre (L140, L184-L185).
  - [media] Añadir límites explícitos a la cantidad de IDs del mapa de recursos (L158-L159).
  - [baja] Separar el análisis de componentes y la generación de hallazgos de seguridad en funciones más pequeñas (L196-L285).

### `eolfi/providers/base.py`
- **Propósito:** Define la interfaz abstracta común para proveedores de herramientas.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** La interfaz documenta la forma esperada de los hallazgos, pero no define ni valida su esquema (L17-L19). No se muestran pruebas para implementaciones de proveedores.
- **Mejoras:**
  - [baja] Definir un tipo o esquema para validar la estructura devuelta por `run` (L17-L19).

### `eolfi/providers/binfmt.py`
- **Propósito:** Analiza binarios PE, ELF, Mach-O y WebAssembly y produce hallazgos sobre estructura, dependencias, seguridad y entropía.
- **Seguridad:** El presupuesto de análisis no se activa en `run`; archivos dentro del límite de 512 MB aún pueden consumir recursos durante el cálculo de entropía (L602-L629). La conversión de RVA comprueba el límite del archivo, pero no que la lectura quede dentro del tamaño en disco de la sección (L236-L246).
- **Errores y robustez:** `run` captura `ParseError`, pero otras excepciones de los analizadores, de `_pe_extra` o de las operaciones de archivo pueden propagarse (L604, L624-L632, L686). En ELF, las cadenas dinámicas solo se limitan al archivo, no a la tabla de cadenas, lo que puede producir datos incorrectos (L503-L505).
- **Calidad:** `opt_size` se lee, pero no se usa para comprobar que las estructuras del encabezado opcional PE queden dentro de sus límites declarados (L184-L205). El análisis combina varios formatos y responsabilidades en un mismo módulo.
- **Mejoras:**
  - [media] Activar un presupuesto de bytes y tiempo durante el análisis desde `run` (L602-L629).
  - [media] Validar las lecturas RVA frente al tamaño en disco de la sección y las cadenas frente a su tabla (L236-L246, L503-L505).
  - [media] Convertir excepciones de entrada y análisis en hallazgos controlados (L604-L632, L686).

### `eolfi/providers/der.py`
- **Propósito:** Extrae campos de certificados X.509 y estructuras PKCS#7 en DER, sin validar confianza ni firmas criptográficas.
- **Seguridad:** No hay límites de tamaño global ni de profundidad; el límite de elementos DER se aplica por iterador, por lo que entradas grandes o estructuras anidadas pueden consumir recursos (L15, L79-L87, L174-L205). La falta de validación criptográfica está indicada explícitamente y debe tenerse en cuenta al usar los resultados (L3-L5).
- **Errores y robustez:** `parse_pkcs7` realiza accesos a índices anidados sin protegerlos; estructuras truncadas o vacías pueden provocar `IndexError` en vez de `ParseError` (L177-L187). `oid` no señala una codificación base-128 que termine con el bit de continuación activo (L90-L100).
- **Calidad:** `MAX_DEPTH` y `HASHES` están definidos, pero no se usan (L15, L31). El campo `content` puede devolver un objeto `Node`, que no es directamente serializable como JSON (L187, L204).
- **Mejoras:**
  - [media] Añadir límites globales de entrada y profundidad, o documentar límites impuestos por el llamador (L15, L79-L87).
  - [media] Validar la estructura y los índices de PKCS#7 y convertir fallos de formato en `ParseError` (L177-L203).
  - [baja] Eliminar constantes sin uso y devolver un valor serializable para `content` (L15, L31, L187, L204).

### `eolfi/providers/dex.py`
- **Propósito:** Analiza cabeceras DEX y archivos ZIP de aplicaciones, identificando clases, APIs, manifiestos y bibliotecas nativas.
- **Seguridad:** L201-L208: en ZIP64 el recuento previo devuelve `None`, por lo que `infolist()` puede cargar un directorio central enorme antes de aplicar el límite. L211-L222: detecta rutas peligrosas, pero no las elimina; actualmente no extrae entradas. L247-L255: las entradas DEX duplicadas pueden hacer que `getinfo()` lea una copia distinta de la que sugiere el inventario.
- **Errores y robustez:** L88 y L138: si `file_size` es inválido, el checksum y la firma pueden quedar sin verificar, sin registrar explícitamente ese motivo. L119-L135: los límites de métodos y cadenas no indican si el análisis quedó truncado.
- **Calidad:** L108-L127: la presencia de una API en la tabla de métodos no confirma que se invoque desde el bytecode. L338-L339: `_mobile_frameworks(names)` se calcula dos veces.
- **Mejoras:** [alta] Aplicar un límite de tamaño al directorio central ZIP64 antes de `infolist()` (L201-L208). [media] Informar truncamiento de los escaneos DEX y distinguir referencias de invocaciones reales (L119-L135). [media] Resolver explícitamente entradas duplicadas o evitar analizarlas sin advertencia adicional (L247-L255).

### `eolfi/providers/dotnet.py`
- **Propósito:** Extrae metadatos CLR, dependencias, P/Invoke y señales de ofuscación; también detecta archivos bundle de .NET single-file.
- **Seguridad:** L143: `strong_name_signed` indica flags y presencia de RVA, pero no verifica criptográficamente la firma. L268-L303: analiza nombres de rutas del bundle sin extraer archivos; no se observa ejecución de contenido.
- **Errores y robustez:** L130-L174: offsets y tamaños de cabecera, directorios y streams se usan sin validar explícitamente que queden dentro de sus regiones declaradas; entradas malformadas pueden provocar errores de lectura o resultados inconsistentes. L280-L303: el análisis del bundle limita la cantidad de archivos, pero no informa si `count` supera ese límite.
- **Calidad:** L31-L32: las lambdas para definir columnas reducen la claridad del esquema. L268-L303: el parser del bundle concentra lectura, validación y resumen en una función.
- **Mejoras:** [alta] Validar que offsets y tamaños de streams estén dentro de los límites de metadatos antes de leerlos (L153-L174). [media] Etiquetar la firma como declarada, no verificada, o añadir verificación criptográfica (L143). [baja] Indicar truncamiento cuando `count` exceda 2000 y añadir pruebas con bundles y metadatos malformados (L295-L303).

### `eolfi/providers/external.py`
- **Propósito:** Integra capa, rizin/radare2 y Ghidra mediante procesos externos y normaliza sus resultados.
- **Seguridad:** En Windows, los lanzadores `.bat`/`.cmd` pueden pasar por `cmd.exe`, pero solo se valida el nombre del archivo analizado; no se validan todos los argumentos, como la ruta del ejecutable o la de los scripts (L137-L139, L361-L369, L402-L405). La salida de los procesos se almacena sin límite, lo que permite consumir memoria si una herramienta produce una salida excesiva (L153-L157).
- **Errores y robustez:** La salida JSON con estructura inesperada puede provocar excepciones no capturadas en `parse_capa_json` o `_slim_functions` (L188-L190, L325-L337); también pueden propagarse errores al iniciar rizin o Ghidra (L280-L293, L408-L410).
- **Calidad:** La gestión manual de contextos con `__enter__`/`__exit__` es menos legible que un bloque `with` (L271-L278, L389-L396).
- **Mejoras:**
  - [alta] Valida todos los argumentos de lanzadores `.bat`/`.cmd`, incluidas las rutas del ejecutable y los scripts (L137-L139, L402-L405).
  - [media] Limita la salida capturada y maneja estructuras JSON inesperadas y errores de inicio de procesos (L153-L157, L188-L190, L280-L293, L325-L337, L408-L410).
  - [baja] Sustituye la gestión manual de los contextos temporales por bloques `with` (L271-L278, L389-L396).

### `eolfi/providers/ghidra_scripts/EolfiExport.java`
- **Propósito:** Exporta a JSON metadatos del programa, funciones, símbolos externos y, opcionalmente, código decompilado.
- **Seguridad:** La ruta de salida se recibe de los argumentos y se abre para escritura sin validación; una invocación con argumentos no confiables podría sobrescribir un archivo accesible (L55-L57, L109-L110).
- **Errores y robustez:** Se ignora el resultado de `openProgram` (L153-L155). Si se cancela el análisis, se puede exportar un recuento parcial sin indicarlo como tal (L74-L78, L91-L92).
- **Calidad:** `resolve` oculta cualquier excepción al intentar interpretar una dirección, lo que dificulta diagnosticar fallos (L130-L138). No se observan pruebas en este archivo.
- **Mejoras:**
  - [alta] Restringe la ruta de salida a un destino autorizado antes de abrirla (L55-L57, L109-L110).
  - [media] Comprueba el resultado de `openProgram` y refleja explícitamente la cancelación en la exportación (L74-L78, L91-L92, L153-L155).
  - [baja] Conserva o registra el detalle de las excepciones de resolución de direcciones (L130-L138).

### `eolfi/providers/isolated.py`
- **Propósito:** Ejecuta un proveedor en un proceso separado y aplica límites de memoria y tiempo al análisis.
- **Seguridad:** El prefijo permitido para el módulo no restringe módulos ni clases a una lista de proveedores concretos; si los argumentos son controlables, se podrían importar módulos del paquete y construir clases no previstas (L19-L30). Los límites configurables por entorno se convierten directamente y el límite de tiempo no tiene validación ni máximo (L15, L34).
- **Errores y robustez:** La asignación de argumentos falla con `ValueError` si la cantidad no es exactamente tres (L19). El límite de memoria puede fallar y la excepción se ignora, dejando el proceso sin esa protección (L26-L29).
- **Calidad:** La función principal concentra validación, configuración de recursos, importación y ejecución. No se observan pruebas en este archivo.
- **Mejoras:**
  - [alta] Usa una lista permitida de módulos y clases de proveedores, y valida los argumentos antes de importarlos (L19-L30).
  - [media] Valida y limita los valores de memoria y tiempo configurables (L15, L26-L34).
  - [baja] Maneja explícitamente una cantidad incorrecta de argumentos y documenta el fallo de aplicación del límite (L19, L26-L29).

### `eolfi/providers/java.py`
- **Propósito:** Analiza archivos `.class` y archivos JAR para extraer metadatos, dependencias, paquetes y versiones de bytecode.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Las operaciones sobre el manifiesto pueden propagar errores del archivo ZIP o de lectura; solo se filtran excepciones al muestrear cabeceras de clases (L118-L121, L125-L132).
- **Calidad:** `MAX_POOL` está definido pero no se utiliza (L17). La decodificación UTF-8 estándar no implementa UTF-8 modificado de Java, como señala el comentario del propio código (L42). No se observan pruebas en este archivo.
- **Mejoras:**
  - [media] Maneja explícitamente errores al obtener y leer el manifiesto (L118-L121).
  - [baja] Elimina `MAX_POOL` si no se necesita y considera decodificar UTF-8 modificado para cadenas de clase (L17, L42).

### `eolfi/providers/macho.py`
- **Propósito:** Analiza archivos Mach-O delgados y universales. Extrae metadatos de cabeceras, segmentos, símbolos y opciones de seguridad.
- **Seguridad:** Los límites de la tabla de símbolos no se comprueban contra el tamaño de la arquitectura ni de la tabla de cadenas; `r.cstr` puede leer más allá de `strsize` (L197-L204). Los offsets de segmentos y firmas se devuelven sin validar que queden dentro de la arquitectura (L148-L149, L178-L181).
- **Errores y robustez:** Un `symtab` malformado puede producir errores de lectura; estos se capturan, pero el resultado puede quedar incompleto (L199-L208). No se comprueba que los comandos consuman exactamente `sizeofcmds` (L129-L137, L192).
- **Calidad:** El análisis de símbolos y el de comandos de carga están concentrados en una función extensa (L106-L244). No se incluyen pruebas aquí.
- **Mejoras:**
  - [alta] Limitar lecturas de símbolos y cadenas a sus rangos declarados y a la arquitectura (L197-L204).
  - [media] Validar rangos de segmentos y de firma antes de reportarlos (L148-L149, L178-L181).
  - [baja] Separar el análisis de comandos de carga en funciones auxiliares (L129-L192).

### `eolfi/providers/pe_extra.py`
- **Propósito:** Añade análisis de Authenticode, imphash, cabecera Rich, callbacks TLS e información de versión a PE.
- **Seguridad:** El propio módulo aclara que no valida la confianza de la cadena ni la firma criptográfica; `digest_matches` solo informa coincidencia del resumen (L3-L5, L108-L112). El mapeo RVA→offset comprueba el límite del archivo, pero no que el offset corresponda a bytes respaldados por datos de la sección (L30-L40).
- **Errores y robustez:** `_block` recorta longitudes inválidas en vez de rechazarlas, lo que puede hacer que estructuras malformadas se interpreten parcialmente (L226-L237). `analyze` no captura todas las excepciones posibles de datos o estructuras inconsistentes (L277-L280).
- **Calidad:** Se mezclan varios analizadores independientes en un archivo; los bloques de VERSIONINFO tienen validación limitada. No se incluyen pruebas aquí.
- **Mejoras:**
  - [alta] Validar que el mapeo RVA→offset quede dentro de los datos disponibles de la sección (L30-L40).
  - [media] Rechazar bloques de versión con longitudes incoherentes, en vez de ajustarlas silenciosamente (L226-L237).
  - [baja] Documentar en la salida que la coincidencia del resumen no valida la firma ni la confianza (L108-L112).

### `eolfi/providers/strings.py`
- **Propósito:** Extrae cadenas ASCII imprimibles de un archivo por bloques y devuelve un recuento y una muestra limitada.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `min_len` y `limit` no se validan; valores inválidos pueden causar errores al compilar la expresión regular o resultados inesperados (L20-L23). Un fallo al abrir o leer el archivo se propaga al llamador (L43-L46).
- **Calidad:** `Path` está importado pero no se usa (L5). No se incluyen pruebas aquí.
- **Mejoras:**
  - [media] Validar `min_len` y `limit` antes de compilar la expresión regular (L20-L23).
  - [baja] Eliminar el import no usado de `Path` (L5).

### `eolfi/providers/triage.py`
- **Propósito:** Calcula el SHA-256 y tamaño de un archivo, detecta su formato por bytes mágicos y aplica una heurística para PyInstaller.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El tamaño, la cabecera, la cola y el hash se leen en operaciones separadas; si el archivo cambia durante el análisis, los resultados pueden corresponder a contenidos distintos (L77-L84).
- **Calidad:** La detección de formato y la heurística PyInstaller son sencillas, pero se basan únicamente en firmas o cadenas (L49-L65, L80-L80). No se incluyen pruebas aquí.
- **Mejoras:**
  - [media] Evitar resultados inconsistentes si el archivo cambia durante el análisis, por ejemplo, verificando metadatos antes y después de las lecturas (L77-L84).
  - [baja] Añadir pruebas para firmas ambiguas y casos de archivo modificado durante el análisis (L49-L65, L77-L84).

### `eolfi/providers/wasm.py`
- **Propósito:** Analiza secciones WebAssembly y extrae importaciones, exportaciones, memorias, nombres y señales de herramientas de compilación.
- **Seguridad:** Varias lecturas de bytes usan el límite global del archivo, no el final de la sección; un módulo malformado puede hacer que el análisis lea datos de una sección posterior (L53-L56, L100-L114, L122-L124).
- **Errores y robustez:** Los límites de elementos se aplican por sección, no globalmente; muchas secciones repetidas pueden acumular grandes listas (L97-L124). Los errores de secciones personalizadas se ignoran, por lo que se pueden omitir metadatos sin indicarlo en el resultado (L85-L96).
- **Calidad:** No se valida el orden ni la unicidad de secciones, y se aceptan versiones sin comprobarlas (L63-L64, L72-L80). No se incluyen pruebas aquí.
- **Mejoras:**
  - [alta] Comprobar cada lectura de bytes contra `s.end` y no solo contra el tamaño del archivo (L53-L56, L100-L114, L122-L124).
  - [media] Aplicar límites globales a importaciones, exportaciones y memorias (L97-L124).
  - [media] Validar versión y estructura de secciones antes de analizarlas (L63-L80).
  - [baja] Registrar los errores de secciones personalizadas en el resultado en vez de descartarlos (L85-L96).

### `eolfi/security/resilience.py`
- **Propósito:** Ejecuta fuzzing sobre un archivo semilla en subprocesos y busca patrones de inyección en binarios. Registra hallazgos en `EvidenceStore`.
- **Seguridad:** L90-L93 ejecuta el runner sin shell y con argumentos separados, pero el subproceso no está aislado como sandbox: hereda el entorno y no tiene límites de memoria ni CPU; el timeout solo limita la duración. L92 captura toda la salida en memoria, lo que puede consumir recursos si el proceso genera mucho contenido. L28-L33 detecta patrones concretos, pero no permite concluir que el contenido se trate como dato.
- **Errores y robustez:** L68-L70 no valida `iters` ni `timeout`; un timeout negativo puede causar `ValueError` en L90-L93. L82-L87 carga el archivo semilla completo y crea un archivo por iteración, por lo que semillas grandes o muchas iteraciones pueden consumir mucho espacio y memoria. L89-L108 no garantiza la limpieza del directorio temporal si ocurre una excepción inesperada.
- **Calidad:** L137-L170 devuelve `treated_as_data: True` sin comprobar ese comportamiento. L28-L33 es una detección heurística y puede producir falsos positivos o negativos. Faltan pruebas visibles para límites, fallos del subproceso y análisis entre bloques.
- **Mejoras:**
  - [alta] Añadir límites de recursos y aislamiento real al subproceso; revisar L90-L93.
  - [alta] Limitar el tamaño de la semilla y de la salida capturada; revisar L74 y L90-L93.
  - [media] Validar `iters` y `timeout` antes de iniciar el trabajo; revisar L68-L70.
  - [media] Garantizar la limpieza del directorio temporal mediante `try/finally`; revisar L82-L112.
  - [media] No afirmar que el contenido se trató como dato sin verificarlo; revisar L167-L170.
  - [baja] Añadir pruebas para detección de patrones y límites de bloques; revisar L137-L170.

### `eolfi/server.py` — parte 1 de 2
- **Propósito:** Implementa la lógica de la API local/remota, el servidor HTTP y sus rutas para análisis, trabajos, archivos, informes y el panel web.
- **Seguridad:**
  - **[Alta]** El canje de códigos de vinculación no requiere autenticación (L964-L965, L1091-L1092). Los códigos tienen solo seis dígitos y el retraso de un segundo por intento no limita intentos concurrentes; falta una defensa eficaz contra fuerza bruta (L471-L490).
  - **[Alta]** El servidor no implementa TLS (L1158-L1168); en modo remoto, el token inicial viaja en la URL y la cookie no lleva `Secure` (L1036-L1040). Sin TLS externo, las credenciales pueden quedar expuestas en tránsito.
  - **[Media]** Se aceptan fuentes HTTP/HTTPS suministradas por el usuario y se entregan al flujo web sin validación de destino visible aquí (L290-L291, L676-L691); revisar protección contra SSRF, incluidas redirecciones y direcciones locales.
  - **[Media]** La comprobación de raíces resuelve la ruta antes de usarla (L278-L285), pero no evita cambios de symlink entre comprobación y acceso; hay riesgo de TOCTOU en rutas locales.
  - **[Media]** El modo remoto revela rutas absolutas y raíces permitidas en errores de validación (L284-L285).
  - No se observan secretos incrustados ni uso directo de `eval`/`exec` en esta parte.
- **Errores y robustez:**
  - **[Media]** El servidor HTTP crea hilos por petición y no se aprecia límite de concurrencia; peticiones lentas o cargas de hasta 256 MB pueden agotar recursos (L38-L39, L945-L957, L1144-L1145).
  - **[Media]** El cuerpo se lee con `read(n)` sin comprobar que se hayan recibido exactamente `n` bytes (L945-L957).
  - **[Media]** La cancelación y el estado de los trabajos se consultan y modifican en distintos puntos fuera de un bloqueo común (L136-L161, L247-L253); pueden darse lecturas inconsistentes.
  - **[Media]** El historial trunca el JSON serializado del cuerpo, que luego se vuelve a decodificar al repetir el trabajo; una fila truncada puede impedir la repetición (L186-L189, L205-L214).
  - **[Baja]** `_remember_name` usa un bloqueo local al proceso, insuficiente para evitar escrituras concurrentes desde varios procesos (L868-L881).
  - **[Baja]** La respuesta del puente se lee íntegramente sin límite de tamaño (L773-L775).
- **Calidad:**
  - La clase `EolfiApp` concentra lógica de negocio, persistencia, red y trabajos; separar responsabilidades facilitaría pruebas y mantenimiento.
  - Faltan límites de tasa y pruebas visibles para vinculación, concurrencia de trabajos, rutas con symlinks y cuerpos HTTP incompletos.
  - El filtrado y paginado de evidencias se hace después de cargar la lista completa, lo que puede resultar costoso con bases grandes (L402-L418).
- **Mejoras:**
  - [alta] Añadir límite de intentos y caducidad efectiva para códigos de vinculación, y limitar su generación por cliente (L471-L490).
  - [alta] Usar TLS para conexiones remotas y marcar la cookie `Secure` cuando corresponda (L1036-L1040, L1158-L1168).
  - [media] Restringir destinos de rastreo web y validar cada redirección para evitar SSRF (L290-L291, L676-L691).
  - [media] Comprobar la longitud real de cada cuerpo y rechazar explícitamente `Transfer-Encoding` no admitido (L945-L957).
  - [media] Aplicar límites de concurrencia y tamaño a las respuestas del puente (L773-L775, L1144-L1145).
  - [baja] Evitar truncar JSON persistido o validar la fila antes de permitir repetir un trabajo (L186-L189, L205-L214).

### `eolfi/server.py` — parte 2 de 2
- **Propósito:** Inicia y cierra el servidor HTTP. Implementa el modo `--reload`, que vigila cambios y reinicia el proceso hijo.
- **Seguridad:** L1196-L1197: imprime el token de acceso en una URL; puede quedar expuesto en el historial del terminal o en registros. No se observa uso de shell al crear el proceso hijo (L1228).
- **Errores y robustez:** L1244: tras `kill()` no espera a que termine el proceso; L1247: al interrumpir, tampoco espera tras `terminate()`. El hijo podría seguir activo brevemente mientras se inicia otro.
- **Calidad:** `_snapshot` descarta silenciosamente errores de lectura de metadatos (L1215-L1218), lo que puede ocultar cambios. No se aprecian pruebas en este fragmento.
- **Mejoras:**
  - [media] Evitar imprimir el token en la URL o advertir sobre su exposición (L1196-L1197).
  - [media] Esperar al proceso hijo tras `kill()` y `terminate()` (L1244, L1247).
  - [baja] Informar de errores al obtener metadatos, en vez de ignorarlos silenciosamente (L1215-L1218).

### `eolfi/sites/fetch.py`
- **Propósito:** Descarga recursos HTTP/HTTPS con límites de tamaño y tiempo, respeto de `robots.txt` y controles anti-SSRF.
- **Seguridad:** [Alta] La primera URL puede habilitar `allow_private` si su DNS devuelve alguna IP privada; desde entonces se permiten conexiones privadas para las demás URLs del mismo `Fetcher` (L74-L80, L173-L177). La conexión fijada valida la IP efectiva, pero no corrige ese permiso inicial demasiado amplio (L87-L93).
- **Errores y robustez:** La resolución DNS síncrona no queda limitada por el plazo total de la descarga (L87-L89, L247-L250). El estado compartido (`_deadline`, `_timers`, `_last` y `total`) no está protegido frente a llamadas concurrentes, lo que puede interferir con plazos y límites (L159-L167, L232-L245, L306-L308).
- **Calidad:** `_raw_get_inner` concentra validación, redirecciones, lectura y contabilización en una función extensa (L247-L313). No se incluyen pruebas en este archivo; la cobertura externa no es verificable.
- **Mejoras:**
  - [alta] Determinar el permiso para direcciones privadas de forma explícita y segura; no habilitarlo por una resolución DNS mixta (L74-L80, L173-L177).
  - [media] Aislar el estado por petición o sincronizar el acceso para evitar carreras entre descargas concurrentes (L159-L167, L232-L245, L306-L308).
  - [media] Aplicar un límite o estrategia con plazo a la resolución DNS (L87-L89, L247-L250).
  - [baja] Separar `_raw_get_inner` en funciones para redirecciones, lectura y contabilización (L247-L313).

### `eolfi/sites/repo.py`
- **Propósito:** Clona o analiza repositorios locales y extrae información sobre lenguajes, dependencias, estructura, calidad y documentación. No ejecuta los scripts del repositorio.
- **Seguridad:** [media] La comprobación anti-SSRF valida el host antes de clonar, pero no fija la dirección IP usada por Git; un cambio de resolución entre ambas operaciones podría eludirla (L174-L201). [media] El clon permite SSH a hosts públicos y desactiva el agente, pero no impide explícitamente que SSH use claves de identidad predeterminadas (L109, L124, L198-L201). [media] El límite de 5 MB es por blob, no por repositorio; un clon con muchos blobs puede consumir disco o recursos en exceso (L197-L201). [baja] Los comandos sugeridos incorporan texto de scripts sin eliminar saltos de línea; si se copian y ejecutan, un `package.json` hostil podría alterar el fragmento generado (L275, L717-L719).
- **Errores y robustez:** `os.walk` no informa de errores de recorrido, por lo que un análisis puede omitir directorios sin indicarlo (L408). La caché global de tamaños se borra y modifica durante los análisis; llamadas concurrentes pueden interferir (L227-L241, L403-L404). La limpieza puede borrar clones antiguos mientras otro análisis aún los usa (L184-L192).
- **Calidad:** Buenas medidas defensivas y límites de lectura, pero el archivo concentra muchos parsers y lógica de análisis. No se incluyen pruebas en el archivo; convendría cubrir formatos hostiles, límites y concurrencia.
- **Mejoras:**
  - [alta] Fijar y verificar las direcciones resueltas durante el clon para cerrar la ventana de SSRF (L174-L201).
  - [media] Limitar el tamaño total y el número de objetos del clon, no solo el tamaño de cada blob (L197-L201).
  - [media] Neutralizar saltos de línea y caracteres de control antes de generar comandos sugeridos (L719).
  - [media] Evitar la carrera de la caché global, por ejemplo, usando una caché local al análisis (L227-L241, L403-L404).
  - [baja] Añadir manejo y registro de errores de recorrido de `os.walk` (L408).

### `eolfi/sites/stack.py`
- **Propósito:** Define tecnologías y sus huellas; detecta tecnologías en contenido web y manifiestos/rutas de repositorios. También calcula tecnologías implícitas y comandos de scaffolding.
- **Seguridad:** Riesgo condicional de XSS si el consumidor muestra las evidencias como HTML sin escaparlas: se interpolan `src`, valores de cabecera y nombres de dependencias en L216, L224 y L243. No ejecuta comandos ni accede al sistema de archivos.
- **Errores y robustez:** No valida tamaños ni tipos de entrada; el recorrido anidado de tecnologías, firmas y contenidos puede consumir muchos recursos con entradas grandes (L209-L224, L234-L245). `deps` no se usa en `_special_repo` (L266).
- **Calidad:** La detección por subcadenas puede producir falsos positivos o negativos por diferencias de mayúsculas y minúsculas (L210-L224). `TECHS` es una lista extensa de firmas mantenidas manualmente (L43-L194).
- **Mejoras:**
  - [alta] Escapar las evidencias al mostrarlas en HTML y documentar el contrato de salida — L216, L224, L243.
  - [media] Limitar o validar el tamaño de las entradas procesadas — L205-L224, L229-L245.
  - [baja] Eliminar el parámetro `deps` sin uso de `_special_repo` — L266.

### `eolfi/sites/webpage.py`
- **Propósito:** Analiza HTML de una URL o un sitio local y genera hallazgos sobre estructura, assets, seguridad, SEO, accesibilidad y tecnologías. También propone un plano de página.
- **Seguridad:** La URL principal se envía al `Fetcher` sin validar aquí si apunta a una dirección privada o local (L501-L506); si el analizador acepta entradas no confiables, podría habilitar SSRF, según las protecciones del `Fetcher`. `cross_origin` permite descargar recursos de otros orígenes (L497-L499). No se observan secretos ni ejecución de contenido.
- **Errores y robustez:** JSON-LD válido pero con `@graph` no iterable puede provocar una excepción no capturada (L812-L814). Los límites de captura pueden excederse con un fragmento grande de texto (L209-L213); además, se acumulan estilos inline sin límite global (L233-L234). El inventario omite cualquier error de lectura o análisis sin registrarlo (L719-L723).
- **Calidad:** `analyze_web` concentra carga, análisis y generación de hallazgos en una función extensa (L497-L689). El análisis CSS/JS basado en patrones es aproximado, como indican sus limitaciones (L666-L667). No se incluyen pruebas en el archivo.
- **Mejoras:**
  - [alta] Aplicar controles de destino para evitar SSRF en la URL principal y revisar que el `Fetcher` los mantenga también con redirecciones (L501-L506).
  - [media] Validar que `@graph` sea una lista antes de iterarlo y manejar estructuras JSON-LD inesperadas (L812-L814).
  - [media] Hacer efectivos los límites de captura por fragmento y establecer un presupuesto total para estilos inline (L209-L213, L233-L234).
  - [baja] Separar `analyze_web` en funciones enfocadas y añadir pruebas para entradas HTML, CSS, JS y JSON-LD malformadas (L497-L689).

### `eolfi/vscode_tools.py`
- **Propósito:** Envía acciones a la extensión puente de VS Code y devuelve su respuesta.
- **Seguridad:** El token de autorización se envía a la URL obtenida del puente; la seguridad depende de que `read_vscode_bridge()` devuelva una URL confiable (L24-L27). La validación de rutas y permisos se delega a la extensión.
- **Errores y robustez:** No valida el formato de la configuración del puente ni el valor de `timeout` antes de usarlos (L21, L24-L27).
- **Calidad:** Interfaz breve y clara; no se muestran pruebas.
- **Mejoras:**
  - [media] Validar la configuración del puente y limitar `timeout` (L21, L24-L27).

### `eolfi/vscode_web.py`
- **Propósito:** Arranca y controla una instancia local de VS Code Web, protegida con un token aleatorio.
- **Seguridad:** El token se incluye en la URL como parámetro de consulta (L47-L52); puede quedar expuesto en registros o en el contexto del navegador. La carpeta recibida se pasa a VS Code sin comprobar que esté dentro del workspace (L82-L83). La aceptación de licencia depende de quien invoque `start()` (L63-L68).
- **Errores y robustez:** Si vence la espera, el proceso no se detiene (L90-L100). Se libera el puerto antes de que el subproceso lo use, lo que permite una carrera (L74-L76, L85). `stop()` no espera la terminación ni cierra explícitamente `stdout` (L111-L119).
- **Calidad:** La gestión de ciclo de vida combina inicio, espera y registro en una clase; no se muestran pruebas.
- **Mejoras:**
  - [alta] Asegurar la carpeta permitida antes de iniciar el servidor (L59, L82-L83).
  - [media] Detener el proceso si vence la espera y esperar su cierre en `stop()` (L90-L100, L111-L119).
  - [media] Evitar transportar el token en la URL o mitigar su exposición (L47-L52).

### `eolfi/vscode-bridge/agent-tools.js`
- **Propósito:** Define herramientas de terminal y acceso web para el agente, con permisos y registro.
- **Seguridad:** La lista de bloqueo de comandos es una comprobación textual evadible; después se ejecuta la orden mediante un shell con permisos del usuario (L29-L35, L97-L102). En Windows se usa `-ExecutionPolicy Bypass` (L100). La comprobación DNS no fija la dirección validada a la conexión; la resolución posterior de `fetch` permite riesgo de DNS rebinding/SSRF (L49-L59, L145-L146). El cuerpo se carga entero antes de truncarlo, por lo que `MAX_PAGE` no limita la memoria usada (L151).
- **Errores y robustez:** Si `runInTerminal` falla tras haber ejecutado la orden, se vuelve a intentar por shell, con riesgo de duplicar efectos (L131). La cancelación mata el proceso directo, no necesariamente sus descendientes (L107-L110).
- **Calidad:** `htmlToText` usa sustituciones regulares simples y no es un parser HTML (L62-L69). No se muestran pruebas.
- **Mejoras:**
  - [alta] Sustituir la lista de bloqueo por una política de ejecución más restrictiva y explícita (L29-L35, L97-L102).
  - [alta] Fijar la resolución DNS validada a la conexión HTTP y limitar la lectura del cuerpo en streaming (L49-L59, L145-L151).
  - [media] Evitar reejecutar una orden si falla la integración de terminal tras iniciarla (L131).
  - [baja] Añadir pruebas para las reglas de comandos, direcciones IP y extracción HTML (L29-L69).

### `eolfi/vscode-bridge/audit.js`
- **Propósito:** Inventaría archivos, los agrupa para su revisión por un modelo y guarda el progreso e informe.
- **Seguridad:** El estado cargado desde JSON no se valida; sus rutas se reutilizan para leer archivos y podrían salir de `root` si el estado se manipula (L121, L143-L146, L168-L170). El contenido de los archivos se incorpora al prompt sin delimitarlo de forma resistente a instrucciones o separadores falsificados (L105-L113); la plantilla contiene instrucciones dirigidas al modelo, que aquí se tratan como datos del archivo auditado (L89-L102). El contenido se envía a `deps.complete` (L184-L186).
- **Errores y robustez:** Se tragan errores al recorrer directorios y al leer metadatos o archivos (L29, L43, L170). La constante `MAX_FILE` no se aplica y los archivos se leen completos en memoria (L19, L53-L56). Un estado reanudado puede estar desactualizado o inconsistente (L143-L146).
- **Calidad:** El flujo de auditoría y generación del informe está concentrado en una función extensa (L141-L210). No se muestran pruebas.
- **Mejoras:**
  - [alta] Validar el estado reanudado y restringir cada ruta a `root` antes de leerla (L121, L143-L146, L168-L170).
  - [alta] Delimitar de forma robusta el contenido de archivos y tratarlo como entrada no confiable al construir prompts (L105-L113).
  - [media] Aplicar límites de tamaño y evitar lecturas completas de archivos grandes (L19, L53-L56).
  - [media] Registrar o comunicar los errores de inventario y lectura en vez de omitirlos silenciosamente (L29, L43, L170).

### `eolfi/vscode-bridge/chat.js`
- **Propósito:** Implementa el participante `@eolfi` de VS Code: análisis, consultas a herramientas, auditorías por archivo e historial.
- **Seguridad:** L81 permite URLs HTTP(S) y L161/L376 las envían al análisis; si el servidor las obtiene, podría existir SSRF (no verificable aquí). L254 y L496 envían solicitudes al modelo de VS Code; el propio archivo advierte en L71 que el modelo se ejecuta en la nube. El código contiene instrucciones para el modelo, por ejemplo en L432-L436; son datos del archivo, no instrucciones para esta revisión. La defensa frente a instrucciones maliciosas en resultados se basa en texto del prompt (L430-L431, L460), no en una validación técnica visible.
- **Errores y robustez:** L167 y L382 descartan errores de consulta de incógnitas y muestran resultados parciales. L273, L294, L513 y L545 usan una escala de espera tomada del entorno sin validar; un valor inválido puede alterar los reintentos. L695 presupone que `request.prompt` existe y es texto.
- **Calidad:** `ask` concentra mucha lógica y un prompt extenso (L415-L610), lo que dificulta cambios y pruebas. No se observan pruebas en el archivo; no puede determinarse si existen en otra parte.
- **Mejoras:**
  - [alta] Validar y restringir destinos URL antes de enviarlos al análisis; comprobar también las restricciones en el servidor (L81, L161).
  - [media] Validar que `request.prompt` sea una cadena antes de usar `.trim()` (L695).
  - [media] Validar la escala de espera del entorno y establecer límites razonables (L273, L294).
  - [media] Registrar o comunicar explícitamente los fallos de consulta de incógnitas, en vez de ocultarlos (L167, L382).
  - [baja] Extraer el prompt y las etapas principales de `ask` en módulos o funciones más pequeñas, y añadir pruebas para reintentos y cancelación (L415-L610).

### `eolfi/vscode-bridge/core.js`
- **Propósito:** Implementa el chat con modelos y herramientas de VS Code, y expone rutas HTTP locales protegidas por token.
- **Seguridad:** El indicador `auto_approve` recibido en la petición puede habilitar escrituras sin confirmación si la acción lo acepta (L104, L143). El límite de tamaño deja de almacenar el cuerpo, pero sigue leyéndolo hasta el final, lo que permite consumir recursos con cargas excesivas (L209-L211, L229-L231).
- **Errores y robustez:** No se valida la estructura de `messages` ni de las entradas antes de procesarlas; datos malformados pueden provocar errores durante el chat (L68-L79, L83-L85). La URL de la petición se construye fuera de un bloque de manejo de errores (L186-L187). La ruta directa de herramientas no libera explícitamente su `CancellationTokenSource` (L239-L242).
- **Calidad:** `chat` concentra selección de modelos, herramientas, escrituras, registro y reversión en una función extensa (L82-L177). La lógica de lectura del cuerpo HTTP está duplicada (L207-L220, L227-L245).
- **Mejoras:**
  - [alta] Exigir confirmación efectiva para escrituras y no confiar en `auto_approve` enviado por el cliente (L104, L143).
  - [media] Abortar la lectura al superar `MAX_BODY`, en vez de seguir consumiendo el flujo (L209-L211, L229-L231).
  - [media] Validar el esquema de mensajes y liberar el token de cancelación de la ruta directa (L83-L85, L239-L242).
  - [baja] Extraer el manejo común del cuerpo HTTP y dividir `chat` en funciones más pequeñas (L82-L177, L207-L245).

### `eolfi/vscode-bridge/e2e/launch.js`
- **Propósito:** Inicia VS Code con un perfil temporal para ejecutar una prueba e2e y mostrar su resultado.
- **Seguridad:** En Windows se usa `shell: true` con una cadena de argumentos cuya función de comillas solo escapa espacios y comillas, no todos los metacaracteres del shell (L19-L21).
- **Errores y robustez:** No se maneja el evento de error del proceso iniciado ni se comprueba que haya terminado correctamente (L20-L21). Un JSON de resultado inválido hace fallar la lectura dentro del temporizador (L27). El directorio temporal no se elimina al terminar (L10, L31-L34).
- **Calidad:** El flujo de espera y lectura es sencillo, pero no se separan el lanzamiento, la validación del resultado y la limpieza.
- **Mejoras:**
  - [media] Evitar `shell: true` o construir los argumentos de Windows con un mecanismo de escape seguro (L19-L21).
  - [media] Gestionar errores de inicio y JSON inválido, y limpiar el perfil temporal al finalizar (L10, L20-L21, L27-L34).

### `eolfi/vscode-bridge/e2e/run.js`
- **Propósito:** Ejecuta pruebas de integración dentro de VS Code, incluida la vinculación al servidor y el uso del manejador de chat.
- **Seguridad:** El objetivo recibido por variable de entorno se envía al servidor real para analizarlo; debe considerarse entrada no confiable si el entorno de ejecución no lo controla (L12, L60-L64). La limpieza elimina todos los clientes creados dentro de una ventana temporal, no solo el creado por esta prueba (L84-L87).
- **Errores y robustez:** Si ocurre una excepción antes del cierre de sesión, la vinculación temporal puede quedar activa (L82-L91). Las peticiones HTTP no tienen tiempo límite y pueden dejar la prueba esperando indefinidamente (L14-L20).
- **Calidad:** La prueba acumula muchos escenarios en una sola función y no garantiza limpieza mediante un bloque `finally` (L33-L92).
- **Mejoras:**
  - [alta] Revocar únicamente el cliente creado por esta prueba, identificándolo de forma inequívoca (L84-L87).
  - [media] Asegurar la revocación y el cierre de sesión en un bloque `finally` (L82-L91).
  - [media] Añadir límites de tiempo a las peticiones HTTP (L14-L20).

### `eolfi/vscode-bridge/eolfi-client.js`
- **Propósito:** Proporciona un cliente HTTP para el servidor Eolfi y resume informes de análisis.
- **Seguridad:** `base` puede apuntar a cualquier host y el token de autorización se envía a ese destino; un valor no confiable podría exfiltrar el token o dirigir solicitudes a otros servicios (L8-L16, L40-L46). El parámetro `format` se interpola en la URL sin codificación (L66).
- **Errores y robustez:** Las respuestas se acumulan sin límite de tamaño (L18-L21). El análisis puede sondear indefinidamente si el trabajo no alcanza un estado terminal y no se solicita cancelación (L52-L63).
- **Calidad:** El sondeo fijo cada 700 ms es simple, pero no aplica espera progresiva ni un plazo total para el trabajo (L57-L63).
- **Mejoras:**
  - [alta] Validar `base` contra destinos permitidos antes de enviar solicitudes o credenciales (L8-L16, L40-L46).
  - [media] Limitar el tamaño de las respuestas y establecer un plazo máximo para el sondeo (L18-L21, L52-L63).
  - [baja] Codificar `format` al construir la URL (L66).

### `eolfi/vscode-bridge/extension.js`
- **Propósito:** Integra Eolfi con VS Code: gestiona el puente local, la sesión, los análisis y el chat con herramientas del agente.
- **Seguridad:** L334–335 valida solo el prefijo `http(s)`, no el destino de la URL; la protección frente a SSRF depende del servidor. L41–42 silencia errores al leer o borrar el archivo de credenciales. L178–179 registra eventos en un archivo sin fijar permisos; puede contener datos sensibles.
- **Errores y robustez:** L50–58 no gestiona errores del servidor ni fallos al escribir el archivo en la callback de escucha. L164–165 no limpia el temporizador ni la suscripción de cancelación al terminar normalmente; el temporizador podría interrumpir una orden posterior. L154–157 puede resolver dos veces la espera de integración.
- **Calidad:** Archivo extenso que concentra ciclo de vida, autenticación, interfaz y ejecución de herramientas; convendría dividir responsabilidades y añadir pruebas de los casos de error.
- **Mejoras:**
  - [alta] L164–165: limpiar el temporizador y la suscripción de cancelación al finalizar la ejecución.
  - [media] L31–35: asegurar permisos del archivo temporal incluso si ya existe y gestionar errores de escritura.
  - [media] L334–335: validar destinos de URL conforme a la política del servidor.
  - [media] L178–179: restringir permisos del registro y evitar guardar datos sensibles.

### `eolfi/vscode-bridge/fixtures/fake-mcp.js`
- **Propósito:** Simula un servidor MCP por entrada/salida estándar para probar el cliente de REA.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** L10: una línea JSON malformada provoca una excepción no gestionada y termina el proceso.
- **Calidad:** Fixture pequeño y legible; cubre inicialización, paginación, llamadas y métodos desconocidos.
- **Mejoras:**
  - [baja] L10: capturar errores de parseo para que una entrada inválida no cierre el servidor de pruebas.

### `eolfi/vscode-bridge/history.js`
- **Propósito:** Guarda, busca, presenta y borra el historial del agente en un archivo JSONL local.
- **Seguridad:** L43–49 guarda solicitudes, respuestas, rutas y herramientas potencialmente sensibles sin cifrado. L51–52 crea y añade al archivo sin fijar permisos.
- **Errores y robustez:** L15 y L19 descartan errores de lectura o líneas dañadas sin informar. L27, L63–67 pueden fallar si el archivo contiene JSON válido que no tenga la estructura esperada, por ejemplo `null`.
- **Calidad:** La búsqueda por carpeta usa prefijo textual (L65), lo que puede mezclar rutas con prefijos coincidentes; faltan pruebas visibles para datos corruptos y concurrencia entre procesos.
- **Mejoras:**
  - [media] L51–52: fijar permisos restrictivos y documentar el tratamiento de datos sensibles.
  - [media] L27, L63–67: validar la estructura de cada entrada antes de usarla.
  - [baja] L65: comparar límites de directorio, no solo prefijos.

### `eolfi/vscode-bridge/package.json`
- **Propósito:** Define la extensión de VS Code, sus comandos, ajustes, menús, participante de chat y scripts.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** L10–12 limita la compatibilidad declarada a VS Code `^1.95.0`; no se puede comprobar aquí la compatibilidad efectiva de todas las API usadas.
- **Calidad:** Manifiesto estructurado; varios ajustes habilitan terminal e internet por defecto (L135–143), aunque las descripciones indican que se solicita permiso.
- **Mejoras:**
  - [media] L135–143: reconsiderar los valores predeterminados de terminal e internet y aclarar el alcance de los permisos.
  - [baja] L285–287: complementar los scripts declarados con una indicación de cobertura de pruebas o validación del manifiesto.

### `eolfi/vscode-bridge/rea.js`
- **Propósito:** Cliente MCP por stdio para iniciar un servidor REA, descubrir herramientas y ejecutarlas.
- **Seguridad:** La configuración permite ejecutar cualquier `command` con sus `args` (L15, L21-L22, L46); solo debe aceptarse desde una fuente de confianza. El proceso hereda todas las variables de entorno, que pueden incluir secretos (L46). La política de confirmación confía en anotaciones del servidor: una herramienta marcada como de solo lectura evita la confirmación incluso si su nombre indica una acción de ejecución o modificación (L128-L140).
- **Errores y robustez:** La salida sin saltos de línea puede crecer sin límite en memoria (L47-L54). No se controlan errores ni contrapresión al escribir en stdin (L85-L96). `dispose()` no rechaza solicitudes pendientes ni limpia sus temporizadores directamente (L120-L124). La respuesta se almacena completa antes de aplicar el límite de tamaño (L116-L117).
- **Calidad:** `checkArgs()` comprueba campos obligatorios y adicionales, pero no tipos ni valores de enum (L164-L172). Se silencian errores de lectura y parseo de configuración, dificultando el diagnóstico (L17-L24).
- **Mejoras:**
  - [alta] Limitar las confirmaciones por nombre de herramienta, aunque el servidor la marque como de solo lectura (L128-L140).
  - [alta] Reducir las variables de entorno heredadas al mínimo necesario (L46).
  - [media] Validar y restringir el comando configurado a fuentes de confianza (L14-L22, L46).
  - [media] Limitar el búfer de stdout y el tamaño de las respuestas antes de acumularlas (L47-L54, L116-L117).
  - [media] Gestionar errores y contrapresión de stdin y rechazar solicitudes pendientes al cerrar (L85-L96, L120-L124).
  - [baja] Validar tipos y enums conforme al esquema de argumentos (L164-L172).

### `eolfi/vscode-bridge/test/agent-tools.test.js`
- **Propósito:** Pruebas de herramientas de terminal y web, incluidos controles de comandos, permisos, SSRF y extracción de texto HTML.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Los directorios temporales no se eliminan al terminar las pruebas (L11-L23, L32). Los dobles de prueba no cubren errores del proceso ni fallos de red.
- **Calidad:** Buena cobertura de casos de seguridad representativos; faltan casos para fallos de ejecución y respuestas web malformadas (L26-L55, L57-L90).
- **Mejoras:**
  - [media] Limpiar los directorios temporales creados por las pruebas (L11-L23, L32).
  - [baja] Añadir pruebas de errores del proceso y respuestas web incompletas o malformadas (L26-L55, L71-L79).

### `eolfi/vscode-bridge/test/audit.test.js`
- **Propósito:** Prueba el inventario de archivos, la división en partes, la auditoría completa y su pausa y reanudación.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Los directorios temporales del proyecto y del estado no se eliminan al terminar las pruebas (L11-L12, L32).
- **Calidad:** Cubre los flujos principales, incluidos secretos y archivos excluidos mediante fixtures (L13-L22, L50-L106). No prueba errores de lectura ni de escritura del informe.
- **Mejoras:**
  - [media] Eliminar los directorios temporales al finalizar las pruebas (L11-L12, L32).
  - [baja] Añadir pruebas de fallos de lectura y escritura del informe (L71-L106).

### `eolfi/vscode-bridge/test/chat.test.js`
- **Propósito:** Prueba el manejador de chat de Eolfi: comandos, herramientas, modelos, historial y auditorías. También comprueba casos de errores, límites y protección de secretos.
- **Seguridad:** Sin hallazgos directos; el token de L173 es sintético y la prueba comprueba que no se filtre en L189. L209 ejecuta un fixture local con `process.execPath` y sin shell. La prueba de rutas de L58-L67 no cubre traversal ni enlaces simbólicos.
- **Errores y robustez:** Las pruebas modifican variables globales de entorno y las restauran solo al final del flujo normal (por ejemplo, L442-L463 y L522-L547); si una aserción falla, pueden contaminar pruebas posteriores. Se crean directorios y archivos temporales sin eliminarlos (por ejemplo, L59-L60, L327-L328).
- **Calidad:** Buena cobertura funcional, aunque el archivo concentra muchos escenarios distintos. En L409, `D:\Eolfi` no representa fielmente una ruta Windows porque `\E` no está escapado.
- **Mejoras:**
  - [alta] Restaurar las variables de entorno en `finally` o con limpieza registrada por prueba; revisar L442-L463, L465-L487, L501-L519 y L522-L547.
  - [media] Escapar la barra invertida de la ruta de prueba en L409.
  - [media] Eliminar directorios y archivos temporales al terminar cada prueba; por ejemplo, L59-L60 y L327-L328.
  - [media] Añadir casos de traversal y enlaces simbólicos a las pruebas de `resolveTarget` en L58-L67.
  - [baja] Separar las pruebas por áreas para facilitar mantenimiento; L58-L681.

### `eolfi/vscode-bridge/test/core.test.js`
- **Propósito:** Prueba el puente HTTP, la autenticación, el chat, las herramientas permitidas y la recuperación ante fallos.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `srv.close()` no se espera antes de terminar cada prueba (L58, L69, L90), lo que puede dejar el cierre pendiente.
- **Calidad:** Cubre los flujos principales, pero no prueba respuestas ante cuerpos inválidos ni límites de entrada.
- **Mejoras:**
  - [baja] Esperar el cierre del servidor en los bloques `finally` (L58, L69, L90).
  - [baja] Añadir pruebas para solicitudes malformadas y entradas fuera de límites (L61-L90).

### `eolfi/vscode-bridge/test/history.test.js`
- **Propósito:** Comprueba la búsqueda, el formato, la persistencia y el recorte por antigüedad del historial.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Los directorios y archivos temporales creados por las pruebas no se eliminan (L9, L29-L37).
- **Calidad:** Las pruebas cubren búsquedas y líneas dañadas; no comprueban concurrencia ni fallos de escritura.
- **Mejoras:**
  - [baja] Eliminar los recursos temporales al terminar cada prueba (L9, L29-L37).
  - [baja] Añadir cobertura para errores de persistencia y accesos concurrentes (L11-L37).

### `eolfi/vscode-bridge/test/rea.test.js`
- **Propósito:** Prueba la lectura de configuración MCP, el cliente, la detección de herramientas de solo lectura y las confirmaciones.
- **Seguridad:** Sin hallazgos; el cliente se prueba con un ejecutable de fixture local (L9, L20-L28).
- **Errores y robustez:** El directorio temporal de configuración no se elimina (L12-L17).
- **Calidad:** Buena cobertura de reglas de confirmación; faltan casos para errores de configuración y fallos del proceso MCP.
- **Mejoras:**
  - [baja] Limpiar el directorio temporal al acabar la prueba (L12-L17).
  - [baja] Probar errores de inicio, timeout y respuestas inválidas del cliente (L20-L28).

### `eolfi/vscode-bridge/test/workspace.test.js`
- **Propósito:** Prueba las acciones de lectura, escritura, apertura, comandos, diarios y deshacer en un workspace temporal.
- **Seguridad:** Sin hallazgos en el código de prueba.
- **Errores y robustez:** Los workspaces temporales no se eliminan (L63-L68). El mock de `applyEdit` simplifica las operaciones y puede no reproducir fallos reales de VS Code (L50-L56).
- **Calidad:** Buena cobertura de flujos habituales; faltan pruebas de enlaces simbólicos y de apertura de archivos externos.
- **Mejoras:**
  - [baja] Limpiar los workspaces temporales al terminar cada prueba (L63-L68).
  - [media] Añadir casos de rutas con enlaces simbólicos y archivos fuera del workspace (L71-L82, L99-L109).

### `eolfi/vscode-bridge/workspace.js`
- **Propósito:** Expone acciones de lectura, búsqueda, escritura y control de VS Code, con confirmaciones, filtros de secretos y diarios de cambios.
- **Seguridad:** `resolveInside` valida rutas de forma léxica, pero no resuelve enlaces simbólicos; una ruta dentro del workspace que atraviese un enlace podría acceder fuera de él (L42-L49; uso en L140-L145 y L195-L205). `open` acepta rutas absolutas y permite abrir archivos externos sin confirmación ni aplicar el filtro de secretos (L171-L185).
- **Errores y robustez:** Una lectura por rango lee el archivo completo antes de limitar la respuesta, lo que puede consumir mucha memoria (L144-L151). `undo` elimina el diario aunque algunas restauraciones fallen, impidiendo reintentarlas (L268-L282). `append` ignora errores al crear el directorio (L247). Si falla la apertura del diff o el diálogo, las propuestas pueden quedar en el mapa (L75-L89, L96-L98).
- **Calidad:** Las acciones concentran bastante lógica en una sola función; los topes de tamaño y permisos no son uniformes entre acciones. El límite de lecturas por archivo no limita el volumen total de búsqueda (L154-L168).
- **Mejoras:**
  - [alta] Resolver rutas reales y verificar que no escapen del workspace ni atraviesen enlaces simbólicos antes de leer o escribir (L42-L49).
  - [alta] Restringir `open` al workspace o exigir confirmación y aplicar el filtro de secretos a rutas externas (L171-L185).
  - [media] Limitar la lectura física de archivos grandes también cuando se solicitan rangos (L144-L151).
  - [media] Conservar el diario si falla alguna restauración y comunicar qué archivos no se revirtieron (L268-L282).
  - [media] Garantizar la limpieza de propuestas mediante `finally` y no ignorar errores de creación de directorios (L75-L98, L247).
  - [baja] Imponer un presupuesto total de bytes o tiempo para la búsqueda (L154-L168).

### `eolfi/web/app.js`
- **Propósito:** Gestiona la interfaz web de Eolfi: análisis de evidencias, trabajos, chats, creación de proyectos y acceso a VS Code.
- **Seguridad:** L388-L405 y L795, L829 envían rutas y fuentes introducidas por el usuario a la API; las fuentes web también permiten opciones de cruce de origen y omisión de `robots.txt` (L399-L402). El servidor debe validar rutas, limitar el acceso al sistema de archivos y prevenir SSRF; este archivo no permite confirmar si lo hace. L564 interpola el proveedor en una URL sin codificarlo: conviene usar `encodeURIComponent`.
- **Errores y robustez:** L38-L46 consulta trabajos indefinidamente, sin límite de tiempo ni cancelación. L982-L992, si falla una consulta de trabajos, no programa el siguiente refresco. L737 puede lanzar `URIError` ante un fragmento mal codificado. L280 presupone que `operation` y `provider` son cadenas.
- **Calidad:** Archivo extenso que concentra numerosas responsabilidades; `renderSummary` (L150-L260) es especialmente largo. No se observan pruebas en este archivo.
- **Mejoras:**
  - [alta] Validar y restringir en el servidor las rutas y fuentes recibidas, con protección frente a SSRF y path traversal; revisar L388-L405 y L795, L829.
  - [media] Añadir timeout y cancelación al sondeo de trabajos; L38-L46.
  - [media] Reanudar el sondeo de trabajos tras errores transitorios; L982-L992.
  - [baja] Codificar el proveedor al construir la URL; L564.
  - [baja] Dividir `renderSummary` y separar responsabilidades del archivo; L150-L260.

### `eolfi/web/index.html`
- **Propósito:** Define la interfaz del panel de Eolfi: análisis, proyectos, chats, trabajos y configuración.
- **Seguridad:** El iframe integrado permite lectura y escritura del portapapeles (L275); limitar esa capacidad al contenido de confianza.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** La estructura reúne muchas vistas en un único documento.
- **Mejoras:**
  - [media] L275: Restringir los permisos del iframe a los estrictamente necesarios.

### `eolfi/web/style.css`
- **Propósito:** Define los temas, la disposición y los estilos de los componentes del panel.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** La regla para `.chat-tabs .dot.busy` está duplicada (L80, L138).
- **Mejoras:**
  - [baja] L138: Consolidar la regla duplicada de `.chat-tabs .dot.busy`.

### `eolfi/web/theme.js`
- **Propósito:** Aplica el tema guardado antes de que se muestre la página.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El acceso a `localStorage` está protegido ante excepciones (L2-L5).
- **Calidad:** Código breve y claro.
- **Mejoras:**
  - [baja] L3-L4: Considerar sincronizar el tema inicial con el selector de la interfaz.

### `pyproject.toml`
- **Propósito:** Configura los metadatos, dependencias, comandos y empaquetado del proyecto Python.
- **Seguridad:** Las dependencias opcionales no especifican versiones ni rangos (L24-L25), lo que reduce la reproducibilidad y el control de cambios de la cadena de suministro.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** La configuración es directa y documenta el propósito de las dependencias opcionales.
- **Mejoras:**
  - [media] L24-L25: Fijar versiones o definir rangos compatibles para las dependencias opcionales.

### `tests/conftest.py`
- **Propósito:** Evita que las pruebas dependan del archivo `.env` del usuario.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** La variable de entorno se modifica globalmente para el proceso de pruebas (L4), lo que puede afectar pruebas que necesiten otro valor.
- **Calidad:** Configuración mínima y comentada.
- **Mejoras:**
  - [baja] L4: Aislar el cambio de entorno si algunas pruebas deben comprobar otros valores.

### `tests/e2e/bridge-chat.test.mjs`
- **Propósito:** Prueba el adaptador declarativo con un chat simulado local, incluyendo streaming, diagnóstico y comparación entre proveedores.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** L62 no espera el cierre del servidor HTTP; un fallo al arrancar podría dejar recursos abiertos.
- **Calidad:** Buenas comprobaciones de streaming y de que `discover()` no exponga el texto del chat (L110-L118).
- **Mejoras:** [baja] L62 esperar el cierre del servidor y cubrir el cierre ante fallos de inicialización.

### `tests/e2e/package.json`
- **Propósito:** Declara las dependencias y el comando de ejecución de las pruebas E2E.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** El comando de pruebas es sencillo; no se incluye aquí un archivo de bloqueo.
- **Mejoras:** [baja] L6-L10 mantener las dependencias sincronizadas con el archivo de bloqueo del proyecto, si corresponde.

### `tests/e2e/panel.test.mjs`
- **Propósito:** Ejecuta pruebas E2E del panel, incluida la accesibilidad, con un servidor local y un navegador instalado.
- **Seguridad:** L35 inserta una ruta en código Python pasado a `-c`; una ruta con comillas puede alterar ese código. L45-L46 desactiva CSP en el contexto de prueba, de forma explícita y solo para inyectar axe.
- **Errores y robustez:** L20 el puerto aleatorio puede estar ocupado; L24-L29 espera hasta el tiempo límite sin detectar antes si el proceso terminó. L55-L56 no espera la terminación del servidor antes de borrar los temporales.
- **Calidad:** Las pruebas dependen del estado creado por pruebas anteriores, por ejemplo el binario de L77-L90 y el historial de L137-L152.
- **Mejoras:** [alta] L35 pasar la ruta como argumento al proceso Python, sin interpolarla en código. [media] L24-L29 detectar la salida del proceso y L55-L56 esperar su cierre. [media] L77-L152 aislar el estado requerido por cada prueba.

### `tests/elfgen.py`
- **Propósito:** Genera un ELF64 sintético para probar el analizador sin ejecutar el archivo.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos para los datos fijos que construye.
- **Calidad:** L39-L41 y L54-L73 usan constantes numéricas de formato ELF que son poco descriptivas.
- **Mejoras:** [baja] L39-L73 nombrar las constantes de formato para facilitar su revisión.

### `tests/fake_bridge.mjs`
- **Propósito:** Arranca el puente con adaptadores simulados y guarda respuestas y datos de prueba para su consumo por otras pruebas.
- **Seguridad:** L19-L22 usa tokens fijos y aprueba todas las solicitudes; son valores y comportamiento de prueba, no aptos para un servicio real. L14-L15 guarda en un archivo los primeros 40 caracteres de cada prompt, que podrían contener datos sensibles.
- **Errores y robustez:** L9 falla si falta el archivo de respuestas o su JSON es inválido; L16 no comprueba que queden respuestas disponibles.
- **Calidad:** El uso de `process.cwd()` en L8 hace que la ubicación de ejecución afecte a la resolución del servidor.
- **Mejoras:** [media] L14-L15 evitar persistir fragmentos del prompt o redactarlos. [baja] L9 y L16 validar argumentos y disponibilidad de respuestas. [baja] L8 resolver la ruta respecto al archivo del módulo.

### `tests/fixtures.py`
- **Propósito:** Construye muestras sintéticas de formatos binarios, APK, sitios web y repositorios para pruebas.
- **Seguridad:** Sin hallazgos; L129 escribe un valor marcador de prueba en un `.env`, no una credencial real.
- **Errores y robustez:** L84-L85, L112-L114 y L131 fallan si se reutilizan directorios ya existentes. L147-L159 y L185-L203 pueden alcanzar el límite de recursión con árboles profundamente anidados; L254 falla si `flags` no es una clave prevista.
- **Calidad:** La serialización de formatos en funciones largas y llamadas `struct.pack` densas dificulta revisar los datos generados (L142-L205).
- **Mejoras:**
  - [media] Hacer explícito si los constructores admiten directorios existentes (L84-L85, L112-L114).
  - [baja] Añadir validación y pruebas de límites para árboles y parámetros de formato (L147-L159, L242-L256).

### `tests/formats.py`
- **Propósito:** Genera muestras sintéticas de Java, WebAssembly, ELF, DEX e IPA para las pruebas.
- **Seguridad:** Sin hallazgos; las cadenas como `Runtime.exec` y la URL HTTP son datos inertes de fixtures (L27-L31, L130-L131).
- **Errores y robustez:** `build_class` puede fallar al empaquetar nombres UTF-8 de más de 65535 bytes (L17-L20). `build_android_so` no valida `align`, por lo que un valor inválido puede producir un ELF inconsistente (L85-L86, L104-L105).
- **Calidad:** La construcción de estructuras binarias usa bloques densos de empaquetado que son difíciles de mantener (L85-L116, L164-L178).
- **Mejoras:**
  - [media] Validar `align` y los límites de longitud antes de serializar (L17-L20, L85-L105).
  - [baja] Añadir pruebas para parámetros inválidos y estructuras truncadas (L14-L40, L85-L116).

### `tests/test_assist.py`
- **Propósito:** Comprueba la asistencia con cliente simulado, proveedores HTTP locales, rechazo de rutas y restauración ante errores.
- **Seguridad:** El servidor de prueba escucha solo en loopback (L141), pero lee el cuerpo HTTP sin límite de tamaño (L133). La clave usada es un valor de prueba (L186).
- **Errores y robustez:** `FakeClient` lanza `IndexError` si se solicitan más respuestas de las preparadas (L39-L42). Los servidores se apagan, pero no se cierran explícitamente ni se espera la terminación de los hilos (L141-L143, L166-L167, L185-L190).
- **Calidad:** Las pruebas combinan asistencia, proveedores y servidor HTTP en un único módulo; faltan casos para cuerpos inválidos o excesivos en el servidor falso.
- **Mejoras:**
  - [media] Limitar el tamaño del cuerpo recibido por el servidor de prueba (L133).
  - [baja] Cerrar los servidores y esperar a que terminen sus hilos (L141-L143, L166-L167).
  - [baja] Separar las pruebas de proveedores HTTP del resto del módulo (L120-L124).

### `tests/test_binfmt.py`
- **Propósito:** Prueba parsers ELF/PE, detección de formato, métricas de entropía y resistencia a mutaciones.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El bucle de mutaciones solo considera aceptable `ParseError`; otras excepciones hacen fallar la prueba deliberadamente (L93-L105). La cobertura de mutaciones es determinista y acotada a dos semillas (L93-L100).
- **Calidad:** Las pruebas cubren casos sintéticos y una muestra PE del sistema, pero la última depende de Windows (L45-L52).
- **Mejoras:**
  - [baja] Ampliar las semillas y los casos de límites para los parsers (L93-L100).
  - [baja] Añadir pruebas portables para más variantes PE y ELF (L45-L52, L55-L85).

### `tests/test_bridge.py`
- **Propósito:** Prueba la integración del generador y el panel con el puente Node simulado, incluida la reparación de respuestas y el estado del puente.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** La espera de inicio no comprueba que el proceso siga vivo ni que haya creado el archivo (L25-L30). Los procesos se matan sin esperar a que terminen (L33-L35).
- **Calidad:** Buena cobertura de los flujos principales; depende del helper privado `_project` de otro módulo de pruebas (L12).
- **Mejoras:**
  - [media] Comprobar el resultado del inicio y añadir un plazo explícito de espera (L25-L30).
  - [baja] Esperar la terminación de los procesos y cerrar el servidor de pruebas al finalizar (L33-L35, L92).

### `tests/test_evidence.py`
- **Propósito:** Prueba deduplicación, conflictos, exportación e importación de evidencias, y resolución de incógnitas.
- **Seguridad:** Sin hallazgos. El texto con apariencia de SQL se usa como dato de prueba para verificar el rechazo de columnas desconocidas (L58-L65).
- **Errores y robustez:** No se prueban paquetes JSON malformados ni otros casos de importación inválida además de los cubiertos (L47-L85).
- **Calidad:** Las pruebas cubren bien los casos esenciales de integridad e idempotencia.
- **Mejoras:**
  - [baja] Añadir pruebas para JSON inválido y estructuras incompletas del paquete (L47-L55).

### `tests/test_external.py`
- **Propósito:** Prueba el parseo de resultados y los adaptadores de Capa y Rizin con ejecutables simulados.
- **Seguridad:** Sin hallazgos. Los ejecutables simulados se crean a partir de datos controlados por las pruebas (L34-L43).
- **Errores y robustez:** La prueba de fallo de Capa verifica el resultado de error, pero no cubre límites de tiempo ni salidas excesivamente grandes (L67-L72).
- **Calidad:** La sustitución de `PATH` aísla los adaptadores de las instalaciones reales (L45-L48).
- **Mejoras:**
  - [baja] Añadir casos de timeout y salida excesiva para los adaptadores (L51-L92).

### `tests/test_fase_a.py`
- **Propósito:** Reúne pruebas de regresión para seguridad, robustez, generación de proyectos y parsers.
- **Seguridad:** Sin hallazgos. Los comandos de subprocess emplean argumentos separados y datos de prueba controlados (L14-L15, L38-L40, L141-L145).
- **Errores y robustez:** La aserción `... or True` nunca falla y no verifica el resultado de Git (L55-L56). El `except Exception` permite que cualquier error haga pasar esa parte de la prueba (L187-L191). La prueba de entorno modifica y luego elimina `SSH_AUTH_SOCK`, incluso si ya existía antes (L62-L66).
- **Calidad:** Archivo muy extenso y con pruebas de áreas diversas; varios límites temporales estrictos pueden producir fallos dependientes de la máquina (L192, L205).
- **Mejoras:**
  - [alta] Sustituir la aserción siempre verdadera por una comprobación efectiva o eliminarla (L55-L56).
  - [media] Restringir la excepción aceptada y comprobar el error esperado (L187-L191).
  - [media] Usar `monkeypatch` para restaurar el entorno original sin perder valores previos (L62-L66).
  - [baja] Separar las pruebas por área y revisar los límites temporales para reducir flakiness (L192, L205).

### `tests/test_fase_b_sites.py`
- **Propósito:** Prueba regresiones de análisis de sitios y repositorios, flujos y comparación de resultados.
- **Seguridad:** Sin hallazgos. Los scripts ejecutados por `run_diff` se escriben en el directorio temporal con contenido fijo de la prueba (L55-L61).
- **Errores y robustez:** `pytest.raises(Exception)` acepta cualquier excepción, por lo que no confirma el fallo esperado de la clonación (L30-L34).
- **Calidad:** Las pruebas abarcan varias áreas y verifican casos límite útiles; la función `names` se define mediante una lambda para una operación simple (L70).
- **Mejoras:**
  - [media] Comprobar una excepción concreta en lugar de cualquier `Exception` (L30-L34).
  - [baja] Reemplazar la lambda por una función con nombre para mejorar la claridad (L70).

### `tests/test_fase_b.py`
- **Propósito:** Prueba mejoras del servidor, el generador, los analizadores y la importación de evidencias.
- **Seguridad:** L71 usa `secreto123` como token de prueba, no como secreto de producción. L103-L104 solo comprueba que la petición con `../x` devuelve 202; no verifica el resultado del trabajo ni que no haya acceso fuera de la ruta prevista.
- **Errores y robustez:** L36-L55 puede dejar el trabajo en bucle si una aserción falla antes de `release.set()`. L15-L18 cierra el servidor, pero no conserva ni une el hilo de servicio.
- **Calidad:** L138-L139 usa `pytest.raises(Exception)`, que acepta excepciones no relacionadas con el caso esperado. L69-L76 no comprueba el registro pese a indicarlo en el docstring.
- **Mejoras:**
  - [media] L103-L104: comprobar que el trabajo termina con error y no accede a rutas externas.
  - [media] L36-L55: asegurar la liberación del evento mediante `finally`.
  - [baja] L138-L139: esperar el tipo de excepción concreto.

### `tests/test_fase_c.py`
- **Propósito:** Prueba casos límite de analizadores, flujos, seguridad, sitios web e integración con el puente LLM.
- **Seguridad:** L110 contiene «ignore previous instructions» como bytes de una muestra de prueba; se trata como dato, no como instrucción para este auditor. L214-L223 comprueba que `DiskLoader` rechaza un archivo hermano, pero no cubre explícitamente enlaces simbólicos ni otras variantes de traversal.
- **Errores y robustez:** L153-L156 sustituye `_raw_get` por una función local, pero no prueba respuestas de robots malformadas ni fallos distintos de red. Sin otros fallos evidentes en estas pruebas.
- **Calidad:** L113 permite que la prueba pase si `ra` no contiene `hits`; L114-L116 no compara directamente los sujetos de ambos archivos.
- **Mejoras:**
  - [media] L113-L116: verificar explícitamente los resultados y sujetos de ambos archivos distintos.
  - [media] L214-L223: añadir casos de enlace simbólico y variantes de traversal.
  - [baja] L148-L156: ampliar los casos de error y respuesta inválida de robots.

### `tests/test_fase_d.py`
- **Propósito:** Cubre casos límite de analizadores y núcleo, CLI, servidor, generador y análisis de sitios.
- **Seguridad:** Sin hallazgos. L195 ejecuta un proceso hijo como parte de una prueba de timeout, con código controlado por el test.
- **Errores y robustez:** L103-L108 y L230-L232 usan tiempo de pared y límites estrictos, lo que puede provocar fallos intermitentes en equipos lentos.
- **Calidad:** L138-L139 acepta cualquier `Exception`, por lo que puede ocultar un fallo distinto al esperado.
- **Mejoras:**
  - [media] L103-L108 y L230-L232: usar reloj monotónico y reducir la sensibilidad a carga variable.
  - [baja] L138-L139: comprobar el tipo de excepción esperado.

### `tests/test_fase_e.py`
- **Propósito:** Prueba mejoras de informes, flujos, parsers, integración con VS Code, autenticación de clientes, configuración y herramientas externas.
- **Seguridad:** Sin hallazgos. Las entradas hostiles se usan como datos de prueba y se comprueba su escape; las llamadas a subprocess y al servidor local usan valores controlados por el test (L38-L44, L123-L131, L179-L209).
- **Errores y robustez:** Los bucles de espera de trabajos tienen un límite, pero no comprueban que el estado haya llegado a `done` antes de continuar (L20-L34); pueden fallar de forma intermitente o con un error poco claro. Varias pruebas crean almacenes sin cierre explícito, por ejemplo L38-L45 y L115-L120, lo que puede retener recursos.
- **Calidad:** Cobertura amplia y pruebas específicas de seguridad. Hay imports sin uso (`json`, L2; `monkeypatch`, L61) y se permite que el CLI devuelva `None` además de `0` (L67), debilitando la comprobación del contrato.
- **Mejoras:**
  - [media] Afirmar explícitamente que el trabajo terminó dentro del plazo y sustituir las pausas fijas por una espera sincronizada (L20-L34).
  - [baja] Cerrar los almacenes y los `ZipFile` abiertos por las pruebas (L38-L45, L115-L120, L142-L159, L353-L357).
  - [baja] Eliminar imports y parámetros no utilizados y precisar el código de salida esperado (L2, L61, L67).

### `tests/test_flows.py`
- **Propósito:** Comprueba el aislamiento de proveedores, la comparación de comandos, la generación SARIF, la creación de proyectos y el listado del sistema de archivos.
- **Seguridad:** Sin hallazgos. Los scripts y archivos que se pasan a los flujos se crean en directorios temporales; los comandos se construyen como listas de argumentos, no como cadenas de shell (L38-L45, L47-L57).
- **Errores y robustez:** Los almacenes de evidencia no se cierran explícitamente (por ejemplo, L28-L35, L55-L61 y L90-L107), lo que puede dejar recursos abiertos durante la suite.
- **Calidad:** Las pruebas cubren casos de fallo y regresión con aserciones útiles. Los imports de `pytest` y `OverwriteSourceError` se hacen dentro del test en vez de junto a los demás (L117-L118).
- **Mejoras:**
  - [baja] Cerrar los almacenes al terminar cada prueba (L28-L35, L55-L61, L78-L81, L90-L107, L116-L127, L134-L137).
  - [baja] Agrupar los imports de la prueba de sobrescritura al inicio del archivo (L117-L118).

### `tests/test_formatos.py`
- **Propósito:** Valida parsers y análisis de Authenticode, .NET, Java/JAR, WebAssembly, APK, DEX e IPA, además de casos malformados y mutaciones.
- **Seguridad:** Sin hallazgos. Las pruebas ejercitan entradas malformadas y contenido hostil como datos; no se observa ejecución de esas entradas (L36-L43, L250-L270, L273-L285).
- **Errores y robustez:** El bucle de mutación invoca ambos proveedores, pero no verifica resultados ni clasifica los errores controlados (L250-L270); la prueba confirma sobre todo que no se propague una excepción.
- **Calidad:** Buena separación por formato y uso de fixtures deterministas. Las rutas de referencia de Windows limitan la cobertura real de PE y .NET a entornos donde existan esos archivos (L11-L12, L47-L48, L85-L86).
- **Mejoras:**
  - [media] Comprobar explícitamente los resultados esperados del fuzz de mutación y distinguir errores de parseo controlados de resultados válidos (L250-L270).
  - [baja] Añadir fixtures portables para mantener cobertura de PE y .NET fuera de Windows (L11-L12, L47-L48, L85-L86).

### `tests/test_hardening.py`
- **Propósito:** Prueba regresiones de seguridad y robustez en analizadores, fetch, clonación, generación y almacenamiento.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `open(staged, "rb")` no se cierra explícitamente (L96); el `EvidenceStore` creado en línea no se cierra (L211). Las mediciones con `time.time()` pueden ser inestables ante ajustes del reloj o carga del sistema (L25-L27, L47-L52, L106-L111).
- **Calidad:** Buena cobertura de entradas hostiles; el archivo agrupa pruebas de varias áreas distintas.
- **Mejoras:**
  - [media] Cerrar el archivo con un gestor de contexto y cerrar el almacén tras la importación (L96, L211).
  - [baja] Usar `time.monotonic()` para las mediciones de duración (L25-L27, L47-L52, L106-L111).
  - [baja] Separar las pruebas por área para facilitar su mantenimiento (L20-L235).

### `tests/test_learn_and_generador.py`
- **Propósito:** Prueba análisis de formatos, sitios y repositorios, además de comparación, STIX y generación de proyectos.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** La prueba de importación FastAPI inserta temporalmente una ruta global y la restaura en `finally` (L271-L283); el patrón es adecuado. No se observan fallos claros adicionales.
- **Calidad:** Cobertura amplia, pero el archivo concentra pruebas de muchas áreas; las comprobaciones de seguridad de autenticación y escritorio verifican principalmente presencia de cadenas (L312-L347).
- **Mejoras:**
  - [media] Añadir pruebas de comportamiento para autenticación, en lugar de limitarse a comprobar nombres de funciones y primitivas en el código generado (L312-L330).
  - [media] Probar el comportamiento de navegación y permisos de la ventana Electron, además de la presencia de opciones de configuración (L334-L347).
  - [baja] Dividir las pruebas por dominio para mejorar su localización y mantenimiento (L25-L418).

### `tests/test_phase4.py`
- **Propósito:** Prueba generación con entradas hostiles, parsers binarios, fetch, API, migraciones y otras funciones de la aplicación.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `time.time()` puede hacer que los límites temporales sean sensibles a ajustes del reloj (L94, L108, L113-L114). Los servidores de prueba no cierran explícitamente el socket ni esperan la terminación de los hilos (L141-L147, L202-L209). El estado global mutable `routes` puede provocar interferencias entre servidores concurrentes (L118-L122).
- **Calidad:** Archivo extenso que agrupa pruebas de subsistemas distintos. La excepción amplia se ignora al construir la semilla ELF, ocultando la causa si falla (L68-L72).
- **Mejoras:**
  - [media] Usar `time.monotonic()` para medir duraciones y plazos (L94, L108, L113-L114).
  - [media] Cerrar los servidores y esperar los hilos en el teardown de los fixtures (L141-L147, L202-L209).
  - [media] Evitar el estado compartido de `routes` entre instancias de servidor (L118-L122).
  - [baja] Registrar el motivo del fallo o limitar las excepciones ignoradas al crear la semilla ELF (L68-L72).
  - [baja] Separar las pruebas por subsistema para facilitar su mantenimiento (L32-L400).

### `tests/test_server.py`
- **Propósito:** Comprueba endpoints HTTP, controles de acceso, carga y análisis de archivos, creación de proyectos y exportaciones.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Las funciones `req` cierran la conexión solo si la petición termina correctamente; una excepción previa puede dejarla abierta (L21-L28). El fixture apaga y cierra el servidor, pero no espera explícitamente la terminación del hilo (L14-L18).
- **Calidad:** Las pruebas cubren varios flujos y controles de seguridad; el helper HTTP concentra la lectura y conversión de respuestas JSON.
- **Mejoras:**
  - [baja] Cerrar la conexión en un bloque `finally` (L21-L28).
  - [baja] Esperar la terminación del hilo tras apagar el servidor (L14-L18).

### `tools/axe-audit.mjs`
- **Propósito:** Ejecuta axe-core en un panel web y muestra infracciones de accesibilidad por vista y tema.
- **Seguridad:** L17-L19 aceptan una URL arbitraria que se abre en Chrome; L25 ejecuta en la página el código JavaScript recibido como argumento. Es comportamiento intencionado para la auditoría, pero los argumentos deben considerarse confiables.
- **Errores y robustez:** Si falla `findBrowser` o la creación de `ChromeEngine`, el perfil temporal puede quedar sin limpiar porque ocurre antes del `try` (L15-L18). Si `engine.close()` falla, tampoco se alcanza `rmSync` (L35-L38).
- **Calidad:** La carga de axe-core y la ejecución de código en la página son directas, pero el script no valida explícitamente las vistas ni la URL antes de iniciar el navegador (L14-L19, L22-L27).
- **Mejoras:**
  - [media] Incluir la creación del motor dentro de una estrategia de limpieza que cubra también errores de inicialización (L15-L18, L35-L38).
  - [media] Garantizar la eliminación del perfil aunque falle `engine.close()` (L35-L38).
  - [baja] Documentar claramente que la URL y los argumentos de vista deben ser confiables (L17-L25).

## Resumen y prioridades

La auditoría identifica riesgos altos concentrados en la ejecución de código, el acceso a red y archivos, y el tratamiento de entradas no confiables.  
Varias mejoras requieren controles en más de una capa —cliente, servidor y procesos auxiliares—, no solo validaciones locales.  
También se necesitan límites de tamaño y aislamiento al procesar código generado y formatos de archivo.  
Se recomienda priorizar estas correcciones antes de habilitar los flujos afectados en entornos remotos o con datos no confiables.

### Ejecución y límites

1. **Restringir y validar acciones, argumentos y comandos de ejecución**, y confirmar los controles de autorización de la extensión. Archivos: `eolfi/cli.py`, `eolfi/vscode_tools.py`, `eolfi/vscode-bridge/core.js`.
2. **Aislar la ejecución de verificaciones y limitar recursos**, incluidos los procesos que analizan código generado. Archivos: `eolfi/corpus.py`, `eolfi/generador/verify.py`, `eolfi/security/resilience.py`.
3. **Validar lanzadores, módulos y rutas de salida de proveedores externos** antes de importar o ejecutar. Archivo: `eolfi/providers/external.py`.
4. **Endurecer el flujo `diff`**: validar corpus, comandos y límites, aplicar `_safe_input` a la repetición y neutralizar nombres temporales. Limitar también el tamaño de las entradas antes de leerlas. Archivos: `eolfi/cli.py`, `eolfi/flows/diff_flow.py`.

### Red y acceso remoto

5. **Aplicar controles SSRF coherentes**, con validación de destinos, direcciones privadas, DNS fijado y redirecciones. Archivos: `eolfi/flows/diff_flow.py`, `eolfi/sites/fetch.py`, `eolfi/sites/repo.py`, `eolfi/sites/webpage.py`, `eolfi/vscode_tools.py`, `eolfi/vscode-bridge/chat.js`, `eolfi/web/app.js`.
6. **Restringir los destinos de `base_url` antes de enviar solicitudes o credenciales.** Archivo: `eolfi/generador/llm.py`.
7. **Proteger el servidor remoto** con TLS, cookies `Secure` cuando corresponda y controles efectivos de autenticación, caducidad y límite de intentos para los códigos de vinculación. Archivo: `eolfi/server.py`.

### Rutas y permisos

8. **Comprobar la contención de rutas resueltas antes de leer, escribir o restaurar archivos**, incluidos enlaces simbólicos y rutas del workspace. Archivos: `eolfi/generador/assist.py`, `eolfi/generador/generators_backend.py`, `eolfi/generador/generators_cli.py`, `eolfi/generador/generators.py`, `eolfi/vscode_tools.py`, `eolfi/vscode-bridge/test/core.test.js`.
9. **Revisar el servidor estático para impedir escapes de la raíz y exposición de archivos**, y corregir el manejo de `.gitignore.extra` para no borrar archivos ajenos ni retirar entradas inexistentes. Archivo: `eolfi/generador/generators.py`.
10. **Proteger las operaciones CRUD con autenticación y autorización, y revisar la exención CSRF.** Archivo: `eolfi/generador/generators_more.py`.

### Salidas generadas y datos no confiables

11. **Escapar y validar valores según su contexto de salida** —código, rutas, HTML, XML, JSX, TOML, CSS y plantillas— antes de interpolarlos. Archivos: `eolfi/core/evidence.py`, `eolfi/generador/generators_backend.py`, `eolfi/generador/generators_cli.py`, `eolfi/generador/generators_mobile.py`, `eolfi/generador/generators_more.py`, `eolfi/generador/generators_tauri.py`, `eolfi/generador/generators.py`, `eolfi/generador/spec.py`, `eolfi/sites/stack.py`.
12. **Delimitar el contenido no confiable y tratarlo explícitamente como datos al construir prompts.** Archivos: `eolfi/generador/assist.py`, `eolfi/vscode_tools.py`.

### Análisis, puente y pruebas

13. **Validar límites de chunks, offsets y tamaños antes de leer datos**, incluidos tamaños descomprimidos y directorios ZIP64. Archivos: `eolfi/generador/verify.py`, `eolfi/providers/axml.py`, `eolfi/providers/dex.py`, `eolfi/providers/macho.py`.
14. **Exigir confirmación efectiva para escrituras y herramientas**, sin confiar en `auto_approve` del cliente; limitar confirmaciones y revocar solo el cliente de prueba correspondiente. Archivos: `eolfi/vscode-bridge/core.js`, `eolfi/vscode-bridge/rea.js`.
15. **Corregir los controles y la limpieza de pruebas**: restaurar variables de entorno, pasar rutas como argumentos, comprobar aserciones y limpiar temporizadores y suscripciones. Archivos: `eolfi/vscode-bridge/extension.js`, `eolfi/vscode-bridge/test/chat.test.js`, `eolfi/vscode-bridge/test/core.test.js`, `tests/e2e/bridge-chat.test.mjs`, `tests/test_bridge.py`.

## Omitidos (2)

- `eolfi/bridge/package-lock.json`: generado o minificado
- `tests/e2e/package-lock.json`: generado o minificado
