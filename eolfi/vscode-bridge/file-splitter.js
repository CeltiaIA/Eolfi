'use strict';

// Divide archivos de texto sin modificar el original. Las partes conservan los
// bytes exactos y el manifiesto permite comprobar que ninguna se ha alterado.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const MAX_PARTS = 1000;

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function validateParts(value) {
  const parts = Number(value);
  if (!Number.isInteger(parts) || parts < 2 || parts > MAX_PARTS) {
    throw new Error(`El número de partes debe estar entre 2 y ${MAX_PARTS}.`);
  }
  return parts;
}

function utf8Boundary(bytes, target, limit) {
  let at = Math.max(1, Math.min(target, limit));
  // Nunca se corta en medio de un carácter UTF-8 multibyte.
  while (at > 1 && (bytes[at] & 0xc0) === 0x80) at--;
  return at;
}

function boundaries(bytes, parts) {
  const out = [];
  let start = 0;
  for (let index = 0; index < parts - 1; index++) {
    const remainingParts = parts - index;
    const remainingBytes = bytes.length - start;
    const limit = bytes.length - (remainingParts - 1);
    const target = Math.min(limit, start + Math.ceil(remainingBytes / remainingParts));
    let end = target;
    // Se prefiere el primer salto de línea posterior al punto equilibrado.
    while (end < limit && bytes[end - 1] !== 0x0a) end++;
    if (end === limit && bytes[end - 1] !== 0x0a) end = utf8Boundary(bytes, target, limit);
    out.push([start, end]);
    start = end;
  }
  out.push([start, bytes.length]);
  return out;
}

function splitTextFile(file, requestedParts, { outputDir } = {}) {
  const parts = validateParts(requestedParts);
  const source = path.resolve(file);
  const bytes = fs.readFileSync(source);
  if (!bytes.length) throw new Error('No se puede dividir un archivo vacío.');
  if (bytes.includes(0)) throw new Error('El particionador de Eolfi solo admite archivos de texto UTF-8.');
  try { new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch {
    throw new Error('El archivo no está codificado en UTF-8 válido.');
  }
  if (parts > bytes.length) throw new Error('Hay más partes solicitadas que bytes en el archivo.');

  const dir = path.resolve(outputDir || `${source}.eolfi-parts`);
  if (fs.existsSync(dir)) throw new Error(`Ya existe la carpeta de partes: ${dir}`);

  const sourceName = path.basename(source);
  const width = String(parts).length;
  const chunks = boundaries(bytes, parts);
  const records = [];
  fs.mkdirSync(dir, { recursive: false });
  try {
    for (const [index, [start, end]] of chunks.entries()) {
      const chunk = bytes.subarray(start, end);
      const name = `${sourceName}.part-${String(index + 1).padStart(width, '0')}-of-${String(parts).padStart(width, '0')}`;
      fs.writeFileSync(path.join(dir, name), chunk, { flag: 'wx' });
      records.push({ index: index + 1, file: name, bytes: chunk.length, sha256: sha256(chunk) });
    }
    const manifest = {
      schema: 'eolfi-file-parts/v1',
      source: { file: sourceName, bytes: bytes.length, sha256: sha256(bytes), encoding: 'utf-8' },
      parts: records,
    };
    const manifestName = `${sourceName}.eolfi-manifest.json`;
    fs.writeFileSync(path.join(dir, manifestName), JSON.stringify(manifest, null, 2) + '\n', { flag: 'wx' });
    return { source, output: dir, manifest: path.join(dir, manifestName), parts: records };
  } catch (error) {
    fs.rmSync(dir, { recursive: true, force: true });
    throw error;
  }
}

function mergeTextParts(manifestPath, { outputFile } = {}) {
  const manifestFile = path.resolve(manifestPath);
  const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
  if (manifest?.schema !== 'eolfi-file-parts/v1' || !manifest.source || !Array.isArray(manifest.parts)) {
    throw new Error('El manifiesto de partes no es válido.');
  }
  const directory = path.dirname(manifestFile);
  const ordered = [...manifest.parts].sort((a, b) => a.index - b.index);
  if (ordered.length < 2 || ordered.some((part, index) => part.index !== index + 1 || typeof part.file !== 'string')) {
    throw new Error('El manifiesto tiene partes incompletas o fuera de orden.');
  }
  const bytes = ordered.map((part) => {
    const candidate = path.resolve(directory, part.file);
    if (path.dirname(candidate) !== directory) throw new Error(`Ruta de parte no permitida: ${part.file}`);
    const chunk = fs.readFileSync(candidate);
    if (sha256(chunk) !== part.sha256) throw new Error(`La comprobación SHA-256 falló para ${part.file}.`);
    return chunk;
  });
  const joined = Buffer.concat(bytes);
  if (joined.length !== manifest.source.bytes || sha256(joined) !== manifest.source.sha256) {
    throw new Error('La comprobación del archivo recompuesto falló.');
  }
  const destination = path.resolve(outputFile || path.join(directory, `reconstruido-${manifest.source.file}`));
  if (fs.existsSync(destination)) throw new Error(`Ya existe el destino: ${destination}`);
  fs.writeFileSync(destination, joined, { flag: 'wx' });
  return { output: destination, bytes: joined.length, sha256: manifest.source.sha256, parts: ordered.length };
}

// Estado para reanudar una revisión larga: no lee el contenido completo al
// modelo; solo identifica qué partes siguen presentes e íntegras.
function inspectTextParts(manifestPath) {
  const manifestFile = path.resolve(manifestPath);
  const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
  if (manifest?.schema !== 'eolfi-file-parts/v1' || !Array.isArray(manifest.parts)) throw new Error('El manifiesto de partes no es válido.');
  const directory = path.dirname(manifestFile);
  const parts = [...manifest.parts].sort((a, b) => a.index - b.index).map((part) => {
    const candidate = path.resolve(directory, part.file || '');
    if (path.dirname(candidate) !== directory) return { index: part.index, file: part.file, status: 'ruta_insegura' };
    if (!fs.existsSync(candidate)) return { index: part.index, file: part.file, status: 'ausente' };
    const bytes = fs.readFileSync(candidate);
    return { index: part.index, file: part.file, bytes: bytes.length, status: bytes.length === part.bytes && sha256(bytes) === part.sha256 ? 'lista' : 'alterada' };
  });
  return { manifest: manifestFile, source: manifest.source, parts, ready: parts.every((part) => part.status === 'lista') };
}

module.exports = { splitTextFile, mergeTextParts, inspectTextParts, validateParts, boundaries };
