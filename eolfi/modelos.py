"""Confianza en los modelos locales (PLAN_DEFINITIVO.md, bloque G).

- **Auditar** un GGUF sin cargarlo: estructura, bytes sobrantes tras los tensores, claves fuera de norma, plantilla
  de chat y cadenas con URL u órdenes, y su SHA-256. Un GGUF son pesos y metadatos: no ejecuta nada; lo que se
  busca es contenido pegado, metadatos raros o una plantilla que intente dirigir al modelo hacia fuera.
- **Lista de confianza** (``~/.eolfi/modelos-confianza.json``): los SHA-256 que el titular ha aceptado. Con
  ``exigir`` activado, Eolas V2 no arranca un modelo que no esté en la lista.
- **Conexiones** de los motores en marcha (solo Windows): a qué escuchan y con quién hablan.

Límite que no cambia: una puerta trasera en los propios pesos no se detecta mirando el archivo.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ESCALARES = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
# tipo ggml → (elementos por bloque, bytes por bloque)
_BLOQUE = {0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20), 6: (32, 22), 7: (32, 24), 8: (32, 34), 9: (32, 36),
           10: (256, 84), 11: (256, 110), 12: (256, 144), 13: (256, 176), 14: (256, 210), 15: (256, 292),
           24: (1, 1), 25: (1, 2), 26: (1, 4), 27: (1, 8), 28: (1, 8), 30: (1, 2)}
_URL = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
_ORDEN = re.compile(r"\b(?:curl|wget|powershell|cmd\.exe|XMLHttpRequest|os\.system|subprocess|__import__)\b|"
                    r"\b(?:fetch|eval|exec)\(", re.IGNORECASE)
# Claves cuyo valor es, por norma, una dirección de procedencia o licencia.
_PROCEDENCIA = re.compile(r"general\.(.*\.)?(url|repo_url|source|doi|license(\.link)?)$|general\.base_model\.\d+\.")
MAX_CADENA = 64 * 1024 * 1024
MAX_ELEMENTOS = 10_000_000
_SHA = re.compile(r"[0-9a-f]{64}")


class ModeloError(ValueError):
    pass


class _Lector:
    def __init__(self, f, tam: int):
        self.f, self.tam = f, tam

    def num(self, fmt: str) -> Any:
        n = struct.calcsize(fmt)
        data = self.f.read(n)
        if len(data) != n:
            raise ModeloError("archivo truncado en la cabecera")
        return struct.unpack("<" + fmt, data)[0]

    def cadena(self) -> str:
        n = self.num("Q")
        if n > MAX_CADENA or n > self.tam:
            raise ModeloError(f"cadena de {n} bytes: cabecera corrupta o maliciosa")
        return self.f.read(n).decode("utf-8", "replace")

    def valor(self, tipo: int) -> Any:
        if tipo == 8:
            return self.cadena()
        if tipo == 9:
            sub, n = self.num("I"), self.num("Q")
            if n > MAX_ELEMENTOS:
                raise ModeloError(f"lista de {n} elementos: cabecera corrupta o maliciosa")
            if sub == 8:
                return [self.cadena() for _ in range(n)]
            if sub not in _ESCALARES:
                raise ModeloError(f"tipo de lista desconocido: {sub}")
            return [self.num(_ESCALARES[sub]) for _ in range(n)]
        if tipo not in _ESCALARES:
            raise ModeloError(f"tipo de metadato desconocido: {tipo}")
        return self.num(_ESCALARES[tipo])


def sha256_de(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for bloque in iter(lambda: f.read(8 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def auditar(path: str | Path, *, con_sha256: bool = True) -> dict[str, Any]:
    """Informe de un GGUF. ``hallazgos`` lista lo que merece mirarse; ``limpio`` es True si está vacía."""
    p = Path(path)
    if not p.is_file():
        raise ModeloError(f"no existe el archivo: {p}")
    tam = p.stat().st_size
    r: dict[str, Any] = {"archivo": str(p), "bytes": tam}
    hallazgos: list[str] = []
    with p.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ModeloError(f"{p.name} no es un GGUF")
        lee = _Lector(f, tam)
        version, n_tensores, n_claves = lee.num("I"), lee.num("Q"), lee.num("Q")
        if n_tensores > 1_000_000 or n_claves > 1_000_000:
            raise ModeloError("cabecera corrupta: demasiados tensores o claves")
        meta: dict[str, Any] = {}
        cadenas: list[tuple[str, str]] = []
        for _ in range(n_claves):
            clave = lee.cadena()
            valor = lee.valor(lee.num("I"))
            meta[clave] = valor
            if clave in ("tokenizer.ggml.tokens", "tokenizer.ggml.merges"):
                continue                                   # vocabulario: palabras del idioma, no órdenes
            for x in ([valor] if isinstance(valor, str) else [v for v in valor if isinstance(v, str)]
                      if isinstance(valor, list) else []):
                cadenas.append((clave, x))
        tensores = []
        for _ in range(n_tensores):
            lee.cadena()
            dims = [lee.num("Q") for _ in range(lee.num("I"))]
            tensores.append((dims, lee.num("I"), lee.num("Q")))        # dimensiones, tipo, desplazamiento
        alineacion = meta.get("general.alignment", 32)
        if not isinstance(alineacion, int) or not 1 <= alineacion <= 4096:
            raise ModeloError("alineación inválida")
        base = (f.tell() + alineacion - 1) // alineacion * alineacion
    sobrantes: int | None = None
    if tensores:
        dims, tipo, desplazamiento = max(tensores, key=lambda t: t[2])
        elementos = 1
        for d in dims:
            elementos *= d
        if tipo in _BLOQUE:
            por_bloque, bytes_bloque = _BLOQUE[tipo]
            sobrantes = tam - (base + desplazamiento + (elementos + por_bloque - 1) // por_bloque * bytes_bloque)
        else:
            hallazgos.append(f"tipo de tensor {tipo} desconocido: no se puede comprobar si sobran bytes")
    if sobrantes is not None and sobrantes != 0:
        hallazgos.append(f"sobran {sobrantes} bytes tras los tensores" if sobrantes > 0
                         else f"faltan {-sobrantes} bytes: archivo truncado")
    arquitectura = meta.get("general.architecture")
    prefijos = ("general.", "tokenizer.", "quantize.", "split.", f"{arquitectura}.")
    fuera = sorted(k for k in meta if not k.startswith(prefijos))
    if fuera:
        hallazgos.append("claves fuera de norma: " + ", ".join(fuera[:8]))
    plantilla = meta.get("tokenizer.chat_template", "")
    plantilla = plantilla if isinstance(plantilla, str) else ""
    for clave, texto in cadenas:
        es_plantilla = clave.startswith("tokenizer.chat_template")
        if not _PROCEDENCIA.search(clave) or es_plantilla:
            for m in _URL.finditer(texto):
                hallazgos.append(f"URL en «{clave}»: {m.group(0)[:120]}")
        if es_plantilla or not clave.startswith("general."):
            for m in _ORDEN.finditer(texto):
                hallazgos.append(f"posible orden en «{clave}»: {m.group(0)[:40]}")
    r.update({"version": version, "tensores": n_tensores, "claves": n_claves, "arquitectura": arquitectura,
              "nombre": meta.get("general.name"), "bytes_sobrantes": sobrantes,
              "procedencia": {k: v for k, v in meta.items() if isinstance(v, str) and _PROCEDENCIA.search(k)},
              "plantilla_bytes": len(plantilla.encode("utf-8")),
              "plantilla_sha256": hashlib.sha256(plantilla.encode("utf-8")).hexdigest() if plantilla else None,
              "hallazgos": sorted(set(hallazgos)), "limpio": not hallazgos})
    if con_sha256:
        r["sha256"] = sha256_de(p)
    return r


# ── Lista de confianza ──────────────────────────────────────────────────────────────────────────────────────────

def lista_path() -> Path:
    return Path(os.environ.get("EOLFI_MODELOS_CONFIANZA") or Path.home() / ".eolfi" / "modelos-confianza.json")


def lista() -> dict[str, Any]:
    try:
        data = json.loads(lista_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    modelos = data.get("modelos") if isinstance(data, dict) else None
    limpios = {k: v for k, v in (modelos or {}).items() if isinstance(k, str) and _SHA.fullmatch(k) and isinstance(v, dict)}
    return {"exigir": bool(isinstance(data, dict) and data.get("exigir")), "modelos": limpios}


def _guardar(data: dict[str, Any]) -> None:
    p = lista_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def confiar(path: str | Path, *, por: str, aunque_haya_hallazgos: bool = False) -> dict[str, Any]:
    """Audita el archivo y, si sale limpio, lo añade a la lista. Lo decide una persona (``por``)."""
    if not por.strip():
        raise ModeloError("falta quién lo acepta (--por)")
    informe = auditar(path)
    if not informe["limpio"] and not aunque_haya_hallazgos:
        raise ModeloError("la auditoría tiene hallazgos y no se añade: " + "; ".join(informe["hallazgos"][:5]))
    data = lista()
    data["modelos"][informe["sha256"]] = {
        "nombre": informe.get("nombre") or Path(path).name, "archivo": Path(path).name, "bytes": informe["bytes"],
        "arquitectura": informe.get("arquitectura"), "plantilla_sha256": informe.get("plantilla_sha256"),
        "hallazgos": informe["hallazgos"], "aceptado_por": por.strip()[:80],
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _guardar(data)
    return {"sha256": informe["sha256"], **data["modelos"][informe["sha256"]]}


def retirar(sha256: str) -> bool:
    data = lista()
    if data["modelos"].pop(sha256.lower(), None) is None:
        return False
    _guardar(data)
    return True


def exigir(activo: bool) -> dict[str, Any]:
    data = lista()
    if activo and not data["modelos"]:
        raise ModeloError("la lista está vacía: añade antes los modelos con «eolfi modelos confiar»")
    data["exigir"] = bool(activo)
    _guardar(data)
    return {"exigir": data["exigir"], "modelos": len(data["modelos"])}


def _cache_path() -> Path:
    return lista_path().with_name("modelos-sha256-cache.json")


def sha256_con_cache(path: str | Path) -> str:
    """SHA-256 del archivo, recordado por ruta, tamaño y fecha de modificación (hashear 7 GB tarda)."""
    p = Path(path).resolve()
    st = p.stat()
    clave = f"{p}|{st.st_size}|{st.st_mtime_ns}"
    try:
        cache = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if isinstance(cache, dict) and _SHA.fullmatch(str(cache.get(clave, ""))):
        return cache[clave]
    digest = sha256_de(p)
    cache = {k: v for k, v in (cache if isinstance(cache, dict) else {}).items() if not k.startswith(f"{p}|")}
    cache[clave] = digest
    try:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps(cache, indent=1), encoding="utf-8")
    except OSError:
        pass
    return digest


def comprobar_carga(path: str | Path) -> dict[str, Any]:
    """Antes de cargar un modelo. Con ``exigir`` activado, lanza ModeloError si no está en la lista."""
    data = lista()
    if not data["exigir"]:
        return {"exigir": False, "de_confianza": None}
    p = Path(path)
    if not p.is_file():
        raise ModeloError(f"no existe el modelo: {p}")
    digest = sha256_con_cache(p)
    if digest not in data["modelos"]:
        raise ModeloError(f"el modelo {p.name} (SHA-256 {digest[:16]}…) no está en la lista de confianza. "
                          f"Audítalo y acéptalo con «eolfi modelos confiar \"{p}\" --por TU_NOMBRE».")
    return {"exigir": True, "de_confianza": True, "sha256": digest}


# ── Conexiones de los motores en marcha ─────────────────────────────────────────────────────────────────────────

_PS_CONEXIONES = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$out = @()
foreach ($p in Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(llama-server|eolas|whisper-cli)\.exe$' }) {
  $tcp = @(Get-NetTCPConnection -OwningProcess $p.ProcessId | ForEach-Object {
    @{ estado = [string]$_.State; local = $_.LocalAddress; puerto = $_.LocalPort; remoto = $_.RemoteAddress; puerto_remoto = $_.RemotePort } })
  $udp = @(Get-NetUDPEndpoint -OwningProcess $p.ProcessId | ForEach-Object { @{ local = $_.LocalAddress; puerto = $_.LocalPort } })
  $out += @{ pid = $p.ProcessId; nombre = $p.Name; tcp = $tcp; udp = $udp }
}
ConvertTo-Json -InputObject @($out) -Depth 5 -Compress
"""
_LOCALES = ("127.0.0.1", "::1", "0.0.0.0", "::", "")


