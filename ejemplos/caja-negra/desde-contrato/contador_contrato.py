"""Implementación escrita SOLO a partir del contrato (`eolfi spec contract`) del guion guion-contenidos.json.

Lo que dice el contrato y se aplica aquí:
- «suma N» y «resta N» acumulan; «total» escribe «total=<valor>» en la salida estándar (REQ «sumar», «restar»);
- el valor de estado/total.txt al empezar no cuenta: tras «suma 10, resta 4» con el archivo a 5 queda 6;
- al terminar se guarda el total, sin salto de línea, en estado/total.txt;
- una orden no reconocida escribe «orden desconocida: <línea>» en la salida de error, termina con código 2 y no
  toca el archivo (REQ «invalida»: sin efectos en archivos).
Lo que el contrato marca como desconocido (otras órdenes, números no enteros, líneas vacías) es una decisión de
esta implementación, no comportamiento comprobado.
"""
import sys
from pathlib import Path


def ejecutar(lineas):
    acumulado = 0
    for linea in lineas:
        palabras = linea.split()
        if not palabras:
            continue
        orden, resto = palabras[0], palabras[1:]
        if orden == "total" and not resto:
            sys.stdout.write(f"total={acumulado}\n")
        elif orden in ("suma", "resta") and len(resto) == 1 and resto[0].lstrip("-").isdigit():
            acumulado = acumulado + int(resto[0]) if orden == "suma" else acumulado - int(resto[0])
        else:
            sys.stderr.write(f"orden desconocida: {linea}\n")
            return 2
    destino = Path("estado") / "total.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(str(acumulado), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(ejecutar(sys.stdin.read().splitlines()))
