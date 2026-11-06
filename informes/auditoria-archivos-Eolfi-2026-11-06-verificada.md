# Auditoría archivo por archivo — Eolfi

- Carpeta: `D:\Eolfi`
- Fecha: 2026-11-06
- Archivos a revisar: 137
- Omitidos: 2 (dependencias, compilados, muestras, minificados o secretos)

## Revisión por archivo

### `.claude/launch.json`
- **Propósito:** Configura el lanzamiento de Eolfi con `serve` en el puerto 8777 y recarga automática.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Configuración breve y clara.
- **Mejoras:** [baja] Documentar cuándo conviene usar `--reload` (L7).

### `.github/workflows/ci.yml`
- **Propósito:** Ejecuta pruebas de Python, del puente y del panel e2e en GitHub Actions.
- **Seguridad:** Las acciones externas se referencian con etiquetas, no con hashes inmutables (L20-L25, L33-L34, L47-L52); esto deja la cadena de suministro expuesta a cambios en esas etiquetas. `npm ci --no-audit` omite avisos de auditoría de npm (L58).
- **Errores y robustez:** La matriz de Python y sistemas operativos mejora la cobertura; no se observan fallos evidentes en el flujo.
- **Calidad:** Flujo organizado por componentes y con permisos de solo lectura para contenidos (L8-L9).
- **Mejoras:** [media] Fijar las acciones a hashes de commit verificados (L20-L25, L33-L34, L47-L52). [baja] Considerar una auditoría de dependencias separada para no perder visibilidad de avisos de npm (L58).

### `.vscode/extensions.json`
- **Propósito:** Recomienda la extensión de VS Code del puente de Eolfi.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Configuración mínima y legible.
- **Mejoras:** Sin mejoras necesarias.

### `eolfi/__init__.py`
- **Propósito:** Documenta el paquete y define su versión, autoría y licencia.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Metadatos concisos; la licencia remite a `LICENSE` (L11).
- **Mejoras:** Sin mejoras necesarias.

### `eolfi/__main__.py`
- **Propósito:** Permite ejecutar Eolfi como módulo y delega la entrada en `eolfi.cli.main`.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Propaga el código de salida de `main()` mediante `SystemExit` (L4).
- **Calidad:** Punto de entrada mínimo y claro.
- **Mejoras:** Sin mejoras necesarias.

### `eolfi/bridge/adapters/core.mjs`
- **Propósito:** Proporciona funciones comunes para cancelar, esperar respuestas y comprobar el origen y la conversación de los adaptadores.
- **Seguridad:** [baja] `EOLFI_BRIDGE_MAX_REPLY_MS=Infinity` elimina el tope temporal efectivo de espera (L20).
- **Errores y robustez:** `sleep` gestiona la cancelación y limpia el temporizador; sin hallazgos adicionales.
- **Calidad:** La lógica de estabilidad de respuesta podría ser más explícita; `stableHits` solo necesita un incremento para devolverla (L29, L42-L45).
- **Mejoras:**
  - [baja] Rechazar valores no finitos para el límite de espera (L20).

### `eolfi/bridge/adapters/declarative.mjs`
- **Propósito:** Implementa un adaptador configurable mediante selectores para chats web, con diagnóstico y envío de mensajes.
- **Seguridad:** [baja] Los selectores de la configuración local no tienen un límite total de cantidad, lo que podría elevar el uso de recursos al procesar una configuración grande (L20-L26). No se observa inyección de código: los valores se serializan con `JSON.stringify`.
- **Errores y robustez:** Un selector inválido aceptado en la configuración puede hacer fallar `readState` y operaciones posteriores; el manejo de errores de selectores solo aparece en `selftest` (L68-L74, L116-L121). `status` oculta cualquier excepción y dificulta diagnosticar su causa (L137-L144).
- **Calidad:** `send` concentra comprobaciones, escritura, envío y seguimiento de la respuesta en una función extensa (L155-L209).
- **Mejoras:**
  - [media] Validar los selectores al cargar la configuración y descartar los inválidos antes de usarlos (L18-L37).
  - [baja] Dividir `send` en pasos con responsabilidades más acotadas (L155-L209).
  - [baja] Conservar información diagnóstica útil al manejar errores en `status` (L137-L144).

