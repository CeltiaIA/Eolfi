"""Variaciones de entradas, reducción de casos que fallan y repetición determinista (Fase 5).

Para cada requisito de línea de comandos con entrada estándar, genera variantes deterministas de esa entrada
(semilla fija), ejecuta el ORIGINAL y el CANDIDATO con el mismo paso de guion (mismo sandbox y entorno) y compara
el paso. Las variantes que divergen se reducen (ddmin por líneas y luego por caracteres) a una entrada mínima que
sigue divergiendo. Semilla, número de variantes, tolerancias y presupuesto quedan en la evidencia: con los mismos
parámetros se obtienen las mismas variantes.

Solo se ejecuta con autorización explícita y con el original intacto (mismo SHA-256 que en la observación).
"""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Callable

from eolfi.core.cases import case_run, file_identity
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita

PROVIDER = "eolfi.explore"
VERSION = "1.0.0"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def variants_for(data: bytes, n: int, rng: random.Random) -> list[bytes]:
    """Variantes distintas de la entrada original (nunca la propia original), en orden determinista."""
    from eolfi.security.resilience import _mutate

    text = data.decode("utf-8", "replace")
    pool = [b"", data + data, data.upper(), data.lower(), data[::-1], data + b"\n", data.strip(),
            ("x" + text).encode("utf-8"), text.replace(" ", "").encode("utf-8")]
    rng.shuffle(pool)
    out: list[bytes] = []
    seen = {data}
    for v in pool:
        if v not in seen and len(out) < n:
            out.append(v)
            seen.add(v)
    tries = 0
    while len(out) < n and tries < n * 20:
        tries += 1
        v = _mutate(data, rng)
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def ddmin(data: bytes, fails: Callable[[bytes], bool], budget: list[int]) -> bytes:
    """Reducción delta (Zeller): por líneas y después por caracteres, mientras ``fails`` siga siendo cierto."""
    def reduce(parts: list[bytes]) -> list[bytes]:
        n = 2
        while len(parts) >= 2 and budget[0] > 0:
            chunk = max(1, len(parts) // n)
            done = False
            for i in range(0, len(parts), chunk):
                cand = parts[:i] + parts[i + chunk:]
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                if fails(b"".join(cand)):
                    parts, n, done = cand, max(n - 1, 2), True
                    break
            if not done:
                if n >= len(parts):
                    break
                n = min(len(parts), n * 2)
        return parts

    lines = reduce(data.splitlines(keepends=True))
    joined = b"".join(lines)
    return b"".join(reduce([joined[i:i + 1] for i in range(len(joined))]))


def explore(store: EvidenceStore, case_id: str, candidate: str | Path, *, authorized: bool, variants: int = 8,
            seed: int = 1337, max_runs: int = 200, tolerances: list[str] | None = None) -> dict[str, Any]:
    if not authorized:
        raise PermissionError("la exploración EJECUTA el original y el candidato: confirma la autorización")
    if not 1 <= variants <= 100 or not 10 <= max_runs <= 5000:
        raise ValueError("variants entre 1 y 100; max_runs entre 10 y 5000")
    from eolfi.observe.compare import compare_sessions
    from eolfi.observe.session import execute
    from eolfi.observe.script import validate_script
    from eolfi.providers.triage import sha256_file
    from eolfi.spec import latest_spec

    tolerances = list(tolerances or [])
    cand = Path(candidate).resolve()
    if not cand.is_file():
        raise ValueError(f"no existe el candidato: {cand}")
    spec = latest_spec(store, case_id)
    if spec is None:
        raise ValueError("el caso no tiene especificación: ejecuta antes eolfi spec build")
    config = {"seed": seed, "variants": variants, "max_runs": max_runs, "tolerances": tolerances,
              "spec_version": spec["spec_version"]}
    budget = [max_runs]
    with case_run(store, case_id, "explore", {"candidate": str(cand), **config},
                  "exploración de variantes autorizada por el operador") as run:
        results, subjects = [], set()
        for r in spec["requirements"]:
            if r["inputs"]["action"] != "run" or not r.get("source_steps"):
                continue
            eid, step_id = r["source_steps"][0]
            ev = store.get_evidence(eid)
            params, session = json.loads(ev["params"]), json.loads(ev["result"])
            step = next(s for s in params["script"]["steps"] if s["id"] == step_id)
            tgt = session.get("target") or {}
            entry: dict[str, Any] = {"requirement": r["id"], "title": r["title"]}
            if "stdin" not in step:
                results.append({**entry, "status": "skipped", "reason": "el paso no usa entrada estándar"})
                continue
            if not tgt.get("path") or not Path(tgt["path"]).is_file() or sha256_file(Path(tgt["path"])) != tgt.get("sha256"):
                results.append({**entry, "status": "skipped", "reason": "original no disponible o cambiado: "
                                "no se ejecuta otro binario en su lugar"})
                continue
            subjects.add(ev["subject"])
            from eolfi.observe.script import content_bytes

            original = content_bytes(step["stdin"])
            rng = random.Random(f"{seed}:{r['id']}")
            base_dir = Path(params.get("base_dir") or Path.cwd())

            def run_one(path: str, data: bytes) -> dict[str, Any]:
                sc = json.loads(json.dumps(params["script"]))
                sc["steps"] = [{**step, "stdin": {"base64": base64.b64encode(data).decode("ascii")}}]
                sc["target"] = {**{k: v for k, v in sc["target"].items() if k != "sha256"}, "path": path}
                return execute(validate_script(sc), base_dir)

            def diverges(data: bytes) -> list[str]:
                budget[0] -= 2
                a, b = run_one(tgt["path"], data), run_one(str(cand), data)
                cmp = compare_sessions(a, b)
                return sorted({d["aspect"] for d in cmp["differences"]
                               if not any(fnmatch.fnmatchcase(d["aspect"], t) for t in tolerances)})

            tried, failing = [], []
            for v in variants_for(original, variants, rng):
                if budget[0] < 2:
                    break
                aspects = diverges(v)
                tried.append({"sha256": _sha(v), "size": len(v), "divergent": bool(aspects)})
                if aspects:
                    failing.append((v, aspects))
            minimal = []
            for v, aspects in failing[:3]:
                small = ddmin(v, lambda d: budget[0] >= 2 and bool(diverges(d)), budget)
                txt = small.decode("utf-8", "replace") if small.isascii() or _is_utf8(small) else None
                minimal.append({"aspects": aspects, "size": len(small), "sha256": _sha(small),
                                **({"text": txt[:2000]} if txt is not None else
                                   {"base64": base64.b64encode(small[:2000]).decode("ascii")})})
            results.append({**entry, "status": "explored", "variants": tried,
                            "divergent": sum(t["divergent"] for t in tried), "minimal_failing": minimal})
            if minimal:
                store.add_incognita(Incognita(subject=ev["subject"], severity="medium", question=(
                    f"Exploración: el candidato diverge del original con entradas no observadas en {r['id']} "
                    f"({r['title']}); entrada mínima sha256 {minimal[0]['sha256'][:12]} en "
                    f"{', '.join(minimal[0]['aspects'])}.")))
        exhausted = budget[0] < 2
        result = {"candidate": str(cand), "config": config, "requirements": results,
                  "explored": sum(x["status"] == "explored" for x in results),
                  "skipped": sum(x["status"] == "skipped" for x in results),
                  "divergent_variants": sum(x.get("divergent", 0) for x in results),
                  "budget_exhausted": exhausted,
                  "limits": "Variantes limitadas a la entrada estándar de pasos run; repetir con la misma semilla y "
                            "configuración genera las mismas variantes, pero el original puede no ser determinista."}
        sha, info = file_identity(cand)
        evid, _ = store.add_evidence(Evidence(
            subject=sha, provider=PROVIDER, provider_version=VERSION, operation="variation_exploration",
            params={"case_id": case_id, **config}, result=result, authority=Authority.CONTROLLED_REPRO,
            confidence=Confidence.MEDIUM, limitations=result["limits"]))
        if run.active:
            info["metadata"] = {"role": "reconstrucción candidata"}
            run.artifact(sha, **info)
            for s in subjects:
                run.associate(s)
            run.finish(status="partial" if exhausted else "done", evidence_ids=[evid],
                       tools=[{"name": PROVIDER, "version": VERSION, "status": "ran"}],
                       errors=["presupuesto de ejecuciones agotado"] if exhausted else [],
                       result={k: result[k] for k in ("explored", "skipped", "divergent_variants", "budget_exhausted")}
                       | {"config": config})
            result["case_record"] = run.record_id
        result["evidence_id"] = evid
        return result


def _is_utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
