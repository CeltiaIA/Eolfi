'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const MAX_ARCHIVE_ENTRIES = 5000;
const MAX_ARCHIVE_BYTES = 512 * 1024 * 1024;
const TEXT_LIMIT = 4 * 1024 * 1024;
const SKIP_DIRECTORIES = new Set(['.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__']);

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const readU16 = (bytes, offset) => bytes.readUInt16LE(offset);
const readU32 = (bytes, offset) => bytes.readUInt32LE(offset);

function magic(bytes) {
  if (bytes.subarray(0, 4).equals(Buffer.from('PK\x03\x04'))) return 'zip';
  if (bytes.subarray(0, 2).equals(Buffer.from([0x1f, 0x8b]))) return 'gzip';
  if (bytes.subarray(0, 6).equals(Buffer.from('7z\xbc\xaf\x27\x1c', 'binary'))) return '7z';
  if (bytes.subarray(0, 7).equals(Buffer.from('Rar!\x1a\x07\x00', 'binary')) || bytes.subarray(0, 8).equals(Buffer.from('Rar!\x1a\x07\x01\x00', 'binary'))) return 'rar';
  if (bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) return 'pdf';
  if (bytes.subarray(0, 4).equals(Buffer.from('\x7fELF', 'binary'))) return 'elf';
  if (bytes.subarray(0, 2).equals(Buffer.from('MZ'))) return 'pe';
  return null;
}

function detectText(bytes) {
  if (bytes.includes(0)) return { text: false, encoding: null };
  try { new TextDecoder('utf-8', { fatal: true }).decode(bytes); return { text: true, encoding: 'utf-8' }; } catch { return { text: false, encoding: null }; }
}

function inspectFile(file) {
  const full = path.resolve(file);
  const bytes = fs.readFileSync(full);
  const text = detectText(bytes);
  const prefix = bytes.subarray(0, Math.min(bytes.length, TEXT_LIMIT));
  const value = text.text ? prefix.toString('utf8') : '';
  return {
    path: full,
    name: path.basename(full),
    bytes: bytes.length,
    sha256: sha256(bytes),
    format: magic(bytes) || (text.text ? 'text' : 'binary'),
    encoding: text.encoding,
    lines: text.text ? (value ? value.split(/\r?\n/).length : 0) : null,
    truncated_text_analysis: bytes.length > TEXT_LIMIT,
  };
}

function safeArchiveName(name) {
  const normalized = String(name || '').replace(/\\/g, '/');
  if (!normalized || normalized.startsWith('/') || /^[A-Za-z]:/.test(normalized) || normalized.split('/').includes('..')) {
    throw new Error(`Entrada de archivo no segura: ${name}`);
  }
  return normalized;
}

function zipEntries(bytes) {
  let eocd = -1;
  for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 65557); at--) {
    if (readU32(bytes, at) === 0x06054b50) { eocd = at; break; }
  }
  if (eocd < 0) throw new Error('ZIP sin directorio central válido.');
  const count = readU16(bytes, eocd + 10);
  const offset = readU32(bytes, eocd + 16);
  if (count > MAX_ARCHIVE_ENTRIES) throw new Error(`ZIP supera el límite de ${MAX_ARCHIVE_ENTRIES} entradas.`);
  let at = offset;
  const entries = [];
  for (let index = 0; index < count; index++) {
    if (at + 46 > bytes.length || readU32(bytes, at) !== 0x02014b50) throw new Error('Directorio central ZIP incompleto.');
    const method = readU16(bytes, at + 10);
    const compressed = readU32(bytes, at + 20);
    const uncompressed = readU32(bytes, at + 24);
    const nameSize = readU16(bytes, at + 28);
    const extraSize = readU16(bytes, at + 30);
    const commentSize = readU16(bytes, at + 32);
    const localOffset = readU32(bytes, at + 42);
    const name = safeArchiveName(bytes.subarray(at + 46, at + 46 + nameSize).toString('utf8'));
    entries.push({ name, method, compressed, uncompressed, localOffset, directory: name.endsWith('/') });
    at += 46 + nameSize + extraSize + commentSize;
  }
  return entries;
}

function zipContent(bytes, entry) {
  const at = entry.localOffset;
  if (at + 30 > bytes.length || readU32(bytes, at) !== 0x04034b50) throw new Error(`Cabecera ZIP ausente: ${entry.name}`);
  const nameSize = readU16(bytes, at + 26);
  const extraSize = readU16(bytes, at + 28);
  const start = at + 30 + nameSize + extraSize;
  const raw = bytes.subarray(start, start + entry.compressed);
  let result;
  if (entry.method === 0) result = raw;
  else if (entry.method === 8) result = zlib.inflateRawSync(raw);
  else throw new Error(`Compresión ZIP no compatible (${entry.method}) en ${entry.name}`);
  if (result.length !== entry.uncompressed) throw new Error(`Tamaño ZIP inesperado en ${entry.name}`);
  return result;
}

