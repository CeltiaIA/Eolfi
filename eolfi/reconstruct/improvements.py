"""Mejoras de la reconstrucción con razón verificable (Fase 4).

Una mejora solo se aplica si el operador la pide, si tiene una razón de una de las categorías admitidas
(seguridad, accesibilidad, rendimiento, compatibilidad, mantenibilidad), si es compatible con TODO el
comportamiento observado que exige la especificación y si su efecto se puede comprobar al ejecutar la base
generada. Las que no cumplen se registran como rechazadas con el motivo; nunca se aplican en silencio.

La compatibilidad conductual la sigue comprobando ``verify`` con los casos observados: una mejora aplicada que
cambiara un resultado observado haría que el caso «difiera».
"""
from __future__ import annotations

from typing import Any

CATEGORIES = ("seguridad", "accesibilidad", "rendimiento", "compatibilidad", "mantenibilidad")
DEFAULT_BODY_LIMIT = 1024 * 1024

CATALOG: dict[str, dict[str, Any]] = {
    "seguridad-nosniff": {
        "target": "python-http", "category": "seguridad",
        "reason": "Añade «X-Content-Type-Options: nosniff» a las respuestas para que el navegador no interprete el "
                  "cuerpo con otro tipo de contenido (MIME sniffing).",
        "check": "cada respuesta lleva la cabecera X-Content-Type-Options: nosniff",
    },
    "seguridad-limite-cuerpo": {
        "target": "python-http", "category": "seguridad", "param": "bytes",
        "reason": "Rechaza con 413 los cuerpos de petición mayores que el límite antes de leerlos, para que una "
                  "petición enorme no agote la memoria del servidor.",
        "check": "una petición con un cuerpo de límite+1 bytes recibe 413 sin leerse",
    },
    "compatibilidad-utf8": {
        "target": "python-cli", "category": "compatibilidad",
        "reason": "Escribe la salida estándar y la de error en UTF-8 aunque la consola o PYTHONIOENCODING usen otra "
                  "codificación, para que la salida observada no cambie ni falle según el equipo.",
        "check": "con PYTHONIOENCODING=ascii los casos observados siguen dando la misma salida",
    },
}


def parse(spec: str) -> tuple[str, str | None]:
    """«id» o «id=valor» (p. ej. «seguridad-limite-cuerpo=4096»)."""
    ident, _, value = spec.partition("=")
    ident = ident.strip()
    if ident not in CATALOG:
        raise ValueError(f"mejora desconocida: {ident} (disponibles: {', '.join(sorted(CATALOG))})")
    return ident, (value.strip() or None) if _ else None


def plan(requested: list[str] | None, target: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decide qué mejoras pedidas se aplican. Cada entrada lleva su razón, su comprobación y, si se rechaza, por
    qué (destino distinto, parámetro no válido o conflicto con un requisito observado)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in requested or []:
        ident, value = parse(raw)
        if ident in seen:
            raise ValueError(f"mejora repetida: {ident}")
        seen.add(ident)
        info = CATALOG[ident]
        item: dict[str, Any] = {"id": ident, "category": info["category"], "reason": info["reason"],
                                "check": info["check"], "status": "applied", "params": {}}
        if info["target"] != target:
            item.update(status="rejected", why=f"solo aplica al destino {info['target']}, no a {target}")
        elif ident == "seguridad-limite-cuerpo":
            try:
                limit = int(value) if value is not None else DEFAULT_BODY_LIMIT
            except ValueError:
                limit = -1
            if limit < 1:
                item.update(status="rejected", why=f"límite no válido: {value!r} (entero positivo de bytes)")
            else:
                import base64

                sizes = {c["requirement"]: len(base64.b64decode(c["request_body_base64"]))
                         for c in cases if c.get("request_body_base64")}
                broken = sorted(r for r, n in sizes.items() if n > limit)
                item["params"] = {"bytes": limit}
                if broken:
                    item.update(status="rejected", requirements=broken,
                                why=f"rompería la compatibilidad: {', '.join(broken)} se observaron con cuerpos "
                                    f"mayores que {limit} bytes")
                else:
                    item["requirements"] = sorted(sizes)
        elif value is not None:
            item.update(status="rejected", why="esta mejora no admite parámetro")
        elif ident == "compatibilidad-utf8":
            affected = sorted(c["requirement"] for c in cases if c.get("status") != "pendiente" and not (
                (c.get("stdout") or "").isascii() and (c.get("stderr") or "").isascii()))
            if affected:
                item["requirements"] = affected
            else:
                item.update(status="rejected",
                            why="ninguna salida observada tiene caracteres fuera de ASCII: la razón no se puede "
                                "comprobar con esta especificación")
        out.append(item)
    return out


def config(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Configuración que lee la base generada (``mejoras.json``): solo las aplicadas."""
    cfg: dict[str, Any] = {}
    for it in items:
        if it["status"] != "applied":
            continue
        if it["id"] == "seguridad-nosniff":
            cfg["nosniff"] = True
        elif it["id"] == "seguridad-limite-cuerpo":
            cfg["max_body"] = it["params"]["bytes"]
        elif it["id"] == "compatibilidad-utf8":
            cfg["utf8"] = True
    return cfg
