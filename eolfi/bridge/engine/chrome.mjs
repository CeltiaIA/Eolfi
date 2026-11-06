// Motor de navegador real para el puente: controla Chrome / Edge instalados por CDP
// (Chrome DevTools Protocol), sin dependencias.
//
// Por qué: Google (y otros) bloquean el inicio de sesión dentro de Electron
// ("Es posible que el navegador o la aplicación no sean seguros"). En un Chrome o
// Edge reales el inicio de sesión funciona con normalidad.
//
// - Perfil propio de Eolfi (~/.eolfi/browser-profile): no toca tu perfil personal.
// - Control por TUBERÍA privada (--remote-debugging-pipe), sin ningún puerto TCP: ningún
//   otro proceso ni usuario del equipo puede conectarse al navegador ni leer sus cookies.
//   No se activa el modo de automatización (--enable-automation): la web ve un navegador normal.
// - Cada web va en su propia ventana para que se renderice y se pueda capturar.
// - CdpContents imita la parte de WebContents de Electron que usan los adaptadores
//   (getURL, loadURL, executeJavaScript, insertText, sendInputEvent, focus,
//   isDestroyed), de modo que los adaptadores no cambian.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const LOCAL = process.env.LOCALAPPDATA || '';
const PF = process.env.ProgramFiles || 'C:/Program Files';
const PF86 = process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)';

