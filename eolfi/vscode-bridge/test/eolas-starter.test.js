'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { makeEolasStarter } = require('../eolas-starter');
const { makeLocalModel, EOLAS_URL, EOLAS_MODEL } = require('../local-model');

const reply = (body) => ({ ok: true, json: async () => body });

function tempLauncher() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-eolas-starter-'));
  const script = path.join(dir, 'launch-eolas.ps1');
  fs.writeFileSync(script, '# synthetic launcher\n');
  return { dir, script };
}

test('autoarranque: Eolfi lanza CELTIAIA/Eolas con el Gemma 12B exacto y no lo para al cerrar', async () => {
  const tmp = tempLauncher();
  try {
    let call;
    let launched = false;
    let killed = false;
    const spawnFn = (exe, args, options) => {
      call = { exe, args, options };
      launched = true;
      const child = new EventEmitter();
      child.kill = () => { killed = true; };
      setImmediate(() => child.emit('close', 0));
      return child;
    };
    const fetchFn = async (url) => launched && url === `${EOLAS_URL}/api/tags`
      ? reply({ models: [{ name: EOLAS_MODEL }] }) : { ok: false };
    const starter = makeEolasStarter({ launcher: tmp.script, endpoint: EOLAS_URL, model: EOLAS_MODEL,
      spawnFn, fetchFn, readyMs: 50, pollMs: 1 });
    const lm = makeLocalModel({ endpoints: [EOLAS_URL], model: EOLAS_MODEL, fetchFn, starter,
      allowStart: async () => true });
    const at = await lm.locate();
    assert.deepStrictEqual(at, { url: EOLAS_URL, api: 'eolas', model: EOLAS_MODEL });
    assert.strictEqual(call.exe, 'powershell.exe');
    assert.ok(call.args.includes('-Backend') && call.args.includes('llama'));
    assert.ok(call.args.includes('-EolasPort') && call.args.includes('11435'));
    assert.ok(call.args.includes('-Detach') && call.args.includes('-NoBrowser'));
    assert.ok(!call.args.some((x) => /8090|8080|\.gguf|llama-server/i.test(x)));
    lm.stop();
    assert.strictEqual(killed, false);
  } finally { fs.rmSync(tmp.dir, { recursive: true, force: true }); }
});

test('autoarranque: se detiene si CELTIAIA no anuncia el Gemma 12B exacto', async () => {
  const tmp = tempLauncher();
  try {
    const spawnFn = () => {
      const child = new EventEmitter();
      child.kill = () => {};
      setImmediate(() => child.emit('close', 0));
      return child;
    };
    const fetchFn = async () => reply({ models: [{ name: 'other-model:latest' }] });
    const starter = makeEolasStarter({ launcher: tmp.script, spawnFn, fetchFn, readyMs: 8, pollMs: 1 });
    await assert.rejects(starter.start(), /no anuncia gemma-4-12b-it:latest/);
  } finally { fs.rmSync(tmp.dir, { recursive: true, force: true }); }
});
