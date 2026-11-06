"""Destino línea de comandos: herramienta en Python (solo librería estándar) para Windows,
macOS y Linux.

- `pip install .` (o `pipx install .`) instala el comando; `python -m <paquete>` también sirve.
- Un subcomando por recurso detectado en las fuentes (listar, añadir, ver, borrar), con
  salida legible o `--json`, códigos de salida correctos y datos en la carpeta de datos del
  usuario de cada sistema (%APPDATA%, ~/Library/Application Support, $XDG_DATA_HOME).
- El CI generado prueba en los tres sistemas y crea un ejecutable único por sistema con
  PyInstaller (opcional, no es dependencia del proyecto).
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from eolfi.generador.generators import Writer


def _pkg(slug: str) -> str:
    """Nombre de paquete importable que no tapa nada (PLAN_MEJORAS A12): «class» daría SyntaxError y
    «json» ocultaría el módulo estándar json a todo el programa."""
    import keyword

    p = re.sub(r"[^a-z0-9_]", "_", slug.lower()).strip("_") or "app"
    reserved = keyword.iskeyword(p) or keyword.issoftkeyword(p) or p in sys.stdlib_module_names         or p in {"test", "tests", "src", "setuptools", "pip", "pytest"}
    if not p[0].isalpha() or reserved:
        p = "app_" + p
    return p


def _cmd(slug: str) -> str:
    c = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-") or "app"
    return c if c[0].isalpha() else "app-" + c


def _res(r: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", r.lower())


STORAGE_PY = r'''"""Almacenamiento local en JSON, en la carpeta de datos del usuario de cada sistema."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APP = "__CMD__"


def data_dir() -> Path:
    """Windows: %APPDATA%; macOS: ~/Library/Application Support; Linux: $XDG_DATA_HOME o ~/.local/share."""
    override = os.environ.get("__ENV__")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP


class Store:
    """Una lista de elementos por recurso; escritura atómica (archivo temporal + reemplazo)."""

    def __init__(self, resource: str) -> None:
        self.path = data_dir() / f"{resource}.json"

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise SystemExit(f"error: no se pudo leer {self.path}: {exc}") from exc
        return data if isinstance(data, list) else []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list(self) -> list[dict[str, Any]]:
        return self._load()

    def add(self, name: str, description: str = "") -> dict[str, Any]:
        items = self._load()
        item = {"id": max((i["id"] for i in items), default=0) + 1, "name": name, "description": description}
        items.append(item)
        self._save(items)
        return item

    def get(self, item_id: int) -> dict[str, Any] | None:
        return next((i for i in self._load() if i["id"] == item_id), None)

    def remove(self, item_id: int) -> bool:
        items = self._load()
        keep = [i for i in items if i["id"] != item_id]
        if len(keep) == len(items):
            return False
        self._save(keep)
        return True
