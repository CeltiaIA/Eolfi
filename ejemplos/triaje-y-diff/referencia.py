"""Muestra sintética propia (Eolfi): cuenta líneas, palabras y caracteres de la entrada estándar."""
import sys

texto = sys.stdin.read()
print(f"lineas={len(texto.splitlines())} palabras={len(texto.split())} caracteres={len(texto)}")
