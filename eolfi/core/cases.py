"""Casos persistentes que agrupan objetivos, observaciones y resultados de Eolfi.

Un caso reúne artefactos con identidad reproducible (hash de contenido, commit, descriptor o subject
derivado), registros tipados de cada ejecución de flujo (con herramientas, versiones y entorno) y las
evidencias e incógnitas de esos artefactos. Las conclusiones (``claims``) declaran su estado:
``observed`` exige evidencia observada (artefacto o reproducción controlada), ``derived`` exige alguna
evidencia y ``hypothesis`` se conserva como tal: ni exportar ni importar la eleva a hecho.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from eolfi.core.evidence import EvidenceStore

CASE_PACKAGE_VERSION = 2
MAX_RECENT_PROJECTS = 3
RECORD_KINDS = {"analysis", "execution", "observation", "specification", "reconstruction", "comparison"}
FLOW_KINDS = {"triage": "analysis", "web": "analysis", "repo": "analysis",
              "diff": "comparison", "compare": "comparison", "create": "reconstruction",
              "observe": "observation", "replay": "observation", "observe_compare": "comparison",
              "reconstruct": "reconstruction", "equivalence": "comparison",
              "explore": "comparison"}
FLOW_STATUSES = {"done", "partial", "error", "cancelled"}
CLAIM_STATUSES = {"observed", "derived", "hypothesis"}
# Identidad: content = SHA-256 de los bytes; git_commit = commit fijado; descriptor = referencia cuyo contenido
# puede cambiar (URL, carpeta sin git); derived = subject producido por Eolfi (comparación, proyecto, comando).
IDENTITIES = {"content", "git_commit", "descriptor", "derived"}
OBSERVED_AUTHORITIES = {"distributed_artifact", "controlled_repro"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED = re.compile(r"^(url|local|repo|cmd|compare|proyecto|resilience):[^\x00-\x1f]{1,4200}$")
_MAX_RECORD_BYTES = 16 * 1024 * 1024
_ARTIFACT_KEYS_V1 = {"case_id", "subject", "size", "format", "version", "provenance", "path", "platform",
                     "metadata", "added_at"}
_ARTIFACT_KEYS = _ARTIFACT_KEYS_V1 | {"identity", "content_sha256", "tools", "environment"}

_CASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS case_artifacts (
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  subject TEXT NOT NULL, identity TEXT NOT NULL, content_sha256 TEXT NOT NULL, size INTEGER,
  format TEXT NOT NULL, version TEXT NOT NULL, provenance TEXT NOT NULL, path TEXT NOT NULL,
  platform TEXT NOT NULL, tools TEXT NOT NULL, environment TEXT NOT NULL,
  metadata TEXT NOT NULL, added_at REAL NOT NULL,
  PRIMARY KEY(case_id, subject)
);
CREATE TABLE IF NOT EXISTS case_records (
  record_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_records ON case_records(case_id, created_at);
CREATE TABLE IF NOT EXISTS case_imports (
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  package_sha256 TEXT NOT NULL, source_name TEXT NOT NULL, imported_at REAL NOT NULL,
  PRIMARY KEY(case_id, package_sha256)
);
"""


def _json(value: Any, label: str) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: debe ser JSON válido") from None
    if len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
        raise ValueError(f"{label}: supera {_MAX_RECORD_BYTES} bytes")
    return raw


def environment_identity() -> dict[str, str]:
    """Entorno de ejecución reproducible (sin nombre de equipo ni usuario)."""
    from eolfi import __version__

    return {"os": platform.system(), "os_release": platform.release(), "os_version": platform.version()[:200],
            "machine": platform.machine(), "python": platform.python_version(),
            "python_implementation": platform.python_implementation(), "eolfi": __version__}


def valid_subject(subject: Any) -> bool:
    return isinstance(subject, str) and bool(_SHA256.fullmatch(subject) or _PREFIXED.fullmatch(subject))


def _check_tools(tools: Any, label: str = "tools") -> list[dict[str, str]]:
    if not isinstance(tools, list) or len(tools) > 500:
        raise ValueError(f"{label} debe ser una lista")
    for t in tools:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"] \
                or not isinstance(t.get("version", ""), str) or not set(t) <= {"name", "version", "status"} \
                or not isinstance(t.get("status", ""), str):
            raise ValueError(f"{label}: cada herramienta necesita name/version (texto) y status opcional")
    return tools


def _check_environment(env: Any, label: str = "environment") -> dict[str, str]:
    if not isinstance(env, dict) or len(env) > 50 or not all(
            isinstance(k, str) and isinstance(v, str) and len(v) <= 500 for k, v in env.items()):
        raise ValueError(f"{label} debe ser un objeto de textos")
    return env


