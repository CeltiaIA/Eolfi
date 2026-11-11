// Herramientas de espacio de trabajo del puente: lo que Eolfi (o el modelo de IA) puede hacer en VS Code.
//
// Límites:
// - Leer, listar y buscar: solo dentro de las carpetas abiertas en VS Code (workspace) y con topes de tamaño.
// - Escribir: SIEMPRE pide confirmación en VS Code (salvo «eolfi.autoApproveEdits»), y se hace con WorkspaceEdit:
//   queda en el historial de deshacer (Ctrl+Z) y se guarda el archivo.
// - Abrir una carpeta fuera del workspace: confirmación.
// - Comandos de VS Code: solo los de «eolfi.allowedCommands».
// - Archivos de secretos (.env, claves, credenciales): ni se leen, ni se buscan, ni se escriben. Su contenido
//   nunca llega al modelo de IA (que no se ejecuta en este equipo).
'use strict';
const path = require('node:path');

const MAX_READ = 512 * 1024;
const MAX_WRITE = 2 * 1024 * 1024;
const MAX_LIST = 2000;
const SKIP = '**/{node_modules,.git,.venv,venv,__pycache__,dist,build,.next,.expo,target,bin,obj}/**';

// .env.example / .sample / .template sí se pueden leer: son plantillas sin valores.
const SECRET_NAME = /^(\.env(\.(?!example$|sample$|template$|dist$)[\w.-]+)?|\.git-credentials|\.npmrc|\.pypirc|\.netrc|_netrc|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|credentials(\.json)?|secrets?\.(json|ya?ml|toml|env)|.*\.(pem|key|p12|pfx|jks|keystore|kdbx|ovpn))$/i;
const SECRET_DIR = /(^|[\\/])(\.ssh|\.aws|\.gnupg|\.azure|\.kube|\.docker)([\\/]|$)/i;

function isSecretPath(p) {
  const s = String(p || '');
  // Nombre final con «\» o «/» en cualquier sistema: una ruta de Windows también se reconoce en Linux.
  return SECRET_NAME.test(s.split(/[\\/]/).pop()) || SECRET_DIR.test(s);
}

function isSecretTarget(p) {
  const fs = require('node:fs');
  if (isSecretPath(p)) return true;
  try { return isSecretPath(fs.realpathSync.native(p)); } catch { return false; }
}

class ActionError extends Error { constructor(status, message) { super(message); this.status = status; } }

function settings(vscode) {
  const c = vscode.workspace.getConfiguration('eolfi');
  const list = (k) => (Array.isArray(c.get(k)) ? c.get(k).filter((x) => typeof x === 'string') : []);
  return { autoApproveEdits: c.get('autoApproveEdits') === true, allowedCommands: list('allowedCommands'),
    automatic: c.get('agent.mode') === 'automatico' };
}

