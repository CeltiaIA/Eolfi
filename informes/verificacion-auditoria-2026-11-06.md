# Verificación de la auditoría archivo por archivo (2026-11-06)

La auditoría `auditoria-archivos-Eolfi-2026-11-06.md` (129 archivos) marcó **69 mejoras de prioridad alta**. Las
revisaron modelos de IA, así que cada una se comprobó contra el código real antes de tocar nada.

## Reales: corregidas, con prueba

| Problema | Archivo | Arreglo |
|---|---|---|
| `.gitignore.extra` se borraba **sin fusionarse**: los proyectos .NET quedaban sin ignorar `bin/` y `obj/`, y los de CLI sin `build/` | `generador/generators.py` | Se fusiona en `.gitignore`, sin repetir líneas |
| La repetición de determinismo de `diff` no usaba `_safe_input` (un `a&calc.txt` con un lanzador `.bat` ejecutaría `calc`) | `flows/diff_flow.py` | `_safe_input` también ahí; entradas de más de 256 MB se omiten |
| Códigos de vinculación tanteables en paralelo (6 dígitos) | `server.py` | Al 5.º fallo se anulan todos los códigos pendientes |
| El subproceso aislado heredaba tokens y claves | `flows/triage_flow.py` | Entorno sin variables secretas |
| Un dominio con DNS mixto (pública + privada) activaba el acceso a direcciones privadas | `sites/fetch.py` | Solo con `localhost` o una IP privada escrita a mano, y solo para ese host |
| Lectura web del agente: el DNS se resolvía otra vez al conectar (DNS rebinding) y la página se leía entera | `vscode-bridge/agent-tools.js` | Conexión a la IP validada y lectura con tope |
| Un enlace simbólico o unión dentro del workspace permitía leer y escribir fuera | `vscode-bridge/workspace.js` | Contención con la ruta real |
| Al acabar bien una orden, el temporizador mandaba **Ctrl+C a la terminal «Eolfi»** a los 120 s | `vscode-bridge/extension.js` | Temporizador y suscripciones se limpian al terminar |
| REA recibía todas las variables de entorno (tokens incluidos) | `vscode-bridge/rea.js` | Entorno sin secretos |
| Una herramienta de REA de ejecución que se declarase «solo lectura» no pedía confirmación | `vscode-bridge/rea.js` | Lo que por su nombre ejecuta algo se confirma siempre |
| El estado reanudado de la auditoría no se validaba | `vscode-bridge/audit.js` | Si es ajeno o tiene archivos fuera de la carpeta, se empieza de cero |
| Bomba ZIP: firma v1 de APK, `Info.plist` y perfil de IPA se descomprimían sin tope | `providers/apksig.py`, `providers/apple.py` | Tope de tamaño descomprimido |
| `assist`: la contención de la ruta no era lo primero | `generador/assist.py` | Se comprueba antes que nada |
| Servidor estático generado: prefijo sin separador | `generador/generators.py` | `root + sep` |
| Aserción siempre verdadera (`or True`) | `tests/test_fase_a.py` | Comprueba el commit de verdad |
| Ruta interpolada en código Python | `tests/e2e/panel.test.mjs` | Va como argumento |
| La e2e podía revocar un cliente ajeno creado a la vez | `vscode-bridge/e2e/run.js` | Solo el cliente nuevo de esa prueba |

Pruebas: `tests/test_verificacion_auditoria.py` y las nuevas de `vscode-bridge/test/`.

## Falsos positivos (ya estaba bien)

- **Escapar título y recursos en los generadores** (backend, CLI, .NET, móvil, Tauri, Django, Vue, HTML): `build_spec`
  sanea el título (`safe_title`: sin comillas, llaves, `<`, `>`, `$`, `\`) y los recursos y rutas
  (`[a-z][a-z0-9_-]*` y sin palabras reservadas), y la prueba `test_hostile_title_in_every_target` lo verifica en
  todos los objetivos. Se añadió `_check_spec` como defensa en profundidad.
- **Analizadores de formatos** (ARSC, AXML, .NET, Mach-O, PE, WASM, DEX): el `Reader` comprueba cada lectura contra
  los límites («lectura fuera de rango») y hay un presupuesto de lectura (`parse_budget`) y un fuzzer.
- **XSS en el panel**: el panel no usa `innerHTML`. `stack.py` no genera HTML.
- `isolated.py` ya solo admite módulos `eolfi.providers.*`; `external.py` ya pasa `check_cmd_safe` a las rutas de
  los lanzadores `.bat`; `vscode_web` comprueba la carpeta en el servidor; el protocolo `app://` de Electron ya
  comprueba `RENDERER + sep`; `eolfi-client` solo recibe direcciones de este equipo (`baseUrl`).
- `core.js` y `auto_approve`: aunque Eolfi pida el modo automático, VS Code se lo pregunta al usuario.
- `.env versionado`: no hay repositorio git y `.gitignore` excluye `.env`.

## Diseño (no se cambia; documentado)

- **Aislamiento real** (contenedor o VM) al verificar código generado o al hacer fuzzing: hoy hay subproceso, límites
  de tiempo y memoria (POSIX) y entorno filtrado. Un sandbox completo es un proyecto aparte.
- **TLS en modo remoto**: el servidor está pensado para 127.0.0.1; con `--allow-remote`, ponerlo detrás de un proxy
  con TLS.
- `corpus.py` usa `-ExecutionPolicy Bypass` solo para tus propios scripts de configuración.
- `llm.py` y `base_url`: el destino lo eliges tú (variables de entorno o `--base-url`).
- La terminal del agente usa lista de bloqueo + confirmación (+ modo manual); una lista de permitidos cerrada
  limitaría demasiado al agente.
