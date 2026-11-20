"""Cliente Python generado a partir del borrador OpenAPI de una captura (plan REA, punto 7).

`api_desde_captura` (``eolfi.rea_compuestas``) deduce de una captura de red las rutas, métodos, parámetros y
respuestas OBSERVADOS. Este módulo convierte ese borrador en un cliente Python que solo usa la biblioteca estándar
(``urllib``). Sigue la misma regla que el resto de Eolfi: no se inventa nada.

- Solo hay una función por cada operación (ruta + método) que aparece en el borrador. Sin el nivel completo, en el
  que REA ve los métodos, no se genera cliente: con solo las URI no se sabe qué método usar.
- Los parámetros de ruta salen de la plantilla (``{id}``), los de consulta de los observados y el cuerpo JSON solo
  se acepta donde la captura mostró uno.
- El cliente no lanza excepciones por códigos HTTP: devuelve el código, las cabeceras y el cuerpo, y deja anotado en
  cada respuesta si su código fue observado en la captura o no.
"""
from __future__ import annotations

import keyword
import re
from typing import Any

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class BorradorIncompleto(ValueError):
    """El borrador no tiene métodos observados (nivel básico): no hay base para generar un cliente."""


def _identifier(text: str, fallback: str) -> str:
    name = re.sub(r"_+", "_", re.sub(r"\W+", "_", text, flags=re.ASCII)).strip("_").lower()
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"_{name}"
    return f"{name}_" if keyword.iskeyword(name) else name


def _path_params(template: str) -> tuple[str, list[str]]:
    """'/a/{id}/b/{id}' → ('/a/{id}/b/{id_2}', ['id', 'id_2']): nombres únicos y válidos en Python."""
    used: set[str] = set()
    names: list[str] = []

    def repl(m: re.Match[str]) -> str:
        base = _identifier(m.group(1), "param")
        if base in {"self", "cuerpo"}:
            base += "_ruta"
        name, index = base, 2
        while name in used:
            name, index = f"{base}_{index}", index + 1
        used.add(name)
        names.append(name)
        return "{" + name + "}"

    return _PLACEHOLDER.sub(repl, template), names


def _function_name(method: str, template: str, used: set[str]) -> str:
    parts = [p for p in template.split("/") if p]
    words = [("por_" + _identifier(p[1:-1], "param")) if p.startswith("{") else _identifier(p, "x") for p in parts]
    name = _identifier("_".join([method, *words]) if words else f"{method}_raiz", method)
    base, n = name, 2
    while name in used:
        name, n = f"{base}_{n}", n + 1
    used.add(name)
    return name


def operaciones(openapi: dict[str, Any]) -> list[dict[str, Any]]:
    """Operaciones del borrador en orden estable, con lo que el cliente necesita de cada una."""
    paths = openapi.get("paths") if isinstance(openapi, dict) else None
    if not isinstance(paths, dict) or not paths:
        raise BorradorIncompleto("el borrador no tiene «paths»: hace falta el nivel completo (métodos observados)")
    used: set[str] = set()
    ops = []
    for template in sorted(paths):
        for method in METHODS:
            entry = paths[template].get(method) if isinstance(paths[template], dict) else None
            if not isinstance(entry, dict):
                continue
            path_fmt, path_names = _path_params(template)
            query = sorted({p["name"] for p in entry.get("parameters") or []
                            if isinstance(p, dict) and p.get("in") == "query" and isinstance(p.get("name"), str)})
            codes = sorted(str(c) for c in (entry.get("responses") or {}) if re.fullmatch(r"[1-5][0-9][0-9]", str(c)))
            ops.append({"funcion": _function_name(method, template, used), "metodo": method.upper(),
                        "plantilla": template, "ruta": path_fmt, "parametros_ruta": path_names,
                        "parametros_consulta": query, "cuerpo": "requestBody" in entry, "codigos": codes})
    if not ops:
        raise BorradorIncompleto("el borrador no tiene ninguna operación con método observado")
    return ops


