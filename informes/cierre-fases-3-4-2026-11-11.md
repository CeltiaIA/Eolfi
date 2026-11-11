# Cierre de las Fases 3 y 4 — 2026-11-11

Rama `fases-3-4-caja-negra` (desde `main` `68f625e`). Flujo de caja negra: **observar → especificar → reconstruir
→ validar**. Este informe dice qué criterio cierra cada cambio, con qué prueba, y qué queda NO VERIFICADO.

## Criterios abiertos de los que se partía

Los fijaba `PLAN_INGENIERIA_INVERSA_EOLFI.md`:

| Fase | Criterio abierto | Por qué estaba abierto |
|---|---|---|
| 3 | Aceptación: «otra persona puede implementar una función a partir de la especificación sin consultar el código original, y puede identificar qué afirmaciones son seguras, inferidas o desconocidas» | La especificación solo guardaba huellas (SHA-256) de las salidas: no se podía implementar desde ella. No había un grado seguro/inferido/desconocido. El propio plan decía «la aceptación no está demostrada». |
| 4 | Casilla «Aplicar mejoras solo cuando exista una razón verificable… y mantener compatibilidad conductual» | No había ningún mecanismo de mejoras. |
| 4 | Aceptación: «proyecto nuevo que compila/arranca… sin copiar código fuente inaccesible» | Se comprobaba el arranque, pero no la compilación de cada archivo ni la ausencia de código del original. |

## Cambios y criterio que cierra cada uno

| Cambio | Archivos | Criterio | Pruebas |
|---|---|---|---|
| Ejemplos literales por requisito (`examples`: argumentos, stdin, stdout/stderr, código, petición y respuesta HTTP, contenido de archivos capturados). Lo que la evidencia no guarda completo, o guarda con datos personales ocultados, va a `omitted` y no se inventa. | `eolfi/spec/build.py` | F3, aceptación (implementable) | `tests/test_spec_contract.py` |
| Grado de cada afirmación: `certainty` por requisito y un resumen en la especificación: **seguro**, **inferido** y **desconocido**. Las entradas no observadas figuran siempre como desconocidas. | `eolfi/spec/build.py` | F3, aceptación (seguro/inferido/desconocido) | `test_grados_inferido_y_desconocido` |
| Contrato de implementación `eolfi spec contract --case ID [--format md\|json] [--out]`: Dado/Entonces, orden observado de los pasos, grado y desconocidos. Sale solo de la especificación guardada. | `eolfi/spec/contract.py`, `eolfi/spec/__init__.py`, `eolfi/cli.py` | F3, aceptación | `test_contrato_basta_para_implementar_sin_el_original` |
| Demostración: guion con contenido capturado e implementación escrita desde el contrato. Resultado: `equivalent: true` en los 3 requisitos, incluido el archivo `estado/total.txt`; el contrato no contiene ninguna línea significativa de `contador.py`. | `ejemplos/caja-negra/guion-contenidos.json`, `ejemplos/caja-negra/desde-contrato/contador_contrato.py`, `GUIA.md` (3b) | F3, aceptación | ídem |
| **Defecto corregido:** tras capturar el contenido de un archivo, el paso siguiente lo daba por «modified» sin haberlo tocado. Causa: el dict de la instantánea se modificaba en el sitio. Lo vi al generar el contrato: decía que la orden inválida escribía el archivo. | `eolfi/observe/session.py` | F3 (exactitud de la especificación) | aserción de regresión en `test_contrato_…` |
| Mejoras con razón verificable: catálogo con categoría admitida, razón y comprobación (`seguridad-nosniff`, `seguridad-limite-cuerpo[=BYTES]`, `compatibilidad-utf8`), activadas con `--mejora` (repetible). Solo se aplican si se piden. Se rechazan, con el motivo en el manifiesto, si son de otro destino, si romperían un requisito observado (un límite menor que un cuerpo observado; se listan los requisitos) o si su razón no se puede comprobar con esta especificación (sin salida no ASCII, la de UTF-8). | `eolfi/reconstruct/improvements.py`, `eolfi/reconstruct/core.py`, `eolfi/cli.py` | F4, casilla de mejoras | `tests/test_reconstruct_mejoras.py` (6) |
| Compatibilidad conductual: `verify` repite todos los casos observados con las mejoras aplicadas y ejecuta la comprobación de cada mejora (cabecera presente, 413 con límite+1 sin leer el cuerpo, salida idéntica con `PYTHONIOENCODING=ascii`). La prueba compara los resultados con y sin mejoras. La razón de UTF-8 se demuestra: sin la mejora, la base falla con `UnicodeEncodeError` en una consola ASCII. | `eolfi/reconstruct/core.py` | F4, casilla de mejoras | `test_http_mejoras_…`, `test_utf8_razon_demostrada_…` |
| Regenerar sin una mejora retira `mejoras.json`, salvo que se haya editado a mano (en ese caso se conserva y se avisa). | `eolfi/reconstruct/core.py` | F4 (regenerar sin destruir cambios manuales) | `test_utf8_…` |
| `verify.build`: compila cada `.py` generado. `verify.independence`: el código generado (`.py`, README) no comparte líneas de ≥20 caracteres con el objetivo cuando es texto accesible; `copia` deja la reconstrucción en «partial» y la CLI en código 4. Las dos cosas quedan en la evidencia `reconstruction_verification`. | `eolfi/reconstruct/core.py` | F4, aceptación | `test_compila_e_independiente_del_original` |

