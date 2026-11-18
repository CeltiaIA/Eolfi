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
