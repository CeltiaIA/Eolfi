Tarea O5 en D:\Eolfi-objetivos: el lanzador de Eolas sin ruta fija de una máquina y con su SHA-256 comprobado antes de ejecutarlo.
Tu contexto es pequeño: NO leas archivos enteros ni listes carpetas. No digas que está hecho hasta haber visto el resultado de node --test.

PASO 1 — eolfi_edit_file, path "eolfi/vscode-bridge/eolas-starter.js":
  old_text: const DEFAULT_LAUNCHER = 'D:\\celtiaia\\launch-eolas.ps1';
  new_text: // Sin ruta fija de una máquina: ajuste «eolfi.fallback.eolasLauncher» o, si falta, CELTIAIA_HOME\launch-eolas.ps1.
const DEFAULT_LAUNCHER = process.env.CELTIAIA_HOME ? require('node:path').join(process.env.CELTIAIA_HOME, 'launch-eolas.ps1') : '';

PASO 2 — eolfi_edit_file, mismo path:
  old_text: function makeEolasStarter({ launcher = DEFAULT_LAUNCHER, powershell = 'powershell.exe', endpoint = DEFAULT_URL,
  new_text: function makeEolasStarter({ launcher = DEFAULT_LAUNCHER, powershell = 'powershell.exe', endpoint = DEFAULT_URL, expectedSha256 = '', log = () => {},

PASO 3 — eolfi_edit_file, mismo path. Busca antes con eolfi_find_text el texto "if (!launcher || !fs.existsSync(launcher))" para saber su línea N y usa start_line N, end_line N, expect_start "if (!launcher ||", con este new_text (7 líneas, 6 espacios de sangría):
      if (!launcher) throw new Error('autoarranque de Eolas sin lanzador: configura «eolfi.fallback.eolasLauncher» (p. ej. D:\\celtiaia\\launch-eolas.ps1) o CELTIAIA_HOME');
      if (!fs.existsSync(launcher)) throw new Error(`no encuentro el lanzador Eolas: ${launcher}`);
      // Identidad del script antes de ejecutarlo con -ExecutionPolicy Bypass; si se fijó un hash, debe coincidir.
      const sha = require('node:crypto').createHash('sha256').update(fs.readFileSync(launcher)).digest('hex');
      log(`Lanzador Eolas ${launcher} · SHA-256 ${sha}`);
      const want = String(expectedSha256 || '').trim().toLowerCase();
      if (want && want !== sha) throw new Error(`el lanzador Eolas no coincide con el SHA-256 configurado (esperado ${want}, actual ${sha}): no se ejecuta`);

PASO 4 — eolfi_edit_file, path "eolfi/vscode-bridge/extension.js":
  old_text: makeEolasStarter({ launcher: launcher || undefined, endpoint, model })
  new_text: makeEolasStarter({ launcher: launcher || undefined, endpoint, model, expectedSha256: String(c.get('fallback.eolasLauncherSha256') || ''), log: (m) => out.appendLine(m) })

PASO 5 — eolfi_edit_file, path "eolfi/vscode-bridge/package.json", start_line 210, end_line 214, expect_start "eolfi.fallback.eolasLauncher", new_text: copia EXACTAMENTE las 10 líneas JSON del archivo D:\Eolfi-objetivos\PROMPT_O5_package.json (léelo con eolfi_read_file).

PASO 6 — crea la prueba con UNA orden de terminal (eolfi_terminal, carpeta "."):
Copy-Item PROMPT_O5_test.js eolfi\vscode-bridge\test\eolas-starter-launcher.test.js

PASO 7 — en la terminal (carpeta "eolfi/vscode-bridge"): node --check eolas-starter.js; node --check extension.js; node -e "JSON.parse(require('fs').readFileSync('package.json','utf8'))"; node --test test/eolas-starter-launcher.test.js test/eolas-starter.test.js; node --test

PASO 8 — con eolfi_informe_anadir añade a informes/progreso-objetivos-eolfi.md una sección «O5 — resultado» con los archivos cambiados y las líneas literales «tests», «pass» y «fail» del último node --test.

Solo si node --test termina sin fallos, acaba con la línea EOLFI-OBJETIVOS-FIN.
