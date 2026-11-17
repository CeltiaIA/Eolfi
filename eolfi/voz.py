"""Voz local de Eolfi (PLAN_DEFINITIVO.md, bloque A): voz a texto y texto a voz sin que el audio salga del equipo.

Motores:
- ``windows``: ``System.Speech`` de Windows (reconocedor y voces del sistema, sin conexión). No instala nada.
  Reconoce peor que Whisper y no puntúa.
- ``whisper``: whisper.cpp, si el titular lo instala y lo declara en la configuración (``whisper.bin`` y
  ``whisper.modelo``). Solo voz a texto.

Configuración: ``~/.eolfi/voz.json`` (o ``EOLFI_VOZ_CONFIG``). ``motor`` es ``auto`` (whisper si está, si no windows),
``windows`` o ``whisper``. El audio de entrada es WAV PCM de 16 bits; se valida antes de pasarlo a ningún programa.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MAX_BYTES = 4 * 1024 * 1024       # ≈ 2 min a 16 kHz mono; coincide con el tope de las rutas JSON del servidor
MAX_SEGUNDOS = 120
MAX_TEXTO = 4000
PLAZO = 120
MOTORES = ("auto", "windows", "whisper")
_IDIOMA = re.compile(r"[a-z]{2}-[A-Z]{2}")
_VOZ = re.compile(r"[\w .()\-]{1,80}")
DEFECTO: dict[str, Any] = {"motor": "auto", "idioma": "es-ES", "voz": "", "whisper": {"bin": "", "modelo": ""}}


class VozError(ValueError):
    pass


def config_path() -> Path:
    return Path(os.environ.get("EOLFI_VOZ_CONFIG") or Path.home() / ".eolfi" / "voz.json")


def cargar() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFECTO))
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k in ("motor", "idioma", "voz"):
            if isinstance(data.get(k), str):
                cfg[k] = data[k]
        if isinstance(data.get("whisper"), dict):
            for k in ("bin", "modelo"):
                if isinstance(data["whisper"].get(k), str):
                    cfg["whisper"][k] = data["whisper"][k]
    if cfg["motor"] not in MOTORES:
        cfg["motor"] = "auto"
    if not _IDIOMA.fullmatch(cfg["idioma"]):
        cfg["idioma"] = "es-ES"
    return cfg


def guardar(cambios: dict[str, Any]) -> dict[str, Any]:
    cfg = cargar()
    if "motor" in cambios:
        if cambios["motor"] not in MOTORES:
            raise VozError(f"motor desconocido: {cambios['motor']} (opciones: {', '.join(MOTORES)})")
        cfg["motor"] = cambios["motor"]
    if "idioma" in cambios:
        cfg["idioma"] = _idioma(cambios["idioma"])
    if "voz" in cambios:
        cfg["voz"] = _voz(cambios["voz"])
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return cfg


def _idioma(valor: Any) -> str:
    if not isinstance(valor, str) or not _IDIOMA.fullmatch(valor):
        raise VozError("idioma inválido: usa la forma es-ES")
    return valor


def _voz(valor: Any) -> str:
    if valor in ("", None):
        return ""
    if not isinstance(valor, str) or not _VOZ.fullmatch(valor):
        raise VozError("nombre de voz inválido")
    return valor


# ── WAV ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def validar_wav(data: bytes) -> dict[str, Any]:
    """Solo WAV PCM de 16 bits, 1 o 2 canales, 8 a 48 kHz y hasta MAX_SEGUNDOS. Devuelve sus datos."""
    if len(data) > MAX_BYTES:
        raise VozError(f"audio demasiado grande (máximo {MAX_BYTES // (1024 * 1024)} MB)")
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VozError("el audio debe ser un WAV")
    pos, fmt, muestras = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        if cid == b"fmt " and size >= 16:
            fmt = struct.unpack_from("<HHIIHH", data, pos + 8)
        elif cid == b"data":
            muestras = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if fmt is None or muestras is None:
        raise VozError("WAV incompleto: falta el formato o los datos")
    codec, canales, hz, _, bloque, bits = fmt
    if codec != 1 or bits != 16 or canales not in (1, 2) or not 8000 <= hz <= 48000 or bloque != canales * 2:
        raise VozError("el WAV debe ser PCM de 16 bits, mono o estéreo, entre 8 y 48 kHz")
    segundos = muestras / (hz * bloque)
    if segundos > MAX_SEGUNDOS:
        raise VozError(f"audio demasiado largo (máximo {MAX_SEGUNDOS} s)")
    if segundos < 0.1:
        raise VozError("audio vacío")
    return {"hz": hz, "canales": canales, "segundos": round(segundos, 2)}


# ── Motor de Windows (System.Speech) ────────────────────────────────────────────────────────────────────────────

_PS_COMUN = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
"""
_PS_ESTADO = _PS_COMUN + r"""
$rec = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | ForEach-Object { $_.Culture.Name })
$voces = @((New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | Where-Object { $_.Enabled } |
  ForEach-Object { @{ nombre = $_.VoiceInfo.Name; idioma = $_.VoiceInfo.Culture.Name } })
@{ reconocedores = $rec; voces = $voces } | ConvertTo-Json -Depth 4 -Compress
"""
_PS_RECONOCER = _PS_COMUN + r"""
$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine([Globalization.CultureInfo]$env:EOLFI_VOZ_IDIOMA)
$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$r.SetInputToWaveFile($env:EOLFI_VOZ_WAV)
$seg = @()
for ($i = 0; $i -lt 400; $i++) {
  try { $x = $r.Recognize() } catch { break }
  if ($null -eq $x) { break }
  $seg += @{ texto = $x.Text; confianza = [math]::Round($x.Confidence, 3) }
}
$r.Dispose()
@{ segmentos = $seg } | ConvertTo-Json -Depth 4 -Compress
"""
_PS_HABLAR = _PS_COMUN + r"""
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:EOLFI_VOZ_NOMBRE) { $s.SelectVoice($env:EOLFI_VOZ_NOMBRE) }
else { try { $s.SelectVoiceByHints('NotSet', 'NotSet', 0, [Globalization.CultureInfo]$env:EOLFI_VOZ_IDIOMA) } catch { } }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono')
$s.SetOutputToWaveFile($env:EOLFI_VOZ_WAV, $fmt)
$s.Speak([IO.File]::ReadAllText($env:EOLFI_VOZ_TEXTO, [Text.Encoding]::UTF8))
$s.Dispose()
'{"ok":true}'
"""


