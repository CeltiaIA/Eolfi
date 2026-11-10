import test from 'node:test';
import assert from 'node:assert/strict';
import { allowedNavigation, siteSuffixes, permissionDecision } from '../policy.mjs';

test('allowedNavigation - origen propio admitido', () => {
  const site = { origin: 'https://deepseek.com', authHostSuffixes: [] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'https://deepseek.com/chat', authHosts), true);
});

test('allowedNavigation - http denegado', () => {
  const site = { origin: 'https://deepseek.com', authHostSuffixes: [] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'http://deepseek.com/chat', authHosts), false);
});

test('allowedNavigation - DeepSeek -> meta.ai denegado', () => {
  const site = { origin: 'https://deepseek.com', authHostSuffixes: [] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'https://www.meta.ai', authHosts), false);
});

test('allowedNavigation - google.com denegados para gemini (sin authHosts)', () => {
  const site = { origin: 'https://gemini.google.com', authHostSuffixes: [] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'https://evilgoogle.com', authHosts), false);
  assert.strictEqual(allowedNavigation(site, 'https://google.com.evil.net', authHosts), false);
});

test('allowedNavigation - authHosts admitido', () => {
  const site = { origin: 'https://gemini.google.com', authHostSuffixes: [] };
  const authHosts = new Set(['accounts.google.com']);
  assert.strictEqual(allowedNavigation(site, 'https://accounts.google.com/x', authHosts), true);
});

test('allowedNavigation - sufijo del sitio admitido', () => {
  const site = { origin: 'https://deepseek.com', authHostSuffixes: ['.deepseek.com'] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'https://chat.deepseek.com', authHosts), true);
});

test('allowedNavigation - URL inválida denegada', () => {
  const site = { origin: 'https://deepseek.com', authHostSuffixes: [] };
  const authHosts = new Set();
  assert.strictEqual(allowedNavigation(site, 'not-a-url', authHosts), false);
});

test('permissionDecision - deniega media, geolocation y notifications', () => {
  const site = { origin: 'https://meta.ai' };
  assert.strictEqual(permissionDecision(site, 'media', 'https://meta.ai'), false);
  assert.strictEqual(permissionDecision(site, 'geolocation', 'https://meta.ai'), false);
  assert.strictEqual(permissionDecision(site, 'notifications', 'https://meta.ai'), false);
});

test('permissionDecision - admite clipboard-sanitized-write solo del mismo origen', () => {
  const site = { origin: 'https://meta.ai' };
  assert.strictEqual(permissionDecision(site, 'clipboard-sanitized-write', 'https://meta.ai/chat'), true);
  assert.strictEqual(permissionDecision(site, 'clipboard-sanitized-write', 'https://evil.com'), false);
});

test('electronEngineWarning - avisa solo con Electron sin empaquetar (O6)', async () => {
  const { electronEngineWarning } = await import('../policy.mjs');
  const msg = electronEngineWarning('electron', false);
  assert.match(msg, /EnableCookieEncryption/);
  assert.match(msg, /persist:eolfi-/);
  assert.strictEqual(electronEngineWarning('electron', true), null);
  assert.strictEqual(electronEngineWarning('browser', false), null);
});
