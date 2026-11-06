"""Almacén de evidencias en SQLite (local, consultable).

- evidence_id único: los duplicados se detectan solos.
- Confianza cruzada: dos evidencias de la misma (subject, operation, params) con
  resultado distinto abren una Incognita automáticamente en vez de elegir
  una a ciegas.
- Paquetes de evidencia: export/import en JSON con validación.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from eolfi.core.models import Authority, Confidence, Evidence, Incognita, Status, _canonical

SCHEMA_VERSION = 1

# Columnas permitidas: un paquete importado es DATO no confiable; nunca se
# interpolan nombres de columna que no estén en esta lista.
_EVIDENCE_COLS = (
    "evidence_id", "subject", "provider", "provider_version", "operation",
    "params", "result", "authority", "confidence", "limitations",
    "environment", "links", "created_at",
)
_INCOGNITA_COLS = (
    "incognita_id", "subject", "question", "status", "evidence_for",
    "evidence_against", "depends_on", "severity", "created_at",
)
_EVIDENCE_REQUIRED = (
    "evidence_id", "subject", "provider", "provider_version", "operation",
    "params", "result", "authority", "confidence", "created_at",
)
_INCOGNITA_REQUIRED = ("incognita_id", "subject", "question", "status", "created_at")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    operation TEXT NOT NULL,
    params TEXT NOT NULL,
    result TEXT NOT NULL,
    authority TEXT NOT NULL,
    confidence TEXT NOT NULL,
    limitations TEXT,
    environment TEXT,
    links TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_subject ON evidence(subject);
CREATE INDEX IF NOT EXISTS idx_ev_subj_op ON evidence(subject, operation);
CREATE TABLE IF NOT EXISTS incognita (
    incognita_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_for TEXT,
    evidence_against TEXT,
    depends_on TEXT,
    severity TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inc_subject ON incognita(subject, status);
"""


