"""Receta de despliegue de los proyectos generados (PLAN_DEFINITIVO.md, C4; 17/11/2026).

Cada proyecto lleva ``DESPLIEGUE.md`` con lo que hay que publicar, cómo compilarlo y arrancarlo en producción, las
variables de entorno que lee SU plantilla y las cabeceras de seguridad. Los pasos de compilación y pruebas son los
que la verificación de Eolfi ejecuta; el despliegue en sí (hosting, proxy, HTTPS) Eolfi no lo prueba y la receta lo
dice. Solo se citan variables que la plantilla lee de verdad (una prueba lo comprueba).
"""
from __future__ import annotations

from typing import Any

# Variables de entorno de producción que lee cada plantilla, con su condición.
VARIABLES: dict[str, list[tuple[str, str]]] = {
    "express": [("PORT", "puerto (por defecto 8000)"),
                ("APP_DB", "ruta de la base SQLite si se generó con `--db sqlite` (por defecto `data/app.db`)")],
    "next": [("NODE_ENV", "`production` activa las cabeceras de seguridad (`npm start` ya lo pone)"),
             ("AUTH_USER", "usuario del inicio de sesión si se generó con `--auth`"),
             ("AUTH_PASSWORD", "contraseña del inicio de sesión si se generó con `--auth`"),
             ("AUTH_SECRET", "clave de la sesión firmada si se generó con `--auth`; defínela en producción")],
    "fastapi": [("APP_DB", "ruta de la base SQLite si se generó con `--db sqlite` (por defecto `data/app.db`)")],
    "django": [("DJANGO_SECRET_KEY", "obligatoria con `DJANGO_DEBUG=0`; sin ella no arranca"),
               ("DJANGO_DEBUG", "`0` en producción"),
               ("DJANGO_ALLOWED_HOSTS", "dominios separados por comas"),
               ("DJANGO_SSL_REDIRECT", "`1` para redirigir a HTTPS"),
               ("DJANGO_SECURE_PROXY", "`1` detrás de un proxy que termina el HTTPS"),
               ("DJANGO_HSTS_SECONDS", "segundos de HSTS cuando el HTTPS ya funciona")],
}

_PROXY = ("Ponlo detrás de un proxy inverso con HTTPS (nginx, Caddy, Traefik) y no expongas el puerto de la app "
          "directamente.")


def _cabeceras(headers: dict[str, str]) -> str:
    filas = "\n".join(f"| `{k}` | `{v}` |" for k, v in headers.items())
    nginx = "\n".join(f"add_header {k} \"{v}\" always;" for k, v in headers.items())
    return f"""## Cabeceras de seguridad

Las mismas que sirve el proyecto en local. Configúralas también en el hosting:

| Cabecera | Valor |
|---|---|
{filas}

Ejemplo para nginx:

```nginx
{nginx}
```
"""


