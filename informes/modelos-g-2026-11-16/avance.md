# Bloque G y adjuntos grandes — 16/11/2026

> Registro de la primera entrega. Continuación posterior:
> [auditor en el chat y conexiones por PID](avance-g1-chat-conexiones.md).

Rama local: `codex/modelos-bloque-g`, desde `ca05ef4`. Sin commits ni publicación.
El plan que estaba en `D:\Eolfi-wt-voz\PLAN_DEFINITIVO.md` se ha copiado a la raíz de este workspace y se han
actualizado G1/G2 con su estado parcial. La copia de voz se conserva intacta.

## Implementación

- `eolfi modelos auditar ARCHIVO`: lectura acotada de GGUF v2/v3 little-endian, hash completo, plantilla,
  parámetros del planificador, comprobaciones de dimensiones, duplicados, offsets, solapamientos y truncamiento
  para tipos cubiertos. Tipos K, Q8_1 y desconocidos conservan sus tamaños como incógnitas. Sin carga del modelo.
- `eolfi modelos comprobar ARCHIVO --manifiesto MANIFIESTO`: contraste de SHA-256 por archivo, incluidas todas
  las partes de modelos divididos. La variable `EOLFI_MODELOS_CONFIANZA` activa el control en los arranques
  Python de V2 y llama.cpp. No se ha establecido en el equipo ni aprobado una lista por el usuario.
- Adjuntos del panel: cualquier extensión, sin tope fijo de tamaño en `/api/upload?store=1` y
  `/api/projects/upload`; ambos guardan por bloques de 1 MiB con hash incremental. Se comprueba espacio libre
  antes de leer (tamaño del archivo más 64 MiB de margen). Se conserva el límite de las rutas JSON y del
  antiguo triaje con cuerpo en memoria. Chat, Analizar y Crear proyecto usan las rutas por bloques.
- El selector del chat ya carecía de filtro de extensiones. Ahora explica el tamaño y ofrece la ruta local
  existente para evitar copiar los modelos. Adjuntar no acredita que todos los formatos puedan analizarse.

## Evidencia real GGUF

Archivo: `D:\AI\Hydra\gguf\gemma-4-12b-it-Q4_K_M.gguf`, 7.121.860.000 bytes.
SHA-256 completo leído por Eolfi:
`43fec98c5102b1c446b4ddd0a9439f1db3a2e1f2e0b8cd143ce1ea619a9403d6`.

[Resultado del auditor](auditoria-gemma-q4.json): 667 tensores, 58 claves, cabecera de 15.822.733 bytes,
datos desde 15.822.752. Arquitectura `gemma4`, 48 bloques y ventana deslizante declarada de 1024.
Estado **NO VERIFICADO**: 285 tensores de tipo 12 y 44 de tipo 14 cuyo layout no se puede determinar sin
procedencia adicional. No se afirma que no sobren bytes. Las tres URL recogidas son metadatos de
procedencia/licencia, no defectos ni conexiones observadas.

[Contraste REA](rea-gemma-q4.json): `inspect_model_artifact`, cabecera solamente; coincide en tamaño,
cabecera, alineación, conteos y arquitectura. Hash de cabecera de REA:
`2ae904db2df9f85a4caf69e8775b5cfb8eaa3383db36659e76d8e98af2936dc4`.
Su identidad completa es desconocida porque no leyó los pesos. REA explicita la ambigüedad histórica
de los layouts K; se corrigió el auditor para no imponer el tamaño de bloque habitual.

Plataforma: Windows, Python 3.12 en `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`.
Proveedor de los resúmenes REA: `REA analysis view projection`, versión 1. La versión del parser padre no
se entrega en esta vista; queda **NO VERIFICADA**. No se ejecutó ningún modelo para esta comprobación.

## Pruebas

- `python -m pytest -q tests/test_modelos.py tests/test_eolas_v2.py tests/test_llamacpp.py`: **90 pasadas**.
- `python -m pytest -q tests/test_server.py tests/test_modelos.py`: **65 pasadas**, con servidor HTTP real;
  extensiones variadas, límites antiguos reducidos para comprobar la separación de rutas, rechazo por falta
  de disco y tamaño declarado inválido.
- `node --test` en `eolfi/bridge`: **63 pasadas, 4 omitidas** (navegador real optativo).
- `node --test` en `eolfi/vscode-bridge`: **192 pasadas**.
- `npm test` en `tests/e2e`: **19 pasadas**, incluidas tres extensiones adjuntas por Chrome y axe.
- `git diff --check`: sin errores de espacios. Aviso de normalización CRLF/LF en `eolas_v2.py`.
- [Subida HTTP real de 257 MiB](subida-257mib.json): 200 y hash de destino comprobado. Datos sintéticos,
  no modelo cargable. Esta primera prueba fue anterior a retirar el tope provisional de 64 GiB.

Las primeras ejecuciones restringidas fallaron por acceso denegado a loopback/subprocesos. Se repitieron
los mismos comandos con permisos locales mediante la herramienta. No se alteraron pruebas para dar verde.
[Subida del BF16 real](subida-modelo-bf16.json): **23.832.066.656 bytes**, HTTP 200, hash del archivo
almacenado comprobado mediante relectura completa:
`5a5eefea73350705c6753105b725a51301d653e8d6646173db29a7e8da8e6efd`.
Duración: 1.287,39 s. La copia temporal se eliminó y se comprobó que no queda ninguna carpeta
`.adjunto-modelo-smoke-*` en el workspace. No se cargó el modelo ni se modificó el original. Esta prueba
real usa un cliente HTTP Python; el navegador se probó con adjuntos pequeños de tres extensiones.

Primera suite sobre todos los cambios finales: **704 pasadas, 2 omitidas, 1 fallida**, 1.413,84 s.
Fallo: `tests/test_observe_mobile.py::test_estado_persistente_y_capturas_en_la_especificacion`;
esperaba `contradicted` y obtuvo `observed`. El código móvil y esa prueba no se han modificado.
Repetición aislada con el mismo permiso local: **1 pasada**, 44,56 s. La posible relación con la carga
simultánea de disco no está demostrada; no se atribuye como causa confirmada. La base temporal de aquella
ejecución dejó de existir antes de poder revisar sus registros completos, así que no se reconstruye
una explicación a partir del resultado esperado.

Segunda suite completa, sin la subida simultánea: `python -m pytest -q` → **705 pasadas, 2 omitidas**,
411,83 s, salida 0. No se modificó el código móvil ni se amplió ningún plazo para obtener este resultado.
El primer fallo queda registrado como incidencia de reproducción intermitente cuya causa no se ha
confirmado; la repetición verde no demuestra equivalencia funcional completa.

## Límites y siguiente trabajo

G1 sigue parcial: conexiones del motor no integradas y tamaños ambiguos pendientes. G2 sigue parcial:
no activado, no extendido a Eolas Base ni a arranques directos de clientes externos. El hash no acredita
procedencia, seguridad de pesos, memoria de un proceso ya cargado ni evita todas las carreras entre
comprobación y apertura. G3–G7 quedan pendientes; este avance no cierra el bloque G.

El análisis estático del panel con `analyze_javascript_application` se conserva en `rea-panel.json`.
Alcance: `eolas-chat.js` y `runtime.js`; 6 archivos sin seleccionar, 6 incógnitas de aplicación y 754
semánticas. Sin truncamiento declarado ni errores de parseo en los dos archivos. Los 23 hallazgos son
observaciones, no defectos. La ejecución del navegador, no esta lectura estática, comprueba los adjuntos.
