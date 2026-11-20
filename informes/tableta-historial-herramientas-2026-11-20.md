# Tableta: historial acotado y selección de herramientas — 20/11/2026

## Continuación posterior a db26227: encargos realmente terminados

Una consulta correcta de `eolfi_vscode_encargo_estado` ya no basta para justificar «He creado la aplicación». La traza conserva el identificador, estado y verificación del proyecto devueltos por esa herramienta. El detector exige el último estado `hecho` y `verificado: true` del mismo encargo; consultar otro encargo no acredita el solicitado. Una consulta sin esos datos tampoco acredita creación. Se conserva el aviso para pendientes, fallos y resultados sin verificar.

Regresiones nuevas antes del arreglo: 6 fallos y un control verde. La suite ampliada señaló además una expectativa anterior que aceptaba cualquier consulta de estado; se reemplazó por un control negativo sin evidencia y otro positivo con identidad, estado y verificación explícitos. Tras corregir y añadir controles del último estado: `python -m pytest -q tests/test_chat.py tests/test_chat_honestidad.py tests/test_encargos_vscode.py tests/test_rea_client.py tests/test_rea_autorizacion.py tests/test_tableta.py tests/test_tableta_puente.py` → **185 aprobadas, 26,24 s**, salida 0. Registro privado `.pytest-tmp-tableta-historial/cascada-encargos.log` (LIM-067). Ruff F/E9 y `git diff --check`: salida 0.

Sin commit ni push. Suite global final y nuevo recorrido con modelo real de esta corrección: pendientes, NO VERIFICADOS. No se modifican aprobaciones, creación de proyectos, permisos ni servicios vivos. Es una comprobación de afirmaciones basada en las llamadas del turno; no garantiza comprender cualquier afirmación del modelo.

## Continuación: negaciones de actividad

Se corrige en `chat_honestidad.py` un falso positivo: «No estoy trabajando en segundo plano», «No hay acciones en curso» y promesas negadas se trataban como acciones afirmadas; esto podía activar la recuperación obligatoria del chat sin que correspondiera. Se aplica negación local a actividad, promesas y hechos («no», «nunca», «tampoco»). Una afirmación posterior en la misma frase sigue detectándose; «No solo estoy trabajando…» sigue siendo una afirmación. Es una regla de patrones acotada, no un análisis general del significado.

Regresiones antes del arreglo: 8 fallos y 3 controles positivos aprobados. Después: **170 pruebas focales aprobadas, 22,06 s**, con el mismo comando de chat/honestidad/REA/autorizaciones/tableta/puente; registro local `.pytest-tmp-tableta-historial/cascada-negaciones.log`. Ruff F/E9 y diff-check: salida 0. Incluye comprobar que una respuesta teórica que niega actividad no gasta otra ronda ni activa herramientas. Cierre global y nueva prueba de modelo real sobre esta continuación: pendientes, NO VERIFICADOS; no se reinician servicios ni se cambian rutas Android.

## Continuación: validación de respuestas y llamadas

Tres correcciones posteriores, sin commit, en `eolfi/chat.py` y `tests/test_chat.py`:

1. Los argumentos nulos, booleanos, numéricos, listas/objetos nativos o texto vacío ya no se convierten silenciosamente en `{}`. La llamada queda registrada como inválida y no se ejecuta. Se mantiene el objeto JSON textual válido y la recuperación del modelo tras argumentos incorrectos.
2. Las respuestas con envoltorio incompatible con el protocolo de chat producen un error explícito del motor, en lugar de `AttributeError`/`TypeError` o un objeto vacío que oculta el defecto.
3. La lista de llamadas se valida estructuralmente antes de ejecutarla: cada entrada necesita función y nombre textual no vacío. Una entrada dañada al final impide que se ejecute una entrada válida anterior de esa misma lista. Esto no introduce una transacción ni revierte herramientas ya ejecutadas en rondas anteriores; los argumentos de cada llamada siguen comprobándose al procesarla.

Regresiones reproducidas antes de corregir: 11 casos fallaban para argumentos/envoltorios y otros 5 para estructuras de llamadas. Después, el comando focal de chat/honestidad/REA/autorizaciones/tableta/puente descrito abajo termina con **159 aprobadas, 21,86 s**, salida 0; salida local `.pytest-tmp-tableta-historial/cascada-chat.log`. Ruff F/E9 y `git diff --check`: salida 0, con avisos informativos CRLF del árbol compartido. Se conserva la recuperación `Obligatorias` revisada anteriormente.

No se repitieron modelo real, dictado ni las cuatro suites completas sobre esta continuación. El cierre global del árbol final queda pendiente antes de su publicación; las cifras globales de las secciones anteriores corresponden a versiones anteriores. No se modificaron las rutas Android/Redmi ni se reiniciaron servicios.