def _por_destino(spec: dict[str, Any]) -> tuple[str, str]:
    t = spec["target"]
    if t == "static":
        return ("Sitio estático: no hay compilación.", """## Publicar

Sube la carpeta del proyecto a cualquier hosting estático (GitHub Pages, Netlify, Cloudflare Pages, nginx) **sin**
`scripts/`, `tests/`, `package.json`, `eolfi.spec.json` ni `eolfi.juez.json`.

- La aplicación es instalable (PWA): `manifest.webmanifest`, `icon.svg` y `sw.js`, que guarda en caché solo los
  archivos propios para funcionar sin conexión. El *service worker* exige **HTTPS** (o `localhost`).
- Si cambias archivos, sube también un `sw.js` con otro valor de `VERSION` para que los navegadores renueven la
  caché.
""")
    if t in ("react", "vue", "svelte"):
        return ("```bash\nnpm ci\nnpm run build\n```", """## Publicar

Publica el contenido de `dist/` en un hosting estático. Es una aplicación de una sola página: las rutas
desconocidas deben servir `index.html` (en nginx, `try_files $uri /index.html;`).
""")
    if t == "next":
        return ("```bash\nnpm ci\nnpm run build\n```", f"""## Arrancar en producción

```bash
npm start -- -p 3000
```

Node.js 22. {_PROXY}
""")
    if t == "express":
        return ("```bash\nnpm ci --omit=dev\n```", f"""## Arrancar en producción

```bash
PORT=8000 node src/server.js
```

{_PROXY} Con `--db sqlite`, haz copias de seguridad de la base (`APP_DB`).
""")
    if t == "fastapi":
        return ("```bash\npython -m venv .venv\n.venv/bin/pip install -r requirements.txt\n```",
                f"""## Arrancar en producción

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

{_PROXY} Con `--db sqlite`, haz copias de seguridad de la base (`APP_DB`).
""")
    if t == "django":
        return ("```bash\npython -m venv .venv\n.venv/bin/pip install -r requirements.txt gunicorn\n"
                "DJANGO_DEBUG=0 DJANGO_SECRET_KEY=... .venv/bin/python manage.py check --deploy\n"
                ".venv/bin/python manage.py migrate\n```", f"""## Arrancar en producción

```bash
.venv/bin/gunicorn config.wsgi -b 127.0.0.1:8000
```

{_PROXY} `manage.py check --deploy` enumera lo que falta para producción; revísalo antes de publicar.
""")
    return ("Consulta «Verificar» en `README.md`.", """## Distribuir

Este destino no se publica en un servidor web: sigue «Arrancar» en `README.md` para construir el ejecutable, el
paquete o la aplicación de tu plataforma.
""")


def receta(spec: dict[str, Any], headers: dict[str, str], docker: bool) -> str:
    t = spec["target"]
    compilar, resto = _por_destino(spec)
    variables = VARIABLES.get(t, [])
    tabla = ("## Variables de entorno\n\n| Variable | Para qué |\n|---|---|\n"
             + "\n".join(f"| `{k}` | {v} |" for k, v in variables) + "\n\n") if variables else ""
    web = t in ("static", "react", "vue", "svelte", "next", "express", "fastapi", "django")
    contenedor = ("## Contenedor\n\nEl proyecto trae `Dockerfile`: `docker build -t app .` y `docker run -p 8000:8000 "
                  "app` (con las variables de arriba).\n\n") if docker else ""
    return f"""# Despliegue de {spec["title"]}

Receta generada por Eolfi para el destino `{t}`. La compilación y las pruebas son las que ejecuta la verificación
de Eolfi; **el despliegue (hosting, proxy y HTTPS) no lo ha probado Eolfi**: compruébalo en tu entorno.

## Compilar

{compilar}

{resto}
{tabla}{contenedor}{_cabeceras(headers) if web else ""}"""


# --- Inglés (C4, 18/11/2026: proyectos generados con --idioma-proyecto en) ----------------------------------------
# Mismo contenido que la receta en castellano; DEPLOYMENT.md en lugar de DESPLIEGUE.md. El castellano no cambia.
VARIABLES_EN: dict[str, dict[str, str]] = {
    "express": {"PORT": "port (8000 by default)",
                "APP_DB": "path of the SQLite database if generated with `--db sqlite` (`data/app.db` by default)"},
    "next": {"NODE_ENV": "`production` enables the security headers (`npm start` already sets it)",
             "AUTH_USER": "sign-in user if generated with `--auth`",
             "AUTH_PASSWORD": "sign-in password if generated with `--auth`",
             "AUTH_SECRET": "key of the signed session if generated with `--auth`; set it in production"},
    "fastapi": {"APP_DB": "path of the SQLite database if generated with `--db sqlite` (`data/app.db` by default)"},
    "django": {"DJANGO_SECRET_KEY": "required with `DJANGO_DEBUG=0`; it does not start without it",
               "DJANGO_DEBUG": "`0` in production",
               "DJANGO_ALLOWED_HOSTS": "comma-separated domains",
               "DJANGO_SSL_REDIRECT": "`1` to redirect to HTTPS",
               "DJANGO_SECURE_PROXY": "`1` behind a proxy that terminates HTTPS",
               "DJANGO_HSTS_SECONDS": "HSTS seconds once HTTPS already works"},
}

