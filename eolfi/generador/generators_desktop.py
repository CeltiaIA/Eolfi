"""Destino escritorio: app Electron para Windows, macOS y Linux.

La interfaz se genera con las mismas plantillas propias que el sitio estático (HTML/CSS/JS
sin dependencias) y se carga desde disco en una ventana endurecida:

- contextIsolation + sandbox, sin nodeIntegration; un preload mínimo con contextBridge.
- CSP estricta, sin navegación fuera de la app; los enlaces https se abren en el navegador.
- Una sola instancia; permisos (cámara, micro, notificaciones…) denegados por defecto.

`npm run dist` crea los instaladores con electron-builder: NSIS (.exe) en Windows,
DMG en macOS y AppImage + .deb en Linux (cada uno se compila en su propio sistema; el CI
generado lo hace en los tres).
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import Writer, _write_static_site

ELECTRON_DEV = ["electron", "electron-builder"]


def app_id(slug: str) -> str:
    seg = re.sub(r"[^a-z0-9]", "", slug.lower())[:40] or "app"
    if not seg[0].isalpha():
        seg = "app" + seg
    return f"com.eolfi.{seg}"


MAIN_JS = r"""// Proceso principal de Electron: ventana endurecida que carga la interfaz desde disco.
const { app, BrowserWindow, shell, session, Menu, protocol, net } = require("electron");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const SMOKE = process.env.APP_SMOKE === "1";   // prueba de humo: abre, comprueba y sale
const RENDERER = path.join(__dirname, "renderer");
const ORIGIN = "app://renderer/";

