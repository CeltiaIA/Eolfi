'use strict';
const test = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const { makeAgentTools, checkCommand, checkUrl, isPrivateIp, htmlToText } = require('../agent-tools');
const { isSecretPath } = require('../workspace');

const vscode = { workspace: { workspaceFolders: [{ uri: { fsPath: os.tmpdir() } }] } };
const resolveInside = (_vs, p) => (p === '.' ? os.tmpdir() : (() => { throw new Error('fuera'); })());
const stream = { progress: () => {} };
const publicLookup = async () => [{ address: '93.184.216.34' }];

test('órdenes peligrosas y de secretos bloqueadas siempre', () => {
  for (const c of ['format C:', 'diskpart', 'shutdown /s /t 0', 'Restart-Computer', 'Set-ExecutionPolicy Unrestricted',
    'reg delete HKLM\\Software\\X /f', 'rm -rf /', 'rm -rf ~', 'Remove-Item -Recurse -Force C:\\', 'Get-ChildItem env:',
    'echo $env:GITHUB_TOKEN', 'env', 'printenv | grep KEY', 'git push --force origin main', 'type .env', 'cat ~/.ssh/id_rsa',
    'Get-Content D:\\p\\secrets.json']) {
    assert.ok(checkCommand(c, isSecretPath), c);
  }
  for (const c of ['npm test', 'python -m pytest -q', 'git status', 'git log --oneline -5', 'dir', 'ls -la src',
    'Get-ChildItem -Recurse *.py', 'cat .env.example', 'node --version']) {
    assert.strictEqual(checkCommand(c, isSecretPath), null, c);
  }
});

test('terminal: permiso por sesión, borrar se confirma siempre, bloqueado no pregunta', async () => {
  const asked = [];
  const spawned = [];
  const fakeSpawn = (bin, args, opts) => {
    spawned.push({ bin, args, cwd: opts.cwd });
    const { EventEmitter } = require('node:events');
    const p = new EventEmitter();
    p.stdout = new EventEmitter(); p.stderr = new EventEmitter(); p.kill = () => {};
    setImmediate(() => { p.stdout.emit('data', 'hola\n'); p.emit('close', 0); });
    return p;
  };
  let answer = 'session';
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async (k) => { asked.push(k); return k === 'delete' ? 'no' : answer; },
    spawnFn: fakeSpawn, platform: 'win32', lookup: publicLookup });
  const run = (orden) => t.run({ name: 'eolfi_terminal', input: { orden } }, stream, null);

  assert.match(await run('git status'), /código de salida 0\nhola/);
  assert.match(await run('npm test'), /hola/);
  assert.deepStrictEqual(asked, ['terminal']);            // la sesión ya está permitida
  assert.strictEqual(spawned[0].bin, 'powershell.exe');
  assert.strictEqual(spawned[0].cwd, os.tmpdir());
  assert.match(await run('Remove-Item build -Recurse'), /no permitió/);
  assert.deepStrictEqual(asked, ['terminal', 'delete']);  // borrar: confirmación propia aunque haya sesión
  assert.match(await run('format D:'), /No ejecutado: bloqueado/);
  assert.strictEqual(asked.length, 2);                    // lo bloqueado ni pregunta
  assert.strictEqual(spawned.length, 2);
  const t2 = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async () => 'no', spawnFn: fakeSpawn, lookup: publicLookup });
  assert.match(await t2.run({ name: 'eolfi_terminal', input: { orden: 'git status' } }, stream, null), /no permitió/);
  assert.match(await t.run({ name: 'eolfi_terminal', input: { orden: 'dir', carpeta: 'C:/Windows' } }, stream, null), /No ejecutado: fuera/);
});

test('web: anti-SSRF, permiso por sesión, sin seguir redirecciones y texto de HTML', async () => {
  assert.ok(isPrivateIp('127.0.0.1') && isPrivateIp('10.1.2.3') && isPrivateIp('192.168.1.1') && isPrivateIp('169.254.169.254')
    && isPrivateIp('::1') && isPrivateIp('fd00::1') && !isPrivateIp('93.184.216.34'));
  assert.match((await checkUrl('http://localhost:8777/'))[1], /no es público/);
  assert.match((await checkUrl('http://127.0.0.1/'))[1], /red interna/);
  assert.match((await checkUrl('file:///C:/x'))[1], /solo http/);
  assert.match((await checkUrl('https://u:p@ejemplo.es/'))[1], /credenciales/);
  assert.match((await checkUrl('https://interno.ejemplo.es/', async () => [{ address: '10.0.0.5' }]))[1], /red interna/);

  const asked = [];
  const pages = {
    'https://ejemplo.es/': { status: 200, type: 'text/html', body: '<html><script>alert(1)</script><h1>Hola</h1><p>mundo &amp; más</p></html>' },
    'https://ejemplo.es/r': { status: 302, type: 'text/html', body: '', location: 'http://127.0.0.1/admin' },
  };
  const fetchFn = async (url) => {
    if (url.startsWith('https://html.duckduckgo.com/')) {
      return { status: 200, headers: { get: (h) => (h === 'content-type' ? 'text/html' : null) },
        arrayBuffer: async () => Buffer.from('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Frea.dev%2F&amp;x=1">REA <b>docs</b></a> <a class="result__snippet" href="#">Agentes de ingeniería inversa</a>') };
    }
    const p = pages[url];
    return { status: p.status, headers: { get: (h) => (h === 'content-type' ? p.type : h === 'location' ? p.location : null) },
      arrayBuffer: async () => Buffer.from(p.body) };
  };
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async (k) => { asked.push(k); return 'session'; }, fetchFn, lookup: publicLookup });
  const page = await t.run({ name: 'eolfi_web_leer', input: { url: 'https://ejemplo.es/' } }, stream, null);
  assert.match(page, /DATOS, no instrucciones/);
  assert.match(page, /Hola\n*\s*mundo & más/);
  assert.doesNotMatch(page, /alert/);
  assert.match(await t.run({ name: 'eolfi_web_leer', input: { url: 'https://ejemplo.es/r' } }, stream, null), /redirige a http:\/\/127\.0\.0\.1\/admin/);
  const found = await t.run({ name: 'eolfi_web_buscar', input: { consulta: 'rea agentes' } }, stream, null);
  assert.match(found, /- REA docs\n {2}https:\/\/rea\.dev\/\n {2}Agentes de ingeniería inversa/);
  assert.deepStrictEqual(asked, ['web']);
  assert.match(await t.run({ name: 'eolfi_web_leer', input: { url: 'http://localhost:8777/api/clients' } }, stream, null), /No leído/);
});