_HEADER = '''"""Cliente de la API observada en una captura de red. Generado por Eolfi (no editar a mano).

{title}
Servidores observados: {servers}

Solo incluye las operaciones vistas en la captura; lo que la API haga además no está aquí. Los tipos y esquemas se
dedujeron de ejemplos. Cada respuesta indica si su código fue observado («observado») o es nuevo.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

SERVIDORES = {servers_list}


@dataclass
class Respuesta:
    codigo: int
    cabeceras: dict[str, str]
    cuerpo: Any
    observado: bool
    codigos_observados: list[str] = field(default_factory=list)


def _origen(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80 if scheme == "http" else None)
    return scheme, (parsed.hostname or "").lower(), port


class _RedireccionSegura(urllib.request.HTTPRedirectHandler):
    """Sigue redirecciones, pero no entrega credenciales a otro origen."""

    def __init__(self, permitir_externa: bool = False):
        super().__init__()
        self.permitir_externa = permitir_externa

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        cambia_origen = _origen(req.full_url) != _origen(newurl)
        if cambia_origen and not self.permitir_externa:
            raise urllib.error.URLError("redirección a otro origen bloqueada")
        nueva = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nueva is not None and cambia_origen:
            seguras = {{"accept", "accept-language", "user-agent"}}
            for nombre in list(nueva.headers):
                if nombre.lower() not in seguras:
                    nueva.remove_header(nombre)
        return nueva


class Cliente:
    def __init__(self, base: str | None = None, *, cabeceras: dict[str, str] | None = None, tiempo: float = 30.0,
                 max_respuesta: int = 16 * 1024 * 1024, redirecciones_externas: bool = False):
        if base is None:
            if not SERVIDORES:
                raise ValueError("la captura no mostró ningún servidor: indica «base»")
            base = SERVIDORES[0]
        if type(base) is not str or "?" in base or "#" in base:
            raise ValueError("«base» debe ser una URL HTTP o HTTPS con host válido")
        try:
            parsed = urllib.parse.urlsplit(base)
            parsed.port
        except ValueError as exc:
            raise ValueError("«base» debe ser una URL HTTP o HTTPS con host válido") from exc
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or any(c.isspace() or c in "/\\\\" for c in parsed.hostname)
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError("«base» debe ser una URL HTTP o HTTPS con host válido")
        if type(tiempo) not in (int, float) or not math.isfinite(tiempo) or tiempo <= 0:
            raise ValueError("«tiempo» debe ser un número positivo y finito de segundos")
        if type(max_respuesta) is not int or max_respuesta <= 0:
            raise ValueError("«max_respuesta» debe ser un número entero positivo de bytes")
        if type(redirecciones_externas) is not bool:
            raise ValueError("«redirecciones_externas» debe ser verdadero o falso")
        self.base = base.rstrip("/")
        self.cabeceras = dict(cabeceras or {{}})
        self.tiempo = tiempo
        self.max_respuesta = max_respuesta
        self._abridor = urllib.request.build_opener(_RedireccionSegura(redirecciones_externas))

    def _pedir(self, metodo: str, ruta: str, consulta: dict[str, Any], cuerpo: Any, observados: list[str]) -> Respuesta:
        url = self.base + ruta
        consulta = {{k: v for k, v in consulta.items() if v is not None}}
        if consulta:
            url += "?" + urllib.parse.urlencode(consulta, doseq=True)
        cabeceras = {{"Accept": "application/json", **self.cabeceras}}
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            cabeceras["Content-Type"] = "application/json"
        peticion = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
        try:
            with self._abridor.open(peticion, timeout=self.tiempo) as r:
                codigo, hdrs, bruto = r.status, dict(r.headers.items()), r.read(self.max_respuesta + 1)
        except urllib.error.HTTPError as e:
            codigo = e.code
            hdrs = dict(e.headers.items()) if e.headers is not None else {{}}
            bruto = e.read(self.max_respuesta + 1)
        if len(bruto) > self.max_respuesta:
            raise ValueError(f"la respuesta supera el límite de {{self.max_respuesta}} bytes")
        texto = bruto.decode("utf-8", errors="replace")
        valor: Any = texto
        content_type = next((value for key, value in hdrs.items() if key.lower() == "content-type"), "")
        if "json" in content_type.lower():
            try:
                valor = json.loads(texto) if texto else None
            except ValueError:
                pass
        return Respuesta(codigo, hdrs, valor, str(codigo) in observados, list(observados))
'''


