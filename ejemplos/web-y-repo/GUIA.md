# Guía: aprender de un sitio web y de un repositorio, y crear un proyecto nuevo

Tres flujos con muestras sintéticas propias de esta carpeta, sin red:

- `sitio/`: sitio estático de notas (HTML, CSS y JavaScript sin framework).
- `repo/`: paquete Python `notas` con biblioteca, CLI y pruebas, **sin licencia** a propósito.

Cada paso lleva su **criterio de aceptación**. `tests/test_guia_web_repo.py` ejecuta estos comandos en la CI.

> Con URLs reales, `web` respeta `robots.txt` y solo descarga recursos del mismo origen salvo `--cross-origin`;
> `repo` clona en superficial y sin ejecutar nada del repositorio. Úsalos con contenido que puedas analizar.

## A. Analizar un sitio web

```bash
cd ejemplos/web-y-repo
python -m eolfi --db guia.db web sitio
python -m eolfi --db guia.db evidence --operation web_js
```

**Aceptación:**

- `summary.stack_label` es «HTML estático sin framework detectado»: no se atribuye ningún framework sin evidencia.
- El esqueleto (`page_skeleton`) incluye `header`, `nav`, `main` y `form#nueva`, y los tokens de diseño recogen
  los colores `#fdfcf8` y `#222`, la fuente `system-ui` y las propiedades `--fondo` y `--tinta`.
- La evidencia `web_js` encuentra el endpoint `/api/notas` y el uso de `fetch` y `localStorage` leyendo el
  JavaScript, sin ejecutarlo. `web_accessibility` no tiene incidencias (el campo tiene su `label`).

## B. Analizar un repositorio

```bash
python -m eolfi --db guia.db repo repo
python -m eolfi --db guia.db incognitas
```

**Aceptación:**

- `repo_languages`: Python es el único lenguaje de código; Markdown y TOML aparecen aparte.
- `repo_manifests` lee `pyproject.toml`: nombre `notas`, `requires_python >=3.10` y el script
  `notas = notas.cli:main`.
- `repo_quality` cuenta 1 archivo de pruebas. `how_to_run` propone la instalación con `pip install -e .`.
- Al no haber licencia se abre una incógnita informativa: «Sin licencia detectada: no reutilices su código sin
  permiso».

## C. Crear un proyecto nuevo a partir del sitio

```bash
python -m eolfi --db guia.db create --from sitio --out nuevo --name "Notas nuevo"
```

`create` genera desde cero un proyecto **nuevo** inspirado en la fuente; no es una reconstrucción. Ninguna línea
procede de la fuente, y la verificación (aquí `node --test`, que necesita Node.js) es obligatoria.

**Aceptación:**

- Destino `static` elegido solo (`target: auto`) y `verification.ok` es `true`.
- `eolfi.spec.json` conserva lo observado: las páginas `home` y `acerca`, los colores de fondo y texto, la fuente,
  el endpoint `/api/notas` y las funciones `fetch` y `localStorage`.
- Secciones: `Hero` se infiere del `h1` observado y `ContactForm` del formulario; `Features` la añade el generador
  por defecto aunque la fuente no la tenga, y lo anota en `sections_added`. Los textos son de ejemplo.
