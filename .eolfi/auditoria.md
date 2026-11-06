# Contexto de Eolfi para la auditoría

Lo leen el auditor y el verificador de `@eolfi /auditar`. Lo que esté cubierto aquí no es un fallo; si cambia el
código y una salvaguarda deja de existir, quítala de esta lista.

## Salvaguardas que ya existen

- **Generadores (títulos, recursos, rutas):** `build_spec` sanea el título con `safe_title` (sin comillas, llaves,
  `<`, `>`, `$` ni `\`), los recursos con `[a-z][a-z0-9_-]{1,30}` + `safe_resource` y las rutas con
  `[a-z][a-z0-9-]*`. `generate()` lo vuelve a comprobar (`_check_spec`) y `test_hostile_title_in_every_target`
  lo verifica en todos los objetivos. Interpolar `spec["title"]` o un recurso en código generado NO es inyección.
- **Analizadores de formatos** (ELF, PE, Mach-O, DEX, ARSC, AXML, .NET, WASM…): toda lectura pasa por `Reader`, que
  lanza `ParseError("lectura fuera de rango")` si se sale del archivo, y por `parse_budget` (tope de bytes y de
  tiempo); además van en un subproceso aislado y hay un fuzzer (`security/resilience.py`). Leer un offset sin
  comprobarlo a mano antes NO es un desbordamiento.
- **ZIP:** firmas v1 de APK y metadatos de IPA tienen tope de tamaño descomprimido.
- **Panel web:** construye el DOM con `el()` y `textContent`; no usa `innerHTML`, así que no hay XSS por ahí.
- **Servidor:** escucha en 127.0.0.1; las escrituras exigen la cabecera `X-Eolfi`; las rutas pasan por
  `_check_root`; los clientes de VS Code necesitan su token (`client_ok`); los códigos de vinculación caducan a los
  10 minutos y se anulan al 5.º fallo.
- **Red:** `sites/fetch.py` conecta a la IP ya validada (`_pinned_socket`), sin seguir redirecciones a direcciones
  privadas; `sites/repo.py` clona con git endurecido (sin hooks, sin credenciales, sin redirecciones).
- **Subprocesos:** `run_tree`, `check_cmd_safe` para lanzadores `.bat`/`.cmd`, `_safe_input` en `diff`, entorno
  sin secretos en el subproceso aislado y en REA.
- **Extensión de VS Code:** el workspace se comprueba con la ruta real (enlaces incluidos); los archivos de
  secretos están bloqueados (`isSecretPath`); escribir pide un diff en modo manual; `auto_approve` lo concede el
  usuario en VS Code; REA confirma por nombre lo que ejecuta algo; la lectura web fija la IP y tiene tope.
- **`isolated.py`** solo importa módulos `eolfi.providers.*`, y sus argumentos los pone el propio servidor.

## Decisiones de diseño aceptadas

- **Sin sandbox completo** (contenedor o VM) al verificar código generado o al hacer fuzzing: subproceso con límites
  de tiempo y memoria y entorno filtrado. Es una herramienta local para tu propio código.
- **Sin TLS propio:** el servidor es local (127.0.0.1); con `--allow-remote` se pone detrás de un proxy con TLS.
- **`corpus.py`** ejecuta con `-ExecutionPolicy Bypass` solo los scripts de tu propia configuración.
- **`llm.py` `base_url`:** el destino lo elige el usuario (variables de entorno o `--base-url`).
- **Terminal del agente:** lista de bloqueo + permiso por sesión + modo manual, no una lista cerrada de permitidos.
- **Pruebas** (`tests/`, `*/test/`, `e2e/`): variables de entorno y temporales de prueba son aceptables si se
  limpian al final; no son código de producción.
