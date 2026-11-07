# Guía: de un programa sin fuentes a una reconstrucción comprobada

Recorrido completo con la muestra sintética de esta carpeta (`contador.py`, propia del proyecto). Cada paso dice
qué hace, qué queda guardado y su **criterio de aceptación**. `tests/test_guia_caja_negra.py` ejecuta exactamente
estos comandos en la CI, así que la guía no puede quedarse desfasada sin que una prueba falle.

> Observar, repetir, comparar equivalencia y explorar **ejecutan el programa**. Hazlo solo con software que puedas
> ejecutar y, si no es tuyo, en el modo contenedor (`"isolation": {"mode": "container", "image": "..."}`) o en una
> VM. Sin contenedor, Eolfi lo ejecuta con tus permisos (no es un sandbox de seguridad).

```bash
cd ejemplos/caja-negra
python -m eolfi --db guia.db case create "Contador"            # anota el case_id
```

## 1. Ver qué se ejecutaría (sin ejecutar nada)

```bash
python -m eolfi --db guia.db observe plan guion.json
```

Muestra programas, hosts, alcance de archivos, entorno, datos que se capturan y no se capturan, dónde se guardan y
cómo borrarlos. **Aceptación:** `level` es `observed` (o `isolated` con contenedor) y `warnings` explica los riesgos.

## 2. Observar

```bash
python -m eolfi --db guia.db observe run guion.json --autorizo --case CASE_ID
python -m eolfi --db guia.db observe replay EVIDENCE_ID --autorizo --case CASE_ID
```

**Aceptación:** cada paso tiene salida, código de salida y efectos en archivos; la repetición dice si fue
reproducible y lista los factores no fijados (reloj, planificación…). `coverage` declara lo que no se observó
(p. ej. llamadas al sistema).

## 3. Especificar

```bash
python -m eolfi --db guia.db spec build --case CASE_ID
python -m eolfi --db guia.db spec review --case CASE_ID REQ-… accepted --reviewer "Tu nombre"
python -m eolfi --db guia.db spec tests --case CASE_ID --out pruebas.json
```

**Aceptación:** un requisito por entrada observada, con evidencias y confianza (`high` tras la repetición); la orden
inválida aparece como requisito de error (código 2); las hipótesis y contradicciones no generan pruebas.

## 4. Reconstruir

```bash
python -m eolfi --db guia.db reconstruct --case CASE_ID --out reconstruccion
```

**Aceptación:** `verification.match` igual al número de casos simulados y `differ = 0`; `.eolfi/trazabilidad.json`
liga cada archivo con sus requisitos; lo que la evidencia no permite reproducir (aquí, el contenido de
`estado/total.txt`, conocido solo por hash) queda **pendiente**, no inventado.

## 5. Medir la equivalencia con el original

```bash
python -m eolfi --db guia.db reconstruct --case CASE_ID --equivalence reconstruccion/app.py --autorizo
python -m eolfi --db guia.db reconstruct --case CASE_ID --explore reconstruccion/app.py --autorizo --seed 7 --variants 4
```

**Aceptación:** la equivalencia lista cada requisito como `equivalent`, `divergent` (con severidad) o
`not_exercised`, y solo dice `equivalent: true` sin divergencias ni huecos. En este ejemplo los efectos en archivos
divergen —la etapa 1 no los reconstruye— y la exploración con variantes muestra que la reconstrucción no
generaliza a entradas no observadas: ambas cosas se ven, no se ocultan.

## 6. Informe y limpieza

```bash
python -m eolfi --db guia.db case report CASE_ID --out informe.html
python -m eolfi --db guia.db observe forget EVIDENCE_ID --confirmo
```

**Aceptación:** el informe enlaza cada conclusión con sus evidencias y oculta datos personales; `forget` borra la
sesión y sus derivadas de la base.

## Sin herramientas externas

Todo este recorrido usa solo Python. El triaje de binarios funciona sin rizin, capa ni Ghidra: el informe incluye
`coverage_gaps` con lo que cada herramienta ausente cubriría y declara que la cobertura **no es equivalente**.
`python -m eolfi doctor --pin herramientas.lock.json` fija las herramientas que sí tengas para repetir resultados.
