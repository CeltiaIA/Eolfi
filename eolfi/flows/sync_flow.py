"""``eolfi sync`` (D1, 18/11/2026): volver a analizar las fuentes de un proyecto y proponer los cambios con fusión a
tres bandas.

Las tres versiones de cada archivo:

- **base**: lo que Eolfi generó entonces. Se regenera desde ``eolfi.spec.json`` (la generación es determinista: la
  misma especificación da los mismos archivos).
- **fuente**: lo que Eolfi generaría hoy tras volver a analizar las fuentes (misma tecnología, nombre, idioma y
  opciones).
- **tuyo**: lo que hay ahora en la carpeta del proyecto, con tus cambios y los de la IA.

Por archivo: si la fuente no lo cambia, se queda como está; si tú no lo tocaste, se toma el de la fuente; si cambiaron
los dos, se fusionan las líneas y, donde chocan, quedan marcas de conflicto (``<<<<<<< tuyo`` / ``>>>>>>> fuente``).
Los archivos que no son de la plantilla (los tuyos, lockfiles, criterios del juez) no se tocan nunca.

Por defecto solo propone (diff y resumen). Con ``aplicar`` escribe los cambios en la carpeta, guarda antes una copia
de cada archivo que toca en ``.eolfi-sync/<fecha>/`` y verifica el resultado en una carpeta limpia (un proyecto con
conflictos sin resolver no se verifica: queda NO VERIFICADO).
"""
from __future__ import annotations

import difflib
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence
from eolfi.flows.triage_flow import environment_string

CARPETA_COPIAS = ".eolfi-sync"
MAX_DIFF = 6000   # caracteres de diff por archivo en el informe


# ── Fusión a tres bandas por líneas ─────────────────────────────────────────────────────────────────────────────
def _trozos(base: list[str], otro: list[str]) -> list[tuple[int, int, int, int]]:
    ops = difflib.SequenceMatcher(None, base, otro, autojunk=False).get_opcodes()
    return [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in ops if tag != "equal"]


def _aplicar(trozos: list[tuple[int, int, int, int]], lo: int, hi: int, base: list[str], otro: list[str]) -> list[str]:
    out, pos = [], lo
    for i1, i2, j1, j2 in trozos:
        out += base[pos:i1] + otro[j1:j2]
        pos = i2
    return out + base[pos:hi]


def fusionar3(base: str, tuyo: str, fuente: str) -> tuple[str, int]:
    """Fusiona por líneas los cambios de ``tuyo`` y de ``fuente`` respecto a ``base``. Devuelve el texto y el número de
    conflictos (zonas que cambiaron los dos de forma distinta, marcadas como en git)."""
    b, t, f = base.splitlines(keepends=True), tuyo.splitlines(keepends=True), fuente.splitlines(keepends=True)
    hunks = sorted([(h, "t") for h in _trozos(b, t)] + [(h, "f") for h in _trozos(b, f)], key=lambda x: (x[0][0], x[0][1]))
    out: list[str] = []
    conflictos, pos, k = 0, 0, 0
    while k < len(hunks):
        lo, hi = hunks[k][0][0], hunks[k][0][1]
        grupo = [hunks[k]]
        k += 1
        # Se juntan los trozos que se solapan o que insertan en el mismo punto.
        while k < len(hunks):
            (i1, i2, _, _), _lado = hunks[k]
            if i1 < hi or (i1 == hi and (i1 == i2 or lo == hi)):
                grupo.append(hunks[k])
                hi = max(hi, i2)
                k += 1
            else:
                break
        out += b[pos:lo]
        de_t = [h for h, lado in grupo if lado == "t"]
        de_f = [h for h, lado in grupo if lado == "f"]
        vt = _aplicar(de_t, lo, hi, b, t)
        vf = _aplicar(de_f, lo, hi, b, f)
        if not de_t or vt == vf:
            out += vf
        elif not de_f:
            out += vt
        else:
            conflictos += 1
            fin = lambda lineas: lineas if not lineas or lineas[-1].endswith("\n") else [*lineas[:-1], lineas[-1] + "\n"]
            out += ["<<<<<<< tuyo\n", *fin(vt), "=======\n", *fin(vf), ">>>>>>> fuente\n"]
        pos = hi
    out += b[pos:]
    return "".join(out), conflictos


# ── Las tres versiones del proyecto ─────────────────────────────────────────────────────────────────────────────
def _fuente_de(subject: str) -> str | None:
    """De un objetivo analizado a la fuente que se vuelve a analizar (ruta o URL). None si no se puede."""
    for prefijo in ("local:", "repo:"):
        if subject.startswith(prefijo):
            return subject[len(prefijo):]
    if subject.startswith(("http://", "https://", "git@", "ssh://")):
        return subject
    return None