_PROXY_EN = ("Put it behind a reverse proxy with HTTPS (nginx, Caddy, Traefik) and do not expose the app port "
             "directly.")


def _cabeceras_en(headers: dict[str, str]) -> str:
    filas = "\n".join(f"| `{k}` | `{v}` |" for k, v in headers.items())
    nginx = "\n".join(f"add_header {k} \"{v}\" always;" for k, v in headers.items())
    return f"""## Security headers

The same ones the project serves locally. Configure them on your hosting too:

| Header | Value |
|---|---|
{filas}

Example for nginx:

```nginx
{nginx}
```
"""


def _por_destino_en(spec: dict[str, Any]) -> tuple[str, str]:
    t = spec["target"]
    if t == "static":
        return ("Static site: there is no build step.", """## Publish

Upload the project folder to any static hosting (GitHub Pages, Netlify, Cloudflare Pages, nginx) **without**
`scripts/`, `tests/`, `package.json`, `eolfi.spec.json` or `eolfi.juez.json`.

- The app is installable (PWA): `manifest.webmanifest`, `icon.svg` and `sw.js`, which caches only the project's own
  files to work offline. The *service worker* requires **HTTPS** (or `localhost`).
- If you change files, also upload an `sw.js` with another `VERSION` value so browsers refresh the cache.
""")
    if t in ("react", "vue", "svelte"):
        return ("```bash\nnpm ci\nnpm run build\n```", """## Publish

Publish the contents of `dist/` on a static hosting. It is a single-page app: unknown routes must serve
`index.html` (in nginx, `try_files $uri /index.html;`).
""")
    if t == "next":
        return ("```bash\nnpm ci\nnpm run build\n```", f"""## Run in production

```bash
npm start -- -p 3000
```

Node.js 22. {_PROXY_EN}
""")
    if t == "express":
        return ("```bash\nnpm ci --omit=dev\n```", f"""## Run in production

```bash
PORT=8000 node src/server.js
```

{_PROXY_EN} With `--db sqlite`, back up the database (`APP_DB`).
""")
    if t == "fastapi":
        return ("```bash\npython -m venv .venv\n.venv/bin/pip install -r requirements.txt\n```",
                f"""## Run in production

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

{_PROXY_EN} With `--db sqlite`, back up the database (`APP_DB`).
""")
    if t == "django":
        return ("```bash\npython -m venv .venv\n.venv/bin/pip install -r requirements.txt gunicorn\n"
                "DJANGO_DEBUG=0 DJANGO_SECRET_KEY=... .venv/bin/python manage.py check --deploy\n"
                ".venv/bin/python manage.py migrate\n```", f"""## Run in production

```bash
.venv/bin/gunicorn config.wsgi -b 127.0.0.1:8000
```

{_PROXY_EN} `manage.py check --deploy` lists what is missing for production; review it before publishing.
""")
    return ("See «Verify» in `README.md`.", """## Distribute

This target is not published on a web server: follow «Run» in `README.md` to build the executable, the package or the
app for your platform.
""")


def receta_en(spec: dict[str, Any], headers: dict[str, str], docker: bool) -> str:
    t = spec["target"]
    compilar, resto = _por_destino_en(spec)
    variables = [(k, VARIABLES_EN[t][k]) for k, _ in VARIABLES.get(t, [])]
    tabla = ("## Environment variables\n\n| Variable | Purpose |\n|---|---|\n"
             + "\n".join(f"| `{k}` | {v} |" for k, v in variables) + "\n\n") if variables else ""
    web = t in ("static", "react", "vue", "svelte", "next", "express", "fastapi", "django")
    contenedor = ("## Container\n\nThe project includes a `Dockerfile`: `docker build -t app .` and `docker run -p "
                  "8000:8000 app` (with the variables above).\n\n") if docker else ""
    return f"""# Deployment of {spec["title"]}

Recipe generated by Eolfi for the `{t}` target. The build and the tests are the ones Eolfi's verification runs;
**the deployment (hosting, proxy and HTTPS) has not been tested by Eolfi**: check it in your environment.

## Build

{compilar}

{resto}
{tabla}{contenedor}{_cabeceras_en(headers) if web else ""}"""
