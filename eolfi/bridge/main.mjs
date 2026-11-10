// Puente Electron de Eolfi para DeepSeek web, Gemini web y Meta AI web.
// Arranque: python -m eolfi bridge   (o: npx electron .  en esta carpeta)
//
// Abre una ventana por proveedor con sesión persistente: inicias sesión a mano
// una vez y queda guardada en el perfil del puente. Eolfi envía las peticiones a
// una pasarela local con token; cada envío pide tu permiso en un diálogo.
// Automatizar estas webs puede ir contra sus condiciones de uso: úsalo bajo tu cuenta y responsabilidad.
import { app, BrowserWindow, dialog, session } from 'electron';
import { allowedNavigation as policyAllowed, siteSuffixes, permissionDecision, DENIED_PERMISSIONS } from './policy.mjs';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { DEEPSEEK_ORIGIN, DeepseekAdapter } from './adapters/deepseek.mjs';
import { GEMINI_ORIGIN, GeminiAdapter } from './adapters/gemini.mjs';
import { META_ORIGIN, MetaAdapter } from './adapters/meta.mjs';
import { startBridgeServer } from './server.mjs';
import { createApprover } from './approval.mjs';
import { loadSites, makeDeclarativeAdapter } from './adapters/declarative.mjs';
import { ChromeEngine, findBrowser } from './engine/chrome.mjs';

const BRIDGE_FILE = process.env.EOLFI_BRIDGE_FILE || join(homedir(), '.eolfi', 'bridge.json');
const SITES = {
  deepseek: { url: `${DEEPSEEK_ORIGIN}/`, origin: DEEPSEEK_ORIGIN, Adapter: DeepseekAdapter, title: 'DeepSeek web' },
  gemini: { url: `${GEMINI_ORIGIN}/app`, origin: GEMINI_ORIGIN, Adapter: GeminiAdapter, title: 'Gemini web' },
  meta: { url: META_ORIGIN, origin: META_ORIGIN, Adapter: MetaAdapter, title: 'Meta AI web' },
};
// Chats descritos con selectores (adapters/sites.json + ~/.eolfi/bridge-sites.json para recalibrar).
// EOLFI_BRIDGE_CHATS=deepseek,gemini,chatgpt limita qué ventanas se abren al arrancar.
for (const [name, cfg] of Object.entries(loadSites())) {
  SITES[name] = { url: cfg.home, origin: cfg.origin, Adapter: makeDeclarativeAdapter(cfg), title: cfg.title,
    authHostSuffixes: [...siteSuffixes(name), ...(cfg.authHostSuffixes || [])] };
}
for (const name of ['deepseek', 'gemini', 'meta']) SITES[name].authHostSuffixes = siteSuffixes(name);
const STARTUP = (process.env.EOLFI_BRIDGE_CHATS || 'deepseek,gemini,meta,lechat').split(',').map((s) => s.trim()).filter((s) => SITES[s]);
const AUTH_HOSTS = new Set(['accounts.google.com', 'myaccount.google.com', 'appleid.apple.com', 'account.apple.com',
  'auth.meta.com', 'accountscenter.meta.com', 'www.facebook.com', 'www.instagram.com']);
const windows = {};
const adapters = {};

// Motor: navegador real (Chrome/Edge/Brave… por CDP; por defecto si hay uno instalado,
// porque Google bloquea el inicio de sesión dentro de Electron) o ventanas de Electron.
let ENGINE = (process.env.EOLFI_ENGINE || '').toLowerCase();
let browserEngine = null;
if (ENGINE !== 'electron') {
  try {
    const exe = findBrowser(process.env.EOLFI_BROWSER || '');
    if (exe) { browserEngine = new ChromeEngine({ browser: exe, log: (m) => console.log(m),
      policy: { allowed: (name, url) => allowedNavigation(name, url), deniedPermissions: DENIED_PERMISSIONS } }); ENGINE = 'browser'; }
    else ENGINE = 'electron';
  } catch (e) {
    console.error(String(e.message || e));
    app.exit(2);
    process.exit(2);   // app.exit() no corta el módulo: sin esto seguía arrancando (B6)
  }
}
const engineLabel = () => (ENGINE === 'browser' ? browserEngine.name : 'Electron');

