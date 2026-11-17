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
