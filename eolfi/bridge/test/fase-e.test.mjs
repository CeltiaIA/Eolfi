// Fase E, grupo 3: espera de respuestas con streaming, plazo por inactividad y texto estable.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { waitReply } from '../adapters/core.mjs';
import { loadSites, makeDeclarativeAdapter } from '../adapters/declarative.mjs';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('plazo por inactividad: una respuesta que sigue creciendo no caduca', async () => {
  let n = 0;
  const partials = [];
  const t0 = Date.now();
  // Plazo de inactividad 150 ms; la respuesta tarda ~400 ms pero crece en cada lectura.
  const text = await waitReply(async () => {
    n++;
    return [{ id: 'a', text: 'x'.repeat(Math.min(n, 8)), complete: n >= 10 }];
  }, new Set(), undefined, 150, 40, 'Prueba', (t) => partials.push(t.length));
  assert.equal(text, 'x'.repeat(8));
  assert.ok(Date.now() - t0 >= 150, 'superó el plazo de inactividad sin caducar');
  assert.deepEqual(partials, [1, 2, 3, 4, 5, 6, 7, 8]);
});

test('plazo por inactividad: si deja de crecer sin terminar, caduca', async () => {
  await assert.rejects(waitReply(async () => [{ id: 'a', text: 'a medias', complete: false }],
    new Set(), undefined, 120, 30, 'Prueba'), /tiempo límite/);
});

test('texto estable: «completa» no basta si el texto acaba de cambiar (M4)', async () => {
  const seq = [['uno', true], ['uno dos', true], ['uno dos', true]];
  let i = 0;
  const text = await waitReply(async () => {
    const [t, c] = seq[Math.min(i++, seq.length - 1)];
    return [{ id: 'a', text: t, complete: c }];
  }, new Set(), undefined, 1000, 10, 'Prueba');
  assert.equal(text, 'uno dos');   // con una sola señal habría devuelto «uno»
});

test('sitios declarativos: recalibrar solo cambia selectores de chats conocidos', () => {
  const dir = mkdtempSync(join(tmpdir(), 'eolfi-sites-'));
  const f = join(dir, 'bridge-sites.json');
  writeFileSync(f, JSON.stringify({
    chatgpt: { editor: ['#nuevo'], origin: 'https://evil.example' },   // origin no se puede cambiar
    inventado: { origin: 'https://evil.example', editor: ['x'] },      // ni añadir sitios
  }));
  const s = loadSites(f);
  assert.deepEqual(s.chatgpt.editor, ['#nuevo']);
  assert.equal(s.chatgpt.origin, 'https://chatgpt.com');
  assert.equal(s.chatgpt.recalibrated, true);
  assert.ok(!('inventado' in s));
  assert.ok(['copilot', 'lechat'].every((k) => k in s));
  const A = makeDeclarativeAdapter(s.chatgpt);
  assert.equal(new A({ isDestroyed: () => false, getURL: () => '' }).label, 'ChatGPT web');
});

test('recalibrar: completeAttr y completeWithin se aceptan solo si son válidos', () => {
  const dir = mkdtempSync(join(tmpdir(), 'eolfi-sites-'));
  const f = join(dir, 'bridge-sites.json');
  writeFileSync(f, JSON.stringify({
    chatgpt: { completeAttr: 'data-done', completeWithin: { container: '[data-id]', selector: 'button.like' } },
    lechat: { completeAttr: 'x"]; alert(1)//', completeWithin: { container: 3 } },
  }));
  const s = loadSites(f);
  assert.equal(s.chatgpt.completeAttr, 'data-done');
  assert.deepEqual(s.chatgpt.completeWithin, { container: '[data-id]', selector: 'button.like' });
  assert.notEqual(s.lechat.completeAttr, 'x"]; alert(1)//');
  assert.equal(s.lechat.completeWithin.container, '[data-message-id]');   // el calibrado de fábrica
});
