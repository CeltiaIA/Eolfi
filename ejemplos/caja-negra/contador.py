"""Muestra sintética propia para las guías de Eolfi (dominio público dentro del proyecto).

Lee órdenes por la entrada estándar («suma N», «resta N», «total») y guarda el total en estado/total.txt.
Se usa como objetivo «sin fuentes»: las guías solo miran su comportamiento observable.
"""
import os
import sys

total = 0
for linea in sys.stdin.read().splitlines():
    partes = linea.split()
    if not partes:
        continue
    if partes[0] in ("suma", "resta") and len(partes) == 2 and partes[1].lstrip("-").isdigit():
        total += int(partes[1]) * (1 if partes[0] == "suma" else -1)
    elif partes[0] == "total":
        print(f"total={total}")
    else:
        print(f"orden desconocida: {linea}", file=sys.stderr)
        sys.exit(2)
os.makedirs("estado", exist_ok=True)
with open(os.path.join("estado", "total.txt"), "w", encoding="utf-8") as f:
    f.write(str(total))
