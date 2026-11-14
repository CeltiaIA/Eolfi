r"""Conjunto de datos para entrenar modelos (LLM) a partir del corpus de Alejandría (14/11/2026, titular).

    python -m eolfi dataset [--library D:\Alejandria] [--dry-run]

Lee SOLO lo que el índice de Alejandría ya aceptó (sintaxis validada, sin secretos, una copia por contenido) y lo
escribe en <biblioteca>/datasets/llm-eolfi/ en los formatos habituales de entrenamiento:

- sft-chat.jsonl         {"messages": [{"role": "user", …}, {"role": "assistant", …}], "metadata": {…}}
                         Respuestas de los motores que PASARON su verificación (pruebas ejecutadas en el
                         contenedor o salida esperada), sacadas del corpus de entrenamiento de las rondas.
- pretrain-codigo.jsonl  {"text": "…", "metadata": {…}}  código del corpus.
- pretrain-texto.jsonl   {"text": "…", "metadata": {…}}  documentación .md/.txt.
- manifest.json          recuentos, exclusiones por motivo y SHA-256 de cada archivo.
- README.md              ficha del conjunto (formato, verificación, privacidad, límites).

Verificación de cada entrada (lo que no la pasa queda fuera y se cuenta en el manifiesto por motivo):
- integridad: el contenido coincide con el SHA-256 normalizado que guarda el índice;
- formato: UTF-8 válido, ni vacío ni demasiado corto, ni mayor que MAX_BYTES;
- procedencia: fuera temporales y salidas de pruebas (.codex-tmp, .pytest-tmp*, pytest-of-*), proyectos
  generados y cachés: entre ellos hay cargas HOSTILES de las pruebas de seguridad (evil.bat…);
- duplicados: además de los idénticos (ya fuera en el índice), los que solo difieren en espacios o mayúsculas;
- privacidad: redactado de Eolfi (correos, teléfonos, tarjetas, IBAN, DNI…) y rutas de usuario
  (C:\Users\<nombre>, /home/<nombre>) cambiadas por <usuario>; sin el nombre de la máquina.

La salida se escribe en una carpeta temporal y se cambia de golpe: nunca queda un conjunto a medias.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "eolfi.dataset-llm/1"
OUT_DIR = Path("datasets") / "llm-eolfi"
MAX_BYTES = 200_000            # un archivo mayor no es una muestra útil (y suele ser datos generados)
MIN_CHARS = 40                 # sin espacios: por debajo no enseña nada
TRAINING_SCHEMA = "eolfi.ejemplo-entrenamiento/1"
# Partes de ruta que delatan temporales, salidas de pruebas o artefactos generados.
_JUNK = re.compile(r"(^|[\\/])(\.codex-tmp|\.pytest-tmp[^\\/]*|pytest-of-[^\\/]*|pytest-\d+|generated|"
                   r"__pycache__|node_modules|\.cache|dist|build|_?backups?[^\\/]*)([\\/]|$)", re.IGNORECASE)
_USER_PATH = re.compile(r"(?i)(?<![\w])([A-Z]:[\\/]+Users[\\/]+|/home/|/Users/)([^\\/\s\"'<>|:*?]+)")


def _local_accounts() -> list[str]:
    """La cuenta de este equipo (USERNAME/USER) aparece también fuera de las rutas: «pytest-of-<cuenta>»,
    «EQUIPO\\<cuenta>». Se oculta como palabra completa. El nombre del equipo NO, porque aquí coincide con la marca."""
    import getpass

    names = {os.environ.get("USERNAME") or "", os.environ.get("USER") or ""}
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001 — sin cuenta conocida no hay nada que ocultar
        pass
    return sorted(n for n in names if len(n) >= 3)


def _normalized_sha(text: str) -> str:
    """El mismo SHA-256 que Alejandría: CRLF→LF y sin espacios al final de cada línea."""
    norm = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _loose_key(text: str) -> str:
    """Clave de casi-duplicado: sin espacios de ningún tipo y en minúsculas."""
    return hashlib.sha256(re.sub(r"\s+", "", text).lower().encode("utf-8")).hexdigest()


def clean_text(text: str) -> tuple[str, bool]:
    """Redactado de privacidad de Eolfi y rutas de usuario → <usuario>. Devuelve (texto, ¿cambió?)."""
    from eolfi.security.privacy import redact

    out, _counts = redact(text)
    out = _USER_PATH.sub(lambda m: m.group(1) + "<usuario>", out)
    for name in _local_accounts():
        out = re.sub(r"(?i)(?<![\w])" + re.escape(name) + r"(?![\w])", "<usuario>", out)
    return out, out != text


def _clean_obj(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(value)[0]
    if isinstance(value, list):
        return [_clean_obj(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean_obj(v) for k, v in value.items()}
    return value


def _answer_json(text: str) -> dict[str, Any] | None:
    m = re.fullmatch(r"\s*(?:```(?:json)?\s*)?(\{.*\})(?:\s*```)?\s*", text, re.DOTALL | re.IGNORECASE)
    try:
        data = json.loads(m.group(1)) if m else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# Tareas que la ronda corrige con una regla propia: se vuelve a comprobar aquí sobre la respuesta guardada.
_RULES = {
    "buscar_definicion": lambda answer: str((_answer_json(answer) or {}).get("ruta") or "")
    .replace("\\", "/").endswith("eolfi/library.py"),
}


def _verified(r: dict[str, Any]) -> str | None:
    """Cómo se verificó el ejemplo, o None si no hay prueba de que la respuesta sea buena."""
    verif = r.get("verificacion") or {}
    if "EOLFI-OK" in str(verif.get("salida") or ""):
        return "pruebas ejecutadas"
    if verif.get("esperado") is not None:
        return "salida esperada"
    rule = _RULES.get(str(r.get("caso")))
    answer = str(((r.get("mensajes") or [{}, {}])[-1] or {}).get("content") or "")
    if rule is not None and rule(answer):
        return "regla de la tarea"
    return None


def _sft_examples(path: Path, why: Counter) -> list[dict[str, Any]]:
    """Ejemplos de entrenamiento verificados → formato de chat. Lo demás (exámenes con fallos…) no es SFT."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            why["sft: línea no es JSON"] += 1
            continue
        if not isinstance(r, dict) or r.get("esquema") != TRAINING_SCHEMA:
            why["sft: no es un ejemplo de entrenamiento"] += 1
            continue
        msgs = r.get("mensajes") or []
        ok_roles = [m.get("role") for m in msgs if isinstance(m, dict)] == ["user", "assistant"]
        if not ok_roles or not all(str(m.get("content") or "").strip() for m in msgs):
            why["sft: mensajes incompletos"] += 1
            continue
        how = _verified(r)
        if how is None:
            why["sft: sin verificación superada"] += 1
            continue
        out.append({
            "messages": [{"role": m["role"], "content": clean_text(str(m["content"]))[0]} for m in msgs],
            "metadata": {"fuente": "eolfi-ronda-motores", "tipo": r.get("tipo"), "caso": r.get("caso"),
                         "version_caso": r.get("version_caso"), "calidad": r.get("calidad"),
                         "herramientas": r.get("herramientas_usadas") or [],
                         "verificacion": how,
                         "motor": {k: (r.get("motor") or {}).get(k) for k in ("perfil", "gguf", "cuantizacion")},
                         "id_origen": r.get("id")},
        })
    return out


