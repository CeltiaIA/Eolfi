# Eolfi Tableta (Android 4.1, API 16, hasta Android 14)

Desde la 0.3.0 (20/11/2026) el mismo APK sirve también en móviles modernos (probado en un Redmi Note 12R Pro con
Android 14): `targetSdkVersion` 28, porque Android 14 no instala apps con `targetSdk` < 23. 28 evita el
almacenamiento con ámbito y mantiene válida la firma v1. En Android 6+ el micrófono se pide la primera vez que se
mantiene «Mantén para hablar» (por reflexión: la app sigue compilándose contra la API 16). Fuera de la red local, la
app llega a `eolfi tableta-puente` por una VPN privada (Tailscale) usando la IP 100.x del PC; no se abre ningún puerto
del router.

Desde la 0.4.0 (21/11/2026) se puede dirigir a Eolas mientras trabaja: lo que escribes o dictas con «Añadir» entra
en el mismo hilo antes del siguiente paso (`POST /api/tableta/chat/mensaje`), y **Parar** lo corta en el acto. Un
corte pasajero de wifi o datos ya no abandona la respuesta: la consulta se reintenta hasta 10 veces.

Satélite de voz y terminal del chat de Eolas para la Galaxy Tab 2 (GT-P3100). La app usa el micrófono y el altavoz
de la tableta, y el trabajo pesado (whisper, Gemma, voz) lo hace el panel de Eolfi en el PC, por la red local.

- Vínculo: el código de 6 cifras del panel (Proveedores → Vincular VS Code) canjeado con `"scope": "tableta"`. Ese
  token solo abre `/api/tableta/*`, `/api/voz/transcribir` y `/api/voz/hablar` (ver `eolfi/tableta.py`).
- HTTPS con huella SHA-256 fijada (la primera se acepta al vincular y se muestra para compararla). Android 4.1 solo
  negocia ECDHE-AES-CBC-SHA en TLS 1.2: arranca el panel con `eolfi serve ... --cert C --key K --tls-legado`.
- Semidúplex: no graba mientras suena la respuesta ni mientras Eolas contesta.
- Dictado: por defecto el texto aparece en la caja para revisarlo; «Enviar al soltar» lo manda directo. Si Eolas no
  responde (por ejemplo, ocupado con otra petición), el texto vuelve a la caja.
- «Nueva conversación» empieza un contexto separado; «Historial» permite retomar uno anterior. La selección,
  los mensajes y los borradores sobreviven al cierre de la app. Durante una respuesta, grabación o transcripción
  no se cambia de conversación. El modelo recibe como máximo los últimos 12 mensajes, como antes.
- Historial limitado a **8 MiB** de archivo: primero se retiran las conversaciones más antiguas, conservando la
  activa; si la activa sola supera el presupuesto, se conserva su parte más reciente. La app avisa al recortar.
  Se usa preferentemente la tarjeta extra (`SECONDARY_STORAGE`, en la GT-P3100 `extSdCard`), después el
  almacenamiento externo de la app y, si no están disponibles, la memoria interna. La ubicación se muestra bajo
  los botones. La SD conserva texto sin cifrar: el archivo no incluye el token de vínculo. Android 4.1 necesita
  `WRITE_EXTERNAL_STORAGE` para escribir allí. Si se retira la tarjeta durante el guardado, se avisa del fallo.
  Durante una sustitución puede existir una copia temporal adicional de hasta 8 MiB; se retira al completarla.
- Para recuperar expresamente un chat anterior a la versión 0.2, se puede colocar su texto en
  `Download/eolfi-recuperar-chat.txt` y abrir la actividad con `--ez recuperar_chat_archivo true`. La app pide
  confirmar, admite como máximo 1 MiB, no envía nada al modelo y no acepta mensajes de sistema. Una copia de
  recuperación no forma parte del límite del historial y debe revisarse al terminar la migración.
- Sin Google ni Samsung: solo framework AOSP, JDK y `org.json`; ni Play Services, ni cuentas, ni TTS o reconocedor
  del sistema. Dictado y voz los pone el panel. Lo vigila `tests/test_tableta.py::test_app_android_sin_google_ni_samsung`.

## Construir sin Android SDK

```bash
python construir.py --comprobar-api CARPETA_CON_core.odex_framework.odex_framework2.odex
```

Usa el JDK (javac), D8 del jar de jadx (`EOLFI_D8_JAR`) y aapt2 del jar de apktool (`EOLFI_APKTOOL_JAR`). Firma v1
con SHA-1 y PKCS#7 sin atributos firmados (lo único que acepta Android < 4.3); la clave queda en `~/.eolfi/tableta/`.
Salida en `build/` (ignorada por Git) con `construccion.json` (SHA-256 del APK y de las herramientas).

## Pruebas

`python -m pytest tests/test_tableta.py tests/test_tableta_android.py`: unidad en la JVM (`pruebas/PruebasJvm.java`),
cliente Java contra el panel real por HTTPS y construcción del APK si las herramientas existen.
Informe y smoke en la tableta: `D:\Eolfi-objetivos\informes\tablet-gtp3100\INFORME-GT-P3100.md`.
