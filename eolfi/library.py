"""Búsqueda local, acotada y de solo lectura en el corpus de Alejandría."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ALLOWED_SUFFIXES = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".css", ".html", ".htm", ".ps1", ".psm1", ".sql"}
EXCLUDED_PARTS = {".git", ".claude", ".eolfi", "backups", "backup", "generated", "build", "dist", "node_modules", "samples", "venv", ".venv", "__pycache__"}
MAX_FILE_BYTES = 512_000
MAX_ENTRIES = 25_000
MAX_READ_CHARS = 30_000


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


# 13/11/2026: el «\b» final impedía reconocer constantes («MAX_READ_CHARS = 30_000»: tras «=» viene un espacio y no
# hay límite de palabra), así que el archivo que define una constante nunca recibía la bonificación de definición.
_DEFINITION = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:(?:class|def|function|interface|type|const|let|var)\b|"
                         r"[A-Z][A-Z0-9_]*\s*(?::[^=]*)?=(?!=))")


_CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".ps1", ".psm1")


def _inside_string(line: str, pos: int) -> bool:
    """¿La posición cae dentro de un texto entre comillas de esta línea? (número impar de comillas antes). Una línea de
    continuación que empieza por comillas («    "texto…"») también cuenta."""
    before = line[:pos]
    return before.count('"') % 2 == 1 or before.count("'") % 2 == 1

# Nombre que define una línea («class X», «def f», «const y», «MAX = …»): la bonificación por definición solo cuenta
# si lo DEFINIDO es lo buscado (13/11/2026: «PROMPT = '… MAX_READ_CHARS'» no define MAX_READ_CHARS).
_DEFINED_NAME = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:(?:class|def|function|interface|type|const|let|var)\s+"
                           r"([\w$]+)|([A-Z][A-Z0-9_]*)\s*(?::[^=]*)?=(?!=))")


def _defined_name(line: str) -> str | None:
    m = _DEFINED_NAME.match(line)
    return _normal(m.group(1) or m.group(2)) if m else None


def _rank(terms: list[str], phrase: str, norm_lines: list[str], lines: list[str], matched: list[int],
          norm_path: str, weight: dict[str, float] | None = None) -> tuple[int, str]:
    """Relevancia de un archivo (12/11/2026). Antes cada término contaba igual y bastaba uno: «class» en miles de
    líneas hacía ganar a cualquier componente frente al archivo que define lo buscado. Ahora pesan, por orden:
    contener TODOS los términos, la frase exacta, la línea donde se DEFINE y, al final, la frecuencia (acotada).
    El fragmento muestra las mejores líneas, no las primeras.

    13/11/2026: cada término pesa según lo raro que es en el corpus (`weight`): «de», «la», «clase» o «eolfi» están
    en casi todo y no deben ganar a «AlexandriaLibrary». Un término que está en la RUTA también cuenta
    («MAX_READ_CHARS eolfi»: library.py está bajo eolfi/), pero es contexto: definirlo no es definir lo buscado."""
    w = weight or {}
    wt = {t: w.get(t, 1.0) for t in terms}
    # Palabra completa vale más que una parte («_normal» no es «_normalize»).
    words = {t: re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])") for t in terms}
    exact = re.compile(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])")
    present = {t for t in terms if t in norm_path or any(t in norm_lines[i] for i in matched)}
    whole = {t for t in terms if words[t].search(norm_path) or any(words[t].search(norm_lines[i]) for i in matched)}
    key = {t for t in terms if t not in norm_path} or set(terms)

    def defines(i: int) -> bool:
        name = _defined_name(lines[i])
        return bool(name) and name in key

    # 14/11/2026: en el código, una línea que es solo un texto entre comillas (p. ej. la continuación del enunciado de
    # un examen) no da la bonificación de frase exacta: «definición de la clase AlexandriaLibrary» devolvía el archivo
    # del examen, que contiene esa frase literal, antes que el que define la clase.
    code = norm_path.endswith(_CODE_SUFFIXES)

    def phrase_in(i: int) -> bool:
        hits = list(exact.finditer(norm_lines[i]))
        if not code:
            return bool(hits)
        return any(not _inside_string(norm_lines[i], m.start()) for m in hits)

    def line_score(i: int) -> float:
        line = norm_lines[i]
        full = [t for t in terms if words[t].search(line)]
        part = [t for t in terms if t in line and t not in full]
        return (sum(wt[t] for t in full) * 3 + sum(wt[t] for t in part)
                + (12 if len(terms) > 1 and phrase_in(i) else 0) + (10 if defines(i) else 0))

    scored = sorted(matched, key=lambda i: (-line_score(i), i))
    best = scored[0]
    score = (sum(wt[t] for t in present) * 20 + sum(wt[t] for t in whole) * 20 + (60 if any(defines(i) for i in matched) else 0)
             + (25 if len(terms) > 1 and any(phrase_in(i) for i in matched) else 0)
             + line_score(best) * 2 + min(len(matched), 10)
             + sum(5 * wt[t] for t in terms if t in norm_path))
    excerpt = "\n".join(f"{i + 1}: {lines[i][:300]}" for i in sorted(scored[:3]))
    return round(score), excerpt


class AlexandriaLibrary:
    """Consulta únicamente los archivos que el índice sitúa bajo corpus/codigo o corpus/texto."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def search(self, query: str, limit: int = 5) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("La consulta debe contener entre 1 y 300 caracteres.")
        limit = max(1, min(int(limit), 10))
        manifest = self.root / "manifests" / "corpus.index.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"No se encuentra el índice de Alejandría: {manifest}")
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        entries = data.get("entries", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            raise ValueError("El índice de Alejandría no tiene una lista entries válida.")
        corpus_roots = [(self.root / "corpus" / name).resolve() for name in ("codigo", "texto")]
        terms = [t for t in re.findall(r"[\w.-]+", _normal(query)) if len(t) > 1]
        if not terms:
            terms = [_normal(query)]
        phrase = " ".join(_normal(query).split())
        hits = []
        found: list[tuple[str, list[str], list[str], list[int]]] = []
        scanned = 0
        for entry in entries[:MAX_ENTRIES]:
            rel = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(rel, str):
                continue
            candidate = (self.root / rel).resolve()
            if not any(candidate == base or base in candidate.parents for base in corpus_roots):
                continue
            try:
                parts = {p.casefold() for p in candidate.relative_to(self.root).parts}
                if parts & EXCLUDED_PARTS or candidate.suffix.casefold() not in ALLOWED_SUFFIXES:
                    continue
                if not candidate.is_file() or candidate.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = candidate.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            scanned += 1
            lines = content.splitlines()
            norm_lines = [_normal(line) for line in lines]
            matched = [i for i, line in enumerate(norm_lines) if any(term in line for term in terms)]
            if not matched:
                continue
            rel_path = str(candidate.relative_to(self.root)).replace("\\", "/")
            found.append((rel_path, lines, norm_lines, matched))
        # Peso por rareza: un término que está en más del 10 % de los documentos leídos es común y pesa menos.
        df = {t: sum(any(t in nl[i] for i in m) for _r, _l, nl, m in found) for t in terms}
        common = max(2, 0.1 * scanned)
        weight = {t: (1.0 if df[t] <= common else 0.35) for t in terms}
        for rel_path, lines, norm_lines, matched in found:
            score, excerpt = _rank(terms, phrase, norm_lines, lines, matched, _normal(rel_path), weight)
            hits.append((score, rel_path, excerpt))
        hits.sort(key=lambda x: (-x[0], x[1].casefold()))
        return {"consulta": query, "biblioteca": self.root.name, "resultados": [
            {"ruta": path, "relevancia": score, "fragmento": excerpt}
            for score, path, excerpt in hits[:limit]
        ], "recortado": len(entries) > MAX_ENTRIES}

    def read(self, relative_path: str, offset: int = 0) -> dict:
        """Recupera un documento específico del corpus bajo demanda; nunca copia la biblioteca."""
        if not isinstance(relative_path, str) or not relative_path.strip() or len(relative_path) > 500:
            raise ValueError("Indica una ruta relativa devuelta por la búsqueda (máximo 500 caracteres).")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10_000_000:
            raise ValueError("El desplazamiento debe ser un entero entre 0 y 10.000.000.")
        manifest = self.root / "manifests" / "corpus.index.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"No se encuentra el índice de Alejandría: {manifest}")
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        entries = data.get("entries", []) if isinstance(data, dict) else []
        rel = relative_path.replace("\\", "/").lstrip("/")
        indexed = {e.get("path", "").replace("\\", "/").lstrip("/")
                   for e in entries[:MAX_ENTRIES] if isinstance(e, dict) and isinstance(e.get("path"), str)}
        if rel not in indexed:
            raise ValueError("La ruta no aparece en el índice del corpus; busca primero en Alejandría.")
        candidate = (self.root / rel).resolve()
        corpus_roots = [(self.root / "corpus" / name).resolve() for name in ("codigo", "texto")]
        if not any(candidate == base or base in candidate.parents for base in corpus_roots):
            raise ValueError("La ruta está fuera de corpus/codigo y corpus/texto.")
        parts = {p.casefold() for p in candidate.relative_to(self.root).parts}
        if parts & EXCLUDED_PARTS or candidate.suffix.casefold() not in ALLOWED_SUFFIXES:
            raise ValueError("Ese tipo de archivo o carpeta no está permitido para consulta.")
        if not candidate.is_file() or candidate.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("El documento no existe o supera el límite de lectura (512 KB).")
        content = candidate.read_text(encoding="utf-8", errors="replace")
        chunk = content[offset:offset + MAX_READ_CHARS]
        next_offset = offset + len(chunk)
        return {"ruta": rel, "desde": offset, "contenido": chunk, "recortado": next_offset < len(content),
                "siguiente_desde": next_offset if next_offset < len(content) else None,
                "caracteres_totales": len(content)}
