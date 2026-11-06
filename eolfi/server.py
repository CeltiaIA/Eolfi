"""Servidor de desarrollo de Eolfi: API JSON + panel web, solo stdlib.

    python -m eolfi serve                 # http://127.0.0.1:8777
    python -m eolfi serve --reload        # se reinicia al cambiar el código

Seguridad (el servidor maneja datos de binarios hostiles):
- Escucha en 127.0.0.1 por defecto; otra interfaz exige --allow-remote.
- Cabecera Host comprobada (frena DNS rebinding).
- Las peticiones que cambian estado exigen la cabecera X-Eolfi: 1. Una web
  ajena no puede enviarla sin preflight CORS, que este servidor no concede.
- CSP estricta y todo el texto se pinta con textContent: las cadenas del
  binario se muestran como dato, nunca como HTML.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Status

WEB_DIR = Path(__file__).with_name("web")
MAX_UPLOAD = 256 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024   # rutas JSON: nunca necesitan más
_STATIC = {"/": "index.html", "/app.js": "app.js", "/theme.js": "theme.js", "/style.css": "style.css",
           "/favicon.svg": "favicon.svg",
           "/favicon.ico": "favicon.svg"}
_CTYPE = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
# frame-ancestors: el panel solo se puede incrustar en VS Code (Simple Browser, esquema vscode-webview:).
# frame-src: el panel incrusta VS Code web (code serve-web), que escucha en 127.0.0.1 en un puerto libre.
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-src http://127.0.0.1:*; frame-ancestors 'self' vscode-webview:; "
        "base-uri 'none'; form-action 'none'")
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class JobCancelled(BaseException):
    """Se lanza en el hilo del trabajo (desde _progress) cuando el usuario lo cancela. BaseException para
    que los «except Exception» de los flujos no se la traguen."""


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        self.extra = extra   # campos adicionales de la respuesta (p. ej. needs_confirm)
        super().__init__(message)
        self.status = status


def _decode_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    for r in rows:
        for k in fields:
            if isinstance(r.get(k), str):
                try:
                    r[k] = json.loads(r[k])
                except json.JSONDecodeError:
                    pass
    return rows


class EolfiApp:
    """Lógica de la API, separada del transporte HTTP (fácil de probar)."""

    def __init__(self, db: str, samples_dir: str | Path = "samples", roots: list[str] | None = None):
        self.db = db
        self.samples = Path(samples_dir)
        # Carpetas permitidas para rutas locales (analizar, fuentes, destino, selector). Vacío = sin
        # restricción (uso local). Se configuran con `serve --root` o EOLFI_ROOTS (separadas por ;/:).
        env = [r for r in os.environ.get("EOLFI_ROOTS", "").split(os.pathsep) if r.strip()]
        self.roots = [Path(r).expanduser().resolve() for r in (roots if roots is not None else env)]
        self.lock = threading.Lock()   # operaciones cortas (resolver incógnitas)
        # Los análisis largos (Ghidra, descargas, clonados, verificación) ya no bloquean todo el
        # panel: corren en paralelo y SQLite (WAL + busy_timeout) ordena las escrituras. Solo se
        # serializan dos trabajos sobre la MISMA fuente/destino.
        self._jobs: dict[str, threading.Lock] = {}
        self._jobs_guard = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}   # trabajos en segundo plano (id -> estado)
        self._tl = threading.local()
        # Como mucho MAX_RUNNING trabajos a la vez; el resto espera «en cola» (PLAN_MEJORAS M2).
        self._slots = threading.BoundedSemaphore(self.MAX_RUNNING)
        self._providers_cache: tuple[float, dict[str, Any]] | None = None
        # Proveedores locales en subproceso (EOLFI_ISOLATE=0 lo desactiva, p. ej. para depurar).
        self.isolate = os.environ.get("EOLFI_ISOLATE", "1") != "0"
        from eolfi.vscode_web import VSCodeWeb

        self.vscode_web = VSCodeWeb()
        self._pair_codes: dict[str, float] = {}   # código de vinculación → caducidad

    def store(self) -> EvidenceStore:
        return EvidenceStore(self.db)

    # -- trabajos en segundo plano (análisis largos, crear y verificar) ---------------
    # POST /api/jobs {"kind": "create"|"web"|"repo"|"triage", "body": {...}} -> {"job_id"}
    # GET  /api/jobs?id=…&since=N -> {"status": running|done|error, "log": [...], "next": N, "result"|"error"}
    JOB_KINDS = ("create", "web", "repo", "triage")
    MAX_JOBS = 50
    MAX_RUNNING = 3

    def _progress(self, message: str) -> None:
        job = getattr(self._tl, "job", None)
        if job is not None:
            if job.get("cancel"):
                raise JobCancelled()   # cancelación cooperativa: en el siguiente aviso de progreso
            with self._jobs_guard:
                job["log"].append({"t": round(time.time() - job["started"], 1), "msg": str(message)[:500]})
                del job["log"][:-2000]

    def start_job(self, body: dict[str, Any]) -> dict[str, Any]:
        import secrets

        kind, payload = body.get("kind"), body.get("body") or {}
        if kind not in self.JOB_KINDS or not isinstance(payload, dict):
            raise ApiError(400, f"kind debe ser uno de {', '.join(self.JOB_KINDS)} y body un objeto")
        fn = {"create": self.create, "web": lambda b: self.learn("web", b),
              "repo": lambda b: self.learn("repo", b), "triage": self.triage_path}[kind]
        job = {"id": secrets.token_hex(8), "kind": kind, "status": "queued", "log": [], "started": time.time(),
               "label": str(payload.get("name") or payload.get("source") or payload.get("path")
                            or ", ".join(map(str, payload.get("sources") or [])))[:160],
               "body": payload}

        def run() -> None:
            self._tl.job = job
            acquired = False
            try:
                while not (acquired := self._slots.acquire(timeout=0.5)):
                    if job.get("cancel"):
                        raise JobCancelled()
                    if not job["log"]:
                        self._progress(f"en cola: ya hay {self.MAX_RUNNING} trabajos en marcha")
                job["status"] = "running"
                job["result"] = fn(payload)
                if isinstance(job["result"], dict) and isinstance(job["result"].get("subject"), str):
                    job["subject"] = job["result"]["subject"]
                job["status"] = "done"
            except JobCancelled:
                job.update(status="cancelled", error="Cancelado por el usuario", code=499)
            except ApiError as exc:
                job.update(status="error", error=str(exc), code=exc.status, **exc.extra)
            except Exception as exc:  # noqa: BLE001 — el error se informa en el propio trabajo
                job.update(status="error", error=f"{type(exc).__name__}: {exc}", code=500)
            finally:
                if acquired:
                    self._slots.release()
                job["finished"] = time.time()
                self._tl.job = None
                self._save_job(job)

        with self._jobs_guard:
            self.jobs[job["id"]] = job
            for old in list(self.jobs)[:-self.MAX_JOBS]:     # se conservan los últimos 50
                if self.jobs[old]["status"] not in ("running", "queued"):
                    del self.jobs[old]
        threading.Thread(target=run, name=f"job-{kind}", daemon=True).start()
        return {"job_id": job["id"], "kind": kind}

    # -- historial persistente (pestaña «Trabajos») ------------------------------
    _JOB_FIELDS = ("id", "kind", "status", "label", "started", "finished", "error", "subject")

    def _history(self):
        s = self.store()
        s.conn.execute("CREATE TABLE IF NOT EXISTS job_history (id TEXT PRIMARY KEY, kind TEXT, status TEXT, "
                       "label TEXT, started REAL, finished REAL, error TEXT, subject TEXT, body TEXT)")
        return s

    def _save_job(self, job: dict[str, Any]) -> None:
        """Al terminar, cada trabajo queda en eolfi.db (sobrevive a reinicios y a --reload)."""
        try:
            s = self._history()
            try:
                with s.conn:
                    s.conn.execute("INSERT OR REPLACE INTO job_history VALUES (?,?,?,?,?,?,?,?,?)", (
                        job["id"], job["kind"], job["status"], job.get("label"), job["started"], job.get("finished"),
                        (job.get("error") or "")[:2000] or None, job.get("subject"),
                        json.dumps(job.get("body") or {}, ensure_ascii=False)[:200_000]))
                    s.conn.execute("DELETE FROM job_history WHERE id NOT IN "
                                   "(SELECT id FROM job_history ORDER BY started DESC LIMIT 500)")
            finally:
                s.close()
        except Exception:  # noqa: BLE001 — el historial nunca tumba un trabajo
            traceback.print_exc()

    def _stored_job(self, job_id: str) -> dict[str, Any] | None:
        s = self._history()
        try:
            row = s.conn.execute("SELECT * FROM job_history WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            s.close()

    def repeat_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            row = self._stored_job(job_id)
            if row is None:
                raise ApiError(404, "trabajo no encontrado")
            job = {"kind": row["kind"], "body": json.loads(row["body"] or "{}")}
        if job.get("status") in ("queued", "running"):
            raise ApiError(409, "ese trabajo sigue en marcha")
        return self.start_job({"kind": job["kind"], "body": job.get("body") or {}})

    def job_status(self, q: dict[str, str]) -> dict[str, Any]:
        if not q.get("id"):   # sin id: los de esta ejecución y el historial guardado (más recientes primero)
            with self._jobs_guard:
                live = [{k: j[k] for k in self._JOB_FIELDS if k in j} for j in reversed(list(self.jobs.values()))]
            seen = {j["id"] for j in live}
            s = self._history()
            try:
                rows = s.conn.execute(f"SELECT {', '.join(self._JOB_FIELDS)} FROM job_history "
                                      "ORDER BY started DESC LIMIT 100").fetchall()
            finally:
                s.close()
            old = [{k: v for k, v in dict(r).items() if v is not None} | {"stored": True}
                   for r in rows if r["id"] not in seen]
            return {"jobs": (live + old)[:100], "max_running": self.MAX_RUNNING}
        job = self.jobs.get(q.get("id", ""))
        if job is None:
            raise ApiError(404, "trabajo no encontrado")
        try:
            since = max(0, int(q.get("since", 0)))
        except ValueError as exc:
            raise ApiError(400, "since inválido") from exc
        with self._jobs_guard:
            out = {k: job[k] for k in ("id", "kind", "status") if k in job}
            out["log"] = job["log"][since:]
            out["next"] = len(job["log"])
            out["elapsed"] = round((job.get("finished") or time.time()) - job["started"], 1)
            for k in ("result", "error", "code", "needs_confirm"):
                if k in job:
                    out[k] = job[k]
        return out

    def cancel_job(self, q: dict[str, str]) -> dict[str, Any]:
        job = self.jobs.get(q.get("id", ""))
        if job is None:
            raise ApiError(404, "trabajo no encontrado")
        if job["status"] in ("queued", "running"):
            job["cancel"] = True   # en cola: no llega a empezar; en marcha: se corta en el siguiente paso
        return {"id": job["id"], "status": job["status"], "cancel_requested": bool(job.get("cancel"))}

    @contextlib.contextmanager
    def _job(self, key: str):
        """Dos trabajos sobre la MISMA fuente/destino van de uno en uno; el segundo avisa de que espera."""
        with self._jobs_guard:
            lock = self._jobs.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            self._progress("esperando a que termine otro trabajo sobre la misma fuente o destino")
            while not lock.acquire(timeout=0.5):
                self._progress_check()
        try:
            yield
        finally:
            lock.release()

    def _progress_check(self) -> None:
        job = getattr(self._tl, "job", None)
        if job is not None and job.get("cancel"):
            raise JobCancelled()

    # -- lectura -------------------------------------------------------
    def health(self, _q) -> dict[str, Any]:
        return {"ok": True, "version": __version__, "db": str(Path(self.db).resolve()), "pid": os.getpid()}

    def _check_root(self, path: str | Path, what: str = "ruta") -> None:
        """Con carpetas permitidas configuradas, ninguna ruta local puede salir de ellas."""
        if not self.roots:
            return
        p = Path(path).expanduser().resolve()
        if not any(p == r or r in p.parents for r in self.roots):
            raise ApiError(403, f"{what} fuera de las carpetas permitidas: {p} "
                                f"(permitidas: {', '.join(str(r) for r in self.roots)})")

    def _check_local_source(self, src: str) -> None:
        from eolfi.flows.create_flow import classify

        if not src.startswith(("http://", "https://", "git@", "ssh://")) and classify(src) != "subject":
            self._check_root(src, "fuente")

    def fs_list(self, q) -> dict[str, Any]:
        """Carpetas para el selector del panel. Sin ruta: unidades (Windows) o raíz + inicio. Solo nombres de carpetas."""
        raw = (q.get("path") or "").strip()
        if not raw and self.roots:
            return {"path": "", "parent": None, "dirs": [{"name": str(r), "path": str(r)} for r in self.roots]}
        if raw:
            self._check_root(raw)
        if not raw:
            if os.name == "nt":
                import string
                roots = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
            else:
                roots = ["/"]
            home = str(Path.home())
            return {"path": "", "parent": None, "dirs": [{"name": r, "path": r} for r in [home, *roots]]}
        p = Path(raw).expanduser()
        if not p.is_dir():
            raise ApiError(404, f"No es una carpeta: {raw}")
        p = p.resolve()
        dirs = []
        try:
            for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                try:
                    if c.is_dir() and not c.name.startswith(("$", ".")):
                        dirs.append({"name": c.name, "path": str(c)})
                except OSError:
                    continue
                if len(dirs) >= 500:
                    break
        except PermissionError:
            raise ApiError(403, f"Sin permiso para leer {p}")
        parent = str(p.parent) if p.parent != p else ""
        return {"path": str(p), "parent": parent, "dirs": dirs}

    def providers(self, _q) -> dict[str, Any]:
        from eolfi.flows.triage_flow import ALL_PROVIDERS, DEFAULT_PROVIDERS, LOCAL_PROVIDERS

        def mode(p):
            return "local" if p in LOCAL_PROVIDERS else "default" if p in DEFAULT_PROVIDERS else "deep"
        from concurrent.futures import ThreadPoolExecutor

        from eolfi.generador.llm import PRESETS, probe

        cached = self._providers_cache
        if cached and time.time() - cached[0] < 30 and not _q.get("refresh"):
            return cached[1]

        def ia(n: str) -> dict[str, Any]:
            r = probe(n)   # una sola sonda por preajuste (antes eran dos, en serie)
            return {"name": f"ia:{n}", "available": r["available"], "version": r["detail"], "mode": "ia"}

        def local(p) -> dict[str, Any]:
            return {"name": p.name, "available": p.available(), "version": getattr(p, "version", "?"), "mode": mode(p)}

        with ThreadPoolExecutor(max_workers=8) as pool:
            ia_rows = list(pool.map(ia, PRESETS))
            local_rows = list(pool.map(local, ALL_PROVIDERS))
        out = {"providers": ia_rows + local_rows}
        self._providers_cache = (time.time(), out)
        return out

    def subjects(self, _q) -> dict[str, Any]:
        s = self.store()
        try:
            # Una sola consulta (antes 2 por objetivo) y index.json leído una vez (PLAN_MEJORAS M3).
            rows = s.conn.execute(
                "SELECT e.subject, COUNT(*) AS n, MIN(e.created_at) AS first, MAX(e.created_at) AS last, "
                "(SELECT f.result FROM evidence f WHERE f.subject=e.subject AND f.operation='detect_format' "
                " ORDER BY f.created_at DESC LIMIT 1) AS fmt, "
                "(SELECT COUNT(*) FROM incognita i WHERE i.subject=e.subject AND i.status!='resolved') AS open_n "
                "FROM evidence e GROUP BY e.subject ORDER BY last DESC"
            ).fetchall()
            index = self._index()
            out = []
            for r in rows:
                fmt = {"result": r["fmt"]} if r["fmt"] else None
                open_n = r["open_n"]
                subj = r["subject"]
                kind = ("binario" if len(subj) == 64 and ":" not in subj else
                        {"url": "web", "local": "web", "repo": "repo", "proyecto": "proyecto", "forge": "proyecto",
                         "compare": "comparación", "cmd": "diferencial", "resilience": "resiliencia"}
                        .get(subj.split(":", 1)[0], "otro"))
                out.append({
                    "subject": r["subject"], "kind": kind, "evidence": r["n"], "open_incognitas": open_n,
                    "format": json.loads(fmt["result"]).get("format") if fmt else None,
                    "names": self._names_for(r["subject"], index),
                    "first_seen": r["first"], "last_seen": r["last"],
                })
            return {"subjects": out}
        finally:
            s.close()

    def _index(self) -> dict[str, Any]:
        try:
            data = json.loads((self.samples / "index.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _names_for(self, subject: str, index: dict[str, Any] | None = None) -> list[str]:
        if subject.startswith(("url:", "repo:", "local:", "proyecto:", "forge:", "compare:")):
            kind, _, rest = subject.partition(":")
            return [f"{kind} · {rest.rstrip('/').rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1] or rest}"]
        names = (self._index() if index is None else index).get(subject, [])
        return names if isinstance(names, list) else []

    def evidence(self, q) -> dict[str, Any]:
        s = self.store()
        try:
            rows = s.list_evidence(q.get("subject"))
            if q.get("operation"):
                rows = [r for r in rows if r["operation"] == q["operation"]]
            needle = (q.get("q") or "").strip().lower()
            if needle:
                rows = [r for r in rows if needle in r["operation"].lower() or needle in r["provider"].lower()
                        or needle in (r.get("result") or "").lower()[:200_000]]
            try:
                offset = max(0, int(q.get("offset", 0)))
                limit = max(1, min(int(q.get("limit", 2000)), 5000))
            except ValueError as exc:
                raise ApiError(400, "limit/offset inválidos") from exc
            page = rows[offset:offset + limit]
            out: dict[str, Any] = {"evidence": _decode_rows(page, ("params", "result", "links")), "total": len(rows)}
            if offset + limit < len(rows):
                out["next_offset"] = offset + limit
            return out
        finally:
            s.close()

    def report(self, q) -> tuple[str, str]:
        from eolfi.core.report import build_report, render_html, render_markdown

        subject, fmt = q.get("subject", ""), q.get("format", "html")
        if fmt not in ("html", "md"):
            raise ApiError(400, "format debe ser html o md")
        s = self.store()
        try:
            rep = build_report(s, subject, self._names_for(subject))
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc
        finally:
            s.close()
        return (render_html(rep), "text/html; charset=utf-8") if fmt == "html" else \
            (render_markdown(rep), "text/markdown; charset=utf-8")

    # -- VS Code integrado en el panel (code serve-web) --------------------------------------------
    def vscode_status(self, _q) -> dict[str, Any]:
        return self.vscode_web.status()

    def vscode_start(self, body: dict[str, Any]) -> dict[str, Any]:
        folder = body.get("folder")
        if folder is not None:
            if not isinstance(folder, str) or not folder.strip():
                raise ApiError(400, "carpeta inválida")
            self._check_root(folder, "carpeta")
            if not Path(folder).is_dir():
                raise ApiError(404, f"no es una carpeta: {folder}")
        try:
            st = self.vscode_web.start(folder, accept_license=body.get("accept_license") is True)
        except PermissionError as exc:
            raise ApiError(412, str(exc), needs_license=True) from exc
        except FileNotFoundError as exc:
            raise ApiError(501, str(exc)) from exc
        except (RuntimeError, TimeoutError) as exc:
            raise ApiError(502, str(exc)) from exc
        st["url"] = self.vscode_web.url(folder)
        return st

    def vscode_stop(self, _body) -> dict[str, Any]:
        return self.vscode_web.stop()

    # -- Vinculación de clientes (extensión de VS Code): código de un solo uso → token -------------------
    def _clients(self):
        s = self.store()
        s.conn.execute("CREATE TABLE IF NOT EXISTS client_tokens (id TEXT PRIMARY KEY, token_sha256 TEXT UNIQUE, "
                       "name TEXT, created REAL, last_used REAL)")
        return s

    def pair_code(self, _body) -> dict[str, Any]:
        """El panel pide un código (6 dígitos, 10 min, un solo uso) que el usuario escribe en VS Code."""
        import secrets as _s

        now = time.time()
        self._pair_codes = {c: t for c, t in self._pair_codes.items() if t > now}
        if len(self._pair_codes) > 10:
            raise ApiError(429, "demasiados códigos pendientes")
        code = f"{_s.randbelow(10**6):06d}"
        self._pair_codes[code] = now + 600
        return {"code": code, "expires_in": 600}

    def pair_exchange(self, body: dict[str, Any]) -> dict[str, Any]:
        import secrets as _s

        code = str(body.get("code", "")).strip()
        name = str(body.get("name") or "VS Code")[:80]
        if self._pair_codes.pop(code, 0) < time.time():
            # Fallos: 1 s de espera y, al quinto fallo, se anulan TODOS los códigos pendientes (los intentos en
            # paralelo ya no pueden tantear el millón de combinaciones: hay que generar otro en el panel).
            self._pair_failures = getattr(self, "_pair_failures", 0) + 1
            if self._pair_failures >= 5:
                self._pair_codes.clear()
                self._pair_failures = 0
            time.sleep(1)   # frena el tanteo de códigos
            raise ApiError(403, "código incorrecto o caducado: genera otro en el panel (Proveedores → Vincular VS Code)")
        self._pair_failures = 0
        token = "ect_" + _s.token_urlsafe(32)
        s = self._clients()
        try:
            with s.conn:
                s.conn.execute("INSERT INTO client_tokens VALUES (?,?,?,?,?)",
                               (_s.token_hex(6), hashlib.sha256(token.encode()).hexdigest(), name, time.time(), None))
        finally:
            s.close()
        return {"token": token, "name": name}

    def client_ok(self, token: str) -> bool:
        if not token.startswith("ect_"):
            return False
        s = self._clients()
        try:
            h = hashlib.sha256(token.encode()).hexdigest()
            with s.conn:
                cur = s.conn.execute("UPDATE client_tokens SET last_used=? WHERE token_sha256=?", (time.time(), h))
            return cur.rowcount == 1
        finally:
            s.close()

    def clients(self, _q) -> dict[str, Any]:
        s = self._clients()
        try:
            rows = s.conn.execute("SELECT id, name, created, last_used FROM client_tokens ORDER BY created DESC").fetchall()
            return {"clients": [dict(r) for r in rows]}
        finally:
            s.close()

    def revoke_client(self, q) -> dict[str, Any]:
        s = self._clients()
        try:
            with s.conn:
                n = s.conn.execute("DELETE FROM client_tokens WHERE id=?", (q.get("id", ""),)).rowcount
            return {"revoked": n}
        finally:
            s.close()

    def incognitas(self, q) -> dict[str, Any]:
        status = q.get("status")
        if status and status not in {x.value for x in Status}:
            raise ApiError(400, f"status inválido: {status}")
        s = self.store()
        try:
            rows = s.list_incognitas(Status(status) if status else None, subject=q.get("subject"))
            return {"incognitas": _decode_rows(rows, ("evidence_for", "evidence_against", "depends_on"))}
        finally:
            s.close()

    def export(self, fmt: str) -> dict[str, Any]:
        s = self.store()
        try:
            if fmt == "sarif":
                from eolfi.core.sarif import build_sarif
                return build_sarif(s, self._sample_paths())
            if fmt == "stix":
                from eolfi.core.stix import build_stix
                idx = self.samples / "index.json"
                try:
                    names = json.loads(idx.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    names = {}
                return build_stix(s, names)
            from eolfi.core.evidence import SCHEMA_VERSION
            return {"schema_version": SCHEMA_VERSION, "evidence": s.list_evidence(),
                    "incognita": s.list_incognitas()}
        finally:
            s.close()

    def _sample_paths(self) -> list[Path]:
        return [p for p in self.samples.glob("*.bin") if p.is_file()]

    # -- escritura -----------------------------------------------------
    def resolve(self, incognita_id: str, body: dict[str, Any]) -> dict[str, Any]:
        status = body.get("status", Status.RESOLVED.value)
        if status not in {x.value for x in Status}:
            raise ApiError(400, f"status inválido: {status}")
        with self.lock:
            s = self.store()
            try:
                ok = s.resolve_incognita(incognita_id, Status(status))
            finally:
                s.close()
        if not ok:
            raise ApiError(404, "incógnita no encontrada")
        return {"incognita_id": incognita_id, "status": status}

    def store_upload(self, stream, length: int, name: str) -> dict[str, Any]:
        """Guarda el cuerpo por bloques de 1 MB con hash incremental: nunca entero en memoria (A4)."""
        import secrets

        if length <= 0:
            raise ApiError(400, "archivo vacío")
        self.samples.mkdir(parents=True, exist_ok=True)
        part = self.samples / f".subida-{secrets.token_hex(8)}.part"
        h = hashlib.sha256()
        left = length
        try:
            with open(part, "wb") as fh:
                while left:
                    chunk = stream.read(min(1 << 20, left))
                    if not chunk:
                        raise ApiError(400, "la subida se cortó antes de terminar")
                    h.update(chunk)
                    fh.write(chunk)
                    left -= len(chunk)
            sha = h.hexdigest()
            dst = self.samples / f"{sha}.bin"      # nombre por huella: nunca se usa el del cliente
            if dst.exists():
                part.unlink()
            else:
                os.replace(part, dst)
        finally:
            part.unlink(missing_ok=True)
        return {"upload": sha, "name": name[:200], "size": length}

    def triage_path(self, body: dict[str, Any]) -> dict[str, Any]:
        up = body.get("upload")
        if up is not None:   # archivo ya subido con /api/upload?store=1: se triará como trabajo
            if not isinstance(up, str) or not re.fullmatch(r"[0-9a-f]{64}", up):
                raise ApiError(400, "upload inválido")
            dst = self.samples / f"{up}.bin"
            if not dst.is_file():
                raise ApiError(404, "subida no encontrada")
            mode = body.get("mode", "local")
            if mode not in ("local", "default", "deep"):
                raise ApiError(400, f"modo inválido: {mode}")
            return self._triage(str(dst), mode, name=str(body.get("name") or "upload")[:200],
                                providers=body.get("providers"))
        path = body.get("path")
        if not isinstance(path, str) or not path:
            raise ApiError(400, "falta 'path'")
        self._check_root(path, "archivo")
        if Path(path).is_dir():
            # Una carpeta en «Binario»: se analiza como repositorio/carpeta (código, pila, estructura).
            self._progress(f"{path} es una carpeta: se analiza como repositorio")
            rep = self.learn("repo", {"source": path})
            rep.setdefault("analyzed_as", "repo")
            return rep
        if not Path(path).is_file():
            raise ApiError(404, f"no existe el archivo ni la carpeta: {path}")
        return self._triage(path, body.get("mode", "default"), name=Path(path).name, providers=body.get("providers"))

    def triage_upload(self, data: bytes, name: str, mode: str, providers: str | None = None) -> dict[str, Any]:
        if not data:
            raise ApiError(400, "archivo vacío")
        if mode not in ("local", "default", "deep"):   # antes de guardar nada en samples/
            raise ApiError(400, f"modo inválido: {mode}")
        self.samples.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(data).hexdigest()
        dst = self.samples / f"{sha}.bin"      # nombre por huella: nunca se usa el del cliente
        if not dst.exists():
            dst.write_bytes(data)
        return self._triage(str(dst), mode, name=name, providers=providers)

    def _triage(self, path: str, mode: str, name: str, providers: Any = None) -> dict[str, Any]:
        from eolfi.flows import triage_flow as tf

        provs = {"local": tf.LOCAL_PROVIDERS, "default": tf.DEFAULT_PROVIDERS, "deep": tf.DEEP_PROVIDERS}.get(mode)
        if provs is None:
            raise ApiError(400, f"modo inválido: {mode}")
        if providers:   # selección explícita desde la pestaña «Proveedores» (sustituye al modo)
            names = providers.split(",") if isinstance(providers, str) else providers
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise ApiError(400, "providers debe ser una lista de nombres")
            known = {p.name: p for p in tf.ALL_PROVIDERS}
            unknown = [n for n in names if n not in known]
            if unknown:
                raise ApiError(400, f"proveedores desconocidos: {', '.join(unknown)}")
            provs = [known[n] for n in dict.fromkeys(names)]
            mode = "selección"
        with self._job("triage:" + path):
            s = self.store()
            self._progress(f"triaje «{mode}» de {name}: {len(provs)} proveedores (Ghidra puede tardar minutos)")
            try:
                rep = tf.run_triage(path, s, provs, isolate=self.isolate)
                self._progress(f"proveedores ejecutados: {', '.join(rep.get('providers_run', []))}")
            finally:
                s.close()
            with self.lock:   # index.json: una escritura a la vez
                self._remember_name(rep["subject"], name)
        rep.pop("evidence_ids", None)
        return rep

    def learn(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        src = body.get("source")
        if not isinstance(src, str) or not src.strip():
            raise ApiError(400, "falta 'source'")
        self._check_local_source(src.strip())
        with self._job(f"{kind}:{src.strip()}"):
            s = self.store()
            try:
                if kind == "web":
                    from eolfi.flows.learn_flow import run_web
                    rep = run_web(src.strip(), s, max_assets=max(1, min(int(body.get("max_assets", 40)), 200)),
                                  cross_origin=bool(body.get("cross_origin")), progress=self._progress,
                                  ignore_robots=bool(body.get("ignore_robots")))
                else:
                    from eolfi.flows.learn_flow import run_repo
                    rep = run_repo(src.strip(), s, workdir=str(self.samples / "repos"), progress=self._progress)
            except (FileNotFoundError, ValueError) as exc:
                raise ApiError(400, str(exc)) from exc
            finally:
                s.close()
        rep.pop("evidence_ids", None)
        return rep

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.flows.create_flow import OverwriteSourceError, create_project

        sources = body.get("sources")
        if not isinstance(sources, list) or not sources or not all(isinstance(x, str) and x.strip() for x in sources):
            raise ApiError(400, "'sources' debe ser una lista no vacía")
        name = str(body.get("name") or "Nuevo proyecto")[:80]
        out = body.get("out") or str(Path("generated") / _folder_slug(name))
        self._check_root(out, "carpeta destino")
        for src in sources:
            self._check_local_source(src.strip())
        with self._job("create:" + str(Path(out).resolve())):
            s = self.store()
            try:
                rep = create_project([x.strip() for x in sources], s, out, name=name,
                                     target=str(body.get("target") or "auto"), do_verify=bool(body.get("verify")),
                                     force=bool(body.get("force")), workdir=str(self.samples / "repos"),
                                     ai_brief=(str(body["ai_brief"])[:4000] if body.get("ai_brief") else None),
                                     ai_provider=str(body.get("ai_provider") or "claude"),
                                     ai_model=(str(body["ai_model"]) if body.get("ai_model") else None),
                                     ai_base_url=(str(body["ai_base_url"])[:300] if body.get("ai_base_url") else None),
                                     reanalyze=bool(body.get("reanalyze")),
                                     db="sqlite" if body.get("db") == "sqlite" else "memory",
                                     auth=bool(body.get("auth")), progress=self._progress)
            except FileExistsError as exc:
                raise ApiError(409, str(exc)) from exc
            except OverwriteSourceError as exc:
                raise ApiError(409, str(exc), needs_confirm=True) from exc
            except (FileNotFoundError, ValueError) as exc:
                raise ApiError(400, str(exc)) from exc
            except Exception as exc:
                from eolfi.generador.assist import AssistError
                if isinstance(exc, AssistError):
                    raise ApiError(502, str(exc)) from exc
                raise
            finally:
                s.close()
        return rep

    def compare(self, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.flows.compare_flow import compare
        from eolfi.flows.create_flow import resolve_subject

        with self._job("compare"):
            s = self.store()
            try:
                a, b = resolve_subject(s, str(body.get("a", ""))), resolve_subject(s, str(body.get("b", "")))
                if not a or not b:
                    raise ApiError(404, "objetivo no encontrado o ambiguo")
                return compare(s, a, b)
            finally:
                s.close()

    # -- puente de chats web (DeepSeek / Gemini / Meta AI) ----------------
    # El token del puente se queda en el servidor: el navegador nunca lo ve.
    BRIDGE_SITES = ("deepseek", "gemini", "meta", "chatgpt", "copilot", "lechat")

    def _bridge(self, path: str, body: dict[str, Any] | None = None, timeout: float = 20.0, raw: bool = False):
        import urllib.error
        import urllib.request

        from eolfi.generador.llm import LLMError, read_bridge

        try:
            b = read_bridge()
        except LLMError as exc:
            raise ApiError(503, str(exc)) from exc
        req = urllib.request.Request(
            b["url"] + path, method="POST" if body is not None else "GET",
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            # El panel usa su propia credencial (panelToken): solo ella permite /v1/input,
            # /v1/screen y los mensajes sin aprobación. Eolfi automático (llm.py) usa `token`.
            headers={"Authorization": f"Bearer {b.get('panelToken') or b['token']}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return data if raw else json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                msg = json.loads(exc.read().decode("utf-8")).get("error", f"HTTP {exc.code}")
            except (ValueError, OSError):
                msg = f"HTTP {exc.code}"
            raise ApiError(502 if exc.code >= 500 else exc.code, msg) from exc
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
            # HTTPException (p. ej. IncompleteRead si el puente se reinicia a mitad de una captura) daba 500.
            raise ApiError(503, "El puente no responde: arráncalo con  python -m eolfi bridge") from exc

    def bridge_status(self, _q) -> dict[str, Any]:
        try:
            return {"running": True, **self._bridge("/v1/status")}
        except ApiError as exc:
            if exc.status == 503:
                return {"running": False, "detail": str(exc), "providers": {}}
            raise

    def bridge_events(self, q) -> dict[str, Any]:
        since = q.get("since", "0")
        if not since.isdigit():
            raise ApiError(400, "since inválido")
        return self._bridge(f"/v1/events?since={since}")

    def bridge_screen(self, q) -> bytes:
        prov = q.get("provider", "")
        if prov not in self.BRIDGE_SITES:
            raise ApiError(400, "proveedor inválido")
        return self._bridge(f"/v1/screen?provider={prov}", raw=True)

    INPUT_KEYS = {"Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft",
                  "ArrowRight", "PageDown", "PageUp"}

    def bridge_input(self, body: dict[str, Any]) -> dict[str, Any]:
        prov, kind = body.get("provider"), body.get("type")
        if prov not in self.BRIDGE_SITES:
            raise ApiError(400, "proveedor inválido")
        ev: dict[str, Any] = {"provider": prov, "type": kind}
        if kind in ("click", "wheel"):
            try:
                ev["x"], ev["y"] = float(body["x"]), float(body["y"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ApiError(400, "faltan coordenadas") from exc
            if not (0 <= ev["x"] <= 1 and 0 <= ev["y"] <= 1):
                raise ApiError(400, "coordenadas fuera de rango")
            if kind == "wheel":
                ev["deltaY"] = max(-3000.0, min(3000.0, float(body.get("deltaY", 0))))
        elif kind == "key":
            if body.get("key") not in self.INPUT_KEYS:
                raise ApiError(400, "tecla no soportada")
            ev["key"] = body["key"]
        elif kind == "text":
            text = body.get("text")
            if not isinstance(text, str) or not 0 < len(text) <= 2000:
                raise ApiError(400, "texto inválido")
            ev["text"] = text
        else:
            raise ApiError(400, "tipo de entrada no soportado")
        return self._bridge("/v1/input", ev)

    def bridge_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        prov = body.get("provider")
        prompt = body.get("prompt")
        if prov not in self.BRIDGE_SITES:
            raise ApiError(400, "proveedor inválido")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30_000:
            raise ApiError(400, "escribe un mensaje (máx. 30 000 caracteres)")
        conv = str(body.get("conversation") or f"panel-{prov}")
        if not re.fullmatch(rf"panel-{prov}(-\d{{1,16}})?", conv):
            raise ApiError(400, "conversación inválida")
        return self._bridge("/v1/chat", {"provider": prov, "prompt": prompt, "source": "panel",
                                         "conversation": conv}, timeout=1900)

    def bridge_selftest(self, q) -> dict[str, Any]:
        prov = q.get("provider", "")
        if prov not in self.BRIDGE_SITES:
            raise ApiError(400, "proveedor inválido")
        extra = "&discover=1" if q.get("discover") == "1" else ""
        return self._bridge(f"/v1/selftest?provider={prov}{extra}", timeout=30)

    def bridge_compare(self, body: dict[str, Any]) -> dict[str, Any]:
        provs, prompt = body.get("providers"), body.get("prompt")
        if not isinstance(provs, list) or not 2 <= len(set(provs)) <= 6 or any(p not in self.BRIDGE_SITES for p in provs):
            raise ApiError(400, "elige entre 2 y 6 chats")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30_000:
            raise ApiError(400, "escribe un mensaje (máx. 30 000 caracteres)")
        conv = str(body.get("conversation") or "panel-compare")
        if not re.fullmatch(r"panel-compare(-\d{1,16})?", conv):
            raise ApiError(400, "conversación inválida")
        return self._bridge("/v1/compare", {"providers": list(dict.fromkeys(provs)), "prompt": prompt,
                                            "source": "panel", "conversation": conv}, timeout=1900)

    def _remember_name(self, subject: str, name: str) -> None:
        safe = re.sub(r"[^\w.\- ]", "_", name)[:120] or "sin_nombre"
        self.samples.mkdir(parents=True, exist_ok=True)
        idx = self.samples / "index.json"
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        names = data.setdefault(subject, [])
        if safe not in names:
            names.append(safe)
        tmp = idx.with_name(f".index-{os.getpid()}-{threading.get_ident()}.tmp")   # escritura atómica
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, idx)


def _folder_slug(name: str) -> str:
    """«Árbol de tareas» → «arbol-de-tareas»; «日本語» se conserva; vacío → proyecto-AAAAMMDD-HHMM (M1)."""
    import unicodedata

    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    slug = re.sub(r"[^\w]+", "-", plain.lower()).strip("-_")[:60]
    return slug or time.strftime("proyecto-%Y%m%d-%H%M")


def make_handler(app: EolfiApp, allowed_hosts: set[str], token: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"eolfi/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # una línea por petición, a stderr (sin el token)
            path = re.sub(r"([?&]token=)[^&]*", r"\1***", self.path or "")
            msg = re.sub(r"([?&]token=)[^&\s]*", r"\1***", fmt % args)
            sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {self.command} {path} {msg}\n")

        # -- utilidades ------------------------------------------------
        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")   # <img src> desde otra web: bloqueado
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")   # el cliente reabre: el cuerpo no leído no se reutiliza
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, obj: Any, extra: dict[str, str] | None = None):
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", extra)

        def _check_host(self) -> bool:
            raw = (self.headers.get("Host") or "").lower()
            host = raw[: raw.find("]") + 1] if raw.startswith("[") else raw.split(":")[0]
            # Con --host 0.0.0.0 los clientes llegan con la IP del equipo: se admite cualquier Host
            # porque entonces la API exige el token de arranque (protege también del DNS rebinding).
            if host not in allowed_hosts and not (token and allowed_hosts & {"0.0.0.0", "::", "[::]"}):
                self._json(421, {"error": f"Host no permitido: {host}"})
                return False
            return True

        def _body(self) -> bytes:
            return self._raw

        def _obj(self) -> dict[str, Any]:
            """Cuerpo JSON que debe ser un objeto ([] o "x" darían 500 más adelante)."""
            body = json.loads(self._raw or b"{}")
            if not isinstance(body, dict):
                raise ApiError(400, "el cuerpo debe ser un objeto JSON")
            return body

        def _read_body(self, limit: int) -> None:
            """Lee el cuerpo solo si la petición ya pasó las comprobaciones baratas; si no se lee,
            se cierra la conexión (keep-alive lo tomaría como otra petición)."""
            self._raw = b""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > limit:
                self.close_connection = True
                raise ApiError(413, f"Content-Length inválido o mayor que {limit} bytes")
            if n:
                self._raw = self.rfile.read(n)

        def _authorized(self, q: dict[str, str]) -> bool:
            """Con --allow-remote hace falta el token de arranque (cookie HttpOnly o ?token= la primera vez).
            Los clientes vinculados (extensión de VS Code) se identifican con X-Eolfi-Client y su token propio."""
            bearer = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            path = urlparse(self.path).path
            if path == "/api/clients/token":   # el canje del código es lo único que se hace sin token
                return True
            if self.headers.get("X-Eolfi-Client") or bearer.startswith("ect_"):
                return app.client_ok(bearer)
            if not token:
                return True
            import hmac
            from http.cookies import SimpleCookie

            c = SimpleCookie()
            try:
                c.load(self.headers.get("Cookie") or "")
            except Exception:  # noqa: BLE001
                pass
            got = c["eolfi_token"].value if "eolfi_token" in c else q.get("token", "")
            return hmac.compare_digest(got.encode(), token.encode())

        def _reject(self, status: int, msg: str) -> None:
            """Rechazo antes de leer: un cuerpo pequeño se descarta (evita el reset TCP en Windows);
            uno grande no se lee y se cierra la conexión."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if 0 < n <= 64 * 1024:
                self.rfile.read(n)
            elif n != 0:
                self.close_connection = True
            raise ApiError(status, msg)

        def _precheck(self, method: str) -> None:
            """Antes de leer un byte del cuerpo: origen de la petición y cabecera anti-CSRF."""
            site = (self.headers.get("Sec-Fetch-Site") or "").lower()
            if method in ("GET", "HEAD"):
                # Una web ajena no puede disparar capturas ni leer la API con <img>/<script> (M6). Abrir el
                # panel desde un enlace (navegación) sí se permite.
                if site in ("cross-site", "same-site") and urlparse(self.path).path.startswith("/api/") \
                        and (self.headers.get("Sec-Fetch-Mode") or "").lower() != "navigate":
                    self._reject(403, "petición desde otro sitio rechazada")
                return
            if site in ("cross-site", "same-site"):
                self._reject(403, "petición desde otro sitio rechazada")
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                self._reject(403, "Origin no permitido")
            if self.headers.get("X-Eolfi") != "1":
                self._reject(403, "falta la cabecera X-Eolfi: 1")

        def _route(self, method: str):
            if not self._check_host():
                self.close_connection = True
                return
            url = urlparse(self.path)
            path = url.path
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if not self._authorized(q):
                    self._reject(401, "falta el token: abre la URL con ?token=… que mostró `eolfi serve`")
                self._precheck(method)
                if method == "POST" and path == "/api/upload" and q.get("store") == "1":
                    # Por bloques, directamente a disco; el triaje se lanza después como trabajo (A4).
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                    except ValueError:
                        n = -1
                    if n < 0 or n > MAX_UPLOAD:
                        self.close_connection = True
                        raise ApiError(413, f"Content-Length inválido o mayor que {MAX_UPLOAD} bytes")
                    return self._json(200, app.store_upload(self.rfile, n, q.get("name", "upload")))
                self._read_body(MAX_UPLOAD if path == "/api/upload" else MAX_JSON)
                if method in ("GET", "HEAD"):
                    if path in _STATIC:
                        if token and q.get("token"):
                            # Cookie y redirección a la URL sin token: no queda en el historial ni en registros.
                            return self._send(303, b"", "text/plain; charset=utf-8", {
                                "Set-Cookie": f"eolfi_token={token}; HttpOnly; SameSite=Strict; Path=/",
                                "Location": path})
                        f = WEB_DIR / _STATIC[path]
                        return self._send(200, f.read_bytes(), _CTYPE[f.suffix])
                    routes = {
                        "/api/health": app.health, "/api/providers": app.providers,
                        "/api/vscode/status": app.vscode_status, "/api/clients": app.clients,
                        "/api/subjects": app.subjects, "/api/evidence": app.evidence,
                        "/api/incognitas": app.incognitas, "/api/fs/list": app.fs_list, "/api/jobs": app.job_status,
                    }
                    if path in routes:
                        return self._json(200, routes[path](q))
                    if path == "/api/bridge/selftest":
                        return self._json(200, app.bridge_selftest(q))
                    if path in ("/api/bridge/status", "/api/bridge/events"):
                        fn = app.bridge_status if path.endswith("status") else app.bridge_events
                        return self._json(200, fn(q))
                    if path == "/api/report":
                        text, ctype = app.report(q)
                        ext = "html" if ctype.startswith("text/html") else "md"
                        short = re.sub(r"[^\w.-]", "_", q.get("subject", "objetivo"))[-40:]
                        return self._send(200, text.encode("utf-8"), ctype, {
                            "Content-Disposition": f'attachment; filename="eolfi-{short}.{ext}"'})
                    if path == "/api/bridge/screen":
                        return self._send(200, app.bridge_screen(q), "image/jpeg")
                    if path in ("/api/export.sarif", "/api/export.json", "/api/export.stix"):
                        fmt = path.rsplit(".", 1)[1]
                        return self._json(200, app.export(fmt), {
                            "Content-Disposition": f'attachment; filename="eolfi.{fmt}"'})
                    raise ApiError(404, "ruta no encontrada")
                if method == "POST":
                    if path == "/api/triage":
                        body = self._obj()
                        return self._json(200, app.triage_path(body))
                    if path in ("/api/web", "/api/repo"):
                        return self._json(200, app.learn(path.rsplit("/", 1)[1], self._obj()))
                    if path == "/api/jobs":
                        return self._json(202, app.start_job(self._obj()))
                    if path == "/api/create":
                        return self._json(200, app.create(self._obj()))
                    if path == "/api/bridge/input":
                        return self._json(200, app.bridge_input(self._obj()))
                    if path == "/api/bridge/chat":
                        return self._json(200, app.bridge_chat(self._obj()))
                    if path == "/api/vscode/start":
                        return self._json(200, app.vscode_start(self._obj()))
                    if path == "/api/vscode/stop":
                        return self._json(200, app.vscode_stop(self._obj()))
                    if path == "/api/clients/pair":
                        if self.headers.get("X-Eolfi-Client"):   # el código solo lo pide el panel, no un cliente
                            raise ApiError(403, "el código de vinculación se genera en el panel de Eolfi")
                        return self._json(200, app.pair_code(self._obj()))
                    if path == "/api/clients/token":
                        return self._json(200, app.pair_exchange(self._obj()))
                    if path == "/api/bridge/compare":
                        return self._json(200, app.bridge_compare(self._obj()))
                    if path == "/api/compare":
                        return self._json(200, app.compare(self._obj()))
                    if path == "/api/upload":
                        data = self._body()
                        return self._json(200, app.triage_upload(
                            data, q.get("name", "upload"), q.get("mode", "local"), q.get("providers")))
                    m = re.fullmatch(r"/api/jobs/([0-9a-f]{16})/repeat", path)
                    if m:
                        return self._json(202, app.repeat_job(m.group(1)))
                    m = re.fullmatch(r"/api/incognitas/([0-9a-f]{16})/resolve", path)
                    if m:
                        body = self._obj()
                        return self._json(200, app.resolve(m.group(1), body))
                    raise ApiError(404, "ruta no encontrada")
                if method == "DELETE" and path == "/api/clients":
                    return self._json(200, app.revoke_client(q))
                if method == "DELETE" and path == "/api/jobs":
                    return self._json(200, app.cancel_job(q))
                raise ApiError(405, "método no permitido")
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc), **exc.extra})
            except json.JSONDecodeError as exc:
                self._json(400, {"error": f"JSON inválido: {exc}"})
            except (ValueError, TypeError, KeyError) as exc:
                self._json(400, {"error": f"petición inválida: {exc}"})
            except UnicodeDecodeError:
                self._json(400, {"error": "El cuerpo de la petición no está en UTF-8"})
            except Exception as exc:  # noqa: BLE001 — el servidor no cae por una petición
                traceback.print_exc()
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_GET(self):
            self._route("GET")

        def do_HEAD(self):
            self._route("HEAD")

        def do_POST(self):
            self._route("POST")

        def do_PUT(self):
            self._route("PUT")

        def do_DELETE(self):
            self._route("DELETE")

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # En Windows SO_REUSEADDR permite que dos procesos escuchen en el mismo
    # puerto (secuestro de puerto). Allí se pide uso exclusivo.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        import socket

        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(db: str, host: str = "127.0.0.1", port: int = 8777,
                samples_dir: str | Path = "samples", token: str | None = None) -> ThreadingHTTPServer:
    allowed = set(_LOOPBACK) | {host.lower()}
    if host not in _LOOPBACK and not token:
        import secrets
        token = secrets.token_urlsafe(24)   # fuera de loopback la API nunca queda abierta
    app = EolfiApp(db, samples_dir)
    if token and not app.roots:
        # Modo remoto sin carpetas configuradas: solo las de Eolfi (muestras y proyectos generados).
        app.roots = [Path(samples_dir).resolve(), Path("generated").resolve()]
    httpd = _Server((host, port), make_handler(app, allowed, token))
    httpd.app = app
    httpd.token = token
    return httpd


