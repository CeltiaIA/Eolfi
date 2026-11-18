"""Idioma de los proyectos generados (C4, 18/11/2026).

Los generadores escriben en castellano. Con ``spec["idioma"] == "en"`` el escritor (``generators._writer``) pasa cada
archivo por :func:`traducir`, que sustituye las frases de :data:`EN` por su versión en inglés. Se traduce en el
escritor, y no en cada generador, para que el texto de la interfaz y las pruebas generadas que lo comprueban
(``<html lang="es">``, «Página no encontrada», la etiqueta del botón…) cambien siempre a la vez.

Reglas del catálogo:
- Coincidencia exacta y sensible a mayúsculas, sin partir palabras (``Diseño`` no toca ``Diseñora``).
- Si dos frases se solapan gana la más larga («Inicia sesión para añadir datos.» antes que «Añadir»).
- Solo frases que ve el usuario o que nombran pruebas y errores del proyecto; nunca identificadores de código.

README.md y la receta de despliegue no pasan por aquí: en inglés se escriben enteros aparte (`_readme_en`, `despliegue.receta_en` y DEPLOYMENT.md), sin traducirlos a medias.
"""
from __future__ import annotations

import re
from functools import lru_cache

IDIOMAS = ("es", "en")
NO_TRADUCIR = ("README.md", "DESPLIEGUE.md", "DEPLOYMENT.md", "eolfi.spec.json")