def _timestamp(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 4_102_444_800:
        raise ValueError(f"{label} inválido")
    return float(value)


def _str_list(value: Any, label: str, limit: int = 100_000) -> list[str]:
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{label} debe ser una lista de textos")
    return value


def _check_payload_shape(kind: str, payload: dict[str, Any]) -> None:
    """Forma tipada: referencias, registros de flujo y conclusiones."""
    _str_list(payload.get("artifacts", []), "payload.artifacts")
    _str_list(payload.get("evidence_ids", []), "payload.evidence_ids")
    if "flow" in payload:
        flow = payload["flow"]
        if flow not in FLOW_KINDS or FLOW_KINDS[flow] != kind:
            raise ValueError(f"payload.flow inválido para kind {kind!r}")
        if payload.get("status") not in FLOW_STATUSES:
            raise ValueError(f"payload.status debe ser uno de {sorted(FLOW_STATUSES)}")
        _check_tools(payload.get("tools", []), "payload.tools")
        _check_environment(payload.get("environment", {}), "payload.environment")
        _str_list(payload.get("errors", []), "payload.errors", 1000)
        for key in ("started_at", "finished_at"):
            if key in payload:
                _timestamp(payload[key], f"payload.{key}")
    claims = payload.get("claims", [])
    if not isinstance(claims, list) or len(claims) > 10_000:
        raise ValueError("payload.claims debe ser una lista")
    for c in claims:
        if not isinstance(c, dict) or not set(c) <= {"text", "status", "evidence_ids", "incognita_ids", "limits"}:
            raise ValueError("cada conclusión admite text, status, evidence_ids, incognita_ids y limits")
        if not isinstance(c.get("text"), str) or not c["text"].strip() or len(c["text"]) > 4000:
            raise ValueError("conclusión sin texto o demasiado larga")
        if c.get("status") not in CLAIM_STATUSES:
            raise ValueError(f"estado de conclusión debe ser uno de {sorted(CLAIM_STATUSES)}")
        _str_list(c.get("evidence_ids", []), "claim.evidence_ids")
        _str_list(c.get("incognita_ids", []), "claim.incognita_ids")
        if not isinstance(c.get("limits", ""), str):
            raise ValueError("claim.limits debe ser texto")


def _check_claims_support(payload: dict[str, Any], authority_of: dict[str, str]) -> None:
    """Una conclusión observada necesita evidencia observada; una derivada, alguna evidencia."""
    for c in payload.get("claims", []):
        ids = c.get("evidence_ids", [])
        if c["status"] == "observed" and not any(authority_of.get(x) in OBSERVED_AUTHORITIES for x in ids):
            raise ValueError("conclusión «observed» sin evidencia observada (artefacto o reproducción controlada): "
                             "decláralo como «derived» o «hypothesis»")
        if c["status"] == "derived" and not ids:
            raise ValueError("conclusión «derived» sin evidencias que la sustenten")


def _evidence_refs(payload: dict[str, Any]) -> set[str]:
    refs = set(payload.get("evidence_ids", []))
    for c in payload.get("claims", []):
        refs.update(c.get("evidence_ids", []))
    return refs


class CaseStore:
    """Almacena casos en la misma SQLite que evidencias/incógnitas."""

    def __init__(self, evidence: EvidenceStore):
        self.evidence = evidence
        self.conn = evidence.conn
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self.conn.executescript(_CASE_SCHEMA)
        self.conn.commit()

    def _migrate(self) -> None:
        """Esquema v1 (solo SHA-256, sin identidad/entorno/herramientas) → v2, conservando las filas."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(case_artifacts)")]
        if not cols or "identity" in cols:
            return
        with self.conn:
            self.conn.execute("ALTER TABLE case_artifacts RENAME TO case_artifacts_v1")
            self.conn.executescript(_CASE_SCHEMA.split("CREATE TABLE IF NOT EXISTS case_records")[0])
            self.conn.execute("""INSERT INTO case_artifacts
              (case_id,subject,identity,content_sha256,size,format,version,provenance,path,platform,tools,
               environment,metadata,added_at)
              SELECT case_id,subject,'content',subject,size,format,version,provenance,path,platform,'[]','{}',
                     metadata,added_at FROM case_artifacts_v1""")
            self.conn.execute("DROP TABLE case_artifacts_v1")

    # -- casos -------------------------------------------------------------
    def create(self, name: str, description: str = "") -> dict[str, Any]:
        if not isinstance(name, str) or not isinstance(description, str):
            raise ValueError("nombre y descripción deben ser texto")
        name = name.strip()
        if not name or len(name) > 240 or len(description) > 20_000:
            raise ValueError("nombre vacío/largo o descripción demasiado larga")
        now, case_id = time.time(), str(uuid.uuid4())
        self.conn.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (case_id, name, description, now, now))
        # El historial del panel es deliberadamente corto: conserva los tres
        # proyectos/casos más recientes y al cuarto libera el más antiguo.
        # Las evidencias globales no se borran; solo su agrupación de historial.
        stale = self.conn.execute("SELECT case_id FROM cases ORDER BY created_at DESC, rowid DESC "
                                  "LIMIT -1 OFFSET ?", (MAX_RECENT_PROJECTS,)).fetchall()
        for row in stale:
            self.conn.execute("DELETE FROM cases WHERE case_id=?", (row[0],))
        self.conn.commit()
        return self.get(case_id)

    def list(self) -> list[dict[str, Any]]:
        out = []
        for row in self.conn.execute("SELECT * FROM cases ORDER BY updated_at DESC, rowid DESC").fetchall():
            case = dict(row)
            cid = case["case_id"]
            subjects = self._subjects(cid)
            case["artifacts"] = len(subjects)
            case["records"] = self.conn.execute("SELECT COUNT(*) FROM case_records WHERE case_id=?",
                                                (cid,)).fetchone()[0]
            case["open_incognitas"] = self._count_open(subjects)
            last = self.conn.execute("SELECT payload FROM case_records WHERE case_id=? "
                                     "ORDER BY created_at DESC, rowid DESC LIMIT 1", (cid,)).fetchone()
            if last:
                p = json.loads(last[0])
                case["last_record"] = {"flow": p.get("flow"), "status": p.get("status")}
            out.append(case)
        return out

    def _subjects(self, case_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT subject FROM case_artifacts WHERE case_id=?", (case_id,))]

    def _count_open(self, subjects: list[str]) -> int:
        n = 0
        for chunk in _chunks(subjects):
            n += self.conn.execute(f"SELECT COUNT(*) FROM incognita WHERE status!='resolved' AND subject IN "
                                   f"({','.join('?' * len(chunk))})", chunk).fetchone()[0]
        return n

    def get(self, case_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise ValueError(f"caso no encontrado: {case_id}")
        case = dict(row)
        case["artifacts"] = [self._artifact_dict(x) for x in self.conn.execute(
            "SELECT * FROM case_artifacts WHERE case_id=? ORDER BY added_at, subject", (case_id,))]
        case["records"] = [self._record_dict(x) for x in self.conn.execute(
            "SELECT * FROM case_records WHERE case_id=? ORDER BY created_at, rowid", (case_id,))]
        case["evidence"], case["incognitas"] = [], []
        for subject in [x["subject"] for x in case["artifacts"]]:
            case["evidence"].extend(self.evidence.list_evidence(subject))
            case["incognitas"].extend(self.evidence.list_incognitas(subject=subject))
        case["imports"] = [dict(x) for x in self.conn.execute(
            "SELECT package_sha256, source_name, imported_at FROM case_imports WHERE case_id=? ORDER BY imported_at",
            (case_id,))]
        return case

    @staticmethod
    def _artifact_dict(row) -> dict[str, Any]:
        out = dict(row)
        for key in ("metadata", "tools", "environment"):
            out[key] = json.loads(out[key])
        return out

    @staticmethod
    def _record_dict(row) -> dict[str, Any]:
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        return out

    # -- artefactos ----------------------------------------------------------
    def add_artifact(self, case_id: str, subject: str, *, size: int | None, format: str,
                     provenance: str, path: str = "", platform: str = "",
                     version: str = "", metadata: dict[str, Any] | None = None,
                     identity: str | None = None, content_sha256: str | None = None,
                     tools: list[dict[str, str]] | None = None,
                     environment: dict[str, str] | None = None) -> bool:
        """Asocia (o completa) un artefacto. Devuelve True si es nuevo en el caso."""
        self._require(case_id)
        if not valid_subject(subject):
            raise ValueError("subject debe ser el SHA-256 hexadecimal del artefacto o un subject de Eolfi "
                             "(url:, local:, repo:, cmd:, compare:, proyecto:)")
        is_sha = bool(_SHA256.fullmatch(subject))
        identity = identity or ("content" if is_sha else "descriptor")
        content_sha256 = (subject if is_sha else "") if content_sha256 is None else content_sha256
        if identity not in IDENTITIES:
            raise ValueError(f"identity debe ser una de {sorted(IDENTITIES)}")
        if content_sha256 and not _SHA256.fullmatch(content_sha256):
            raise ValueError("content_sha256 debe ser un SHA-256 hexadecimal")
        if identity == "content" and not content_sha256:
            raise ValueError("identity «content» requiere content_sha256")
        if is_sha and content_sha256 != subject:
            raise ValueError("un subject SHA-256 debe coincidir con content_sha256")
        if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
            raise ValueError("size debe ser un entero no negativo (o None si se desconoce)")
        for label, value, limit in (("format", format, 120), ("version", version, 200),
                                    ("provenance", provenance, 4000), ("path", path, 4096),
                                    ("platform", platform, 200)):
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"{label} inválido")
        meta = {} if metadata is None else metadata
        if not isinstance(meta, dict):
            raise ValueError("metadata debe ser un objeto")
        tools = _check_tools([] if tools is None else tools)
        env = _check_environment(environment_identity() if environment is None else environment)
        now = time.time()
        old = self.conn.execute("SELECT * FROM case_artifacts WHERE case_id=? AND subject=?",
                                (case_id, subject)).fetchone()
        if old is None:
            self.conn.execute("""INSERT INTO case_artifacts
              (case_id,subject,identity,content_sha256,size,format,version,provenance,path,platform,tools,
               environment,metadata,added_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (case_id, subject, identity, content_sha256, size, format, version, provenance, path, platform,
               _json(tools, "tools"), _json(env, "environment"), _json(meta, "metadata"), now))
        else:
            # Completa lo desconocido y suma herramientas; nunca reescribe una identidad ya fijada.
            o = self._artifact_dict(old)
            merged_tools = o["tools"] + [t for t in tools if t not in o["tools"]]
            self.conn.execute("""UPDATE case_artifacts SET size=?, format=?, version=?, path=?, platform=?,
              provenance=?, tools=?, metadata=? WHERE case_id=? AND subject=?""", (
                o["size"] if o["size"] is not None else size,
                o["format"] if o["format"] not in ("", "unknown") else format,
                o["version"] or version, o["path"] or path, o["platform"] or platform,
                o["provenance"] or provenance, _json(merged_tools, "tools"),
                _json({**meta, **o["metadata"]}, "metadata"), case_id, subject))
        self.conn.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (now, case_id))
        self.conn.commit()
        return old is None

    def associate(self, case_id: str, subject: str, *, provenance: str = "", path: str = "") -> dict[str, Any]:
        """Asocia un objetivo ya analizado; identidad, tamaño, formato y herramientas salen de sus evidencias."""
        info = describe_subject(self.evidence, subject, path=path)
        created = self.add_artifact(case_id, subject, provenance=provenance or "no declarada", **info)
        return {"case_id": case_id, "subject": subject, "created": created, **info}

    # -- registros -------------------------------------------------------------
    def _authorities(self, ids: set[str], subjects: set[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for chunk in _chunks(sorted(ids)):
            for r in self.conn.execute(f"SELECT evidence_id, subject, authority FROM evidence WHERE evidence_id IN "
                                       f"({','.join('?' * len(chunk))})", chunk):
                if r[1] in subjects:
                    out[r[0]] = r[2]
        return out

    def add_record(self, case_id: str, kind: str, payload: dict[str, Any], *, created_at: float | None = None) -> str:
        self._require(case_id)
        if kind not in RECORD_KINDS:
            raise ValueError(f"kind debe ser uno de {sorted(RECORD_KINDS)}")
        if not isinstance(payload, dict):
            raise ValueError("payload debe ser un objeto JSON")
        _check_payload_shape(kind, payload)
        # Referencias declaradas deben existir en este caso; no se aceptan enlaces rotos.
        known_artifacts = set(self._subjects(case_id))
        if not set(payload.get("artifacts", [])) <= known_artifacts:
            raise ValueError("payload contiene artefactos que no pertenecen al caso")
        refs = _evidence_refs(payload)
        authority = self._authorities(refs, known_artifacts)
        if not refs <= set(authority):
            raise ValueError("payload contiene evidence_ids inexistentes o ajenos al caso")
        inc_refs = {x for c in payload.get("claims", []) for x in c.get("incognita_ids", [])}
        known_inc = {i["incognita_id"] for s in known_artifacts for i in self.evidence.list_incognitas(subject=s)}
        if not inc_refs <= known_inc:
            raise ValueError("payload contiene incognita_ids ajenos al caso")
        _check_claims_support(payload, authority)
        ts = time.time() if created_at is None else _timestamp(created_at, "created_at")
        record_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO case_records VALUES(?,?,?,?,?)",
                          (record_id, case_id, kind, _json(payload, "payload"), ts))
        self.conn.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (time.time(), case_id))
        self.conn.commit()
        return record_id

    # -- paquetes ----------------------------------------------------------------
    def export(self, case_id: str, out_path: str | Path) -> None:
        Path(out_path).write_text(json.dumps(self.package(case_id), ensure_ascii=False, indent=2, allow_nan=False),
                                  encoding="utf-8")

    def package(self, case_id: str) -> dict[str, Any]:
        case = self.get(case_id)
        # evidence package keeps the existing, independently versioned format.
        case_data = {k: v for k, v in case.items() if k not in {"evidence", "incognitas", "imports"}}
        return {"case_package_version": CASE_PACKAGE_VERSION, "case": case_data,
                "evidence_package": {"schema_version": 1, "evidence": case["evidence"],
                                     "incognita": case["incognitas"]}}

    def import_case(self, in_path: str | Path) -> bool:
        """Valida el paquete completo antes de incorporarlo; devuelve False si ya existía idéntico."""
        import tempfile
        from eolfi.core.evidence import MAX_PACKAGE_BYTES

        path = Path(in_path)
        if path.stat().st_size > MAX_PACKAGE_BYTES + _MAX_RECORD_BYTES:
            raise ValueError("paquete de caso demasiado grande")
        raw = path.read_bytes()
        try:
            pkg = json.loads(raw.decode("utf-8"))
        except RecursionError:
            raise ValueError("paquete de caso anidado en exceso") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("paquete de caso no es JSON UTF-8 válido") from None
        if not isinstance(pkg, dict) or set(pkg) != {"case_package_version", "case", "evidence_package"}:
            raise ValueError("estructura de paquete de caso inválida")
        version = pkg["case_package_version"]
        if version not in (1, CASE_PACKAGE_VERSION) or isinstance(version, bool):
            raise ValueError("versión de paquete de caso incompatible")
        case = pkg["case"]
        required = {"case_id", "name", "description", "created_at", "updated_at", "artifacts", "records"}
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError("campos del caso inválidos")
        try:
            uuid.UUID(case["case_id"])
        except (ValueError, TypeError, AttributeError):
            raise ValueError("case_id inválido") from None
        if not isinstance(case["name"], str) or not case["name"].strip() or len(case["name"]) > 240:
            raise ValueError("nombre de caso inválido")
        if not isinstance(case["description"], str) or len(case["description"]) > 20_000:
            raise ValueError("descripción de caso inválida")
        for key in ("created_at", "updated_at"):
            _timestamp(case[key], key)
        artifacts = case["artifacts"]
        records = case["records"]
        if not isinstance(artifacts, list) or len(artifacts) > 100_000:
            raise ValueError("lista de artefactos inválida")
        if not isinstance(records, list) or len(records) > 1_000_000:
            raise ValueError("lista de registros inválida")
        subjects: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ValueError("registro de artefacto inválido")
            if version == 1 and set(artifact) == _ARTIFACT_KEYS_V1 and isinstance(artifact.get("subject"), str):
                artifact.update(identity="content", content_sha256=artifact["subject"], tools=[], environment={})
            if set(artifact) != _ARTIFACT_KEYS:
                raise ValueError("registro de artefacto inválido")
            if artifact["case_id"] != case["case_id"] or not valid_subject(artifact["subject"]):
                raise ValueError("identidad de artefacto inválida")
            if version == 1 and not _SHA256.fullmatch(artifact["subject"]):
                raise ValueError("identidad de artefacto inválida")
            if artifact["subject"] in subjects:
                raise ValueError("artefacto duplicado en el caso")
            subjects.add(artifact["subject"])
            if artifact["identity"] not in IDENTITIES or not isinstance(artifact["content_sha256"], str) or (
                    artifact["content_sha256"] and not _SHA256.fullmatch(artifact["content_sha256"])) or (
                    artifact["identity"] == "content" and not artifact["content_sha256"]) or (
                    _SHA256.fullmatch(artifact["subject"]) and artifact["content_sha256"] != artifact["subject"]):
                raise ValueError("identidad de contenido del artefacto inválida")
            size = artifact["size"]
            if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
                raise ValueError("tamaño de artefacto inválido")
            for key, limit in (("format", 120), ("version", 200), ("provenance", 4000),
                               ("path", 4096), ("platform", 200)):
                if not isinstance(artifact[key], str) or len(artifact[key]) > limit:
                    raise ValueError(f"artefacto.{key} inválido")
            if not isinstance(artifact["metadata"], dict):
                raise ValueError("metadata de artefacto debe ser objeto")
            _json(artifact["metadata"], "metadata")
            _check_tools(artifact["tools"], "artefacto.tools")
            _check_environment(artifact["environment"], "artefacto.environment")
            _timestamp(artifact["added_at"], "added_at")
        record_ids: set[str] = set()
        for record in records:
            if not isinstance(record, dict) or set(record) != {"record_id", "case_id", "kind", "payload", "created_at"}:
                raise ValueError("registro de caso inválido")
            try:
                uuid.UUID(record["record_id"])
            except (ValueError, TypeError, AttributeError):
                raise ValueError("record_id inválido") from None
            if record["record_id"] in record_ids or record["case_id"] != case["case_id"]:
                raise ValueError("identidad de registro inválida o duplicada")
            record_ids.add(record["record_id"])
            if not isinstance(record["kind"], str) or record["kind"] not in RECORD_KINDS or not isinstance(record["payload"], dict):
                raise ValueError("tipo o payload de registro inválido")
            _json(record["payload"], "payload")
            _timestamp(record["created_at"], "created_at")
            try:
                _check_payload_shape(record["kind"], record["payload"])
            except ValueError as exc:
                raise ValueError(f"registro {record['record_id']}: {exc}") from None
            if not set(record["payload"].get("artifacts", [])) <= subjects:
                raise ValueError("registro refiere artefactos ajenos al caso")
        evidence_pkg = pkg["evidence_package"]
        if not isinstance(evidence_pkg, dict) or evidence_pkg.get("schema_version") != 1:
            raise ValueError("paquete de evidencias incompatible")
        for kind in ("evidence", "incognita"):
            if not isinstance(evidence_pkg.get(kind), list):
                raise ValueError(f"lista {kind} inválida")
        ev_subjects = {row.get("subject") for row in evidence_pkg["evidence"] if isinstance(row, dict)}
        inc_subjects = {row.get("subject") for row in evidence_pkg["incognita"] if isinstance(row, dict)}
        if not ev_subjects <= subjects or not inc_subjects <= subjects:
            raise ValueError("paquete contiene evidencia no asociada a un artefacto del caso")

        # El importador existente valida huellas, enums, referencias y transacciones de evidencia.
        # Se ejecuta primero en una SQLite efímera; el paquete no se incorpora al almacén real si falla.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            validation_path = Path(temp_dir) / path.name
            validation_path.write_text(json.dumps(evidence_pkg, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            staged = EvidenceStore(":memory:")
            try:
                staged.import_package(validation_path)
            finally:
                staged.close()

            # Referencias de registros y conclusiones: evidencias del paquete o ya existentes de esos artefactos.
            authority = {r["evidence_id"]: r["authority"] for s in subjects for r in self.evidence.list_evidence(s)}
            authority.update({row["evidence_id"]: row["authority"] for row in evidence_pkg["evidence"]
                              if isinstance(row, dict) and row.get("subject") in subjects})
            known_inc = {r["incognita_id"] for s in subjects for r in self.evidence.list_incognitas(subject=s)}
            known_inc.update(row.get("incognita_id") for row in evidence_pkg["incognita"] if isinstance(row, dict))
            for record in records:
                payload = record["payload"]
                if not _evidence_refs(payload) <= set(authority):
                    raise ValueError("registro contiene referencias a evidencias desconocidas")
                if not {x for c in payload.get("claims", []) for x in c.get("incognita_ids", [])} <= known_inc:
                    raise ValueError("registro contiene referencias a incógnitas desconocidas")
                try:
                    _check_claims_support(payload, authority)
                except ValueError as exc:
                    raise ValueError(f"registro {record['record_id']}: {exc}") from None

            existing = self.conn.execute("SELECT 1 FROM cases WHERE case_id=?", (case["case_id"],)).fetchone()
            if existing:
                current = self.package(case["case_id"])["case"]
                if _comparable(current) != _comparable(case):
                    raise ValueError("ya existe un caso con ese id y contenido distinto")
                self.evidence.import_package(validation_path)
                return False
            self.evidence.import_package(validation_path)
            with self.conn:
                self.conn.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (case["case_id"], case["name"],
                    case["description"], case["created_at"], case["updated_at"]))
                for a in artifacts:
                    self.conn.execute("""INSERT INTO case_artifacts
                      (case_id,subject,identity,content_sha256,size,format,version,provenance,path,platform,tools,
                       environment,metadata,added_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        a["case_id"], a["subject"], a["identity"], a["content_sha256"], a["size"], a["format"],
                        a["version"], a["provenance"], a["path"], a["platform"], _json(a["tools"], "tools"),
                        _json(a["environment"], "environment"), _json(a["metadata"], "metadata"), a["added_at"]))
                for r in records:
                    self.conn.execute("INSERT INTO case_records VALUES(?,?,?,?,?)", (r["record_id"], r["case_id"],
                        r["kind"], _json(r["payload"], "payload"), r["created_at"]))
                self.conn.execute("INSERT OR IGNORE INTO case_imports VALUES(?,?,?,?)", (
                    case["case_id"], hashlib.sha256(raw).hexdigest(), path.name[:200], time.time()))
        return True

    def _require(self, case_id: str) -> None:
        if not isinstance(case_id, str) or self.conn.execute(
                "SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is None:
            raise ValueError(f"caso no encontrado: {case_id}")


def _comparable(case: dict[str, Any]) -> dict[str, Any]:
    """Compara contenido sin el updated_at ni las huellas locales de herramientas añadidas después."""
    return {**{k: v for k, v in case.items() if k != "updated_at"},
            "artifacts": [{k: v for k, v in a.items() if k not in {"tools", "environment", "metadata"}}
                          for a in case["artifacts"]]}


def _chunks(items: list[str], size: int = 500) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# -- identidad a partir de evidencias ----------------------------------------------------
def tools_for(store: EvidenceStore, subject: str, evidence_ids: list[str] | None = None) -> list[dict[str, str]]:
    """Herramientas (proveedor + versión) que produjeron las evidencias del objetivo."""
    wanted = set(evidence_ids) if evidence_ids is not None else None
    seen: list[dict[str, str]] = []
    for ev in store.list_evidence(subject):
        if wanted is not None and ev["evidence_id"] not in wanted:
            continue
        t = {"name": ev["provider"], "version": ev["provider_version"] or ""}
        if t not in seen:
            seen.append(t)
    return seen


def describe_subject(store: EvidenceStore, subject: str, *, path: str = "") -> dict[str, Any]:
    """Identidad, tamaño, formato, versión y plataforma de un objetivo según sus evidencias."""
    if not valid_subject(subject):
        raise ValueError(f"subject inválido: {subject[:80]}")
    latest: dict[str, Any] = {}
    for ev in store.list_evidence(subject):
        try:
            latest[ev["operation"]] = json.loads(ev["result"])
        except (TypeError, ValueError):
            continue
    info: dict[str, Any] = {"size": None, "format": "unknown", "version": "", "platform": "", "path": path,
                            "metadata": {}, "tools": tools_for(store, subject)}
    if not latest:
        info["metadata"]["note"] = "sin evidencias registradas para este objetivo"
    h = latest.get("hash")
    if isinstance(h, dict) and isinstance(h.get("size"), int):
        info["size"] = h["size"]
    fmt = latest.get("detect_format")
    if isinstance(fmt, dict) and isinstance(fmt.get("format"), str):
        info["format"] = fmt["format"][:120]
    for key in ("pe_headers", "elf_headers"):
        head = latest.get(key)
        if isinstance(head, dict) and head.get("machine"):
            info["platform"] = str(head["machine"])[:200]
    if _SHA256.fullmatch(subject):
        info.update(identity="content", content_sha256=subject)
    elif subject.startswith("repo:"):
        git = latest.get("repo_git") if isinstance(latest.get("repo_git"), dict) else {}
        commit = (git.get("last_commit") or {}).get("sha") if isinstance(git.get("last_commit"), dict) else None
        info["format"] = "repository"
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40,64}", commit):
            info.update(identity="git_commit", content_sha256="", version=commit)
        else:
            info.update(identity="descriptor", content_sha256="")
            info["metadata"]["note"] = "carpeta sin commit fijado: el contenido puede cambiar"
    elif subject.startswith("local:"):
        index = Path(subject[len("local:"):])
        info["format"] = "html"
        info["path"] = info["path"] or str(index)
        if index.is_file():
            from eolfi.providers.triage import sha256_file

            info.update(identity="content", content_sha256=sha256_file(index), size=index.stat().st_size)
            info["metadata"]["note"] = "hash del HTML principal; los recursos enlazados no se incluyen"
        else:
            info.update(identity="descriptor", content_sha256="")
    elif subject.startswith("url:"):
        fetch = latest.get("web_fetch") if isinstance(latest.get("web_fetch"), dict) else {}
        info.update(identity="descriptor", content_sha256="", format="web")
        if isinstance(fetch.get("bytes"), int):
            info["size"] = fetch["bytes"]
        info["metadata"]["note"] = "contenido remoto: puede variar entre peticiones, usuarios o idioma"
    else:
        info.update(identity="derived", content_sha256="", format=subject.split(":", 1)[0])
    return info


def file_identity(path: str | Path) -> tuple[str, dict[str, Any]]:
    """(sha256, datos de artefacto) de un archivo local: hash, tamaño y formato por bytes mágicos."""
    from eolfi.providers.triage import detect_format, read_head_tail, sha256_file

    p = Path(path)
    sha = sha256_file(p)
    head, _tail = read_head_tail(p)
    fmt, _desc = detect_format(head)
    return sha, {"size": p.stat().st_size, "format": str(fmt)[:120], "path": str(p.resolve()),
                 "identity": "content", "content_sha256": sha,
                 "tools": [{"name": "eolfi.file_identity", "version": "1"}]}


# -- enlace automático de flujos -----------------------------------------------------------
class _NullRun:
    active = False

    def artifact(self, *_a, **_k) -> None:
        return None

    def associate(self, *_a, **_k) -> None:
        return None

    def finish(self, *_a, **_k) -> None:
        return None


class CaseRun:
    """Registro de una ejecución de flujo dentro de un caso (artefactos + resultado tipado)."""
    active = True

    def __init__(self, cases: CaseStore, case_id: str, flow: str, params: dict[str, Any], provenance: str):
        self.cases, self.case_id, self.flow, self.params = cases, case_id, flow, params
        self.provenance = provenance
        self.started = time.time()
        self.subjects: list[str] = []
        self.record_id: str | None = None

    def artifact(self, subject: str, **kw: Any) -> None:
        kw.setdefault("provenance", self.provenance)
        self.cases.add_artifact(self.case_id, subject, **kw)
        if subject not in self.subjects:
            self.subjects.append(subject)

    def associate(self, subject: str, *, path: str = "", provenance: str | None = None) -> None:
        info = describe_subject(self.cases.evidence, subject, path=path)
        self.artifact(subject, provenance=provenance or self.provenance, **info)

    def finish(self, *, status: str, evidence_ids: list[str] | None = None, result: dict[str, Any] | None = None,
               tools: list[dict[str, str]] | None = None, errors: list[str] | None = None,
               claims: list[dict[str, Any]] | None = None) -> str:
        known = set(self.cases._subjects(self.case_id))
        ids = [x for x in dict.fromkeys(evidence_ids or [])]
        authority = self.cases._authorities(set(ids), known)
        if tools is None:
            tools = []
            for s in self.subjects:
                tools += [t for t in tools_for(self.cases.evidence, s, ids) if t not in tools]
        open_inc = self.cases._count_open(self.subjects)
        payload = {"flow": self.flow, "status": status, "params": self.params, "artifacts": self.subjects,
                   "evidence_ids": [x for x in ids if x in authority], "tools": tools,
                   "environment": environment_identity(), "result": result or {}, "errors": errors or [],
                   "open_incognitas": open_inc, "started_at": self.started, "finished_at": time.time()}
        if claims:
            payload["claims"] = claims
        self.record_id = self.cases.add_record(self.case_id, FLOW_KINDS[self.flow], payload)
        return self.record_id


@contextlib.contextmanager
def case_run(store: EvidenceStore, case_id: str | None, flow: str, params: dict[str, Any] | None = None,
             provenance: str = "") -> Iterator[CaseRun | _NullRun]:
    """Sin case_id no hace nada. Con él, comprueba el caso ANTES de trabajar y, si el flujo falla o se cancela,
    deja un registro con estado error/cancelled y los artefactos que ya se habían identificado."""
    if case_id is None or case_id == "":
        yield _NullRun()
        return
    if flow not in FLOW_KINDS:
        raise ValueError(f"flujo desconocido: {flow}")
    cases = CaseStore(store)
    cases._require(case_id)
    run = CaseRun(cases, case_id, flow, _safe_params(params or {}), provenance or "no declarada")
    try:
        yield run
    except BaseException as exc:
        if run.record_id is None:
            status = "error" if isinstance(exc, Exception) else "cancelled"
            try:
                run.finish(status=status, errors=[f"{type(exc).__name__}: {str(exc)[:1000]}"])
            except Exception:  # noqa: BLE001 — el error original es el que importa
                pass
        raise
    if run.record_id is None:
        run.finish(status="error", errors=["el flujo terminó sin registrar su resultado"])


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Parámetros serializables y acotados (sin claves de API ni textos enormes)."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if re.search(r"(key|token|secret|password)", k, re.I):
            continue
        if isinstance(v, str):
            out[k] = v[:2000]
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:2000] for x in list(v)[:200]]
        else:
            out[k] = str(v)[:2000]
    return out
