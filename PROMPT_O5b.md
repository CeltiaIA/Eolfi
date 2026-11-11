Tarea O5 (continuación) en D:\Eolfi-objetivos. La ronda anterior hizo el PASO 1, pero añadió por su cuenta una variable EOLFI_LAUNCHER que NO se pidió (amplía qué script se ejecuta con -ExecutionPolicy Bypass): hay que quitarla. No añadas nada que no esté aquí.
Tu contexto es pequeño: NO leas archivos enteros ni listes carpetas. No digas que está hecho hasta haber visto el resultado de node --test.

PASO 0 — eolfi_edit_file, path "eolfi/vscode-bridge/eolas-starter.js":
  old_text: : process.env.EOLFI_LAUNCHER || '';
  new_text: : '';

PASO 2 — eolfi_edit_file, mismo path:
  old_text: function makeEolasStarter({ launcher = DEFAULT_LAUNCHER, powershell = 'powershell.exe', endpoint = DEFAULT_URL,
  new_text: function makeEolasStarter({ launcher = DEFAULT_LAUNCHER, powershell = 'powershell.exe', endpoint = DEFAULT_URL, expectedSha256 = '', log = () => {},

PASO 3 — eolfi_edit_file, mismo path:
  old_text: if (!launcher || !fs.existsSync(launcher)) throw new Error(`no encuentro el lanzador Eolas: ${launcher}`);
  new_text (7 líneas; la primera SIN sangría porque el archivo ya la tiene delante; las otras 6 con 6 espacios):
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