EN: dict[str, str] = {
    # ── Atributos de idioma ──
    '<html lang="es">': '<html lang="en">',
    '<html lang="es"': '<html lang="en"',
    '"lang": "es"': '"lang": "en"',
    'LANGUAGE_CODE = "es"': 'LANGUAGE_CODE = "en"',
    # ── Esqueleto de las páginas ──
    "Saltar al contenido": "Skip to content",
    "Principal": "Main",
    "Tema oscuro": "Dark theme",
    "Tema claro": "Light theme",
    "Cambiar tema": "Toggle theme",
    "Inicio": "Home",
    "Página de ejemplo: cambia este texto.": "Sample page: change this text.",
    "Página no encontrada": "Page not found",
    "No encontrado": "Not found",
    "Volver al inicio": "Back to home",
    "Hecho con código nuevo.": "Built with new code.",
    "proyecto generado con Eolfi.": "project generated with Eolfi.",
    # Nombres de página (spec.PAGE_WORDS)
    "Sobre": "About", "Precios": "Pricing", "Contacto": "Contact", "Funciones": "Features", "Equipo": "Team",
    "Productos": "Products", "Servicios": "Services", "Guía": "Guide", "Noticias": "News", "Empleo": "Careers",
    # ── Textos de ejemplo (templates.content_for) ──
    "Nuevo": "New",
    "Una base moderna, accesible y rápida para empezar tu proyecto. Cambia estos textos por los tuyos.":
        "A modern, accessible and fast starting point for your project. Replace these texts with your own.",
    "Empezar": "Get started",
    "Ver funciones": "See features",
    "Confían en nosotros": "Trusted by",
    "Marca": "Brand",
    "Todo lo necesario, nada de sobra.": "Everything you need, nothing you don't.",
    "Rápido": "Fast",
    "Carga en milisegundos y funciona sin conexión lenta.": "Loads in milliseconds and works on slow connections.",
    "Accesible": "Accessible",
    "Semántica correcta, foco visible y contraste suficiente.": "Correct semantics, visible focus and enough contrast.",
    "Modular": "Modular",
    "Secciones independientes que puedes reordenar.": "Independent sections you can reorder.",
    "Catálogo": "Catalog",
    "Elemento": "Item",
    "Descripción breve del elemento.": "Short description of the item.",
    "Ver más": "See more",
    "99,9 %": "99.9%",
    "disponibilidad": "uptime",
    "tiempo de carga": "load time",
    "soporte": "support",
    "Opiniones": "Testimonials",
    "Lo pusimos en marcha en una tarde.": "We had it running in an afternoon.",
    "Ana, diseñadora": "Ana, designer",
    "Claro, rápido y fácil de mantener.": "Clear, fast and easy to maintain.",
    "Luis, desarrollador": "Luis, developer",
    "Justo lo que necesitábamos para empezar.": "Just what we needed to get started.",
    "Marta, producto": "Marta, product",
    "Dirección": "Management", "Diseño": "Design", "Ingeniería": "Engineering", "Soporte": "Support",
    "Últimas entradas": "Latest posts",
    "Entrada de ejemplo": "Sample post",
    "Resumen corto de la entrada.": "Short summary of the post.",
    "Básico": "Basic",
    "0 €": "€0",
    "Para probar.": "To try it out.",
    "12 €/mes": "€12/mo",
    "Para equipos pequeños.": "For small teams.",
    "Elegir Pro": "Choose Pro",
    "Empresa": "Enterprise",
    "A medida": "Custom",
    "Para organizaciones.": "For organizations.",
    "Contactar": "Contact us",
    "Preguntas frecuentes": "Frequently asked questions",
    "¿Puedo cambiar los textos?": "Can I change the texts?",
    "Sí: están todos en el archivo de contenido.": "Yes: they are all in the content file.",
    "¿Funciona en móvil?": "Does it work on mobile?",
    "Sí, el diseño es adaptable.": "Yes, the layout is responsive.",
    "¿Cómo lo despliego?": "How do I deploy it?",
    "Sigue los pasos del README.": "Follow the steps in the README.",
    "¿Empezamos?": "Shall we start?",
    "Crea tu primera versión hoy mismo.": "Build your first version today.",
    "Hablemos": "Let's talk",
    "Escríbenos y te respondemos pronto.": "Write to us and we'll get back to you soon.",
    "Nombre": "Name",
    "Correo": "Email",
    "Mensaje": "Message",
    "Enviar": "Send",
    "Formulario de ejemplo: el mensaje aún no se envía a ningún sitio (conéctalo a tu servidor).":
        "Sample form: the message is not sent anywhere yet (connect it to your server).",
    "Revisa los campos: todos son obligatorios y el correo debe ser válido.":
        "Check the fields: all are required and the email must be valid.",
    # ── Datos en vivo, sesión y API ──
    "Datos en vivo": "Live data",
    "Estas listas vienen de la API del propio proyecto.": "These lists come from the project's own API.",
    "Vacío": "Empty",
    "API no disponible (arranca el backend en :8000)": "API unavailable (start the backend on :8000)",
    "API no disponible": "API unavailable",
    "Configura EXPO_PUBLIC_API_URL para ver datos en vivo": "Set EXPO_PUBLIC_API_URL to see live data",
    "Añadir": "Add",
    "Dato de ejemplo": "Sample item",
    "Inicia sesión para añadir datos.": "Sign in to add data.",
    "Inicia sesión para hacer cambios": "Sign in to make changes",
    "Iniciar sesión": "Sign in",
    "Crear cuenta": "Create account",
    "Entrar": "Sign in",
    "Entrando…": "Signing in…",
    "Usuario": "User",
    "Borrar": "Delete",
    "No se pudo iniciar sesión": "Could not sign in",
    "Credenciales incorrectas": "Wrong credentials",
    "Demasiados intentos: espera unos minutos": "Too many attempts: wait a few minutes",
    "Sesión iniciada como": "Signed in as",
    # ── Migraciones SQLite (--db sqlite) ──
    "Número de migración repetido:": "Duplicate migration number:",
    "no uses BEGIN/COMMIT; cada migración ya va en su transacción":
        "do not use BEGIN/COMMIT; each migration already runs in its own transaction",
    "La migración": "Migration",
    "cambió después de aplicarse: crea una nueva en lugar de editarla":
        "changed after being applied: create a new one instead of editing it",
    '"cambió"': '"changed"',
    "/cambió/": "/changed/",
    "Falló": "Failed",
    "describe aquí el cambio de esquema.": "describe the schema change here.",
    "Ejemplo:": "Example:",
    "Migraciones al día.": "Migrations up to date.",
    "No hay migraciones pendientes.": "No pending migrations.",
    "Bearer nada": "Bearer nothing",
    "nombre de tabla inválido:": "invalid table name:",
    "debía detectar la migración editada": "should have detected the edited migration",
    "Cerrar sesión": "Sign out",
    "Contraseña": "Password",
    "Sesión iniciada.": "Signed in.",
    "Inicio de sesión no configurado (AUTH_USER, AUTH_PASSWORD)": "Sign-in not configured (AUTH_USER, AUTH_PASSWORD)",
    "Inicio y cierre de sesión": "Sign-in and sign-out",
    "inicio y cierre de sesión": "sign-in and sign-out",
    "Inicio de sesión (solo si el proyecto se generó con --auth). El token vive en":
        "Sign-in (only if the project was generated with --auth). The token lives in",
    "sessionStorage: se borra al cerrar la pestaña.": "sessionStorage: it is cleared when the tab closes.",
    "Demasiadas peticiones: espera un minuto": "Too many requests: wait a minute",
    "Sesión caducada o inválida": "Session expired or invalid",
    "correo inválido": "invalid email",
    "la contraseña necesita 8-200 caracteres": "the password needs 8-200 characters",
    "las escrituras exigen sesión": "writes require a session",
    "sin enumeración, cierre de sesión y límite de intentos": "no enumeration, sign-out and attempt limit",
    "Ventana deslizante por IP para /register y /login.": "Sliding window per IP for /register and /login.",
    "contraseña-segura": "secure-password",
    "otra-contraseña": "another-password",
    "mal-contraseña": "wrong-password",
    "contraseña-eva": "eva-password",
    "No se pudo crear la cuenta": "Could not create the account",
    "Correo o contraseña incorrectos": "Wrong email or password",
    "Primer elemento de": "First item of",
    "CRUD de": "CRUD for",
    "name es obligatorio (1-200 caracteres)": "name is required (1-200 characters)",
    "description debe ser texto (máx. 2000)": "description must be text (max. 2000)",
    "el nombre debe tener entre 1 y 200 caracteres": "the name must be between 1 and 200 characters",
    "JSON inválido": "Invalid JSON",
    "Petición inválida": "Invalid request",
    "Error interno": "Internal error",
    "método no permitido": "method not allowed",
    "Prohibido": "Forbidden",
    "Router no instalado": "Router not installed",
    "validación": "validation",
    # ── Comentarios y arranque de servidores ──
    "Tokens de diseño generados por Eolfi a partir de los colores, fuentes y":
        "Design tokens generated by Eolfi from the colors, fonts and",
    "puntos de corte observados en las fuentes. Ajústalos a tu marca.":
        "breakpoints observed in the sources. Adjust them to your brand.",
    "/* aún arrancando */": "/* still starting */",
    "Sirviendo ${root} en http://localhost:${port}": "Serving ${root} on http://localhost:${port}",
    "Escuchando en http://localhost:${port}": "Listening on http://localhost:${port}",
    "API de": "API for",
    "Arranque:": "Start:",
    "Cabeceras de seguridad en TODAS las respuestas (API y frontend estático).":
        "Security headers on ALL responses (API and static frontend).",
    "Cabeceras de seguridad en todas las respuestas (generado por Eolfi).":
        "Security headers on all responses (generated by Eolfi).",
    "Almacén en memoria, seguro entre hilos (se pierde al reiniciar). Usa --db sqlite para persistir.":
        "Thread-safe in-memory store (lost on restart). Use --db sqlite to persist.",
    "Ajustes de": "Settings for",
    "En producción define DJANGO_SECRET_KEY, DJANGO_DEBUG=0 y DJANGO_ALLOWED_HOSTS.":
        "In production set DJANGO_SECRET_KEY, DJANGO_DEBUG=0 and DJANGO_ALLOWED_HOSTS.",
    "Define DJANGO_SECRET_KEY (obligatoria con DJANGO_DEBUG=0)": "Set DJANGO_SECRET_KEY (required with DJANGO_DEBUG=0)",
    "solo-desarrollo-no-usar-en-produccion": "development-only-do-not-use-in-production",
    "clave-de-prueba": "test-key",
    # ── Pruebas generadas ──
    "${page} enlaza ${ref}, que no existe": "${page} links ${ref}, which does not exist",
    "${page} es HTML accesible y enlaza recursos existentes": "${page} is accessible HTML and links existing resources",
    "renderiza la portada con un único h1": "renders the home page with a single h1",
    "la ruta %s renderiza": "route %s renders",
    "muestra 404 en rutas desconocidas": "shows 404 on unknown routes",
    "404 en rutas desconocidas": "404 on unknown routes",
    "debe haber un único h1": "there must be a single h1",
    "${page}: debe haber un único h1": "${page}: there must be a single h1",
    "${page}: un único h1": "${page}: a single h1",
    "${page} sin CSP": "${page} without CSP",
    "next start no respondió": "next start did not respond",
    "la página ${path} responde": "page ${path} responds",
    "la portada muestra el título y todas las pestañas": "the home page shows the title and every tab",
    "la pestaña Sobre muestra su página": "the About tab shows its page",
    "el formulario valida y da las gracias": "the form validates and says thanks",
    "Mensaje de prueba": "Test message",
    "La prueba de humo falló (código ${r.status ?? r.signal})": "The smoke test failed (code ${r.status ?? r.signal})",
    "Prueba de humo superada: la app de escritorio arranca y carga su interfaz.":
        "Smoke test passed: the desktop app starts and loads its interface.",
    "ventana endurecida: aislamiento, sandbox y sin Node en la página":
        "hardened window: isolation, sandbox and no Node in the page",
    "la interfaz se sirve por app://, no por file://": "the interface is served over app://, not file://",
    "fusibles de Electron al empaquetar (sin RunAsNode ni --inspect)":
        "Electron fuses when packaging (no RunAsNode or --inspect)",
    "la interfaz tiene CSP y enlaza recursos existentes": "the interface has a CSP and links existing resources",
    "instaladores configurados para Windows, macOS y Linux": "installers configured for Windows, macOS and Linux",
    "CSP estricta y sin API global de Tauri en la página": "strict CSP and no global Tauri API in the page",
    "permisos mínimos: solo core:default": "minimal permissions: only core:default",
    "instaladores para todos los sistemas e identificador válido": "installers for every system and a valid identifier",
    "la interfaz enlaza recursos existentes": "the interface links existing resources",
    "no se pudo arrancar la aplicación": "the application could not start",
    # ── Línea de órdenes (destino cli) ──
    "herramienta de línea de comandos (Windows, macOS y Linux).": "command-line tool (Windows, macOS and Linux).",
    "herramienta de línea de comandos": "command-line tool",
    "salida en JSON (para scripts)": "JSON output (for scripts)",
    "versión, sistema y carpeta de datos": "version, system and data folder",
    "RECURSO": "RESOURCE",
    "ACCIÓN": "ACTION",
    "añade un elemento a {res}": "adds an item to {res}",
    "gestiona {res}": "manages {res}",
    "lista {res}": "lists {res}",
    "{text} un elemento por id": "{text} an item by id",
    '"muestra"': '"shows"',
    '"borra"': '"removes"',
    "descripción": "description",
    "(vacío)": "(empty)",
    # ── Destino Rust (D2) ──
    "Uso:": "Usage:",
    "RECURSO ACCIÓN": "RESOURCE ACTION",
    "NOMBRE [-d DESCRIPCIÓN]": "NAME [-d DESCRIPTION]",
    "Opciones:": "Options:",
    "falta la descripción tras -d": "missing description after -d",
    "id no válido:": "invalid id:",
    "orden desconocida": "unknown command",
    "no se pudo leer {}: {e}": "could not read {}: {e}",
    "no se pudo guardar {}: {e}": "could not save {}: {e}",
    "error: no existe {res} {}": "error: {res} {} does not exist",
    "no existe": "does not exist",
    "error: no existe {args.resource} {args.id}": "error: {args.resource} {args.id} does not exist",
    "error: no se pudo leer {self.path}: {exc}": "error: could not read {self.path}: {exc}",
    "Almacenamiento local en JSON, en la carpeta de datos del usuario de cada sistema.":
        "Local JSON storage, in each system's user data folder.",
    "Una lista de elementos por recurso; escritura atómica (archivo temporal + reemplazo).":
        "One list of items per resource; atomic writes (temporary file + replace).",
    "Primero": "First",
}

