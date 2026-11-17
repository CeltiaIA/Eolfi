# Guía: registro de acciones encadenado y firmado

Eolfi anota en un registro encadenado por SHA-256 (`~/.eolfi/acciones.jsonl`, esquema `eolfi-acciones/v1`) cada
acción que cambia estado: crear o quitar un acceso directo, cambios de Eolas V2 y de modelos, acciones del puente y
del RSI. Las vistas previas no se anotan. Esta guía lo recorre **en una carpeta temporal**, sin tocar tu registro
real. `tests/test_guia_registro_acciones.py` ejecuta estos mismos pasos en la CI.

## 0. Un registro de prueba

```bash
mkdir guia-acciones && cd guia-acciones
export EOLFI_ACCIONES_FILE="$PWD/registro/acciones.jsonl"     # PowerShell: $env:EOLFI_ACCIONES_FILE = "$PWD\registro\acciones.jsonl"
```

Para generar acciones se usa el lanzador de Eolfi en una carpeta de esta prueba (no en el escritorio real):

```bash
python -m eolfi acceso-directo --carpeta lanzadores             # vista previa: no crea ni anota nada
python -m eolfi acceso-directo --carpeta lanzadores --aplicar
```

**Aceptación:** tras la vista previa el registro no existe; tras `--aplicar` hay un evento.

## 1. Ver y verificar la cadena

```bash
python -m eolfi acciones listar
python -m eolfi acciones verificar
```

**Aceptación:** el evento 1 tiene `operacion: instalador.acceso_directo`, `origen: cli`, `ok: true`, `prev` con 64
ceros (es el primero) y su `sha256`. `verificar` da `ok: true`, `eventos: 1` y `ultimo` igual a ese `sha256`.

## 2. Firmar la cabeza de la cadena

```bash
python -m eolfi acciones clave --destino clave/firma.key        # guárdala fuera del equipo en un uso real
python -m eolfi acciones firmar --clave clave/firma.key
python -m eolfi acciones verificar --clave clave/firma.key
```

La firma es HMAC-SHA256 de la cabeza y se añade como un evento más.

**Aceptación:** `clave` no sobrescribe un archivo existente (repetirla con el mismo destino falla). `firmar` da
`firmado_hasta: 1` y `evento: 2`. `verificar --clave` da `firmas.ok: true`, `firmas: 1` y `sin_firmar_al_final: 0`.

## 3. Lo que pasa después de firmar

```bash
python -m eolfi acceso-directo --carpeta lanzadores --quitar
python -m eolfi acciones verificar --clave clave/firma.key
```

**Aceptación:** la cadena sigue íntegra (`eventos: 3`) y `sin_firmar_al_final: 1`: lo posterior a la última firma
se ve como no firmado hasta que vuelvas a firmar.

## 4. Una manipulación se detecta

Cambia a mano `"creado": true` por `"creado": false` en el primer evento de `registro/acciones.jsonl` y verifica:

```bash
python -m eolfi acciones verificar --clave clave/firma.key
```

**Aceptación:** código de salida `2`, `ok: false`, `roto_en: 1` y `motivo: cadena rota`.

Límites (documentados en B8): la firma es simétrica (quien tenga la clave puede firmar) y los eventos posteriores a la
última firma no están protegidos por ella; solo por la cadena.

## Limpieza

Borra la carpeta `guia-acciones` y la variable `EOLFI_ACCIONES_FILE`.