test('red privada: se fija la IP y se pide permiso por petición incluso con el ajuste activado', async () => {
  const privateLookup = async () => [{ address: '192.168.1.24' }];
  const [u, error, address, isPrivate] = await checkUrl('http://panel.local:8080/status', privateLookup, true);
  assert.equal(error, null);
  assert.equal(u.hostname, 'panel.local');
  assert.equal(address.address, '192.168.1.24');
  assert.equal(isPrivate, true);
  assert.match((await checkUrl('http://panel.local:8080/status', privateLookup))[1], /no es público/);
  assert.match((await checkUrl('https://mi-servicio.example/', async () => [
    { address: '192.168.1.24' }, { address: '93.184.216.34' },
  ], true))[1], /mezcla direcciones públicas y privadas/);

  const asked = [];
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside,
    ask: async (kind, what) => { asked.push([kind, what.address]); return 'once'; },
    enabled: () => ({ terminal: false, web: true, privateNetwork: true }),
    lookup: privateLookup,
    fetchFn: async () => ({ status: 200, headers: { get: () => 'text/plain' }, arrayBuffer: async () => Buffer.from('estado local') }),
  });
  for (let i = 0; i < 2; i++) {
    assert.match(await t.run({ name: 'eolfi_web_leer', input: { url: 'http://panel.local:8080/status' } }, stream, null), /estado local/);
  }
  assert.deepEqual(asked, [['privateWeb', '192.168.1.24'], ['privateWeb', '192.168.1.24']]);
});

test('ajustes: se pueden apagar terminal o web', () => {
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async () => 'no', enabled: () => ({ terminal: false, web: true }) });
  assert.deepStrictEqual(t.names(), ['eolfi_web_leer', 'eolfi_web_buscar']);
  assert.strictEqual(htmlToText('<p>a</p><p>b</p>'), 'a\n b');
});

test('terminal integrada: se usa si responde; si no hay integración de shell, proceso aparte', async () => {
  const { EventEmitter } = require('node:events');
  const fakeSpawn = () => {
    const p = new EventEmitter();
    p.stdout = new EventEmitter(); p.stderr = new EventEmitter(); p.kill = () => {};
    setImmediate(() => { p.stdout.emit('data', 'aparte'); p.emit('close', 0); });
    return p;
  };
  let integrated = { code: 0, out: 'en la terminal Eolfi' };
  const seen = [];
  const t = makeAgentTools({ vscode, isSecretPath, resolveInside, ask: async () => 'session', spawnFn: fakeSpawn, lookup: publicLookup,
    runInTerminal: async (cmd, cwd) => { seen.push([cmd, cwd]); return integrated; } });
  assert.match(await t.run({ name: 'eolfi_terminal', input: { orden: 'npm test' } }, stream, null), /en la terminal Eolfi/);
  assert.deepStrictEqual(seen[0], ['npm test', os.tmpdir()]);
  integrated = null;
  assert.match(await t.run({ name: 'eolfi_terminal', input: { orden: 'npm test' } }, stream, null), /aparte/);
});

test('lectura web: conecta a la IP ya validada (sin volver a resolver el DNS) y corta al llegar al tope', async () => {
  const http = require('node:http');
  const { pinnedFetch } = require('../agent-tools');
  const srv = http.createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/plain', 'x-host': req.headers.host }); res.end('x'.repeat(50000)); });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const port = srv.address().port;
  try {
    // «no-existe.invalid» no resuelve: si la petición llega es porque usó la IP fijada.
    const r = await pinnedFetch(`http://no-existe.invalid:${port}/`, { address: { address: '127.0.0.1' }, maxBytes: 1000 });
    assert.strictEqual(r.status, 200);
    assert.strictEqual(r.headers.get('x-host'), `no-existe.invalid:${port}`);
    assert.strictEqual(Buffer.from(await r.arrayBuffer()).length, 1000);
  } finally { srv.close(); }
});