def serve(db: str, host: str = "127.0.0.1", port: int = 8777, allow_remote: bool = False,
          samples_dir: str | Path = "samples") -> int:
    if host not in _LOOPBACK and not allow_remote:
        print(f"eolfi: negando escuchar en {host}: usa --allow-remote si de verdad lo quieres "
              f"(la API puede analizar archivos locales).", file=sys.stderr)
        return 2
    try:
        httpd = make_server(db, host, port, samples_dir)
    except OSError as exc:
        print(f"eolfi: no se pudo escuchar en {host}:{port} ({exc.strerror or exc}). "
              f"¿Puerto ocupado? Prueba con --port.", file=sys.stderr)
        return 2
    shown = host
    if host in ("0.0.0.0", "::", "[::]"):
        import socket

        try:
            shown = socket.gethostbyname(socket.gethostname())   # 0.0.0.0 no se puede abrir en el navegador
        except OSError:
            shown = "127.0.0.1"
    url = f"http://{shown}:{httpd.server_address[1]}"
    if httpd.token:
        url += f"/?token={httpd.token}"
        print("eolfi: modo remoto. Abre esta URL (contiene el token de acceso de esta ejecución):", flush=True)
    print(f"Eolfi {__version__} sirviendo en {url}  (db: {db})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


# ---------------------------------------------------------------------------
# --reload: proceso vigilante que reinicia el servidor al cambiar el código
# ---------------------------------------------------------------------------
def _snapshot(root: Path) -> dict[str, float]:
    out = {}
    for p in root.rglob("*"):
        if p.suffix in (".py", ".html", ".js", ".css") and "__pycache__" not in p.parts:
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


def serve_with_reload(child_argv: list[str], interval: float = 0.7) -> int:
    root = Path(__file__).resolve().parent
    env = dict(os.environ, PYTHONPATH=str(root.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    print(f"eolfi: modo --reload, vigilando {root}", flush=True)
    while True:
        snap = _snapshot(root)
        proc = subprocess.Popen([sys.executable, "-m", "eolfi", *child_argv], env=env)
        try:
            while True:
                time.sleep(interval)
                if proc.poll() is not None:
                    # El hijo cayó (p. ej. error de sintaxis): esperar a otro cambio.
                    print("eolfi: el servidor terminó; esperando cambios para reiniciar…", flush=True)
                    while _snapshot(root) == snap:
                        time.sleep(interval)
                    break
                if _snapshot(root) != snap:
                    print("eolfi: cambio detectado, reiniciando…", flush=True)
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
        except KeyboardInterrupt:
            proc.terminate()
            return 0
