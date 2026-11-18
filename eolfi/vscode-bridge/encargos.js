// Encargos del chat de Eolfi a @eolfi en VS Code (18/11/2026).
// El chat del panel propone una aplicación nueva para la carpeta abierta aquí. Eolfi la deja PENDIENTE y avisa por el
// puente (POST /v1/encargo). Esta parte muestra el aviso con las operaciones de riesgo; si el titular aprueba aquí,
// se lo dice al servidor de Eolfi (que aprueba el plan y lanza «create» con verificación) y sigue el progreso.
// El trabajo lo hace siempre el flujo verificado de Eolfi; la extensión no escribe archivos por su cuenta.
'use strict';
const path = require('node:path');

const ID = /^[0-9a-f]{32}$/;
const FINAL = new Set(['hecho', 'fallido', 'rechazado']);

function validEncargo(body) {
  const e = body || {};
  const fail = (msg) => { throw Object.assign(new Error(msg), { status: 400 }); };
  if (typeof e.id !== 'string' || !ID.test(e.id)) fail('encargo sin id válido');
  if (typeof e.nombre !== 'string' || !e.nombre.trim() || e.nombre.length > 200) fail('encargo sin nombre');
  if (typeof e.carpeta !== 'string' || !path.isAbsolute(e.carpeta)) fail('encargo sin carpeta absoluta');
  if (!Array.isArray(e.riesgos) || !e.riesgos.length || !e.riesgos.every((r) => typeof r === 'string')) fail('encargo sin riesgos');
  return { id: e.id, nombre: e.nombre.trim(), carpeta: e.carpeta, riesgos: e.riesgos.slice(0, 10).map((r) => r.slice(0, 300)),
    descripcion: String(e.descripcion || '').slice(0, 2000) };
}

// Texto de estado legible para la barra de progreso y el resultado.
function describe(st) {
  const p = st.proyecto || {};
  const t = st.trabajo || {};
  if (st.estado === 'hecho') return `«${st.nombre}» creado y verificado en ${st.carpeta}`;
  if (st.estado === 'fallido') return `«${st.nombre}» no quedó verificado: ${t.error || p.error || p.estado || 'fallo'}`;
  if (st.estado === 'rechazado') return `encargo «${st.nombre}» rechazado`;
  return (t.progreso || []).slice(-1)[0] || `«${st.nombre}»: ${st.estado}`;
}

function makeEncargoHandler({ vscode, getClient, log = () => {}, pollMs = 1500, maxPolls = 2400 }) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function follow(client, id) {
    let last = null;
    return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Eolfi: encargo', cancellable: false },
      async (progress) => {
        for (let i = 0; i < maxPolls; i++) {
          const list = await client.encargos();
          last = (list.encargos || []).find((x) => x.id === id) || last;
          if (last) {
            const msg = describe(last);
            progress.report({ message: msg });
            log(`encargo ${id.slice(0, 8)}: ${msg}`);
            if (FINAL.has(last.estado)) return last;
          }
          await sleep(pollMs);
        }
        return last;
      });
  }

  async function finish(st) {
    if (!st) return;
    if (st.estado === 'hecho') {
      const inside = (vscode.workspace.workspaceFolders || []).some((f) => {
        const rel = path.relative(f.uri.fsPath, st.carpeta);
        return rel && !rel.startsWith('..') && !path.isAbsolute(rel);
      });
      const pick = await vscode.window.showInformationMessage(`Eolfi: ${describe(st)}.`, inside ? 'Mostrar en el explorador' : 'Abrir carpeta');
      const uri = vscode.Uri.file(st.carpeta);
      if (pick === 'Mostrar en el explorador') await vscode.commands.executeCommand('revealInExplorer', uri);
      else if (pick === 'Abrir carpeta') await vscode.commands.executeCommand('vscode.openFolder', uri, { forceNewWindow: true });
    } else if (st.estado === 'fallido') {
      await vscode.window.showWarningMessage(`Eolfi: ${describe(st)}. Detalles en el panel (caso ${String(st.case_id || '').slice(0, 8)}).`);
    }
  }

  // Devuelve la decisión tomada aquí ('aprobar', 'rechazar' o null si se cerró el aviso: sigue pendiente en el panel).
  return async function onEncargo(body) {
    const e = validEncargo(body);
    const detail = `${e.descripcion ? e.descripcion + '\n\n' : ''}Carpeta: ${e.carpeta}\n\nAl aprobar, Eolfi podrá:\n`
      + e.riesgos.map((r) => `• ${r}`).join('\n')
      + '\n\nLo genera el flujo verificado de Eolfi (compilación, pruebas, juez funcional y accesibilidad).';
    log(`encargo recibido: ${e.nombre} → ${e.carpeta}`);
    const pick = await vscode.window.showWarningMessage(`Eolfi: el chat encarga la aplicación «${e.nombre}»`,
      { modal: true, detail }, 'Aprobar', 'Rechazar');
    if (pick !== 'Aprobar' && pick !== 'Rechazar') { log('encargo sin decidir: queda pendiente en el panel'); return null; }
    const accion = pick === 'Aprobar' ? 'aprobar' : 'rechazar';
    const client = await getClient();
    const st = await client.encargoDecidir(e.id, accion);
    log(`encargo ${e.id.slice(0, 8)}: ${accion} → ${st.estado}`);
    if (accion === 'aprobar') {
      if (st.error) { await vscode.window.showWarningMessage(`Eolfi: no se pudo arrancar el encargo: ${st.error}`); return accion; }
      await finish(await follow(client, e.id));
    }
    return accion;
  };
}

module.exports = { validEncargo, describe, makeEncargoHandler };
