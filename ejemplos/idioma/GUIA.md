# Guía: Eolfi en inglés (panel, API y CLI)

Eolfi responde en castellano por defecto. El inglés se elige de forma explícita y solo cambia los textos fijos de la
interfaz: nunca traduce chats, evidencias, casos ni resultados JSON. `tests/test_guia_idioma.py` ejecuta los pasos de
la CLI y la API en la CI; el panel lo prueba el e2e (`tests/e2e`, prueba «idioma»).

## 1. CLI

```bash
python -m eolfi --idioma en acciones --help
EOLFI_IDIOMA=en python -m eolfi acciones --help                 # PowerShell: $env:EOLFI_IDIOMA = "en"
```

**Aceptación:** la descripción de los subcomandos sale en inglés (por ejemplo «Recomputes the log's SHA-256 chain»);
los nombres de las órdenes y de las opciones no cambian. Sin `--idioma`, «Recalcula la cadena SHA-256 del registro».
Los resultados JSON tienen las mismas claves en los dos idiomas.

## 2. API

```bash
python -m eolfi serve --port 8777
curl -s -i "http://127.0.0.1:8777/api/jobs?id=no-existe"
curl -s -i "http://127.0.0.1:8777/api/jobs?id=no-existe&lang=en"
curl -s -i -H "Accept-Language: en-GB,en;q=0.9" "http://127.0.0.1:8777/api/jobs?id=no-existe"
```

**Aceptación:** `404` en los tres casos. Sin elegir idioma, `{"error": "trabajo no encontrado"}` con
`Content-Language: es`; con `?lang=en`, `Accept-Language` o la cookie `eolfi_idioma=en` (la que pone el panel),
`{"error": "job not found"}` con `Content-Language: en`. Solo se traduce el campo `error`.

## 3. Panel

Abre `http://127.0.0.1:8777/?lang=en` o elige «EN» en el selector de la cabecera. **Aceptación:** los textos fijos
del panel salen en inglés, el contenido de los chats y de las evidencias no cambia, y al volver a «ES» todo vuelve al
castellano.

Pendiente (C1 parcial): textos dinámicos del JS, errores con partes variables y algunos mensajes de la CLI.