### `eolfi/bridge/adapters/deepseek.mjs`
- **Propósito:** Automatiza el envío y la lectura de respuestas de DeepSeek mediante su interfaz visible.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** La detección de respuesta completa depende de selectores y elementos específicos de la interfaz, que pueden cambiar (L128-L131).
- **Calidad:** `send` reúne varias fases de estado, envío y seguimiento; no se ven pruebas en el archivo proporcionado (L49-L102).
- **Mejoras:**
  - [baja] Añadir pruebas para la identificación del turno y los cambios de estructura de la interfaz (L118-L133).
  - [baja] Separar las fases de `send` para facilitar su mantenimiento (L49-L102).

### `eolfi/bridge/adapters/gemini.mjs`
- **Propósito:** Automatiza el envío y la lectura de respuestas de Gemini mediante su interfaz visible.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El patrón que detecta el botón de parada contiene un carácter de retroceso literal en lugar de `\b`; puede no detectar las etiquetas previstas y retrasar la determinación de respuesta completa (L187).
- **Calidad:** `send` es extensa y combina validación del borrador, envío, seguimiento y limpieza (L54-L135).
- **Mejoras:**
  - [alta] Sustituir el carácter de retroceso del patrón por el límite de palabra `\b` y probar las etiquetas admitidas (L187).
  - [baja] Extraer fases de `send` en funciones con responsabilidades acotadas (L54-L135).
  - [baja] Añadir pruebas para la detección de finalización y la limpieza del borrador (L179-L207).

### `eolfi/bridge/adapters/meta.mjs`
- **Propósito:** Adaptador de Meta AI web para comprobar el estado, enviar mensajes y leer respuestas mediante la interfaz visible.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** `active` impide solicitudes simultáneas incluso para conversaciones distintas (L52); una petición podría bloquear a las demás mientras espera la respuesta.
- **Calidad:** La lectura y limpieza de respuestas depende de selectores y etiquetas de la interfaz de Meta (L126-L168); no se incluyen pruebas en este archivo.
- **Mejoras:**
  - [baja] Si se pretende permitir conversaciones paralelas, sustituir el bloqueo global por control por conversación (L52).

### `eolfi/bridge/adapters/sites.json`
- **Propósito:** Configura orígenes, selectores y señales de estado para los adaptadores web de ChatGPT, Copilot y Le Chat.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Copilot está marcado explícitamente como no calibrado y sin selectores verificados (L77-L78, L113-L118); su uso depende de completar esa calibración.
- **Calidad:** Los selectores y notas de verificación están centralizados; algunos patrones y señales se repiten entre sitios.
- **Mejoras:**
  - [baja] Mantener la calibración y las notas de verificación actualizadas al cambiar los selectores (L55-L63, L113-L118, L165-L176).

### `eolfi/bridge/approval.mjs`
- **Propósito:** Gestiona la aprobación de envíos y permisos temporales por proveedor y conversación.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Si `showMessageBox` rechaza la promesa, el error se propaga al llamador (L48); este archivo no define recuperación.
- **Calidad:** La lógica es breve y separa la vista previa, concesión y revocación; no se incluyen pruebas en este archivo.
- **Mejoras:**
  - [baja] Añadir pruebas para cancelación, caducidad y revocación de permisos (L33-L54).

