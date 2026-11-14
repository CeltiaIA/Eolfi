"""Crear un proyecto NUEVO a partir de una o varias apps, webs, repos o carpetas.

1. Cada fuente se analiza (o se reutiliza si ya está en la base).
2. Los análisis se fusionan en una especificación (eolfi.generador.spec).
3. Se genera código nuevo desde plantillas propias (eolfi.generador.generators).
4. Se instala, se fijan versiones, se compila y se prueba antes de considerar terminado el proyecto.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita
from eolfi.flows.triage_flow import environment_string

MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
             "build.gradle", "build.gradle.kts", "composer.json", "Gemfile", "pubspec.yaml", "setup.py")
GIT_HOSTS = ("github.com/", "gitlab.com/", "bitbucket.org/", "codeberg.org/", "git.sr.ht/")


def classify(source: str) -> str:
    """web | repo | binary | subject"""
    s = source.strip()
    if s.startswith(("http://", "https://")):
        import urllib.parse

        u = urllib.parse.urlsplit(s)
        host_path = f"{(u.hostname or '').lower()}{u.path}"   # sin la query: «?r=github.com/x» no es un repo
        if u.path.endswith(".git") or any(host_path.startswith(h) or host_path.startswith("www." + h) for h in GIT_HOSTS):
            return "repo"
        return "web"
    if s.startswith(("git@", "ssh://")):
        return "repo"
    p = Path(s)
    if p.is_dir():
        if any((p / m).exists() for m in MANIFESTS) or any(p.glob("*.csproj")) or (p / ".git").exists():
            return "repo"
        if any(p.glob("*.html")):
            return "web"
        return "repo"
    if p.is_file():
        return "web" if p.suffix.lower() in (".html", ".htm") else "binary"
    return "subject"


def resolve_subject(store: EvidenceStore, ref: str) -> str | None:
    """Objetivo ya analizado: exacto, por prefijo o, si es único, por nombre (sin mayúsculas)."""
    esc = re.sub(r"([%_\\])", r"\\\1", ref)
    rows = store.conn.execute(
        "SELECT DISTINCT subject FROM evidence WHERE subject = ? OR subject LIKE ? ESCAPE '\\' LIMIT 2",
        (ref, esc + "%")).fetchall()
    exact = [r[0] for r in rows if r[0] == ref]
    if exact:
        return exact[0]
    # Una ruta local ya analizada (repo:C:\x o local:C:\x) se reutiliza en vez de analizarla otra vez (B24).
    if re.match(r"^(?:[a-zA-Z]:[\\/]|/|\.{1,2}[\\/])", ref) or "\\" in ref or "/" in ref:
        try:
            full = str(Path(ref).expanduser().resolve())
        except (OSError, ValueError):
            full = ref
        for kind in ("repo", "local"):
            hit = store.conn.execute("SELECT 1 FROM evidence WHERE subject = ? LIMIT 1", (f"{kind}:{full}",)).fetchone()
            if hit:
                return f"{kind}:{full}"
    if len(rows) == 1:
        return rows[0][0]
    # Por nombre: 'Alejandria' encuentra 'repo:C:\Alejandria' (si solo hay uno).
    rows = store.conn.execute(
        "SELECT DISTINCT subject FROM evidence WHERE lower(subject) LIKE ? ESCAPE '\\' "
        "AND subject NOT LIKE 'proyecto:%' AND subject NOT LIKE 'forge:%' AND subject NOT LIKE 'compare:%' LIMIT 50", ("%" + esc.lower(),)).fetchall()
    named = [r[0] for r in rows if re.split(r"[\\/:]", r[0].rstrip("\\/"))[-1].lower() == ref.lower()]
    return named[0] if len(set(named)) == 1 else None


def _local_drive(letter: str) -> bool:
    """Solo discos locales: comprobar una unidad de red caída puede bloquear decenas de segundos (B24)."""
    try:
        import ctypes

        kind = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\")
    except (AttributeError, OSError):
        return True
    return kind in (2, 3)   # DRIVE_REMOVABLE, DRIVE_FIXED (4 = red, 5 = CD, 1 = no existe)


def guess_folder(ref: str) -> Path | None:
    """Un nombre suelto ('Alejandria') que coincide con una única carpeta en la raíz de las unidades o en el inicio."""
    if not re.fullmatch(r"[\w .-]+", ref) or ref.strip(". ") == "":
        return None
    roots = [Path.home(), Path.home() / "Desktop", Path.home() / "Documents"]
    roots += [Path(f"{d}:/") for d in "CDEF" if _local_drive(d)] if os.name == "nt" else [Path("/")]
    hits = {(r / ref).resolve() for r in roots if (r / ref).is_dir()}
    return hits.pop() if len(hits) == 1 else None


class OverwriteSourceError(ValueError):
    """La salida coincide con una fuente: hace falta confirmación explícita (force)."""


BACKUP_SKIP = ("node_modules", ".venv", "venv", "__pycache__", "dist", ".next", ".expo")


def backup_folder(folder: Path) -> Path:
    """Copia completa (sin dependencias instaladas ni artefactos) junto a la carpeta: <nombre>.eolfi-backup-<fecha>."""
    import shutil
    from datetime import datetime

    folder = folder.resolve()
    if folder == Path(folder.anchor) or folder == Path.home().resolve():
        raise ValueError(f"No se escribe sobre {folder}: elige una carpeta de proyecto, no una unidad ni tu carpeta personal")
    dst = folder.with_name(f"{folder.name}.eolfi-backup-{datetime.now():%Y%m%d-%H%M%S}")
    # symlinks=True: se copian los enlaces como enlaces, sin seguirlos fuera de la carpeta.
    shutil.copytree(folder, dst, ignore=shutil.ignore_patterns(*BACKUP_SKIP), symlinks=True)
    return dst


def create_project(sources: list[str], store: EvidenceStore, out: str | Path, *, name: str = "nuevo-proyecto",
                   target: str = "auto", do_verify: bool = True, force: bool = False,
                   reanalyze: bool = False, workdir: str = "samples/repos", ai_brief: str | None = None,
                   ai_client=None, ai_provider: str = "eolas-v2", ai_model: str | None = None,
                   ai_base_url: str | None = None, db: str = "memory", auth: bool = False,
                   progress: Callable[[str], None] | None = None, case_id: str | None = None,
                   provenance: str = "") -> dict[str, Any]:
    """case_id: cada fuente analizada queda en el caso (con su propio registro «analysis») y la reconstrucción
    se registra como «reconstruction», con la verificación y sus pasos. Sin verificación verde: «partial»."""
    from eolfi.core.cases import case_run

    params = {"sources": sources, "out": str(out), "name": name, "target": target, "do_verify": do_verify,
              "force": force, "reanalyze": reanalyze, "db": db, "auth": auth, "ai": bool(ai_brief),
              "ai_provider": ai_provider if ai_brief else None}
    with case_run(store, case_id, "create", params,
                  provenance or "fuentes indicadas por el operador para una reconstrucción") as run:
        rep = _create_project(sources, store, out, name=name, target=target, do_verify=do_verify, force=force,
                              reanalyze=reanalyze, workdir=workdir, ai_brief=ai_brief, ai_client=ai_client,
                              ai_provider=ai_provider, ai_model=ai_model, ai_base_url=ai_base_url, db=db,
                              auth=auth, progress=progress, case_id=case_id)
        if run.active:
            for src in rep["sources"]:
                run.associate(src["subject"])
            run.associate(rep["subject"], path=rep["out"])
            ver = rep.get("verification")
            errors = []
            if ver is None:
                errors.append("proyecto no verificado")
            elif not ver["ok"]:
                failed = [s["step"] for s in ver["steps"] if s["exit"] != 0]
                errors.append(f"verificación fallida: {', '.join(failed) or ver.get('error', '?')}")
            if rep.get("assist") and not rep["assist"].get("ok"):
                errors.append("la IA no consiguió un estado verde")
            run.finish(status="done" if not errors else "partial", errors=errors,
                       evidence_ids=[x for x in (rep["evidence_id"], rep.get("verification_evidence_id")) if x],
                       result={"out": rep["out"], "target": rep["target"], "files": rep["files"],
                               "sources": rep["sources"], "verification": ver})
            rep["case_record"] = run.record_id
        return rep


def _create_project(sources: list[str], store: EvidenceStore, out: str | Path, *, name: str, target: str,
                    do_verify: bool, force: bool, reanalyze: bool, workdir: str, ai_brief: str | None,
                    ai_client, ai_provider: str, ai_model: str | None, ai_base_url: str | None, db: str,
                    auth: bool, progress: Callable[[str], None] | None, case_id: str | None) -> dict[str, Any]:
    from eolfi.generador.generators import generate
    from eolfi.generador.spec import build_spec

    log = progress or (lambda _m: None)
    if not sources:
        raise ValueError("indica al menos una fuente (--from)")
    subjects: list[str] = []
    analyzed: list[dict[str, str]] = []
    for src in sources:
        kind = classify(src)
        existing = resolve_subject(store, src) if kind == "subject" or not reanalyze else None
        if kind == "subject" and not existing and (folder := guess_folder(src)):
            log(f"'{src}' se interpreta como la carpeta {folder}")
            src, kind = str(folder), classify(str(folder))
            existing = None if reanalyze else resolve_subject(store, src)
        if kind == "subject":
            if not existing:
                raise ValueError(f"'{src}' no es una URL, una ruta existente ni un objetivo ya analizado. "
                                 f"Escribe la ruta completa (p. ej. C:\\{src}) o analízala antes en «Analizar».")
            subjects.append(existing)
            analyzed.append({"source": src, "kind": "existente", "subject": existing})
            continue
        log(f"analizando {src} como {kind}…")
        if kind == "web":
            from eolfi.flows.learn_flow import run_web
            rep = run_web(src, store, progress=log, case_id=case_id)
        elif kind == "repo":
            from eolfi.flows.learn_flow import run_repo
            rep = run_repo(src, store, workdir=workdir, progress=log, case_id=case_id)
        else:
            from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
            rep = run_triage(src, store, LOCAL_PROVIDERS, case_id=case_id)
        subjects.append(rep["subject"])
        analyzed.append({"source": src, "kind": kind, "subject": rep["subject"]})

    out_path = Path(out).resolve()
    backup_path: Path | None = None
    overwrite = False
    for a in analyzed:
        # La fuente puede venir por nombre de un objetivo ya analizado («Alejandria» → repo:D:\Alejandria):
        # se comprueba la ruta real del objetivo, no solo el texto escrito (PLAN_MEJORAS A18).
        candidates = [Path(a["source"])]
        subj = str(a.get("subject") or "")
        for prefix in ("repo:", "local:"):
            if subj.startswith(prefix):
                candidates.append(Path(subj[len(prefix):]))
        sp = next((c for c in candidates if c.exists()), candidates[0])
        if sp.exists():
            sp = sp.resolve()
            if out_path == sp or sp in out_path.parents or out_path in sp.parents:
                # Escribir sobre el origen está permitido, pero solo si se pide explícitamente
                # (force / confirmación en el panel) y siempre con copia de seguridad previa.
                if not force:
                    raise OverwriteSourceError(
                        f"Confirmación necesaria: la carpeta destino {out_path} es (o contiene) la fuente {sp}. "
                        f"Se sobrescribirá tras hacer una copia de seguridad completa.")
                if backup_path is None and out_path.exists() and any(out_path.iterdir()):
                    backup_path = backup_folder(out_path)
                    log(f"copia de seguridad de {out_path} en {backup_path}")
                # La carpeta conserva conftest.py, tests, .npmrc o node_modules del original:
                # verificar ahí ejecutaría código ajeno al proyecto generado (PLAN_CORRECCIONES A4).
                # Por eso, en este caso, se genera y verifica en una carpeta limpia y luego se copia.
                overwrite = True
    # Cualquier escritura forzada sobre una carpeta con contenido (sea o no la fuente): copia de seguridad
    # y verificación en carpeta limpia, para no ejecutar conftest.py, .npmrc o node_modules ajenos.
    if force and not overwrite and out_path.exists() and any(out_path.iterdir()):
        backup_path = backup_folder(out_path)
        log(f"copia de seguridad de {out_path} en {backup_path}")
        overwrite = True
    if re.search(r"[\\/]", name) or re.match(r"^[A-Za-z]:[\\/]", name):
        # Solo si parece una ruta («C:\x\y», «a/b»); «Tienda: precios» sigue siendo un título.
        name = re.split(r"[\\/]", name.rstrip("\\/"))[-1] or "nuevo-proyecto"
    spec = build_spec(store, subjects, name=name, target=target)
    if db not in ("memory", "sqlite"):
        raise ValueError("db debe ser memory o sqlite")
    spec["options"] = {"db": db, "auth": bool(auth)}
    if (db == "sqlite" and spec["target"] not in ("fastapi", "express")) or (
            auth and spec["target"] not in ("fastapi", "express", "next")):
        spec["notes"].append(f"--db solo afecta a FastAPI y Express y --auth a FastAPI, Express y Next.js; "
                             f"'{spec['target']}' no los usa (Django ya trae SQLite y su propia autenticación).")
    log(f"especificación: destino {spec['target']}, secciones {spec['sections']}, páginas {spec['pages']}")
    ver = None
    if overwrite and do_verify:
        import shutil
        import tempfile

        from eolfi.generador.verify import verify

        clean = Path(tempfile.mkdtemp(prefix="eolfi-limpio-"))
        try:
            files = generate(spec, clean)
            log(f"verificando en una carpeta limpia ({clean}) antes de escribir sobre el origen…")
            ver = verify(clean, spec["target"], progress=log)
            # Lo verificado (con versiones ya fijadas y lockfiles) es lo que se copia al origen.
            extra = [f for f in ("package-lock.json", "src-tauri/Cargo.lock") if (clean / f).is_file()]
            for rel in dict.fromkeys(files + extra):
                dst = out_path / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(clean / rel, dst)
            files = list(dict.fromkeys(files + extra))
        finally:
            shutil.rmtree(clean, ignore_errors=True)
        log(f"{len(files)} archivos verificados y copiados a {out_path}")
    else:
        files = generate(spec, out_path, force=force)
        log(f"{len(files)} archivos generados en {out_path}")
    subject = f"proyecto:{out_path}"
    env = environment_string()
    eid, _ = store.add_evidence(Evidence(
        subject=subject, provider="eolfi.generador", provider_version="0.1.0", operation="project_generated",
        params={"sources": subjects, "target": target, "name": name},
        result={"spec": spec, "files": files}, authority=Authority.ANALYST_INFERENCE,
        confidence=Confidence.HIGH, environment=env,
        limitations="Proyecto nuevo desde plantillas de Eolfi; los textos son de ejemplo."))
    result: dict[str, Any] = {"subject": subject, "out": str(out_path), "target": spec["target"],
                              "sources": analyzed, "files": len(files), "spec": spec, "evidence_id": eid}
    if backup_path:
        result["backup"] = str(backup_path)
    if do_verify:
        if ver is None:
            from eolfi.generador.verify import verify
            ver = verify(out_path, spec["target"], progress=log)
        result["verification_evidence_id"], _ = store.add_evidence(Evidence(
            subject=subject, provider="eolfi.generador", provider_version="0.1.0", operation="project_verification",
            params={"target": spec["target"]}, result=ver, authority=Authority.CONTROLLED_REPRO,
            confidence=Confidence.HIGH, environment=env,
            limitations="Instalación, compilación y pruebas del proyecto generado en esta máquina."))
        if not ver["ok"]:
            failed = next((s for s in ver.get("steps", []) if s["exit"] != 0), None)
            store.add_incognita(Incognita(subject=subject, severity="high", question=(
                f"La verificación falló en '{failed['step'] if failed else ver.get('error')}'; "
                f"revisa la salida antes de usar el proyecto.")))
        result["verification"] = {"ok": ver["ok"], "pinned": ver.get("pinned"),
                                  "steps": [{k: s[k] for k in ("step", "exit", "seconds")} |
                                            ({"tail": s["tail"][-1200:]} if s["exit"] != 0 else {})
                                            for s in ver.get("steps", [])],
                                  **({"error": ver["error"]} if "error" in ver else {})}
    if ai_brief:
        result["assist"] = run_assist(store, out_path, ai_brief, client=ai_client, provider=ai_provider,
                                      model=ai_model, base_url=ai_base_url, progress=log)
    return result


def run_assist(store: EvidenceStore, project: str | Path, brief: str, *, client=None, provider: str = "eolas-v2",
               model: str | None = None, base_url: str | None = None,
               progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Pide a Claude la lógica de negocio sobre un proyecto generado y lo registra como evidencia."""
    from eolfi.generador.assist import assist

    root = Path(project).resolve()
    rep = assist(root, brief, client=client, provider=provider, model=model, base_url=base_url, progress=progress)
    subject = f"proyecto:{root}"
    store.add_evidence(Evidence(
        subject=subject, provider="eolfi.assist", provider_version="0.1.0", operation="project_assist",
        params={"brief": brief[:2000], "provider": rep["provider"], "model": rep["model"]}, result=rep,
        authority=Authority.ANALYST_INFERENCE, confidence=Confidence.MEDIUM if rep["ok"] else Confidence.LOW,
        environment=environment_string(),
        limitations="Código escrito por un modelo y validado solo por la compilación y las pruebas del proyecto; revísalo."))
    if not rep["ok"]:
        store.add_incognita(Incognita(subject=subject, severity="medium", question=(
            "La IA no consiguió un estado verde; los cambios se deshicieron. Prueba con una petición más concreta.")))
    return rep
