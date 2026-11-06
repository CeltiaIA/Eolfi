// Apertura concurrente y arranque único del motor (sin navegador real: se simulan las partes lentas).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ChromeEngine } from '../engine/chrome.mjs';

const fakeContents = () => ({ destroyed: false, isDestroyed() { return this.destroyed; } });

test('tres page() simultáneos del mismo sitio abren UNA sola ventana', async () => {
  const e = new ChromeEngine({ browser: process.execPath, profile: '.' });
  let opened = 0;
  e._page = async (name) => { opened++; await new Promise((r) => setTimeout(r, 50)); const c = fakeContents(); e.pages.set(name, c); return c; };
  const [a, b, c] = await Promise.all([e.page('gemini', 'u', 'o'), e.page('gemini', 'u', 'o'), e.page('gemini', 'u', 'o')]);
  assert.equal(opened, 1);
  assert.ok(a === b && b === c);
  assert.equal(await e.page('gemini', 'u', 'o'), a);               // reutiliza la abierta
  a.destroyed = true;                                              // el usuario cerró la pestaña
  await e.page('gemini', 'u', 'o');
  assert.equal(opened, 2);
});

test('sitios distintos se abren en paralelo y un fallo no bloquea reintentos', async () => {
  const e = new ChromeEngine({ browser: process.execPath, profile: '.' });
  let fail = true;
  e._page = async (name) => {
    if (name === 'meta' && fail) { fail = false; throw new Error('fallo de prueba'); }
    const c = fakeContents(); e.pages.set(name, c); return c;
  };
  await assert.rejects(e.page('meta', 'u', 'o'), /fallo de prueba/);
  assert.ok(await e.page('meta', 'u', 'o'));                       // el reintento sí abre
  assert.ok(await e.page('deepseek', 'u', 'o'));
});

test('start() simultáneos arrancan el navegador una sola vez', async () => {
  const e = new ChromeEngine({ browser: process.execPath, profile: '.' });
  let starts = 0;
  e._start = async () => { starts++; await new Promise((r) => setTimeout(r, 50)); };
  await Promise.all([e.start(), e.start(), e.start()]);
  assert.equal(starts, 1);
  await e.start();                                                 // terminado: puede volver a arrancar
  assert.equal(starts, 2);
});