### `eolfi/bridge/engine/chrome.mjs`
- **Propósito:** Inicia y controla un navegador Chromium mediante CDP por tubería, y expone una interfaz compatible con los adaptadores.
- **Seguridad:** El puerto de `DevToolsActivePort` se convierte a número y se usa para conectarse a `127.0.0.1` sin validar rango ni confirmar que el destino sea CDP (L406-L408); un archivo manipulado en el perfil podría provocar una conexión a otro servicio local y enviarle `Browser.close` (L183).
- **Errores y robustez:** `loadURL` continúa como si hubiera terminado tras 20 segundos aunque no llegue el evento de carga (L229); el llamador puede recibir una página aún cargando. El borrado de un lock de más de seis horas puede permitir una segunda sesión si la primera sigue activa (L364-L367).
- **Calidad:** La implementación concentra transporte, gestión de ventanas e interacción con páginas; algunos errores de lectura de CDP se ignoran deliberadamente (L86, L224).
- **Mejoras:**
  - [alta] Validar que el puerto esté entre 1 y 65535 y comprobar el endpoint antes de enviar el comando de cierre (L406-L408, L183).
  - [media] Informar del timeout de carga en vez de continuar silenciosamente (L229).
  - [baja] Revisar el lock antiguo con una comprobación atómica antes de borrarlo (L364-L367).

### `eolfi/bridge/main.mjs`
- **Propósito:** Inicia el puente Electron o el motor Chrome, administra ventanas por proveedor y conecta adaptadores, aprobación y servidor local.
- **Seguridad:** [media] Si falla `icacls`, el archivo con credenciales conserva permisos heredados, que podrían ser demasiado amplios (L167-L170). La navegación permite cualquier subdominio de Google, DeepSeek o Meta, además del origen configurado; esto amplía los destinos permitidos (L69-L74).
- **Errores y robustez:** La promesa de `app.whenReady()` no tiene manejador de rechazo; errores al iniciar el servidor o abrir ventanas pueden quedar sin gestionar (L175-L194). La escritura temporal no limpia el archivo si falla antes del renombrado (L164-L173).
- **Calidad:** La lógica de arranque, navegación, entrada y persistencia está concentrada en un único archivo.
- **Mejoras:**
  - [media] Verificar permisos efectivos del archivo y fallar de forma segura si `icacls` falla (L167-L170).
  - [media] Limitar los destinos de navegación a hosts estrictamente necesarios (L69-L74).
  - [baja] Separar el arranque y la gestión de ventanas en módulos (L77-L194).
  - [baja] Gestionar explícitamente los errores de arranque y carga de ventanas (L175-L194).

### `eolfi/bridge/package.json`
- **Propósito:** Define el paquete Electron del puente, su punto de entrada y los comandos de inicio y pruebas.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** No se especifica una versión de Node compatible (L1-L17).
- **Calidad:** No hay comando de lint ni comprobación estática definidos (L10-L13).
- **Mejoras:**
  - [baja] Declarar la versión de Node requerida (L1-L17).
  - [baja] Añadir una comprobación estática al flujo de desarrollo (L10-L13).

### `eolfi/bridge/server.mjs`
- **Propósito:** Expone la API local del puente para estado, eventos, capturas, entrada del usuario y envíos a los adaptadores.
- **Seguridad:** [media] La autenticación común también permite al token de Eolfi acceder a autodiagnóstico y a las rutas de reinicio y revocación, aunque el comentario limita ese token a otras rutas (L50-L56, L89-L100, L164-L179). `/v1/compare` deja de acumular el cuerpo al superar el límite, pero sigue leyendo hasta el final sin rechazar pronto ni limitar el tiempo de recepción (L108-L112).
- **Errores y robustez:** El cuerpo de `/v1/reset` y `/v1/revoke` se acumula con un cálculo repetido y puede aceptar un prefijo válido si llega más contenido tras el límite (L165-L170). El servidor no gestiona explícitamente errores de escucha (L284-L284).
- **Calidad:** El manejador central reúne muchas rutas y lógica asíncrona; faltan pruebas visibles para límites de cuerpo, autorización por ruta y cancelación de comparativas.
- **Mejoras:**
  - [media] Aplicar autorización específica a autodiagnóstico, reinicio y revocación (L89-L100, L164-L179).
  - [media] Rechazar cuerpos de comparativa excesivos y limitar su recepción (L108-L112).
  - [media] Rechazar cuerpos de reinicio o revocación que superen el límite, sin analizarlos parcialmente (L165-L170).
  - [baja] Gestionar errores de `listen` y probar cancelaciones durante la aprobación (L284-L284, L124-L133).

