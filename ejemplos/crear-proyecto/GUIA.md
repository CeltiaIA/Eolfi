# Guía: crear un proyecto nuevo con plan, aprobación y verificación

Recorrido con la muestra sintética de esta carpeta (`fuente/`, propia del proyecto): un recetario web mínimo
(`index.html`, `estilo.css`, `app.js` con `localStorage`). Cada paso dice qué hace, qué queda guardado y su
**criterio de aceptación**. `tests/test_guia_crear_proyecto.py` ejecuta estos mismos pasos en la CI, así que la guía
no puede desfasarse sin que falle una prueba.

«Crear proyecto» genera desde cero un proyecto **nuevo** inspirado en la fuente: no copia su código y no es una
reconstrucción (para eso está la guía de [caja negra](../caja-negra/GUIA.md)). El proyecto solo cuenta como
terminado si su verificación (instalación, compilación, pruebas y prueba de humo, según el destino) pasa. Aquí el
destino es `static` y la verificación usa `node --test`, así que hace falta Node.js. Desde el 17/11/2026 también
mide la accesibilidad con axe, así que hace falta el navegador propio de Eolfi (`eolfi navegador instalar`, una sola
vez) o un Chrome con Playwright. No se usa red ni IA.

## 0. Arrancar Eolfi

```bash
cd ejemplos/crear-proyecto
python -m eolfi --db guia.db serve --port 8777 --samples muestras
```

Es lo mismo que usa el panel en «Herramientas → Crear proyecto». Las peticiones que cambian algo llevan la cabecera
`X-Eolfi: 1` (protección contra peticiones de otras webs). Las rutas relativas se resuelven desde la carpeta en la
que arrancó `serve`.

## 1. Proponer el plan (no ejecuta nada)

```bash
curl -s -X POST http://127.0.0.1:8777/api/projects/plan -H "X-Eolfi: 1" -H "Content-Type: application/json" \
  -d '{"name": "Recetario nuevo", "sources": ["fuente"], "out": "nuevo",
       "description": "Quiero una web en HTML estático. Que tenga modo oscuro."}'
```

**Aceptación:**

- Respuesta `201` con `status: awaiting_approval` y `approved: false`. Anota el `case_id`.
- Tres pasos: `analizar-1` (la fuente), `especificar` y `generar`. Cada uno dice qué hará (`what`), cómo se
  comprueba (`verification`), por qué (`rationale`) y sus riesgos (`risks`).
- Destino `static`, deducido de «HTML estático». «Que tenga modo oscuro.» no se traduce a ninguna opción del
  generador: queda en `interpretation.uninterpreted` y no se aplica sola.
- El razonamiento del plan recuerda que nunca se copia código de la fuente.
- Todavía no hay evidencias en la base ni carpeta `nuevo`.

## 2. Sin aprobación no se ejecuta

```bash
curl -s -X POST http://127.0.0.1:8777/api/jobs -H "X-Eolfi: 1" -H "Content-Type: application/json" \
  -d '{"kind": "project", "body": {"case_id": "CASE_ID"}}'
curl -s "http://127.0.0.1:8777/api/jobs?id=JOB_ID"
```

**Aceptación:** el trabajo termina con `status: error`, código `409` y el mensaje «el plan no está aprobado».
No se escribe nada.

## 3. Aprobar la versión que has revisado

```bash
curl -s -X POST http://127.0.0.1:8777/api/projects/CASE_ID/approve -H "X-Eolfi: 1" \
  -H "Content-Type: application/json" -d '{"version": 1, "note": "revisado"}'
```

**Aceptación:** aprobar una versión que no es la vigente (por ejemplo `"version": 2`) se rechaza con `400` y «la
versión vigente del plan es la 1»: solo se aprueba lo que se ha revisado. Con la
versión 1, `approved: true` y `status: ready`; la aprobación queda en las decisiones del caso con su nota.

## 4. Ejecutar el plan aprobado

```bash
curl -s -X POST http://127.0.0.1:8777/api/jobs -H "X-Eolfi: 1" -H "Content-Type: application/json" \
  -d '{"kind": "project", "body": {"case_id": "CASE_ID"}}'
curl -s "http://127.0.0.1:8777/api/jobs?id=JOB_ID"          # repite hasta que no esté «queued» ni «running»
```

El modo es `auto`: los tres pasos se ejecutan seguidos. En modo `guided` (`"mode": "guided"` en el plan) se
detiene tras cada paso hasta que lo continúes.

**Aceptación:**

- El trabajo termina en `done` y `result.status` es `done` (no `done_unverified`).
- `analizar-1` registra la fuente como objetivo del caso; `especificar` crea la especificación versión 1.
- `generar` usa el destino `static`, escribe archivos en `nuevo` y trae el objeto `verification`.

## 5. Revisar la verificación

En `result.results.generar.verification`:

- `ok` es `true`.
- `steps` lista cada comprobación con su código de salida: `sintaxis JS del sitio (js/main.js)`,
  `pruebas (node --test)` y `juez funcional (3/3)` (sin errores de JavaScript y axe en el tema claro y en el
  oscuro), las tres con `exit: 0`. Sin navegador el juez no puede correr y la verificación no queda en verde.

**Si un paso falla o la verificación no se pudo ejecutar** (por ejemplo, sin Node.js), `generar` queda `partial`,
`verified: false`, el plan termina en `done_unverified` y `note` dice «NO VERIFICADO»: el proyecto no es un
producto listo y no debe presentarse como tal.

## 6. Qué conserva el proyecto de la fuente

**Aceptación** sobre `nuevo/eolfi.spec.json`:

- Página `home`; color de fondo `#fffaf0`, color principal `#8b4513` y fuente `Georgia`, observados en
  `estilo.css`; la función `localStorage` observada en `app.js`.
- Secciones: `Hero` (del `h1`) y `ContactForm` (del formulario); `Features` la añade el generador y lo anota en
  `sections_added`. Los textos son de ejemplo.
- Ninguna línea de `app.js` aparece en el proyecto generado.

`GET /api/projects/CASE_ID` devuelve el mismo estado (`done`) más tarde, también tras reiniciar `serve`: el plan, la
aprobación y el resultado de cada paso están guardados en el caso.

## Sin plan: `create` desde la CLI

```bash
python -m eolfi --db guia.db create --from fuente --out nuevo-cli --name "Recetario CLI"
```

Genera y verifica en un solo paso, sin plan ni aprobación. **Aceptación:** código de salida `0`, `target: static`
y el mismo objeto `verification` (`ok: true`, tres pasos con `exit: 0`). Si la verificación falla, el código de
salida es `5`.

## Limpieza

Borra `guia.db`, `muestras`, `nuevo` y `nuevo-cli`. Nada sale de esta carpeta.
