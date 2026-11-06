"""Carga de secretos y ajustes desde un archivo .env (sin dependencias).

Orden de búsqueda (el primero que exista gana en cada variable; nunca se pisa una variable ya definida):
  1. EOLFI_ENV_FILE (ruta explícita)
  2. .env en la carpeta del proyecto (junto a pyproject.toml)
  3. .env en la carpeta actual
  4. ~/.eolfi/.env

Formato: NOMBRE=valor por línea; admite «export », comillas simples o dobles y comentarios con #.
Los valores no se muestran nunca: load_dotenv() devuelve solo los nombres cargados.
EOLFI_NO_DOTENV=1 desactiva la carga (las pruebas lo usan para no depender de tu .env).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _parse_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace("\\n", "\n").replace('\\"', '"') if raw[0] == '"' else inner
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()   # comentario al final de la línea


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = _parse_value(m.group(2))
    return out


def candidates() -> list[Path]:
    paths = []
    if os.environ.get("EOLFI_ENV_FILE"):
        paths.append(Path(os.environ["EOLFI_ENV_FILE"]))
    paths += [Path(__file__).resolve().parents[1] / ".env", Path.cwd() / ".env", Path.home() / ".eolfi" / ".env"]
    seen, uniq = set(), []
    for p in paths:
        key = os.path.normcase(str(p.resolve()))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def load_dotenv(paths: list[Path] | None = None) -> list[str]:
    """Carga las variables que falten. Devuelve los NOMBRES cargados (nunca los valores)."""
    if os.environ.get("EOLFI_NO_DOTENV") == "1":
        return []
    loaded: list[str] = []
    for p in paths if paths is not None else candidates():
        try:
            data = parse(p.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
        for k, v in data.items():
            if k not in os.environ:
                os.environ[k] = v
                loaded.append(k)
    return loaded
