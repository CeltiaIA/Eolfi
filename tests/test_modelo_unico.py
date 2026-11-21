"""Modelo en un solo sitio (18/11/2026, titular: «que si se cambia el modelo no haya que estar cambiando cosas»).

El modelo se elige en eolas-v2.json: perfil activo, `roles` y perfiles dados de alta. Los perfiles nuevos solo se
activan o reciben un rol si aprobaron el examen de herramientas («los GGUF elegidos deben usar las herramientas de
Eolfi y entender qué hace cada una y cuándo usarlas»).
"""
import json
import re
from pathlib import Path

import pytest

from eolfi import eolas_v2

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "eolas-v2.json"
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(path))
    monkeypatch.setenv("EOLFI_EOLAS_V2_ADMISION", str(tmp_path / "admision.json"))
    monkeypatch.delenv("EOLAS_MODEL", raising=False)
    server = tmp_path / "llama-server.exe"
    server.touch()
    monkeypatch.setattr(eolas_v2, "_server_default", lambda: str(server))
    for name in ("gemma_q4", "gemma"):
        gguf = tmp_path / f"{name}.gguf"
        gguf.write_bytes(b"GGUF")
    path.write_text(json.dumps({"server": str(server), "active_profile": "gemma_q4", "profiles": {
        "gemma_q4": {"model": str(tmp_path / "gemma_q4.gguf")}, "gemma": {"model": str(tmp_path / "gemma.gguf")}}}),
        encoding="utf-8")
    return path


def _nuevo_gguf(tmp_path, nombre="nuevo.gguf", datos=b"GGUF nuevo"):
    gguf = tmp_path / nombre
    gguf.write_bytes(datos)
    return gguf


def test_alta_de_un_gguf_sin_tocar_codigo_y_aparece_en_el_catalogo(cfg_path, tmp_path):
    r = eolas_v2.register_profile("qwen3_q4", str(_nuevo_gguf(tmp_path)), etiqueta="Qwen3 14B Q4", plantilla=None,
                                  extra_args=["-fa", "on", "-np", "1"])
    assert r["alta"] and r["alias"] == "nuevo:latest"
    cfg = eolas_v2.load_config(create=False)
    assert cfg["profiles"]["qwen3_q4"]["etiqueta"] == "Qwen3 14B Q4"
    fila = next(x for x in eolas_v2.catalogo(cfg) if x["perfil"] == "qwen3_q4")
    assert fila["disponible"] and fila["origen"] == "usuario" and fila["examen_obligatorio"]
    assert not fila["admision"]["admitido"]
    assert "qwen3_q4" in eolas_v2.available_evaluation_profiles(cfg)   # entra en la ronda para examinarlo
    with pytest.raises(FileExistsError):
        eolas_v2.register_profile("qwen3_q4", str(_nuevo_gguf(tmp_path)))


@pytest.mark.parametrize("cambio", [
    {"extra_args": ["--host", "0.0.0.0"]}, {"extra_args": ["-ctk", "rm -rf"]}, {"plantilla": "otra"},
    {"reasoning_format": "otro"}, {"model": "relativo.gguf"}, {"model": "C:/x/modelo.bin"}, {"desconocido": 1},
    {"extra_args": ["--override-kv", "dory.num_loops=int:5"]},
    {"extra_args": ["--override-kv", "general.architecture=str:llama"]},
    {"extra_args": ["--override-kv", "dory.num_loops=int:2,tokenizer.chat_template=str:x"]}])
def test_un_perfil_de_usuario_no_admite_opciones_peligrosas_ni_campos_raros(cambio):
    base = {"managed_by": eolas_v2.USER_PROFILE_MARKER, "alias": "a:latest", "model": str(Path.cwd() / "a.gguf"),
            "ctx": 4096, "gpu_layers": 10, "batch": 256, "ubatch": 128}
    eolas_v2._validate_user_profile("mi_modelo", base)
    with pytest.raises(ValueError):
        eolas_v2._validate_user_profile("mi_modelo", {**base, **cambio})


@pytest.mark.parametrize("valor", ["dory.num_loops=int:1", "dory.num_loops=int:4",
                                   "dory.num_loops=int:2,dory.recurrent_kv_cache_mode=str:last_loop"])
def test_un_perfil_de_usuario_admite_los_bucles_de_dory_de_su_ficha(valor):
    base = {"managed_by": eolas_v2.USER_PROFILE_MARKER, "alias": "a:latest", "model": str(Path.cwd() / "a.gguf"),
            "ctx": 4096, "gpu_layers": 10, "batch": 256, "ubatch": 128, "extra_args": ["--override-kv", valor]}
    eolas_v2._validate_user_profile("mi_modelo", base)