def build(library: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    lib = Path(library)
    index_path = lib / "manifests" / "corpus.index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"No existe el índice de Alejandría: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    entries = [e for e in index.get("entries") or [] if isinstance(e, dict)]
    why: Counter = Counter()
    seen_loose: set[str] = set()
    sft: list[dict[str, Any]] = []
    sft_seen: set[str] = set()
    code: list[dict[str, Any]] = []
    text: list[dict[str, Any]] = []
    redacted = 0

    for e in sorted(entries, key=lambda x: str(x.get("path") or "")):
        rel = str(e.get("path") or "")
        kind = e.get("tipo")
        if _JUNK.search(rel):
            why["temporal, prueba, copia de seguridad o generado"] += 1
            continue
        f = lib / rel
        if not f.is_file():
            why["falta en disco"] += 1
            continue
        size = f.stat().st_size
        if size > MAX_BYTES:
            why[f"mayor de {MAX_BYTES} bytes"] += 1
            continue
        try:
            content = f.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            why["no es UTF-8"] += 1
            continue
        if _normalized_sha(content) != e.get("sha256"):
            why["no coincide con el SHA-256 del índice"] += 1
            continue
        if kind == "datos":
            if "corpus-entrenamiento" not in rel.replace("\\", "/").split("/"):
                why["datos que no son ejemplos de entrenamiento (exámenes)"] += 1
                continue
            for ex in _sft_examples(f, why):
                key = _loose_key(json.dumps(ex["messages"], ensure_ascii=False))
                if key in sft_seen:
                    why["sft: duplicado"] += 1
                    continue
                sft_seen.add(key)
                sft.append(ex)
            continue
        if kind not in ("codigo", "texto"):
            why[f"tipo no usado ({kind})"] += 1
            continue
        if len(re.sub(r"\s+", "", content)) < MIN_CHARS:
            why[f"menos de {MIN_CHARS} caracteres"] += 1
            continue
        loose = _loose_key(content)
        if loose in seen_loose:
            why["casi duplicado (solo cambian espacios o mayúsculas)"] += 1
            continue
        seen_loose.add(loose)
        clean, changed = clean_text(content)
        redacted += changed
        parts = rel.replace("\\", "/").split("/")
        record = {"text": clean, "metadata": {
            "fuente": parts[2] if len(parts) > 2 else "", "ruta": "/".join(parts[3:]), "lenguaje": e.get("lenguaje"),
            "sha256": e.get("sha256"), "bytes": size, "redactado": changed,
            "validacion": "sintaxis validada por Alejandría" if kind == "codigo" else "texto"}}
        (code if kind == "codigo" else text).append(record)

    files = {"sft-chat.jsonl": sft, "pretrain-codigo.jsonl": code, "pretrain-texto.jsonl": text}
    manifest: dict[str, Any] = {
        "esquema": SCHEMA, "generado": datetime.now(timezone.utc).isoformat(),
        "indice": {"ruta": str(index_path.relative_to(lib)), "entradas": len(entries),
                   "generado": index.get("generated_utc")},
        "archivos": {name: {"registros": len(rows)} for name, rows in files.items()},
        "excluidos": dict(sorted(why.items(), key=lambda kv: (-kv[1], kv[0]))),
        "redactados": redacted,
        "limites": {"max_bytes": MAX_BYTES, "min_caracteres": MIN_CHARS},
    }
    if dry_run:
        return {**manifest, "salida": None}

    out = lib / OUT_DIR
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".llm-eolfi-", dir=out.parent))
    try:
        for name, rows in files.items():
            data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
            (tmp / name).write_bytes(data)
            manifest["archivos"][name]["sha256"] = hashlib.sha256(data).hexdigest()
            manifest["archivos"][name]["bytes"] = len(data)
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (tmp / "README.md").write_text(_card(manifest), encoding="utf-8")
        old = out.with_name(out.name + ".anterior")
        if old.exists():
            shutil.rmtree(old)
        if out.exists():
            os.replace(out, old)
        os.replace(tmp, out)
        if old.exists():
            shutil.rmtree(old)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {**manifest, "salida": str(out)}


