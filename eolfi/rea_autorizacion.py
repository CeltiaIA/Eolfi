"""Autorización por caso para las herramientas de REA que EJECUTAN o abren algo vivo (13/11/2026, plan punto 2).

AGENTS.md: «No ejecutes el artefacto para obtener cobertura sin autorización». Cuando el modelo necesita una de esas
herramientas (Frida, depuradores, capturas de procesos o navegador, ADB…), Eolfi crea una PETICIÓN y el titular
decide en el panel:
- «una vez»: esa herramienta con esos argumentos exactos, una sola vez;
- «caso»: esa herramienta dentro del caso activo, hasta que se revoque;
- «rechazar».
Solo el titular aprueba (API del panel); el modelo no tiene ninguna herramienta para autorizarse. Cada petición,
decisión y ejecución queda registrada en la base de Eolfi.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Callable

NO_CASE = "sin-caso"
DECISIONS = ("once", "case", "deny")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS rea_requests (id TEXT PRIMARY KEY, case_key TEXT, tool TEXT, args TEXT, args_sha TEXT, "
    "created REAL, status TEXT, decided REAL)",
    "CREATE TABLE IF NOT EXISTS rea_grants (id TEXT PRIMARY KEY, case_key TEXT, tool TEXT, args_sha TEXT, scope TEXT, "
    "created REAL, used REAL, revoked REAL, request_id TEXT)",
    "CREATE TABLE IF NOT EXISTS rea_exec_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, case_key TEXT, tool TEXT, "
    "args TEXT, grant_id TEXT, ok INTEGER)",
)


def args_digest(tool: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class Authorizer:
    """`connect()` devuelve una conexión SQLite (con row_factory) que el llamante cierra con `close()`."""

    def __init__(self, connect: Callable[[], Any], case_key: str | None):
        self.connect = connect
        self.case_key = case_key or NO_CASE

    def _db(self) -> Any:
        conn = self.connect()
        for stmt in SCHEMA:
            conn.execute(stmt)
        return conn

    def peek(self, tool: str, args: dict[str, Any]) -> bool:
        """¿Hay permiso para esta llamada? No consume nada (para operaciones de varias ejecuciones)."""
        digest = args_digest(tool, args)
        conn = self._db()
        try:
            return conn.execute(
                "SELECT 1 FROM rea_grants WHERE case_key=? AND tool=? AND revoked IS NULL AND "
                "(scope='case' OR (scope='once' AND args_sha=? AND used IS NULL)) LIMIT 1",
                (self.case_key, tool, digest)).fetchone() is not None
        finally:
            conn.close()

    def allowed(self, tool: str, args: dict[str, Any]) -> str | None:
        """Id del permiso que cubre esta llamada (consume los de «una vez»), o None."""
        digest = args_digest(tool, args)
        conn = self._db()
        try:
            with conn:
                row = conn.execute(
                    "SELECT id FROM rea_grants WHERE case_key=? AND tool=? AND scope='case' AND revoked IS NULL "
                    "ORDER BY created DESC LIMIT 1", (self.case_key, tool)).fetchone()
                if row:
                    return row[0]
                row = conn.execute(
                    "SELECT id FROM rea_grants WHERE case_key=? AND tool=? AND args_sha=? AND scope='once' "
                    "AND used IS NULL AND revoked IS NULL ORDER BY created LIMIT 1",
                    (self.case_key, tool, digest)).fetchone()
                if row:
                    conn.execute("UPDATE rea_grants SET used=? WHERE id=?", (time.time(), row[0]))
                    return row[0]
            return None
        finally:
            conn.close()

    def request(self, tool: str, args: dict[str, Any]) -> str:
        """Crea (o reutiliza, si ya hay una igual pendiente) una petición de autorización."""
        digest = args_digest(tool, args)
        conn = self._db()
        try:
            with conn:
                row = conn.execute("SELECT id FROM rea_requests WHERE case_key=? AND tool=? AND args_sha=? "
                                   "AND status='pending'", (self.case_key, tool, digest)).fetchone()
                if row:
                    return row[0]
                rid = "aut_" + secrets.token_hex(8)
                conn.execute("INSERT INTO rea_requests VALUES (?,?,?,?,?,?,?,?)",
                             (rid, self.case_key, tool, json.dumps(args, ensure_ascii=False)[:20_000], digest,
                              time.time(), "pending", None))
                return rid
        finally:
            conn.close()

    def log(self, tool: str, args: dict[str, Any], grant_id: str, ok: bool) -> None:
        conn = self._db()
        try:
            with conn:
                conn.execute("INSERT INTO rea_exec_log (ts, case_key, tool, args, grant_id, ok) VALUES (?,?,?,?,?,?)",
                             (time.time(), self.case_key, tool, json.dumps(args, ensure_ascii=False)[:20_000],
                              grant_id, int(ok)))
        finally:
            conn.close()


# -- lo que usa la API del panel (el titular) -------------------------------------------------------------------
def overview(connect: Callable[[], Any], case_key: str | None) -> dict[str, Any]:
    auth = Authorizer(connect, case_key)
    conn = auth._db()
    try:
        pending = [dict(r) for r in conn.execute(
            "SELECT id, case_key, tool, args, created FROM rea_requests WHERE status='pending' ORDER BY created DESC")]
        grants = [dict(r) for r in conn.execute(
            "SELECT id, case_key, tool, scope, created, used FROM rea_grants WHERE revoked IS NULL "
            "AND NOT (scope='once' AND used IS NOT NULL) ORDER BY created DESC")]
        log = [dict(r) for r in conn.execute(
            "SELECT ts, case_key, tool, grant_id, ok FROM rea_exec_log ORDER BY ts DESC LIMIT 20")]
    finally:
        conn.close()
    for p in pending:
        p["args"] = json.loads(p["args"] or "{}")
    return {"pendientes": pending, "permisos": grants, "ejecuciones": log}


def decide(connect: Callable[[], Any], request_id: str, decision: str) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"decisión inválida: usa {', '.join(DECISIONS)}")
    auth = Authorizer(connect, None)
    conn = auth._db()
    try:
        with conn:
            row = conn.execute("SELECT * FROM rea_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise KeyError("petición de autorización no encontrada")
            if row["status"] != "pending":
                raise ValueError("esa petición ya se decidió")
            if decision == "case" and row["case_key"] == NO_CASE:
                raise ValueError("«Permitir en este caso» necesita un caso activo; usa «una vez» o activa un caso")
            now = time.time()
            conn.execute("UPDATE rea_requests SET status=?, decided=? WHERE id=?",
                         ("denied" if decision == "deny" else decision, now, request_id))
            grant = None
            if decision != "deny":
                grant = "perm_" + secrets.token_hex(8)
                conn.execute("INSERT INTO rea_grants VALUES (?,?,?,?,?,?,?,?,?)",
                             (grant, row["case_key"], row["tool"], row["args_sha"] if decision == "once" else None,
                              decision, now, None, None, request_id))
        return {"peticion": request_id, "decision": decision, "permiso": grant, "herramienta": row["tool"],
                "caso": row["case_key"]}
    finally:
        conn.close()


def revoke(connect: Callable[[], Any], grant_id: str) -> dict[str, Any]:
    auth = Authorizer(connect, None)
    conn = auth._db()
    try:
        with conn:
            n = conn.execute("UPDATE rea_grants SET revoked=? WHERE id=? AND revoked IS NULL",
                             (time.time(), grant_id)).rowcount
        if not n:
            raise KeyError("permiso no encontrado o ya revocado")
        return {"permiso": grant_id, "revocado": True}
    finally:
        conn.close()
