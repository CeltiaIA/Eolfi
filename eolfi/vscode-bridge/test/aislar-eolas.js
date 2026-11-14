'use strict';
// 13/11/2026: sin esto, las pruebas del modelo local leían el estado REAL del equipo
// (~/.eolfi/eolas-v2.runtime.json) y fallaban siempre que Eolas V2 tuviera un modelo cargado de verdad: la guardia
// de GPU rechazaba la petición simulada. Por defecto apuntan a una carpeta temporal vacía; las pruebas de la propia
// guardia pasan su propio env.
if (!process.env.EOLFI_EOLAS_V2_CONFIG) {
  const os = require('node:os');
  const path = require('node:path');
  const fs = require('node:fs');
  process.env.EOLFI_EOLAS_V2_CONFIG = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-pruebas-')), 'eolas-v2.json');
}