function roots(vscode) {
  return (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
}

// Nombre comparable: sin mayúsculas, tildes ni separadores («CeltIA-IA», «celtia_ia» y «celtiaia» son el mismo).
const norm = (s) => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');

// Carpetas abiertas en VS Code con su nombre visible (en un .code-workspace puede no coincidir con la carpeta).
function folders(vscode) {
  return (vscode.workspace.workspaceFolders || []).map((f) => ({ name: f.name || path.basename(f.uri.fsPath), path: f.uri.fsPath }));
}

// Busca una carpeta por su NOMBRE entre las abiertas: el nombre del workspace, el de la carpeta raíz o el de una
// subcarpeta de primer nivel. Devuelve la ruta o null (también si el nombre es ambiguo).
function findFolderByName(vscode, name) {
  const want = norm(name);
  if (!want || want.length < 2) return null;
  const fs = require('node:fs');
  const hits = new Set();
  for (const f of folders(vscode)) {
    if (norm(f.name) === want || norm(path.basename(f.path)) === want) hits.add(f.path);
  }
  if (!hits.size) {
    for (const f of folders(vscode)) {
      let ents = [];
      try { ents = fs.readdirSync(f.path, { withFileTypes: true }); } catch { continue; }
      for (const e of ents) if (e.isDirectory() && norm(e.name) === want) hits.add(path.join(f.path, e.name));
    }
  }
  return hits.size === 1 ? [...hits][0] : null;
}

// Ruta relativa: primero la que exista en alguna carpeta abierta (en orden); si ninguna, el nombre de una carpeta
// abierta («celtiaia» cuando el workspace ES celtiaia); si nada, relativa a la primera (para crear archivos).
function pickRelative(vscode, rs, p) {
  const fs = require('node:fs');
  for (const r of rs) { const c = path.resolve(r, p); if (fs.existsSync(c)) return c; }
  const parts = p.split(/[\\/]+/).filter(Boolean);
  if (parts.length) {
    const base = findFolderByName(vscode, parts[0]);
    if (base) return path.resolve(base, ...parts.slice(1));
  }
  return path.resolve(rs[0], p);
}

// Ruta absoluta o relativa a las carpetas abiertas; debe quedar DENTRO de un workspace (sin ../ que escape).
function resolveInside(vscode, p) {
  if (typeof p !== 'string' || !p.trim() || p.length > 1000) throw new ActionError(400, 'ruta inválida');
  const rs = roots(vscode);
  if (!rs.length) throw new ActionError(409, 'VS Code no tiene ninguna carpeta abierta');
  const full = path.isAbsolute(p) ? path.resolve(p) : pickRelative(vscode, rs, p.trim());
  const within = (target, roots) => roots.some((r) => { const rel = path.relative(r, target); return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel)); });
  if (!within(full, rs)) throw new ActionError(403, `fuera de las carpetas abiertas en VS Code: ${full}`);
  // Un enlace simbólico (o unión) DENTRO del workspace que apunte fuera no sirve para salir: se comprueba la ruta
  // real del destino o, si aún no existe, la de su carpeta existente más cercana.
  const fs = require('node:fs');
  const real = (x) => { try { return fs.realpathSync.native(x); } catch { return null; } };
  let probe = full;
  let r = real(probe);
  while (r === null && path.dirname(probe) !== probe) { probe = path.dirname(probe); r = real(probe); }
  const realRoots = rs.map((x) => real(x) || x);
  if (r !== null && !within(r, realRoots)) throw new ActionError(403, `fuera de las carpetas abiertas en VS Code (enlace a ${r})`);
  return full;
}

async function confirm(vscode, message, detail, yes = 'Permitir') {
  const pick = await vscode.window.showWarningMessage(message, { modal: true, detail }, yes);
  return pick === yes;
}

// Modo automático: Eolfi lo PIDE, pero solo lo concede el usuario en VS Code (una vez por sesión o siempre).
const MAX_JOURNALS = 30;

