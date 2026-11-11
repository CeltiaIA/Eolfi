// Meta pliega los bloques de código largos («N líneas ocultas»): la respuesta no puede llegar recortada.
// DOM mínimo simulado: solo lo que lee el script de readState del adaptador.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MetaAdapter } from '../adapters/meta.mjs';

function node({ innerText = '', textContent = innerText, children = [], q = {}, attrs = {} } = {}) {
  const n = { innerText, textContent, children, dataset: {}, clicks: 0, parentElement: null,
    getClientRects: () => [1], getAttribute: (k) => attrs[k] ?? null, closest: () => null,
    querySelector: (s) => (q[s] || [])[0] || null, querySelectorAll: (s) => q[s] || [], click() { n.clicks++; } };
  return n;
}

function page({ withLabels = true, virtualized = false } = {}) {
  const full1 = 'const a = 1;\nconst b = 2;\nconst c = 3;\nconst d = 4;';
  const full2 = 'test(1);\ntest(2);\ntest(3);';
  const code1 = node({ innerText: 'const a = 1;', textContent: virtualized ? 'const a = 1;' : full1 });
  const code2 = node({ innerText: 'test(1);', textContent: virtualized ? 'test(1);' : full2 });
  const pre1 = node({ innerText: 'const a = 1;', q: { code: [code1] } });
  const pre2 = node({ innerText: 'test(1);', q: { code: [code2] } });
  const label1 = node({ innerText: '3 líneas ocultas' });
  const label2 = node({ innerText: '2 líneas ocultas' });
  const part = node({
    innerText: ['Archivo 1:', 'const a = 1;', withLabels ? '3 líneas ocultas' : '', 'Archivo 2:', 'test(1);', withLabels ? '2 líneas ocultas' : '']
      .filter(Boolean).join('\n'),
    q: { 'pre code': [code1, code2], pre: [pre1, pre2] },
  });
  const reply = node({ attrs: { 'data-message-id': 'm1', 'data-turn-id': 't1' },
    q: { 'button,[role="tab"]': [], 'button,[role="button"],span,div': withLabels ? [label1, label2] : [], '.markdown-content': [part] } });
  reply.querySelector = (s) => (s.includes('data-streaming-state') ? {} : null);
  const document = { querySelectorAll: (s) => (s.includes('data-message-role="assistant"') ? [reply] : []), querySelector: () => null };
  return { document, reply, labels: [label1, label2], full1, full2 };
}

function adapterOn(p) {
  return new MetaAdapter({ isDestroyed: () => false, getURL: () => 'https://www.meta.ai/',
    executeJavaScript: async (src) => new Function('document', 'location', `return ${src}`)(p.document, { origin: 'https://www.meta.ai' }) });
}

test('Meta: despliega una vez las líneas ocultas y devuelve el código completo de cada bloque', async () => {
  const p = page();
  const a = adapterOn(p);
  const first = await a.readState();
  assert.equal(first.replies[0].text, '', 'tras pulsar el desplegable la respuesta aún no se da por leída');
  assert.deepEqual(p.labels.map((l) => l.clicks), [1, 1]);
  const second = await a.readState();
  const text = second.replies[0].text;
  assert.ok(text.includes(p.full1) && text.includes(p.full2), text);
  assert.doesNotMatch(text, /líneas ocultas/);
  assert.deepEqual(p.labels.map((l) => l.clicks), [1, 1], 'no vuelve a pulsar');
});

test('Meta: consultar el estado no pulsa nada, pero recupera el código con textContent', async () => {
  const p = page();
  const s = await adapterOn(p).readState(false);
  assert.deepEqual(p.labels.map((l) => l.clicks), [0, 0]);
  assert.ok(s.replies[0].text.includes(p.full1) && s.replies[0].text.includes(p.full2));
});

test('Meta: si el código no está en el DOM, la marca de líneas ocultas se conserva', async () => {
  const p = page({ virtualized: true });
  const s = await adapterOn(p).readState(false);
  assert.match(s.replies[0].text, /3 líneas ocultas/);
});