def _leer(p: Path) -> bytes | None:
    return p.read_bytes() if p.is_file() else None


def _generar(spec: dict[str, Any], destino: Path) -> dict[str, bytes]:
    from eolfi.generador.generators import generate

    archivos = generate(spec, destino)
    return {rel.replace("\\", "/"): (destino / rel).read_bytes() for rel in dict.fromkeys(archivos)}


def _resumen_spec(antes: dict[str, Any], despues: dict[str, Any]) -> dict[str, Any]:
    cambios: dict[str, Any] = {}
    for clave in ("pages", "sections"):
        a, d = antes.get(clave) or [], despues.get(clave) or []
        if a != d:
            cambios[clave] = {"añadidas": [x for x in d if x not in a], "quitadas": [x for x in a if x not in d]}
    ra, rd = (antes.get("api") or {}).get("resources") or [], (despues.get("api") or {}).get("resources") or []
    if ra != rd:
        cambios["resources"] = {"añadidos": [x for x in rd if x not in ra], "quitados": [x for x in ra if x not in rd]}
    pa, pd = (antes.get("design") or {}).get("palette") or {}, (despues.get("design") or {}).get("palette") or {}
    if pa != pd:
        cambios["palette"] = {k: [pa.get(k), pd.get(k)] for k in sorted(set(pa) | set(pd)) if pa.get(k) != pd.get(k)}
    return cambios


def _diff(rel: str, antes: bytes | None, despues: bytes | None) -> str:
    try:
        a = (antes or b"").decode("utf-8").splitlines(keepends=True)
        d = (despues or b"").decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return f"(binario: {rel})"
    texto = "".join(difflib.unified_diff(a, d, f"a/{rel}", f"b/{rel}"))
    return texto if len(texto) <= MAX_DIFF else texto[:MAX_DIFF] + "\n… (diff recortado)\n"


