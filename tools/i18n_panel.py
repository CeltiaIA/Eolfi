"""Textos fijos del panel (``eolfi/web/index.html``) y su cobertura en el diccionario inglés (C1).

Extrae, con el espacio en blanco normalizado igual que ``eolfi/web/i18n.js``, cada nodo de texto visible y los
atributos ``title``, ``placeholder`` y ``aria-label``. Sin argumentos imprime la cobertura; con ``--faltan`` lista
los textos que no tienen traducción.
Uso: python tools/i18n_panel.py [--js] [--faltan]   (--js: los textos del JS del panel)
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "eolfi" / "web"
ATRIBUTOS = ("title", "placeholder", "aria-label")
_LETRAS = re.compile(r"[A-Za-zÁÉÍÓÚÜáéíóúüÑñ]{2}")


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.textos: list[str] = []
        self._saltar = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._saltar += 1
        for k, v in attrs:
            if k in ATRIBUTOS and v and _LETRAS.search(v):
                self.textos.append(normalizar(v))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._saltar -= 1

    def handle_data(self, data: str) -> None:
        texto = normalizar(data)
        if texto and not self._saltar and _LETRAS.search(texto):
            self.textos.append(texto)


def textos_panel() -> list[str]:
    ex = _Extractor()
    ex.feed((WEB / "index.html").read_text(encoding="utf-8"))
    vistos: dict[str, None] = {}
    for t in ex.textos:
        vistos.setdefault(t, None)
    return list(vistos)


def diccionario() -> dict[str, str]:
    return json.loads((WEB / "i18n-en.json").read_text(encoding="utf-8"))


def cobertura() -> dict[str, object]:
    textos = textos_panel()
    dic = diccionario() if (WEB / "i18n-en.json").is_file() else {}
    faltan = [t for t in textos if t not in dic]
    return {"textos": len(textos), "traducidos": len(textos) - len(faltan), "faltan": faltan}


# ── Textos del JS del panel (C1, 18/11/2026) ─────────────────────────────────────────────────────────────────────
# Los avisos y estados que el JS escribe en la página. Un texto fijo se traduce si está entero en el diccionario; uno
# con partes variables (`… ${x} …`) se describe en el diccionario como plantilla con «{}» en cada hueco
# («Listo en {} s») y i18n.js la reconoce en la página ya escrita.
JS = ("app.js", "cases.js", "eolas-chat.js", "mapa.js", "projects.js", "subjects.js", "voz.js")
_CASTELLANO = re.compile(r"[áéíóúñ¿¡]|\b(?:el|la|los|las|del|que|con|para|por|una?|se|sin|no|hay|de|en|y|ya|aún|ni)\b",
                         re.I)
_FRASE = re.compile(r"^(?:\{\}\s*)*[:·—✓✗⬆]?\s*(?:\{\}\s*)*[A-ZÁÉÍÓÚÑ¿¡]")
_NO_FRASE = re.compile(r"https?://|[\[\]=]|^[A-Z][A-Z0-9_]+$|^[A-Z]:[\\/]")   # y rutas de ejemplo (C:\…)
# Literales que no son texto de la interfaz (identificadores, clases, valores de la API, consultas, selectores).
NO_SON_TEXTO = re.compile(r"^[\w.:#\[\]=\"'/-]+$|^(?:sin-caso|proj-change-no)$")


def _literales(src: str) -> list[tuple[str, bool]]:
    """Literales de cadena de un JS: (texto, es_plantilla). Las plantillas `…${x}…` salen con «{}» en cada hueco.
    Salta comentarios y expresiones regulares; basta para el JS propio del panel (no es un analizador completo)."""
    out: list[tuple[str, bool]] = []
    i, n, previo = 0, len(src), ""
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
            continue
        if src.startswith("/*", i):
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 2
            continue
        if c == "/" and previo in "(,=:[!&|?{};+" + "\n":
            j = i + 1
            clase = False
            while j < n and (src[j] != "/" or clase):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    clase = True
                elif src[j] == "]":
                    clase = False
                elif src[j] == "\n":
                    break
                j += 1
            i, previo = j + 1, "x"
            continue
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\" and j + 1 < n:
                    buf.append({"n": "\n", "t": "\t"}.get(src[j + 1], src[j + 1]))
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append(("".join(buf), False))
            i, previo = j + 1, "x"
            continue
        if c == "`":
            j, buf, plantilla = i + 1, [], False
            while j < n and src[j] != "`":
                if src[j] == "\\" and j + 1 < n:
                    buf.append({"n": "\n", "t": "\t"}.get(src[j + 1], src[j + 1]))
                    j += 2
                    continue
                if src.startswith("${", j):
                    prof, k = 1, j + 2
                    while k < n and prof:
                        prof += {"{": 1, "}": -1}.get(src[k], 0)
                        k += 1
                    out += _literales(src[j + 2:k - 1])   # los textos dentro del hueco también cuentan
                    buf.append("{}")
                    plantilla = True
                    j = k
                    continue
                buf.append(src[j])
                j += 1
            out.append(("".join(buf), plantilla))
            i, previo = j + 1, "x"
            continue
        if not c.isspace():
            previo = c
        elif c == "\n" and previo in ";{}":
            pass
        i += 1
    return out


def textos_js() -> dict[str, str]:
    """Textos de la interfaz en castellano que escribe el JS del panel → archivo donde aparecen."""
    vistos: dict[str, str] = {}
    for nombre in JS:
        for texto, _plantilla in _literales((WEB / nombre).read_text(encoding="utf-8")):
            t = normalizar(texto)
            sin_huecos = t.replace("{}", " ")
            # 18/11/2026: antes solo contaba lo que tenía tildes o palabras como «de»/«la», y se saltaba un centenar
            # de textos reales («Trabajando… {} s», «Puente parado»). Ahora también lo que empieza como una frase
            # (mayúscula o símbolo de la interfaz), salvo selectores y URL.
            frase = _FRASE.match(t) and not _NO_FRASE.search(t)
            if (len(t) < 3 or not re.search(r"[A-Za-zÁÉÍÓÚáéíóúñ]{3}", sin_huecos)
                    or not (_CASTELLANO.search(sin_huecos) or frase)
                    or NO_SON_TEXTO.match(t) or "<" in t or t.startswith(("/api/", "#", "."))):
                continue
            vistos.setdefault(t, nombre)
    return vistos


def cobertura_js() -> dict[str, object]:
    textos = textos_js()
    dic = diccionario()
    faltan = [t for t in textos if t not in dic]
    return {"textos": len(textos), "traducidos": len(textos) - len(faltan), "faltan": faltan}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    c = cobertura_js() if "--js" in sys.argv else cobertura()
    if "--faltan" in sys.argv:
        print(json.dumps(c["faltan"], ensure_ascii=False, indent=1))
    else:
        print(json.dumps({k: v for k, v in c.items() if k != "faltan"} | {"faltan": len(c["faltan"])},
                         ensure_ascii=False))
