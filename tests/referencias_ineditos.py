"""Soluciones de REFERENCIA de los casos inéditos de la ronda (14/11/2026). Solo para comprobar que los casos son
correctos: nunca se enseñan a los motores ni se guardan como aportes."""

REFERENCIAS = {
    "restar_intervalos": '''
def restar_intervalos(base, cortes):
    cambios = {}
    for clase, intervalos in enumerate((base, cortes)):
        for a, b in intervalos:
            cambios.setdefault(a, [0, 0])[clase] += 1
            cambios.setdefault(b, [0, 0])[clase] -= 1
    cubiertos = tapados = 0
    inicio = None
    salida = []
    for punto, (delta_base, delta_cortes) in sorted(cambios.items()):
        cubiertos += delta_base
        tapados += delta_cortes
        if cubiertos and not tapados:
            if inicio is None:
                inicio = punto
        elif inicio is not None:
            salida.append((inicio, punto))
            inicio = None
    return salida
''',
    "repartir_centimos": '''
def repartir_centimos(total, pesos):
    suma = sum(pesos)
    cuotas = [divmod(total * peso, suma) for peso in pesos]
    asignados = [entero for entero, resto in cuotas]
    orden = sorted(range(len(pesos)), key=lambda i: (-cuotas[i][1], i))
    for i in orden[:total - sum(asignados)]:
        asignados[i] += 1
    return asignados
''',
    "romano": '''
def romano(n):
    if not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError("fuera de rango")
    tabla = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for valor, letras in tabla:
        while n >= valor:
            out.append(letras)
            n -= valor
    return "".join(out)
''',
    "rle_bytes": '''
def rle_bytes(data):
    out = bytearray()
    i = 0
    while i < len(data):
        j = i
        while j < len(data) and data[j] == data[i] and j - i < 255:
            j += 1
        out += bytes([j - i, data[i]])
        i = j
    return bytes(out)
''',
    "orden_topologico": '''
def orden_topologico(dependencias):
    import heapq
    nodos = set(dependencias)
    for antes in dependencias.values():
        nodos.update(antes)
    previos = {n: set(dependencias.get(n, [])) for n in nodos}
    listos = [n for n in nodos if not previos[n]]
    heapq.heapify(listos)
    orden = []
    while listos:
        n = heapq.heappop(listos)
        orden.append(n)
        for m in nodos:
            if n in previos[m]:
                previos[m].discard(n)
                if not previos[m]:
                    heapq.heappush(listos, m)
    if len(orden) != len(nodos):
        raise ValueError("ciclo")
    return orden
''',
    "duracion": '''
def duracion(texto):
    import re
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", texto or "")
    if not texto or not m or not any(m.groups()):
        raise ValueError("formato")
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s
''',
}
