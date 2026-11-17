"""Textos fijos del panel (``eolfi/web/index.html``) y su cobertura en el diccionario inglés (C1).

Extrae, con el espacio en blanco normalizado igual que ``eolfi/web/i18n.js``, cada nodo de texto visible y los
atributos ``title``, ``placeholder`` y ``aria-label``. Sin argumentos imprime la cobertura; con ``--faltan`` lista
los textos que no tienen traducción.
Uso: python tools/i18n_panel.py [--faltan]
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    c = cobertura()
    if "--faltan" in sys.argv:
        print(json.dumps(c["faltan"], ensure_ascii=False, indent=1))
    else:
        print(json.dumps({k: v for k, v in c.items() if k != "faltan"} | {"faltan": len(c["faltan"])},
                         ensure_ascii=False))