function makeActions(vscode) {
  const fs = vscode.workspace.fs;
  const U = (p) => vscode.Uri.file(p);
  let sessionAuto = false;
  const reportsAllowed = new Set();   // informes que el usuario ya dejó ir escribiendo en esta sesión
  const journals = new Map();   // id → [{ path, original }] (original null = el archivo no existía)

  // Como Copilot: el cambio propuesto se enseña en un diff (izquierda el archivo, derecha la propuesta) y se
  // aplica o descarta desde ahí. Sin la API de documentos virtuales (pruebas), se pregunta con un diálogo.
  const SCHEME = 'eolfi-propuesta';
  const proposals = new Map();
  let provider = null;
  const canDiff = () => typeof vscode.workspace.registerTextDocumentContentProvider === 'function' && vscode.Uri.from;
  async function reviewInDiff(full, exists, content, reason) {
    if (!provider) {
      provider = vscode.workspace.registerTextDocumentContentProvider(SCHEME, { provideTextDocumentContent: (u) => proposals.get(u.toString()) ?? '' });
    }
    const id = require('node:crypto').randomBytes(4).toString('hex');
    const right = vscode.Uri.from({ scheme: SCHEME, path: `/${id}/${path.basename(full)}` });
    proposals.set(right.toString(), content);
    let left = U(full);
    if (!exists) {
      left = vscode.Uri.from({ scheme: SCHEME, path: `/${id}/vacío/${path.basename(full)}` });
      proposals.set(left.toString(), '');
    }
    await vscode.commands.executeCommand('vscode.diff', left, right,
      `${path.basename(full)} ↔ cambio propuesto por Eolfi${exists ? '' : ' (archivo nuevo)'}`, { preview: false });
    const apply = 'Aplicar', discard = 'Descartar';
    const pick = await vscode.window.showInformationMessage(
      `Eolfi propone ${exists ? 'cambiar' : 'crear'} ${path.basename(full)}${reason ? `: ${String(reason).slice(0, 160)}` : ''}`, apply, discard);
    // Cierra la pestaña del diff.
    try {
      for (const g of vscode.window.tabGroups?.all || []) {
        for (const t of g.tabs) if (t.input?.modified?.toString?.() === right.toString()) await vscode.window.tabGroups.close(t);
      }
    } catch { /* sin pestañas que cerrar */ }
    proposals.delete(right.toString());
    proposals.delete(left.toString());
    return pick === apply;
  }

  async function autoAllowed() {
    if (settings(vscode).autoApproveEdits || sessionAuto) return true;
    const session = 'Permitir en esta sesión', always = 'Permitir siempre';
    const pick = await vscode.window.showWarningMessage(
      'Eolfi pide el modo AUTOMÁTICO: escribir archivos del workspace sin preguntar cada vez.',
      { modal: true, detail: 'Cada cambio se guarda en un diario: si la petición falla o la verificación de Eolfi no queda en '
        + 'verde, se deshace solo. Cancelar = seguir preguntando archivo por archivo.' }, session, always);
    if (pick === always) {
      await vscode.workspace.getConfiguration('eolfi').update('autoApproveEdits', true, vscode.ConfigurationTarget?.Global ?? true);
      return true;
    }
    if (pick === session) { sessionAuto = true; return true; }
    return false;
  }

  function newJournal() {
    const id = require('node:crypto').randomBytes(8).toString('hex');
    journals.set(id, []);
    while (journals.size > MAX_JOURNALS) journals.delete(journals.keys().next().value);
    return id;
  }

  const actions = {
    async workspace() {
      const active = vscode.window.activeTextEditor?.document;
      return {
        folders: roots(vscode),
        folder_names: folders(vscode).map((f) => f.name),
        active_file: active?.uri?.fsPath || null,
        open_editors: (vscode.window.visibleTextEditors || []).map((e) => e.document.uri.fsPath).slice(0, 50),
      };
    },

    async list({ glob = '**/*', max = 500 } = {}) {
      if (typeof glob !== 'string' || glob.length > 300) throw new ActionError(400, 'glob inválido');
      const n = Math.max(1, Math.min(Number(max) || 500, MAX_LIST));
      const files = await vscode.workspace.findFiles(glob, SKIP, n);
      const visible = files.map((u) => u.fsPath).filter((p) => {
        try { resolveInside(vscode, p); return !isSecretTarget(p); } catch { return false; }
      });
      return { files: visible.sort(), truncated: files.length >= n };
    },

    async read({ path: p, start_line, end_line } = {}) {
      const full = resolveInside(vscode, p);
      if (isSecretTarget(full)) throw new ActionError(403, `${path.basename(full)} guarda secretos: Eolfi no lo lee ni lo envía al modelo`);
      const stat = await fs.stat(U(full));
      if (stat.size > MAX_READ && !(start_line || end_line)) throw new ActionError(413, `archivo de ${stat.size} bytes: pide un rango de líneas`);
      const bytes = await fs.readFile(U(full));
      if (bytes.subarray(0, 8000).includes(0)) throw new ActionError(415, 'archivo binario');
      let text = Buffer.from(bytes).toString('utf8');
      const lines = text.split('\n');
      const a = Math.max(1, Number(start_line) || 1), b = Math.min(lines.length, Number(end_line) || lines.length);
      if (start_line || end_line) text = lines.slice(a - 1, b).join('\n');
      return { path: full, lines: lines.length, range: [a, b], text: text.slice(0, MAX_READ) };
    },

    async find({ text: needle, glob = '**/*', max = 100 } = {}) {
      if (typeof needle !== 'string' || !needle || needle.length > 200) throw new ActionError(400, 'texto inválido');
      const files = await vscode.workspace.findFiles(glob, SKIP, 3000);
      const hits = [];
      for (const u of files) {
        if (hits.length >= Math.min(Number(max) || 100, 500)) break;
        try { resolveInside(vscode, u.fsPath); } catch { continue; }
        if (isSecretTarget(u.fsPath)) continue;   // nunca se busca dentro de archivos de secretos
        let bytes;
        try { bytes = await fs.readFile(u); } catch { continue; }
        if (bytes.length > MAX_READ || bytes.subarray(0, 8000).includes(0)) continue;
        Buffer.from(bytes).toString('utf8').split('\n').forEach((line, i) => {
          if (hits.length < 500 && line.includes(needle)) hits.push({ path: u.fsPath, line: i + 1, text: line.trim().slice(0, 200) });
        });
      }
      return { matches: hits };
    },

    async open({ path: p, line } = {}) {
      if (typeof p !== 'string' || !p.trim()) throw new ActionError(400, 'ruta inválida');
      const full = path.resolve(p);
      let stat;
      try { stat = await fs.stat(U(full)); } catch { throw new ActionError(404, `no existe: ${full}`); }
      if (stat.type & vscode.FileType.Directory) {
        let inWorkspace = false;
        try { resolveInside(vscode, full); inWorkspace = true; } catch { /* una carpeta externa puede abrirse con confirmación */ }
        if (inWorkspace) return { opened: full, kind: 'folder', note: 'ya está abierta' };
        if (!settings(vscode).automatic && !(await confirm(vscode, `Eolfi quiere abrir la carpeta ${full} en una ventana nueva de VS Code.`, 'Podrá leer y buscar en ella; escribir seguirá pidiendo confirmación.'))) {
          throw new ActionError(403, 'El usuario no permitió abrir la carpeta');
        }
        await vscode.commands.executeCommand('vscode.openFolder', U(full), { forceNewWindow: true });
        return { opened: full, kind: 'folder' };
      }
      resolveInside(vscode, full);
      if (isSecretTarget(full)) throw new ActionError(403, `${path.basename(full)} guarda secretos: Eolfi no lo abre ni lo envía al modelo`);
      const doc = await vscode.workspace.openTextDocument(U(full));
      const ed = await vscode.window.showTextDocument(doc, { preview: false });
      if (line) {
        const pos = new vscode.Position(Math.max(0, Number(line) - 1), 0);
        ed.selection = new vscode.Selection(pos, pos);
        ed.revealRange(new vscode.Range(pos, pos));
      }
      return { opened: full, kind: 'file' };
    },

    async write({ path: p, content, reason = '', auto = false, journal = null } = {}) {
      // (con diario: «Deshacer estos cambios» en el chat restaura todo lo escrito en la petición)
      const full = resolveInside(vscode, p);
      if (isSecretTarget(full)) throw new ActionError(403, `${path.basename(full)} guarda secretos: Eolfi no lo modifica (edítalo tú)`);
      if (typeof content !== 'string' || Buffer.byteLength(content) > MAX_WRITE) throw new ActionError(400, 'contenido inválido o demasiado grande');
      let exists = true;
      try { await fs.stat(U(full)); } catch { exists = false; }
      // Diario: el contenido de ANTES del primer cambio de esta petición, para poder deshacer.
      const entries = journal && journals.get(journal);
      if (entries && !entries.some((e) => e.path === full)) {
        entries.push({ path: full, original: exists ? Buffer.from(await fs.readFile(U(full))).toString('utf8') : null });
      }
      const st = settings(vscode);
      if (!st.automatic && !(auto && await autoAllowed()) && !st.autoApproveEdits) {
        const ok = canDiff() ? await reviewInDiff(full, exists, content, reason)
          : await confirm(vscode, `Eolfi quiere ${exists ? 'modificar' : 'crear'} ${full}`,
            `${String(reason).slice(0, 300)}\n${content.length} caracteres. Podrás deshacerlo con Ctrl+Z en el editor.`);
        if (!ok) throw new ActionError(403, 'El usuario no permitió la escritura');
      }
      const edit = new vscode.WorkspaceEdit();
      const uri = U(full);
      if (!exists) edit.createFile(uri, { ignoreIfExists: true });
      else {
        const doc = await vscode.workspace.openTextDocument(uri);
        edit.delete(uri, new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length)));
      }
      edit.insert(uri, new vscode.Position(0, 0), content);
      if (!(await vscode.workspace.applyEdit(edit))) throw new ActionError(500, 'VS Code no aplicó la edición');
      const doc = await vscode.workspace.openTextDocument(uri);
      await doc.save();
      return { written: full, created: !exists, chars: content.length, ...(journal ? { journal } : {}) };
    },

    // Edición parcial: sustituye un fragmento literal (único en el archivo) y escribe el resultado con «write»,
    // así se conservan la confirmación/diff del modo manual, el diario y «Deshacer». Evita que el modelo tenga que
    // reescribir un archivo existente entero para cambiar unas líneas.
    async edit({ path: p, old_text, new_text, start_line, end_line, expect_start, reason = '', auto = false, journal = null } = {}) {
      const full = resolveInside(vscode, p);
      if (isSecretTarget(full)) throw new ActionError(403, `${path.basename(full)} guarda secretos: Eolfi no lo modifica (edítalo tú)`);
      if (typeof new_text !== 'string') throw new ActionError(400, 'new_text inválido');
      const byLines = (old_text === undefined || old_text === '') && start_line !== undefined;
      if (!byLines) {
        if (typeof old_text !== 'string' || !old_text) throw new ActionError(400, 'old_text vacío: copia literalmente el fragmento que quieres cambiar (o usa start_line, end_line y expect_start)');
        if (old_text === new_text) throw new ActionError(400, 'old_text y new_text son iguales: no hay nada que cambiar');
      }
      let bytes;
      try { bytes = await fs.readFile(U(full)); } catch { throw new ActionError(404, `no existe: ${full} (para crear un archivo usa eolfi_write_file)`); }
      if (bytes.subarray(0, 8000).includes(0)) throw new ActionError(415, 'archivo binario');
      const text = Buffer.from(bytes).toString('utf8');
      if (byLines) {
        // Rango de líneas (1-based, inclusivo). expect_start es obligatorio: un número de línea desfasado
        // (el archivo cambió desde que se leyó) no debe sustituir otra cosa en silencio.
        const lines = text.split('\n');
        const a = Number(start_line), b = Number(end_line ?? start_line);
        if (!Number.isInteger(a) || !Number.isInteger(b) || a < 1 || b < a || b > lines.length) {
          throw new ActionError(400, `rango inválido ${start_line}-${end_line}: el archivo tiene ${lines.length} líneas`);
        }
        if (typeof expect_start !== 'string' || !expect_start.trim()) throw new ActionError(400, 'expect_start obligatorio: un trozo del texto de la línea start_line');
        if (!lines[a - 1].includes(expect_start.trim())) {
          const hit = lines.findIndex((l) => l.includes(expect_start.trim()));
          throw new ActionError(409, `la línea ${a} no contiene «${expect_start.trim()}»${hit >= 0 ? `; aparece en la línea ${hit + 1}` : ''}: vuelve a leer el rango`);
        }
        const eol = lines[a - 1].endsWith('\r') ? '\r' : '';
        const replaced = lines.slice(a - 1, b).join('\n');
        const repl = new_text === '' ? [] : new_text.replace(/\r?\n/g, '\n').split('\n').map((l) => l + eol);
        const content = [...lines.slice(0, a - 1), ...repl, ...lines.slice(b)].join('\n');
        const r = await actions.write({ path: full, content, reason, auto, journal });
        return { edited: r.written, written: r.written, lines: [a, b], replaced: replaced.replace(/\r/g, '').slice(0, 4000), ...(journal ? { journal } : {}) };
      }
      // Los modelos suelen copiar con \n aunque el archivo use \r\n: se adapta solo si así coincide.
      const crlf = text.includes('\r\n') && !old_text.includes('\r\n');
      const oldT = crlf ? old_text.replace(/\n/g, '\r\n') : old_text;
      const newT = crlf ? new_text.replace(/\r?\n/g, '\r\n') : new_text;
      const first = text.indexOf(oldT);
      if (first < 0) throw new ActionError(409, 'old_text no aparece en el archivo: vuelve a leerlo (eolfi_read_file) y copia el fragmento exacto');
      if (text.indexOf(oldT, first + 1) >= 0) throw new ActionError(409, 'old_text aparece más de una vez: incluye más líneas de contexto para que sea único');
      const content = text.slice(0, first) + newT + text.slice(first + oldT.length);
      const r = await actions.write({ path: full, content, reason, auto, journal });
      const line = text.slice(0, first).split('\n').length;
      return { edited: r.written, written: r.written, line, removed_chars: oldT.length, added_chars: newT.length, ...(journal ? { journal } : {}) };
    },

    // Informe incremental: añade una sección al final de un .md/.txt del workspace. En modo manual se pide permiso una
    // vez por informe y sesión (no un diff por sección); queda en el diario para «Deshacer estos cambios».
    async append({ path: p, content, journal = null } = {}) {
      const full = resolveInside(vscode, p);
      if (isSecretTarget(full)) throw new ActionError(403, `${path.basename(full)} guarda secretos: Eolfi no lo modifica`);
      if (!/\.(md|markdown|txt)$/i.test(full)) throw new ActionError(400, 'solo se añaden secciones a informes .md o .txt (para código usa eolfi_write_file)');
      if (typeof content !== 'string' || !content.trim() || Buffer.byteLength(content) > MAX_WRITE) throw new ActionError(400, 'contenido inválido o demasiado grande');
      let exists = true, old = '';
      try { old = Buffer.from(await fs.readFile(U(full))).toString('utf8'); } catch { exists = false; }
      const entries = journal && journals.get(journal);
      if (entries && !entries.some((e) => e.path === full)) entries.push({ path: full, original: exists ? old : null });
      const st = settings(vscode);
      if (!st.automatic && !st.autoApproveEdits && !reportsAllowed.has(full)) {
        const ok = await confirm(vscode, `Eolfi quiere ${exists ? 'ir añadiendo secciones a' : 'crear e ir escribiendo'} el informe ${full}`,
          'Podrá añadirle secciones sin volver a preguntar en esta sesión. Podrás deshacerlo con «Deshacer estos cambios».');
        if (!ok) throw new ActionError(403, 'El usuario no permitió escribir el informe');
        reportsAllowed.add(full);
      }
      const text = `${old}${old && !old.endsWith('\n') ? '\n' : ''}${old ? '\n' : ''}${content.replace(/\s+$/, '')}\n`;
      if (!exists && typeof fs.createDirectory === 'function') await fs.createDirectory(U(path.dirname(full))).then(undefined, () => {});
      const edit = new vscode.WorkspaceEdit();
      const uri = U(full);
      if (!exists) edit.createFile(uri, { ignoreIfExists: true });
      else {
        const doc = await vscode.workspace.openTextDocument(uri);
        edit.delete(uri, new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length)));
      }
      edit.insert(uri, new vscode.Position(0, 0), text);
      if (!(await vscode.workspace.applyEdit(edit))) throw new ActionError(500, 'VS Code no aplicó la edición');
      await (await vscode.workspace.openTextDocument(uri)).save();
      return { appended: full, created: !exists, total_chars: text.length };
    },

    // Diario de cambios de una petición (modo automático): crear, consultar y deshacer.
    async journal_start() { return { journal: newJournal() }; },

    async undo({ journal } = {}) {
      const entries = journals.get(journal);
      if (!entries) throw new ActionError(404, 'diario no encontrado (ya deshecho o demasiado antiguo)');
      const restored = [];
      for (const e of [...entries].reverse()) {
        const uri = U(e.path);
        const edit = new vscode.WorkspaceEdit();
        if (e.original === null) edit.deleteFile(uri, { ignoreIfNotExists: true });
        else {
          const doc = await vscode.workspace.openTextDocument(uri);
          edit.delete(uri, new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length)));
          edit.insert(uri, new vscode.Position(0, 0), e.original);
        }
        if (await vscode.workspace.applyEdit(edit)) {
          if (e.original !== null) await (await vscode.workspace.openTextDocument(uri)).save();
          restored.push(e.path);
        }
      }
      journals.delete(journal);
      return { journal, restored };
    },

    async command({ command, args = [] } = {}) {
      if (typeof command !== 'string' || !settings(vscode).allowedCommands.includes(command)) {
        throw new ActionError(403, `comando no permitido: ${command} (añádelo a «eolfi.allowedCommands»)`);
      }
      const r = await vscode.commands.executeCommand(command, ...(Array.isArray(args) ? args : []));
      let out;
      try { out = JSON.parse(JSON.stringify(r ?? null)); } catch { out = String(r); }
      return { command, result: out };
    },
  };
  return actions;
}

