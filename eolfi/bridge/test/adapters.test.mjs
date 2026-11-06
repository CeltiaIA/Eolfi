// Los scripts que se inyectan en cada web deben compilar (un error aquí solo se vería en la página real).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DeepseekAdapter } from '../adapters/deepseek.mjs';
import { GeminiAdapter } from '../adapters/gemini.mjs';
import { MetaAdapter } from '../adapters/meta.mjs';

const cases = [
  ['DeepSeek', DeepseekAdapter, 'https://chat.deepseek.com/', { draft: '', blocked: false, rows: [] }],
  ['Gemini', GeminiAdapter, 'https://gemini.google.com/app', { draft: '', blocked: false, rows: [], stop: false }],
  ['Meta AI', MetaAdapter, 'https://www.meta.ai/', { draft: '', blocked: false, replies: [], users: [] }],
];

for (const [name, Adapter, url, state] of cases) {
  for (const guest of [false, true]) {
    test(`${name}: scripts compilan y el estado indica la sesión (${guest ? 'invitado' : 'con sesión'})`, async () => {
      const scripts = [];
      const a = new Adapter({ isDestroyed: () => false, getURL: () => url,
        executeJavaScript: async (src) => { new Function(src); scripts.push(src); return /iniciar sesión/.test(src) ? guest : state; } });
      const st = await a.status();
      assert.equal(st.ok, true);
      assert.equal(st.signedIn, !guest);
      assert.match(st.detail, guest ? /modo invitado/ : /con sesión/);
      assert.ok(scripts.every((s) => /location\.origin !== /.test(s)));   // siempre protegido por origen
    });
  }

  test(`${name}: fuera de su web no ejecuta nada`, async () => {
    let ran = false;
    const a = new Adapter({ isDestroyed: () => false, getURL: () => 'https://auth.example.com/login',
      executeJavaScript: async () => { ran = true; } });
    const st = await a.status();
    assert.equal(st.ok, false);
    assert.match(st.detail, /auth\.example\.com/);
    assert.equal(ran, false);
  });
}