## Corrección y revisión posterior

El fallo de respuesta vacía descrito abajo queda corregido para los escenarios reproducidos. En la vuelta de recuperación de una orden o promesa sin llamadas, `chat.Obligatorias` transmite `tool_choice: required`: el modelo tiene que elegir una herramienta del catálogo ofrecido. La obligación dura solo esa vuelta; después se vuelve a selección automática. Un saludo o una respuesta únicamente vacía no activan por sí solos esta obligación. Se conservan las comprobaciones de argumentos, resultados y autorizaciones.

Revisión independiente del código y lectura directa, en modo solo lectura, de los trabajos del panel principal:

| Trabajo de la tableta | Resultado observado |
|---|---|
| `68d386cb9fbbf5e5` | Terminado, `eolfi_doctor` con argumentos válidos y resultado correcto; una recuperación, 11,7 s. |
| `e97c37f2167d4b81` | Terminado con respuesta de texto, sin herramientas ni recuperación; 3,0 s. |
| `084f0606239ad37f` | Terminado, `eolfi_evidencias` con argumentos válidos y resultado correcto; una recuperación, 22,8 s. |

Evidencia local reproducible: `.pytest-tmp-tableta-historial/verificar_correccion.py` consulta esos tres identificadores en `job_history`/`job_results`, exige texto, estado terminado y la llamada esperada; salida 0, tres resultados correctos. Copia de contraste: `revision-correccion-trabajos.json` en esa carpeta privada. Se contrastaron trabajos existentes de la prueba física; esta revisión no volvió a manejar la tableta ni a consumir GPU mientras se prepara la adaptación del Redmi.

Comprobaciones ejecutadas sobre la corrección:

- `python -m pytest -q tests/test_chat.py tests/test_chat_honestidad.py tests/test_rea_client.py tests/test_rea_autorizacion.py tests/test_tableta.py tests/test_tableta_puente.py`: **143 aprobadas**, 22,49 s.
- `node --test` desde `eolfi/bridge`: **73 aprobadas, 4 omitidas**, salida 0.
- `node --test` desde `eolfi/vscode-bridge`: **211 aprobadas**, salida 0.
- `npm.cmd test` desde `tests/e2e`: **28 aprobadas**, salida 0.
- Ruff F/E9 para `eolfi/chat.py` y `tests/test_chat.py`, y `git diff --check`: salida 0; avisos informativos de conversión CRLF en archivos del árbol compartido.
- El cierre completo Python registrado en `ESTADO-TRABAJO.md` tras la corrección comunica **1459 aprobadas, 11 omitidas** (834 s); esta revisión no repitió esa suite ni recuperó su salida original. Se distingue ese resultado comunicado de las comprobaciones ejecutadas arriba.

El arreglo y los casos reales comprobados no garantizan acierto en toda petición ni equivalencia de las 13 herramientas. Dictado desde el micrófono hasta texto sigue NO VERIFICADO en esta revisión. Sin commit ni push. Las secciones siguientes conservan la evidencia anterior y los fallos que motivaron esta corrección.

Cambios sin commit en `luis/voz-piper`. La app 0.2.0 añade Nueva conversación e Historial; conserva borrador, conversación activa y contexto separado. Prefiere la SD extraíble y mantiene un archivo de hasta 8 MiB, retirando primero conversaciones antiguas distintas de la activa. Si una sola conversación excede el límite, conserva su parte reciente. Durante la sustitución puede existir una copia temporal adicional de hasta 8 MiB. El límite corresponde al archivo, no al consumo total de RAM. El historial en SD es texto sin cifrar y no incluye el token de vinculación.

El chat ofrece las 13 herramientas registradas en EolfiMCP. Una petición de acción que termina sin llamadas recibe una oportunidad adicional de seleccionar y ejecutar herramientas. Si sigue sin ejecutarlas se indica expresamente. Se registran argumentos válidos, llamadas y resultados correctos; se mantienen las autorizaciones existentes. Exponer las herramientas no demuestra que el modelo acierte en cualquier petición.

## Comprobaciones