// Las mismas acciones, como herramientas que el modelo de IA puede pedir (ejecutadas por el puente).
const TOOL_DEFS = [
  { name: 'eolfi_workspace', action: 'workspace', description: 'Carpetas abiertas en VS Code, archivo activo y editores visibles.',
    inputSchema: { type: 'object', properties: {} } },
  { name: 'eolfi_list_files', action: 'list', description: 'Lista archivos del workspace con un patrón glob (p. ej. **/*.py).',
    inputSchema: { type: 'object', properties: { glob: { type: 'string' }, max: { type: 'number' } } } },
  { name: 'eolfi_read_file', action: 'read', description: 'Lee un archivo de texto del workspace (opcionalmente un rango de líneas).',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, start_line: { type: 'number' }, end_line: { type: 'number' } }, required: ['path'] } },
  { name: 'eolfi_find_text', action: 'find', description: 'Busca un texto literal en los archivos del workspace.',
    inputSchema: { type: 'object', properties: { text: { type: 'string' }, glob: { type: 'string' } }, required: ['text'] } },
  { name: 'eolfi_open', action: 'open', description: 'Abre un archivo (opcionalmente en una línea) o una carpeta en VS Code.',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, line: { type: 'number' } }, required: ['path'] } },
  { name: 'eolfi_informe_anadir', action: 'append', description: 'Añade una sección (Markdown) al final de un informe .md del workspace, creándolo si no existe (p. ej. informes/auditoria-2026-11-06.md). Úsala para ir escribiendo informes largos por partes.',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string', description: 'Sección en Markdown' } }, required: ['path', 'content'] } },
  { name: 'eolfi_write_file', action: 'write', description: 'Crea o reemplaza un archivo del workspace (el usuario lo confirma en VS Code).',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' }, reason: { type: 'string' } }, required: ['path', 'content'] } },
  { name: 'eolfi_edit_file', action: 'edit', description: 'Cambia una parte de un archivo existente sin reescribirlo: o sustituye old_text (copiado literalmente y único en el archivo) por new_text, o sustituye las líneas start_line..end_line por new_text (entonces expect_start, un trozo del texto actual de start_line, es obligatorio; los números de línea los da eolfi_find_text o eolfi_read_file). Para varios cambios, llámala varias veces.',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, old_text: { type: 'string', description: 'Fragmento exacto actual (con unas líneas de contexto si hace falta para que sea único)' }, new_text: { type: 'string', description: 'Texto que lo sustituye (vacío = borrar el rango de líneas)' }, start_line: { type: 'number', description: 'Primera línea a sustituir (1-based), en lugar de old_text' }, end_line: { type: 'number', description: 'Última línea a sustituir (incluida)' }, expect_start: { type: 'string', description: 'Trozo del texto actual de start_line, para comprobar que el número no está desfasado' }, reason: { type: 'string' } }, required: ['path', 'new_text'] } },
];

module.exports = { makeActions, TOOL_DEFS, ActionError, resolveInside, isSecretPath, findFolderByName, folders, norm };
