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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Status

WEB_DIR = Path(__file__).with_name("web")
MAX_UPLOAD = 256 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024   # rutas JSON: nunca necesitan más
_STATIC = {"/": "index.html", "/app.js": "app.js", "/runtime.js": "runtime.js", "/cases.js": "cases.js",
           "/projects.js": "projects.js", "/eolas-chat.js": "eolas-chat.js",
           "/subjects.js": "subjects.js", "/theme.js": "theme.js", "/style.css": "style.css",
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
_CASE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Informe de caso: HTML autocontenido sin scripts; solo necesita estilos en línea.
_REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"


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


class _WslPaths:
    """Traduce las rutas de Windows de los argumentos a /mnt/… para el REA de WSL."""

    def __init__(self, client: Any):
        self.client = client

    def call(self, name: str, args: dict[str, Any], limit: Any = None) -> tuple[str, bool]:
        from eolfi.rea_client import wsl_path

        args = {k: (wsl_path(v) if k == "path" and isinstance(v, str) else v) for k, v in args.items()}
        return self.client.call(name, args, limit=limit)


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
        # Actividad del agente: conserva progreso redactado sin prompts ni respuestas.
        self._vscode_activity_lock = threading.Lock()
        self._tl = threading.local()
        self._mark_interrupted()
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
    JOB_KINDS = ("create", "web", "repo", "triage", "project", "eolas-e2e", "chat")
    MAX_JOBS = 50
    MAX_RUNNING = 3

    def _progress(self, message: str) -> None:
        job = getattr(self._tl, "job", None)
        if job is not None:
            if job.get("cancel"):
                raise JobCancelled()   # cancelación cooperativa: en el siguiente aviso de progreso
            with self._jobs_guard:
                from eolfi.security.privacy import redact

                job["log"].append({"t": round(time.time() - job["started"], 1), "msg": redact(str(message)[:500])[0]})
                del job["log"][:-2000]
                snapshot = time.time() - job.get("_saved", 0) > 60
                if snapshot:
                    job["_saved"] = time.time()
            if snapshot:   # el registro se guarda como mucho cada minuto, fuera del cerrojo
                self._save_job(job)

    def start_job(self, body: dict[str, Any]) -> dict[str, Any]:
        import secrets

        kind, payload = body.get("kind"), body.get("body") or {}
        if kind not in self.JOB_KINDS or not isinstance(payload, dict):
            raise ApiError(400, f"kind debe ser uno de {', '.join(self.JOB_KINDS)} y body un objeto")
        fn = {"create": self.create, "web": lambda b: self.learn("web", b), "project": self.project_run,
              "repo": lambda b: self.learn("repo", b), "triage": self.triage_path,
              "eolas-e2e": self.eolas_e2e, "chat": self.chat}[kind]
        job = {"id": secrets.token_hex(8), "kind": kind, "status": "queued", "log": [], "started": time.time(),
               "label": str(payload.get("name") or payload.get("source") or payload.get("path")
                            or ", ".join(map(str, payload.get("sources") or []))
                            or (f"Banco · {payload.get('battery') or ('json' if payload.get('suite') else 'pregunta')} · "
                                f"{', '.join(map(str, payload.get('profiles') or []))}" if kind == "eolas-e2e" else ""))[:160],
               "body": payload, **({"case_id": cid} if (cid := self._case_id(payload)) else {})}

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
                job["_saved"] = time.time()
                self._save_job(job)
                job["result"] = fn(payload)
                if isinstance(job["result"], dict) and isinstance(job["result"].get("subject"), str):
                    job["subject"] = job["result"]["subject"]
                final: dict[str, Any] = {"status": "done"}
                result = job["result"]
                if kind == "create" and isinstance(result, dict):
                    assistance = result.get("assist") or {}
                    verification = result.get("verification") or {}
                    if assistance.get("ok") is False:
                        final = {"status": "error", "code": 422,
                                 "error": "Creación fallida: la IA no superó las pruebas; archivos originales restaurados"}
                    elif verification.get("ok") is False:
                        final = {"status": "error", "code": 422,
                                 "error": "Creación fallida: la verificación del proyecto no se superó"}
            except JobCancelled:
                final = {"status": "cancelled", "error": "Cancelado por el usuario", "code": 499}
            except ApiError as exc:
                final = {"status": "error", "error": str(exc), "code": exc.status, **exc.extra}
            except Exception as exc:  # noqa: BLE001 — el error se informa en el propio trabajo
                final = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "code": 500}
            finally:
                if acquired:
                    self._slots.release()
                self._tl.job = None
            # Primero queda guardado en la base y solo después se publica como terminado: quien vea «done»
            # (el panel, otra instancia tras un reinicio) ya lo encuentra en el historial.
            finished = time.time()
            self._save_job({**job, **final, "finished": finished})
            job.update(final, finished=finished)

        with self._jobs_guard:
            self.jobs[job["id"]] = job
            for old in list(self.jobs)[:-self.MAX_JOBS]:     # se conservan los últimos 50
                if self.jobs[old]["status"] not in ("running", "queued"):
                    del self.jobs[old]
        threading.Thread(target=run, name=f"job-{kind}", daemon=True).start()
        return {"job_id": job["id"], "kind": kind}

    def eolas_e2e(self, body: dict[str, Any]) -> dict[str, Any]:
        """Banco local de motores: progreso visible y un único llama-server."""
        from eolfi import eolas_v2

        raw_profiles = body.get("profiles")
        profiles = [str(p) for p in raw_profiles] if isinstance(raw_profiles, list) else None
        if body.get("suite") is True:
            battery = body.get("battery") if body.get("battery") in ("codigo", "codigo_nuevo", "completa") else "json"
            return eolas_v2.run_full_evaluation(profiles=profiles, progress=self._progress, battery=battery,
                                                use_lessons=body.get("lessons", True) is not False,
                                                learn=battery == "codigo", retire_failed=body.get("retire_failed") is True,
                                                repesca=(str(eolas_v2.exams_dir() / Path(str(body["repesca"])).name)
                                                         if body.get("repesca") else None))
        return eolas_v2.run_fair_evaluation(prompt=str(body.get("prompt") or ""),
                                             expected=str(body.get("expected") or ""), profiles=profiles,
                                             progress=self._progress)

    # -- historial persistente (pestaña «Trabajos») ------------------------------
    _JOB_FIELDS = ("id", "kind", "status", "label", "started", "finished", "error", "subject")
    MAX_STORED_RESULT = 4_000_000
    HISTORY_KEEP = 4

    def _history(self):
        s = self.store()
        s.conn.execute("CREATE TABLE IF NOT EXISTS job_history (id TEXT PRIMARY KEY, kind TEXT, status TEXT, "
                       "label TEXT, started REAL, finished REAL, error TEXT, subject TEXT, body TEXT)")
        # Resultado y registro del trabajo terminado: antes se perdían si el servidor se reiniciaba (12/11/2026,
        # una batería de una hora quedó sin resultados tras un --reload).
        s.conn.execute("CREATE TABLE IF NOT EXISTS job_results (id TEXT PRIMARY KEY, result TEXT, log TEXT)")
        # Trabajos en marcha y el proceso que los ejecuta: si ese proceso ya no existe, el trabajo se cortó.
        s.conn.execute("CREATE TABLE IF NOT EXISTS job_live (id TEXT PRIMARY KEY, pid INTEGER)")
        return s

    INTERRUPTED = ("El servidor se reinició o se cerró con el trabajo en marcha; el registro llega hasta el último "
                   "guardado. Puedes repetirlo.")

    def _mark_interrupted(self) -> None:
        """12/11/2026: un trabajo cortado por un reinicio desaparecía sin rastro (dos pruebas de horas perdidas).
        Ahora queda en el historial como «interrumpido», con su registro hasta el último guardado."""
        from eolfi.eolas_v2 import _pid_alive

        try:
            s = self._history()
            try:
                with s.conn:
                    for row in s.conn.execute("SELECT id, pid FROM job_live").fetchall():
                        if _pid_alive(int(row["pid"] or 0)):
                            continue
                        s.conn.execute("UPDATE job_history SET status='interrupted', error=?, "
                                       "finished=COALESCE(finished, ?) WHERE id=?",
                                       (self.INTERRUPTED, time.time(), row["id"]))
                        s.conn.execute("DELETE FROM job_live WHERE id=?", (row["id"],))
            finally:
                s.close()
        except Exception:  # noqa: BLE001 — el historial nunca impide arrancar
            traceback.print_exc()

    def _save_job(self, job: dict[str, Any]) -> None:
        """Cada trabajo queda en eolfi.db al empezar, cada minuto mientras corre y al terminar (sobrevive a reinicios)."""
        try:
            s = self._history()
            try:
                with s.conn:
                    if job["status"] in ("queued", "running"):
                        s.conn.execute("INSERT OR REPLACE INTO job_live VALUES (?,?)", (job["id"], os.getpid()))
                    else:
                        s.conn.execute("DELETE FROM job_live WHERE id=?", (job["id"],))
                    s.conn.execute("INSERT OR REPLACE INTO job_history VALUES (?,?,?,?,?,?,?,?,?)", (
                        job["id"], job["kind"], job["status"], job.get("label"), job["started"], job.get("finished"),
                        (job.get("error") or "")[:2000] or None, job.get("subject"),
                        json.dumps(job.get("body") or {}, ensure_ascii=False)[:200_000]))
                    result = json.dumps(job.get("result"), ensure_ascii=False, default=str) if "result" in job else None
                    if result is not None and len(result) > self.MAX_STORED_RESULT:
                        result = json.dumps({"omitido": f"resultado de {len(result)} caracteres: no se guarda"})
                    log = json.dumps((job.get("log") or [])[-2000:], ensure_ascii=False, default=str)
                    s.conn.execute("INSERT OR REPLACE INTO job_results VALUES (?,?,?)", (job["id"], result, log))
                    # El historial guarda solo los últimos trabajos terminados (decisión del titular, 12/11/2026).
                    s.conn.execute("DELETE FROM job_history WHERE id NOT IN "
                                   "(SELECT id FROM job_history ORDER BY started DESC LIMIT ?)", (self.HISTORY_KEEP,))
                    s.conn.execute("DELETE FROM job_results WHERE id NOT IN (SELECT id FROM job_history)")
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

    def _stored_result(self, job_id: str) -> dict[str, Any] | None:
        """Un trabajo terminado de una ejecución anterior del servidor, con su resultado y su registro."""
        row = self._stored_job(job_id) if job_id else None
        if row is None:
            return None
        s = self._history()
        try:
            extra = s.conn.execute("SELECT result, log FROM job_results WHERE id=?", (job_id,)).fetchone()
        finally:
            s.close()
        log = json.loads(extra["log"]) if extra and extra["log"] else []
        out = {"id": row["id"], "kind": row["kind"], "status": row["status"], "log": log, "next": len(log),
               "elapsed": round((row["finished"] or row["started"]) - row["started"], 1), "stored": True}
        if extra and extra["result"] is not None:
            out["result"] = json.loads(extra["result"])
        if row["error"]:
            out["error"] = row["error"]
        return out

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
                live = [{k: j[k] for k in self._JOB_FIELDS + ("case_id",) if k in j}
                        for j in reversed(list(self.jobs.values()))]
            seen = {j["id"] for j in live}
            s = self._history()
            try:
                rows = s.conn.execute(f"SELECT {', '.join(self._JOB_FIELDS)} FROM job_history "
                                      "ORDER BY started DESC LIMIT ?", (self.HISTORY_KEEP,)).fetchall()
            finally:
                s.close()
            old = [{k: v for k, v in dict(r).items() if v is not None} | {"stored": True}
                   for r in rows if r["id"] not in seen]
            return {"jobs": (live + old)[:100], "max_running": self.MAX_RUNNING}
        job = self.jobs.get(q.get("id", ""))
        if job is None:
            stored = self._stored_result(q.get("id", ""))
            if stored is None:
                raise ApiError(404, "trabajo no encontrado")
            return stored
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

    @contextlib.contextmanager
    def _activity_store(self):
        with contextlib.closing(self.store()) as store, store.conn as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS vscode_activity "
                         "(run_id TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL)")
            yield conn

    def chat_status(self, _q=None) -> dict[str, Any]:
        """Motor del chat: el perfil activo de Eolas V2 (llama-server de Eolfi)."""
        from eolfi import chat, eolas_v2

        try:
            remote = chat.remote_engine()
        except RuntimeError as exc:
            return {"available": False, "detail": str(exc), "busy": None}
        if remote:
            return {"available": True, "detail": remote["label"], "model": remote["alias"], "remote": True,
                    "loaded": True, "busy": None}
        try:
            st = eolas_v2.status()
        except Exception as exc:  # noqa: BLE001 — configuración ausente o inválida
            return {"available": False, "detail": f"Eolas V2 no está configurado: {exc}", "busy": self._gpu_busy()}
        available = Path(str(st["model"])).is_file()
        detail = (f"{st['active_profile']} ({st['alias']}) " + ("cargado" if st["running"] else "se cargará al primer mensaje")
                  if available else f"falta el GGUF del perfil {st['active_profile']}")
        names = [n for n in eolas_v2.available_evaluation_profiles() if n != eolas_v2.NEMO_MOE_PROFILE]
        return {"available": available, "detail": detail, "profile": st["active_profile"], "model": st["alias"],
                "loaded": bool(st["running"]), "busy": self._gpu_busy(),
                "profiles": [{"name": n, "alias": eolas_v2.profile_config(n)["alias"]} for n in names]}

    def chat_set_profile(self, body: dict[str, Any]) -> dict[str, Any]:
        """El motor elegido en Eolfi pasa a ser el perfil activo de Eolas V2."""
        from eolfi import eolas_v2

        try:
            eolas_v2.set_active_profile(str(body.get("profile") or ""))
        except (ValueError, FileNotFoundError) as exc:
            raise ApiError(400, str(exc)) from exc
        return self.chat_status()

    def _gpu_busy(self) -> str | None:
        """El banco de motores tiene la GPU: el chat no carga otro modelo encima."""
        for job in list(self.jobs.values()):
            if job.get("kind") == "eolas-e2e" and job.get("status") in ("queued", "running"):
                return "El banco de motores está usando la GPU; el chat estará disponible cuando termine."
        return None

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        """Chat del panel: el modelo de Eolas V2 decide qué herramientas de Eolfi usar y responde con sus resultados."""
        from eolfi import chat, eolas_v2
        from eolfi.mcp_server import EolfiMCP

        try:
            messages = chat.validate_messages(body.get("messages"))
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        raw = body.get("attachments") or []
        if not isinstance(raw, list) or len(raw) > chat.MAX_ATTACHMENTS:
            raise ApiError(400, f"attachments: hasta {chat.MAX_ATTACHMENTS} archivos")
        attachments = []
        for att in raw:
            up = att.get("upload") if isinstance(att, dict) else None
            if not isinstance(up, str) or not re.fullmatch(r"[0-9a-f]{64}", up):
                raise ApiError(400, "adjunto inválido")
            path = self.samples / f"{up}.bin"
            if not path.is_file():
                raise ApiError(404, "adjunto no encontrado: vuelve a adjuntarlo")
            attachments.append({"name": str(att.get("name") or "adjunto")[:200], "path": str(path),
                                "kind": "binario" if att.get("kind") == "binario" else "archivo"})
        analyze = body.get("analyze") or None
        if analyze is not None:
            kind, target = analyze.get("kind") if isinstance(analyze, dict) else None, str((analyze or {}).get("target") or "").strip()
            if kind not in chat.ANALYSIS_KINDS or not target:
                raise ApiError(400, f"analyze.kind debe ser uno de {', '.join(chat.ANALYSIS_KINDS)} con su destino")
            analyze = {"kind": kind, "target": target}
        try:
            remote = chat.remote_engine()
        except RuntimeError as exc:
            raise ApiError(503, str(exc)) from exc
        busy = None if remote else self._gpu_busy()
        if busy:
            raise ApiError(409, busy)
        # Mismas carpetas permitidas que el resto del panel; los adjuntos viven en samples/.
        roots = [str(r) for r in self.roots] + [str(self.samples)] if self.roots else None
        rea = self._chat_rea(self._case_id(body))
        mcp = chat.Toolbox(EolfiMCP(db=self.db, roots=roots), {
            "eolfi_proponer_proyecto": self._chat_propose_project,
            "eolfi_objetivos": self._chat_subjects,
            "eolfi_casos": lambda _a: {"casos": [{k: c.get(k) for k in ("case_id", "name", "status", "updated_at")}
                                                 for c in self.cases_list({})["cases"][:30]]},
            **(self._chat_rea_composites(rea, self._case_id(body)) if rea is not None else {}),
        }, rea=rea)
        context = chat.with_context(messages, attachments, analyze)
        try:
            return self._chat_answer(context, remote, mcp)
        finally:
            if rea is not None:
                rea.client.close()

    def _chat_rea_composites(self, rea: Any, case_id: str | None = None) -> dict[str, Any]:
        """Herramientas compuestas sobre REA. Con un caso activo, cada resultado queda en él (plan REA, punto 6)."""
        from eolfi import rea_caso, rea_compuestas as rc

        def ruta(a: dict[str, Any]) -> str:
            path = str(a.get("ruta") or "").strip()
            if not path:
                raise ValueError("falta la ruta")
            self._check_root(path, "ruta")
            return path

        def checked_scenario(sc: Any) -> dict[str, Any]:
            if not isinstance(sc, dict):
                raise ValueError("escenario inválido")
            for key in ("ejecutable", "carpeta"):
                value = str(sc.get(key) or "")
                if value and (":" in value[:3] or value.startswith(("/", "\\", "."))):
                    self._check_root(value, "ruta")
            return sc

        def step(msg: str, fn: Any) -> Any:
            self._progress(msg)
            return fn()

        def in_case(operation: str, fn: Any) -> Any:
            def run(a: dict[str, Any]) -> Any:
                result = fn(a)
                if case_id and isinstance(result, dict) and not result.get("autorizacion_pendiente"):
                    s = self.store()
                    try:
                        result["caso"] = rea_caso.registrar(s, case_id, operation, a, result)
                    finally:
                        s.close()
                return result
            return run

        tools = {
            "eolfi_revisar_modelo": lambda a: rc.revisar_modelo(rea.client, ruta(a)),
            "eolfi_explicar_binario": lambda a: step("REA analiza el binario con Ghidra (estático, ~1 min)…",
                                                     lambda: rc.explicar_binario(rea.client, ruta(a), a.get("funciones") or 5)),
            "eolfi_reimplementar_funcion": lambda a: step("REA descompila la función…",
                                                          lambda: rc.reimplementar_funcion(rea.client, ruta(a), str(a.get("funcion") or ""))),
            "eolfi_inventario_dependencias": lambda a: rc.inventario_dependencias(rea.client, ruta(a)),
            "eolfi_api_desde_captura": lambda a: step("REA lee la captura de red…",
                                                      lambda: self._api_from_capture(rea.client, ruta(a))),
            "eolfi_recuperar_fuentes_js": lambda a: step("REA (WSL2) reconstruye las fuentes con Wakaru…",
                                                         lambda: self._recover_js(ruta(a), a.get("destino"))),
            "eolfi_analizar_app_js": lambda a: step("REA analiza la aplicación JavaScript (estático)…",
                                                    lambda: rc.analizar_app_js(rea.client, ruta(a))),
            "eolfi_verificar_comportamiento": lambda a: rc.verificar_comportamiento(
                rea.client, rea.authorizer, checked_scenario(a.get("original")), checked_scenario(a.get("reconstruccion"))),
            "eolfi_comparar_versiones": lambda a: step("REA compara las dos versiones (estático, ~1-2 min)…",
                                                       lambda: rc.comparar_versiones(rea.client, ruta({"ruta": a.get("original")}),
                                                                                     ruta({"ruta": a.get("nueva")}))),
        }
        names = {"eolfi_revisar_modelo": "revisar_modelo", "eolfi_explicar_binario": "explicar_binario",
                 "eolfi_reimplementar_funcion": "reimplementar_funcion", "eolfi_comparar_versiones": "comparar_versiones",
                 "eolfi_inventario_dependencias": "inventario_dependencias",
                 "eolfi_verificar_comportamiento": "verificar_comportamiento", "eolfi_analizar_app_js": "analizar_app_js",
                 "eolfi_recuperar_fuentes_js": "recuperar_fuentes_js", "eolfi_api_desde_captura": "api_desde_captura"}
        return {name: in_case(names[name], fn) for name, fn in tools.items()}

    def _api_from_capture(self, client: Any, path: str) -> dict[str, Any]:
        """Nivel completo si hay tshark en WSL (REA de Linux); si no, el básico con el REA de Windows."""
        from eolfi import rea_client, rea_compuestas as rc

        cmd = rea_client.wsl_rea_command() if rea_client.wsl_has_tshark() else None
        if not cmd:
            return rc.api_desde_captura(client, path)
        fields = rea_client.ReaClient(cmd, timeout=600)
        try:
            return rc.api_desde_captura(client, path, fields_client=_WslPaths(fields))
        finally:
            fields.close()

    def _recover_js(self, path: str, destino: Any = None) -> dict[str, Any]:
        """Recuperar fuentes JavaScript con el REA de WSL2 (Wakaru solo funciona en Linux x64)."""
        from eolfi import rea_client, rea_compuestas as rc

        cmd = rea_client.wsl_rea_command()
        if not cmd:
            raise RuntimeError("REA de WSL2 no instalado: ejecuta tools/instalar-rea-wsl.sh dentro de Ubuntu")
        if destino:
            dest = str(destino)
            self._check_root(dest, "carpeta destino")
        else:
            dest = str(self.samples / "recuperado" / f"{Path(path).stem}-{time.strftime('%Y%m%d-%H%M%S')}")
        client = rea_client.ReaClient(cmd, timeout=600)
        try:
            return rc.recuperar_fuentes_js(client, path, dest)
        finally:
            client.close()

    def _rea_db(self) -> Any:
        """Conexión a eolfi.db para las autorizaciones de REA (quien la pide la cierra)."""
        return self.store().conn

    def _chat_rea(self, case_id: str | None = None) -> Any:
        """REA para Eolas V2: catálogo completo; lo que ejecuta solo con permiso del titular para el caso activo
        (plan punto 2); rutas dentro de las carpetas permitidas."""
        from eolfi import rea_autorizacion, rea_client

        if not rea_client.rea_command():
            return None
        try:
            self._progress("Conectando REA…")
            return rea_client.ReaTools(rea_client.ReaClient(), check_path=lambda p: self._check_root(p, "ruta"),
                                       authorizer=rea_autorizacion.Authorizer(self._rea_db, case_id))
        except Exception as exc:  # noqa: BLE001 — sin REA el chat sigue con las herramientas de Eolfi
            self._progress(f"REA no disponible: {exc}")
            return None

    # -- autorizaciones de REA: SOLO el titular, desde el panel ------------------------------------------------
    def rea_authorizations(self, q: dict[str, str]) -> dict[str, Any]:
        from eolfi import rea_autorizacion

        return rea_autorizacion.overview(self._rea_db, q.get("caso") or None)

    def rea_decide(self, request_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi import rea_autorizacion

        try:
            return rea_autorizacion.decide(self._rea_db, request_id, str(body.get("decision") or ""))
        except KeyError as exc:
            raise ApiError(404, str(exc).strip("'")) from exc
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

    def rea_revoke(self, grant_id: str) -> dict[str, Any]:
        from eolfi import rea_autorizacion

        try:
            return rea_autorizacion.revoke(self._rea_db, grant_id)
        except KeyError as exc:
            raise ApiError(404, str(exc).strip("'")) from exc

    def _chat_answer(self, context: list[dict[str, str]], remote: Any, mcp: Any) -> dict[str, Any]:
        from eolfi import chat, eolas_v2

        try:
            if remote:
                self._progress(f"Consultando {remote['label']}…")
                return {**chat.agent_turn(context, remote, mcp, self._progress), "model": remote["label"]}
            profile = str(eolas_v2.load_config()["active_profile"])
            self._progress(f"Cargando el motor Eolas V2 ({profile})…")
            with eolas_v2.inference_profile(profile) as c:
                engine = chat.local_engine(c)
                self._progress(f"Eolas ({c['alias']}) está pensando…")
                return {**chat.agent_turn(context, engine, mcp, self._progress), "model": engine["label"]}
        except RuntimeError as exc:
            raise ApiError(502, str(exc)) from exc

    def _chat_propose_project(self, a: dict[str, Any]) -> dict[str, Any]:
        """Herramienta del chat: propone el plan (caso + evaluación). No ejecuta: el usuario lo aprueba en el panel."""
        fuentes = a.get("fuentes") or []
        if not isinstance(fuentes, list) or not all(isinstance(x, str) for x in fuentes):
            raise ValueError("fuentes debe ser una lista de textos")
        state = self.project_plan({"name": str(a.get("nombre") or "").strip(), "description": str(a.get("descripcion") or ""),
                                   "sources": fuentes, "mode": "guided" if a.get("modo") == "guiado" else "auto"})
        return {"case_id": state.get("case_id"), "estado": state.get("status"), "plan": state.get("plan"),
                "aviso": "El plan NO se ejecuta hasta que el usuario lo revise y lo apruebe en el panel."}

    def _chat_subjects(self, a: dict[str, Any]) -> dict[str, Any]:
        wanted = str(a.get("buscar") or "").casefold()
        rows = [r for r in self.subjects({})["subjects"]
                if not wanted or wanted in " ".join([*(r.get("names") or []), str(r.get("format") or ""), r["subject"]]).casefold()]
        return {"objetivos": [{k: r.get(k) for k in ("subject", "names", "kind", "format", "evidence", "open_incognitas")}
                              for r in rows[:30]], "total": len(rows)}

    def local_chat_workspace(self, _q=None):
        from eolfi.vscode_tools import vscode_action
        from eolfi.generador.llm import LLMError
        try:
            return vscode_action("workspace", timeout=4)
        except LLMError as exc:
            raise ApiError(503, "Abre VS Code e vincula a extensión de Eolfi.") from exc

    def local_chat_send(self, body):
        from eolfi.generador.llm import LLMError, _post, read_vscode_bridge
        prompt, project = body.get("prompt"), body.get("project")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000 or not isinstance(project, str):
            raise ApiError(400, "Mensaxe ou proxecto inválido.")
        try:
            bridge = read_vscode_bridge()
            return _post(bridge["url"] + "/v1/local-chat", {"prompt": prompt, "project": project},
                         {"Authorization": "Bearer " + bridge["token"]}, 900, retries=0)
        except LLMError as exc:
            raise ApiError(502, str(exc)) from exc

    def vscode_activity(self, _q=None) -> dict[str, Any]:
        with self._vscode_activity_lock, self._activity_store() as conn:
            rows = conn.execute("SELECT payload FROM vscode_activity ORDER BY updated DESC LIMIT 10")
            return {"activity": [json.loads(row[0]) for row in rows]}

    def update_vscode_activity(self, body: dict[str, Any]) -> dict[str, Any]:
        run_id = str(body.get("run_id") or "")
        phase = str(body.get("phase") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", run_id) or phase not in ("start", "progress", "done", "error"):
            raise ApiError(400, "run_id o phase inválido")
        from eolfi.security.privacy import redact
        message = redact(str(body.get("message") or "")[:500])[0]
        label = redact(str(body.get("label") or "Chat de Eolfi")[:120])[0]
        now = time.time()
        with self._vscode_activity_lock, self._activity_store() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM vscode_activity WHERE run_id = ?", (run_id,)).fetchone()
            run = json.loads(row[0]) if row else None
            if phase == "start":
                run = {"run_id": run_id, "label": label, "status": "running", "started": now, "log": []}
            elif run is None:
                raise ApiError(404, "actividad de VS Code no encontrada")
            if phase == "progress" and message:
                run["log"].append({"t": round(now - run["started"], 1), "msg": message})
            elif phase in ("done", "error"):
                run["status"] = "done" if phase == "done" else "error"
                run["finished"] = now
                if message:
                    run["log"].append({"t": round(now - run["started"], 1), "msg": message})
            run["updated"] = now
            del run["log"][:-100]
            conn.execute("INSERT INTO vscode_activity VALUES (?, ?, ?) "
                         "ON CONFLICT(run_id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload",
                         (run_id, now, json.dumps(run, ensure_ascii=False)))
            conn.execute("DELETE FROM vscode_activity WHERE run_id IN "
                         "(SELECT run_id FROM vscode_activity ORDER BY updated DESC LIMIT -1 OFFSET 20)")
            return {"activity": run}

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
        # El motor V1 de CeltIA vive en 11435 y puede no estar instalado. Si no
        # se ha pedido expresamente otro, el panel prefiere Eolas V2, que gestiona
        # un único llama-server y el perfil local activo (Gemma Q4 por defecto).
        selected_ai = os.environ.get("EOLFI_DEFAULT_AI")
        if not selected_ai and any(row["name"] == "ia:eolas-v2" and row["available"] for row in ia_rows):
            selected_ai = "eolas-v2"
        # La elección se aplica una vez por versión de arranque; después el panel
        # respeta el selector que el usuario haya guardado en este navegador.
        if selected_ai:
            out["default_ai"] = selected_ai
            out["boot"] = os.environ.get("EOLFI_BOOT_ID", "eolas-v2-q4")
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
                                providers=body.get("providers"), case_id=self._case_id(body),
                                provenance=f"subida desde el panel: {str(body.get('name') or 'upload')[:200]}")
        path = body.get("path")
        if not isinstance(path, str) or not path:
            raise ApiError(400, "falta 'path'")
        self._check_root(path, "archivo")
        if Path(path).is_dir():
            # Una carpeta en «Binario»: se analiza como repositorio/carpeta (código, pila, estructura).
            self._progress(f"{path} es una carpeta: se analiza como repositorio")
            rep = self.learn("repo", {"source": path, "case_id": body.get("case_id")})
            rep.setdefault("analyzed_as", "repo")
            return rep
        if not Path(path).is_file():
            raise ApiError(404, f"no existe el archivo ni la carpeta: {path}")
        return self._triage(path, body.get("mode", "default"), name=Path(path).name, providers=body.get("providers"),
                            case_id=self._case_id(body))

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

    def _triage(self, path: str, mode: str, name: str, providers: Any = None, case_id: str | None = None,
                provenance: str = "") -> dict[str, Any]:
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
                rep = tf.run_triage(path, s, provs, isolate=self.isolate, case_id=case_id, provenance=provenance)
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
        case_id = self._case_id(body)
        with self._job(f"{kind}:{src.strip()}"):
            s = self.store()
            try:
                if kind == "web":
                    from eolfi.flows.learn_flow import run_web
                    rep = run_web(src.strip(), s, max_assets=max(1, min(int(body.get("max_assets", 40)), 200)),
                                  cross_origin=bool(body.get("cross_origin")), progress=self._progress,
                                  ignore_robots=bool(body.get("ignore_robots")), case_id=case_id)
                else:
                    from eolfi.flows.learn_flow import run_repo
                    rep = run_repo(src.strip(), s, workdir=str(self.samples / "repos"), progress=self._progress,
                                   case_id=case_id)
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
        case_id = self._case_id(body)
        with self._job("create:" + str(Path(out).resolve())):
            s = self.store()
            try:
                rep = create_project([x.strip() for x in sources], s, out, name=name,
                                     target=str(body.get("target") or "auto"), do_verify=True,
                                     force=bool(body.get("force")), workdir=str(self.samples / "repos"),
                                     ai_brief=(str(body["ai_brief"])[:4000] if body.get("ai_brief") else None),
                                     ai_provider=str(body.get("ai_provider") or "eolas-v2"),
                                     ai_model=(str(body["ai_model"]) if body.get("ai_model") else None),
                                     ai_base_url=(str(body["ai_base_url"])[:300] if body.get("ai_base_url") else None),
                                     reanalyze=bool(body.get("reanalyze")),
                                     db="sqlite" if body.get("db") == "sqlite" else "memory",
                                     auth=bool(body.get("auth")), progress=self._progress, case_id=case_id)
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

        case_id = self._case_id(body)
        with self._job("compare"):
            s = self.store()
            try:
                a, b = resolve_subject(s, str(body.get("a", ""))), resolve_subject(s, str(body.get("b", "")))
                if not a or not b:
                    raise ApiError(404, "objetivo no encontrado o ambiguo")
                return compare(s, a, b, case_id=case_id)
            finally:
                s.close()

    # -- crear proyecto con plan razonado y aprobado (eolfi.flows.project_flow) ------------
    def _project(self, fn):
        from eolfi.flows.project_flow import PlanError

        with self.lock:
            s = self.store()
            try:
                return fn(s)
            except PlanError as exc:
                raise ApiError(409 if "no está aprobado" in str(exc) or "pendiente" in str(exc) else 400,
                               str(exc)) from exc
            except ValueError as exc:
                raise ApiError(404 if "no encontrado" in str(exc) else 400, str(exc)) from exc
            finally:
                s.close()

    def project_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.flows.project_flow import propose_plan

        sources = body.get("sources")
        if not isinstance(sources, list):
            raise ApiError(400, "'sources' debe ser una lista")
        for src in sources:
            if isinstance(src, str):
                self._check_local_source(src.strip())
        name = str(body.get("name") or "").strip()
        from eolfi.flows.project_flow import default_out

        out = body.get("out") or default_out(name or "proyecto")
        self._check_root(out, "carpeta destino")
        return self._project(lambda s: propose_plan(s, name=name, description=str(body.get("description") or ""),
                                                    sources=sources, mode=str(body.get("mode") or "auto"), out=out))

    def project_get(self, case_id: str) -> dict[str, Any]:
        from eolfi.flows.project_flow import state

        return self._project(lambda s: state(s, case_id))

    def project_action(self, case_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.flows import project_flow as pf

        if action == "approve":
            v = body.get("version")
            if isinstance(v, bool) or not isinstance(v, int):
                raise ApiError(400, "falta 'version' (entero)")
            return self._project(lambda s: pf.approve_plan(s, case_id, version=v, edits=body.get("edits") or None,
                                                           note=str(body.get("note") or "")))
        if action == "instruction":
            return self._project(lambda s: pf.add_instruction(s, case_id, str(body.get("text") or "")))
        if action == "change":
            return self._project(lambda s: pf.accept_change(s, case_id, accept=body.get("accept") is True))
        raise ApiError(404, "acción desconocida")

    def project_run(self, body: dict[str, Any]) -> dict[str, Any]:
        """Trabajo «project»: sigue el plan aprobado (todo en auto, un paso en guiado), con progreso y cancelación."""
        from eolfi.flows.project_flow import PlanError, run_plan

        case_id = self._case_id(body)
        if not case_id:
            raise ApiError(400, "falta case_id")
        with self._job("project:" + case_id):
            s = self.store()
            try:
                return run_plan(s, case_id, workdir=str(self.samples / "repos"), progress=self._progress)
            except PlanError as exc:
                raise ApiError(409, str(exc)) from exc
            finally:
                s.close()

    def project_upload(self, data: bytes, name: str) -> dict[str, Any]:
        """Guarda un archivo adjunto por su huella (sin analizarlo todavía: el análisis es un paso del plan)."""
        if not data:
            raise ApiError(400, "archivo vacío")
        self.samples.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(data).hexdigest()
        dst = self.samples / f"{sha}.bin"
        if not dst.exists():
            dst.write_bytes(data)
        return {"path": str(dst.resolve()), "sha256": sha, "size": len(data), "name": str(name)[:200]}

    # -- observación de caja negra (mismo estado que `eolfi observe`) --------------------
    def observe_get(self, evidence_id: str) -> dict[str, Any]:
        from eolfi.observe import load_session

        s = self.store()
        try:
            return load_session(s, evidence_id)
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc
        finally:
            s.close()

    def observe_compare(self, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.observe import run_compare

        case_id = self._case_id(body)
        with self._job("observe_compare"):
            s = self.store()
            try:
                tol = body.get("tolerances") or []
                if not isinstance(tol, list) or not all(isinstance(t, str) and len(t) <= 200 for t in tol):
                    raise ApiError(400, "tolerances debe ser una lista de patrones")
                return run_compare(s, str(body.get("a", "")), str(body.get("b", "")), case_id=case_id,
                                   tolerances=tol)
            except ValueError as exc:
                raise ApiError(404 if "no es una sesión" in str(exc) else 400, str(exc)) from exc
            finally:
                s.close()

    def observe_execute(self, action: str, body: dict[str, Any], remote: bool) -> dict[str, Any]:
        """run/replay EJECUTAN el objetivo: solo en modo local y con authorized=true explícito."""
        from eolfi.observe import ScriptError, run_observation, run_replay

        if remote:
            raise ApiError(403, "la observación ejecuta programas: no está disponible en modo remoto")
        if body.get("authorized") is not True:
            raise ApiError(403, "la observación EJECUTA el objetivo: envía authorized=true para confirmarlo")
        variables = body.get("variables") or {}
        if not isinstance(variables, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                      for k, v in variables.items()):
            raise ApiError(400, "variables debe ser un objeto de textos")
        case_id = self._case_id(body)
        with self._job("observe"):
            s = self.store()
            try:
                if action == "replay":
                    return run_replay(s, str(body.get("evidence_id", "")), authorized=True, variables=variables,
                                      case_id=case_id)
                script = body.get("script")
                if isinstance(script, str):
                    self._check_root(script, "guion")
                elif not isinstance(script, dict):
                    raise ApiError(400, "falta 'script' (ruta del guion u objeto)")
                elif "target" in script and isinstance(script["target"], dict):
                    self._check_root(str(script["target"].get("path", "")), "objetivo")
                return run_observation(script, s, authorized=True, variables=variables, case_id=case_id,
                                       provenance=str(body.get("provenance", "")))
            except (ScriptError, FileNotFoundError) as exc:
                raise ApiError(400, str(exc)) from exc
            except ValueError as exc:
                raise ApiError(404 if "no es una sesión" in str(exc) else 400, str(exc)) from exc
            finally:
                s.close()

    # -- casos de análisis (mismo estado que la CLI y el agente de VS Code) ----------
    def _case_id(self, body: dict[str, Any]) -> str | None:
        """case_id opcional de un trabajo: se valida antes de empezar a trabajar."""
        cid = body.get("case_id")
        if cid in (None, ""):
            return None
        if not isinstance(cid, str) or not _CASE_ID.fullmatch(cid):
            raise ApiError(400, "case_id inválido")
        s = self.store()
        try:
            from eolfi.core.cases import CaseStore
            CaseStore(s)._require(cid)
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc
        finally:
            s.close()
        return cid

    def _cases(self, fn):
        from eolfi.core.cases import CaseStore

        with self.lock:
            s = self.store()
            try:
                return fn(CaseStore(s), s)
            except ValueError as exc:
                raise ApiError(404 if "no encontrado" in str(exc) else 400, str(exc)) from exc
            finally:
                s.close()

    def cases_list(self, _q) -> dict[str, Any]:
        return {"cases": self._cases(lambda c, _s: c.list())}

    def case_create(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._cases(lambda c, _s: c.create(body.get("name", ""), body.get("description", "")))

    def case_get(self, case_id: str) -> dict[str, Any]:
        case = self._cases(lambda c, _s: c.get(case_id))
        case["evidence"] = _decode_rows(case["evidence"], ("params", "result", "links"))
        case["incognitas"] = _decode_rows(case["incognitas"], ("evidence_for", "evidence_against", "depends_on"))
        with self._jobs_guard:   # progreso de los trabajos de este caso que siguen vivos
            case["jobs"] = [{k: j[k] for k in self._JOB_FIELDS + ("case_id",) if k in j} | {"log": j["log"][-20:]}
                            for j in reversed(list(self.jobs.values())) if j.get("case_id") == case_id]
        return case

    def case_associate(self, case_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from eolfi.flows.create_flow import resolve_subject

        ref, prov = body.get("subject"), body.get("provenance", "")
        if not isinstance(ref, str) or not ref.strip() or not isinstance(prov, str):
            raise ApiError(400, "falta 'subject' (sha256, nombre o ruta ya analizada)")

        def run(c, s):
            subject = resolve_subject(s, ref.strip())
            if not subject:
                raise ApiError(404, f"objetivo no encontrado o ambiguo: {ref[:120]}")
            return c.associate(case_id, subject, provenance=prov)
        return self._cases(run)

    def case_record(self, case_id: str, body: dict[str, Any]) -> dict[str, Any]:
        kind, payload = body.get("kind"), body.get("payload")
        if not isinstance(kind, str) or not isinstance(payload, dict):
            raise ApiError(400, "kind (texto) y payload (objeto) son obligatorios")
        rid = self._cases(lambda c, _s: c.add_record(case_id, kind, payload))
        return {"case_id": case_id, "record_id": rid, "kind": kind}

    def case_export(self, case_id: str) -> dict[str, Any]:
        return self._cases(lambda c, _s: c.package(case_id))

    def case_import(self, body: dict[str, Any]) -> dict[str, Any]:
        import tempfile

        pkg = body.get("package")
        if not isinstance(pkg, dict):
            raise ApiError(400, "falta 'package' (el JSON exportado del caso)")
        name = re.sub(r"[^\w.-]", "_", str(body.get("name") or "caso-importado.json"))[-80:] or "caso.json"
        with tempfile.TemporaryDirectory(prefix="eolfi-caso-") as tmp:
            path = Path(tmp) / name
            path.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
            created = self._cases(lambda c, _s: c.import_case(path))
        return {"imported": created, "case_id": pkg.get("case", {}).get("case_id")}

    def case_report(self, case_id: str) -> str:
        from eolfi.core.case_report import build_case_report, render_case_html

        return render_case_html(build_case_report(self._cases(lambda c, _s: c.get(case_id))))

    # -- puente de chats web (DeepSeek / Gemini / Meta AI) ----------------
    # El token del puente se queda en el servidor: el navegador nunca lo ve. 14/11/2026: ChatGPT, Copilot y Le Chat
    # retirados por decisión del titular (sus adaptadores del puente siguen en eolfi/bridge: ver REGISTRO_LIMPIEZA).
    BRIDGE_SITES = ("deepseek", "gemini", "meta")

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
            try:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                extra = dict(extra or {})
                self.send_header("Content-Security-Policy", extra.pop("Content-Security-Policy", _CSP))
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
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Cerrar la pestaña durante una petición AJAX es normal; no es un error del servidor.
                self.close_connection = True

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
                        "/api/vscode/activity": app.vscode_activity,
                        "/api/local-chat/workspace": app.local_chat_workspace, "/api/chat/estado": app.chat_status,
                        "/api/rea/autorizaciones": app.rea_authorizations,
                        "/api/eolas/perfiles": lambda _q: {"perfiles": __import__("eolfi.eolas_v2", fromlist=["x"]).available_evaluation_profiles()},
                        "/api/eolas/lecciones": lambda _q: __import__("eolfi.eolas_v2", fromlist=["x"]).lessons_report(),
                    }
                    if path in routes:
                        return self._json(200, routes[path](q))
                    if path == "/api/cases":
                        return self._json(200, app.cases_list(q))
                    m = re.fullmatch(r"/api/cases/([0-9a-f-]{36})(/report|/export)?", path)
                    if m and _CASE_ID.fullmatch(m.group(1)):
                        if m.group(2) == "/report":
                            extra = {"Content-Security-Policy": _REPORT_CSP}
                            if q.get("download") == "1":
                                extra["Content-Disposition"] = f'attachment; filename="eolfi-caso-{m.group(1)[:8]}.html"'
                            return self._send(200, app.case_report(m.group(1)).encode("utf-8"),
                                              "text/html; charset=utf-8", extra)
                        if m.group(2) == "/export":
                            return self._json(200, app.case_export(m.group(1)), {
                                "Content-Disposition": f'attachment; filename="eolfi-caso-{m.group(1)[:8]}.json"'})
                        return self._json(200, app.case_get(m.group(1)))
                    m = re.fullmatch(r"/api/projects/([0-9a-f-]{36})", path)
                    if m and _CASE_ID.fullmatch(m.group(1)):
                        return self._json(200, app.project_get(m.group(1)))
                    m = re.fullmatch(r"/api/observe/([0-9a-f]{64})", path)
                    if m:
                        return self._json(200, app.observe_get(m.group(1)))
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
                    if path == "/api/local-chat/send":
                        if self.client_address[0] not in _LOOPBACK:
                            raise ApiError(403, "Chat local limitado a este equipo.")
                        return self._json(200, app.local_chat_send(self._obj()))
                    if path == "/api/vscode/activity":
                        if self.headers.get("X-Eolfi-Client") != "vscode":
                            raise ApiError(403, "solo la extensión vinculada de VS Code puede publicar actividad")
                        return self._json(200, app.update_vscode_activity(self._obj()))
                    if path == "/api/triage":
                        body = self._obj()
                        return self._json(200, app.triage_path(body))
                    if path in ("/api/web", "/api/repo"):
                        return self._json(200, app.learn(path.rsplit("/", 1)[1], self._obj()))
                    if path == "/api/jobs":
                        return self._json(202, app.start_job(self._obj()))
                    if path == "/api/eolas/lecciones":
                        from eolfi import eolas_v2 as _ev2

                        body = self._obj()
                        return self._json(200, _ev2.set_lesson_active(str(body.get("profile") or ""),
                                                                      str(body.get("categoria") or ""),
                                                                      bool(body.get("activa"))))
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
                    if path == "/api/cases":
                        return self._json(201, app.case_create(self._obj()))
                    if path == "/api/cases/import":
                        return self._json(200, app.case_import(self._obj()))
                    m = re.fullmatch(r"/api/cases/([0-9a-f-]{36})/(artifacts|records)", path)
                    if m and _CASE_ID.fullmatch(m.group(1)):
                        fn = app.case_associate if m.group(2) == "artifacts" else app.case_record
                        return self._json(200, fn(m.group(1), self._obj()))
                    m = re.fullmatch(r"/api/rea/autorizaciones/(aut_[0-9a-f]{16})", path)
                    if m:
                        return self._json(200, app.rea_decide(m.group(1), self._obj()))
                    m = re.fullmatch(r"/api/rea/permisos/(perm_[0-9a-f]{16})/revocar", path)
                    if m:
                        return self._json(200, app.rea_revoke(m.group(1)))
                    if path == "/api/chat/motor":
                        return self._json(200, app.chat_set_profile(self._obj()))
                    if path == "/api/projects/plan":
                        return self._json(201, app.project_plan(self._obj()))
                    if path == "/api/projects/upload":
                        return self._json(200, app.project_upload(self._body(), q.get("name", "adjunto")))
                    m = re.fullmatch(r"/api/projects/([0-9a-f-]{36})/(approve|instruction|change)", path)
                    if m and _CASE_ID.fullmatch(m.group(1)):
                        return self._json(200, app.project_action(m.group(1), m.group(2), self._obj()))
                    if path == "/api/observe/compare":
                        return self._json(200, app.observe_compare(self._obj()))
                    if path in ("/api/observe/run", "/api/observe/replay"):
                        return self._json(200, app.observe_execute(path.rsplit("/", 1)[1], self._obj(),
                                                                   bool(getattr(self.server, "token", None))))
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
    # Solo el código Python obliga a reiniciar: el panel (.html/.js/.css) se lee del disco en cada petición. Antes un
    # cambio en app.js reiniciaba el servidor y cortaba el trabajo en curso (12/11/2026, batería de código).
    out = {}
    for p in root.rglob("*.py"):
        if "__pycache__" not in p.parts:
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


def _active_jobs(port: int) -> int | None:
    """Trabajos en marcha o en cola en el servidor hijo; None si no responde (NO significa que no haya ninguno)."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs", timeout=10) as r:
            jobs = json.loads(r.read().decode("utf-8")).get("jobs", [])
        return sum(1 for j in jobs if j.get("status") in ("running", "queued"))
    except Exception:  # noqa: BLE001
        return None


def _wait_jobs_idle(proc: Any, port: int, *, pause: float = 2.0, sleep: Callable[[float], None] | None = None,
                    active: Callable[[int], int | None] | None = None) -> None:
    """Espera a que no quede ningún trabajo antes de recargar. 12/11/2026: una respuesta lenta del servidor durante
    la carga de un motor se tomaba como «0 trabajos» y la recarga mató una ronda de horas y dejó un llama-server
    huérfano. Ahora «sin respuesta» se trata como «ocupado» y hacen falta dos lecturas seguidas de 0."""
    active = active or _active_jobs
    sleep = sleep or time.sleep
    told, idle = False, 0
    while proc.poll() is None and idle < 2:
        n = active(port)
        idle = idle + 1 if n == 0 else 0
        if n != 0 and not told:
            print("eolfi: cambio detectado; hay trabajos en marcha: recargaré al terminar…", flush=True)
            told = True
        if idle < 2:
            sleep(pause)


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
                    # No se corta un trabajo en curso (una batería de motores puede durar una hora): se espera a
                    # que termine y entonces se recarga.
                    port = int(child_argv[child_argv.index("--port") + 1]) if "--port" in child_argv else 8777
                    _wait_jobs_idle(proc, port)
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
