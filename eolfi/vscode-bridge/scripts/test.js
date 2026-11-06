// Ejecuta las pruebas con una carpeta temporal PROPIA (TEMP/TMP/TMPDIR) y la borra al terminar: así las pruebas no
// dejan carpetas en el Temp del sistema (antes se acumulaban cientos, y una prueba dejaba ~2,9 GB cada vez).
'use strict';
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-pruebas-'));
const env = { ...process.env, TEMP: tmp, TMP: tmp, TMPDIR: tmp };
const selected = process.argv.slice(2);
const r = spawnSync(process.execPath, ['--test', ...(selected.length ? selected : ['test/*.test.js'])], {
  stdio: 'inherit', env, cwd: path.resolve(__dirname, '..'),
});
try { fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch (e) {
  console.error(`No se pudo borrar ${tmp}: ${e.message}`);
}
process.exit(r.status ?? 1);
