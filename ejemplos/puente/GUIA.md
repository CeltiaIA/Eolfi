# Guía: el puente de chats web (DeepSeek, Gemini, Meta AI…)

El puente deja que Eolfi use **tus** sesiones de los chats web como proveedor de IA (`--provider meta-web`,
`deepseek-web`, `gemini-web`…). Tiene dos partes:

- **En tu equipo, con tus cuentas (laboratorio):** pasos A y B. No se pueden ejecutar en la CI.
- **Con un chat simulado (CI):** pasos C y D. Usan la pasarela **real** del puente (`eolfi/bridge/server.mjs`) con un
  adaptador que responde lo que hay en `respuestas-simuladas.json`. `tests/test_guia_puente.py` ejecuta estos pasos.

> Automatizar estas webs puede ir contra sus condiciones de uso: úsalo con tu cuenta y bajo tu responsabilidad.
> **Cada envío de Eolfi pide tu permiso** en un diálogo del puente; lo que escribes tú en el panel no lo pide.

## A. Iniciar sesión (una vez)

```bash
python -m eolfi bridge --login        # abre el perfil del puente en tu navegador, SIN control remoto
```

Entra en cada chat y cierra la ventana. Google y otros rechazan el inicio de sesión en un navegador controlado por
software, por eso este paso va sin control.

**Aceptación:** al arrancar el puente (paso B), su estado marca cada chat como «con sesión».

## B. Arrancar el puente y usarlo

```bash
python -m eolfi bridge                 # tu navegador (Chrome, Edge…) controlado por una tubería privada
python -m eolfi assist PROYECTO --brief "Qué quieres cambiar" --provider meta-web
```

**Aceptación:**

- El puente escucha solo en `127.0.0.1`, con dos credenciales en `~/.eolfi/bridge.json`: la de Eolfi y la del panel.
- Cada envío de Eolfi abre un diálogo de permiso. Si lo deniegas, no se envía nada y el proyecto no cambia.
- Las ventanas solo navegan por el origen de su chat y por sus dominios de inicio de sesión; los permisos que pidan
  las webs (cámara, micrófono, ubicación, notificaciones…) se deniegan por defecto.
- Con `--engine electron` (o sin navegador instalado) el puente avisa de que las sesiones se guardan sin el cifrado
  de cookies de Electron. El motor recomendado es tu navegador.

## C. Un cambio de principio a fin con un chat simulado

```bash
# en otra terminal, desde la raíz del repositorio: la pasarela real con el chat simulado
node tests/fake_bridge.mjs ejemplos/puente/bridge.json ejemplos/puente/respuestas-simuladas.json

cd ejemplos/puente
python -m eolfi --db guia.db create --from ../web-y-repo/sitio --out proyecto --name "Notas"
EOLFI_BRIDGE_FILE=bridge.json python -m eolfi --db guia.db assist proyecto --brief "Destaca las notas nuevas" --provider meta-web
```

(En PowerShell: `$env:EOLFI_BRIDGE_FILE="bridge.json"` antes del `assist`.)

**Aceptación:**

- `assist` devuelve `ok: true`, `provider: meta-web`, `files_changed: ["css/ofertas.css"]` y `restored: false`.
- El chat recibió **una** petición de su conversación, que empieza con las instrucciones para la IA
  («Eres un ingeniero…») y no pasa de 31.000 caracteres (el límite de los chats es 32.000).
- La verificación del proyecto (`node --test`) se repite tras el cambio, en una carpeta personal temporal.

Con `EOLFI_FAKE_BRIDGE_DENY=1` el chat simulado se comporta como si denegaras el permiso: `assist` termina con
código 1, explica «El usuario denegó el envío en el puente» y el proyecto queda igual.

## D. Las protecciones de la pasarela

**Aceptación** (la prueba las comprueba con peticiones HTTP a la pasarela):

| Petición | Respuesta |
|---|---|
| Sin credencial o con una inválida | 401 |
| Con otra cabecera `Host` (rebinding de DNS) | 421 |
| Ver o controlar la ventana (`/v1/screen`) con la credencial de Eolfi | 403: solo el panel puede |
| `/v1/status` con la credencial de Eolfi | 200 y el estado de cada chat |