### `eolfi/bridge/test/adapters.test.mjs`
- **Propósito:** Comprueba que los scripts de los adaptadores compilan, que el estado distingue sesiones y que no se ejecutan fuera del origen esperado.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Las pruebas dependen de respuestas simuladas y no comprueban el comportamiento ante errores de `executeJavaScript` (L18-L24).
- **Calidad:** La compilación con `new Function` verifica sintaxis, pero no el comportamiento de los scripts en una página real (L19).
- **Mejoras:**
  - [baja] Añadir casos de error y de adaptador con ventana destruida (L18-L35).
  - [baja] Complementar la prueba de compilación con pruebas de comportamiento aisladas (L16-L25).

### `eolfi/bridge/test/engine-concurrency.test.mjs`
- **Propósito:** Verifica que aperturas y arranques concurrentes del motor se reutilizan y permiten reintentos tras un fallo.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** No se comprueba que `stop()` cierre correctamente recursos ni qué ocurre si se invoca durante un arranque (L33-L40).
- **Calidad:** Las pruebas reemplazan métodos internos, por lo que no cubren la integración real con el proceso del navegador (L11, L24-L26, L36).
- **Mejoras:**
  - [baja] Añadir casos para parada durante el arranque y liberación de recursos (L33-L40).
  - [baja] Complementar los dobles internos con una prueba de integración controlada (L8-L40).

### `eolfi/bridge/test/engine.test.mjs`
- **Propósito:** Prueba opcional de integración con un navegador real y CDP: navegación, entrada, ejecución de JavaScript y captura de pantalla.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** La limpieza depende de una espera fija de 1,5 segundos y no espera a que `srv.close()` termine; el borrado del perfil podría adelantarse al cierre del navegador (L27-L29).
- **Calidad:** La prueba solo se ejecuta con un navegador disponible y `EOLFI_REAL_BROWSER=1` (L10, L32).
- **Mejoras:**
  - [media] Esperar el cierre del servidor y confirmar que el navegador terminó antes de borrar el perfil (L26-L29).

### `eolfi/bridge/test/fase-a.test.mjs`
- **Propósito:** Prueba la caducidad de aprobaciones, la selección de conversación y la normalización de saltos de línea.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El cierre del servidor no se espera (L28). La prueba de aprobación incluye temporizadores que siguen activos tras la caducidad (L15, L22).
- **Calidad:** Las pruebas cubren casos concretos y las aserciones son claras.
- **Mejoras:**
  - [media] Esperar el cierre del servidor y limpiar o controlar los temporizadores de la prueba (L15, L28).

### `eolfi/bridge/test/fase-b.test.mjs`
- **Propósito:** Prueba respuestas del puente ante ventanas cerradas, reinicio, revocación y cuerpos demasiado grandes.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El cierre del servidor no se espera (L22). La prueba del cuerpo grande acepta una conexión cortada como resultado alternativo, aunque después exige código 413 (L48-L50).
- **Calidad:** El adaptador y el estado compartidos entre pruebas pueden hacer que estas dependan del orden de ejecución (L7-L9).
- **Mejoras:**
  - [media] Esperar el cierre del servidor al terminar (L22).
  - [baja] Crear estado de adaptador aislado por prueba para evitar dependencias de orden (L7-L9).

### `eolfi/bridge/test/fase-c.test.mjs`
- **Propósito:** Comprueba que el puente exige `panelToken` y que la lista de teclas no acepta claves heredadas.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Sin hallazgos.
- **Calidad:** Pruebas pequeñas y directas; la cobertura se limita a las condiciones indicadas.
- **Mejoras:**
  - [baja] Sin mejoras necesarias.

