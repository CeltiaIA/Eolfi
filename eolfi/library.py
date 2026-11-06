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
        hits = []
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
            lines = content.splitlines()
            norm_lines = [_normal(line) for line in lines]
            matched = [i for i, line in enumerate(norm_lines) if any(term in line for term in terms)]
            if not matched:
                continue
            score = sum(sum(2 if term in norm_lines[i] else 0 for term in terms) for i in matched)
            excerpt = "\n".join(f"{i + 1}: {lines[i][:300]}" for i in matched[:3])
            hits.append((score, str(candidate.relative_to(self.root)).replace("\\", "/"), excerpt))
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