function tarEntries(bytes) {
  const entries = [];
  for (let at = 0; at + 512 <= bytes.length;) {
    const header = bytes.subarray(at, at + 512);
    if (header.every((byte) => byte === 0)) break;
    const name = header.subarray(0, 100).toString('utf8').replace(/\0.*$/, '');
    const prefix = header.subarray(345, 500).toString('utf8').replace(/\0.*$/, '');
    const sizeText = header.subarray(124, 136).toString('ascii').replace(/\0.*$/, '').trim();
    const size = sizeText ? parseInt(sizeText, 8) : 0;
    const type = String.fromCharCode(header[156] || 0);
    const fullName = safeArchiveName(prefix ? `${prefix}/${name}` : name);
    // No materializamos enlaces ni tipos especiales: un archivo TAR no debe poder
    // convertir la extracción en una ruta fuera de la carpeta elegida.
    if (!['\0', '0', '5'].includes(type)) throw new Error(`Tipo TAR no compatible en ${fullName}`);
    entries.push({ name: fullName, size, directory: type === '5', offset: at + 512 });
    at += 512 + Math.ceil(size / 512) * 512;
    if (entries.length > MAX_ARCHIVE_ENTRIES) throw new Error(`TAR supera el límite de ${MAX_ARCHIVE_ENTRIES} entradas.`);
  }
  return entries;
}

function archiveInfo(file) {
  const full = path.resolve(file);
  const bytes = fs.readFileSync(full);
  const format = magic(bytes);
  if (format === 'zip') return { path: full, format, entries: zipEntries(bytes).map(({ name, compressed, uncompressed, directory }) => ({ name, compressed, uncompressed, directory })) };
  if (format === 'gzip') {
    const decoded = zlib.gunzipSync(bytes);
    const tar = tarEntries(decoded);
    return { path: full, format: tar.length ? 'tar.gz' : 'gzip', entries: tar.length ? tar.map(({ name, size, directory }) => ({ name, uncompressed: size, directory })) : [{ name: path.basename(full, path.extname(full)), uncompressed: decoded.length, directory: false }] };
  }
  if (format === '7z' || format === 'rar') return { path: full, format, entries: [], note: `La extensión no extrae ${format.toUpperCase()} sin una herramienta local compatible.` };
  throw new Error('Formato de archivo comprimido no compatible.');
}

function extractArchive(file, outputDir) {
  const full = path.resolve(file);
  const bytes = fs.readFileSync(full);
  const format = magic(bytes);
  const output = path.resolve(outputDir || `${full}.eolfi-extract`);
  if (fs.existsSync(output)) throw new Error(`Ya existe la carpeta de extracción: ${output}`);
  let entries = [];
  if (format === 'zip') {
    entries = zipEntries(bytes);
    if (entries.reduce((sum, entry) => sum + entry.uncompressed, 0) > MAX_ARCHIVE_BYTES) throw new Error('El ZIP supera el límite de extracción de 512 MiB.');
    fs.mkdirSync(output, { recursive: false });
    try {
      for (const entry of entries) {
        const target = path.resolve(output, entry.name);
        if (target !== output && !target.startsWith(output + path.sep)) throw new Error(`Entrada fuera de destino: ${entry.name}`);
        if (entry.directory) fs.mkdirSync(target, { recursive: true });
        else { fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, zipContent(bytes, entry), { flag: 'wx' }); }
      }
    } catch (error) { fs.rmSync(output, { recursive: true, force: true }); throw error; }
  } else if (format === 'gzip') {
    const decoded = zlib.gunzipSync(bytes);
    entries = tarEntries(decoded);
    if (!entries.length) {
      fs.mkdirSync(output, { recursive: false });
      fs.writeFileSync(path.join(output, path.basename(full, path.extname(full))), decoded, { flag: 'wx' });
    } else {
      if (entries.reduce((sum, entry) => sum + entry.size, 0) > MAX_ARCHIVE_BYTES) throw new Error('El TAR supera el límite de extracción de 512 MiB.');
      fs.mkdirSync(output, { recursive: false });
      try {
        for (const entry of entries) {
          const target = path.resolve(output, entry.name);
          if (target !== output && !target.startsWith(output + path.sep)) throw new Error(`Entrada fuera de destino: ${entry.name}`);
          if (entry.directory) fs.mkdirSync(target, { recursive: true });
          else { fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, decoded.subarray(entry.offset, entry.offset + entry.size), { flag: 'wx' }); }
        }
      } catch (error) { fs.rmSync(output, { recursive: true, force: true }); throw error; }
    }
  } else {
    throw new Error('Solo se extraen ZIP, TAR y GZIP.');
  }
  return { path: full, format: format === 'gzip' && entries.length ? 'tar.gz' : format, output, entries: entries.length };
}

function walk(root, visitor, { limit = 5000 } = {}) {
  const files = [];
  const visit = (dir) => {
    if (files.length >= limit) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (files.length >= limit) return;
      if (entry.isDirectory()) { if (!SKIP_DIRECTORIES.has(entry.name)) visit(path.join(dir, entry.name)); continue; }
      if (entry.isFile()) { const file = path.join(dir, entry.name); files.push(file); visitor?.(file); }
    }
  };
  visit(root);
  return files;
}