def test_un_perfil_nuevo_no_se_activa_ni_recibe_rol_sin_aprobar_el_examen(cfg_path, tmp_path):
    gguf = _nuevo_gguf(tmp_path)
    eolas_v2.register_profile("nuevo", str(gguf))
    with pytest.raises(PermissionError, match="examen"):
        eolas_v2.set_active_profile("nuevo")
    with pytest.raises(PermissionError):
        eolas_v2.set_role("completo", "nuevo")
    cfg = eolas_v2.load_config(create=False)
    # Suspende: sigue sin poder usarse.
    eolas_v2._record_admission({"nuevo": {"aprobado": False, "herramientas_pct": 50, "codigo_primera_pct": 90}}, cfg, "r1")
    assert "no aprobó" in eolas_v2.admitido("nuevo", cfg)["motivo"]
    with pytest.raises(PermissionError):
        eolas_v2.set_active_profile("nuevo")
    # Aprueba: ya puede ser el activo y tener un rol.
    eolas_v2._record_admission({"nuevo": {"aprobado": True, "herramientas_pct": 100, "codigo_primera_pct": 90}}, cfg, "r2")
    assert eolas_v2.set_active_profile("nuevo") == {"active_profile": "nuevo"}
    assert eolas_v2.set_role("completo", "nuevo")["perfil"] == "nuevo"
    assert eolas_v2.rol("completo") == "nuevo"
    # Si el GGUF cambia, hay que examinarlo otra vez y el rol vuelve al perfil activo.
    gguf.write_bytes(b"GGUF distinto y mas largo")
    assert eolas_v2.admitido("nuevo")["motivo"] == "el GGUF cambió desde el examen"
    eolas_v2.set_role("redactor", "gemma")   # los de serie no necesitan examen obligatorio
    with pytest.raises(PermissionError):
        eolas_v2.set_active_profile("nuevo")


def test_un_examen_anterior_a_las_pruebas_actuales_de_herramientas_no_vale(cfg_path, tmp_path):
    eolas_v2.register_profile("nuevo", str(_nuevo_gguf(tmp_path)))
    cfg = eolas_v2.load_config(create=False)
    eolas_v2._record_admission({"nuevo": {"aprobado": True}}, cfg, "r1")
    datos = json.loads(eolas_v2.admission_file().read_text(encoding="utf-8"))
    datos["nuevo"]["casos_herramientas"] = 5   # el examen de antes, sin elegir ni abstenerse
    eolas_v2.admission_file().write_text(json.dumps(datos), encoding="utf-8")
    assert "anterior" in eolas_v2.admitido("nuevo")["motivo"]


def test_roles_de_serie_configurables_y_con_respaldo_al_activo(cfg_path):
    cfg = eolas_v2.load_config(create=False)
    assert eolas_v2.rol("redactor", cfg) == "gemma" and eolas_v2.rol("revisor", cfg) == "gemma_q4"
    assert eolas_v2.rol("rapido", cfg) == "gemma_q4"            # mistral no tiene GGUF aquí: cae en el activo
    assert eolas_v2.rol("rapido", cfg, respaldo=False) == "mistral"
    stored = json.loads(cfg_path.read_text(encoding="utf-8"))
    stored["roles"] = {"redactor": "gemma_q4"}
    stored["celtia_v2_revisor"] = "gemma"                       # clave antigua: sigue valiendo
    cfg_path.write_text(json.dumps(stored), encoding="utf-8")
    from eolfi.generador import llm

    assert llm.celtia_v2_roles(eolas_v2.load_config(create=False)) == ("gemma_q4", "gemma")


def test_el_comportamiento_va_en_el_perfil_no_en_listas_de_nombres(cfg_path):
    cfg = eolas_v2.load_config(create=False)
    assert eolas_v2.is_mistral_profile("nemo_q4", cfg) and not eolas_v2.is_mistral_profile("gemma", cfg)
    assert "--reasoning-format" in eolas_v2.server_args("gemma_q4", cfg)
    assert eolas_v2.etiqueta("gemma", cfg) == "Gemma 4 12B Q5" and eolas_v2.etiqueta("nemo_moe", cfg).endswith("MoE")
    assert not hasattr(eolas_v2, "MISTRAL_PROFILES") and not hasattr(eolas_v2, "THINKING_PROFILES")