// Adaptador "en reposo" para el estado cuando la ventana del sitio está cerrada (no la reabre).
const closed = (name) => ({ status: async () => ({ ok: false, detail: `Ventana de ${SITES[name].title} cerrada: se abrirá al enviar o al pulsar su pestaña` }) });

// Agente de usuario de Chrome sin la marca de Electron (algunos inicios de sesión la rechazan).
app.userAgentFallback = app.userAgentFallback.replace(/ Electron\/\S+/, '').replace(/ eolfi-bridge\/\S+/, '');
if (!app.requestSingleInstanceLock()) {
  // Ya hay un puente: salir YA (app.quit() dejaría seguir el módulo y pisaría bridge.json).
  console.error('Ya hay un puente de Eolfi en marcha.');
  app.exit(0);
  process.exit(0);
}

function allowedNavigation(name, target) {
  return policyAllowed(SITES[name], target, AUTH_HOSTS);
}

function openWindow(name) {
  if (windows[name] && !windows[name].isDestroyed()) return windows[name];
  const site = SITES[name];
  const ses = session.fromPartition(`persist:eolfi-${name}`);
  ses.setPermissionRequestHandler((wc, perm, cb, details) => cb(permissionDecision(SITES[name], perm, details?.requestingUrl || wc.getURL())));
  ses.setPermissionCheckHandler((wc, perm, origin) => permissionDecision(SITES[name], perm, origin));
  const win = new BrowserWindow({
    width: 1100, height: 820, title: `Eolfi · ${site.title}`,
    webPreferences: { partition: `persist:eolfi-${name}`, contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.webContents.setWindowOpenHandler(({ url }) => (allowedNavigation(name, url) ? { action: 'allow' } : { action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => { if (!allowedNavigation(name, url)) event.preventDefault(); });
  win.on('page-title-updated', (event) => event.preventDefault());
  win.on('closed', () => { delete windows[name]; delete adapters[name]; });
  win.loadURL(site.url);
  windows[name] = win;
  return win;
}

async function getAdapter(name, { peek = false } = {}) {
  const cached = adapters[name];
  if (cached && !cached.contents.isDestroyed()) return cached;
  if (ENGINE === 'browser') {
    if (peek && !browserEngine.pages.get(name)) return closed(name);
    const contents = await browserEngine.page(name, SITES[name].url, SITES[name].origin);
    // El adaptador se conserva (conversaciones, turnos dudosos, URL activa): solo se cambia la pestaña.
    if (adapters[name]) Object.assign(adapters[name], { contents, current: null, lastUrl: null });   // pestaña nueva: la conversación activa ya no se sabe
    else adapters[name] = new SITES[name].Adapter(contents);
    return adapters[name];
  }
  if (peek && !(windows[name] && !windows[name].isDestroyed())) return closed(name);
  const win = openWindow(name);
  adapters[name] = new SITES[name].Adapter(win.webContents);
  return adapters[name];
}

// La vista en directo NO reabre lo que el usuario cerró (M1): 404 «ventana cerrada».
function closedError(name) {
  const e = new Error(`Ventana de ${SITES[name].title} cerrada: envía un mensaje para volver a abrirla`);
  e.status = 404;
  return e;
}
async function liveContents(name) {
  const a = await getAdapter(name, { peek: true });
  if (!a.contents) throw closedError(name);
  return a.contents;
}

// Captura reducida de la ventana del chat, para la vista en directo del panel de Eolfi.
async function screen(name) {
  if (ENGINE === 'browser') return (await liveContents(name)).screenshot();
  if (!(windows[name] && !windows[name].isDestroyed())) throw closedError(name);
  const win = windows[name];
  const image = await win.webContents.capturePage();
  const size = image.getSize();
  const scaled = size.width > 960 ? image.resize({ width: 960, quality: 'good' }) : image;
  return scaled.toJPEG(62);
}

// Entrada remota desde el panel (clic, rueda, tecla, texto) sobre la ventana del sitio.
async function input(name, ev) {
  if (ENGINE === 'browser') {
    const c = await liveContents(name);
    if (ev.type === 'click') return c.click(ev.x, ev.y);
    if (ev.type === 'wheel') return c.wheel(ev.x, ev.y, ev.deltaY);
    if (ev.type === 'key') return c.key(ev.key);
    return c.typeText(ev.text);
  }
  if (!(windows[name] && !windows[name].isDestroyed())) throw closedError(name);
  const wc = windows[name].webContents;
  const [w, h] = windows[name].getContentSize();
  const x = Math.round((ev.x ?? 0) * w), y = Math.round((ev.y ?? 0) * h);
  if (ev.type === 'click') {
    wc.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
  } else if (ev.type === 'wheel') wc.sendInputEvent({ type: 'mouseWheel', x, y, deltaX: 0, deltaY: -ev.deltaY });
  else if (ev.type === 'key') { wc.sendInputEvent({ type: 'keyDown', keyCode: ev.key }); wc.sendInputEvent({ type: 'keyUp', keyCode: ev.key }); }
  else await wc.insertText(ev.text);
}

// Aprobación (módulo propio y probado: approval.mjs).
const approver = createApprover({
  titleOf: (p) => SITES[p]?.title || p,
  beforeShow: (p) => { if (ENGINE !== 'electron') return null; const w = openWindow(p); w.show(); return w; },
  showMessageBox: (win, options) => (win ? dialog.showMessageBox(win, options) : dialog.showMessageBox(options)),
});
const { approve, grants, revoke } = approver;

// bridge.json lleva las credenciales: se escribe entero de una vez (archivo temporal + renombrar) y, en
// Windows, con permisos solo para el usuario actual (mode 0o600 no hace nada allí; B7).
function writeBridgeFile(data) {
  const tmp = `${BRIDGE_FILE}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(data), { mode: 0o600 });
  if (process.platform === 'win32' && process.env.USERNAME) {
    try {
      execFileSync('icacls', [tmp, '/inheritance:r', '/grant:r', `${process.env.USERNAME}:F`], { stdio: 'ignore', windowsHide: true });
    } catch { /* sin icacls: queda con los permisos heredados de ~/.eolfi */ }
  }
  renameSync(tmp, BRIDGE_FILE);
}

app.whenReady().then(async () => {
  const token = randomBytes(32).toString('hex');        // Eolfi automático: cada envío pide aprobación
  const panelToken = randomBytes(32).toString('hex');   // panel de Eolfi: lo que teclea el usuario
  const { port } = await startBridgeServer({
    adapters: Object.fromEntries(Object.keys(SITES).map((n) => [n, (opts) => getAdapter(n, opts)])),
    info: () => ({ engine: engineLabel(), grants: grants() }),
    revoke,
    inputs: Object.fromEntries(Object.keys(SITES).map((n) => [n, (ev) => input(n, ev)])),
    approve, token, panelToken, log: (m) => console.log(m),
    screens: Object.fromEntries(Object.keys(SITES).map((n) => [n, () => screen(n)])),
  });
  mkdirSync(dirname(BRIDGE_FILE), { recursive: true });
  writeBridgeFile({ url: `http://127.0.0.1:${port}`, token, panelToken, pid: process.pid, providers: Object.keys(SITES), engine: engineLabel() });
  console.log(`Puente de Eolfi escuchando en http://127.0.0.1:${port} con ${engineLabel()} (credenciales en ${BRIDGE_FILE})`);
  console.log('Inicia sesión en sus ventanas; después usa --provider deepseek-web | gemini-web | meta-web | lechat-web.');
  // Las pestañas se abren DESPUÉS de escuchar y en paralelo (antes: en serie y sin responder mientras tanto).
  await Promise.all(STARTUP.map((name) => (ENGINE === 'browser'
    ? getAdapter(name).catch((e) => console.error(`${name}: ${e.message}`))
    : Promise.resolve(openWindow(name)))));
});

app.on('window-all-closed', () => { /* el puente sigue activo: las ventanas se reabren al recibir una petición */ });
app.on('before-quit', () => {
  browserEngine?.stop();
  try {   // solo si bridge.json es NUESTRO (otra instancia podría haberlo escrito)
    if (JSON.parse(readFileSync(BRIDGE_FILE, 'utf8')).pid === process.pid) rmSync(BRIDGE_FILE, { force: true });
  } catch { /* ya borrado o ilegible */ }
});