function codeMap(target) {
  const full = path.resolve(target);
  const stat = fs.statSync(full);
  const files = stat.isDirectory() ? walk(full, null, { limit: 2000 }) : [full];
  const symbols = [];
  const imports = [];
  for (const file of files) {
    const bytes = fs.readFileSync(file);
    if (bytes.length > TEXT_LIMIT || !detectText(bytes).text) continue;
    const lines = bytes.toString('utf8').split(/\r?\n/);
    lines.forEach((line, index) => {
      const found = line.match(/^\s*(?:export\s+)?(?:async\s+)?(?:function|class|def)\s+([A-Za-z_$][\w$]*)/) || line.match(/^\s*([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>/);
      if (found) symbols.push({ file, line: index + 1, name: found[1] });
      const imported = line.match(/(?:from\s+['\"]([^'\"]+)['\"]|import\s+.*?from\s+['\"]([^'\"]+)['\"]|^\s*import\s+([\w.]+))/);
      if (imported) imports.push({ file, line: index + 1, target: imported[1] || imported[2] || imported[3] });
    });
  }
  return { path: full, files: files.length, symbols, imports };
}

function compareFiles(left, right) {
  const a = fs.readFileSync(path.resolve(left));
  const b = fs.readFileSync(path.resolve(right));
  const result = { left: path.resolve(left), right: path.resolve(right), left_sha256: sha256(a), right_sha256: sha256(b), equal: a.equals(b), left_bytes: a.length, right_bytes: b.length };
  if (result.equal) return result;
  const ta = detectText(a), tb = detectText(b);
  if (ta.text && tb.text) {
    const al = a.toString('utf8').split(/\r?\n/), bl = b.toString('utf8').split(/\r?\n/);
    let line = 0;
    while (line < Math.min(al.length, bl.length) && al[line] === bl[line]) line++;
    return { ...result, kind: 'text', first_difference_line: line + 1, left_line: al[line] ?? null, right_line: bl[line] ?? null };
  }
  let offset = 0;
  while (offset < Math.min(a.length, b.length) && a[offset] === b[offset]) offset++;
  return { ...result, kind: 'binary', first_difference_offset: offset };
}

function findDuplicates(root) {
  const files = walk(path.resolve(root), null, { limit: 5000 });
  const bySize = new Map();
  for (const file of files) {
    const size = fs.statSync(file).size;
    if (!size) continue;
    const group = bySize.get(size) || [];
    group.push(file);
    bySize.set(size, group);
  }
  const duplicates = [];
  for (const [bytes, candidates] of bySize) {
    if (candidates.length < 2) continue;
    const hashes = new Map();
    for (const file of candidates) {
      const hash = sha256(fs.readFileSync(file));
      const group = hashes.get(hash) || [];
      group.push(file);
      hashes.set(hash, group);
    }
    for (const [hash, matches] of hashes) if (matches.length > 1) duplicates.push({ bytes, sha256: hash, files: matches });
  }
  return { root: path.resolve(root), scanned: files.length, duplicates };
}

function stripXml(value) {
  return String(value).replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/\s+/g, ' ').trim();
}

function extractDocument(file) {
  const full = path.resolve(file);
  const ext = path.extname(full).toLowerCase();
  const bytes = fs.readFileSync(full);
  if (ext === '.html' || ext === '.htm') return { path: full, format: 'html', text: stripXml(bytes.toString('utf8')), partial: false };
  if (ext === '.pdf') {
    const strings = [...bytes.toString('latin1').matchAll(/\(([^()]*)\)/g)].map((m) => m[1].replace(/\\[()\\]/g, (x) => x.slice(1))).filter(Boolean);
    return { path: full, format: 'pdf', text: strings.join('\n'), partial: true, note: 'Solo se extrajeron cadenas PDF sin descomprimir flujos.' };
  }
  if (!['.docx', '.xlsx', '.pptx'].includes(ext) || magic(bytes) !== 'zip') throw new Error('Solo se extraen DOCX, XLSX, PPTX, HTML y PDF.');
  const entries = zipEntries(bytes);
  const read = (name) => { const item = entries.find((entry) => entry.name === name); return item ? zipContent(bytes, item).toString('utf8') : ''; };
  let sources;
  if (ext === '.docx') sources = [read('word/document.xml')];
  else if (ext === '.pptx') sources = entries.filter((entry) => /^ppt\/slides\/slide\d+\.xml$/.test(entry.name)).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })).map((entry) => zipContent(bytes, entry).toString('utf8'));
  else {
    const shared = [...read('xl/sharedStrings.xml').matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((match) => stripXml(match[1]));
    sources = entries.filter((entry) => /^xl\/worksheets\/sheet\d+\.xml$/.test(entry.name)).map((entry) => zipContent(bytes, entry).toString('utf8').replace(/<v>(\d+)<\/v>/g, (_, value) => shared[Number(value)] ?? value));
  }
  return { path: full, format: ext.slice(1), text: sources.map(stripXml).filter(Boolean).join('\n\n'), partial: false };
}

module.exports = { inspectFile, archiveInfo, extractArchive, codeMap, compareFiles, findDuplicates, extractDocument, zipEntries, zipContent };