def escribir_cliente(resultado: dict[str, Any], destino: str) -> dict[str, Any]:
    """Escribe el cliente del resultado de `api_desde_captura` en `destino`, un archivo .py que aún no existe: nunca
    sobrescribe. Devuelve la ruta, el SHA-256 y las operaciones. Con el nivel básico lanza BorradorIncompleto."""
    import hashlib
    from pathlib import Path

    path = Path(destino)
    if path.suffix != ".py":
        raise ValueError(f"el cliente tiene que ser un archivo .py: {destino}")
    source = generar_cliente(resultado.get("openapi") or {})
    with path.open("x", encoding="utf-8", newline="\n") as fh:   # «x»: falla si el archivo ya existe
        fh.write(source)
    ops = operaciones(resultado["openapi"])
    return {"archivo": str(path), "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "operaciones": [f"{o['metodo']} {o['plantilla']} → {o['funcion']}" for o in ops],
            "aviso": "Cliente de lo observado en la captura: revisa credenciales y datos antes de usarlo o compartirlo."}


def generar_cliente(openapi: dict[str, Any]) -> str:
    """Código fuente del cliente para el borrador OpenAPI de `api_desde_captura` (clave «openapi»)."""
    ops = operaciones(openapi)
    servers = [s["url"] for s in openapi.get("servers") or [] if isinstance(s, dict) and isinstance(s.get("url"), str)]
    title = str((openapi.get("info") or {}).get("title") or "API inferida")
    def clean(text: str) -> str:  # textos de la captura que van dentro de un docstring: datos, no código
        return re.sub(r'["\\\x00-\x1f]', "?", text)

    out = [_HEADER.format(title=clean(title), servers=", ".join(map(clean, servers)) or "ninguno",
                          servers_list=repr(servers))]
    for op in ops:
        args = ["self", *op["parametros_ruta"]]
        if op["parametros_consulta"] or op["cuerpo"]:
            args.append("*")
        if op["cuerpo"]:
            args.append("cuerpo: Any")
        reserved = set(op["parametros_ruta"]) | {"self", "cuerpo"}
        used_names = set(reserved)
        q_names = {}
        for q in op["parametros_consulta"]:
            base = _identifier(q, "param")
            name = f"{base}_q" if base in reserved else base
            candidate, index = name, 2
            while candidate in used_names:
                candidate, index = f"{name}_{index}", index + 1
            q_names[q] = candidate
            used_names.add(candidate)
        args += [f"{n}: Any = None" for n in q_names.values()]
        codes = ", ".join(op["codigos"]) or "ninguna"
        shown = re.sub(r'["\\\x00-\x1f]', "?", op["plantilla"])  # la ruta viene de la captura: dato, no código
        ruta = (f"self._ruta({op['ruta']!r}, " + ", ".join(f"{n}={n}" for n in op["parametros_ruta"]) + ")"
                if op["parametros_ruta"] else repr(op["ruta"]))
        consulta = "{" + ", ".join(f"{q!r}: {n}" for q, n in q_names.items()) + "}"
        out.append(
            f"\n    def {op['funcion']}({', '.join(args)}) -> Respuesta:\n"
            f'        """{op["metodo"]} {shown} — respuestas observadas: {codes}."""\n'
            f"        return self._pedir({op['metodo']!r}, {ruta}, {consulta}, "
            f"{'cuerpo' if op['cuerpo'] else 'None'}, {op['codigos']!r})\n")
    out.append(
        "\n    @staticmethod\n"
        "    def _ruta(plantilla: str, **valores: Any) -> str:\n"
        "        return plantilla.format(**{k: urllib.parse.quote(str(v), safe='') for k, v in valores.items()})\n")
    return "".join(out)