def sync_project(store: EvidenceStore, project: str | Path, *, aplicar: bool = False, verificar: bool = True,
                 workdir: str = "repos", progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    from eolfi.flows.create_flow import classify
    from eolfi.generador.spec import build_spec

    log = progress or (lambda _m: None)
    carpeta = Path(project).resolve()
    spec_path = carpeta / "eolfi.spec.json"
    if not spec_path.is_file():
        raise ValueError(f"{carpeta} no tiene eolfi.spec.json: no es un proyecto creado con «eolfi create»")
    spec_base = json.loads(spec_path.read_text(encoding="utf-8"))

    # 1) Volver a analizar las fuentes (las que se puedan; un objetivo sin ruta ni URL se reutiliza tal cual).
    subjects: list[str] = []
    analizadas: list[dict[str, str]] = []
    for s in spec_base.get("sources") or []:
        subj = str(s.get("subject") or "")
        src = _fuente_de(subj)
        kind = classify(src) if src else "subject"
        if kind in ("web", "repo", "binary"):
            log(f"volviendo a analizar {src} como {kind}…")
            if kind == "web":
                from eolfi.flows.learn_flow import run_web
                rep = run_web(src, store, progress=log)
            elif kind == "repo":
                from eolfi.flows.learn_flow import run_repo
                rep = run_repo(src, store, workdir=workdir, progress=log)
            else:
                from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
                rep = run_triage(src, store, LOCAL_PROVIDERS)
            subjects.append(rep["subject"])
            analizadas.append({"source": src, "kind": kind, "subject": rep["subject"]})
        else:
            subjects.append(subj)
            analizadas.append({"source": subj, "kind": "sin_reanalizar", "subject": subj})
    if not subjects:
        raise ValueError("el proyecto no registra sus fuentes en eolfi.spec.json")

    # 2) La especificación nueva conserva la identidad y las decisiones del proyecto.
    spec_nueva = build_spec(store, subjects, name=spec_base.get("title") or spec_base.get("name") or "proyecto",
                            target=spec_base["target"])
    for clave in ("name", "title", "idioma", "options"):
        if clave in spec_base:
            spec_nueva[clave] = spec_base[clave]
    if "auth" in (spec_base.get("conventions") or {}):
        spec_nueva.setdefault("conventions", {})["auth"] = spec_base["conventions"]["auth"]

    tmp = Path(tempfile.mkdtemp(prefix="eolfi-sync-"))
    try:
        base = _generar(spec_base, tmp / "base")
        fuente = _generar(spec_nueva, tmp / "fuente")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 3) Fusión por archivo.
    cambios: list[dict[str, Any]] = []
    escribir: dict[str, bytes | None] = {}
    for rel in sorted(set(base) | set(fuente)):
        b, f, t = base.get(rel), fuente.get(rel), _leer(carpeta / rel)
        if f == b:
            continue                                   # la fuente no lo cambia: se queda como está
        if t == f:
            continue                                   # ya está como lo dejaría la fuente
        if t == b:
            accion = "nuevo" if b is None else ("borrado" if f is None else "actualizado")
            escribir[rel] = f
            cambios.append({"ruta": rel, "accion": accion, "diff": _diff(rel, t, f)})
            continue
        if t is None:
            cambios.append({"ruta": rel, "accion": "conflicto", "motivo": "lo borraste y la fuente lo cambia; "
                            "no se recupera", "diff": _diff(rel, b, f)})
            continue
        if f is None:
            cambios.append({"ruta": rel, "accion": "conflicto", "motivo": "la fuente ya no lo genera y lo "
                            "cambiaste tú; se conserva", "diff": ""})
            continue
        try:
            texto, n = fusionar3((b or b"").decode("utf-8"), t.decode("utf-8"), f.decode("utf-8"))
        except UnicodeDecodeError:
            cambios.append({"ruta": rel, "accion": "conflicto", "motivo": "binario cambiado por los dos; se conserva "
                            "el tuyo", "diff": ""})
            continue
        nuevo = texto.encode("utf-8")
        escribir[rel] = nuevo
        cambios.append({"ruta": rel, "accion": "conflicto" if n else "fusionado", "conflictos": n,
                        "diff": _diff(rel, t, nuevo)})

    resumen = {a: sum(1 for c in cambios if c["accion"] == a)
               for a in ("nuevo", "actualizado", "borrado", "fusionado", "conflicto")}
    result: dict[str, Any] = {
        "project": str(carpeta), "target": spec_base["target"], "sources": analizadas,
        "spec_changes": _resumen_spec(spec_base, spec_nueva), "summary": resumen, "changes": cambios,
        "applied": False,
    }
    if not aplicar or not escribir:
        if not escribir:
            result["note"] = "sin cambios que aplicar: el proyecto ya está al día con sus fuentes"
        else:
            result["note"] = "propuesta: repite con --aplicar para escribirla (se guarda copia de lo que se toca)"
        return result

    # 4) Aplicar: copia de lo que se toca, escritura y verificación en una carpeta limpia.
    copia = carpeta / CARPETA_COPIAS / time.strftime("%Y%m%d-%H%M%S")
    for rel, contenido in escribir.items():
        destino = carpeta / rel
        if destino.is_file():
            (copia / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destino, copia / rel)
        if contenido is None:
            destino.unlink(missing_ok=True)
        else:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(contenido)
    result.update(applied=True, backup=str(copia) if copia.exists() else None)
    log(f"{len(escribir)} archivos escritos; copia de los anteriores en {copia}")
    subject = f"proyecto:{carpeta}"
    store.add_evidence(Evidence(
        subject=subject, provider="eolfi.sync", provider_version="0.1.0", operation="project_synced",
        params={"sources": subjects, "target": spec_base["target"]},
        result={"summary": resumen, "files": sorted(escribir), "spec_changes": result["spec_changes"]},
        authority=Authority.ANALYST_INFERENCE, confidence=Confidence.HIGH, environment=environment_string(),
        limitations="Fusión a tres bandas automática; los conflictos marcados los resuelve una persona."))
    if resumen["conflicto"]:
        result["verification"] = {"ok": False, "error": "NO VERIFICADO: hay conflictos sin resolver; resuélvelos "
                                  "(busca «<<<<<<< tuyo») y verifica el proyecto"}
    elif verificar:
        from eolfi.generador.verify import verify

        limpia = Path(tempfile.mkdtemp(prefix="eolfi-sync-verifica-"))
        try:
            # Solo lo del proyecto, sin dependencias instaladas ni copias: la verificación instala lo suyo.
            shutil.copytree(carpeta, limpia / "p", ignore=shutil.ignore_patterns(
                CARPETA_COPIAS, "node_modules", ".venv", "target", "bin", "dist", ".next", "__pycache__"))
            ver = verify(limpia / "p", spec_base["target"], progress=log)
        finally:
            shutil.rmtree(limpia, ignore_errors=True)
        result["verification"] = {"ok": ver["ok"], "steps": [{k: s[k] for k in ("step", "exit", "seconds")}
                                                             for s in ver.get("steps", [])],
                                  **({"error": ver["error"]} if "error" in ver else {})}
    else:
        result["verification"] = {"ok": False, "error": "NO VERIFICADO: se pidió no verificar"}
    return result