// Navegadores basados en Chromium (todos hablan CDP). Firefox no: retiró CDP.
export const BROWSERS = {
  chrome: [join(PF, 'Google/Chrome/Application/chrome.exe'), join(PF86, 'Google/Chrome/Application/chrome.exe'),
    join(LOCAL, 'Google/Chrome/Application/chrome.exe'), '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'],
  edge: [join(PF86, 'Microsoft/Edge/Application/msedge.exe'), join(PF, 'Microsoft/Edge/Application/msedge.exe'),
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/usr/bin/microsoft-edge'],
  brave: [join(PF, 'BraveSoftware/Brave-Browser/Application/brave.exe'), join(LOCAL, 'BraveSoftware/Brave-Browser/Application/brave.exe'),
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser', '/usr/bin/brave-browser'],
  opera: [join(LOCAL, 'Programs/Opera/opera.exe'), join(PF, 'Opera/opera.exe'), '/Applications/Opera.app/Contents/MacOS/Opera'],
  vivaldi: [join(LOCAL, 'Vivaldi/Application/vivaldi.exe'), join(PF, 'Vivaldi/Application/vivaldi.exe'),
    '/Applications/Vivaldi.app/Contents/MacOS/Vivaldi'],
  chromium: [join(LOCAL, 'Chromium/Application/chrome.exe'), '/usr/bin/chromium', '/usr/bin/chromium-browser'],
};

// Navegadores instalados: { nombre: ruta }.
export function installedBrowsers() {
  const out = {};
  for (const [name, paths] of Object.entries(BROWSERS)) {
    const hit = paths.find((p) => p && existsSync(p));
    if (hit) out[name] = hit;
  }
  return out;
}

// choice: nombre (chrome, edge, brave…), ruta a un ejecutable, o vacío = el primero instalado.
export function findBrowser(choice = process.env.EOLFI_BROWSER) {
  const installed = installedBrowsers();
  if (choice) {
    if (installed[choice.toLowerCase()]) return installed[choice.toLowerCase()];
    if (existsSync(choice)) return choice;
    throw new Error(`Navegador '${choice}' no encontrado. Instalados: ${Object.keys(installed).join(', ') || 'ninguno'}`);
  }
  return Object.values(installed)[0] || null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Conexión CDP por la tubería del propio proceso (fd 3 = escritura, fd 4 = lectura); cada
// mensaje es JSON terminado en \0. Una sola conexión para todo el navegador; las pestañas se
// controlan con sesiones (Target.attachToTarget con flatten).
export class PipeConnection {
  constructor(proc) {
    this.proc = proc;
    this.out = proc.stdio[3];
    this.id = 0;
    this.pending = new Map();
    this.handlers = new Map();     // `${sessionId}|${método}` -> [handler]
    this.closed = false;
    let buf = '';
    let scan = 0;   // hasta dónde ya se buscó el \0: un mensaje grande en muchos trozos no se re-examina entero
    proc.stdio[4].setEncoding('utf8');
    proc.stdio[4].on('data', (chunk) => {
      buf += chunk;
      let i;
      while ((i = buf.indexOf('\0', scan)) >= 0) {
        const raw = buf.slice(0, i);
        buf = buf.slice(i + 1);
        scan = 0;
        if (!raw) continue;
        let msg;
        try { msg = JSON.parse(raw); } catch { continue; }   // mensaje corrupto: se ignora, no tumba el puente (A4)
        try { this._dispatch(msg); } catch (e) { console.error(`CDP: ${e?.message || e}`); }
      }
      scan = buf.length;
    });
    const end = () => this._close();
    proc.stdio[4].on('close', end);
    proc.stdio[4].on('error', end);
    this.out.on('error', end);
    proc.on('exit', end);
    proc.on('error', end);   // EACCES/ENOENT al lanzar: sin manejador tumbaba el proceso (A4)
  }

  _dispatch(msg) {
    if (msg.id && this.pending.has(msg.id)) {
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message || 'error CDP'));
      else resolve(msg.result);
    } else if (msg.method) {
      this.handlers.get(`${msg.sessionId ?? ''}|${msg.method}`)?.slice().forEach((h) => h(msg.params));
    }
  }

  _close() {
    if (this.closed) return;
    this.closed = true;
    for (const { reject } of this.pending.values()) reject(new Error('El navegador cerró la conexión'));
    this.pending.clear();
    this.handlers.get('|close')?.slice().forEach((h) => h());
  }

  send(method, params = {}, sessionId, timeout = 30000) {
    if (this.closed) return Promise.reject(new Error('El navegador cerró la conexión'));
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP ${method}: sin respuesta`)); }, timeout);
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      });
      this.out.write(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }) + '\0');
    });
  }

  on(key, handler) {
    if (!this.handlers.has(key)) this.handlers.set(key, []);
    this.handlers.get(key).push(handler);
  }

  off(key, handler) {
    const list = this.handlers.get(key);
    const i = list ? list.indexOf(handler) : -1;
    if (i >= 0) list.splice(i, 1);
  }
}

// Vista de la conexión ligada a una sesión (o al navegador si sessionId es vacío). Tiene la
// misma forma que la antigua conexión por WebSocket: send / on / off / closed / close.
export class CdpSession {
  constructor(conn, sessionId = '', root = null) {
    this.conn = conn;
    this.sessionId = sessionId;
    this.root = root || this;        // sesión del navegador (para Browser.* y Target.*)
    this._closed = false;
  }

  get closed() { return this._closed || this.conn.closed; }

  send(method, params = {}, timeout = 30000) {
    if (this._closed) return Promise.reject(new Error('La pestaña se cerró'));
    return this.conn.send(method, params, this.sessionId || undefined, timeout);
  }

  on(event, handler) { this.conn.on(`${event === 'close' ? '' : this.sessionId}|${event}`, handler); }
  off(event, handler) { this.conn.off(`${event === 'close' ? '' : this.sessionId}|${event}`, handler); }

  _markClosed() {
    if (this._closed) return;
    this._closed = true;
    this.conn.handlers.get(`${this.sessionId}|#closed`)?.slice().forEach((h) => h());
    // Fuera todos los manejadores de esta sesión: antes se acumulaban al cerrar y reabrir pestañas (B4).
    for (const key of [...this.conn.handlers.keys()]) if (key.startsWith(`${this.sessionId}|`)) this.conn.handlers.delete(key);
  }

  close() {
    if (this.sessionId && !this.closed) this.conn.send('Target.detachFromTarget', { sessionId: this.sessionId }).catch(() => {});
    this._markClosed();
  }
}

// Solo para migrar: cerrar un navegador antiguo de Eolfi que aún escuchaba en un puerto TCP.
async function closeLegacyBrowser(wsUrl) {
  await new Promise((resolve) => {
    let ws;
    try { ws = new WebSocket(wsUrl); } catch { resolve(); return; }
    const done = () => { try { ws.close(); } catch { /* cerrado */ } resolve(); };
    ws.onopen = () => { ws.send(JSON.stringify({ id: 1, method: 'Browser.close' })); setTimeout(done, 500); };
    ws.onerror = done;
    setTimeout(done, 3000);
  });
}

// Equivalente mínimo de Electron.WebContents sobre una pestaña de Chrome.
export class CdpContents {
  constructor(cdp, targetId, url) {
    this.cdp = cdp;
    this.targetId = targetId;
    this.url = url || '';
    cdp.on('Page.frameNavigated', ({ frame }) => { if (!frame.parentId) this.url = frame.url; });
    cdp.on('Page.navigatedWithinDocument', ({ url }) => { if (url) this.url = url; });
  }

  static async attach(session, targetId, url) {
    const cdp = session;
    const c = new CdpContents(cdp, targetId, url);
    await cdp.send('Page.enable');
    const { result } = await cdp.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    c.url = result?.value || c.url;
    return c;
  }

  isDestroyed() { return this.cdp.closed; }
  getURL() { return this.url; }
  getType() { return 'browser'; }

  // Espera la carga de ESTA navegación (por loaderId del marco principal), sin dejar
  // listeners ni temporizadores colgando entre llamadas.
  async loadURL(url) {
    let loaderId = null, wake = () => {}, timer;
    const loadedLoaders = new Set();
    const onLife = (e) => {
      if (e.name !== 'load' || e.frameId !== this.targetId) return;   // solo el marco principal
      loadedLoaders.add(e.loaderId);
      if (loaderId && e.loaderId === loaderId) wake();
    };
    this.cdp.on('Page.lifecycleEvent', onLife);
    try {
      await this.cdp.send('Page.setLifecycleEventsEnabled', { enabled: true }).catch(() => {});
      const r = await this.cdp.send('Page.navigate', { url });
      if (r.errorText) throw new Error(`No se pudo abrir ${url}: ${r.errorText}`);
      loaderId = r.loaderId || null;
      if (!loaderId || loadedLoaders.has(loaderId)) return;   // mismo documento (#hash) o ya cargado
      await new Promise((resolve) => { wake = resolve; timer = setTimeout(resolve, 20000); });
    } finally {
      clearTimeout(timer);
      this.cdp.off('Page.lifecycleEvent', onLife);
    }
  }

  async executeJavaScript(expression) {
    const r = await this.cdp.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error(d.exception?.description?.split('\n')[0] || d.text || 'Error en la página');
    }
    return r.result?.value;
  }

  insertText(text) { return this.cdp.send('Input.insertText', { text }); }

  sendInputEvent({ type, keyCode }) {
    if (keyCode !== 'Enter') throw new Error(`tecla no soportada: ${keyCode}`);
    const base = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
    // rawKeyDown sin carácter: con 'keyDown' + text '\r' Chrome emite además un carácter de
    // retorno, y webs como Gemini lo toman como un segundo envío (error y texto devuelto a la caja).
    return this.cdp.send('Input.dispatchKeyEvent', type === 'keyDown' ? { type: 'rawKeyDown', ...base } : { type: 'keyUp', ...base });
  }

  // Antes de interactuar: si la ventana está minimizada, restaurarla. Una página oculta no se
  // pinta (Gemini deja la respuesta vacía, Meta no monta su editor).
  async ensureVisible() {
    const state = await this.executeJavaScript('document.visibilityState').catch(() => 'visible');
    if (state !== 'hidden') return;
    try {
      const browser = this.cdp.root ?? this.cdp;   // Browser.* va por la sesión del navegador
      const { windowId, bounds } = await browser.send('Browser.getWindowForTarget', { targetId: this.targetId });
      if (bounds?.windowState === 'minimized') {
        await browser.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'normal' } });
      }
    } catch { /* sin acceso a la ventana: se intenta igualmente */ }
    for (let i = 0; i < 20; i++) {
      if (await this.executeJavaScript('document.visibilityState').catch(() => 'visible') !== 'hidden') return;
      await sleep(150);
    }
  }

  async focus() {
    await this.ensureVisible();
    return this.cdp.send('Page.bringToFront').catch(() => {});
  }

  // Entrada remota desde el panel. x, y normalizados (0..1) sobre la captura.
  async viewport() {
    const v = await this.executeJavaScript('({ w: innerWidth, h: innerHeight })');
    return { w: v?.w || 1280, h: v?.h || 800 };
  }

  async click(nx, ny) {
    const { w, h } = await this.viewport();
    const x = Math.round(nx * w), y = Math.round(ny * h);
    const base = { x, y, button: 'left', clickCount: 1 };
    await this.cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await this.cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...base });
    await this.cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...base });
  }

  async wheel(nx, ny, deltaY) {
    const { w, h } = await this.viewport();
    await this.cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: Math.round(nx * w), y: Math.round(ny * h), deltaX: 0, deltaY });
  }

  async key(name) {
    // Object.hasOwn: «__proto__» o «constructor» no son teclas (B3).
    if (typeof name !== 'string' || !Object.hasOwn(KEYS, name)) throw new Error(`tecla no soportada: ${name}`);
    const k = KEYS[name];
    // keyDown con su texto: un único evento de pulsación. rawKeyDown + char aparte podía enviar dos
    // veces en Gemini (Intro = enviar).
    await this.cdp.send('Input.dispatchKeyEvent', { type: k.text ? 'keyDown' : 'rawKeyDown', ...k });
    await this.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...k });
  }

  typeText(text) { return this.cdp.send('Input.insertText', { text }); }

  async screenshot(quality = 62, maxWidth = 960) {
    // Una sola evaluación: visibilidad y tamaño. Minimizada no se pinta y la captura se colgaría.
    const st = await this.executeJavaScript('({ v: document.visibilityState, w: innerWidth, h: innerHeight })')
      .catch(() => ({ v: 'visible' }));
    if (st.v === 'hidden') throw new Error('La ventana de este chat está minimizada u oculta: restáurala para ver la vista en directo');
    const params = { format: 'jpeg', quality, optimizeForSpeed: true };
    // Escalada en el navegador (antes: resolución completa según el DPR, varias veces más bytes).
    if (st.w > 0 && st.h > 0) params.clip = { x: 0, y: 0, width: st.w, height: st.h, scale: Math.min(1, maxWidth / st.w) };
    const { data } = await this.cdp.send('Page.captureScreenshot', params, 8000);
    return Buffer.from(data, 'base64');
  }

  close() { this.cdp.close(); }
}

