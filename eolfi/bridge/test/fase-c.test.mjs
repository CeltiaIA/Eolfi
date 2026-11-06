// Fase C del plan de mejoras: detalles del puente (B1, B3).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { startBridgeServer } from '../server.mjs';
import { SUPPORTED_KEYS } from '../engine/chrome.mjs';

test('B1: sin panelToken el puente no arranca', () => {
  assert.throws(() => startBridgeServer({ adapters: {}, approve: async () => true, token: 'a'.repeat(64) }), /panelToken/);
  assert.throws(() => startBridgeServer({ adapters: {}, approve: async () => true, token: 'a'.repeat(64), panelToken: 'a'.repeat(64) }), /panelToken/);
});

test('B3: solo teclas propias, nunca claves heredadas', () => {
  assert.ok(SUPPORTED_KEYS.includes('Enter'));
  assert.ok(!SUPPORTED_KEYS.includes('__proto__') && !SUPPORTED_KEYS.includes('constructor'));
});