def test_el_modelo_de_eolas_v1_sale_de_la_configuracion(cfg_path, monkeypatch):
    from eolfi.generador import llm

    assert llm.eolas_v1_model() == eolas_v2.DEFAULT_CONFIG["eolas_v1_model"]
    stored = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg_path.write_text(json.dumps({**stored, "eolas_v1_model": "qwen3-14b:latest"}), encoding="utf-8")
    assert llm.make_provider("eolas").model == "qwen3-14b:latest"
    monkeypatch.setenv("EOLAS_MODEL", "otro:latest")
    assert llm.eolas_v1_model() == "otro:latest"


# --- Guardián: ningún nombre de modelo escrito a mano fuera del catálogo ---------------------------------------------
# Excepciones con su motivo. Añadir una aquí debe ser una decisión revisada, no la salida fácil.
PERMITIDOS = {
    "eolfi/eolas_v2.py": "el catálogo: DEFAULT_PROFILES, DEFAULT_ROLES y eolas_v1_model",
    "eolfi/llamacpp.py": "servidor llama.cpp antiguo, retirado (solo estado y parada)",
    "eolfi/vscode-bridge/llamacpp-config.js": "configuración del llama.cpp antiguo de la extensión",
    "eolfi/modelos_reconstruir.py": "nombres de ARQUITECTURA GGUF (gemma, gemma3…), no de perfiles",
}
# Líneas concretas: LlamaCppProvider es inalcanzable (ningún proveedor tiene kind «llamacpp»); candidato a retirar
# anotado en REGISTRO_LIMPIEZA.md, no se borra antes de revisar el registro.
LINEAS_PERMITIDAS = {("eolfi/generador/llm.py", 'super().__init__("gemma"'), ("eolfi/generador/llm.py", 'PRESETS["gemma"]')}
# Espejos para un eolas-v2.json antiguo: se permiten porque una prueba exige que coincidan con el catálogo.
ESPEJOS = {"eolfi/vscode-bridge/eolas-v2-starter.js", "eolfi/vscode-bridge/local-model.js"}


def _patron():
    nombres = [n for n in eolas_v2.DEFAULT_PROFILES if n != "moe"]
    alias = sorted({str(p["alias"]).split(":")[0] for n, p in eolas_v2.DEFAULT_PROFILES.items() if n != "moe"},
                   key=len, reverse=True)
    v1 = str(eolas_v2.DEFAULT_CONFIG["eolas_v1_model"]).split(":")[0]
    return re.compile(r"""["'`](?:%s)["'`]|%s""" % ("|".join(map(re.escape, nombres)),
                                                  "|".join(map(re.escape, [*alias, v1]))))


def test_ningun_nombre_de_modelo_fijo_fuera_del_catalogo():
    patron = _patron()
    archivos = [*ROOT.joinpath("eolfi").rglob("*.py"), *ROOT.joinpath("eolfi").rglob("*.js"),
                *ROOT.joinpath("eolfi").rglob("*.mjs"), *ROOT.joinpath("tools").rglob("*.py")]
    hallados = []
    for f in archivos:
        rel = f.relative_to(ROOT).as_posix()
        if "/test/" in rel or "node_modules" in rel or rel in PERMITIDOS or rel in ESPEJOS:
            continue
        for i, linea in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            codigo = linea.split("#")[0] if f.suffix == ".py" else linea.split("//")[0]
            if any(rel == a and b in codigo for a, b in LINEAS_PERMITIDAS):
                continue
            if patron.search(codigo) and "plantilla" not in codigo:   # «mistral» como plantilla no es un modelo
                hallados.append(f"{rel}:{i}: {linea.strip()[:120]}")
    assert not hallados, "Nombres de modelo fijos (usa eolas_v2.rol/etiqueta/eolas_v1_model):\n" + "\n".join(hallados)


def test_los_espejos_de_la_extension_coinciden_con_el_catalogo():
    starter = (ROOT / "eolfi/vscode-bridge/eolas-v2-starter.js").read_text(encoding="utf-8")
    espejo = dict(re.findall(r"(\w+): '([^']+)'", re.search(r"DEFAULT_ALIASES = \{([^}]*)\}", starter).group(1)))
    assert espejo and all(eolas_v2.DEFAULT_PROFILES[n]["alias"] == a for n, a in espejo.items())
    local = (ROOT / "eolfi/vscode-bridge/local-model.js").read_text(encoding="utf-8")
    assert re.search(r"const EOLAS_MODEL = '([^']+)'", local).group(1) == eolas_v2.DEFAULT_CONFIG["eolas_v1_model"]