def _powershell() -> str | None:
    """Windows PowerShell 5.1: es la que trae System.Speech (PowerShell 7 no)."""
    if os.name != "nt":
        return None
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(exe) if exe.is_file() else None


def _ps(script: str, entorno: dict[str, str] | None = None, *, plazo: float = PLAZO) -> Any:
    exe = _powershell()
    if not exe:
        raise VozError("el motor de voz de Windows no está disponible en este sistema")
    # Los datos van por variables de entorno y archivos, nunca dentro del texto del guion.
    env = {k: v for k, v in os.environ.items() if k.upper() in
           ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA")}
    env.update(entorno or {})
    try:
        # -EncodedCommand: el guion (constante) llega entero; por la entrada estándar PowerShell no ejecuta la última
        # instrucción de varias líneas.
        codigo = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        out = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-EncodedCommand", codigo],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=plazo, env=env, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise VozError(f"el motor de voz no respondió en {plazo:.0f} s") from exc
    if out.returncode != 0:
        raise VozError("el motor de voz de Windows falló: " + out.stderr.decode("utf-8", "replace").strip()[-300:])
    linea = out.stdout.decode("utf-8", "replace").strip().splitlines()[-1:] or ["{}"]
    return json.loads(linea[0])


_estado_windows: dict[str, Any] | None = None


def _windows() -> dict[str, Any]:
    global _estado_windows
    if _estado_windows is None:
        try:
            d = _ps(_PS_ESTADO, plazo=30)
            rec, voces = d.get("reconocedores") or [], d.get("voces") or []
            _estado_windows = {"disponible": True, "reconocedores": [rec] if isinstance(rec, str) else list(rec),
                               "voces": [voces] if isinstance(voces, dict) else list(voces)}
        except (VozError, ValueError, OSError) as exc:
            _estado_windows = {"disponible": False, "reconocedores": [], "voces": [], "motivo": str(exc)[:200]}
    return _estado_windows


def _whisper(cfg: dict[str, Any]) -> dict[str, Any]:
    exe, modelo = cfg["whisper"]["bin"], cfg["whisper"]["modelo"]
    exe = exe or shutil.which("whisper-cli") or ""
    ok = bool(exe and Path(exe).is_file() and modelo and Path(modelo).is_file())
    return {"disponible": ok, "bin": exe, "modelo": modelo}


def estado() -> dict[str, Any]:
    cfg = cargar()
    win, whi = _windows(), _whisper(cfg)
    return {"configuracion": str(config_path()), "motor": cfg["motor"], "motor_activo": _motor(cfg, win, whi, estricto=False),
            "idioma": cfg["idioma"], "voz": cfg["voz"], "local": True,
            "windows": win, "whisper": whi,
            "voz_a_texto": bool(whi["disponible"] or cfg["idioma"] in win["reconocedores"]),
            "texto_a_voz": bool(win["voces"])}


def _motor(cfg: dict[str, Any], win: dict[str, Any], whi: dict[str, Any], *, estricto: bool = True) -> str | None:
    pedido = cfg["motor"]
    if pedido in ("auto", "whisper") and whi["disponible"]:
        return "whisper"
    if pedido in ("auto", "windows") and win["disponible"] and win["reconocedores"]:
        return "windows"
    if estricto:
        raise VozError("no hay ningún motor de voz a texto disponible (mira `eolfi voz estado`)")
    return None


# ── Voz a texto y texto a voz ───────────────────────────────────────────────────────────────────────────────────

def transcribir(data: bytes, *, idioma: str | None = None) -> dict[str, Any]:
    info = validar_wav(data)
    cfg = cargar()
    lang = _idioma(idioma) if idioma else cfg["idioma"]
    win, whi = _windows(), _whisper(cfg)
    motor = _motor(cfg, win, whi)
    if motor == "windows" and lang not in win["reconocedores"]:
        raise VozError(f"Windows no tiene reconocedor para {lang} (instalados: {', '.join(win['reconocedores']) or 'ninguno'})")
    t0 = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix="eolfi-voz-"))
    try:
        wav = work / "entrada.wav"
        wav.write_bytes(data)
        if motor == "whisper":
            try:
                out = subprocess.run([whi["bin"], "-m", whi["modelo"], "-f", str(wav), "-l", lang[:2], "-nt", "-np"],
                                     capture_output=True, timeout=PLAZO, check=False,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as exc:
                raise VozError(f"whisper no respondió en {PLAZO} s") from exc
            if out.returncode != 0:
                raise VozError("whisper falló: " + out.stderr.decode("utf-8", "replace").strip()[-300:])
            texto = " ".join(out.stdout.decode("utf-8", "replace").split())
            segmentos = [{"texto": texto, "confianza": None}] if texto else []
        else:
            d = _ps(_PS_RECONOCER, {"EOLFI_VOZ_IDIOMA": lang, "EOLFI_VOZ_WAV": str(wav)})
            seg = d.get("segmentos") or []
            segmentos = [seg] if isinstance(seg, dict) else list(seg)
            texto = " ".join(str(s.get("texto", "")).strip() for s in segmentos).strip()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    conf = [s["confianza"] for s in segmentos if isinstance(s.get("confianza"), (int, float))]
    return {"texto": texto, "motor": motor, "idioma": lang, "segundos": info["segundos"],
            "confianza": round(sum(conf) / len(conf), 3) if conf else None,
            "ms": int((time.monotonic() - t0) * 1000), "local": True}


def hablar(texto: str, *, idioma: str | None = None, voz: str | None = None) -> bytes:
    """Texto a voz con las voces de Windows. Devuelve un WAV (16 kHz, mono)."""
    texto = (texto or "").strip()
    if not texto:
        raise VozError("no hay texto que leer")
    if len(texto) > MAX_TEXTO:
        raise VozError(f"texto demasiado largo (máximo {MAX_TEXTO} caracteres)")
    cfg = cargar()
    lang = _idioma(idioma) if idioma else cfg["idioma"]
    nombre = _voz(voz) if voz is not None else cfg["voz"]
    win = _windows()
    if not win["voces"]:
        raise VozError("no hay voces instaladas para leer en voz alta")
    if nombre and nombre not in [v.get("nombre") for v in win["voces"]]:
        raise VozError(f"voz desconocida: {nombre}")
    work = Path(tempfile.mkdtemp(prefix="eolfi-voz-"))
    try:
        (work / "texto.txt").write_text(texto, encoding="utf-8")
        wav = work / "salida.wav"
        _ps(_PS_HABLAR, {"EOLFI_VOZ_IDIOMA": lang, "EOLFI_VOZ_NOMBRE": nombre, "EOLFI_VOZ_WAV": str(wav),
                         "EOLFI_VOZ_TEXTO": str(work / "texto.txt")})
        return wav.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)
