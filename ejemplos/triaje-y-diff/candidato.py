"""Reimplementación de referencia.py con un fallo deliberado: cuenta las líneas por saltos de línea."""
import sys

texto = sys.stdin.read()
print(f"lineas={texto.count(chr(10))} palabras={len(texto.split())} caracteres={len(texto)}")