# Comentarios y docstrings del código generado (C4, 18/11/2026). Cada clave es una línea entera de comentario tal como
# la escriben los generadores (un comentario de varias líneas va línea a línea), para que no quede a medias: la frase
# entera gana a las más cortas del catálogo («no existe», «Nombre»…) que contenga.
COMENTARIOS: dict[str, str] = {
    # ── Autenticación (fastapi, express, next) ──
    "Contraseñas: PBKDF2-SHA256, sal aleatoria de 16 bytes, 210 000 iteraciones.":
        "Passwords: PBKDF2-SHA256, random 16-byte salt, 210,000 iterations.",
    "Tokens: 32 bytes aleatorios, caducan a las 12 h; se guarda solo su hash SHA-256.":
        "Tokens: 32 random bytes, expire after 12 h; only their SHA-256 hash is stored.",
    "Comparaciones en tiempo constante.": "Constant-time comparisons.",
    "Autenticación: registro, inicio de sesión y token Bearer para las escrituras.":
        "Authentication: sign-up, sign-in and a Bearer token for writes.",
    "Asíncrono: pbkdf2Sync bloquearía el event loop ~100-200 ms por login.":
        "Asynchronous: pbkdf2Sync would block the event loop ~100-200 ms per login.",
    "Misma respuesta si el correo ya existía: no se revela qué correos están registrados.":
        "Same response if the email already existed: registered emails are not revealed.",
    "Se calcula el hash aunque el usuario no exista, para no revelar qué correos están registrados.":
        "The hash is computed even if the user does not exist, so registered emails are not revealed.",
    "Registrar de nuevo un correo existente responde igual (sin enumeración) y no cambia la contraseña.":
        "Registering an existing email again gives the same response (no enumeration) and keeps the password.",
    "PBKDF2-SHA256 (sal de 16 bytes, 210 000 iteraciones); tokens aleatorios de 32 bytes,":
        "PBKDF2-SHA256 (16-byte salt, 210,000 iterations); random 32-byte tokens",
    "caducan a las 12 h y se guarda solo su hash; comparaciones en tiempo constante.":
        "that expire after 12 h, of which only the hash is stored; constant-time comparisons.",
    "Un Map recuerda el orden de inserción: borrar y volver a insertar lo marca como reciente.":
        "A Map keeps insertion order: deleting and re-inserting marks it as recent.",
    "peticiones de registro/inicio de sesión por IP y minuto (cada una cuesta un PBKDF2)":
        "sign-up/sign-in requests per IP and minute (each one costs a PBKDF2)",
    "tope de correos/IP recordados: los más antiguos se olvidan (LRU)":
        "cap on remembered emails/IPs: the oldest are forgotten (LRU)",
    "Ventana deslizante por IP para /register y /login.": "Sliding window per IP for /register and /login.",
    "purga de tokens caducados": "purge expired tokens",
    "purga": "purge",
    "auth_users y auth_tokens los crea la migración inicial": "auth_users and auth_tokens are created by the initial migration",
    "las tablas auth_users y auth_tokens las crea la migración inicial":
        "the auth_users and auth_tokens tables are created by the initial migration",
    "mismo lock que el almacén: commits sin mezclar transacciones": "same lock as the store: commits without mixing transactions",
    "Usuario de una sesión válida (firma y caducidad) o null.": "User of a valid session (signature and expiry) or null.",
    "Implementación propia de Eolfi: los usuarios y la política de sesiones del original NO son observables;":
        "Eolfi's own implementation: the original's users and session policy are NOT observable;",
    "aquí hay un único usuario configurado por variables de entorno (pendiente de adaptar a tu base de datos).":
        "here there is a single user configured through environment variables (to be adapted to your database).",
    "Igual en todos los módulos del servidor (rutas de la API y páginas se cargan por separado): AUTH_SECRET o, si":
        "The same in every server module (API routes and pages load separately): AUTH_SECRET or, if",
    "falta, una clave derivada de las credenciales configuradas. En producción define AUTH_SECRET.":
        "missing, a key derived from the configured credentials. In production set AUTH_SECRET.",
    # ── Almacenamiento y migraciones ──
    "0001_init.sql: esquema inicial generado por Eolfi. No la edites: crea migraciones nuevas.":
        "0001_init.sql: initial schema generated by Eolfi. Do not edit it: create new migrations.",
    "Almacén en memoria (se pierde al reiniciar). Usa --db sqlite para persistir.":
        "In-memory store (lost on restart). Use --db sqlite to persist.",
    "Almacén en memoria por recurso (se reinicia con el servidor). Sustitúyelo por una base de datos.":
        "In-memory store per resource (reset with the server). Replace it with a database.",
    "Persistencia en SQLite (librería estándar). Ruta: variable APP_DB (por defecto data/app.db).":
        "SQLite persistence (standard library). Path: APP_DB variable (default data/app.db).",
    "Persistencia en SQLite con node:sqlite (Node ≥ 22.13, sin dependencias). Ruta: APP_DB (data/app.db).":
        "SQLite persistence with node:sqlite (Node ≥ 22.13, no dependencies). Path: APP_DB (data/app.db).",
    "Conexión única; la primera vez aplica las migraciones pendientes (migrations/).":
        "Single connection; the first time it applies pending migrations (migrations/).",
    "Una tabla por recurso; el nombre de tabla está validado (nunca viene del usuario).":
        "One table per resource; the table name is validated (it never comes from the user).",
    "Único lock (reentrante) para TODA la conexión compartida: almacén y autenticación.":
        "Single (reentrant) lock for the WHOLE shared connection: store and authentication.",
    "crea/migra el esquema si hace falta (la tabla la define migrations/)":
        "creates/migrates the schema if needed (migrations/ defines the table)",
    "esquema definido en migrations/": "schema defined in migrations/",
    "prefijo: nunca choca con las tablas de autenticación (la tabla la crea migrations/)":
        "prefix: never clashes with the authentication tables (migrations/ creates the table)",
    "prefijo: nunca choca con las tablas de autenticación": "prefix: never clashes with the authentication tables",
    "Migraciones de esquema SQLite (sin dependencias).": "SQLite schema migrations (no dependencies).",
    "Migraciones de esquema SQLite (node:sqlite, sin dependencias).": "SQLite schema migrations (node:sqlite, no dependencies).",
    "Cada archivo migrations/NNNN_*.sql se aplica una vez, en orden y dentro de una":
        "Each migrations/NNNN_*.sql file is applied once, in order and inside a",
    "transacción. Se guarda su huella SHA-256: si se edita una migración ya aplicada,":
        "transaction. Its SHA-256 fingerprint is stored: if an applied migration is edited,",
    "se avisa (crea una nueva en lugar de modificar la antigua).":
        "you are warned (create a new one instead of changing the old one).",
    "Cada migrations/NNNN_*.sql se aplica una vez, en orden y en una transacción; se guarda su":
        "Each migrations/NNNN_*.sql is applied once, in order and in a transaction; its SHA-256",
    "huella SHA-256 y se avisa si alguien edita una migración ya aplicada.":
        "fingerprint is stored and you are warned if someone edits an applied migration.",
    "python -m app.migrate            aplica las pendientes": "python -m app.migrate            applies pending ones",
    "python -m app.migrate new NOMBRE crea migrations/NNNN_nombre.sql vacía":
        "python -m app.migrate new NAME   creates an empty migrations/NNNN_name.sql",
    "python -m app.migrate status     lista aplicadas y pendientes": "python -m app.migrate status     lists applied and pending",
    "node src/migrate.js            aplica las pendientes": "node src/migrate.js            applies pending ones",
    "node src/migrate.js new NOMBRE crea migrations/NNNN_nombre.sql vacía":
        "node src/migrate.js new NAME   creates an empty migrations/NNNN_name.sql",
    "node src/migrate.js status     lista aplicadas y pendientes": "node src/migrate.js status     lists applied and pending",
    "Sin depender de CRLF/LF (git autocrlf en Windows no debe parecer una edición).":
        "Independent of CRLF/LF (git autocrlf on Windows must not look like an edit).",
    "Sin await de nivel superior: store.js importa este módulo y se bloquearían mutuamente.":
        "No top-level await: store.js imports this module and they would block each other.",
    "Base de datos temporal para las pruebas (no toca data/app.db).": "Temporary database for the tests (data/app.db is untouched).",
    "Una migración con error no deja nada a medias.": "A failing migration leaves nothing half-applied.",
    "Una migración nueva se aplica una sola vez y añade la columna.": "A new migration is applied only once and adds the column.",
    # ── Servidores web (fastapi, express, django, go, next, vite) ──
    "/docs (Swagger) carga recursos de un CDN: se le deja su propia política.":
        "/docs (Swagger) loads resources from a CDN: it keeps its own policy.",
    "Frontend estático (debe ir lo último: captura el resto de rutas).":
        "Static frontend (must go last: it catches the remaining routes).",
    "cabeceras de seguridad en todas las respuestas": "security headers on every response",
    "Errores (JSON mal formado, cuerpo demasiado grande…): JSON sin traza, nunca la página HTML de Express.":
        "Errors (malformed JSON, body too large…): JSON without a trace, never Express's HTML page.",
    "Validación mínima de entrada (sin dependencias).": "Minimal input validation (no dependencies).",
    "Cabeceras de seguridad (generado por Eolfi). La CSP solo en producción: «next dev» usa eval.":
        "Security headers (generated by Eolfi). CSP only in production: \"next dev\" uses eval.",
    "Cabeceras de seguridad (generado por Eolfi): CSP en el HTML del build y cabeceras en «vite preview».":
        "Security headers (generated by Eolfi): CSP in the build's HTML and headers in \"vite preview\".",
    "Cliente de la API del proyecto (el backend escucha en :8000; Vite hace de proxy de /api).":
        "Client for the project's API (the backend listens on :8000; Vite proxies /api).",
    "Prueba de extremo a extremo: arranca `next start` (requiere `npm run build` antes).":
        "End-to-end test: starts `next start` (requires `npm run build` first).",
    "API JSON de demostración: sin sesión ni cookies, por eso se exime de CSRF.":
        "Demo JSON API: no session or cookies, so it is exempt from CSRF.",
    "Añade autenticación (tokens) antes de exponerla.": "Add authentication (tokens) before exposing it.",
    "Cabeceras y cookies seguras siempre; HTTPS obligatorio en producción (detrás de un proxy TLS define":
        "Secure headers and cookies always; HTTPS required in production (behind a TLS proxy set",
    "DJANGO_SECURE_PROXY=1 para confiar en X-Forwarded-Proto).": "DJANGO_SECURE_PROXY=1 to trust X-Forwarded-Proto).",
    "En producción una clave conocida permitiría falsificar sesiones y entrar al admin.":
        "In production a known key would allow forging sessions and entering the admin.",
    "seguro por defecto (manage.py activa la depuración)": "secure by default (manage.py turns debugging on)",
    "manage.py es la herramienta de desarrollo (runserver, test, check): modo depuración salvo que se":
        "manage.py is the development tool (runserver, test, check): debug mode unless",
    "diga otra cosa. El servidor de producción (wsgi/asgi, gunicorn) arranca SIN depuración.":
        "told otherwise. The production server (wsgi/asgi, gunicorn) starts WITHOUT debugging.",
    "Textos de ejemplo: cámbialos por los tuyos.": "Sample texts: replace them with your own.",
    "Servidor de": "Server for",
    "(generado por Eolfi): API REST y web propia, solo con la biblioteca estándar de Go.":
        "(generated by Eolfi): REST API and its own web, using only Go's standard library.",
    "appTitle es el nombre de la aplicación.": "appTitle is the application's name.",
    "smoke arranca el servidor en un puerto libre de 127.0.0.1, se pide /api/health y la portada y se apaga.":
        "smoke starts the server on a free 127.0.0.1 port, requests /api/health and the home page, and shuts down.",
    "Item es un elemento de un recurso de la API.": "Item is an item of an API resource.",
    "Store guarda los elementos de un recurso en memoria (se pierden al reiniciar), seguro entre goroutines.":
        "Store keeps a resource's items in memory (lost on restart), safe across goroutines.",
    "Recursos de la API detectados en las fuentes analizadas.": "API resources detected in the analyzed sources.",
    "64 KiB por petición": "64 KiB per request",
    "Una ruta de la API que no existe responde JSON, no la web.": "An API route that does not exist answers JSON, not the web.",
    "readItem valida el cuerpo: name obligatorio (1-200 caracteres) y description texto opcional (máx. 2000).":
        "readItem validates the body: required name (1-200 characters) and optional description text (max. 2000).",
    # ── Sitio estático y PWA ──
    "Servidor estático mínimo (sin dependencias): node scripts/serve.mjs":
        "Minimal static server (no dependencies): node scripts/serve.mjs",
    "Service worker de la PWA (generado por Eolfi). Solo guarda en caché los archivos PROPIOS del sitio (mismo":
        "PWA service worker (generated by Eolfi). It only caches the site's OWN files (same",
    "origen, GET): nada de terceros ni de la API. Cambia VERSION al publicar archivos nuevos para renovar la caché.":
        "origin, GET): nothing from third parties or the API. Change VERSION when publishing new files to renew the cache.",
    "Red primero (contenido al día) y caché si no hay conexión.": "Network first (up-to-date content) and cache when offline.",
    "Comportamiento del sitio: tema claro/oscuro, formulario y datos de la API.":
        "Site behavior: light/dark theme, form and API data.",
    "PWA (destino static): registra el service worker si la página enlaza un manifiesto y se sirve por HTTP(S).":
        "PWA (static target): registers the service worker if the page links a manifest and is served over HTTP(S).",
    "almacenamiento bloqueado": "storage blocked",
    "sin almacenamiento": "no storage",
    "sin persistencia": "no persistence",
    "sin PWA": "no PWA",
    "textContent: nunca HTML de la API": "textContent: never HTML from the API",
    "puntos de corte (en las media queries van como valor literal)": "breakpoints (written as literal values in media queries)",
    "Cabecera y pie": "Header and footer",
    "Botones": "Buttons",
    "Secciones": "Sections",
    # ── Frontends (react, vue, svelte, expo) ──
    "Enrutador mínimo: History API, sin dependencias.": "Minimal router: History API, no dependencies.",
    "Enrutador mínimo con runas de Svelte 5 (sin dependencias).": "Minimal router with Svelte 5 runes (no dependencies).",
    "Páginas generadas a partir de las fuentes analizadas (navegación por pestañas, sin dependencias).":
        "Pages generated from the analyzed sources (tab navigation, no dependencies).",
    "Campos visibles en las secciones de lista: [principal, secundario, terciario].":
        "Fields shown in list sections: [primary, secondary, tertiary].",
    "Paleta aprendida de las fuentes (modo claro) y variante oscura.": "Palette learned from the sources (light mode) and dark variant.",
    "API del backend generado con Eolfi (FastAPI/Express). Configura EXPO_PUBLIC_API_URL,":
        "API of the backend generated with Eolfi (FastAPI/Express). Set EXPO_PUBLIC_API_URL,",
    "p. ej. EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 (en el móvil, la IP de tu equipo).":
        "e.g. EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 (on the phone, your computer's IP).",
    "Nota: el APK de producción y el de «preview» bloquean http:// en claro: usa https:// para":
        "Note: the production and \"preview\" APKs block cleartext http://: use https:// for",
    "EXPO_PUBLIC_API_URL fuera de desarrollo (o el plugin expo-build-properties con usesCleartextTraffic).":
        "EXPO_PUBLIC_API_URL outside development (or the expo-build-properties plugin with usesCleartextTraffic).",
    # ── Escritorio (Electron, Tauri, .NET) ──
    "Proceso principal de Electron: ventana endurecida que carga la interfaz desde disco.":
        "Electron main process: hardened window that loads the interface from disk.",
    "Una sola instancia: si se abre otra, se enfoca la existente.": "Single instance: opening another focuses the existing one.",
    "Permisos del sistema (cámara, micrófono, ubicación, notificaciones…): denegados salvo que los añadas.":
        "System permissions (camera, microphone, location, notifications…): denied unless you add them.",
    "Nada de navegar fuera de la app: los enlaces https externos van al navegador del sistema.":
        "No navigating away from the app: external https links open in the system browser.",
    "Protocolo propio en lugar de file://: la página no obtiene los permisos extra de file:// (leer otros":
        "Custom protocol instead of file://: the page does not get file://'s extra permissions (reading other",
    "archivos del disco) y solo se sirve lo que hay dentro de renderer/.":
        "files on disk) and only what is inside renderer/ is served.",
    "nada fuera de renderer/ (../, otras unidades…)": "nothing outside renderer/ (../, other drives…)",
    "prueba de humo: abre, comprueba y sale": "smoke test: opens, checks and exits",
    "en macOS la app sigue en el Dock": "on macOS the app stays in the Dock",
    "Puente mínimo y explícito entre la interfaz y Electron (nada de Node en la página).":
        "Minimal, explicit bridge between the interface and Electron (no Node in the page).",
    "Detalles de escritorio: marca la plataforma para estilos específicos (p. ej. barra de macOS).":
        "Desktop details: marks the platform for specific styles (e.g. the macOS bar).",
    "Fusibles de Electron (se aplican al empaquetar, electron-builder afterPack): el ejecutable final no":
        "Electron fuses (applied when packaging, electron-builder afterPack): the final executable cannot",
    "se puede usar como un Node.js cualquiera (ELECTRON_RUN_AS_NODE, NODE_OPTIONS, --inspect) y solo carga":
        "be used as a plain Node.js (ELECTRON_RUN_AS_NODE, NODE_OPTIONS, --inspect) and only loads",
    "la app empaquetada.": "the packaged app.",
    "Prueba de humo real: arranca Electron sin mostrar la ventana, comprueba que la interfaz":
        "Real smoke test: starts Electron without showing the window, checks that the interface",
    "carga (h1, puente seguro y sin Node en la página) y sale con 0 o 1.":
        "loads (h1, safe bridge and no Node in the page) and exits with 0 or 1.",
    "ruta al ejecutable de Electron": "path to the Electron executable",
    "contenedores CI sin espacios de nombres": "CI containers without namespaces",
    "Pruebas sin abrir ventanas: seguridad de la configuración y estructura de la interfaz.":
        "Tests without opening windows: configuration security and interface structure.",
    "Pruebas sin compilar: seguridad de la configuración e interfaz.": "Tests without compiling: configuration security and interface.",
    "Punto de entrada de la app de escritorio (Tauri 2).": "Entry point of the desktop app (Tauri 2).",
    "En Windows, sin consola en la versión de producción.": "On Windows, no console in the production build.",
    "Prueba de humo: arranca, espera a que la interfaz cargue y sale con código 0.":
        "Smoke test: starts, waits for the interface to load and exits with code 0.",
    "Prueba de humo: la ventana se abre con su contenido y la app sale con código 0.":
        "Smoke test: the window opens with its content and the app exits with code 0.",
    "Textos de ejemplo de la app (cámbialos por los tuyos). Sin lógica de interfaz: se prueba aparte.":
        "The app's sample texts (replace them with your own). No interface logic: tested separately.",
    "claro/oscuro según el sistema": "light/dark following the system",
    # ── Línea de órdenes (cli y rust) ──
    "Ejecutable único para este sistema (Windows .exe, macOS o Linux) con PyInstaller.":
        "Single executable for this system (Windows .exe, macOS or Linux) with PyInstaller.",
    "redirigida a archivo en Windows: UTF-8, no la página local": "redirected to a file on Windows: UTF-8, not the local code page",
    "Windows: %APPDATA%; macOS: ~/Library/Application Support; Linux: $XDG_DATA_HOME o ~/.local/share.":
        "Windows: %APPDATA%; macOS: ~/Library/Application Support; Linux: $XDG_DATA_HOME or ~/.local/share.",
    "Toda la lógica está aquí para poder probarla; `main.rs` solo pasa los argumentos y el código de salida.":
        "All the logic lives here so it can be tested; `main.rs` only passes the arguments and the exit code.",
    "Punto de entrada: lee los argumentos (también si no son UTF-8) y sale con el código de `run`.":
        "Entry point: reads the arguments (even if they are not UTF-8) and exits with `run`'s code.",
    "Pruebas del ejecutable de verdad, con una carpeta de datos temporal por prueba.":
        "Tests of the real executable, with a temporary data folder per test.",
    "Ejecuta la orden y devuelve el código de salida: 0 bien, 1 no existe o error de datos, 2 uso incorrecto.":
        "Runs the command and returns the exit code: 0 ok, 1 not found or data error, 2 wrong usage.",
    "Nombre de un elemento: sin espacios a los lados y de 1 a 200 caracteres.":
        "Name of an item: no surrounding spaces and 1 to 200 characters.",
    "caracteres, no bytes": "characters, not bytes",
    "Una lista de elementos por recurso en un archivo JSON; escritura atómica (temporal + renombrar).":
        "One list of items per resource in a JSON file; atomic writes (temporary + rename).",
    "Variable de entorno que cambia la carpeta de datos (las pruebas la usan).":
        "Environment variable that changes the data folder (the tests use it).",
}
_repetidas = {k for k in COMENTARIOS if k in EN and EN[k] != COMENTARIOS[k]}
assert not _repetidas, _repetidas
EN.update(COMENTARIOS)


@lru_cache(maxsize=None)
def _patron(idioma: str) -> re.Pattern[str]:
    claves = sorted(EN, key=len, reverse=True)
    return re.compile("|".join(rf"(?<!\w){re.escape(k)}(?!\w)" for k in claves))


def traducir(texto: str, idioma: str = "es") -> str:
    """Devuelve ``texto`` en ``idioma``. En castellano (o idioma desconocido) no cambia nada."""
    if idioma != "en":
        return texto
    return _patron(idioma).sub(lambda m: EN[m.group(0)], texto)


def idioma_de(spec: dict) -> str:
    idioma = str(spec.get("idioma") or "es")
    if idioma not in IDIOMAS:
        raise ValueError(f"spec: idioma no admitido: {idioma!r} (usa {', '.join(IDIOMAS)})")
    return idioma
