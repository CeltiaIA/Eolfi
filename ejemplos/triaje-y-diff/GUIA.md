# Guía: triaje de un binario y verificación diferencial de una reimplementación

Dos flujos con muestras sintéticas propias de esta carpeta, sin herramientas externas:

- `muestra.wasm`: módulo WebAssembly de 42 bytes, generado para la guía, que exporta la función `respuesta`.
- `referencia.py` y `candidato.py`: un contador de líneas, palabras y caracteres y una reimplementación con un fallo
  deliberado. `corpus/` tiene las entradas.

Cada paso lleva su **criterio de aceptación**. `tests/test_guia_triaje_diff.py` ejecuta estos comandos en la CI.

## A. Triaje

```bash
cd ejemplos/triaje-y-diff
python -m eolfi --db guia.db triage muestra.wasm --local --summary
python -m eolfi --db guia.db evidence --operation wasm_module
python -m eolfi --db guia.db report SUBJECT --format md --fail-on high --out informe.md
```

`--local` usa solo los proveedores de la biblioteca estándar: no ejecuta el objetivo ni llama a rizin, capa o Ghidra.

**Aceptación:**

- El resumen dice `format: wasm`, `providers_failed` está vacío y `subject` es el SHA-256 del archivo.
- La evidencia `wasm_module` lista las secciones `type`, `function`, `export` y `code`, y la exportación
  `respuesta` como función. Su `limitations` aclara que no se desensambla el código.
- El informe Markdown enlaza cada evidencia con su proveedor, confianza y autoridad. Con `--fail-on high` la orden
  devuelve 0 porque no quedan incógnitas graves abiertas; en la CI eso sirve como umbral.

## B. Verificación diferencial

```bash
python -m eolfi --db guia.db diff --autorizo --ref "python referencia.py" --cand "python candidato.py" corpus
```

`diff` **ejecuta** los dos comandos con cada entrada del corpus (por la entrada estándar, o en `{input}` si lo pones
en el comando) y compara las salidas normalizadas. Sin `--autorizo` no ejecuta nada.

**Aceptación:**

- Código 4: `ratio` es `0.6667` frente a un `threshold` de `1.0`, `passed` es `false` y `mismatched_inputs` es
  `["sin-salto.txt"]`. La diferencia (`lineas=1` frente a `lineas=0`) sale en `cases[].stdout_diff`.
- Se abre una incógnita por la divergencia, y queda en la base de evidencias.

Corrige el fallo en `candidato.py` (cuenta las líneas con `len(texto.splitlines())`, como la referencia) y repite:

```bash
python -m eolfi --db guia.db diff --autorizo --ref "python referencia.py" --cand "python candidato.py" corpus
```

**Aceptación:** código 0, `passed: true`, `ratio: 1.0`, y la incógnita abierta antes se cierra
(`incognitas_closed: 1`). Que las tres entradas coincidan no prueba que coincidan todas; `--mutate N` añade
entradas mutadas para buscar más diferencias.
