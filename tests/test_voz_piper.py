"""Lectura con Piper (18/11/2026): texto preparado para el oído, voces instaladas, ajustes, respaldo a Windows y API.
Piper real solo se prueba donde está instalado; el resto usa un Piper simulado."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from eolfi import server, voz
from tests.test_server import srv  # noqa: F401 — fixture
from tests.test_voz import motor, wav  # noqa: F401 — fixture


def test_para_leer_quita_lo_que_suena_mal():
    texto = """### 1. Análisis de los archivos
*   **Imágenes** (`1.png`): ver [la guía](https://x.y/z) y https://a.b/c
2. Ruta C:\\Users\\luis\\Proyecto\\motor.zip, p. ej. el motor → Eolas, etc.
✓ triage✓ triage 📎 que-tal-socio.sh
```python
print(1)
```
¿Empiezo?"""
    assert voz.para_leer(texto) == (
        "Análisis de los archivos. Imágenes (1.png): ver la guía y un enlace. Ruta motor.zip, por ejemplo el motor a "
        "Eolas, etcétera. que-tal-socio.sh. Te muestro un bloque de código en pantalla. ¿Empiezo?")
    assert voz.para_leer("Ver /home/luis/x/y.txt y D:/a/b.gguf") == "Ver y.txt y b.gguf."
    assert voz.para_leer("✓ ✗ 📎") == ""


@pytest.fixture
def piper(monkeypatch, tmp_path):
    """Piper simulado: dos voces instaladas (una con dos hablantes) y un subprocess que escribe el WAV pedido."""
    voces = tmp_path / "voces"
    voces.mkdir()
    for nombre, n in (("es_ES-davefx-medium", 1), ("es_ES-sharvard-medium", 2)):
        (voces / f"{nombre}.onnx").write_bytes(b"onnx")
        (voces / f"{nombre}.onnx.json").write_text(json.dumps({"language": {"code": "es_ES"}, "num_speakers": n}))
    (voces / "huerfana.onnx").write_bytes(b"sin json: no cuenta")
    venv = tmp_path / "venv" / ("Scripts" if os.name == "nt" else "bin")
    venv.mkdir(parents=True)
    (venv / ("python.exe" if os.name == "nt" else "python")).write_bytes(b"")
    monkeypatch.setenv("EOLFI_PIPER_VOCES", str(voces))
    monkeypatch.setenv("EOLFI_PIPER_VENV", str(tmp_path / "venv"))
    monkeypatch.setenv("EOLFI_VOZ_CONFIG", str(tmp_path / "voz.json"))
    llamadas = []

    def run(cmd, **kw):
        llamadas.append({"cmd": cmd, "texto": Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")})
        if getattr(run, "falla", False):
            return subprocess.CompletedProcess(cmd, 1, b"", b"modelo roto")
        Path(cmd[cmd.index("-f") + 1]).write_bytes(wav(0.2, hz=22050))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(voz.subprocess, "run", run)
    run.llamadas = llamadas
    return run


def test_estado_y_configuracion_de_piper(piper, motor):  # noqa: F811
    e = voz.estado()
    assert e["lectura_activa"] == "piper" and e["texto_a_voz"] and e["ajustes"] == ["original", "natural", "pausada"]
    assert [(v["nombre"], v["hablantes"]) for v in e["piper"]["voces"]] == [("es_ES-davefx-medium", 1),
                                                                              ("es_ES-sharvard-medium", 2)]
    assert e["piper"]["modelo"].endswith("es_ES-davefx-medium.onnx") and e["piper"]["ajuste"] == "natural"
    sharvard = e["piper"]["voces"][1]["modelo"]
    cfg = voz.guardar({"piper": {"modelo": sharvard, "hablante": 1, "ajuste": "pausada"}})
    assert cfg["piper"] == {**cfg["piper"], "modelo": sharvard, "hablante": 1, "ajuste": "pausada"}
    for malo, error in (({"modelo": "C:/otro.onnx"}, "desconocido"), ({"hablante": 2}, "2 hablante"),
                        ({"hablante": True}, "inválido"), ({"ajuste": "robot"}, "ajuste desconocido")):
        with pytest.raises(voz.VozError, match=error):
            voz.guardar({"piper": malo})
    with pytest.raises(voz.VozError, match="lectura desconocida"):
        voz.guardar({"lectura": "nube"})
    assert voz.guardar({"lectura": "windows"})["lectura"] == "windows"
    assert voz.estado()["lectura_activa"] == "windows"


def test_hablar_con_piper_prepara_el_texto_y_aplica_el_ajuste(piper, motor):  # noqa: F811
    audio = voz.hablar("**Hola**, Luis.\n- uno\n- dos")
    assert audio[:4] == b"RIFF" and not motor                     # Windows no se usó
    llamada = piper.llamadas[-1]
    assert llamada["texto"] == "Hola, Luis. uno. dos."
    cmd = llamada["cmd"]
    assert cmd[1:3] == ["-m", "piper"] and cmd[cmd.index("-s") + 1] == "0"
    assert cmd[cmd.index("--length-scale") + 1] == "1.08" and cmd[cmd.index("--sentence-silence") + 1] == "0.35"
    voz.guardar({"piper": {"ajuste": "original"}})
    voz.hablar("Hola.")
    assert "--length-scale" not in piper.llamadas[-1]["cmd"]      # «original»: los valores del modelo
    voz.hablar("Hola.", voz="Voz de prueba")                      # una voz de Windows pedida a propósito
    assert len(piper.llamadas) == 2 and motor


def test_si_piper_falla_lee_windows_salvo_que_se_pida_solo_piper(piper, motor):  # noqa: F811
    piper.falla = True
    assert voz.hablar("Hola.")[:4] == b"RIFF" and motor           # respaldo: voces de Windows
    voz.guardar({"lectura": "piper"})
    with pytest.raises(voz.VozError, match="Piper falló: modelo roto"):
        voz.hablar("Hola.")


def test_api_de_configuracion_de_voz_solo_desde_este_equipo(srv, piper, motor, monkeypatch):  # noqa: F811
    import http.client

    port, _tmp = srv

    def post(body):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.request("POST", "/api/voz/config", json.dumps(body), {"Content-Type": "application/json", "X-Eolfi": "1"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"null")

    st, e = post({"piper": {"ajuste": "pausada"}, "motor": "whisper"})   # lo que no es de lectura se ignora
    assert st == 200 and e["piper"]["ajuste"] == "pausada" and e["motor"] == "auto"
    assert post({"piper": {"ajuste": "robot"}})[0] == 400
    monkeypatch.setattr(server, "_LOOPBACK", set())                   # como si viniera de otro equipo
    assert post({"piper": {"ajuste": "natural"}}) == (403, {"error": "La voz solo se configura desde este equipo."})


def test_csp_permite_reproducir_el_audio_generado():
    assert "media-src 'self' blob:" in server._CSP


def test_piper_real_si_esta_instalado(monkeypatch, tmp_path):
    monkeypatch.setenv("EOLFI_VOZ_CONFIG", str(tmp_path / "voz.json"))
    e = voz.estado()
    if e["lectura_activa"] != "piper":
        pytest.skip("Piper no está instalado en este equipo")
    audio = voz.hablar("Hola, soy la voz local de Eolfi.")
    assert audio[:4] == b"RIFF" and int.from_bytes(audio[24:28], "little") == 22050 and len(audio) > 22050
