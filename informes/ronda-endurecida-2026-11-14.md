# Ronda de motores endurecida — 2026-11-14

Preparada para que el titular la lance desde el panel y la deje corriendo de noche. Copia de trabajo `D:\Eolfi`,
sin commit.

## Cómo se lanza

Panel → **Seguimiento** → **Prueba de motores en vivo** → marcar **RONDA COMPLETA** → **Ejecutar comparación justa**. La lista solo
ofrece los motores instalados (`GET /api/eolas/perfiles`: sin retirados ni GGUF ausentes). Hoy (7): `gemma_q4`, `gemma`,
`gemma3_q4`, `gemma3_q3`, `gemma3_q5`, `msmall_q4` y `msmall_q3`. `msmall_q5` aparece solo al terminar su descarga
verificada; `qwen14_q5` está retirado.

## Dónde mirar

| Qué | Dónde |
|---|---|
| Progreso en vivo (último paso, últimos 60 mensajes, estado) | `C:\Users\mejil\.eolfi\ronda-progreso.json` |
| Exámenes, respuestas y correcciones (JSONL, esquema `eolfi.examen-motor/1`) | `D:\Eolfi-aportes\examenes\ronda-<fecha>-<id>.jsonl` |
| Resultado completo y registro del trabajo | Panel → Seguimiento → Trabajos (persisten aunque el servidor se reinicie) |

## Qué se endureció

| Cambio | Antes | Ahora |
|---|---|---|
| Lecciones | La ronda aplicaba las lecciones de cada motor y aprendía de sus fallos en los mismos casos | La ronda completa **no aplica ni aprende** lecciones, se marque o no la casilla del panel: ningún caso se apoya en lo aprendido de otro idéntico |
| Motores | Lista fija en el panel | Solo los instalados |
| Registro para Alejandría | Solo el código aprobado (aportes) | Cada caso y motor: examen (enunciado, versión, pruebas o esperado), motor (perfil, GGUF, SHA-256 del `.sha256` verificado, cuantización, contexto, temperatura, repetición), respuesta literal y segundos, y corrección (aprobado, a la primera, corregido tras error, herramientas correctas, salidas de las pruebas, error). Pasado por el redactado de privacidad. Sin duplicados al repetir la ronda (id = SHA-256 de versión del caso, motor, GGUF y respuesta) |
| Supervisión | Solo el registro del trabajo | Archivo de estado legible desde fuera |

Se mantienen de antes:
- Un solo modelo cargado cada vez, con el cerrojo exclusivo y Eolas liberado antes de empezar.
- Si un motor no carga, se salta y se sigue.
- Validación por ejecución en el contenedor aislado, sin red.
- Herramientas que solo cuentan si se usaron de verdad.
- Marca de final aleatoria contra trampas.
- Descarte anticipado al no poder llegar al 75 %.
- El recargador no corta trabajos.
- Un trabajo cortado queda como «interrumpido».

## Segundo endurecimiento (titular: «endurece algo la prueba», aprobado al 85 %)

