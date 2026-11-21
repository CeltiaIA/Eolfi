# G2: identidades de Alejandría y reconstruido activo — 20/11/2026

Selección del titular: modelos actuales de `D:\Alejandria` y el reconstruido activo `D:\Eolfi\generated\modelos\gemma4-q4_k_m-2026-11-17\modelo.gguf`. Se fijan archivos por ruta absoluta y SHA-256; no se autoriza automáticamente un archivo futuro por estar dentro de la carpeta.

## Auditoría y lista preparada

Se recorrieron los bytes y la estructura de **67 GGUF, 162,25 GiB**, sin cargar sus pesos en un motor. Los 67 hashes calculados coinciden con los nombres del almacén; esa coincidencia es una comprobación interna, no una referencia independiente de procedencia.

- 46 archivos con `estructura_verificada`.
- 2 archivos con tensores pero estado `NO VERIFICADO`: el auditor no tiene tamaño establecido para el tipo 20 (96 tensores, hash `1b36b5c87047351aae5964ff9cbcd04b68a0da949618965c8adfc947da641b1f`) ni el tipo 23 (223 tensores, hash `3a212726e2c1811356d6e85e54cc339aa8abc59b5971cafc12839aac5f12380d`). Esas incógnitas siguen abiertas; fijar su hash no resuelve la validación estructural.
- 19 vocabularios sin tensores, rechazados como modelos de pesos por el auditor y excluidos de la lista. No se declara por ello que los vocabularios sean archivos corruptos ni se propone borrarlos.

El reconstruido se auditó aparte: 7.381.383.776 bytes, 667 tensores, `estructura_verificada`, SHA-256 `d5afb9efb2fa6e39cf9d64e96292f13f5b20c381789643fc9b6f15c9fdc3b054`, coincidente con el fijado en su perfil.

Lista local preparada: `generated/politicas-modelos/modelos-confianza-2026-11-20.json`, esquema `eolfi.modelos.confianza/v1`, **49 rutas** (48 de Alejandría con tensores y sin errores declarados, incluido el estado incompleto de los dos tipos anteriores, más la ruta del reconstruido). Dos rutas pueden corresponder a los mismos bytes. SHA-256 del manifiesto: `ebe2e31d04928a4b3bedd003a158102644401dac18fb3a1822935509bb3c7d31`.

El comprobador real `check_trust` relee el reconstruido y devuelve `hash_autorizado`; una ruta ajena a la lista queda bloqueada. La lista conserva `procedencia: NO VERIFICADO`: la elección del titular y el hash no demuestran origen independiente, seguridad de pesos ni calidad de inferencia. Los Nemotron safetensors se revisan en [su informe separado](nemotron-revision-local-2026-11-20.md); no se convierten ni se cargan aquí.

## Compatibilidad de opciones

La política anterior rechazaba todos los `extra_args`, incluidas las opciones acotadas del perfil activo. En `_start_locked` se validan ahora tanto las opciones globales como las del perfil contra `USER_EXTRA_ARGS`: `-fa`, `-ctk`, `-ctv`, `-np` y `--cache-ram`, con sus valores ya delimitados. No se modifica ninguna opción del perfil. Cambios de modelo, LoRA, proyector, host, clave, valores que inyectan otra opción y pares incompletos siguen rechazándose antes de consultar el runtime o iniciar procesos.

Regresión inicial: 3 casos válidos fallaban y 16 controles de opciones prohibidas pasaban. Tras corregir: `python -m pytest -q tests/test_modelos.py tests/test_eolas_v2.py tests/test_modelos_reconstruir.py` → **170 aprobadas, 6 omitidas, 19,89 s**, salida 0. Ruff F/E9 y diff-check: salida 0. Cierre global del árbol final: pendiente; los verdes de commits anteriores no acreditan esta modificación nueva.

## Estado de activación y evidencia

**La política persistente del panel no se ha activado.** El proceso de prueba real estableció `EOLFI_MODELOS_CONFIANZA` con ese manifiesto, entró en `inference_profile` con el código del workspace y pidió 2+2 al modelo activo: respuesta exacta `4`, salida 0. Evidencia local `probar_confianza_real.py/.json` y `g2-smoke-real.log`; el JSON confirma el mismo SHA-256 del manifiesto y el alcance «solo este proceso de prueba». No valida la calidad general de los otros 48 archivos.

La activación del panel requiere integrar/revisar el cambio, configurar la ruta del manifiesto en su arranque y comprobar el servicio sin interrumpir trabajos vivos. Un cliente o arranque que no reciba `EOLFI_MODELOS_CONFIANZA` no queda protegido por el mero hecho de existir el archivo. Las rutas configuradas fuera de la lista quedan bloqueadas aunque correspondan a otro perfil preexistente; no se amplía automáticamente la selección a copias externas.

Guiones y resultados locales en `.pytest-tmp-tableta-historial/` (LIM-067): `inventario_confianza.py/.json`, `auditar_confianza_alejandria.py`, `confianza-alejandria-auditorias.json`, `confianza-alejandria-propuesta.json` (no activable), `preparar_lista_autorizada.py`, `confianza-lista-resumen.json`, `confianza-reconstruido-auditoria.json` y `g2-compatibilidad-pruebas.log`. El guion de prueba del modelo usa el código del workspace, no una copia interna. No hay entrenamiento, descarga nueva, cambio de perfil, modificación de cortafuegos ni limpieza de archivos.
