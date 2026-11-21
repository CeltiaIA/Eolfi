# Ejecución encadenada del plan — 19/11/2026

Este informe complementa PLAN_DEFINITIVO.md. Un punto con pruebas locales sigue marcado como no verificado en
las plataformas, redes, modelos o dispositivos que no se pudieron ejecutar.

## Continuación local E4, D3 y C7 — 19/11/2026

Se conservó el estado previo del repositorio. Estado inicial: `git status --short` salida 0 con cambios
existentes; `docker info` salida 0 (Docker Desktop 29.7.2); WSL Ubuntu 2 accesible; `adb devices -l`
salida 0 y una tableta autorizada. `eolas-v2 status` salida 0: perfil `gemma`, servidor detenido.

### E4

- **sigrok:** ya estaba instalado, por lo que no se ejecutó el instalador. En WSL, desde `/mnt/d/Eolfi`,
  el lanzador `~/.local/eolfi-rea/sigrok/eolfi-sigrok --version` devolvió 0 y sigrok-cli 0.7.2.
  `python -m eolfi rea herramientas` y `python -m eolfi rea decodificadores` salieron 0; REA enumeró
  111 decodificadores. El conteo bruto de 112 directorios incluye directorios que no son decodificadores.
- **Npcap 1.90:** antes de instalar, `sc.exe query npcap` y `sc.exe query npf` salieron 1060 y faltaba el
  controlador. Instalador oficial: <https://npcap.com/dist/npcap-1.90.exe>; descarga `curl.exe` salida 0;
  SHA-256 `682b57e1c05ef375931975c9d6ded40888f4bfdf9f4b11571e654f962f1199b6`; Authenticode válida,
  firmante Nmap Software LLC. El instalador se inició con `Start-Process -Verb RunAs`; no se capturó su
  código de salida, **NO VERIFICADO**. Después `sc.exe query npcap` salió 0 y mostró el controlador activo
  `C:\Windows\System32\drivers\npcap.sys`, versión 1.90; `C:\Program Files\Wireshark\dumpcap.exe -D`
  salió 0 y enumeró nueve interfaces. No se seleccionó ninguna ni se capturó tráfico.
- **Cutter 2.5.0:** paquete oficial
  <https://github.com/rizinorg/cutter/releases/download/v2.5.0/Cutter-v2.5.0-Windows-x86_64.zip>;
  descarga salida 0; SHA-256 `a04154a03a392dbf5886a629938582f7d23a93636fa0611c3e1c34905b197e69`,
  igual al publicado en GitHub Releases. Extraído sin sobrescribir en
  `C:\Users\mejil\AppData\Local\Eolfi-Cutter-v2.5.0-copilot-20261119-230207\Cutter-v2.5.0-Windows-x86_64`.
  `cutter.exe` SHA-256 `82942b867b2a348119978a70c1cf08bf166af2432c04d71e8018e2edb63b13e5`.
  Arrancó la ventana `Welcome to Cutter` y cargó `rz_core-0.9.dll` del propio paquete. Rizin incluido y
  Rizin externo respondieron 0 con versión 0.9.1 y commit `c3a90e9226d977f58f4e9c75f78fa6b07afe13c7`.
  `CloseMainWindow` no cerró la bienvenida y se terminó únicamente el PID lanzado. No se abrió ningún binario.
  Que Cutter use el Rizin externo, en vez del incluido, es **NO VERIFICADO**. `rea herramientas` final
  salió 0 y aún no detecta Cutter en esa ubicación portátil; no se modificó configuración para registrarlo.
- Los dos paquetes descargados se conservan en `informes/e4-evidencia-copilot-20261119-230006/`.

### D3

`python -m eolfi eolas-v2 examen gemma gemma_q4 --informe
informes/d3-gemma-q5-vs-q4-copilot-20261119-230521.json` terminó con salida 0; stdout y stderr se
conservaron en `informes/d3-gemma-q5-vs-q4-copilot-20261119-230521.log`. Se usaron una copia aislada de
la configuración, puerto 18090 y rutas nuevas para progreso, admisión, telemetría y aportes, sin reemplazar
la configuración, memoria ni resultados existentes. La comprobación previa del contenedor salió 0.

