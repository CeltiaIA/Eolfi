import json
from pathlib import Path


class Almacen:
    """Guarda notas en un archivo JSON."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)

    def todas(self) -> list[str]:
        return json.loads(self.ruta.read_text(encoding="utf-8")) if self.ruta.is_file() else []

    def anadir(self, texto: str) -> int:
        if not texto.strip():
            raise ValueError("nota vacía")
        notas = self.todas() + [texto]
        self.ruta.write_text(json.dumps(notas, ensure_ascii=False), encoding="utf-8")
        return len(notas)