'''

CLI_PY = r'''"""__TITLE__: herramienta de línea de comandos (Windows, macOS y Linux)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from __PKG__ import __version__
from __PKG__.storage import Store, data_dir

RESOURCES = __RESOURCES__


def _print(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    elif isinstance(obj, list):
        if not obj:
            print("(vacío)")
        for item in obj:
            print(f"{item['id']:>4}  {item['name']}" + (f"  — {item['description']}" if item.get("description") else ""))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{k}: {v}")
    else:
        print(obj)


def _name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 200:
        raise argparse.ArgumentTypeError("el nombre debe tener entre 1 y 200 caracteres")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="__CMD__", description="__TITLE__")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--json", action="store_true", help="salida en JSON (para scripts)")
    sub = p.add_subparsers(dest="resource", metavar="RECURSO")
    sub.add_parser("info", help="versión, sistema y carpeta de datos")
    for res in RESOURCES:
        rp = sub.add_parser(res, help=f"gestiona {res}")
        acts = rp.add_subparsers(dest="action", metavar="ACCIÓN", required=True)
        acts.add_parser("list", help=f"lista {res}")
        a = acts.add_parser("add", help=f"añade un elemento a {res}")
        a.add_argument("name", type=_name)
        a.add_argument("-d", "--description", default="")
        for verb, text in (("show", "muestra"), ("remove", "borra")):
            x = acts.add_parser(verb, help=f"{text} un elemento por id")
            x.add_argument("id", type=int)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resource is None:
        build_parser().print_help()
        return 0
    if args.resource == "info":
        _print({"version": __version__, "platform": sys.platform, "data_dir": str(data_dir())}, args.json)
        return 0
    store = Store(args.resource)
    if args.action == "list":
        _print(store.list(), args.json)
    elif args.action == "add":
        _print(store.add(args.name, args.description), args.json)
    elif args.action == "show":
        item = store.get(args.id)
        if item is None:
            print(f"error: no existe {args.resource} {args.id}", file=sys.stderr)
            return 1
        _print(item, args.json)
    elif args.action == "remove":
        if not store.remove(args.id):
            print(f"error: no existe {args.resource} {args.id}", file=sys.stderr)
            return 1
        _print({"removed": args.id}, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST_PY = r'''import json
import subprocess
import sys

import pytest

from __PKG__.cli import RESOURCES, main


@pytest.fixture(autouse=True)
def datos_temporales(tmp_path, monkeypatch):
    monkeypatch.setenv("__ENV__", str(tmp_path))


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_ciclo_completo(capsys):
    res = RESOURCES[0]
    code, out, _ = run(capsys, "--json", res, "add", "Primero", "-d", "descripción")
    assert code == 0 and json.loads(out)["id"] == 1
    code, out, _ = run(capsys, "--json", res, "list")
    assert [i["name"] for i in json.loads(out)] == ["Primero"]
    assert run(capsys, res, "show", "1")[0] == 0
    assert run(capsys, res, "remove", "1")[0] == 0
    code, _, err = run(capsys, res, "show", "1")
    assert code == 1 and "no existe" in err


def test_valida_entradas(capsys):
    with pytest.raises(SystemExit) as exc:
        main([RESOURCES[0], "add", "   "])
    assert exc.value.code == 2


def test_info_y_version(capsys):
    code, out, _ = run(capsys, "--json", "info")
    assert code == 0 and json.loads(out)["platform"] == sys.platform
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "__CMD__" in capsys.readouterr().out


def test_se_ejecuta_como_modulo(tmp_path):
    r = subprocess.run([sys.executable, "-m", "__PKG__", "--json", "info"], capture_output=True, text=True,
                       env={**__import__("os").environ, "__ENV__": str(tmp_path)})
    assert r.returncode == 0 and json.loads(r.stdout)["version"]
'''


def gen_cli(spec: dict[str, Any], w: Writer) -> None:
    slug = spec["name"]
    pkg, cmd = _pkg(slug), _cmd(slug)
    env = pkg.upper() + "_DATA_DIR"
    resources = [_res(r) for r in (spec["api"]["resources"] or ["items"])][:6] or ["items"]
    title = spec["title"]

    def fill(t: str) -> str:
        return (t.replace("__PKG__", pkg).replace("__CMD__", cmd).replace("__ENV__", env)
                 .replace("__TITLE__", title).replace("__RESOURCES__", json.dumps(resources)))

    w(f"src/{pkg}/__init__.py", f'"""{title}."""\n__version__ = "0.1.0"\n')
    w(f"src/{pkg}/__main__.py", f"from {pkg}.cli import main\n\nraise SystemExit(main())\n")
    w(f"src/{pkg}/cli.py", fill(CLI_PY))
    w(f"src/{pkg}/storage.py", fill(STORAGE_PY))
    w("tests/test_cli.py", fill(TEST_PY))
    w("pyproject.toml", f"""[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "{cmd}"
version = "0.1.0"
description = "{title}: herramienta de línea de comandos"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest"]

[project.scripts]
{cmd} = "{pkg}.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
""")
    w("requirements-dev.txt", "pytest\n")
    w("scripts/build_exe.py", f'''"""Ejecutable único para este sistema (Windows .exe, macOS o Linux) con PyInstaller.

    pip install pyinstaller && python scripts/build_exe.py
"""
import subprocess
import sys

sys.exit(subprocess.call([sys.executable, "-m", "PyInstaller", "--onefile", "--name", "{cmd}",
                          "--paths", "src", "src/{pkg}/__main__.py"]))
''')
    w(".gitignore.extra", "build/\n*.spec\n")