La batería es `completa`, ronda `b19f8584-b57f-4f77-8178-c0f262110c51`: 28 casos previstos y 28
resultados únicos con puntuación booleana para cada perfil. `comparar-banco` salió 0: Q5 28/28 y Q4
26/28 a la primera; mejoras `[]`, regresiones `["ofuscado", "duracion"]`. Q4 corrigió `ofuscado`;
`duracion` quedó sin aprobar tras una respuesta truncada. Ambos perfiles figuran aprobados por el umbral
del banco. No se aplicó ninguna recomendación. La memoria y admisión de esta ronda se aislaron, por lo
que no sustituyen las del usuario. `eolas-v2 status` final salió 0: `gemma` configurado, servidor
original detenido; el puerto aislado 18090 quedó sin listener.

### C7

`adb devices -l` salió 0 y mostró una tableta autorizada GT-P3100, Android 4.1.2/API 16.
`adb reverse --list` salió 1 (`error: closed`), así que se probó el panel HTTPS en la dirección local
del equipo con token y certificado autofirmado efímero; el certificado no se instaló en la tableta.
`adb shell am start` y `uiautomator dump /dev/tty` salieron 0. El navegador mostró «Problema de conexión»
y «No se ha podido establecer una conexión segura»; el servidor registró
`ssl.SSLError: [SSL: VERSION_TOO_LOW] version too low`. El panel no llegó a mostrarse: dictado
**NO VERIFICADO**. El volcado sin token está en
`informes/e4-evidencia-copilot-20261119-230006/c7-android-ui.xml`. El servidor se detuvo y se comprobó
que el puerto 18778 quedó sin listener. No se rebajó la versión TLS ni se instaló software en Android.

### Validación final

- `python -m pytest -q tests/test_herramientas_rea.py tests/test_i18n.py tests/test_modelos.py tests/test_eolas_v2.py`:
  salida 0, 124 pruebas aprobadas.
- `python -m ruff check --select F eolfi tests tools`: salida 0, `All checks passed!`.
- `git diff --check`: salida 0, con advertencias de conversión CRLF/LF en archivos previamente modificados.

## Cambios implementados