Los datos generados (`comportamiento.json`, `api.json`) contienen a propósito las salidas observadas. Por eso no
entran en la comparación de independencia; esa limitación está declarada en `limits`.

## Comandos ejecutados y resultados (Windows 11, Python 3.12.10, `D:\Eolfi-fases34`)

| Comprobación | Resultado |
|---|---|
| `python -m pytest -q` | 516 aprobadas, 2 omitidas, 0 fallos (4 min 56 s) |
| `node --test` en `eolfi/bridge` | 67 pruebas: 63 aprobadas, 0 fallos, 4 omitidas |
| `node --test` en `eolfi/vscode-bridge` | 178 aprobadas, 0 fallos |
| `npm test` en `tests/e2e` | 18 aprobadas, 0 fallos |
| `python -m ruff check --select F eolfi` y archivos de prueba nuevos | sin avisos |

`node_modules` de `eolfi/bridge` y `tests/e2e` son uniones a las de `D:\Eolfi`, como en `D:\Eolfi-objetivos`. Git
las ignora y no se instaló nada.

## NO VERIFICADO y límites

- **Que una persona independiente implemente desde el contrato.** La implementación de ejemplo la escribí yo, que
  conocía la muestra. La prueba demuestra que el contrato contiene lo necesario y que una implementación hecha
  desde él es equivalente en lo observado, no la independencia de quien la escribe.
- **Equivalencia general:** solo cubre las entradas observadas. Las no observadas siguen siendo «comportamiento no
  especificado», por definición.
- La independencia no detecta copias reescritas (otros nombres u otro formato) ni compara objetivos binarios
  (`no_comprobado`).
- Siguen sin generarse: transiciones de estado entre peticiones o ejecuciones, cookies, redirecciones, cabeceras
  de petición, interfaz de usuario y registro de Windows. Se declaran pendientes o parciales.
- Las evidencias de un caso se siguen reuniendo por subject: un caso ve también sesiones del mismo objetivo hechas
  fuera de él (límite anterior, sin cambios).
- Linux y macOS: solo los comprueba la CI de la PR (macOS ya no está en la CI).
- No se usó @eolfi en modo automático: el titular pidió hacerlo directamente.

## Registro de limpieza

Sin candidatos nuevos en el repositorio. Fuera de él quedan dos copias de trabajo temporales de esta sesión:
`D:\Eolfi-sim34` (simulación, desacoplada) y `D:\Eolfi-fases34` (esta rama). Se anotan en `ESTADO-TRABAJO.md` y no
se han borrado.
