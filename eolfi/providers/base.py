"""Interfaz común de los proveedores (adaptadores de herramientas)."""
from __future__ import annotations

import abc
from typing import Any


class Provider(abc.ABC):
    name: str = "base"
    version: str = "0.0.0"

    @abc.abstractmethod
    def available(self) -> bool:
        """¿Puede ejecutarse en este entorno? (herramienta instalada, etc.)"""

    @abc.abstractmethod
    def run(self, target: str) -> list[dict[str, Any]]:
        """Devuelve una lista de hallazgos crudos: cada uno es un dict con
        al menos operation, result, authority, confidence, limitations."""
