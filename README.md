# Eolfi

> **Software propietario y privado.** © 2026 Luis Manuel Cousido Hermida. Todos los
> derechos reservados; no se concede ninguna licencia de uso, copia ni distribución. Ver [LICENSE](LICENSE).

Sistema **local** de agentes para ingeniería inversa. Orquesta herramientas
de análisis reales y guarda cada hallazgo en un **modelo de evidencias** que
separa lo observado de lo inferido, para que el agente nunca afirme algo que
no ha comprobado. Inspirado en la metodología de análisis asistido por agentes;
es una implementación propia.

> **Uso responsable.** Úsalo solo sobre software **propio**, de código abierto,
> retos de aprendizaje (CTF/crackmes) o software que tengas **derecho** a
> analizar. No sirve para evadir licencias ni clonar productos de terceros.

## Qué incluye

- **Modelo de evidencias** (`eolfi/core`): cada hallazgo es una `Evidence`
  inmutable con `evidence_id` (sha256 de su proyección semántica), autoridad,
  confianza y límites. Los duplicados se detectan solos y, si dos evidencias
  con el mismo `(subject, operation, params)` discrepan, se abre una
  **incógnita** que cita ambas (confianza cruzada). Almacén SQLite con
  export/import de paquetes **validados** (columnas en lista blanca, huella
  recalculada, importación atómica).
- **Proveedores** (`eolfi/providers`):
  - `eolfi.triage`: hash, formato por magia (distingue Mach-O fat de clase
    Java), señales de PyInstaller.
  - `eolfi.binfmt`: parser **PE y ELF** con stdlib: cabeceras, secciones con
    entropía, importaciones/exportaciones, `DT_NEEDED`, símbolos dinámicos,
    mitigaciones (ASLR/DEP/CFG/Authenticode; NX/PIE/RELRO/canary/FORTIFY) y
    señales de empaquetado. Lector con límites: una entrada malformada da un
    `ParseError`, nunca un crash.
  - `eolfi.strings`: cadenas ASCII.
  - **Formatos y firmas** (todo con la stdlib; se LEEN las firmas, no se valida la cadena de confianza):
    - PE: firma **Authenticode** (firmante, emisor, sello de tiempo y comprobación de que el resumen firmado
      coincide con el archivo), **imphash**, cabecera **Rich**, callbacks **TLS** y **VERSIONINFO**.
    - **.NET**: ensamblado y versión, AssemblyRef, P/Invoke, recursos, framework de destino, ReadyToRun,
      paquetes «single-file» y pistas de ofuscadores (ConfuserEx, Dotfuscator, SmartAssembly…).
    - **Java**: `.class` (versión, clase, interfaces, clases y cadenas referenciadas) y **JAR/WAR** (MANIFEST,
      Spring Boot, bibliotecas incrustadas, versiones de bytecode).
    - **WebAssembly**: secciones, importaciones/exportaciones, `name`, `producers` y cadena de herramientas
      (Emscripten, Rust/wasm-bindgen, Go, AssemblyScript, .NET).
    - **APK**: firma v1/v2/v3/v3.1 (y v4 si hay `.idsig`) con la huella SHA-256 del certificado; bibliotecas
      nativas `lib/<abi>/*.so` (JNI, alineación de 16 KB, build-id); DEX con APIs sensibles, URLs y SHA-1.
    - **IPA (iOS)**: Info.plist (permisos de privacidad, esquemas URL, ATS), firma de código (identificador,
      Team ID, entitlements, certificados), `embedded.mobileprovision` y cifrado FairPlay.
  - Externos opcionales: **capa** (reglas, ATT&CK, MBC), **rizin/radare2**
    (`ij`, `aaa;aflj`) y **Ghidra headless** (script Java propio, Ghidra
    10–12). Si la herramienta no está, se registra una incógnita y se sigue.
- **Flujos** (`eolfi/flows`): triaje en un paso (un proveedor que falla no lo
  tumba) y **verificación diferencial** referencia vs reimplementación.
- **Exportación SARIF 2.1.0** para VS Code / GitHub.
- **Servidor de desarrollo** (`eolfi/server.py` + `eolfi/web`): API JSON y
  panel web para subir binarios, ver evidencias y resolver incógnitas.
- **Banco de resiliencia** (`eolfi/security`): fuzzing de los proveedores
  locales en subprocesos aislados, y escaneo de inyección de prompts (ASCII y
  UTF-16) — el texto hostil del binario se trata como dato, nunca como orden.

## Requisitos

- Python 3.10+ (el núcleo no necesita dependencias externas).
- Opcional: capa, rizin/radare2, Ghidra (define `GHIDRA_INSTALL_DIR`).
  `python -m eolfi doctor` dice cuáles detecta.

## Uso rápido

```bash
# desde la carpeta del proyecto
export PYTHONPATH="$PWD"            # o: pip install -e .

python -m eolfi doctor                         # proveedores disponibles
python -m eolfi triage ./miprograma            # stdlib + capa/rizin si están
python -m eolfi triage --local ./miprograma    # solo stdlib (rápido)
python -m eolfi triage --deep ./miprograma     # + Ghidra headless (minutos)
python -m eolfi evidence --operation pe_security
python -m eolfi incognitas --status open
python -m eolfi resolve <incognita_id>
python -m eolfi export informe.sarif --artifact ./miprograma
python -m eolfi export paquete.json
python -m eolfi import paquete.json

# banco de resiliencia (ataca TU sistema sin tumbarlo)
python -m eolfi resilience fuzz ./semilla --iters 200
python -m eolfi resilience inject ./miprograma
```

La base de evidencias por defecto es `~/.eolfi/eolfi.db` (o `EOLFI_HOME`); cámbiala con `--db` o `EOLFI_DB`.
Si en la carpeta actual hay una `eolfi.db` antigua y aún no existe la de `~/.eolfi`, la primera ejecución la
**copia** allí (con la API de copia de SQLite) y lo avisa; la original se conserva sin cambios. Contiene los
tokens de los clientes del panel: no la copies junto con el código.
Con `EOLFI_DEBUG=1` los errores muestran el traceback completo.

## Casos de análisis

Un caso agrupa artefactos (con hash, tamaño, formato, procedencia, herramientas, versiones y entorno), las ejecuciones
de cada flujo con su estado (`done`, `partial`, `error`, `cancelled`), evidencias, incógnitas y conclusiones
(`observed`, `derived` o `hypothesis`; una hipótesis nunca se exporta ni importa como hecho).

```bash
python -m eolfi case create "Calculadora v2" --description "muestra propia"
python -m eolfi triage muestra.exe --local --case <case_id> --provenance "compilada por mí"
python -m eolfi case report <case_id> --out caso.html
python -m eolfi case export <case_id> caso.json
```

