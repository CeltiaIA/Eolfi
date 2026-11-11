# Guía: de una API HTTP sin fuentes a una API reconstruida y comprobada

Recorrido con la muestra sintética de esta carpeta (`servidor.py`, propia del proyecto): una API de notas mínima.
Cada paso dice qué hace, qué queda guardado y su **criterio de aceptación**. `tests/test_guia_api_http.py` ejecuta
estos mismos comandos en la CI, así que la guía no puede desfasarse sin que falle una prueba.

> Observar una API **le envía peticiones reales**. Hazlo solo con servicios tuyos o que tengas permiso para probar.
> El guion solo puede llamar a `127.0.0.1`/`localhost` y a los hosts que pongas en `allow_hosts`; cualquier otro
> destino, también por redirección, se bloquea y queda registrado.

## 0. Arrancar la muestra

```bash
cd ejemplos/api-http
python servidor.py --port 8765          # en otra terminal; --port 0 elige un puerto libre y lo imprime
python -m eolfi --db guia.db case create "Notas"                 # anota el case_id
```

## 1. Ver qué se enviaría (sin enviar nada)

```bash
python -m eolfi --db guia.db observe plan guion.json --var port=8765
```

**Aceptación:** `level` es `observed` y `warnings` explica los riesgos. El puerto entra como variable
(`{var:port}`): no se guarda en el guion y en la evidencia aparece normalizado como `{var:port}`.

## 2. Observar

```bash
python -m eolfi --db guia.db observe run guion.json --autorizo --case CASE_ID --var port=8765
```

**Aceptación:** cada paso guarda la petición (cabeceras sensibles redactadas y cuerpo por huella) y la respuesta
(estado, cabeceras, cuerpo). Los estados observados son `200, 200, 404, 200, 400, 200, 200`: un 404 o un 400
también son comportamiento observado.

## 3. Especificar

```bash
python -m eolfi --db guia.db spec build --case CASE_ID
```

**Aceptación:** un requisito por petición distinta. Las respuestas 4xx son requisitos de tipo `error`.
`/api/visitas` se pidió dos veces con la misma petición y respondió distinto, así que su requisito queda
`contradicted` con confianza `low`: hay un estado que la observación no explica.

## 4. Reconstruir la API

```bash
python -m eolfi --db guia.db reconstruct --case CASE_ID --out reconstruccion
```

Sin CLI observada, Eolfi elige el destino `python-http` (también con `--target python-http`): `server.py`,
`api.json` con la tabla petición → respuesta, sus pruebas y `.eolfi/trazabilidad.json` con requisito, ruta y
evidencias por caso.

**Aceptación:**

- `generation`: 5 casos simulados y 1 pendiente (`GET /api/visitas`). La CLI termina con código 4 porque la
  reconstrucción queda parcial: lo pendiente no se inventa.
- `verification`: 5 coinciden y 0 difieren. Para cada caso se arranca la API generada, se repite la petición
  observada y se comparan estado, cuerpo, tipo de contenido y archivos capturados.
- `equivalent_on_observed` es `true` porque solo habla de los casos que se pudieron reconstruir; `complete` es
  `false` porque queda un caso pendiente. Coincidir aquí **no** demuestra equivalencia general.

## 5. Usar y probar la API generada

```bash
python reconstruccion/server.py --port 8766
python -m pytest -q reconstruccion/tests
```

**Aceptación:** las pruebas generadas pasan. Una petición no observada (otra ruta, otro método u otro cuerpo)
responde **501** con `X-Eolfi-Estado: no-especificado`, y `GET /api/visitas` responde **503** con
`X-Eolfi-Estado: pendiente`. No hay ninguna ruta inventada.

## 6. Informe

```bash
python -m eolfi --db guia.db case report CASE_ID --out informe.html
```

**Aceptación:** el informe del caso incluye la observación, la especificación y el registro de la reconstrucción con
sus evidencias.

## Límites declarados

No se reproducen las cabeceras de la petición (la evidencia guarda redactadas las sensibles), ni el valor de las
cookies (solo se conoce su nombre), ni las redirecciones, ni las transiciones de estado entre peticiones. Cada caso
afectado queda `parcial` o `pendiente` con el motivo en `api.json` y en el manifiesto.