### `eolfi/bridge/test/fase-d.test.mjs`
- **Propósito:** Prueba la aprobación, el envío de DeepSeek, la tubería CDP, la espera de navegación y algunas respuestas HTTP.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** El servidor de la prueba no espera a cerrar (L155). El ayudante HTTP no maneja errores de conexión, por lo que podría dejar la prueba pendiente (L149-L150). La prueba de navegación puede quedar pendiente si no llega el evento esperado (L133-L140).
- **Calidad:** Se agrupan pruebas de varios componentes en un solo archivo; los `setTimeout` de la navegación hacen que la prueba dependa del tiempo (L134, L136).
- **Mejoras:**
  - [media] Esperar el cierre del servidor y resolver los errores de conexión del ayudante HTTP (L149-L155).
  - [media] Añadir un límite de tiempo a la espera de navegación para evitar pruebas bloqueadas (L133-L140).

### `eolfi/bridge/test/fase-e.test.mjs`
- **Propósito:** Prueba la espera de respuestas con streaming y la validación de la recalibración de sitios declarativos.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Los directorios temporales creados en L40 y L57 no se eliminan; pueden acumularse entre ejecuciones.
- **Calidad:** Las pruebas cubren cambios de selectores y atributos, pero no limpian sus archivos temporales.
- **Mejoras:** [baja] Eliminar los directorios temporales al terminar cada prueba (L40, L57).

### `eolfi/bridge/test/panel.test.mjs`
- **Propósito:** Prueba permisos diferenciados para el panel, respuestas de proveedor ocupado y cancelación durante la aprobación.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Las esperas fijas de L45 y L54 pueden ser inestables en entornos lentos; L58 presupone que la aprobación llegó a asignar `release`. El cierre del servidor en L22 no se espera explícitamente.
- **Calidad:** El uso de estado compartido (`approvals`, `release`, `sent`) acopla las pruebas entre sí.
- **Mejoras:** [media] Sincronizar las pruebas con señales o promesas en vez de temporizadores fijos (L45, L54, L58). [baja] Esperar el cierre del servidor para asegurar la limpieza (L22).

### `eolfi/bridge/test/server.test.mjs`
- **Propósito:** Prueba autenticación, envío de mensajes, eventos, cancelación, capturas e ingreso de eventos remotos.
- **Seguridad:** Sin hallazgos.
- **Errores y robustez:** Las esperas fijas de L45 no aplican aquí; la cancelación depende de un temporizador sin confirmar que la petición ya llegó al servidor (L59). El servidor adicional iniciado en L102 se cierra sin esperar su cierre (L112); el cierre del servidor principal tampoco se espera explícitamente (L21).
- **Calidad:** Las pruebas comparten estado mutable (`allow` y `approvals`), lo que las hace sensibles al orden de ejecución.
- **Mejoras:** [media] Sincronizar la prueba de cancelación con la recepción de la petición, en lugar de depender del temporizador (L59-L62). [baja] Esperar el cierre de ambos servidores (L21, L112).

### `eolfi/cli.py`
- **Propósito:** Define los comandos de Eolfi y despacha sus operaciones. También implementa el puente de navegador y VS Code.
- **Seguridad:** [media] `npm install` puede ejecutar scripts de dependencias con los permisos del usuario y hereda el entorno, que puede contener secretos (L629). El proceso del puente también hereda el entorno completo (L641-L648).
- **Errores y robustez:** La creación y eliminación de `login.lock` no es atómica; dos inicios de sesión simultáneos pueden sobrescribir o borrar el bloqueo del otro (L434, L471). En `_close_browser`, una excepción antes de L586 puede dejar el socket sin cerrar explícitamente (L573-L586).
- **Calidad:** `main` y `_dispatch` concentran muchos comandos y responsabilidades; convendría dividir el despacho por áreas. Faltan pruebas visibles para concurrencia del bloqueo y cierre del socket.
- **Mejoras:**
  - [media] Usar creación exclusiva del bloqueo y borrarlo solo si sigue perteneciendo al proceso actual (L434, L471).
  - [media] Reducir el entorno heredado en la instalación y ejecución del puente, preservando solo las variables necesarias (L629, L641-L648).
  - [baja] Cerrar el socket con un bloque `with` o `finally` (L573-L586).
  - [baja] Separar el despacho de comandos en funciones o módulos más pequeños (L234-L395).