`--case` también funciona con `web`, `repo`, `diff`, `compare` y `create`. El panel (pestaña «Casos», con caso activo)
y el agente de VS Code (`eolfi_casos`, `eolfi_caso_analizar`) usan el mismo estado a través de `/api/cases`.

## Servidor de desarrollo

```bash
python -m eolfi up                    # todo junto: Eolas (D:\celtiaia), puente de chats web y panel
python -m eolfi serve --reload        # solo el panel: http://127.0.0.1:8777
```

`eolfi up` reutiliza lo que ya esté en marcha; si no, arranca Eolas con `launch-eolas.ps1 -Detach -NoBrowser`
del repositorio CeltIA (`--celtiaia` o `CELTIAIA_HOME`, por defecto `D:\celtiaia`) y el puente, y abre el panel
con **Eolas como IA por defecto**; los proveedores web se eligen después en «Proveedores». Ctrl+C para el panel
y el puente; Eolas queda activo (servicio compartido con CeltIA): `D:\celtiaia\launch-eolas.ps1 -Stop`.
`--no-bridge`, `--no-eolas`, `--no-open`, `--reload`. Registros en `~/.eolfi/logs/`.

En el panel: pestañas Binario / Web / Repositorio para analizar, casillas en
"Objetivos" para comparar dos o usarlos como fuentes, y la tarjeta
**Crear proyecto nuevo**.

- Panel web: arrastra un binario (se guarda en `samples/<sha256>.bin`) o
  escribe una ruta local; elige modo local / por defecto / profundo.
- `--reload` reinicia el servidor al cambiar cualquier archivo de `eolfi/`.
- **Pestaña Trabajos**: la cola con su estado, cancelar y repetir; el historial se guarda en la base de
  evidencias (sobrevive a los reinicios). `POST /api/jobs/<id>/repeat` repite uno.
- **Informes**: cada objetivo tiene enlaces «Informe: HTML · Markdown» (`GET /api/report?subject=&format=html|md`).
  En la CLI: `python -m eolfi report <objetivo> --format html --out informe.html`; con `--fail-on high`
  sale con código 1 si hay incógnitas abiertas de esa gravedad o mayor (útil en CI).
- **Atajos**: `Alt+1..4` (Análisis, Chats, Proveedores, Trabajos), `/` busca, `?` muestra la ayuda. Cada vista
  y cada objetivo tienen su URL (`#trabajos`, `#objetivo/<sha256>`…): el botón Atrás funciona.
- **Análisis aislado**: el servidor ejecuta los proveedores locales en un subproceso con plazo (y límite de
  memoria en Linux/macOS): un archivo hostil no puede tumbarlo. `EOLFI_ISOLATE=0` lo desactiva. Además todos
  los parsers comparten un presupuesto de lectura y tiempo por análisis.
- **Trabajos en segundo plano** (análisis largos, crear y verificar): `POST /api/jobs`
  `{"kind": "create"|"web"|"repo"|"triage", "body": {…}}` → `{"job_id"}`;
  `GET /api/jobs?id=…&since=N` (progreso, resultado o error; `needs_confirm` si hace falta
  confirmar una escritura sobre el origen); `GET /api/jobs` lista los últimos 50;
  `DELETE /api/jobs?id=…` cancela. Como mucho 3 a la vez; el resto espera «en cola».
- **API**:
  - Lectura: `GET /api/health`, `/api/providers` (caché de 30 s; `?refresh=1` la renueva),
    `/api/subjects`, `/api/evidence?subject=&operation=&q=&limit=&offset=` (paginada: `total` y
    `next_offset`), `/api/incognitas?subject=&status=`, `/api/fs/list?path=` (carpetas para el selector),
    `/api/export.sarif|export.json|export.stix`.
  - Análisis: `POST /api/triage` (`{"path", "mode", "providers"}`; una carpeta se analiza como
    repositorio), `POST /api/web` (`{"source", "max_assets", "cross_origin", "ignore_robots"}`),
    `POST /api/repo` (`{"source"}`), `POST /api/compare` (`{"a", "b"}`).
  - Subida: `POST /api/upload?store=1&name=` (cuerpo binario, a disco por bloques; devuelve
    `{"upload": sha256}`) y después el trabajo `triage` con `{"upload", "name", "mode"}`.
  - Crear: `POST /api/create` (`{"sources", "name", "target", "out", "force", "db", "auth",
    "reanalyze", "ai_brief", "ai_provider", "ai_model", "ai_base_url"}`).
    La instalación, compilación y pruebas son obligatorias; el antiguo campo `verify` se ignora.
  - Incógnitas: `POST /api/incognitas/<id>/resolve`.
  - Puente: `GET /api/bridge/status|events|screen`, `POST /api/bridge/chat|input` (el token del puente
    se queda en el servidor; el navegador nunca lo ve).
- **Carpetas permitidas**: `serve --root CARPETA` (repetible) o `EOLFI_ROOTS` (separadas por `;` en
  Windows, `:` en Linux/macOS) limitan las rutas locales que acepta la API y el selector de carpetas.
- **Modo remoto**: `--allow-remote` exige un token de arranque. La URL con `?token=` se cambia por una
  cookie `HttpOnly` y una redirección (el token no queda en el historial ni en el registro).
- **Límites**: subidas de 256 MB, cuerpos JSON de 4 MB y evidencias paginadas de hasta 5000 por página.
- Seguridad: solo `127.0.0.1` salvo `--allow-remote`; cabecera `Host` comprobada; los POST y DELETE
  exigen `X-Eolfi: 1` (frena CSRF); los GET de la API desde otra web se rechazan y todo lleva
  `Cross-Origin-Resource-Policy: same-origin`; CSP estricta y todo el texto del binario se pinta como
  texto, no como HTML.
- `.claude/launch.json` ya lo define para la vista previa de Claude Code.

## Aprender de webs y repositorios

```bash
python -m eolfi web https://ejemplo.com/            # o un .html / carpeta de sitio estático
python -m eolfi web https://ejemplo.com/ --save estudio/   # + copia de estudio de HTML/CSS/JS
python -m eolfi repo D:/proyectos/mi-app            # carpeta local
python -m eolfi repo https://github.com/usuario/repo   # clon superficial y seguro
```

- **Web**: estructura (landmarks, encabezados, formularios, esquema del DOM),
  assets, CSS (paleta, fuentes, breakpoints, variables, Grid/Flex), JS
  (bundler, APIs del navegador, endpoints), **source maps** (solo las rutas
  del proyecto original y los paquetes npm, nunca su código), cabeceras de
  seguridad, accesibilidad, SEO/sitemap y pila tecnológica, más un *plano*
  para construir algo parecido (comando de arranque, esqueleto, tokens,
  componentes repetidos, notas de aprendizaje).