- `python -m pytest -q tests/test_chat.py tests/test_chat_honestidad.py tests/test_rea_client.py tests/test_rea_autorizacion.py tests/test_tableta.py tests/test_tableta_puente.py tests/test_tableta_android.py`: **145 aprobadas**, 32,50 s.
- Ruff F/E9 y `git diff --check`: salida 0 (aviso informativo CRLF de `.gitignore`).
- Construcción real con `python eolfi/tableta-android/construir.py --salida D:/Eolfi/.pytest-tmp-tableta-historial/build-020 --comprobar-api D:/Eolfi-objetivos/informes/tablet-gtp3100/evidencias/artefactos`: APK 30.932 bytes, versión 0.2.0, minSdk 16. SHA-256 `d52f202c3361b5a39b61a2716932770a5049b4e7cac37c672feea7c773a2b531`.
- Proveedores de construcción: javac 21.0.12.1, D8 incluido en jadx-headless-mcp 0.7.1, apktool 3.0.3 y AAPT2. Rutas y hashes completos en `.pytest-tmp-tableta-historial/build-020/construccion.json`. Comprobación de API contra core/framework/framework2.odex de la tableta: **274 referencias de clase/miembro, ninguna ausente**; no verifica firmas completas.
- Ejecución real en Galaxy Tab 2 GT-P3100, Android 4.1.2/API 16, mediante ADB 37.0.1 y comprobación de foco REA: actualización instalada sin borrar el vínculo. Comprobados Nueva conversación, borrador, selección desde Historial y persistencia tras cierre forzado y reapertura. Ubicación observada: `extSdCard`, carpeta propia de la app.
- Contraste del paquete instalado: `adb shell dumpsys package com.celtiaia.eolfi.tableta` confirma versionCode 2, versionName 0.2.0 y permisos concedidos. Copia local: `.pytest-tmp-tableta-historial/paquete-instalado.txt`. La proyección REA de ese comando devolvió campos nulos y cobertura parcial (`ev_8ec4e09732eec865d6ca31f5ee8527960b82579c4a1c2d0f609740be5aa84818`); la versión se acredita con la salida nativa, no con dicha proyección.
- Conversación anterior sobre Q5 recuperada del trabajo `3e3bb036bce949c9` del panel e importada mediante confirmación en la tableta. Se comprobó su reapertura tras reiniciar la app. Las capturas y el texto privado no se publican; véase LIM-067.
- Modelo real `gemma4_recon_q4`, configuración activa sin cambios: **4/4 casos**. Seleccionó y ejecutó `eolfi_triage` para un WASM local de 8 bytes, `eolfi_evidencias` para consultar sus evidencias y `eolfi_doctor` para proveedores; respondió a un saludo sin herramientas. Muestra SHA-256 `93a44bbb96c751218e4c00d479e4c14358122a389acca16205b1e4d0dc5f9476`. Registro local: `.pytest-tmp-tableta-historial/smoke-herramientas.json`. Estas pruebas comprueban selección y retorno del resultado; no juzgan exhaustivamente cada frase ni ejecutan las 13 herramientas reales.
- Cierre completo con `python tools/verificar_suites.py`: **las cuatro suites verdes**. Python: 1.456 aprobadas, 11 omitidas y 4 avisos, 838,61 s. Puente: verde (4 omitidas); puente VS Code: verde; navegador e2e: verde. Registro `.pytest-tmp-tableta-historial/suites-completas.log`, cierre `GUARDIA: las suites están en verde.`

## Fallos y límites de la primera validación (anteriores a la corrección)

Prueba adicional de extremo a extremo: desde Nueva conversación se envió «Lista proveedores de analisis disponibles. Usa eolfi_doctor.» por el puente al Eolfi activo en `127.0.0.1:8777`. Trabajos `84916315ba63c7ba` y repetición `6e8915b88e309d0c`: ambos terminaron con **error, el motor terminó sin respuesta de texto**, sin ejecutar herramientas. Se observó en la app la recuperación adicional de `agent_turn`; el registro del motor muestra una generación de 1.500 tokens agotada. Esto no acredita la causa interna de la respuesta vacía. El catálogo completo del panel y su contexto difieren del smoke directo; falta aislar esa diferencia y corregir/verificar el fallo. **Uso de herramientas desde la tableta: NO VERIFICADO.** La conexión y el envío al panel sí se observaron. El error devuelve el mensaje a la caja y no lo presenta como ejecutado.

Los cuatro casos directos verdes no sustituyen estas dos pruebas fallidas del flujo completo. Resultados locales: `.pytest-tmp-tableta-historial/envio-real-6e8915b88e309d0c.json` y capturas XML. Se dejó abierta de nuevo la conversación recuperada Q5 y su borrador; las conversaciones de prueba se conservan. El diagnóstico nativo confirmó apertura y captura del micrófono; nuevo dictado hasta texto y reproducción de voz siguen NO VERIFICADOS en esta continuación.

No se cambian certificados, vínculo, cortafuegos ni perfiles. El servidor del modelo arrancado para el smoke directo se detuvo al terminar; el panel lo volvió a arrancar para los envíos reales y se conserva para su uso normal.
