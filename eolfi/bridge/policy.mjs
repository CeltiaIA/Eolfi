/**
 * @param {{ origin: string, authHostSuffixes?: string[] }} site
 * @param {string} target
 * @param {Set<string>} authHosts
 * @returns {boolean}
 */
export function allowedNavigation(site, target, authHosts) {
  try {
    const u = new URL(target);
    if (u.protocol !== 'https:') return false;
    
    const isOrigin = u.origin === site.origin;
    const isAuthHost = authHosts.has(u.hostname);
    const isSiteSuffix = (site.authHostSuffixes || []).some(h => 
      u.hostname === h || (h.startsWith('.') && u.hostname.endsWith(h))
    );

    return isOrigin || isAuthHost || isSiteSuffix;
  } catch {
    return false;
  }
}

// Permisos que el motor Chrome deniega con Browser.setPermission (nombres de PermissionDescriptor de CDP):
// los usos sensibles que permissionDecision deniega en Electron (dispositivos, ubicación, notificaciones,
// lectura del portapapeles, pantalla y ventanas).
export const DENIED_PERMISSIONS = ['geolocation', 'notifications', 'camera', 'microphone', 'midi', 'display-capture',
  'clipboard-read', 'idle-detection', 'window-management', 'local-fonts', 'accelerometer', 'gyroscope', 'magnetometer',
  'ambient-light-sensor', 'background-sync', 'payment-handler'];

export function siteSuffixes(name) {
  const suffixes = {
    deepseek: ['.deepseek.com'],
    gemini: ['.google.com'],
    meta: ['.meta.ai']
  };
  return suffixes[name] || [];
}

/**
 * @param {{ origin: string, authHostSuffixes?: string[] }} site
 * @param {string} permission
 * @param {string} requestingUrl
 * @returns {boolean}
 */
export function permissionDecision(site, permission, requestingUrl) {
  if (permission === 'clipboard-sanitized-write') {
    try {
      const u = new URL(requestingUrl);
      return u.origin === site.origin;
    } catch {
      return false;
    }
  }
  return false;
}

// O6 (H3): Electron 45 de serie trae EnableCookieEncryption deshabilitado y RunAsNode,
// NODE_OPTIONS e --inspect habilitados. Sin empaquetar con @electron/fuses, las cookies
// de las particiones persist:eolfi-* quedan sin ese cifrado. Devuelve el aviso o null.
export function electronEngineWarning(engine, packaged) {
  if (engine !== 'electron' || packaged) return null;
  return 'Aviso: motor Electron sin empaquetar. Las sesiones de los chats (cookies de persist:eolfi-*) ' +
    'se guardan sin el cifrado de cookies del fusible EnableCookieEncryption, y RunAsNode, NODE_OPTIONS e ' +
    '--inspect siguen habilitados. Motor recomendado: tu navegador (Chrome/Edge), el predeterminado si hay uno instalado.';
}