- **Repositorio**: lenguajes y líneas, manifiestos y dependencias
  (npm, PyPI, Cargo, Go, Maven/Gradle, Composer, Gem, NuGet, pub), separando
  dependencias de ejecución y de desarrollo; estructura y puntos de entrada,
  pruebas, CI, Docker, licencia, variables de entorno (solo nombres) e higiene.
- Respeta robots.txt, solo descarga del mismo origen por defecto y bloquea
  que una página pública dirija peticiones a tu red local (anti-SSRF). Del
  clon: sin hooks, sin submódulos, sin enlaces simbólicos, sin credenciales;
  **nunca se ejecuta nada del repositorio**.

## Crear un proyecto nuevo a partir de una o varias fuentes

```bash
python -m eolfi create \
    --from https://una-web.com/ \
    --from https://github.com/usuario/repo \
    --from D:/otra/carpeta \
    --name "Mi proyecto" --out D:/proyectos/mi-proyecto
```

1. Analiza cada fuente (o reutiliza un objetivo ya analizado: `--from <sha|url:…>`).
2. Fusiona todo en una especificación (`eolfi.spec.json`): pila votada,
   páginas, secciones (Hero, Precios, Opiniones, FAQ, Contacto…), paleta,
   fuente y breakpoints, recursos de API detectados y convenciones (TS, CI, Docker).