| Punto | Cambio | Comprobación |
|---|---|---|
| B4 | La telemetría guarda el tiempo real desde que se lanza Eolas V2 hasta health. Eolas V1 lee load_duration del servidor y lo convierte desde nanosegundos. | Pruebas de telemetría y arranque simulado. |
| B5 | El banco ya incluye tareas, contador y filtro; la evidencia real del banco A/A de B2 ejercitó los tres encargos. | Cinco pares reales, con memoria congelada, descritos en `PLAN_DEFINITIVO.md`. |
| B7 / D3 | Dos casos inéditos adicionales, diferencia de intervalos y reparto entero exacto. Cada uno tiene una solución de referencia ejecutada. Un examen puede incluir dos perfiles y deja el informe completo. comparar-banco exige todos los casos de la misma ronda, sin repesca. | Pruebas de las referencias y de comparación emparejada. |
| B8 | El puente Node firma automáticamente cada evento con el mismo HMAC, clave, formato canónico y cerrojo que Python. | Python verifica una cadena firmada por Node. REA estático del módulo, artefacto SHA-256 cbb064c8…bdd7f9, sin fallos de parseo. |
| C2 | Lanzador Eolfi.command para macOS. El constructor acepta una huella de certificado Windows, firma con SignTool y verifica Authenticode antes de mover el ejecutable. | Lanzador probado en carpeta temporal. Firma real: NO VERIFICADA, falta SignTool y certificado. |
| G1 | Auditor e inventario devuelven procedencia: NO VERIFICADO. Linux y macOS disponen de proveedor de sockets por PID mediante el extra conexiones basado en psutil. | El GGUF real de 7.121.860.000 bytes quedó estructuralmente verificado y con procedencia no verificada. Proveedor no ejecutado en Linux/macOS. |
| G1 / G4 | Los tamaños K se contrastaron con leejet/ggml commit a5915eb0e47adef21c3f25b889a008925ea838c2. Los blobs locales coinciden con Git, ggml-common.h 1dbbe326… y ggml.h 49a6751d… | g++ 16.2.0 aceptó los seis static_assert: 84, 110, 144, 176, 210 y 292 bytes para bloques de 256. |
| G2 | La política de modelos de confianza se comprueba también justo antes de cuantizar y justo antes del smoke con llama-cli. | Pruebas impiden lanzar los ejecutores cuando el manifiesto no autoriza el modelo. Activación real pendiente de aprobar hashes. |
| G3 | CLI para consultar, crear, comprobar y retirar una regla de salida de Windows ligada al ejecutable exacto. status distingue las opciones offline de una regla verificada. | Consulta real: regla Eolfi sin red 8d2f9bb440e2 ausente. Aplicación: NO REALIZADA porque cambia la seguridad del sistema. |
| G5 | Las descargas se reanudan con --reanudar, identidad fijada en un archivo de control, petición Range, validación estricta de Content-Range y SHA-256 del archivo completo. | Pruebas de reanudación, rango ignorado, rango incorrecto, hash y no sobrescritura. |
| G5 / D3 | Comparación formal de dos perfiles sobre el mismo examen completo antes de adoptar. | Prueba CLI con mejora y regresión emparejadas. Ejecución con dos modelos reales: NO VERIFICADA. |
| G6 / RSI | Dos agotamientos reales del plazo de arranque pueden proponer duplicar ready_timeout. La propuesta entra por el flujo RSI y no se aplica sola. | Prueba de propuesta acotada 300 → 600 y rechazo de valores fuera de rango. |
| G7 | La memoria verificada de assist se exporta de forma explícita a dataset SFT, con redacción, deduplicación, particiones deterministas y manifiesto con hash. | Prueba con 100 ejemplos. En la memoria real solo hay 2 peticiones distintas frente al mínimo 20, así que el entrenamiento no se inició. |

## Validación de esta copia

- 87 pruebas de modelos pasaron, 6 se omitieron por ejecutores no disponibles y una prueba real de loopback se excluyó.
- 101 pruebas de Eolas, selección y RSI pasaron, excluyendo la prueba HTTP bloqueada por el entorno.
- 34 pruebas de telemetría, acciones e instalador pasaron, excluyendo la verificación completa de la rueda.
- 40 pruebas de actualización y conexiones pasaron; la prueba de sockets reales se excluyó.
- Un bloque ampliado pasó 178 pruebas, con una prueba HTTP excluida.
- La pasada final sobre los módulos modificados pasó 324 pruebas, omitió 6 por ejecutores no disponibles y
  excluyó 3 pruebas dependientes de loopback o de un paquete instalado.
- Las pruebas de idioma y guías pasaron 16 casos; 4 casos HTTP se excluyeron por el mismo bloqueo de loopback.
- python -m ruff check --select F eolfi tests tools pasó.
- git diff --check pasó.
- Las suites completas de Python, los dos puentes y e2e siguen NO VERIFICADAS en esta sesión. Los primeros
  fallos son conexiones a 127.0.0.1 con WinError 10013 o EACCES. La solicitud de ejecución local fue rechazada
  automáticamente por el perfil de permisos (`sandbox_approval: false`, `request_permissions: false`), incluso
  después de la autorización expresa del titular.

## Dependencias que quedan

### Continuación B7: cobertura de la recomendación

