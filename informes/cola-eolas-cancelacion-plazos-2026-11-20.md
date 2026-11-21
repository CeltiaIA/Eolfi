# Cola de Eolas: cancelación y plazos — 20/11/2026

Se corrigen dos fallos de `_eolas_en_turno`, conservando el comportamiento de la cola existente y el resto de los cambios del servidor compartido.

## Contexto adquirido antes de un aviso que puede fallar

Tras esperar su turno, la función entraba en `inference_profile` y emitía «ya está libre» antes de registrar el contexto en `ExitStack`. Si ese aviso lanzaba `JobCancelled` o un error de progreso, el contexto no salía explícitamente en ese punto; podía permanecer retenido por el traceback.

El contexto se registra ahora antes del aviso. Las regresiones mantienen vivo el traceback y exigen que el `finally` del contexto ya se haya ejecutado al propagarse el error. También se comprueba la salida normal y por excepción del trabajo, con y sin espera previa. Estas pruebas ejecutan la función del workspace con un contexto controlado: no cancelan una petición real de un usuario ni consumen GPU.

Antes del cambio: dos regresiones fallaban y cuatro controles pasaban. Después: ambas regresiones pasan.

## Intervalos y valores del plazo

La cola dormía siempre cinco segundos. Con un límite de seis programaba dos esperas de cinco, y con uno también esperaba cinco. Ahora el siguiente intervalo es el menor entre cinco y el tiempo restante. Los plazos cero o negativos conservan la salida sin espera.

`inf`, `-inf` y `nan` se tratan como valores inválidos y usan el plazo predeterminado finito de 1.200 segundos, igual que un texto no numérico. Antes, infinito podía dejar la espera sin límite; los otros valores no finitos podían cambiarla a cero silenciosamente. No se impone un límite nuevo a los valores finitos configurados por el titular. Se comprueban los intervalos programados; no se garantiza precisión de reloj del planificador del sistema operativo.

Antes de corregir: cinco casos de plazo fallaban y tres controles pasaban. El archivo nuevo `tests/test_turno_eolas.py` conserva **14 casos** de recursos, cancelación y plazos.

## Validación

`python -m pytest -q tests/test_turno_eolas.py tests/test_chat_herramientas.py tests/test_encargos_vscode.py tests/test_chat.py tests/test_chat_honestidad.py tests/test_tableta.py tests/test_tableta_puente.py tests/test_fase_e.py tests/test_i18n.py` → **229 aprobadas, 53,86 s**, salida 0. Registro local: `.pytest-tmp-tableta-historial/cola-cancelacion-plazos.log` (LIM-067).

Ruff F/E9 y `git diff --check` en los archivos afectados: salida 0. Cierre de las cuatro suites: **EN CURSO**, `.pytest-tmp-tableta-historial/cierre-cola-g2-global.log`. Se registraron hashes de 406 archivos de código/pruebas/herramientas durante el inicio de la pasada para contrastar cambios del árbol compartido al terminar; no incluye documentos ni es una prueba de equivalencia funcional.

Sin GPU ni reinicios manuales de servicios en esta tanda. No se reescribieron los cambios existentes de generación desde descripción, archivo de trabajos, traducciones ni especificación. La función de espera de creación de proyectos es distinta de esta cola y no queda acreditada por las pruebas anteriores. Publicación y comprobación global sobre el árbol final: pendientes.
