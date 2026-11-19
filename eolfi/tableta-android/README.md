# Eolfi Tableta (Android 4.1, API 16)

Satélite de voz y terminal del chat de Eolas para la Galaxy Tab 2 (GT-P3100). La app usa el micrófono y el altavoz
de la tableta, y el trabajo pesado (whisper, Gemma, voz) lo hace el panel de Eolfi en el PC, por la red local.

- Vínculo: el código de 6 cifras del panel (Proveedores → Vincular VS Code) canjeado con `"scope": "tableta"`. Ese
  token solo abre `/api/tableta/*`, `/api/voz/transcribir` y `/api/voz/hablar` (ver `eolfi/tableta.py`).
- HTTPS con huella SHA-256 fijada (la primera se acepta al vincular y se muestra para compararla). Android 4.1 solo
  negocia ECDHE-AES-CBC-SHA en TLS 1.2: arranca el panel con `eolfi serve ... --cert C --key K --tls-legado`.
- Semidúplex: no graba mientras suena la respuesta ni mientras Eolas contesta.
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