// Protocolo propio en lugar de file://: la página no obtiene los permisos extra de file:// (leer otros
// archivos del disco) y solo se sirve lo que hay dentro de renderer/.
protocol.registerSchemesAsPrivileged([
  { scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

// Una sola instancia: si se abre otra, se enfoca la existente.
if (!app.requestSingleInstanceLock()) {
  app.exit(0);
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 360,
    minHeight: 480,
    show: false,
    title: __TITLE__,
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: true,
    },
  });

  // Nada de navegar fuera de la app: los enlaces https externos van al navegador del sistema.
  const inside = (url) => url.startsWith(ORIGIN);
  win.webContents.on("will-navigate", (event, url) => {
    if (!inside(url)) {
      event.preventDefault();
      if (url.startsWith("https://")) shell.openExternal(url);
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });

  win.once("ready-to-show", () => { if (!SMOKE) win.show(); });
  win.loadURL(ORIGIN + "index.html");

  if (SMOKE) {
    win.webContents.once("did-finish-load", async () => {
      const title = await win.webContents.executeJavaScript("document.querySelector('h1')?.textContent ?? ''");
      const bridge = await win.webContents.executeJavaScript("typeof window.app?.version === 'string'");
      const node = await win.webContents.executeJavaScript("typeof require");
      const ok = title.length > 0 && bridge && node === "undefined";
      console.log(JSON.stringify({ smoke: ok, title, bridge, node }));
      app.exit(ok ? 0 : 1);
    });
    win.webContents.once("did-fail-load", (_e, code, desc) => { console.error(desc); app.exit(1); });
  }
  return win;
}

app.on("second-instance", () => {
  const [win] = BrowserWindow.getAllWindows();
  if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
});

app.whenReady().then(() => {
  protocol.handle("app", (request) => {
    const { host, pathname } = new URL(request.url);
    const file = path.normalize(path.join(RENDERER, decodeURIComponent(pathname)));
    if (host !== "renderer" || !file.startsWith(RENDERER + path.sep)) {
      return new Response("Prohibido", { status: 403 });   // nada fuera de renderer/ (../, otras unidades…)
    }
    return net.fetch(pathToFileURL(file).toString());
  });
  // Permisos del sistema (cámara, micrófono, ubicación, notificaciones…): denegados salvo que los añadas.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  if (process.platform !== "darwin") Menu.setApplicationMenu(null);
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();   // en macOS la app sigue en el Dock
});
"""

PRELOAD_JS = r"""// Puente mínimo y explícito entre la interfaz y Electron (nada de Node en la página).
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("app", {
  version: process.env.npm_package_version || "0.1.0",
  platform: process.platform,   // "win32" | "darwin" | "linux"
});
"""

DESKTOP_JS = r"""// Detalles de escritorio: marca la plataforma para estilos específicos (p. ej. barra de macOS).
(() => {
  const p = window.app?.platform;
  if (p) document.documentElement.dataset.platform = p;
})();
"""

TEST_JS = r"""// Pruebas sin abrir ventanas: seguridad de la configuración y estructura de la interfaz.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync, existsSync } = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const main = readFileSync(path.join(root, "main.js"), "utf8");

test("ventana endurecida: aislamiento, sandbox y sin Node en la página", () => {
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /nodeIntegration:\s*false/);
  assert.doesNotMatch(main, /webSecurity:\s*false/);
  assert.match(main, /setWindowOpenHandler/);
  assert.match(main, /will-navigate/);
  assert.match(main, /setPermissionRequestHandler/);
  assert.match(main, /protocol\.handle\("app"/, "la interfaz se sirve por app://, no por file://");
  assert.doesNotMatch(main, /loadFile\(/);
});

test("fusibles de Electron al empaquetar (sin RunAsNode ni --inspect)", () => {
  const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
  assert.equal(pkg.build.afterPack, "scripts/fuses.js");
  const fuses = readFileSync(path.join(root, "scripts", "fuses.js"), "utf8");
  for (const f of ["RunAsNode", "EnableNodeOptionsEnvironmentVariable", "EnableNodeCliInspectArguments",
    "GrantFileProtocolExtraPrivileges"]) assert.match(fuses, new RegExp(`FuseV1Options\\.${f}\\]: false`));
});

test("la interfaz tiene CSP y enlaza recursos existentes", () => {
  for (const page of __PAGES__) {
    const file = path.join(root, "renderer", page);
    const html = readFileSync(file, "utf8");
    assert.match(html, /http-equiv="Content-Security-Policy"/, `${page} sin CSP`);
    assert.match(html, /<html lang="es">/);
    assert.equal((html.match(/<h1[ >]/g) ?? []).length, 1, `${page}: debe haber un único h1`);
    for (const [, ref] of html.matchAll(/(?:href|src)="([^"#:]+\.(?:html|css|js))"/g)) {
      assert.ok(existsSync(path.join(root, "renderer", ref)), `${page} enlaza ${ref}, que no existe`);
    }
  }
});

test("instaladores configurados para Windows, macOS y Linux", () => {
  const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
  assert.ok(pkg.build.win && pkg.build.mac && pkg.build.linux);
  assert.match(pkg.build.appId, /^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$/);
});
"""

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")


def gen_desktop(spec: dict[str, Any], w: Writer) -> None:
    from eolfi.generador.generators import _routes

    pages = [("index.html" if s == "home" else f"{s}.html") for s, _p, _t in _routes(spec)]
    files: dict[str, str] = {}

    def capture(rel: str, text: str) -> None:
        files[rel] = text

    # Interfaz: las mismas plantillas del sitio estático, sin backend (los recursos API no aplican).
    _write_static_site(spec, capture, "renderer/", [])
    for rel, text in files.items():
        if rel.endswith(".html"):
            # La CSP de escritorio sustituye a la del sitio estático (una sola <meta>, no dos).
            text = re.sub(r'\s*<meta http-equiv="Content-Security-Policy"[^>]*>', "", text)
            meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
            text = re.sub(r"(<head>\s*\n?)", lambda m: m.group(1) + "  " + meta, text, count=1)  # noqa: B023 — re.sub la llama en esta misma vuelta
            text = text.replace("</body>", '  <script src="js/desktop.js"></script>\n</body>', 1)
        w(rel, text)
    w("renderer/js/desktop.js", DESKTOP_JS)
    w("main.js", MAIN_JS.replace("__TITLE__", json.dumps(spec["title"], ensure_ascii=False)))
    w("preload.js", PRELOAD_JS)
    w("test/app.test.js", TEST_JS.replace("__PAGES__", json.dumps(pages)))
    w("scripts/smoke.js", SMOKE_JS)
    w("scripts/fuses.js", FUSES_JS)
    w("package.json", json.dumps({
        "name": spec["name"], "version": "0.1.0", "private": True,
        "description": f"{spec['title']} (escritorio: Windows, macOS y Linux)",
        "main": "main.js",
        "scripts": {
            "start": "electron .",
            "test": "node --test",
            "smoke": "node scripts/smoke.js",
            "pack": "electron-builder --dir",
            "dist": "electron-builder",
            "dist:win": "electron-builder --win",
            "dist:mac": "electron-builder --mac",
            "dist:linux": "electron-builder --linux",
        },
        "devDependencies": {"electron": "latest", "electron-builder": "latest", "@electron/fuses": "latest"},
        "build": {
            "appId": app_id(spec["name"]),
            "afterPack": "scripts/fuses.js",
            "productName": spec["title"],
            "files": ["main.js", "preload.js", "renderer/**/*", "package.json"],
            "directories": {"output": "dist"},
            "win": {"target": ["nsis"]},
            "nsis": {"oneClick": False, "allowToChangeInstallationDirectory": True},
            "mac": {"target": ["dmg"], "category": "public.app-category.productivity"},
            "linux": {"target": ["AppImage", "deb"], "category": "Utility",
                      "maintainer": "Tu nombre <tu@correo.example>"},
        },
    }, indent=2, ensure_ascii=False))
    w(".gitignore.extra", "dist/\nout/\n")


FUSES_JS = r"""// Fusibles de Electron (se aplican al empaquetar, electron-builder afterPack): el ejecutable final no
// se puede usar como un Node.js cualquiera (ELECTRON_RUN_AS_NODE, NODE_OPTIONS, --inspect) y solo carga
// la app empaquetada.
const path = require("node:path");
const { flipFuses, FuseVersion, FuseV1Options } = require("@electron/fuses");

exports.default = async function afterPack(context) {
  const name = context.packager.appInfo.productFilename;
  const exe = {
    darwin: path.join(context.appOutDir, `${name}.app`),
    win32: path.join(context.appOutDir, `${name}.exe`),
  }[context.electronPlatformName] ?? path.join(context.appOutDir, context.packager.executableName);
  await flipFuses(exe, {
    version: FuseVersion.V1,
    resetAdHocDarwinSignature: context.electronPlatformName === "darwin",
    [FuseV1Options.RunAsNode]: false,
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
    [FuseV1Options.EnableNodeCliInspectArguments]: false,
    [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
    [FuseV1Options.OnlyLoadAppFromAsar]: true,
    [FuseV1Options.EnableCookieEncryption]: true,
  });
};
"""

SMOKE_JS = r"""// Prueba de humo real: arranca Electron sin mostrar la ventana, comprueba que la interfaz
// carga (h1, puente seguro y sin Node en la página) y sale con 0 o 1.
const { spawnSync } = require("node:child_process");
const electron = require("electron");   // ruta al ejecutable de Electron

const args = ["."];
if (process.platform === "linux") args.push("--no-sandbox");   // contenedores CI sin espacios de nombres
const r = spawnSync(electron, args, {
  env: { ...process.env, APP_SMOKE: "1", ELECTRON_ENABLE_LOGGING: "0" },
  encoding: "utf8",
  timeout: 60000,
});
process.stdout.write(r.stdout || "");
process.stderr.write(r.stderr || "");
if (r.status !== 0) {
  console.error(`La prueba de humo falló (código ${r.status ?? r.signal})`);
  process.exit(1);
}
console.log("Prueba de humo superada: la app de escritorio arranca y carga su interfaz.");
"""
