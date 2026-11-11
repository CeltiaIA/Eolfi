Necesito código JavaScript (módulos ES, Node 22, sin dependencias) para un puente Electron/Chrome que abre ventanas de chats web (DeepSeek, Gemini, Meta AI y otros declarados en sites.json). Devuelve SOLO los archivos completos indicados, cada uno en su bloque de código con la ruta como título. Sin explicaciones largas.

## Situación actual (main.mjs, extracto)

```js
const SITES = {
  deepseek: { url: `${DEEPSEEK_ORIGIN}/`, origin: DEEPSEEK_ORIGIN, Adapter: DeepseekAdapter, title: 'DeepSeek web' },
  gemini: { url: `${GEMINI_ORIGIN}/app`, origin: GEMINI_ORIGIN, Adapter: GeminiAdapter, title: 'Gemini web' },
  meta: { url: META_ORIGIN, origin: META_ORIGIN, Adapter: MetaAdapter, title: 'Meta AI web' },
};
// + sitios de sites.json con authHostSuffixes, p. ej. [".openai.com", "auth.openai.com", "accounts.google.com"]
const AUTH_HOSTS = new Set(['accounts.google.com', 'myaccount.google.com', 'appleid.apple.com', 'account.apple.com',
  'auth.meta.com', 'accountscenter.meta.com', 'www.facebook.com', 'www.instagram.com']);

function allowedNavigation(name, target) {
  try {
    const u = new URL(target);
    return u.protocol === 'https:' && (u.origin === SITES[name].origin || AUTH_HOSTS.has(u.hostname) || u.hostname.endsWith('.google.com') || u.hostname.endsWith('.deepseek.com') || u.hostname.endsWith('.meta.ai')
      || (SITES[name].authHostSuffixes || []).some((h) => u.hostname === h || (h.startsWith('.') && u.hostname.endsWith(h))));
  } catch { return false; }
}
// BrowserWindow con webPreferences: { partition: `persist:eolfi-${name}`, contextIsolation: true, sandbox: true, nodeIntegration: false }
// No hay session.setPermissionRequestHandler ni setPermissionCheckHandler.
```

Problemas: (1) los sufijos `.google.com`, `.deepseek.com` y `.meta.ai` valen para TODOS los sitios (la ventana de DeepSeek puede navegar a *.meta.ai); (2) sin manejadores de permisos, Electron concede por defecto lo que pidan las páginas.

## Lo que quiero

### Archivo 1: `eolfi/bridge/policy.mjs`
Funciones puras exportadas, sin importar Electron:
- `allowedNavigation(site, target, authHosts)` — `site` = `{ origin, authHostSuffixes }`. `true` solo si la URL es `https:` y: su origen es `site.origin`; o su host está en `authHosts` (Set); o el host es igual a un elemento de `site.authHostSuffixes`, o termina en un elemento que empieza por `.`. URL inválida → `false`. Sin sufijos globales.
- `siteSuffixes(name)` — sufijos que antes eran globales, ahora por sitio: `deepseek → ['.deepseek.com']`, `gemini → ['.google.com']`, `meta → ['.meta.ai']`, el resto `[]`.
- `permissionDecision(site, permission, requestingUrl)` — devuelve `false` siempre, salvo `permission === 'clipboard-sanitized-write'` con `requestingUrl` del mismo origen que `site.origin`.

### Archivo 2: `eolfi/bridge/test/policy.test.mjs`
Con `node:test` y `node:assert/strict`. Casos: origen propio admitido; `http:` denegado; DeepSeek → `https://www.meta.ai` denegado; `https://evilgoogle.com` y `https://google.com.evil.net` denegados para gemini; `https://accounts.google.com/x` admitido (authHosts); sufijo del sitio admitido (`https://chat.deepseek.com` para deepseek con sus sufijos); URL inválida denegada; `permissionDecision` deniega `media`, `geolocation` y `notifications`, admite `clipboard-sanitized-write` solo del mismo origen.

### Cambio 3: en `eolfi/bridge/main.mjs`
Muestra solo las líneas que cambian:
- `import { allowedNavigation as policyAllowed, siteSuffixes, permissionDecision } from './policy.mjs';` y `session` desde `electron`.
- Al construir SITES, añade `authHostSuffixes: [...siteSuffixes(name), ...(cfg.authHostSuffixes || [])]` (también para deepseek, gemini y meta).
- Sustituye el cuerpo de `allowedNavigation(name, target)` por `return policyAllowed(SITES[name], target, AUTH_HOSTS);`.
- En `openWindow(name)`, antes de crear la ventana: `const ses = session.fromPartition(\`persist:eolfi-${name}\`); ses.setPermissionRequestHandler((wc, perm, cb, details) => cb(permissionDecision(SITES[name], perm, details?.requestingUrl || wc.getURL()))); ses.setPermissionCheckHandler((wc, perm, origin) => permissionDecision(SITES[name], perm, origin));`
