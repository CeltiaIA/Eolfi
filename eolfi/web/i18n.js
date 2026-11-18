// Idioma del panel (C1): castellano por defecto e inglés con un diccionario cuya clave es el propio texto en castellano
// (/i18n-en.json). Así el HTML y el JS siguen escritos en castellano y no hay claves que mantener aparte.
//
// - Elección: la guardada en este navegador, después ?lang=es|en; si no hay ninguna, castellano (no se deduce del
//   navegador: un VS Code o un Chrome en inglés no deben cambiar el panel sin que se pida).
// - En inglés se traduce cada nodo de texto y los atributos title, placeholder y aria-label cuyo texto completo
//   (con el espacio en blanco normalizado) está en el diccionario, también lo que el JS añade después.
// - Nunca se traduce el contenido del usuario ni de los objetivos: lo que esté dentro de [data-i18n-no], pre, code,
//   textarea, script o style, ni el valor de los campos. Solo coincidencias exactas.
// - Textos con partes variables (C1, 18/11): una clave con «{}» es una plantilla («Listo en {} s» → «Done in {} s»)
//   que se reconoce en el texto ya escrito; cada hueco se pasa tal cual o, si es entero un texto del diccionario
//   («NO reproducible»), traducido. En la traducción, «{}» toma los huecos en orden y «{0}», «{1}»… por posición.
// - window.eolfiT(texto) devuelve la traducción de un texto (o el mismo texto) para el JS que la necesite.
(() => {
  'use strict';
  const CLAVE = 'eolfi.idioma';
  const IDIOMAS = ['es', 'en'];
  const ATRIBUTOS = ['title', 'placeholder', 'aria-label'];
  const NO = '[data-i18n-no], pre, code, textarea, script, style';

  function guardado() {
    try { return localStorage.getItem(CLAVE); } catch { return null; }
  }

  function elegir() {
    const g = guardado();
    if (IDIOMAS.includes(g)) return g;
    const q = new URLSearchParams(location.search).get('lang');
    if (IDIOMAS.includes(q)) return q;
    return 'es';
  }

  const idioma = elegir();
  let dic = null;
  let plantillas = [];
  window.eolfiIdioma = idioma;
  window.eolfiT = (texto) => (dic && traducir(normalizar(texto))) || texto;
  document.documentElement.lang = idioma;
  // La API lee esta cookie para responder sus errores en el mismo idioma que el panel.
  document.cookie = `eolfi_idioma=${idioma}; Path=/; SameSite=Strict`;

  function normalizar(t) { return String(t).replace(/\s+/g, ' ').trim(); }

  function prepararPlantillas() {
    const escapar = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    plantillas = Object.keys(dic).filter((k) => k.includes('{}')).map((k) => ({
      re: new RegExp(`^${k.split('{}').map(escapar).join('(.+?)')}$`, 's'),
      trad: dic[k],
      fijo: k.replace(/\{\}/g, '').length,
    })).sort((a, b) => b.fijo - a.fijo);   // la más concreta primero
  }

  // Traducción de un texto ya normalizado: exacta o por plantilla; null si no hay.
  function traducir(clave) {
    if (!clave) return null;
    if (Object.prototype.hasOwnProperty.call(dic, clave)) return dic[clave];
    for (const p of plantillas) {
      const m = clave.match(p.re);
      if (!m) continue;
      const huecos = m.slice(1).map((h) => (Object.prototype.hasOwnProperty.call(dic, h) ? dic[h] : h));
      let i = 0;
      return p.trad.replace(/\{(\d*)\}/g, (_, n) => (n === '' ? huecos[i++] : huecos[Number(n)]) ?? '');
    }
    return null;
  }

  function traducirTexto(nodo) {
    const padre = nodo.parentElement;
    if (!padre || padre.closest(NO)) return;
    const original = nodo.nodeValue;
    const clave = normalizar(original);
    const trad = traducir(clave);
    if (!trad || trad === clave) return;
    const inicio = original.match(/^\s*/)[0];
    const fin = original.match(/\s*$/)[0];
    nodo.nodeValue = inicio + trad + fin;
  }

  function traducirAtributos(el) {
    if (el.parentElement && el.parentElement.closest(NO)) return;
    for (const a of ATRIBUTOS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const trad = traducir(normalizar(v));
      if (trad && trad !== v) el.setAttribute(a, trad);
    }
  }

  function traducirArbol(raiz) {
    if (raiz.nodeType === Node.TEXT_NODE) { traducirTexto(raiz); return; }
    if (raiz.nodeType !== Node.ELEMENT_NODE) return;
    if (raiz.matches(NO)) { traducirAtributos(raiz); return; }
    traducirAtributos(raiz);
    const recorrido = document.createTreeWalker(raiz, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        if (n.nodeType === Node.ELEMENT_NODE && n.matches(NO)) {
          // Los atributos de un elemento excluido (el placeholder de un textarea, el aria-label de un registro)
          // son de la interfaz y sí se traducen; su contenido, no.
          traducirAtributos(n);
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    for (let n = recorrido.nextNode(); n; n = recorrido.nextNode()) {
      if (n.nodeType === Node.TEXT_NODE) traducirTexto(n); else traducirAtributos(n);
    }
  }

  function aplicar() {
    if (document.title && dic[normalizar(document.title)]) document.title = dic[normalizar(document.title)];
    traducirArbol(document.body);
    new MutationObserver((cambios) => {
      for (const c of cambios) {
        if (c.type === 'childList') c.addedNodes.forEach(traducirArbol);
        else if (c.type === 'characterData') traducirTexto(c.target);
        else if (c.type === 'attributes') traducirAtributos(c.target);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ATRIBUTOS });
  }

  function selector() {
    const sel = document.getElementById('idioma');
    if (!sel) return;
    sel.value = idioma;
    sel.addEventListener('change', () => {
      try { localStorage.setItem(CLAVE, sel.value); } catch { /* sin almacenamiento: solo esta visita */ }
      const url = new URL(location.href);
      url.searchParams.set('lang', sel.value);
      location.replace(url.toString());
    });
  }

  function cuandoListo(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
    else fn();
  }

  cuandoListo(selector);
  if (idioma === 'en') {
    fetch('/i18n-en.json', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { dic = d; prepararPlantillas(); cuandoListo(aplicar); })
      .catch((e) => console.warn('Eolfi: sin diccionario inglés, el panel sigue en castellano', e));
  }
})();
