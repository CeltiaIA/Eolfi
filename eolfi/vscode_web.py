"""VS Code dentro del panel de Eolfi: `code serve-web` (la versión web de tu VS Code) en 127.0.0.1 con token.

- Solo arranca si el usuario ha aceptado en el panel la licencia del servidor de VS Code (la primera vez se
  descarga de Microsoft). La aceptación se recuerda en ~/.eolfi/vscode-web-license.
- Escucha en 127.0.0.1, puerto libre, con un token aleatorio por arranque; el panel lo muestra en un iframe.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LICENSE_URL = "https://aka.ms/vscode-server-license"
STATE_DIR = Path(os.environ.get("EOLFI_HOME") or Path.home() / ".eolfi")


class VSCodeWeb:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.token: str | None = None
        self.folder: str | None = None
        self.lock = threading.Lock()
        self.log: list[str] = []

    @property
    def license_file(self) -> Path:
        return STATE_DIR / "vscode-web-license"

    def license_accepted(self) -> bool:
        return self.license_file.is_file()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def url(self, folder: str | None = None) -> str | None:
        if not self.running():
            return None
        q = {"tkn": self.token}
        f = folder or self.folder
        if f:
            # VS Code web abre carpetas locales del servidor con ?folder=<ruta en formato URI>.
            q["folder"] = "/" + Path(f).resolve().as_posix().lstrip("/")
        return f"http://127.0.0.1:{self.port}/?{urllib.parse.urlencode(q)}"

    def status(self) -> dict[str, Any]:
        code = shutil.which("code") or shutil.which("code-insiders")
        return {"available": bool(code), "license_accepted": self.license_accepted(), "license_url": LICENSE_URL,
                "running": self.running(), "folder": self.folder, "url": self.url(), "log": self.log[-5:]}

    def start(self, folder: str | None, accept_license: bool = False, wait: float = 240.0) -> dict[str, Any]:
        code = shutil.which("code") or shutil.which("code-insiders")
        if not code:
            raise FileNotFoundError("No se encuentra el comando «code» de VS Code")
        if not self.license_accepted():
            if not accept_license:
                raise PermissionError("Hay que aceptar la licencia del servidor de VS Code en el panel")
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.license_file.write_text(f"aceptada en el panel de Eolfi: {time.strftime('%Y-%m-%d %H:%M')}\n",
                                         encoding="utf-8")
        with self.lock:
            if self.running():
                if folder:
                    self.folder = folder
                return self.status()
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
            self.token = secrets.token_hex(24)
            self.folder = folder
            cmd = [code, "serve-web", "--host", "127.0.0.1", "--port", str(self.port),
                   "--connection-token", self.token, "--accept-server-license-terms", "--disable-telemetry",
                   "--server-data-dir", str(STATE_DIR / "vscode-web")]
            if folder:
                cmd += ["--default-folder", str(Path(folder).resolve())]
            self.log = []
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         text=True, encoding="utf-8", errors="replace",
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            threading.Thread(target=self._pump, daemon=True).start()
        # La primera vez descarga el servidor: se espera a que responda.
        deadline = time.time() + wait
        while time.time() < deadline:
            if not self.running():
                raise RuntimeError("code serve-web terminó: " + " | ".join(self.log[-3:]))
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/?tkn={self.token}", timeout=3) as r:
                    if r.status < 500:
                        return self.status()
            except OSError:
                time.sleep(1)
        raise TimeoutError("VS Code web no respondió a tiempo (la primera vez descarga el servidor: vuelve a intentarlo)")

    def _pump(self) -> None:
        proc = self.proc
        for line in proc.stdout if proc and proc.stdout else []:
            line = line.strip()
            if line:
                # El token no se guarda en el registro.
                self.log.append(line.replace(self.token or "\0", "***")[:300])
                del self.log[:-200]

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.running():
                if os.name == "nt":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True)
                else:
                    self.proc.terminate()
            self.proc = None
        return self.status()
