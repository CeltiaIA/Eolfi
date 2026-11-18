"""Voz local de Eolfi (PLAN_DEFINITIVO.md, bloque A): voz a texto y texto a voz sin que el audio salga del equipo.

Motores:
- ``windows``: ``System.Speech`` de Windows (reconocedor y voces del sistema, sin conexión). No instala nada.
  Reconoce peor que Whisper y no puntúa.
- ``whisper``: whisper.cpp, si el titular lo instala y lo declara en la configuración (``whisper.bin`` y
  ``whisper.modelo``). Solo voz a texto.

Dictado (A9, 18/11/2026): ``dictar`` graba del micrófono predeterminado del equipo durante N segundos (1-30) con
MCI de Windows (``winmm.dll``, sin instalar nada), en WAV PCM de 16 bits, 16 kHz, mono, en una carpeta temporal que se
borra al terminar, y lo transcribe. Lo usan clientes sin micrófono propio, como la extensión de VS Code (su proceso
no puede grabar). Solo un dictado a la vez; el audio nunca se guarda ni sale del equipo.

Lectura en voz alta con Piper (18/11/2026): voces neuronales locales (``piper-tts`` 1.8, GPL-3.0, en un entorno de
Python aparte que Eolfi llama como programa externo; voces ONNX de ``rhasspy/piper-voices``). Si Piper no está o falla,
se lee con las voces de Windows. ``para_leer`` prepara el texto para que suene natural (sin símbolos de Markdown,
emojis, enlaces ni rutas largas; abreviaturas desarrolladas; una pausa al final de cada línea) y ``AJUSTES`` fija el
ritmo, la variación y las pausas de cada preset.

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
import threading
import time
from pathlib import Path
from typing import Any

MAX_BYTES = 4 * 1024 * 1024       # ≈ 2 min a 16 kHz mono; coincide con el tope de las rutas JSON del servidor
MAX_SEGUNDOS = 120
MAX_TEXTO = 4000
MAX_DICTADO = 30
PLAZO = 120
MOTORES = ("auto", "windows", "whisper")
LECTURAS = ("auto", "piper", "windows")
# Presets de Piper: length_scale (ritmo; >1 más lento), noise_scale (variación de la voz), noise_w (variación del ritmo
# de cada fonema) y silencio tras cada frase en segundos. «original» deja los valores de cada modelo.
AJUSTES: dict[str, dict[str, float]] = {
    "original": {},
    "natural": {"length_scale": 1.08, "noise_scale": 0.62, "noise_w": 0.85, "silencio": 0.35},
    "pausada": {"length_scale": 1.15, "noise_scale": 0.58, "noise_w": 0.75, "silencio": 0.5},
}
_IDIOMA = re.compile(r"[a-z]{2}-[A-Z]{2}")
_VOZ = re.compile(r"[\w .()\-]{1,80}")
DEFECTO: dict[str, Any] = {"motor": "auto", "idioma": "es-ES", "voz": "", "whisper": {"bin": "", "modelo": ""},
                           "lectura": "auto", "piper": {"python": "", "modelo": "", "hablante": 0, "ajuste": "natural"}}


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
        if isinstance(data.get("lectura"), str):
            cfg["lectura"] = data["lectura"]
        if isinstance(data.get("piper"), dict):
            for k in ("python", "modelo", "ajuste"):
                if isinstance(data["piper"].get(k), str):
                    cfg["piper"][k] = data["piper"][k]
            if isinstance(data["piper"].get("hablante"), int) and not isinstance(data["piper"]["hablante"], bool):
                cfg["piper"]["hablante"] = data["piper"]["hablante"]
    if cfg["motor"] not in MOTORES:
        cfg["motor"] = "auto"
    if cfg["lectura"] not in LECTURAS:
        cfg["lectura"] = "auto"
    if cfg["piper"]["ajuste"] not in AJUSTES:
        cfg["piper"]["ajuste"] = "natural"
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
    if "lectura" in cambios:
        if cambios["lectura"] not in LECTURAS:
            raise VozError(f"lectura desconocida: {cambios['lectura']} (opciones: {', '.join(LECTURAS)})")
        cfg["lectura"] = cambios["lectura"]
    if "piper" in cambios:
        p = cambios["piper"]
        if not isinstance(p, dict):
            raise VozError("piper debe ser un objeto")
        if "ajuste" in p:
            if p["ajuste"] not in AJUSTES:
                raise VozError(f"ajuste desconocido: {p['ajuste']} (opciones: {', '.join(AJUSTES)})")
            cfg["piper"]["ajuste"] = p["ajuste"]
        if "modelo" in p:
            modelo = str(p["modelo"] or "")
            if modelo and modelo not in [v["modelo"] for v in voces_piper()]:
                raise VozError("modelo de Piper desconocido: elige uno de los instalados (mira `eolfi voz estado`)")
            cfg["piper"]["modelo"] = modelo
        if "hablante" in p:
            h = p["hablante"]
            if isinstance(h, bool) or not isinstance(h, int) or h < 0:
                raise VozError("hablante inválido")
            cfg["piper"]["hablante"] = h
        modelo = cfg["piper"]["modelo"] or (_voz_piper_defecto() or {}).get("modelo", "")
        elegida = next((v for v in voces_piper() if v["modelo"] == modelo), None)
        if elegida is not None and cfg["piper"]["hablante"] >= elegida["hablantes"]:
            raise VozError(f"esa voz tiene {elegida['hablantes']} hablante(s)")
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


# Graba del micrófono predeterminado con MCI. La ruta y la duración llegan por variables de entorno.
_PS_GRABAR = r'''
$ErrorActionPreference = 'Stop'
Add-Type -Namespace EolfiVoz -Name Mci -MemberDefinition @"
[DllImport("winmm.dll", CharSet = CharSet.Unicode)]
public static extern int mciSendString(string cmd, System.Text.StringBuilder ret, int len, IntPtr hwnd);
[DllImport("winmm.dll", CharSet = CharSet.Unicode)]
public static extern bool mciGetErrorString(int err, System.Text.StringBuilder buf, int len);
"@
function M([string]$c) {
  $r = [EolfiVoz.Mci]::mciSendString($c, $null, 0, [IntPtr]::Zero)
  if ($r -ne 0) {
    $e = New-Object System.Text.StringBuilder 256
    [void][EolfiVoz.Mci]::mciGetErrorString($r, $e, 256)
    throw ("MCI: " + $e.ToString())
  }
}
$ms = [int]$env:EOLFI_VOZ_MS
M 'open new type waveaudio alias eolfidictado'
try {
  M 'set eolfidictado time format ms bitspersample 16 channels 1 samplespersec 16000 bytespersec 32000 alignment 2'
  M 'record eolfidictado'
  Start-Sleep -Milliseconds $ms
  M 'stop eolfidictado'
  M ('save eolfidictado "' + $env:EOLFI_VOZ_WAV + '"')
} finally {
  [void][EolfiVoz.Mci]::mciSendString('close eolfidictado', $null, 0, [IntPtr]::Zero)
}
'{"ok":true}'
'''

# Micrófonos del equipo (19/11/2026, titular: «haz que detecte el micrófono que tengo conectado a la CPU»). Lee de Core
# Audio todas las entradas de sonido (también las desconectadas o desactivadas), cuál es la predeterminada, si está
# silenciada y su volumen. Solo lee: no cambia ningún ajuste de Windows.
_PS_MICROFONOS = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace EolfiMic {
  [StructLayout(LayoutKind.Sequential)] public struct PROPERTYKEY { public Guid fmtid; public int pid; }
  [StructLayout(LayoutKind.Explicit)] public struct PROPVARIANT { [FieldOffset(0)] public short vt; [FieldOffset(8)] public IntPtr p; }
  [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int flujo, int estados, out IMMDeviceCollection col);
    int GetDefaultAudioEndpoint(int flujo, int rol, out IMMDevice d);
  }
  [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceCollection { int GetCount(out int n); int Item(int i, out IMMDevice d); }
  [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    int Activate(ref Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
    int OpenPropertyStore(int acceso, out IPropertyStore ps);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int estado);
  }
  [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore { int GetCount(out int n); int GetAt(int i, out PROPERTYKEY k); int GetValue(ref PROPERTYKEY k, out PROPVARIANT v); }
  [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr p); int UnregisterControlChangeNotify(IntPtr p);
    int GetChannelCount(out int n); int SetMasterVolumeLevel(float l, ref Guid g);
    int SetMasterVolumeLevelScalar(float l, ref Guid g); int GetMasterVolumeLevel(out float l);
    int GetMasterVolumeLevelScalar(out float l);
    int SetChannelVolumeLevel(int c, float l, ref Guid g); int SetChannelVolumeLevelScalar(int c, float l, ref Guid g);
    int GetChannelVolumeLevel(int c, out float l); int GetChannelVolumeLevelScalar(int c, out float l);
    int SetMute(int m, ref Guid g); int GetMute(out int m);
  }
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class Enumerador { }
  public class Mic { public string nombre; public int estado; public bool predeterminado; public bool silenciado; public int volumen = -1; }
  public static class Api {
    public static List<Mic> Listar() {
      var en = (IMMDeviceEnumerator)new Enumerador();
      string pred = null; IMMDevice d0;
      if (en.GetDefaultAudioEndpoint(1, 0, out d0) == 0 && d0 != null) d0.GetId(out pred);
      IMMDeviceCollection col; Marshal.ThrowExceptionForHR(en.EnumAudioEndpoints(1, 15, out col));
      int n; col.GetCount(out n);
      var res = new List<Mic>();
      for (int i = 0; i < n; i++) {
        IMMDevice d; col.Item(i, out d);
        var m = new Mic(); string id; d.GetId(out id); d.GetState(out m.estado); m.predeterminado = id == pred;
        IPropertyStore ps;
        if (d.OpenPropertyStore(0, out ps) == 0) {
          var k = new PROPERTYKEY { fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"), pid = 14 };
          PROPVARIANT v; if (ps.GetValue(ref k, out v) == 0 && v.vt == 31) m.nombre = Marshal.PtrToStringUni(v.p);
        }
        object o; var g = typeof(IAudioEndpointVolume).GUID;
        if (m.estado == 1 && d.Activate(ref g, 23, IntPtr.Zero, out o) == 0) {
          var vol = (IAudioEndpointVolume)o; float l; int s;
          vol.GetMasterVolumeLevelScalar(out l); vol.GetMute(out s); m.volumen = (int)Math.Round(l * 100); m.silenciado = s != 0;
        }
        res.Add(m);
      }
      return res;
    }
  }
}
"@
@{ microfonos = @([EolfiMic.Api]::Listar()) } | ConvertTo-Json -Depth 4 -Compress
'''
ESTADOS_MIC = {1: "activo", 2: "desactivado", 4: "no presente", 8: "desconectado"}
# Pico por debajo del cual una grabación es silencio de la entrada (≈ -55 dBFS en 16 bits): ni voz ni ruido de sala.
UMBRAL_SILENCIO = 60


def nivel(data: bytes) -> dict[str, float]:
    """Pico y RMS (escala de 16 bits) de un WAV PCM ya validado."""
    i = data.find(b"data", 12)
    pcm = data[i + 8:] if i >= 0 else b""
    pcm = pcm[: len(pcm) // 2 * 2]
    if not pcm:
        return {"pico": 0, "rms": 0.0}
    muestras = memoryview(pcm).cast("h")
    pico = max(max(muestras), -min(muestras))
    rms = (sum(x * x for x in muestras) / len(muestras)) ** 0.5
    return {"pico": int(pico), "rms": round(rms, 1)}


def microfonos() -> dict[str, Any]:
    """Entradas de sonido de Windows con su estado, la predeterminada y un diagnóstico de su configuración."""
    if not _powershell():
        return {"disponible": False, "microfonos": [], "predeterminado": None,
                "diagnostico": "solo se puede consultar en Windows"}
    try:
        d = _ps(_PS_MICROFONOS, plazo=30)
    except VozError as exc:
        return {"disponible": False, "microfonos": [], "predeterminado": None, "diagnostico": str(exc)}
    lista = d.get("microfonos") or []
    lista = [lista] if isinstance(lista, dict) else list(lista)
    mics = [{"nombre": str(m.get("nombre") or "entrada sin nombre"),
             "estado": ESTADOS_MIC.get(int(m.get("estado") or 0), "desconocido"),
             "predeterminado": bool(m.get("predeterminado")), "silenciado": bool(m.get("silenciado")),
             "volumen": None if int(m.get("volumen", -1)) < 0 else int(m["volumen"])} for m in lista]
    mics.sort(key=lambda m: (not m["predeterminado"], m["estado"] != "activo", m["nombre"]))
    pred = next((m for m in mics if m["predeterminado"] and m["estado"] == "activo"), None)
    return {"disponible": True, "microfonos": mics, "predeterminado": pred["nombre"] if pred else None,
            "diagnostico": _diagnostico_mic(pred, mics)}


def _diagnostico_mic(pred: dict[str, Any] | None, mics: list[dict[str, Any]]) -> str | None:
    desconectados = sum(1 for m in mics if m["estado"] == "desconectado")
    if pred is None:
        return ("Windows no tiene ningún micrófono activo" + (f" ({desconectados} toma(s) sin nada enchufado)"
                                                             if desconectados else "")
                + ": enchufa el micrófono y comprueba Configuración > Sistema > Sonido > Entrada.")
    if pred["silenciado"]:
        return f"«{pred['nombre']}» está silenciado en Windows: actívalo en Configuración > Sistema > Sonido > Entrada."
    if pred["volumen"] is not None and pred["volumen"] < 10:
        return f"«{pred['nombre']}» tiene el volumen de entrada al {pred['volumen']} %: súbelo en Sonido > Entrada."
    return None


def _silencio(data: bytes) -> None:
    """Si la grabación es silencio de la entrada, se dice qué revisar (antes: «No se entendió nada»)."""
    if nivel(data)["pico"] >= UMBRAL_SILENCIO:
        return
    try:
        m = microfonos()
    except VozError:
        m = {"predeterminado": None, "diagnostico": None}
    cual = f"«{m['predeterminado']}»" if m.get("predeterminado") else "el micrófono"
    raise VozError(m.get("diagnostico") or
                   f"No llega sonido de {cual} (la grabación es silencio). Comprueba que está enchufado en la toma de "
                   "micrófono (rosa) y no en la de línea o auriculares; si es un auricular con un solo conector de 4 "
                   "polos, necesita un adaptador o la toma combinada. Puedes ver su nivel en Configuración > Sistema > "
                   "Sonido > Entrada mientras hablas.")


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
    win, whi, pip = _windows(), _whisper(cfg), _piper(cfg)
    return {"configuracion": str(config_path()), "motor": cfg["motor"], "motor_activo": _motor(cfg, win, whi, estricto=False),
            "idioma": cfg["idioma"], "voz": cfg["voz"], "local": True,
            "windows": win, "whisper": whi, "piper": pip, "lectura": cfg["lectura"],
            "lectura_activa": _lectura(cfg, win, pip), "ajustes": list(AJUSTES),
            "voz_a_texto": bool(whi["disponible"] or cfg["idioma"] in win["reconocedores"]),
            "texto_a_voz": bool(win["voces"] or pip["disponible"])}


# ── Piper (texto a voz neuronal, local) ─────────────────────────────────────────────────────────────────────────

def _piper_dir() -> Path:
    return Path(os.environ.get("EOLFI_PIPER_VOCES") or Path.home() / ".eolfi" / "voces" / "piper")


def _piper_python(cfg: dict[str, Any]) -> str:
    """Python del entorno aislado de Piper: el de la configuración o el de ~/.eolfi/tools/piper-venv."""
    if cfg["piper"]["python"]:
        return cfg["piper"]["python"]
    base = Path(os.environ.get("EOLFI_PIPER_VENV") or Path.home() / ".eolfi" / "tools" / "piper-venv")
    exe = base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(exe) if exe.is_file() else ""


def voces_piper() -> list[dict[str, Any]]:
    """Voces instaladas: cada .onnx con su .onnx.json al lado (idioma y número de hablantes salen del .json)."""
    out = []
    for onnx in sorted(_piper_dir().glob("*.onnx")):
        try:
            meta = json.loads(onnx.with_name(onnx.name + ".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        idioma = str((meta.get("language") or {}).get("code") or "").replace("_", "-")
        out.append({"modelo": str(onnx), "nombre": onnx.stem, "idioma": idioma,
                    "hablantes": max(1, int(meta.get("num_speakers") or 1))})
    return out


def _voz_piper_defecto() -> dict[str, Any] | None:
    voces = voces_piper()
    return next((v for v in voces if "davefx" in v["nombre"]), voces[0] if voces else None)


def _piper(cfg: dict[str, Any]) -> dict[str, Any]:
    exe = _piper_python(cfg)
    voces = voces_piper()
    modelo = cfg["piper"]["modelo"] or (_voz_piper_defecto() or {}).get("modelo", "")
    ok = bool(exe and Path(exe).is_file() and modelo and Path(modelo).is_file())
    return {"disponible": ok, "python": exe, "modelo": modelo, "hablante": cfg["piper"]["hablante"],
            "ajuste": cfg["piper"]["ajuste"], "voces": voces}


def _lectura(cfg: dict[str, Any], win: dict[str, Any], pip: dict[str, Any]) -> str | None:
    if cfg["lectura"] in ("auto", "piper") and pip["disponible"]:
        return "piper"
    if cfg["lectura"] in ("auto", "windows") and win["voces"]:
        return "windows"
    return None


_ABREVIATURAS = [(r"\bp\. ?ej\.", "por ejemplo"), (r"\betc\.", "etcétera"), (r"\baprox\.", "aproximadamente"),
                 (r"\bnúm\.", "número"), (r"\bpág\.", "página"), (r"\bvs\.?(?=\s)", "frente a"),
                 (r"\bEE\. ?UU\.", "Estados Unidos"), (r"\bUd\.", "usted"), (r"\bUds\.", "ustedes")]
_RUTA = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/)(?:[^\s\\/]+[\\/])+([^\s\\/]+)")


def para_leer(texto: str) -> str:
    """Texto pensado para la vista → texto pensado para el oído.

    Quita lo que una voz leería mal (Markdown, emojis, marcas de herramientas, enlaces y rutas completas), desarrolla
    abreviaturas y cierra cada línea con un punto para que haya una pausa natural entre elementos de una lista."""
    import unicodedata

    t = str(texto or "")
    t = re.sub(r"```.*?```", " Te muestro un bloque de código en pantalla. ", t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", t)                 # [texto](url) → texto
    t = re.sub(r"https?://\S+", "un enlace", t)
    t = _RUTA.sub(r"\1", t)                                          # C:\a\b\motor.zip → motor.zip
    t = re.sub(r"[✓✗]\s*[\w.-]+", " ", t)                            # marcas de herramientas del chat («✓ triage»)
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co") and ch not in "\ufe0f\u200d")
    t = t.replace("→", " a ").replace("×", " por ").replace("…", ".").replace("·", ",").replace("|", ",")
    lineas = []
    for linea in t.splitlines():
        linea = re.sub(r"^\s*(?:(?:#{1,6}|>|[-*+•]|\d+[.)])\s*)+(?=\S)", "", linea)   # «### 1. », «* », «> »…
        linea = re.sub(r"(\*\*|__|\*|_)(\S(?:.*?\S)?)\1", r"\2", linea).replace("**", "").strip()
        for patron, sustituto in _ABREVIATURAS:
            linea = re.sub(patron, sustituto, linea, flags=re.I)
        linea = linea.strip()
        if not linea:
            continue
        if linea[-1] not in ".!?:;,":
            linea += "."
        lineas.append(linea)
    t = " ".join(lineas)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _hablar_piper(texto: str, pip: dict[str, Any]) -> bytes:
    voz = next((v for v in pip["voces"] if v["modelo"] == pip["modelo"]), None)
    hablante = pip["hablante"] if voz is None or pip["hablante"] < voz["hablantes"] else 0
    ajuste = AJUSTES.get(pip["ajuste"], {})
    work = Path(tempfile.mkdtemp(prefix="eolfi-piper-"))
    try:
        (work / "texto.txt").write_text(texto, encoding="utf-8")
        wav = work / "salida.wav"
        cmd = [pip["python"], "-m", "piper", "-m", pip["modelo"], "-s", str(hablante), "-i", str(work / "texto.txt"),
               "-f", str(wav)]
        if ajuste:
            cmd += ["--length-scale", str(ajuste["length_scale"]), "--noise-scale", str(ajuste["noise_scale"]),
                    "--noise-w-scale", str(ajuste["noise_w"]), "--sentence-silence", str(ajuste["silencio"])]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=PLAZO, stdin=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise VozError(f"Piper no respondió en {PLAZO} s") from exc
        if out.returncode != 0 or not wav.is_file():
            raise VozError("Piper falló: " + out.stderr.decode("utf-8", "replace").strip()[-300:])
        return wav.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
    _silencio(data)
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


_dictando = threading.Lock()


def _segundos_dictado(segundos: Any) -> float:
    try:
        seg = float(segundos)
    except (TypeError, ValueError):
        raise VozError("segundos de dictado no válidos") from None
    if not 1 <= seg <= MAX_DICTADO:
        raise VozError(f"el dictado dura entre 1 y {MAX_DICTADO} s")
    return seg


def grabar(segundos: Any) -> bytes:
    """Graba ``segundos`` del micrófono predeterminado (WAV PCM 16 bits, 16 kHz, mono). No guarda nada."""
    seg = _segundos_dictado(segundos)
    work = Path(tempfile.mkdtemp(prefix="eolfi-voz-"))
    try:
        wav = work / "dictado.wav"
        _ps(_PS_GRABAR, {"EOLFI_VOZ_MS": str(int(seg * 1000)), "EOLFI_VOZ_WAV": str(wav)}, plazo=seg + 30)
        try:
            data = wav.read_bytes()
        except FileNotFoundError:
            raise VozError("no se grabó nada: ¿hay micrófono y permiso de Windows para las aplicaciones de escritorio?") from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    validar_wav(data)
    return data


def dictar(segundos: Any, *, idioma: str | None = None) -> dict[str, Any]:
    """Graba del micrófono del equipo y lo transcribe. Comprueba antes de grabar que hay motor de voz a texto."""
    seg = _segundos_dictado(segundos)
    cfg = cargar()
    _motor(cfg, _windows(), _whisper(cfg))          # sin motor no se graba: el titular no habla para nada
    if not _dictando.acquire(blocking=False):
        raise VozError("ya hay un dictado en curso")
    try:
        data = grabar(seg)
    finally:
        _dictando.release()
    return {**transcribir(data, idioma=idioma), "origen": "micrófono del equipo", "audio_guardado": False}


def hablar(texto: str, *, idioma: str | None = None, voz: str | None = None) -> bytes:
    """Texto a voz. Con Piper instalado (y sin una voz de Windows pedida a propósito), voz neuronal local con el
    texto preparado para el oído; si no, o si Piper falla, las voces de Windows. Devuelve un WAV."""
    texto = (texto or "").strip()
    if not texto:
        raise VozError("no hay texto que leer")
    if len(texto) > MAX_TEXTO:
        raise VozError(f"texto demasiado largo (máximo {MAX_TEXTO} caracteres)")
    cfg = cargar()
    pip = _piper(cfg)
    if not voz and cfg["lectura"] in ("auto", "piper") and pip["disponible"]:
        oido = para_leer(texto)
        if not oido:
            raise VozError("no hay texto que leer")
        try:
            return _hablar_piper(oido, pip)
        except VozError:
            if cfg["lectura"] == "piper" or not _windows()["voces"]:
                raise
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