def _card(m: dict[str, Any]) -> str:
    rows = "\n".join(f"| `{n}` | {a['registros']} | {a.get('bytes', 0)} | `{a.get('sha256', '')[:16]}…` |"
                     for n, a in m["archivos"].items())
    excl = "\n".join(f"| {k} | {v} |" for k, v in m["excluidos"].items()) or "| — | 0 |"
    return f"""# Conjunto de datos LLM de Eolfi (Alejandría)

Generado el {m['generado']} con `python -m eolfi dataset` a partir de `{m['indice']['ruta']}`
({m['indice']['entradas']} entradas). Esquema `{m['esquema']}`.

| Archivo | Registros | Bytes | SHA-256 |
|---|---|---|---|
{rows}

## Formatos

- `sft-chat.jsonl`: ajuste fino supervisado en formato de chat (`messages` con `user` y `assistant`), el que
  aceptan las herramientas habituales de entrenamiento. Solo respuestas de motores **verificadas**: pasaron
  sus pruebas ejecutadas en un contenedor aislado (o dieron la salida esperada).
- `pretrain-codigo.jsonl` y `pretrain-texto.jsonl`: preentrenamiento o continuación (`text`), con `metadata`
  (fuente, ruta, lenguaje, SHA-256, bytes, si se redactó).

## Verificación y exclusiones

Cada entrada coincide con el SHA-256 del índice, es UTF-8, tiene entre {m['limites']['min_caracteres']} caracteres y
{m['limites']['max_bytes']} bytes, no viene de temporales, pruebas, copias de seguridad ni proyectos generados, y no es un duplicado ni
un casi-duplicado (mismo contenido salvo espacios o mayúsculas). El código ya pasó la validación de sintaxis y el
detector de secretos de Alejandría.

| Motivo de exclusión | Entradas |
|---|---|
{excl}

## Privacidad

Redactado de Eolfi (correos, teléfonos, tarjetas, IBAN, DNI…) y rutas de usuario sustituidas por `<usuario>`:
{m['redactados']} entradas modificadas. No se incluye el nombre de la máquina.

## Límites

- La calidad del código es la de su fuente: está validado en sintaxis, no probado uno a uno (salvo en SFT).
- Revisa la licencia de cada fuente antes de publicar o compartir un modelo entrenado con este conjunto.
"""