La memoria de evaluaciones conserva ahora `ronda`, `casos_previstos`, `case` y `first_try` de cada resultado.
Para las rondas nuevas, `recomendar-perfil` solo considera un perfil aprobado si ejecutó una vez todos los casos
previstos de código de esa ronda. Una ronda incompleta o con casos duplicados no desplaza a una anterior válida.
Las memorias anteriores carecen de estos campos y no permiten comprobar retrospectivamente su cobertura.
Tres pruebas específicas de recomendación pasaron (3/3). La vista previa sobre la memoria real recomendó
`gemma` (100/100, sin aplicar). `assist --model banco` seleccionó `gemma`, pero la inferencia quedó
**NO VERIFICADA**: el cliente negó acceso a `C:\Users\mejil\.eolfi\eolas-v2.lock` y rechazó automáticamente
la solicitud de repetir el mismo comando con ejecución local. La muestra sintética `static` sin juez opcional
se generó con `verification.ok=true`: sintaxis JS (dos pasos) y `node --test`, todos con salida 0. La primera
muestra con juez devolvió 0/3 por el bloqueo de navegador y se interrumpió su reparación automática.
La respuesta de la recomendación distingue `cobertura: NO_VERIFICADO` para memorias anteriores y
`casos previstos completos` cuando la ronda nueva conserva los casos y pasa la comprobación.

Validación adicional de esta continuación: `python -m pytest -q tests/test_eolas_v2.py -k recomendacion`
pasó 3/3; `python -m ruff check --select F eolfi tests tools` y `git diff --check` pasaron.
Se lanzaron las cuatro suites completas. `npm test` desde `tests/e2e` falló 28/28:
`net::ERR_NETWORK_ACCESS_DENIED` en 127.0.0.1 y servidor del panel sin arranque; se usó `npm.cmd`
porque PowerShell bloqueó `npm.ps1`. `node --test` desde `vscode-bridge` terminó con 205/211,
seis fallos `connect EACCES 127.0.0.1`. `python -m pytest -q` y `node --test` desde `bridge`
mostraron múltiples fallos de loopback y se interrumpieron tras quedar bloqueadas en pruebas
dependientes de red local; sus totales son **NO VERIFICADOS**. El titular recibió el prompt para
repetir las cuatro suites y el smoke de B7 en la terminal local de VS Code.

### Resultado comunicado desde VS Code

El titular comunicó que las cuatro suites terminaron con código de salida 0 en su terminal local, fuera de este
entorno restringido. El bloque de salida aportado muestra 28 pruebas e2e, 28 aprobadas, 0 fallidas y 0 omitidas
(36,34 s). La etiqueta del mensaje decía «bridge», pero los nombres de las pruebas son los del panel e2e;
no se conserva aquí la salida detallada de pytest ni de los dos puentes. Por tanto, esos tres resultados se
registran como **código 0 comunicado por el titular**, sin atribuirles cifras de casos ni equivalencia funcional.
B7 no se ejecutó allí: el prompt anterior prohibía editar archivos, mientras que `assist` puede conservar cambios
en la muestra. Se necesita una instrucción nueva que autorice expresamente modificar solo una copia de prueba.

### B7 ejecutado en una copia aislada

El titular ejecutó el prompt corregido en la terminal local de VS Code. La vista previa de
`recomendar-perfil` devolvió `gemma`, salida 0, puntuación [100, 100], `aplicado: false` y
`cobertura: NO_VERIFICADO` porque la memoria de esa ronda antigua no conservaba los casos individuales.
`assist --provider eolas-v2 --model banco` sobre
`D:\Eolfi\.pytest-tmp-b7-copilot-20261119-184413\proyecto` terminó con salida 0.
Una ronda real con Gemma Q5 escribió `index.html`, `js/main.js` y `tests/site.test.mjs`;
`verification.ok=true` y los tres pasos (dos sintaxis JS y `node --test`) devolvieron 0.
`best_attempt` fue la ronda 1, aplicada, sin restauración, y la memoria verificada quedó en la
carpeta de la copia. La generación consumió 397,046 s, 5967 tokens de entrada y 2938 de salida.

