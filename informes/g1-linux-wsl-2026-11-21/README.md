# G1 en Linux real: proveedor de sockets por PID (21/11/2026)

- Entorno: WSL2 Ubuntu, kernel 6.18.33.2-microsoft-standard-WSL2 x86_64, Python 3.14.4, venv `~/eolfi-venv` con
  psutil 7.2.2 (rueda manylinux SHA-256 076a2d2f…bc6f9) y pytest 9.2.0, instalado con permiso del titular.
- Código: el árbol de trabajo `D:\Eolfi` montado en `/mnt/d/Eolfi` (rama `luis/voz-piper`, sobre acfc23b).

## Resultados

| Prueba | Esperado | Observado |
|---|---|---|
| Proceso propio con TCP en escucha, cliente TCP y UDP en 127.0.0.1 (`instantanea-propia.json`) | Los tres sockets con sus puertos | Los tres, puertos idénticos; `estado: observado`, sin incógnitas |
| `python -m http.server` en 0.0.0.0 (`instantanea-otro-proceso.json`) | Escucha marcada como no loopback | `escucha_no_loopback: true`, `tcp_escuchas_no_loopback: 1` |
| Mismo PID tras terminar | No inventar conexiones | `estado: NO VERIFICADO`, incógnita «/proc/PID/ns/net» ausente, lista vacía |
| `tests/test_modelos_red.py` en Linux | Verde | 15 aprobadas (`salida.txt`) |

## Límites

- Solo procesos del mismo espacio de nombres de red; no se probó un PID de otro namespace (contenedor).
- WSL2 es Linux real con kernel de Microsoft, no una distribución en hierro propio.
- macOS sigue **NO VERIFICADO**.