const KEYS = {
  Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
  Backspace: { key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 },
  Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 },
  Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 },
  Delete: { key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46 },
  ArrowUp: { key: 'ArrowUp', code: 'ArrowUp', windowsVirtualKeyCode: 38 },
  ArrowDown: { key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40 },
  ArrowLeft: { key: 'ArrowLeft', code: 'ArrowLeft', windowsVirtualKeyCode: 37 },
  ArrowRight: { key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 },
  PageDown: { key: 'PageDown', code: 'PageDown', windowsVirtualKeyCode: 34 },
  PageUp: { key: 'PageUp', code: 'PageUp', windowsVirtualKeyCode: 33 },
};
export const SUPPORTED_KEYS = Object.keys(KEYS);

// Las sesiones se guardan en el perfil de Eolfi. Además se pide "continuar donde lo
// dejaste", para que Chrome conserve también las cookies de sesión al cerrarse: así,
// una vez iniciada la sesión en cada chat, el puente la reutiliza sin volver a entrar.
function keepSessions(profile) {
  const dir = join(profile, 'Default');
  const file = join(dir, 'Preferences');
  try {
    mkdirSync(dir, { recursive: true });
    const prefs = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
    prefs.session = { ...(prefs.session || {}), restore_on_startup: 1 };
    prefs.profile = { ...(prefs.profile || {}), exit_type: 'Normal', exited_cleanly: true };
    writeFileSync(file, JSON.stringify(prefs));
  } catch { /* si el perfil está en uso o es ilegible, se deja como está */ }
}

