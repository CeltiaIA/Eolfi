"""Verificación diferencial: ¿la reimplementación se comporta como el original?

Ejecuta el programa de referencia y el candidato sobre el mismo corpus de
entradas y compara código de salida, stdout y (opcional) stderr. Cada
discrepancia abre una incógnita concreta (entrada + aspecto); cuando una
ejecución posterior coincide, esa incógnita se cierra sola. El resumen se
guarda como evidencia de autoridad controlled_repro.

ATENCIÓN: esto EJECUTA ambos programas con tus permisos. Úsalo solo con
software que puedas ejecutar con seguridad (idealmente en una VM aislada).

Plantilla de comando: el token {input} se sustituye por la ruta de la
entrada; si no aparece, la entrada se pasa por stdin.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import random
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita, Status
from eolfi.flows.triage_flow import environment_string
from eolfi.providers.triage import sha256_file

PROVIDER = "eolfi.diff"
VERSION = "0.1.0"
MAX_CORPUS = 10_000
MAX_CAPTURE = 4 * 1024 * 1024        # lo que se guarda para mostrar diferencias
MAX_OUTPUT = 64 * 1024 * 1024        # lo que se compara: más que esto mata el proceso (M36)


def split_command(cmd: str | list[str]) -> list[str]:
    """Divide un comando respetando comillas en Windows y POSIX."""
    if isinstance(cmd, list):
        return list(cmd)
    if os.name != "nt":
        return shlex.split(cmd)
    lex = shlex.shlex(cmd, posix=True)
    lex.whitespace_split = True
    lex.escape = ""          # en Windows la barra invertida es separador de ruta
    return list(lex)


@dataclass
class RunResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    error: str | None = None
    output_limit: bool = False


def _run(argv: list[str], inp: Path, timeout: float) -> RunResult:
    """Salida a archivos temporales con tope (un programa que escribe GB no agota la RAM)
    y, si se agota el tiempo, se mata el árbol de procesos (los nietos no cuelgan la espera)."""
    import os
    import tempfile as _tf

    uses_path = any("{input}" in a for a in argv)
    args = [a.replace("{input}", str(inp)) for a in argv]
    with _tf.TemporaryFile() as out, _tf.TemporaryFile() as err,             (open(os.devnull, "rb") if uses_path else open(inp, "rb")) as stdin:
        try:
            proc = subprocess.Popen(args, stdin=stdin, stdout=out, stderr=err,
                                    start_new_session=os.name != "nt")
        except OSError as exc:
            return RunResult(None, b"", b"", error=f"{type(exc).__name__}: {exc}")
        import time as _time

        timed_out = over = False
        deadline = _time.monotonic() + timeout
        while True:   # se vigila el tamaño de la salida: un programa que escribe GB no llena el disco
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2 * MAX_OUTPUT:
                    over = True
                elif _time.monotonic() >= deadline:
                    timed_out = True
                if over or timed_out:
                    _kill_tree(proc)
                    proc.wait()
                    break
        over = over or os.fstat(out.fileno()).st_size > MAX_OUTPUT or os.fstat(err.fileno()).st_size > MAX_OUTPUT
        out.seek(0)
        err.seek(0)
        # Se compara la salida completa (antes solo los primeros 4 MB: dos salidas distintas al final
        # salían «equivalentes»).
        stdout, stderr = out.read(MAX_OUTPUT), err.read(MAX_OUTPUT)
    if over:
        return RunResult(None, stdout, stderr, error=f"salida mayor que {MAX_OUTPUT // 2**20} MB", output_limit=True)
    if timed_out:
        return RunResult(None, stdout, stderr, timed_out=True)
    return RunResult(proc.returncode, stdout, stderr)


def _kill_tree(proc: subprocess.Popen) -> None:
    import os
    import signal

    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _normalize(data: bytes, mode: str) -> bytes:
    if mode == "exact":
        return data
    text = data.replace(b"\r\n", b"\n")
    if mode == "lines":
        text = b"\n".join(line.rstrip() for line in text.split(b"\n")).rstrip(b"\n")
    return text


def _short_diff(a: bytes, b: bytes, limit: int = 20) -> list[str]:
    al = a[:MAX_CAPTURE].decode("utf-8", "replace").splitlines()
    bl = b[:MAX_CAPTURE].decode("utf-8", "replace").splitlines()
    out = list(difflib.unified_diff(al, bl, "referencia", "candidato", lineterm="", n=1))
    return out[:limit]


def _collect_corpus(corpus: str | Path) -> list[Path]:
    p = Path(corpus)
    if p.is_file():
        return [p]
    if not p.is_dir():
        raise FileNotFoundError(str(corpus))
    from eolfi.sites.webpage import walk_files

    files = sorted(walk_files(p, limit=MAX_CORPUS + 1))
    if len(files) > MAX_CORPUS:
        raise ValueError(f"corpus de más de {MAX_CORPUS} archivos")
    if not files:
        raise ValueError(f"corpus vacío: {corpus}")
    return files


MAX_INPUT_BYTES = 256 * 1024 * 1024   # entradas más grandes no se cargan enteras en memoria


def _safe_input(inp: Path, argv: list[str], tmp: str) -> Path:
    """Un .bat/.cmd pasa sus argumentos por cmd.exe: una entrada llamada «a&calc.txt» ejecutaría calc. En ese
    caso la entrada se copia con un nombre neutro (B22)."""
    import shutil

    if not argv or not argv[0].lower().endswith((".bat", ".cmd")) or not any("{input}" in a for a in argv):
        return inp
    if not any(c in str(inp) for c in '&|^%<>()"!'):
        return inp
    safe = Path(tmp, "entrada-" + hashlib.sha256(str(inp).encode()).hexdigest()[:16] + inp.suffix[:10])
    if not safe.exists():
        shutil.copyfile(inp, safe)
    return safe


def _file_tokens(argv: list[str]) -> list[Path]:
    return [Path(t) for t in argv if "{input}" not in t and Path(t).is_file()]


def _subject_for(ref_argv: list[str]) -> str:
    """Subject = huella del último archivo local del comando de referencia
    (en 'python ref.py {input}' es ref.py; en './prog' es prog). Si no hay
    ninguno, la huella del propio comando."""
    files = _file_tokens(ref_argv)
    if files:
        return sha256_file(files[-1])
    return "cmd:" + hashlib.sha256(" ".join(ref_argv).encode("utf-8")).hexdigest()


def _fingerprint(argv: list[str]) -> list[str]:
    return [sha256_file(f) for f in _file_tokens(argv)]


def _question(name: str, aspect: str) -> str:
    return f"Diferencial: '{name}' difiere en {aspect} entre referencia y candidato."


def run_diff(
    reference: str | list[str],
    candidate: str | list[str],
    corpus: str | Path,
    store: EvidenceStore,
    *,
    timeout: float = 10.0,
    compare_stderr: bool = False,
    normalize: str = "lines",          # exact | newlines | lines
    threshold: float = 1.0,
    mutate: int = 0,
    seed_value: int = 1337,
    check_determinism: bool = False,
) -> dict[str, Any]:
    if normalize not in ("exact", "newlines", "lines"):
        raise ValueError("normalize debe ser exact, newlines o lines")
    ref_argv, cand_argv = split_command(reference), split_command(candidate)
    if not ref_argv or not cand_argv:
        raise ValueError("los comandos de referencia y candidato no pueden estar vacíos")
    inputs = _collect_corpus(corpus)
    subject = _subject_for(ref_argv)
    env = environment_string()

    with tempfile.TemporaryDirectory(prefix="eolfi-diff-") as tmp:
        # Corpus ampliado por mutación (deterministas con seed_value).
        if mutate:
            from eolfi.security.resilience import _mutate

            rng = random.Random(seed_value)
            extra = []
            for i in range(mutate):
                src = inputs[i % len(inputs)]
                dst = Path(tmp, f"mut{i:05d}_{src.name}")
                dst.write_bytes(_mutate(src.read_bytes(), rng))
                extra.append(dst)
            inputs = inputs + extra

        cases = []
        corpus_hash = hashlib.sha256()
        for inp in inputs:
            if inp.stat().st_size > MAX_INPUT_BYTES:
                cases.append({"input": inp.name, "status": "skipped", "reason": f"más de {MAX_INPUT_BYTES // 2**20} MB"})
                continue
            data_sha = hashlib.sha256(inp.read_bytes()).hexdigest()
            corpus_hash.update(data_sha.encode())
            if inp.parent == Path(tmp):
                name = f"{inp.name} (sha {data_sha[:12]})"
            else:
                # Ruta relativa al corpus: a/x.bin y b/x.bin son entradas distintas (y sus incógnitas también).
                try:
                    name = inp.resolve().relative_to(Path(corpus).resolve()).as_posix()
                except ValueError:
                    name = inp.name
            ref = _run(ref_argv, _safe_input(inp, ref_argv, tmp), timeout)
            aspects: list[str] = []
            detail: dict[str, Any] = {"input": name, "sha256": data_sha}
            if ref.error or ref.timed_out:
                # Sin referencia no hay nada que comparar: el candidato ya no se ejecuta (B22).
                detail["status"] = "reference_error"
                detail["reason"] = ref.error or "timeout"
                cases.append(detail)
                continue
            cand = _run(cand_argv, _safe_input(inp, cand_argv, tmp), timeout)
            if check_determinism:
                again = _run(ref_argv, _safe_input(inp, ref_argv, tmp), timeout)   # también aquí (B22)
                if (again.exit_code, _normalize(again.stdout, normalize)) != (ref.exit_code, _normalize(ref.stdout, normalize)):
                    detail["status"] = "nondeterministic"
                    cases.append(detail)
                    continue
            if cand.error:
                aspects.append("ejecución")
                detail["candidate_error"] = cand.error
            elif cand.timed_out:
                aspects.append("tiempo (timeout)")
            else:
                if ref.exit_code != cand.exit_code:
                    aspects.append("código de salida")
                    detail["exit"] = [ref.exit_code, cand.exit_code]
                if _normalize(ref.stdout, normalize) != _normalize(cand.stdout, normalize):
                    aspects.append("stdout")
                    detail["stdout_diff"] = _short_diff(ref.stdout, cand.stdout)
                if compare_stderr and _normalize(ref.stderr, normalize) != _normalize(cand.stderr, normalize):
                    aspects.append("stderr")
                    detail["stderr_diff"] = _short_diff(ref.stderr, cand.stderr)
            detail["status"] = "mismatch" if aspects else "equivalent"
            detail["aspects"] = aspects
            cases.append(detail)

    # Incógnitas: abrir por discrepancia, cerrar las que ya coinciden.
    all_aspects = ("ejecución", "tiempo (timeout)", "código de salida", "stdout", "stderr")
    opened = closed = 0
    open_ids = {i["incognita_id"] for i in store.list_incognitas(Status.OPEN, subject=subject)}
    for c in cases:
        if c["status"] == "mismatch":
            for a in c["aspects"]:
                store.add_incognita(Incognita(subject=subject, question=_question(c["input"], a), severity="high"))
                opened += 1
        if c["status"] in ("mismatch", "equivalent"):
            for a in all_aspects:
                if a in c.get("aspects", []):
                    continue
                iid = Incognita(subject=subject, question=_question(c["input"], a)).incognita_id
                if iid in open_ids and store.resolve_incognita(iid):
                    closed += 1
        elif c["status"] == "nondeterministic":
            store.add_incognita(Incognita(
                subject=subject,
                question=f"Diferencial: la referencia es no determinista con '{c['input']}'; "
                         f"normaliza la salida o fija la semilla antes de comparar.",
                severity="medium",
            ))

    comparable = [c for c in cases if c["status"] in ("equivalent", "mismatch")]
    eq = sum(1 for c in comparable if c["status"] == "equivalent")
    ratio = round(eq / len(comparable), 4) if comparable else 0.0
    passed = bool(comparable) and ratio >= threshold
    result = {
        "total": len(cases),
        "comparable": len(comparable),
        "equivalent": eq,
        "mismatches": len(comparable) - eq,
        "reference_errors": sum(1 for c in cases if c["status"] == "reference_error"),
        "nondeterministic": sum(1 for c in cases if c["status"] == "nondeterministic"),
        "ratio": ratio,
        "threshold": threshold,
        "passed": passed,
        "mismatched_inputs": [c["input"] for c in cases if c["status"] == "mismatch"][:200],
    }
    ev = Evidence(
        subject=subject,
        provider=PROVIDER,
        provider_version=VERSION,
        operation="differential_verification",
        params={
            "reference": ref_argv, "candidate": cand_argv,
            "reference_files_sha256": _fingerprint(ref_argv),
            "candidate_files_sha256": _fingerprint(cand_argv),
            "corpus_sha256": corpus_hash.hexdigest(), "normalize": normalize,
            "compare_stderr": compare_stderr, "mutate": mutate, "seed": seed_value,
        },
        result=result,
        authority=Authority.CONTROLLED_REPRO,
        confidence=Confidence.HIGH if len(comparable) >= 20 else Confidence.MEDIUM,
        limitations=(
            "La equivalencia solo cubre el corpus probado; entradas no ensayadas "
            "pueden divergir. No compara efectos secundarios (archivos, red, registro)."
        ),
        environment=env,
    )
    eid, _ = store.add_evidence(ev)
    return {
        "subject": subject,
        "evidence_id": eid,
        **result,
        "incognitas_opened": opened,
        "incognitas_closed": closed,
        "cases": [c for c in cases if c["status"] != "equivalent"][:50],
    }