Se cotejaron los SHA-256 de los tres archivos con `best_attempt.files`: coinciden. Repetido
`node --test` en la copia, 1/1 pasó. Esa prueba solo revisa HTML y presencia de `id="visit-count"`;
no ejercita el contador entre visitas. No había juez funcional en la muestra ni se probó en un navegador,
por lo que el comportamiento del contador y su accesibilidad dinámica siguen **NO VERIFICADOS**.
La ruta B7 de recomendación, inferencia y verificación de este proyecto sí quedó ejercida con modelo real;
esto no demuestra superioridad entre perfiles ni calidad general fuera de la muestra.

### B7: prueba dinámica y corrección de la muestra

El titular ejecutó `evidencia-b7/comprobar.cjs` en Chrome 157.0.8103.79: primera visita 1,
recarga 2 y pestaña nueva 3, persistidos; axe sin problemas graves o críticos en claro y oscuro
(para inyectar axe se desactivó CSP solo durante esa comprobación). Cuando la prueba bloqueó
`localStorage`, el contador quedó en 0 y apareció un `pageerror` no capturado; salida 1.
Se conservan `resultado.json` y las dos capturas en la carpeta `evidencia-b7` de la copia.

Corregido **solo en esa copia** `js/main.js`: el contador captura denegaciones de lectura y
escritura y presenta «No disponible» en vez de fingir un valor persistido. `tests/contador.test.mjs`
ejecuta el JS con un DOM controlado y comprueba tres visitas, lectura denegada con botón de tema
operativo y escritura denegada. `node --test`: 4/4. `eolfi.generador.verify.verify` sobre la copia:
`ok=true`, dos comprobaciones de sintaxis y pruebas Node, las tres con `exit=0`.
El guion de Chrome exige ahora también «No disponible» y ausencia de errores. Repetido por el titular
en Chrome 157.0.8103.79 tras la corrección: salida 0; primera visita 1, recarga 2 y pestaña nueva 3;
almacenamiento bloqueado muestra «No disponible», el botón de tema funciona y no hay errores de consola.
Axe no encontró problemas graves o críticos en claro ni oscuro; la CSP se omitió solo para inyectar axe.
El servidor local se detuvo al terminar. El resultado completo y las capturas se conservan en
`proyecto/evidencia-b7/`. El comportamiento de esta copia queda verificado en ese Chrome. Este arreglo
de la muestra no modifica el generador ni demuestra que futuras respuestas del modelo eviten el error.

### D3: ronda emparejada preparada

Se comprobó que `gemma` Q5 y `gemma_q4` Q4 están disponibles y que el perfil configurado era `gemma`.
Una consulta de estado posterior informa `running=false` y `model_verified=false`; por tanto, no se afirma
que el servidor siga en ejecución ni que el modelo esté verificado ahora. Se intentó `eolfi eolas-v2 examen gemma gemma_q4`, guardando stdout y stderr en
`informes/b7-d3-gemma-q5-vs-q4-2026-11-19.*`. Terminó antes de cargar modelos con salida 1: el entorno
restringido no puede conectar con `npipe:////./pipe/dockerDesktopLinuxEngine`. La solicitud de repetir el
mismo comando con ejecución local fue rechazada automáticamente por la política del cliente. El JSON quedó
vacío y el log conserva el error literal; no son una comparación. El perfil configurado siguió siendo `gemma`.
La ronda emparejada real continúa **NO VERIFICADA** hasta ejecutarla en la terminal local de VS Code.

Para que esa ejecución no dependa de redirecciones de consola, `eolas-v2 examen` admite ahora
`--informe RUTA.json`. Guarda atómicamente el informe completo, exige una ronda identificada y batería
completa, y rechaza extensiones distintas de `.json` y destinos existentes. La salida CLI indica ruta,
ronda y perfiles guardados. Validación: 5 pruebas específicas y las 67 pruebas de `test_eolas_v2.py`
pasaron; Ruff F y `git diff --check` pasaron. Esto robustece la evidencia de D3, pero no sustituye la
comparación real de Q5 y Q4 bloqueada por Docker en este cliente.

### G2: propuesta de confianza no activable