def conexiones() -> dict[str, Any]:
    """Qué escuchan y con quién hablan los motores en marcha. ``hacia_fuera`` lista lo que no es local."""
    if os.name != "nt":
        return {"disponible": False, "motivo": "solo implementado en Windows"}
    import base64

    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        out = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                              base64.b64encode(_PS_CONEXIONES.encode("utf-16-le")).decode("ascii")],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        procesos = json.loads(out.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        return {"disponible": False, "motivo": f"no se pudo consultar: {exc}"}
    procesos = [procesos] if isinstance(procesos, dict) else list(procesos or [])
    fuera, expuestos = [], []
    for p in procesos:
        for c in p.get("tcp") or []:
            if c.get("estado") == "Listen":
                if c.get("local") not in ("127.0.0.1", "::1"):
                    expuestos.append({"proceso": p["nombre"], "pid": p["pid"], "escucha_en": f'{c["local"]}:{c["puerto"]}'})
            elif c.get("remoto") not in _LOCALES:
                fuera.append({"proceso": p["nombre"], "pid": p["pid"], "destino": f'{c["remoto"]}:{c["puerto_remoto"]}'})
    return {"disponible": True, "procesos": procesos, "hacia_fuera": fuera, "expuestos_a_la_red": expuestos,
            "limpio": not fuera and not expuestos}
