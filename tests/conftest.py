import os

# Las pruebas no dependen del .env del usuario (ni leen sus secretos).
os.environ["EOLFI_NO_DOTENV"] = "1"

# 13/11/2026: lanzadas desde un gancho de git (pre-push), heredaban GIT_DIR/GIT_INDEX_FILE apuntando al repositorio
# de Eolfi, y las pruebas que crean repositorios temporales con «git init/commit/update-ref» escribieron en él (lo
# marcaron como bare y añadieron commits a la rama que se subía). Ninguna prueba ve variables GIT_*.
for _name in [k for k in os.environ if k.upper().startswith("GIT_")]:
    del os.environ[_name]

# Ninguna prueba debe crear ni migrar la base de evidencias real del usuario (~/.eolfi/eolfi.db).
_TMP = __import__("tempfile").mkdtemp(prefix="eolfi-pruebas-")
os.environ.setdefault("EOLFI_DB", os.path.join(_TMP, "eolfi.db"))

# Ni la configuración, ni el estado de ejecución, ni las valoraciones de Eolas V2 del usuario
# (~/.eolfi/eolas-v2*) cambian el resultado de las pruebas ni se escriben desde ellas.
os.environ.setdefault("EOLFI_EOLAS_V2_CONFIG", os.path.join(_TMP, "eolas-v2.json"))
os.environ.setdefault("EOLFI_EOLAS_V2_FEEDBACK", os.path.join(_TMP, "eolas-v2-feedback.jsonl"))
# Ni el registro encadenado de acciones del usuario (~/.eolfi/acciones.jsonl, B8).
os.environ.setdefault("EOLFI_ACCIONES_FILE", os.path.join(_TMP, "acciones.jsonl"))

import pytest


# 19/11/2026: en sandboxes de agentes con la red restringida (Codex en Windows con `network: restricted`), un socket
# de 127.0.0.1 enlaza y escucha, pero `connect` falla con WinError 10013 / EACCES. Las pruebas HTTP locales caen
# entonces en cascada y parecen fallos del producto. Se sondea una vez y se avisa en la cabecera y en el resumen;
# ninguna prueba se omite ni cambia su resultado (AGENTS.md: no reducir cobertura para obtener un verde).
def _sondeo_loopback():
    """None si 127.0.0.1 acepta conexiones; si no, la excepción observada."""
    import socket

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        with socket.create_connection(servidor.getsockname(), timeout=3):
            pass
        return None
    except OSError as exc:
        return exc
    finally:
        servidor.close()


def _texto_bloqueo(exc):
    return (f"NO VERIFICADO: el entorno bloquea conexiones a 127.0.0.1 ({exc}). Las pruebas HTTP locales fallarán "
            "por el sandbox, no por el producto. Repite el mismo comando con ejecución local autorizada "
            "(en Codex, sandbox_permissions=require_escalated) o en una sesión con red local permitida.")


def pytest_configure(config):
    config._eolfi_loopback = _sondeo_loopback()


def pytest_report_header(config):
    exc = getattr(config, "_eolfi_loopback", None)
    return [_texto_bloqueo(exc)] if exc is not None else ["loopback 127.0.0.1: disponible"]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    exc = getattr(config, "_eolfi_loopback", None)
    if exc is None:
        return
    marcas = ("10013", "EACCES", "Errno 13", "Errno 1]", "PermissionError")
    fallidas = terminalreporter.stats.get("failed", []) + terminalreporter.stats.get("error", [])
    por_socket = sum(1 for r in fallidas if any(m in str(r.longrepr) for m in marcas))
    terminalreporter.section("loopback bloqueado", sep="=", red=True, bold=True)
    terminalreporter.write_line(_texto_bloqueo(exc))
    terminalreporter.write_line(f"Fallos o errores con firma de socket denegado: {por_socket} de {len(fallidas)}.")


@pytest.fixture(autouse=True)
def _eolas_v2_aislado(tmp_path, monkeypatch):
    """Cada prueba con su propia configuración de Eolas V2 (ni la real ni la de otra prueba: perfiles retirados,
    clave de API…) y sin arrancar el REA real del equipo (12/11/2026)."""
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2-prueba.json"))
    monkeypatch.setenv("EOLFI_EOLAS_V2_EVALUATIONS", str(tmp_path / "evaluation-memory.json"))
    monkeypatch.setenv("EOLFI_EOLAS_V2_ADMISION", str(tmp_path / "admision.json"))   # examen de herramientas
    monkeypatch.setenv("EOLFI_ASSIST_MEMORY", str(tmp_path / "assist-verified.jsonl"))
    monkeypatch.setenv("EOLFI_NO_REA", "1")
    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(tmp_path / "acciones.jsonl"))
    monkeypatch.delenv("EOLFI_ACCIONES_FIRMA_AUTO", raising=False)   # B8: la firma automática del equipo no
    monkeypatch.delenv("EOLFI_ACCIONES_CLAVE", raising=False)        # entra en las pruebas
    monkeypatch.setenv("EOLFI_ENCARGOS_VSCODE", str(tmp_path / "encargos-vscode.json"))   # cola de encargos a VS Code
    monkeypatch.setenv("EOLFI_VOZ_CONFIG", str(tmp_path / "voz-prueba.json"))
    # 15/11/2026: el motor local elegido (~/.eolfi/motor-local.json) y la clave de Eolas V1 (runtime/eolas/api.key
    # de CeltIA) son del equipo; las pruebas no los leen. Sin elección, el motor es el predeterminado (eolas-v2).
    monkeypatch.delenv("EOLFI_LOCAL_ENGINE", raising=False)
    monkeypatch.delenv("EOLAS_API_KEY", raising=False)
    monkeypatch.setenv("EOLFI_MOTOR_LOCAL_FILE", str(tmp_path / "motor-local.json"))
    monkeypatch.setenv("EOLAS_HOME", str(tmp_path / "eolas-v1"))
    monkeypatch.setenv("CELTIAIA_HOME", str(tmp_path / "celtiaia"))
    # 16/11/2026: el registro de la automejora (RSI) es del equipo; lo que observan las pruebas va a su carpeta.
    monkeypatch.setenv("EOLFI_RSI_DIR", str(tmp_path / "rsi"))
    monkeypatch.setenv("EOLFI_TELEMETRIA_DIR", str(tmp_path / "telemetria"))
