# B6: restauración completa con modelo real — 20/11/2026

Se comprobó el escenario pendiente de B6: ninguna ronda válida ni parcial, restauración de los archivos originales y ausencia de incorporación a memoria. Proveedor real Eolas V2, modelo activo `gemma4_recon_q4`; no se modificó su configuración. Esta es una prueba negativa controlada, no un proyecto funcional entregado.

## Método

Fuente HTML sintética propia, proyecto estático generado con verificación y una segunda verificación aislada de la plantilla en verde. Después se instaló un único control negativo del juez: exigir cero elementos `body` en la plantilla que se conserva con uno. El encargo pedía únicamente crear `js/restauracion.js`, sin cambiar HTML, pruebas ni criterios; no se intentó eludir ese control.

`assist` se ejecutó con el proveedor real `EolasEngineProvider`, razonamiento desactivado, máximo 1.500 tokens de salida por respuesta y plazo de 180 s. Estos límites son del ensayo, no cambios persistentes del perfil. Memoria, telemetría y RSI se dirigieron a carpetas aisladas del workspace. Se calcularon hashes SHA-256 del árbol del proyecto antes y después.

| Ronda real | Cambio escrito | Pruebas/sintaxis | Juez |
|---|---|---|---|
| 1 | `js/restauracion.js` | Pasan | 0/1; un body, se esperaban cero |
| 2 | `js/restauracion.js` | Pasan | 0/1 |
| 3 | `js/restauracion.js` | Pasan | 0/1 |

## Resultado observado

- `ok: false`, `parcial: false`, `restored: true`, `files_changed: []`.
- Los **16 archivos originales** conservan exactamente sus SHA-256 y el árbol de archivos vuelve al mismo estado; desaparece el JS nuevo escrito por el modelo durante las rondas.
- No se crea la memoria aislada y `verified_memory_saved: false`.
- El guion termina con salida 0 y `RESTAURACION_REAL=True`, porque el comportamiento esperado del ensayo era rechazar y restaurar.

Evidencia resumida reproducible: [JSON del ensayo](b6-restauracion-completa-real-2026-11-20.json), con las rondas, resultados y hashes antes/después. Guion local: `.pytest-tmp-tableta-historial/b6_restauracion_real.py`; proyecto y resultado completo: `b6-restauracion-real-5/`; log: `b6-restauracion-real-5.log`. SHA-256 del resultado completo local: `67f4c116015da61f2687b062f5c4bc29a20b2d461353d9d8645e1f6fc5b6d0d8`.

## Límites y preparación

Las preparaciones anteriores se conservan: dos errores del guion de criterios, un cerrojo del motor ocupado y un error de codificación de salida cp1252. No se cuentan como ensayos completos de tres rondas; la ejecución acreditada es la quinta, con UTF-8. No se borraron esas evidencias (LIM-067).

El ensayo demuestra esta ruta de restauración con un modelo real y una muestra concreta. No demuestra calidad funcional general del modelo, que todos los proyectos puedan restaurarse, ni ausencia de fallos en otros destinos. El servidor se conserva para el panel; al acabar no queda una tarea B6 usando la GPU.