// Navegador real con perfil propio y una ventana por sitio.
// login.lock huérfano (el proceso de `eolfi bridge --login` ya no existe o el lock es muy antiguo):
// se borra para que el puente no quede bloqueado para siempre.
function loginLockActive(file) {
  if (!existsSync(file)) return false;
  try {
    const pid = Number(readFileSync(file, 'utf8').trim());
    const old = Date.now() - statSync(file).mtimeMs > 6 * 3600 * 1000;
    let alive = true;
    if (pid) { try { process.kill(pid, 0); } catch (e) { alive = e.code === 'EPERM'; } }
    if (old || !alive) { rmSync(file, { force: true }); return false; }
  } catch { /* ilegible: se respeta */ }
  return true;
}

export class ChromeEngine {
  constructor({ browser = findBrowser(), profile = join(homedir(), '.eolfi', 'browser-profile'), log = () => {} } = {}) {
    if (!browser) throw new Error('No se encontró ningún navegador Chromium (Chrome, Edge, Brave, Opera, Vivaldi); usa --browser <ruta>');
    this.browser = browser;
    this.profile = profile;
    this.log = log;
    this.conn = null;           // tubería CDP (PipeConnection)
    this.root = null;           // sesión del navegador
    this.proc = null;
    this.pages = new Map();     // nombre -> CdpContents
  }