`eolfi modelos proponer-confianza --archivo MODELO --out propuesta.json` prepara ahora la revisión de hashes
sin autorizar modelos. Calcula ruta, tamaño, SHA-256 y auditoría local; detecta GGUF divididos, exige todas sus
partes y las identifica por separado. Cada entrada declara `procedencia: NO VERIFICADO`. La salida usa el esquema
`eolfi.modelos.confianza-propuesta/v1`, que `check_trust` rechaza y que no activa ni escribe
`EOLFI_MODELOS_CONFIANZA`. El destino debe ser un JSON nuevo y se escribe atómicamente.
Se generó `informes/modelos-confianza-propuesta-2026-11-19.json` con los GGUF locales Q5 y Q4. Su SHA-256 es
`0965606ef6b97713afdd57af2d6047428c242ed49cccf58af37606e8ad5665fb`. La propuesta conserva expresamente
`procedencia: NO VERIFICADO`; al pasarla a `modelos comprobar`, el esquema autorizado la rechazó con salida 1.
Validación conjunta posterior: 105/105 pruebas de Eolas V2, modelos y herramientas REA; Ruff F y
`git diff --check`. La aprobación de hashes y su procedencia independiente siguen pendientes del titular.

### E4: inventario previo de herramientas

`eolfi rea herramientas` informa ahora, sin instalar ni iniciar herramientas, del estado de Npcap, sigrok y
Cutter y de las alternativas ya presentes. En esta copia: Npcap no se detecta; `dumpcap.exe` de Wireshark 4.6.9
sí existe; sigrok no es accesible desde este entorno; Cutter no está, pero Rizin está disponible en
`~/.eolfi/tools/rizin/.../rizin.exe`. La salida incluye `solo_lectura: true`, `cambios: []` y una lista estructurada
de pendientes con requisito y acción. Para sigrok expone el instalador existente y convierte su ruta al formato
`/mnt/d/...` que acepta WSL. Declara expresamente que un fallo de acceso a WSL no demuestra que sigrok falte allí.
Validación: 3/3 pruebas específicas; el bloque conjunto de C1 y E4 pasó 21/21; Ruff F pasó. E4 sigue pendiente de
instalación o comprobación local de las herramientas ausentes; este inventario no concede ese permiso, no instala
el controlador de Npcap y no confunde Rizin con la interfaz de Cutter.

### C1: regresión de traducciones cerrada

Los subcomandos añadidos por D3, G2 y E4 incorporan ya sus ayudas en inglés: `--informe`,
`modelos proponer-confianza` y `rea herramientas`. La prueba de cobertura detectó las cinco cadenas nuevas antes
de la corrección. Después, `tests/test_i18n.py` y `tests/test_guia_idioma.py` pasaron 20/20.

### Intento E4, D3 y C7 desde el cliente restringido

El intento autorizado de completar los tres bloques queda documentado en
`informes/e4-d3-c7-copilot-2026-11-19.md`. WSL devolvió `E_ACCESSDENIED`; Npcap no está instalado y dumpcap no
puede cargar `wpcap.dll`; Cutter no está y Rizin 0.9.1 sí respondió. Docker Desktop se inició desde su instalación
de usuario, pero el canal del motor mantuvo `permission denied`; D3 salió 1 antes de cargar modelos y no creó el
informe JSON. La elevación fue rechazada por la política del cliente antes de ejecutarse. ADB no enumeró ningún
dispositivo: **NO VERIFICADO: no hay dispositivo ADB conectado**.


- Hardware o plataforma: micrófono del PC, Android para el panel, VS Code real, Linux, macOS y varios perfiles reales.
- Red o publicación: hosting, repositorio remoto real, consulta a Hugging Face y publicación de una versión.
- Credenciales o privilegios: certificado de firma, regla de cortafuegos, Npcap y otras instalaciones del sistema.
- Datos: G7 necesita al menos 20 casos SFT distintos repartidos entre entrenamiento, validación y prueba.
- Decisión del titular: hashes de confianza, retirada de opciones y revisión concreta de REGISTRO_LIMPIEZA.md.