3. Genera **código nuevo** desde plantillas propias, en `--target`
   `react` | `vue` | `svelte` | `next` | `static` | `fastapi` | `express` | `django` | `expo` |
   `desktop` | `tauri` | `dotnet` | `cli` (o `auto`, que elige según el **tipo de app** analizada:
   web, backend, móvil, escritorio o línea de comandos):
   - React / Vue / Svelte 5: Vite + TypeScript, enrutador propio, tema
     claro/oscuro, formulario, cliente de API y pruebas con Vitest.
   - Next.js (App Router): páginas, componentes de cliente donde hace falta,
     rutas de API CRUD y una prueba de extremo a extremo contra `next start`.
   - FastAPI / Express: API CRUD validada por recurso + frontend estático
     conectado a ella + pruebas. Con `--db sqlite`, persistencia real en SQLite
     (solo librería estándar: `sqlite3` / `node:sqlite`); con `--auth`, registro,
     inicio de sesión (PBKDF2-SHA256, tokens con caducidad) y escrituras protegidas.
   - Django: modelos y migración inicial, admin, API JSON, plantillas con
     las secciones y pruebas con `manage.py test`.
   - Estático: HTML/CSS/JS sin dependencias + servidor y pruebas con `node --test`.
   - **Expo (móvil)**: app React Native + TypeScript para Android, iOS y web, con
     pestañas, secciones, formulario validado, modo oscuro y datos del backend
     (`EXPO_PUBLIC_API_URL`). Solo se fija `expo`; `npm run setup` (`expo install`)
     alinea React y React Native con el SDK. Pruébala con Expo Go (`npx expo start`).
   - **Escritorio (Windows, macOS y Linux)**: app Electron endurecida (aislamiento,
     sandbox, CSP, sin Node en la página, permisos denegados, una sola instancia)
     con la interfaz generada desde las mismas plantillas. `npm start` la abre,
     `npm run smoke` la arranca de verdad y comprueba que carga, y `npm run dist`
     crea el instalador del sistema: `.exe` (NSIS) en Windows, `.dmg` en macOS y
     AppImage + `.deb` en Linux. El CI generado compila los tres.
   - **Escritorio nativo ligero con Tauri 2 (Rust)**: la misma interfaz en el WebView del
     sistema (unos MB en lugar de ~100), CSP, permisos mínimos y sin API global en la
     página. `npm run build` crea MSI/NSIS, .dmg o AppImage/.deb/.rpm. Requiere Rust.
   - **Escritorio nativo .NET (C# + Avalonia)**: interfaz nativa (no web) con pestañas y
     tema Fluent claro/oscuro, pruebas xUnit y `dotnet publish -r win-x64|osx-arm64|linux-x64`
     para un ejecutable autocontenido. Requiere .NET SDK 10.
   - **Línea de comandos (Python)**: comando instalable (`pip install .`), un subcomando por
     recurso (list/add/show/remove) con `--json`, datos en la carpeta de usuario de cada
     sistema y ejecutable único por sistema con PyInstaller en el CI.

   Con `auto`, el tipo de app sale de las fuentes: un `.exe` de consola o pilas como
   Click, Typer, clap, Cobra o Commander → **línea de comandos**; WPF, Windows Forms o
   Avalonia → **.NET**; Tauri, Qt o GTK → **Tauri**; un `.exe`/PE gráfico, ELF, Mach-O
   o JAR, o Electron → **escritorio (Electron)**;
   un APK/AAB, IPA, React Native, Flutter o .NET MAUI → **móvil** (Android e
   iOS); el resto, web o backend. La especificación guarda `platforms` (dónde
   funcionará lo generado) y `source_platforms` (sistemas de las apps analizadas).
4. La verificación es **obligatoria**: instala las dependencias en su **última versión**, las
   fija en `package.json`/`requirements.txt`, compila y pasa las pruebas
   (Python usa un `.venv` propio, nunca el global).

Ninguna línea de código ni texto procede de las fuentes: solo su estructura,
pila y tokens de diseño. Revisa la licencia de cada fuente antes de inspirarte
en ella.

### Modo asistido por IA (lógica de negocio)

```bash
pip install "eolfi[ai]"          # SDK oficial de Anthropic; credenciales: ANTHROPIC_API_KEY o `ant auth login`
python -m eolfi create --from https://una-web.com/ --out D:/p/tienda \
    --ai "Catálogo de bicis con filtro por precio y carrito con total"
python -m eolfi assist D:/p/tienda --brief "Añade búsqueda en el catálogo"
```

Claude (Opus 5.5, salida JSON estructurada) recibe la especificación, la
petición y los archivos editables, y devuelve archivos completos. Eolfi:

- solo acepta rutas de código de la app y pruebas (nunca `package.json`,
  configuración de build, CI ni nada fuera del proyecto);
- compila y prueba; si falla, devuelve el error a Claude (hasta 2 reparaciones);
- si no consigue un estado verde, **restaura todos los archivos**;
- registra el resultado (resumen, archivos, rondas, tokens) como evidencia.

Proveedores (`--provider`, también en el panel):

| Proveedor | Qué usa | Requisito |
|---|---|---|
| `claude` (defecto) | Claude Opus 5.5, salida estructurada | `pip install "eolfi[ai]"` + `ANTHROPIC_API_KEY` o `ant auth login` |
| `eolas` | Eolas V1 local (CeltIA), API Ollama en `127.0.0.1:11435` | arrancar Eolas (`launch-eolas.ps1`); `--base-url`/`--model` para cambiarlo |
| `deepseek` | API oficial de DeepSeek | `DEEPSEEK_API_KEY` |
| `gemini` | API oficial de Gemini (endpoint compatible OpenAI) | `GEMINI_API_KEY` |
| `openai` | cualquier servidor compatible OpenAI | `--base-url`, `--model`, `OPENAI_API_KEY` |

| `deepseek-web` · `gemini-web` · `meta-web` | las webs de chat con tu sesión, vía el puente Electron | `python -m eolfi bridge` e iniciar sesión en sus ventanas |

`python -m eolfi doctor` indica cuáles están disponibles. Las claves se leen de variables de entorno o
del archivo **`.env`** de la carpeta del proyecto (copia `.env.example`; también vale `~/.eolfi/.env` o
`EOLFI_ENV_FILE`). `.env` está en `.gitignore`, no se sube nunca a git, no pisa variables ya definidas y
Eolfi no muestra sus valores.

### Modelo local: llama.cpp con Gemma 4 (con razonamiento)

```bash
python -m eolfi llama            # estado
python -m eolfi llama start      # arranca llama-server (también se arranca solo al usarlo)
python -m eolfi llama stop
python -m eolfi llama config     # abre ~/.eolfi/llamacpp.json
python -m eolfi assist D:/mi-proyecto --provider gemma --brief "Añade validación"
```

Una sola configuración para todo Eolfi, `~/.eolfi/llamacpp.json`: `server` (llama-server.exe), `model` (por
defecto **Gemma 4 E4B** Q4_K_M, que cabe entera en una GPU de 8 GB; la 12B Q5_K_M también vale con reparto
GPU/CPU), `port` (8090), `ctx`, `gpu_layers`, `temperature`, `top_p`, `max_tokens`, `system` (instrucciones
propias), `reasoning` (razonamiento del modelo), `review_reasoning` (en la auditoría archivo por archivo),
`show_reasoning` (verlo en el chat) y `extra_args`. llama-server se arranca solo en 127.0.0.1 con `--jinja` y
`--reasoning-format deepseek` (razonamiento separado de la respuesta).

En VS Code: `@eolfi /modelo local` hace de Gemma 4 el modelo principal del agente (con sus herramientas, y el
razonamiento en un bloque «💭 Razonamiento»); `@eolfi /modelo copilot` vuelve a Copilot (con Gemma de respaldo).
«Eolfi: configurar el modelo local» abre el mismo JSON, y el ajuste `eolfi.agent.instructions` añade
instrucciones propias para cualquier modelo. En «Crear», «IA: Gemma 4 local (llama.cpp)».

### Herramientas de análisis instaladas

En `~/.eolfi/tools` (Eolfi también busca ahí, además del PATH) y en el PATH de usuario: **capa** 10.0.0
(`tools/capa`), **rizin** 0.9.1 (`tools/rizin/…/bin`) y el JAR de **jadx-headless-mcp** 0.7.1 para REA
(variable de usuario `REA_JADX_MCP_JAR`; la extensión se lo pasa a REA si lo encuentra). **bandit** con pip.
Ghidra 12.1.4 y Java 21 ya estaban. Otra carpeta: `EOLFI_TOOLS_DIR`.

### Repositorios privados de GitHub

Pon tu token en `GITHUB_TOKEN` del `.env` (token classic con permiso `repo`, o fine-grained con «Contents:
read»). Eolfi lo usa solo al clonar `https://github.com/…`: va en el entorno del proceso de git (no en la
línea de comandos ni en el `.git/config` del clon), sin redirecciones y nunca aparece en los errores.

### IA y herramientas de VS Code (`copilot-vscode`)

```bash
python -m eolfi vscode D:/mi-proyecto       # abre VS Code con la extensión puente (no instala nada)
python -m eolfi vscode --install            # o instálala (VSIX) en tu VS Code: sale en «Extensiones»
python -m eolfi assist D:/mi-proyecto --provider copilot-vscode --brief "Añade validación"
python -m eolfi vscode-do find --text "def main"
python -m eolfi vscode-do open --path src/app.py --line 40
```

- La extensión `eolfi/vscode-bridge` usa la **Language Model API** oficial de VS Code: los modelos de IA
  de tu suscripción. La primera petición hace que VS Code te pida permiso; necesitas la sesión del asistente de
  IA iniciada en VS Code. Escucha solo en `127.0.0.1` con un token nuevo cada vez (`~/.eolfi/vscode-bridge.json`).
- **Eolfi usa VS Code**: listar, leer y buscar en las carpetas abiertas, abrir archivos (en una línea) y carpetas,
  escribir archivos y ejecutar comandos. Límites aplicados en VS Code:
  - leer, listar y buscar solo dentro del workspace;
  - cada escritura pide confirmación (se puede deshacer con Ctrl+Z), salvo `eolfi.autoApproveEdits`;
  - abrir otra carpeta pide confirmación;
  - comandos solo los de `eolfi.allowedCommands`; herramientas de VS Code (terminal, tareas, pruebas…) solo las
    de `eolfi.allowedTools`.
- El modelo recibe por defecto las herramientas de solo lectura del workspace para mirar el proyecto
  (`EOLFI_COPILOT_WORKSPACE=read`; `write` también escribir, con confirmación; `off` ninguna). Modelo con
  `EOLFI_COPILOT_MODEL` y herramientas de VS Code con `EOLFI_COPILOT_TOOLS`.
- Modelo por defecto: el de mayor contexto que acepte peticiones de extensiones (algunos, como «Auto» con
  herramientas o los reservados a VS Code, las rechazan: el puente prueba el siguiente y recuerda el bueno).
- **Modo automático** (`EOLFI_COPILOT_WORKSPACE=auto`): VS Code pide permiso una sola vez («Permitir en esta
  sesión» o «Permitir siempre») y después escribe sin preguntar. Cada escritura queda apuntada en un diario: si
  el chat falla o el resultado no sale en verde, Eolfi deshace todo (restaura los originales y borra los archivos
  nuevos).
- **Iniciar sesión (obligatorio)**: la extensión no hace nada hasta vincularla. En el panel, Proveedores →
  «Vincular VS Code» da un código de 6 cifras (10 minutos, un solo uso); en VS Code, «Eolfi: iniciar sesión» y
  escribe el código (el cuadro lo oculta). Sin ver ningún código: botón «Vincular este VS Code» del panel o
  `python -m eolfi vscode --login` (el código viaja solo dentro de un enlace `vscode://`). El token queda en el almacén de secretos de VS Code; desde el panel se ve cada VS Code
  vinculado y se puede revocar («Eolfi: cerrar sesión» lo quita en VS Code).
- **Ingeniería inversa desde VS Code** (con el servidor `python -m eolfi serve` arrancado): clic derecho en el
  explorador o en la pestaña → «Eolfi: analizar archivo / carpeta», y en la paleta «Eolfi: analizar web»,
  «Eolfi: abrir el panel» (Simple Browser) e «Eolfi: último informe». El progreso sale en el canal «Eolfi».
  Ajustes `eolfi.serverUrl` y `eolfi.analysisMode`.
- **Botón «Eolfi»** (barra de estado, pestañas del editor y explorador): abre el Chat con `@eolfi /ayuda`.
  `@eolfi` es un **agente**: el modelo de IA de VS Code decide solo qué herramientas usar (analizar con Eolfi,
  informe, incógnitas, leer, buscar y abrir archivos del proyecto, escribir con confirmación).
- **Terminal e internet en el agente**: `@eolfi` ejecuta órdenes (PowerShell/bash) dentro del proyecto y lee o
  busca en la web, con tu permiso una vez por sesión («Permitir en esta sesión» o «Solo esta vez»). Borrar archivos
  se confirma orden a orden; formatear, apagar, tocar el registro o la seguridad, volcar variables de entorno, forzar
  `git push` o tocar secretos está bloqueado. También puede leer localhost o la LAN si `eolfi.agent.privateNetwork`
  está activo: muestra URL e IP y pide permiso para cada petición (también en modo automático), sin seguir
  redirecciones. Todo queda en el canal «Eolfi» y en `~/.eolfi/agent-log.jsonl`. Ajustes `eolfi.agent.terminal`,
  `eolfi.agent.web` y `eolfi.agent.privateNetwork`.
- **Prueba e2e en un VS Code real**: `cd eolfi/vscode-bridge && npm run e2e [archivo]` (con `python -m eolfi serve`
  arrancado). Abre una instancia aparte con un perfil y un historial temporales, inicia sesión con un código, usa el
  manejador del chat con un stream congelado como el de VS Code y revoca su vinculación al acabar.
- **Memoria entre sesiones**: cada petición a `@eolfi` (lo pedido, la respuesta, las herramientas y los archivos
  cambiados) se guarda solo en tu equipo, en `~/.eolfi/agent-history.jsonl`. El agente recibe lo último hecho en la
  carpeta, busca en todo con `eolfi_historial` y tú con `@eolfi /historial <palabras>`. Ajustes `eolfi.agent.history`
  y `eolfi.agent.historyDays` (365).
- **Modos de trabajo**: ✋ **manual** (por defecto: diff para cada cambio, terminal e internet una vez por sesión,
  borrar orden a orden y REA que ejecuta algo con confirmación) o 🚀 **automático** (las operaciones normales no
  preguntan; cada borrado y conexión a red privada siguen pidiendo confirmación; todo se registra y los cambios de
  cada petición se deshacen). Botón «Manual/Auto» en la barra de
  estado, `@eolfi /auto` / `@eolfi /manual` o el ajuste `eolfi.agent.mode`.
- **Como el modo Agente de Copilot**: cada cambio de `@eolfi` se abre en un diff (archivo ↔ propuesta) con
  «Aplicar» / «Descartar»; al final lista los archivos cambiados con enlaces y un botón «Deshacer estos cambios»; las
  órdenes van en la terminal integrada «Eolfi» (la ves en directo; sin integración de shell, en un proceso aparte) y
  los archivos leídos salen como referencias.
- **Verificación de la auditoría**: al terminar, cada mejora [alta] se comprueba contra el fragmento de código que
  cita y el contexto del proyecto (`.eolfi/auditoria.md` en la carpeta auditada: salvaguardas que ya existen y
  decisiones de diseño aceptadas) y se clasifica en REAL, FALSO o DISEÑO. El resumen solo usa las reales; las demás
  van a «Descartadas al verificar» con su motivo. Si el veredicto es dudoso o ilegible, se queda como REAL.
- **Límites de peticiones de Copilot**: la auditoría usa Auto primero, cambia de modelo si uno llega a su límite y,
  si todos lo están, sigue con un **modelo local llama.cpp** (Eolas en 127.0.0.1:11435 o un `llama-server` en
  127.0.0.1:8080; ajustes `eolfi.fallback.*`): sin límites y sin que el código salga del equipo. Sin Ollama.
  Si no hay ninguno en marcha, **Eolfi arranca un `llama-server`** (en manual pregunta una vez por sesión; en
  automático no) con el GGUF más adecuado para código, solo en 127.0.0.1, y lo para al cerrar VS Code o tras 15 min
  sin uso (`eolfi.fallback.autoStart`, `eolfi.fallback.llamaServer`, `eolfi.fallback.gguf`).
  El **agente** (`@eolfi` con herramientas) también sigue en local cuando todos los modelos de Copilot con
  herramientas están limitados: llama.cpp con llamadas a herramientas (`--jinja`) y las mismas herramientas.
- **Autoarranque de Eolas** (`eolfi.fallback.autoStart`): si Eolas no responde, Eolfi ejecuta el lanzador de CeltIA
  (`launch-eolas.ps1 -Detach -NoBrowser`). No hay ruta fija: se toma de `eolfi.fallback.eolasLauncher` (p. ej.
  `D:\celtiaia\launch-eolas.ps1`) o, si está vacío, de `%CELTIAIA_HOME%\launch-eolas.ps1`; sin ninguno, el autoarranque
  no se ejecuta y lo dice. Antes de ejecutarlo se anota su SHA-256 en la salida «Eolfi»; con
  `eolfi.fallback.eolasLauncherSha256` se exige ese hash y, si no coincide, no se ejecuta.
- **Auditoría archivo por archivo** (`@eolfi /auditar [carpeta]`, o «audita … archivo por archivo»): la dirige Eolfi,
  no el modelo. Inventario de todo el código (sin dependencias, compilados, `samples`, minificados ni secretos), lotes
  de hasta 5 archivos (los grandes por partes, con números de línea) con una plantilla fija (propósito, seguridad,
  errores, calidad, mejoras [alta]/[media]/[baja]), una sección por archivo en `informes/auditoria-archivos-…md`,
  progreso guardado (`/auditar continuar` tras cancelar) y resumen con prioridades al final.
- **Habilidades de análisis**: guías por tipo (PE/ELF/Mach-O, APK, Electron/JS, código fuente archivo a archivo con
  ruff, pip-audit, bandit, semgrep, npm audit y pruebas); las herramientas de REA se listan con su firma (`path*`) y
  unos argumentos que no cuadran no llegan a REA (vuelve el esquema para corregirlos); los informes se van escribiendo
  por secciones con `eolfi_informe_anadir` y se abren al terminar.
- **Auditorías largas**: el agente da hasta 40 pasos por petición (ajuste `eolfi.agent.maxSteps`, máx. 200);
  al llegar al límite resume lo hecho, los hallazgos y lo pendiente, y ofrece «Continuar». En repos grandes recorta los
  resultados antiguos para no pasarse del contexto del modelo y guarda el informe en `informes/` si se lo pides.
- **REA en el agente**: `@eolfi` usa los agentes REA del sistema por MCP con tu configuración
  (`~/.copilot/mcp-config.json` → «rea», o los ajustes `eolfi.rea.*`). Busca entre sus ~230 herramientas y usa la
  adecuada; solo pide confirmación para las que ejecutan algo o tocan procesos y dispositivos (Frida, depuradores,
  rizin, capturas en vivo, adb, instalar…).
- **Otros MCP de Codex**: `mcp_herramientas` y `mcp_usar` descubren y llaman los servidores locales `stdio` de
  `~/.codex/config.toml` (o la ruta `eolfi.mcp.codex.config`; recarga VS Code si cambias el archivo/ruta). Eolfi pide permiso antes de iniciar cada servidor;
  herramientas no marcadas como solo lectura se confirman en cada llamada, incluso en automático. Solo se pasan al
  proceso las variables declaradas por ese servidor; no se importan servidores remotos/OAuth ni la sesión de Codex.
- **Secretos**: el agente nunca lee, busca, analiza ni escribe `.env`, claves (`.pem`, `.key`, `id_rsa`…),
  credenciales ni carpetas como `.ssh` (su contenido no llega al modelo). `/ayuda` lista lo que hace, lo que no
  hace y lo que no puede hacer.
- **Chat `@eolfi`** en el Chat de VS Code: `@eolfi /analizar <archivo | carpeta | URL>`, `/incognitas`,
  `/informe`, o una pregunta sobre lo analizado (responde el modelo del chat con las evidencias de Eolfi).
- **VS Code dentro de Eolfi**: en «Crear», el botón «VS Code» (o «Abrir en VS Code (dentro de Eolfi)» al terminar)
  abre la carpeta en la vista `#vscode` con `code serve-web` (solo `127.0.0.1`, con token). La primera vez hay que
  marcar en el panel que aceptas la licencia del servidor de VS Code; se descarga de Microsoft.

### Puente de chats web (DeepSeek, Gemini, Meta AI)

```bash
python -m eolfi bridge --login  # una vez: inicia sesión en un navegador normal (sin control)
python -m eolfi bridge          # la primera vez instala Electron en eolfi/bridge
python -m eolfi assist D:/p/tienda --provider meta-web --brief "Añade ofertas"
```

- Usa tu **navegador real** (Chrome, Edge, Brave, Opera, Vivaldi o Chromium,
  `--browser edge`) conectado al puente por CDP, con un perfil propio de Eolfi
  (`~/.eolfi/browser-profile`): Google no permite iniciar sesión dentro de
  Electron, pero sí en un navegador normal. `--engine electron` usa ventanas de
  Electron en su lugar.
- Abre una ventana por web con sesión persistente: inicias sesión a mano una
  vez. Los adaptadores (portados de Force) usan solo la interfaz visible: no
  leen cookies ni llaman a endpoints privados.
- Eolfi habla con el puente por una pasarela local (`127.0.0.1`, token en
  `~/.eolfi/bridge.json`, `Host` comprobado). **Cada envío pide tu permiso**
  (permitir, permitir 30 min o denegar). «Permitir 30 min» vale solo para esa conversación, se ve en
  `/v1/status` (`grants`) y se revoca con `POST /v1/revoke`. Si nadie responde en 2 minutos, el diálogo
  se cierra solo (408) y una respuesta tardía no concede nada.
- Un turno interrumpido deja la conversación «dudosa» (para no duplicar el mensaje): `POST /v1/reset`
  `{"provider", "conversation"}` la desbloquea. El plazo de respuesta (4 min) se cambia con
  `EOLFI_BRIDGE_REPLY_MS` (DeepThink y similares tardan más).
- **Streaming**: mientras el chat escribe, el panel muestra el texto parcial. El plazo es de INACTIVIDAD: una
  respuesta que sigue creciendo no caduca (tope total de 30 min, `EOLFI_BRIDGE_MAX_REPLY_MS`). Una respuesta solo
  se da por terminada si su texto no cambia entre dos lecturas seguidas.
- **Más chats (adaptador declarativo)**: ChatGPT (`chatgpt-web`), Microsoft Copilot (`copilot-web`) y Le Chat de
  Mistral (`lechat-web`), descritos con selectores en `eolfi/bridge/adapters/sites.json`. ChatGPT y Le Chat están
  **calibrados** con mensajes reales (2026-11-05); Copilot no (pide iniciar sesión). El botón **Autodiagnóstico** comprueba
  qué partes de la página encuentra, sin escribir nada, y se recalibran copiando selectores corregidos en
  `~/.eolfi/bridge-sites.json` (solo selectores: no se pueden cambiar orígenes ni añadir sitios). Por defecto se
  abren DeepSeek, Gemini, Meta y **Le Chat** (también en el desplegable de IA de «Crear» y en el
  proveedor automático `web`); `EOLFI_BRIDGE_CHATS=deepseek,chatgpt,lechat` elige otros.
  Claude.ai no se incluye: Eolfi ya usa la API oficial de Claude (`--provider claude`).
- **Comparativa**: el mismo mensaje a 2–6 chats a la vez con **una sola aprobación** y las respuestas lado a lado
  (en el panel, «Comparar varios chats»; API `POST /v1/compare` del puente o `POST /api/bridge/compare`).
- Si el paquete está instalado en una carpeta sin permiso de escritura (site-packages), el puente se
  copia a `~/.eolfi/bridge-app` y se instala allí (`EOLFI_BRIDGE_HOME` lo cambia).
- Límite de 32 000 caracteres por mensaje: Eolfi envía un contexto reducido,
  pide JSON y, en las reparaciones, solo el error (la conversación sigue en la web).
- En el panel, **Chats web** muestra en directo cada ventana (interactiva: clic,
  rueda y teclado van al navegador real), el historial y una caja para escribir
  tú mismo (tus mensajes no piden permiso; los de Eolfi sí).
- **Inicio de sesión**: Google y otras webs rechazan el acceso desde navegadores
  controlados por software. `bridge --login` abre el perfil de Eolfi en un
  navegador normal, sin control remoto; entras, cierras la ventana y el puente
  reutiliza esas sesiones.
- **Sesiones persistentes**: inicias sesión una vez en cada chat y el perfil de
  Eolfi la conserva entre reinicios (también si cierras el navegador).
- **Motor Electron (`--engine electron` o sin navegador instalado)**: se ejecuta con
  `electron .` sin empaquetar, y Electron 45 de serie trae el fusible
  `EnableCookieEncryption` deshabilitado y `RunAsNode`, `NODE_OPTIONS` e `--inspect`
  habilitados. Por eso las sesiones de las ventanas (`persist:eolfi-*`) se guardan
  **sin ese cifrado de cookies**; el puente lo avisa al arrancar. El motor
  recomendado es tu navegador real (el predeterminado si hay uno instalado).
  Empaquetar con `@electron/fuses` lo resolvería, pero requiere instalar esa
  dependencia y no está hecho.
- **Control por tubería privada**: el puente controla su Chrome con
  `--remote-debugging-pipe`, sin ningún puerto de depuración TCP; ningún otro
  programa ni usuario del equipo puede conectarse a él ni leer sus cookies. Al
  cerrar el puente se cierra ese navegador (las sesiones quedan en el perfil).
- **Dos credenciales**: Eolfi automático (cada envío pide tu aprobación) y el
  panel (lo que tecleas tú); solo el panel puede ver y manejar la ventana. El estado indica si cada chat está "con
  sesión" o en "modo invitado".
- `--provider web` elige solo el primer chat listo, prefiriendo los que tienen
  sesión (orden configurable con `EOLFI_WEB_ORDER=meta,deepseek,gemini`).
- La respuesta se da por terminada en cuanto la web retira su botón de
  "Detener respuesta" (~0,2-0,6 s de margen); el resto del tiempo es la web
  generando en sus servidores.
- Automatizar estas webs puede ir contra sus condiciones de uso: se hace con
  tu cuenta y bajo tu responsabilidad.

## Eolfi en el modo agente de VS Code (sustituye a @eolfi)

VS Code marca los *chat participants* como obsoletos y el harness de Copilot ya no los admite. Desde la
extensión 0.6.0, Eolfi llega al chat por las vías nuevas y funciona con **el modelo que elijas en el selector**:

- **Servidor MCP** (`python -m eolfi mcp`): `eolfi_triage`, `eolfi_evidencias`, `eolfi_incognitas`,
  `eolfi_resolver`, `eolfi_informe`, `eolfi_comparar`, `eolfi_web`, `eolfi_repo`, `eolfi_inyeccion`,
  `eolfi_biblioteca_buscar` (consulta local de referencia en Alejandría), `eolfi_biblioteca_leer` (recupera un documento concreto bajo demanda, sin copiar toda la biblioteca), `eolfi_doctor`. La extensión lo registra sola (VS Code ≥ 1.101), limitado a las carpetas abiertas.
  Fuera de VS Code (Claude Code u otro cliente MCP): `{"command": "python", "args": ["-m", "eolfi", "mcp", "--root", "D:/proyectos"]}`
  con `PYTHONPATH` en la carpeta de Eolfi.
- **Herramientas de la extensión**: `eolfi_carpetas`, `eolfi_auditar` (archivo por archivo, con informe y
  reanudación), `eolfi_historial`, `rea_herramientas` y `rea_usar`.
- **Agente «Eolfi»** y prompt files `/analizar`, `/auditar`, `/incognitas`, `/informe`, `/rea`: comando
  «Eolfi: instalar el agente en este workspace» (los copia a `.github/agents` y `.github/prompts`).
- Las carpetas se reconocen por su **nombre** (sin mayúsculas, tildes ni guiones): «celtiaia» encuentra la
  carpeta abierta «CeltIA-IA».
- `@eolfi` sigue una versión más; `eolfi.chatParticipant: false` lo quita.

## Más análisis

```bash
python -m eolfi triage app.apk                    # APK/AAR/JAR/IPA: manifiesto, DEX, libs nativas, librerías
python -m eolfi triage binario-macos              # Mach-O fino o universal
python -m eolfi decompile programa.exe --functions entry,main   # pseudo-C con Ghidra
python -m eolfi compare <objetivo_v1> <objetivo_v2>             # qué cambió entre versiones
python -m eolfi export informe.stix.json          # STIX 2.1
```

## Verificación diferencial

```bash
python -m eolfi diff corpus/     --ref  "./original {input}"     --cand "python reimpl.py {input}"     --mutate 200 --determinism --threshold 1.0 --autorizo
```

`{input}` se sustituye por cada archivo del corpus (sin él, la entrada va por
stdin). Compara código de salida y stdout (`--stderr` para stderr;
`--normalize exact|newlines|lines`). Cada discrepancia abre una incógnita
`high`; cuando una ejecución posterior coincide, se **cierra sola**. Sale con
código 4 si no se alcanza el umbral. **Ejecuta ambos programas**: hazlo solo
con software que puedas ejecutar con seguridad.

## Flujo de reimplementación (replicar en otro lenguaje)

1. **Triaje y adquisición** → ficha del objetivo + huella.
2. **Recuperar comportamiento** (desensamblado, simbólico, trazas).
3. **Especificación** legible que cita sus evidencias.
4. **Reimplementación** en el lenguaje destino a partir de la spec.
5. **Verificación diferencial**: mismo corpus de entradas, comparar salidas.
6. **Cierre de incógnitas** hasta alcanzar el umbral de equivalencia.

## Seguridad

- Analiza muestras no confiables en una **VM aislada** sin red; el orquestador
  no es una sandbox por sí mismo.
- El trazado y la captura *ejecutan* el objetivo con tus permisos: solo sobre
  software que puedas ejecutar con seguridad.
- Descarga cada herramienta de su fuente oficial y fija versiones con huella.

## Estructura

```
eolfi/
  core/        modelo de evidencias, SQLite, exportación SARIF y STIX
  providers/   triaje, PE/ELF/Mach-O, DEX/APK, cadenas, capa, rizin, Ghidra
  sites/       análisis de webs (fetch seguro, HTML/CSS/JS) y repositorios; huellas de pila
  generador/   generador de proyectos de Eolfi: especificación, plantillas, verificación e IA
  flows/       triaje, diferencial, aprendizaje, comparación, creación
  security/    banco de resiliencia (fuzz, inyección)
  web/         panel del servidor de desarrollo
  server.py    servidor de desarrollo (API + panel, --reload)
  cli.py       interfaz de línea de comandos
tests/         pruebas (pytest) con muestras sintéticas
```

## Guía de caja negra

[`ejemplos/caja-negra/GUIA.md`](ejemplos/caja-negra/GUIA.md): de un programa sin fuentes a una reconstrucción
comprobada (plan, observación, especificación, reconstrucción, equivalencia, informe y borrado) con una muestra
sintética propia y criterios de aceptación por paso. La CI la ejecuta tal cual (`tests/test_guia_caja_negra.py`).

Otras guías con el mismo formato, también ejecutadas en la CI:

- [`ejemplos/api-http/GUIA.md`](ejemplos/api-http/GUIA.md): de una API HTTP sin fuentes a una API reconstruida
  (`reconstruct --target python-http`) que solo responde a lo observado (501 para lo no observado, 503 para lo
  pendiente).
- [`ejemplos/triaje-y-diff/GUIA.md`](ejemplos/triaje-y-diff/GUIA.md): triaje local de un WebAssembly, informe con
  umbral `--fail-on` para CI y verificación diferencial de una reimplementación.
- [`ejemplos/web-y-repo/GUIA.md`](ejemplos/web-y-repo/GUIA.md): análisis de un sitio estático y de un repositorio
  locales, y creación de un proyecto nuevo a partir del sitio (`create`), con lo que se observa y lo que se añade.
- [`ejemplos/puente/GUIA.md`](ejemplos/puente/GUIA.md): el puente de chats web. Iniciar sesión y usarlo con tus
  cuentas (laboratorio) y, en la CI, un cambio completo con la pasarela real y un chat simulado, el permiso
  denegado y las protecciones de la pasarela.
- [`ejemplos/agente-vscode/GUIA.md`](ejemplos/agente-vscode/GUIA.md): el agente @eolfi en VS Code (laboratorio) y,
  en la CI, el servidor MCP de Eolfi por stdio y lo que declara la extensión.

## Pruebas

```bash
python -m pytest -q                       # núcleo, parsers, servidor, generador y sitios
cd eolfi/bridge && node --test            # puente (sin Electron ni navegador)
cd tests/e2e && npm install && npm test   # panel en un navegador real + accesibilidad con axe-core
```

- El e2e usa el Chrome ya instalado (no descarga navegadores): `EOLFI_E2E_CHANNEL=msedge` o
  `EOLFI_E2E_BROWSER=/ruta/al/navegador` para usar otro. Falla si axe encuentra problemas graves o críticos.
- `.github/workflows/ci.yml` ejecuta las tres cosas (Python en Windows, macOS y Linux).

### Pruebas de laboratorio (opcionales, fuera de la CI)

Necesitan servicios reales o recursos locales que la CI no tiene; no se ejecutan con `npm test` ni con pytest
salvo que el recurso esté presente:

```bash
# Recorrido completo en el panel REAL con Chrome visible: fuentes → plan razonado → aprobar → generar →
# verificar → comparar. Antes: «python -m eolfi up» (o «serve»). Deja un caso «e2e en vivo <fecha>» en la base.
cd tests/e2e && node live/crear-proyecto.live.mjs        # EOLFI_LIVE_URL, EOLFI_LIVE_HEADLESS=1

# Agente @eolfi con el modelo local (Eolas en 127.0.0.1:11435 o llama-server), sin Copilot.
cd eolfi/vscode-bridge && node e2e/local-eolas-live.js
```

- Observación aislada en contenedor (`tests/test_container.py`): se ejecuta si Docker tiene la imagen
  `python:3.12-slim` (o la de `EOLFI_TEST_IMAGE`) en local; si no, se omite. Eolfi nunca la descarga.
- Escritorio con UI Automation (`tests/test_observe.py`) solo en Windows; el registro, solo en Windows.
- Los pasos de escritorio pueden incluir `"screenshots": true`: guardan hasta 20 imágenes JPEG por paso, limitadas
  a 1280×800 y 256 KiB cada una, y las muestran en el informe HTML del caso. Es opcional; las imágenes no reciben
  redacción automática de datos visuales, así que habilítalo solo si el contenido de esa ventana se puede conservar.
- La observación de interfaz móvil sigue sin implementarse; exige herramientas Android y un dispositivo/emulador autorizado.

## Android

`triage` sobre una APK decodifica el **AndroidManifest binario (AXML)** y
resuelve sus referencias `@0x7f…` contra **`resources.arsc`** (nombre de la app,
icono, tema, configuración de red, siguiendo alias):
paquete, versiones, SDK mínimo/objetivo, permisos (peligrosos y especiales),
componentes y si están exportados, filtros de intent, deep links y el
lanzador real (los alias desactivados se listan aparte). Avisos como app
depurable, `allowBackup`, tráfico HTTP sin cifrar o componentes exportados
sin permiso se registran como incógnitas. Los DEX dan clases, paquetes,
checksum y librerías detectadas (Compose, Room, Ktor, OkHttp, Hilt…).

## Corpus compartido con Alejandría

Eolfi comparte su código y sus textos con la biblioteca **Alejandría** (`D:\Alejandria`) y puede consultarla desde el MCP cuando necesita contexto:
- El código va a `corpus\codigo\Eolfi\…` y los textos (`.md`/`.txt`) a `corpus\texto\Eolfi\…`.
- Una sola copia por contenido, con la sintaxis validada y cada acción registrada en `manifests\auditoria.jsonl`.
- Se incluyen los proyectos generados en `generated\`. Se excluyen `samples\` (binarios y repos ajenos), entornos
  virtuales, `node_modules` y artefactos de compilación.
- Las fuentes se declaran en `D:\Alejandria\config\fuentes.json` (Force y Eolfi).

El mantenimiento horario de Alejandría las importa solo; para hacerlo al momento:

```bash
python -m eolfi corpus --dry-run     # qué entraría
python -m eolfi corpus               # importa y audita la biblioteca
```

`--library` (o `EOLFI_LIBRARY`) elige otra biblioteca. Eolfi no copia nada por su cuenta: usa los scripts de la
propia biblioteca, así la validación, la deduplicación y la auditoría son las mismas.
Las herramientas MCP `eolfi_biblioteca_buscar` y `eolfi_biblioteca_leer` solo leen el índice y archivos permitidos bajo
`corpus/codigo` y `corpus/texto`; Eolfi puede recuperar documentos concretos a petición y leerlos por fragmentos
sin copiar la biblioteca entera. Se omiten carpetas locales de respaldo/salidas antiguas y se limita el tamaño de lectura. Sus resultados
son referencias del corpus, no evidencias del objetivo analizado. Configura `EOLFI_LIBRARY` o pasa `--library`
para elegir otra biblioteca.

## Estado

v0.8.0. Hecho: análisis de binarios de **todos los sistemas** (PE de Windows,
ELF de Linux, Mach-O de macOS/iOS, DEX/APK de Android con manifiesto AXML y
`resources.arsc`, IPA, JAR), Ghidra/capa/rizin, comparación de versiones, SARIF
y STIX, análisis de webs y repositorios, y creación de proyectos nuevos
verificados en 13 destinos: web (estático, React, Vue, Svelte, Next.js),
backend (FastAPI, Express, Django, con SQLite, migraciones y autenticación
opcionales), **móvil Android e iOS** (Expo, con `eas.json`), **escritorio
Windows, macOS y Linux** (Electron, Tauri nativo o .NET/Avalonia nativo, con
instaladores) y **línea de comandos** (Python, ejecutable por sistema). Modo asistido por IA
(Claude, Eolas, APIs y chats web de DeepSeek, Gemini y Meta AI mediante un
puente con tu navegador real), panel con vista en directo, selector de
carpetas, trabajos en segundo plano con progreso, pestaña **Proveedores** (elige la IA
y qué proveedores de análisis se ejecutan) y tema automático, claro u oscuro. Auditoría de seguridad aplicada: ver `PLAN_CORRECCIONES.md`.