| Cambio | Detalle |
|---|---|
| Aprobado | **≥85 %** a la primera en código y en herramientas (antes 75 %). El descarte anticipado sale al 3.er fallo de código (de 18) o al 1.er fallo de herramientas (de 5) |
| Casos inéditos | 4 tareas que ningún motor ha visto: `romano`, `rle_bytes`, `orden_topologico`, `duracion`. Cuentan en el código: 8 + 6 + 4 = 18. Su solución de referencia pasa y una equivocada falla (`tests/referencias_ineditos.py`, comprobado también en el contenedor) |
| Formato estricto | El código debe venir en un bloque ```python: si no, no cuenta a la primera. En herramientas, la respuesta debe ser SOLO el objeto JSON pedido |
| Tiempo límite | 300 s por tarea: si se pasa, suspende |
| Herramientas sin inventar | 3 o más llamadas erróneas (rutas inventadas…) suspenden aunque acierte al final |
| Corpus de entrenamiento | Las respuestas BUENAS van a `D:\Eolfi-aportes\corpus-entrenamiento\<tipo>\<a-la-primera|tras-corregir>\<caso>.jsonl` (esquema `eolfi.ejemplo-entrenamiento/1`: mensajes usuario→asistente, verificación, motor y procedencia), sin duplicados |

Lanzada el 14/11/2026 desde la API del panel: trabajo `37286878444128e6`, 7 motores, retirada automática de los que no lleguen (solo retirar; los GGUF se conservan).

## Pendiente para la siguiente ronda (no daba tiempo en ~15 minutos)

- **Casos nuevos** que ningún motor haya visto: esta ronda usa los mismos 19 casos de la anterior.
- **Varias repeticiones por caso** y contar la peor: ahora hay una.
- **Tokens por respuesta** en el registro: ahora quedan como `null`. El límite de salida sí existe (700 en código).
- **Mismo contexto para todos:** Mistral Small usa 16 000 frente a 32 000 del resto, por memoria.
- **Penalizar el formato inválido** en la puntuación: ahora el formato inválido cuenta como fallo, sin una nota aparte.
- **Ingesta en Alejandría:** `Organizar-Corpus` clasifica código y texto (`.md`/`.txt`). Que importe los `.jsonl` de exámenes está **NO VERIFICADO**; se puede añadir la extensión o convertirlos a texto en la siguiente ronda.

## Comprobaciones

- `tests/test_eolas_v2.py`: 49 en verde, incluida la nueva `test_ronda_endurecida_guarda_examenes_sin_duplicar_y_no_aprende`. Cubre sin lecciones, registro con SHA-256, redactado de privacidad, archivo de estado «terminada» y sin duplicados al repetir.
- La ronda real con motores: NO VERIFICADO. La lanza el titular.

## Resultado de la ronda `37286878444128e6` y correcciones (13/11/2026)

Ningún motor llegó al 85 %. La revisión de los exámenes JSONL encontró que **el examen está bien** (enunciados claros;
los fallos de gemma3 son de código real, p. ej. `"<HII4s"` = 14 bytes para una cabecera de 10), pero había **errores de
la ronda** que falseaban el resultado:

| Error | Efecto | Corrección |
|---|---|---|
| IDs de llamada de llama-server devueltos tal cual | La plantilla de Mistral Small los rechaza (HTTP 400 «Tool call IDs should be alphanumeric strings with length 9!»): **los Mistral suspendían siempre en herramientas** (msmall_q3: 89 % en código, 0/5 en herramientas por esto) | `chat.safe_tool_calls`: IDs de 9 alfanuméricos únicos, en la ronda y en el chat. Esquemas de la ronda pasados también por `template_safe` (Gemma 4) |
| Descarte por código antes de llegar a herramientas | Ningún motor llegó a las herramientas; el 0/5 era «sin hacer» | Al no llegar en código salta el resto del código pero hace SIEMPRE las 5 de herramientas |
| Límite de 300 s | Suspendía código correcto: gemma 302 s y 328 s, gemma_q4 419 s, msmall_q4 319 s (cada tarea son dos peticiones a 2–4 tokens/s) | 600 s |
| Versión del examen con la ruta temporal del `.wasm` | Los exámenes de herramientas se duplicaban al repetir la ronda | La versión sale de la plantilla del enunciado |
| El error HTTP solo decía «Bad Request» | No se veía la causa | Se incluye el cuerpo de la respuesta del servidor |

**Repesca** (titular): `run_round(repesca=<archivo de exámenes>)` / panel `{"repesca": "<nombre .jsonl>"}` conserva lo
aprobado a la primera con la misma versión de examen y repite lo fallado o no contestado. Lanzada como trabajo
`9fe914422f59c782` sobre `ronda-20261113-041809-41636b92.jsonl` con los 8 motores (restaurados los 6 retirados por la
ronda anterior; msmall_q5 hace las 23). Pruebas: `tests/test_eolas_v2.py`, `tests/test_chat.py`, `tests/test_server.py`
— 89 en verde, con `test_repesca_conserva_lo_aprobado_y_repite_lo_fallado` y `test_ids_de_llamada_validos_para_la_plantilla_de_mistral`.
Resultado de la repesca: pendiente.

## Resultado de la repesca (13/11/2026)

| Motor | Código a la primera | Herramientas | Veredicto |
|---|---|---|---|
| **gemma** (Gemma 4 12B Q5) | 17/18 (94 %) | 5/5 (100 %) | **APROBADO** |
| gemma_q4 (Gemma 4 12B Q4, activo) | 15/18 (83 %) | 4/5 (80 %) | no aprueba (no se retira: es el activo) |
| gemma3_q4 | 13/18 (72 %) | 0/5 | no aprueba: no llama a herramientas, se inventa los datos. Gemma 3 **eliminado** (q4, q3, q5; 21,75 GB) por decisión del titular |
| msmall_q4 | 15/18 (83 %) | 3/5 | no aprueba, retirado |
| msmall_q3 | 16/18 (89 %) | 2/5 | no aprueba (argumentos de herramienta con JSON roto → HTTP 500), retirado |
| msmall_q5 | 15/18 (83 %) | 3/5 | no aprueba, retirado |

Trabajos `9fe914422f59c782` (cancelado tras gemma3_q4) y `f3bf8d5c77c52800`. Los fallos de los Mistral son suyos
(orden topológico al revés, duraciones inválidas aceptadas, responder de memoria sin consultar Alejandría, escribir el
código en vez de ejecutarlo), salvo `leer_constante` de msmall_q4, debido a la búsqueda de Alejandría (corregida en
`library.py`); ni con ese acierto llegaría al 85 %, así que no se repesca.

## Mistral y las herramientas (13/11/2026)

Titular: «cal é o problema de Mistral coas ferramentas». Diagnóstico con msmall_q5 cargado:

- La plantilla está bien (`/apply-template`: `[AVAILABLE_TOOLS]` con `ejecutar_python` antes del `[INST]`) y el
  analizador de llama-server también: la salida CRUDA del modelo ya era código en un bloque, sin `[TOOL_CALLS]`.
- La causa era **nuestra instrucción de sistema**: «…devuélvela en el formato exacto que pide la tarea, sin texto
  adicional» hacía que Mistral respondiera ya, escribiendo el código. Variantes: instrucción actual a temperatura 0 y
  0,15 → 0 llamadas; instrucción explícita («LLAMA a la herramienta y espera su resultado; no escribas el código ni
  supongas el resultado») o sin instrucción → llama a `ejecutar_python`.
- Corregido `TOOL_SYSTEM_PROTOCOL` (igual para todos los motores) y añadida la misma indicación al chat.
- Comprobación: las 5 tareas de herramientas de la ronda con msmall_q5 → **5/5 a la primera**.
- msmall_q5 se conserva por decisión del titular (su código, 15/18 = 83 %, sigue por debajo del 85 %);
  msmall_q4 y msmall_q3 **eliminados** (25,8 GB).

## Medición más fiable (14/11/2026)

- **Tokens por respuesta** en los exámenes de código: entrada y salida sumando análisis, respuesta y corrección
  (antes `null`). En las tareas de herramientas siguen sin registrarse.
- **Respuestas truncadas**: se guardan con su texto parcial y `truncada: true` (antes el texto se perdía; p. ej.
  gemma_q4 en `rle_bytes`, cortado dos rondas seguidas sin poder ver por qué).
- **`ejecutar_python` con error** cuenta como llamada errónea (suma al límite de 3) y en el chat se muestra «con
  error»: antes bastaba con que el código se ejecutara, aunque acabase en excepción.