class EvidenceStore:
    def __init__(self, path: str | Path = "eolfi.db"):
        self.path = str(path)
        # Varias conexiones a la vez (panel con análisis en paralelo): WAL deja leer mientras se
        # escribe, y las escrituras esperan su turno en vez de fallar con «database is locked».
        self.conn = sqlite3.connect(self.path, timeout=60)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=60000")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    # -- escritura -----------------------------------------------------
    def add_evidence(self, ev: Evidence) -> tuple[str, bool]:
        """Devuelve (evidence_id, is_new). Abre una incógnita si hay conflicto."""
        row = ev.to_row()
        self._check_cross_confidence(ev)
        cur = self.conn.execute(
            "SELECT 1 FROM evidence WHERE evidence_id = ?", (row["evidence_id"],)
        )
        is_new = cur.fetchone() is None
        if is_new:
            cols = ",".join(row.keys())
            qs = ",".join(["?"] * len(row))
            self.conn.execute(
                f"INSERT INTO evidence ({cols}) VALUES ({qs})", list(row.values())
            )
            self.conn.commit()
        return row["evidence_id"], is_new

    def _check_cross_confidence(self, ev: Evidence) -> None:
        """Si otra evidencia de la misma (subject, operation, params) discrepa, abre
        una incógnita citando ambas en vez de elegir una a ciegas."""
        cur = self.conn.execute(
            "SELECT evidence_id, provider, provider_version, result FROM evidence "
            "WHERE subject=? AND operation=? AND params=?",
            (ev.subject, ev.operation, _canonical(ev.params)),
        )
        new_result = _canonical(ev.result)
        new_id = ev.evidence_id
        rivals = [
            r for r in cur.fetchall()
            if r["result"] != new_result and r["evidence_id"] != new_id
            # Otra versión del mismo proveedor = re-análisis, no un conflicto entre fuentes.
            and not (r["provider"] == ev.provider and r["provider_version"] != ev.provider_version)
        ]
        if not rivals:
            return
        self.add_incognita(
            Incognita(
                subject=ev.subject,
                question=(
                    f"Conflicto en '{ev.operation}': {ev.provider} discrepa de "
                    f"{', '.join(sorted({r['provider'] for r in rivals}))}; "
                    f"revisar antes de concluir."
                ),
                evidence_for=[new_id],
                evidence_against=[r["evidence_id"] for r in rivals],
                severity="medium",
            )
        )

    def add_incognita(self, inc: Incognita) -> str:
        row = inc.to_row()
        cols = ",".join(row.keys())
        qs = ",".join(["?"] * len(row))
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO incognita ({cols}) VALUES ({qs})", list(row.values())
        )
        if cur.rowcount == 0:
            # Ya existía (misma pregunta sobre el mismo objetivo): se añaden las evidencias nuevas
            # y, si estaba resuelta pero llegan evidencias que no se habían visto, se reabre.
            old = self.conn.execute("SELECT status, evidence_for, evidence_against FROM incognita "
                                    "WHERE incognita_id=?", (row["incognita_id"],)).fetchone()
            if old is not None:
                def merge(a: str, b: list[str]) -> list[str]:
                    base = json.loads(a or "[]")
                    return base + [x for x in b if x not in base]
                ev_for = merge(old["evidence_for"], inc.evidence_for)
                ev_against = merge(old["evidence_against"], inc.evidence_against)
                grew = (len(ev_for), len(ev_against)) != (len(json.loads(old["evidence_for"] or "[]")),
                                                          len(json.loads(old["evidence_against"] or "[]")))
                status = Status.OPEN.value if grew and old["status"] == Status.RESOLVED.value else old["status"]
                self.conn.execute("UPDATE incognita SET evidence_for=?, evidence_against=?, status=? "
                                  "WHERE incognita_id=?", (_canonical(ev_for), _canonical(ev_against), status,
                                                           row["incognita_id"]))
        self.conn.commit()
        return row["incognita_id"]

    def resolve_incognita(self, incognita_id: str, status: Status = Status.RESOLVED) -> bool:
        cur = self.conn.execute(
            "UPDATE incognita SET status=? WHERE incognita_id=?",
            (status.value, incognita_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # -- lectura -------------------------------------------------------
    def list_evidence(self, subject: str | None = None) -> list[dict[str, Any]]:
        if subject:
            cur = self.conn.execute(
                "SELECT * FROM evidence WHERE subject=? ORDER BY created_at, rowid", (subject,)
            )
        else:
            cur = self.conn.execute("SELECT * FROM evidence ORDER BY created_at, rowid")
        return [dict(r) for r in cur.fetchall()]

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_incognitas(
        self, status: Status | None = None, subject: str | None = None
    ) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM incognita", []
        conds = []
        if status:
            conds.append("status=?")
            args.append(status.value)
        if subject:
            conds.append("subject=?")
            args.append(subject)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        cur = self.conn.execute(q + " ORDER BY created_at, rowid", args)
        return [dict(r) for r in cur.fetchall()]

    # -- paquetes de evidencia ----------------------------------------
    def export_package(self, out_path: str | Path) -> None:
        pkg = {
            "schema_version": SCHEMA_VERSION,
            "evidence": self.list_evidence(),
            "incognita": self.list_incognitas(),
        }
        Path(out_path).write_text(
            json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def import_package(self, in_path: str | Path) -> int:
        """Importa un paquete validándolo. Devuelve cuántas evidencias eran nuevas.

        El paquete se trata como dato no confiable: solo columnas conocidas,
        campos obligatorios presentes y evidence_id recalculado coherente.
        """
        p = Path(in_path)
        if p.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError(f"paquete de {p.stat().st_size // 2**20} MB: supera {MAX_PACKAGE_BYTES // 2**20} MB")
        try:
            pkg = json.loads(p.read_text(encoding="utf-8"))
        except RecursionError:
            raise ValueError("paquete con JSON anidado en exceso") from None
        except UnicodeDecodeError:
            raise ValueError("el paquete no está en UTF-8") from None
        if not isinstance(pkg, dict) or pkg.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("schema_version incompatible: reconstruye el paquete")
        ev_rows = [_clean_row(r, _EVIDENCE_COLS, _EVIDENCE_REQUIRED, "evidence")
                   for r in pkg.get("evidence", [])]
        inc_rows = [_clean_row(r, _INCOGNITA_COLS, _INCOGNITA_REQUIRED, "incognita")
                    for r in pkg.get("incognita", [])]
        for r in ev_rows:
            _verify_evidence_id(r)
            _validate_evidence_row(r, Path(in_path).name)
        for r in inc_rows:
            _validate_incognita_row(r)
        # Referencias a evidencias o incógnitas que no existen ni aquí ni en el paquete: se quitan (M18).
        known_ev = {r["evidence_id"] for r in ev_rows} | {
            x[0] for x in self.conn.execute("SELECT evidence_id FROM evidence")}
        known_inc = {r["incognita_id"] for r in inc_rows} | {
            x[0] for x in self.conn.execute("SELECT incognita_id FROM incognita")}
        for r in inc_rows:
            for k, pool in (("evidence_for", known_ev), ("evidence_against", known_ev), ("depends_on", known_inc)):
                if r.get(k) is not None:
                    r[k] = _canonical([x for x in json.loads(r[k]) if x in pool])
        n = 0
        new_ev: list[dict[str, Any]] = []
        existing_inc: list[dict[str, Any]] = []
        with self.conn:  # transacción: todo o nada
            for r in ev_rows:
                if self._insert("evidence", r):
                    n += 1
                    new_ev.append(r)
            for r in inc_rows:
                if not self._insert("incognita", r):
                    existing_inc.append(r)
        # Fuera de la transacción: lo mismo que una evidencia nueva (cruce de confianza) y fusión de las
        # incógnitas que ya existían (antes se ignoraban sus evidencias; M18).
        from types import SimpleNamespace

        for r in new_ev:
            ev = SimpleNamespace(subject=r["subject"], operation=r["operation"], params=json.loads(r["params"]),
                                 result=json.loads(r["result"]), evidence_id=r["evidence_id"],
                                 provider=r["provider"], provider_version=r.get("provider_version") or "")
            self._check_cross_confidence(ev)  # type: ignore[arg-type]
        for r in existing_inc:
            self.add_incognita(Incognita(subject=r["subject"], question=r["question"],
                                         evidence_for=json.loads(r.get("evidence_for") or "[]"),
                                         evidence_against=json.loads(r.get("evidence_against") or "[]"),
                                         severity=r.get("severity") or "info"))
        return n

    def _insert(self, table: str, row: dict[str, Any]) -> int:
        cols = ",".join(row.keys())
        qs = ",".join(["?"] * len(row))
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({qs})", list(row.values())
        )
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()


def _clean_row(
    r: Any, allowed: Iterable[str], required: Iterable[str], kind: str
) -> dict[str, Any]:
    if not isinstance(r, dict):
        raise ValueError(f"{kind}: cada registro debe ser un objeto")
    unknown = set(r) - set(allowed)
    if unknown:
        raise ValueError(f"{kind}: columnas desconocidas {sorted(unknown)}")
    missing = [c for c in required if c not in r]
    if missing:
        raise ValueError(f"{kind}: faltan campos {missing}")
    for k, v in r.items():
        if v is not None and not isinstance(v, (str, int, float)):
            raise ValueError(f"{kind}.{k}: tipo no admitido {type(v).__name__}")
    return {k: r[k] for k in allowed if k in r}


MAX_PACKAGE_BYTES = 256 * 1024 * 1024
_MAX_TIME = 4_102_444_800   # 2100-01-01


def _check_time(r: dict[str, Any], kind: str, rid: Any) -> None:
    """created_at real y en rango: 1e300 tumbaba la exportación STIX y NaN se guardaba como NULL (M16)."""
    import math

    t = r.get("created_at")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= _MAX_TIME:
        raise ValueError(f"{kind} {rid}: created_at inválido {t!r}")


def _validate_evidence_row(r: dict[str, Any], origin: str) -> None:
    """Enums válidos y procedencia visible: la autoridad y la confianza que declara un paquete
    no forman parte de la huella, así que se marcan como «declaradas por el paquete»."""
    if r.get("authority") not in {a.value for a in Authority}:
        raise ValueError(f"evidence {r.get('evidence_id')}: authority inválida {r.get('authority')!r}")
    if r.get("confidence") not in {c.value for c in Confidence}:
        raise ValueError(f"evidence {r.get('evidence_id')}: confidence inválida {r.get('confidence')!r}")
    _check_time(r, "evidence", r.get("evidence_id"))
    for k, kind in (("params", dict), ("links", list)):
        if r.get(k) is None:
            continue
        try:
            v = json.loads(r[k])
        except (TypeError, ValueError):
            raise ValueError(f"evidence {r.get('evidence_id')}.{k}: JSON inválido") from None
        if not isinstance(v, kind) or (kind is list and not all(isinstance(x, str) for x in v)):
            raise ValueError(f"evidence {r.get('evidence_id')}.{k}: tipo inválido")
    for k in ("subject", "provider", "operation", "evidence_id"):
        if not isinstance(r.get(k), str):
            raise ValueError(f"evidence {r.get('evidence_id')}.{k}: debe ser texto")
    try:
        parsed = json.loads(r["result"])
    except (TypeError, ValueError):
        raise ValueError(f"evidence {r.get('evidence_id')}: result no es JSON") from None
    # Objeto o lista (p. ej. web_sourcemaps guarda una lista): lo que el modelo admite al crearla.
    if not isinstance(parsed, (dict, list)):
        raise ValueError(f"evidence {r.get('evidence_id')}: result debe ser un objeto o una lista")
    note = f"[importada de {origin[:80]}: autoridad y confianza declaradas por el paquete, no verificadas aquí]"
    lim = str(r.get("limitations") or "")
    if note not in lim:
        r["limitations"] = (lim + " " + note).strip()


def _validate_incognita_row(r: dict[str, Any]) -> None:
    from eolfi.core.models import Incognita

    if r.get("status") not in {x.value for x in Status}:
        raise ValueError(f"incognita {r.get('incognita_id')}: status inválido {r.get('status')!r}")
    _check_time(r, "incognita", r.get("incognita_id"))
    for k in ("subject", "question", "incognita_id"):
        if not isinstance(r.get(k), str):
            raise ValueError(f"incognita {r.get('incognita_id')}.{k}: debe ser texto")
    for k in ("evidence_for", "evidence_against", "depends_on"):
        if r.get(k) is None:
            continue
        try:
            v = json.loads(r[k])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"incognita {r.get('incognita_id')}.{k}: JSON inválido") from exc
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(f"incognita {r.get('incognita_id')}.{k}: debe ser una lista de ids")
    expected = Incognita(subject=str(r["subject"]), question=str(r["question"])).incognita_id
    if expected != r["incognita_id"]:
        raise ValueError(f"incognita {r['incognita_id']}: id no coincide con su contenido")


def _verify_evidence_id(r: dict[str, Any]) -> None:
    """El evidence_id debe ser la huella de su contenido (detecta manipulación)."""
    import hashlib

    try:
        projection = {
            "provider": r["provider"],
            "subject": r["subject"],
            "operation": r["operation"],
            "params": json.loads(r["params"]),
            "result": json.loads(r["result"]),
        }
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"evidence {r.get('evidence_id')}: JSON inválido") from exc
    expected = hashlib.sha256(_canonical(projection).encode("utf-8")).hexdigest()
    if expected != r["evidence_id"]:
        raise ValueError(f"evidence {r['evidence_id']}: huella no coincide con el contenido")