  get name() {
    const b = this.browser.toLowerCase();
    return b.includes('msedge') || b.includes('edge') ? 'Edge' : b.includes('brave') ? 'Brave' : b.includes('opera') ? 'Opera'
      : b.includes('vivaldi') ? 'Vivaldi' : b.includes('chromium') ? 'Chromium' : 'Chrome';
  }

  // Una sola arrancada a la vez: dos llamadas simultáneas no lanzan dos navegadores.
  start() {
    this._starting ??= this._start().finally(() => { this._starting = null; });
    return this._starting;
  }

  async _start() {
    if (this.conn && !this.conn.closed) return;
    if (loginLockActive(join(this.profile, '..', 'login.lock'))) {
      throw new Error('Modo inicio de sesión activo: termina de entrar en las webs y cierra esa ventana de Chrome');
    }
    mkdirSync(this.profile, { recursive: true });
    // Migración: un navegador de una versión anterior del puente pudo quedar abierto con un
    // puerto de depuración TCP. Se cierra (las sesiones siguen en el perfil) y se borra el archivo.
    const portFile = join(this.profile, 'DevToolsActivePort');
    if (existsSync(portFile)) {
      const [first, second] = readFileSync(portFile, 'utf8').split('\n');
      if (Number(first) && second?.startsWith('/devtools/browser/')) {
        await closeLegacyBrowser(`ws://127.0.0.1:${Number(first)}${second.trim()}`);
        await sleep(1500);
      }
      rmSync(portFile, { force: true });
    }
    keepSessions(this.profile);
    this.proc = spawn(this.browser, [
      '--remote-debugging-pipe',
      `--user-data-dir=${this.profile}`, '--no-first-run', '--no-default-browser-check',
      // Que las ventanas tapadas o en segundo plano sigan pintando y ejecutando JavaScript:
      // si no, las webs de chat se quedan a medio renderizar mientras esperan la respuesta.
      '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
      '--disable-background-timer-throttling', '--disable-features=CalculateNativeWinOcclusion',
      '--new-window', 'about:blank',
    ], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
    let spawnError = null;
    this.proc.once('error', (e) => { spawnError = e; });
    // La tubería es del puente: si el puente se cierra, el navegador se cierra con él
    // (las sesiones iniciadas siguen guardadas en el perfil de Eolfi).
    const conn = new PipeConnection(this.proc);
    this.proc.on('exit', () => { this.conn = null; this.root = null; this.pages.clear(); });
    this.root = new CdpSession(conn);
    try {
      await conn.send('Browser.getVersion', {}, undefined, 20000);
    } catch (e) {
      try { this.proc.kill(); } catch { /* ya terminó */ }
      if (spawnError) throw new Error(`No se pudo abrir ${this.name} (${this.browser}): ${spawnError.message}`);
      throw new Error(`${this.name} no respondió por la tubería de control: ¿está abierto con el perfil de Eolfi en otra ventana? Ciérrala y repite (${e.message})`);
    }
    // Pestañas cerradas por el usuario: su sesión deja de ser válida.
    conn.on('|Target.detachedFromTarget', ({ sessionId }) => {
      for (const [name, c] of this.pages) if (c.cdp.sessionId === sessionId) { c.cdp._markClosed(); this.pages.delete(name); }
    });
    this.conn = conn;
    this.log(`${this.name} conectado al puente por tubería privada (perfil ${this.profile})`);
  }

  // Vivo = la tubería sigue abierta (no hay puerto que otro proceso pueda ocupar).
  async alive() {
    return !!(this.conn && !this.conn.closed);
  }

  // Sesión del navegador (Target.*, Browser.*).
  async browserCdp() {
    await this.start();
    return this.root;
  }

  // Abre (o reutiliza) la ventana de un sitio y devuelve su CdpContents.
  // Una sola apertura por sitio a la vez: el arranque, /v1/screen y /v1/chat simultáneos
  // no crean dos ventanas ni dejan conexiones CDP huérfanas.
  page(name, url, origin) {
    const cached = this.pages.get(name);
    if (cached && !cached.isDestroyed()) return Promise.resolve(cached);
    this._opening ??= new Map();
    if (!this._opening.has(name)) {
      this._opening.set(name, this._page(name, url, origin).finally(() => this._opening.delete(name)));
    }
    return this._opening.get(name);
  }

  async _page(name, url, origin) {
    await this.start();
    const root = this.root;
    const sameOrigin = (u) => { try { return new URL(u).origin === origin; } catch { return false; } };
    const { targetInfos } = await root.send('Target.getTargets');
    let target = targetInfos.find((t) => t.type === 'page' && sameOrigin(t.url));
    if (!target) {
      const { targetId } = await root.send('Target.createTarget', { url, newWindow: true });
      target = { targetId, url };
    }
    const { sessionId } = await root.send('Target.attachToTarget', { targetId: target.targetId, flatten: true });
    const session = new CdpSession(this.conn, sessionId, root);
    const contents = await CdpContents.attach(session, target.targetId, target.url);
    this.conn.on(`${sessionId}|#closed`, () => { if (this.pages.get(name) === contents) this.pages.delete(name); });
    // Una ventana recién creada empieza en about:blank: esperar a que el sitio cargue
    // (o a que redirija a su página de acceso) antes de devolverla.
    for (let i = 0; i < 100 && (!contents.url || contents.url === 'about:blank'); i++) {
      await sleep(100);
      const href = await contents.executeJavaScript('location.href').catch(() => '');
      if (href) contents.url = href;
    }
    this.pages.set(name, contents);
    return contents;
  }

  // Cierra el navegador de Eolfi (p. ej. al terminar el puente o en las pruebas).
  async close() {
    if (this.conn && !this.conn.closed) await this.conn.send('Browser.close').catch(() => {});
  }

  stop() {
    for (const p of this.pages.values()) p.close();
    this.pages.clear();
    // Al salir el puente se cierra la tubería y, con ella, el navegador (las sesiones quedan en el perfil).
  }
}
