"""Destino escritorio nativo: app Tauri 2 (Rust + WebView del sistema) para Windows, macOS
y Linux. Pesa unos pocos MB frente a los ~100 MB de Electron.

- La interfaz son las mismas plantillas propias (HTML/CSS/JS sin dependencias).
- Seguridad: CSP en la configuración, sin `withGlobalTauri`, permisos mínimos
  (`core:default`) y ninguna orden de Rust expuesta salvo las que añadas tú.
- `npm run build` crea los instaladores del sistema donde se ejecuta: MSI/NSIS en Windows,
  .app/.dmg en macOS y AppImage/.deb/.rpm en Linux (el CI generado compila en los tres).
- `APP_SMOKE=1` arranca, espera a que cargue la página y sale (prueba de humo real).
"""
from __future__ import annotations

import json
import re
import struct
import zlib
from typing import Any

from eolfi.generador.generators import Writer, _routes, _write_static_site
from eolfi.generador.generators_desktop import CSP, app_id


def crate_name(slug: str) -> str:
    c = re.sub(r"[^a-z0-9_]", "_", slug.lower()).strip("_") or "app"
    return c if c[0].isalpha() else "app_" + c


def _png(size: int, rgb: tuple[int, int, int]) -> bytes:
    """Icono PNG (cuadrado redondeado de dos tonos), sin dependencias."""
    light = tuple(min(255, c + 70) for c in rgb)
    rows = []
    r2 = (size * 0.18) ** 2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cx = min(x, size - 1 - x)
            cy = min(y, size - 1 - y)
            k = size * 0.18
            outside = cx < k and cy < k and (k - cx) ** 2 + (k - cy) ** 2 > r2
            inner = size * 0.3 < x < size * 0.7 and size * 0.3 < y < size * 0.7
            if outside:
                row += bytes((0, 0, 0, 0))
            else:
                row += bytes((*(light if inner else rgb), 255))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _hex(c: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", c or "")
    v = m.group(1) if m else "2b6cb0"
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


MAIN_RS = r"""// Punto de entrada de la app de escritorio (Tauri 2).
// En Windows, sin consola en la versión de producción.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::webview::PageLoadEvent;
use tauri::Manager;

fn main() {
    // Prueba de humo: arranca, espera a que la interfaz cargue y sale con código 0.
    let smoke = std::env::var("APP_SMOKE").map(|v| v == "1").unwrap_or(false);
    tauri::Builder::default()
        .on_page_load(move |webview, payload| {
            if smoke && matches!(payload.event(), PageLoadEvent::Finished) {
                println!("{{\"smoke\":true,\"url\":\"{}\"}}", payload.url());
                webview.app_handle().exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("no se pudo arrancar la aplicación");
}
"""

TEST_JS = r"""// Pruebas sin compilar: seguridad de la configuración e interfaz.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

const conf = JSON.parse(readFileSync("src-tauri/tauri.conf.json", "utf8"));
const caps = JSON.parse(readFileSync("src-tauri/capabilities/default.json", "utf8"));

test("CSP estricta y sin API global de Tauri en la página", () => {
  assert.match(conf.app.security.csp, /default-src 'self'/);
  assert.doesNotMatch(conf.app.security.csp, /unsafe-eval/);
  assert.notEqual(conf.app.withGlobalTauri, true);
});

test("permisos mínimos: solo core:default", () => {
  assert.deepEqual(caps.permissions, ["core:default"]);
});

test("instaladores para todos los sistemas e identificador válido", () => {
  assert.equal(conf.bundle.targets, "all");
  assert.match(conf.identifier, /^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$/);
});

test("la interfaz enlaza recursos existentes", () => {
  for (const page of __PAGES__) {
    const html = readFileSync(`src/${page}`, "utf8");
    assert.match(html, /<html lang="es">/);
    assert.equal((html.match(/<h1[ >]/g) ?? []).length, 1, `${page}: un único h1`);
    for (const [, ref] of html.matchAll(/(?:href|src)="([^"#:]+\.(?:html|css|js))"/g)) {
      assert.ok(existsSync(`src/${ref}`), `${page} enlaza ${ref}, que no existe`);
    }
  }
});
"""


def gen_tauri(spec: dict[str, Any], w: Writer) -> None:
    pages = [("index.html" if s == "home" else f"{s}.html") for s, _p, _t in _routes(spec)]
    crate = crate_name(spec["name"])
    _write_static_site(spec, w, "src/", [])
    w("src-tauri/Cargo.toml", f"""[package]
name = "{crate}"
version = "0.1.0"
description = "{spec['title']}"
edition = "2021"

[build-dependencies]
tauri-build = {{ version = "2", features = [] }}

[dependencies]
tauri = {{ version = "2", features = [] }}

[profile.release]
codegen-units = 1
lto = true
opt-level = "s"
panic = "abort"
strip = true
""")
    w("src-tauri/build.rs", "fn main() {\n    tauri_build::build()\n}\n")
    w("src-tauri/src/main.rs", MAIN_RS)
    w("src-tauri/tauri.conf.json", json.dumps({
        "$schema": "https://schema.tauri.app/config/2",
        "productName": spec["title"],
        "version": "0.1.0",
        "identifier": app_id(spec["name"]),
        "build": {"frontendDist": "../src"},
        "app": {
            "withGlobalTauri": False,
            "windows": [{"label": "main", "title": spec["title"], "width": 1100, "height": 760,
                         "minWidth": 360, "minHeight": 480}],
            "security": {"csp": CSP},
        },
        "bundle": {
            "active": True,
            "targets": "all",
            "icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png",
                     "icons/icon.icns", "icons/icon.ico"],
        },
    }, indent=2, ensure_ascii=False))
    w("src-tauri/capabilities/default.json", json.dumps({
        "$schema": "../gen/schemas/desktop-schema.json",
        "identifier": "default",
        "description": "Permisos mínimos de la ventana principal",
        "windows": ["main"],
        "permissions": ["core:default"],
    }, indent=2))
    w("src-tauri/.gitignore", "/target/\n/gen/schemas\n")
    w("test/config.test.mjs", TEST_JS.replace("__PAGES__", json.dumps(pages)))
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True, "type": "module",
        "scripts": {
            "tauri": "tauri",
            "icons": "tauri icon src-tauri/icons/icon.png",
            "dev": "tauri dev",
            "build": "tauri build",
            "build:debug": "tauri build --debug --no-bundle",
            "test": "node --test",
        },
        "devDependencies": {"@tauri-apps/cli": "latest"},
    }, indent=2, ensure_ascii=False))
    # Icono de partida (los demás tamaños y .icns/.ico los genera `npm run icons`).
    png = _png(512, _hex((spec.get("design", {}).get("palette") or {}).get("primary", "")))
    w_bytes = getattr(w, "write_bytes", None)
    if w_bytes:
        w_bytes("src-tauri/icons/icon.png", png)
    else:
        w("src-tauri/icons/icon.png.b64", __import__("base64").b64encode(png).decode())
