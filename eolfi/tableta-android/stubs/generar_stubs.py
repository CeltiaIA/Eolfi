"""Genera los «stubs» de compilación de la API de Android 16 que usa la app (solo firmas).

No sustituyen a android.jar: sirven para que javac compile sin descargar el SDK. Reglas:
- los métodos lanzan RuntimeException("Stub!") — nunca se ejecutan: en la tableta se usa el framework real;
- las constantes llevan el valor real de la API (javac las incrusta en el código de la app);
- los campos de Build NO son constantes de compilación (se inicializan con una llamada), como en Android.
Tras cambiar la app, `construir.py --comprobar-api` compara cada referencia con el framework sacado de la tableta.
"""
from __future__ import annotations

import sys
from pathlib import Path

X = '{ throw new RuntimeException("Stub!"); }'

STUBS = {
    "android/content/Context.java": """package android.content;
public abstract class Context {
    public static final int MODE_PRIVATE = 0;
    public abstract SharedPreferences getSharedPreferences(String name, int mode);
    public java.io.File getFilesDir() STUB
    public java.io.File getExternalFilesDir(String type) STUB
}""",
    "android/content/Intent.java": """package android.content;
public class Intent {
    public boolean getBooleanExtra(String n, boolean d) STUB
    public String getStringExtra(String n) STUB
    public void removeExtra(String n) STUB
}""",
    "android/content/DialogInterface.java": """package android.content;
public interface DialogInterface {
    interface OnClickListener { void onClick(DialogInterface d, int which); }
}""",
    "android/app/AlertDialog.java": """package android.app;
import android.content.Context; import android.content.DialogInterface;
public class AlertDialog {
    public static class Builder {
        public Builder(Context c) STUB
        public Builder setTitle(CharSequence t) STUB
        public Builder setMessage(CharSequence t) STUB
        public Builder setItems(CharSequence[] items, DialogInterface.OnClickListener l) STUB
        public Builder setPositiveButton(CharSequence t, DialogInterface.OnClickListener l) STUB
        public Builder setNegativeButton(CharSequence t, DialogInterface.OnClickListener l) STUB
        public AlertDialog show() STUB
    }
}""",
    "android/content/SharedPreferences.java": """package android.content;
public interface SharedPreferences {
    String getString(String k, String d);
    boolean getBoolean(String k, boolean d);
    Editor edit();
    interface Editor {
        Editor putString(String k, String v);
        Editor putBoolean(String k, boolean v);
        boolean commit();
    }
}""",
    "android/app/Activity.java": """package android.app;
import android.content.*; import android.os.Bundle; import android.view.View;
public class Activity extends Context {
    protected void onCreate(Bundle b) STUB
    protected void onPause() STUB
    public void setContentView(View v) STUB
    public SharedPreferences getSharedPreferences(String n, int m) STUB
    public Intent getIntent() STUB
    public final void runOnUiThread(Runnable r) STUB
}""",
    "android/os/Bundle.java": "package android.os;\npublic final class Bundle {}",
    "android/os/Environment.java": """package android.os;
public final class Environment { public static java.io.File getExternalStorageDirectory() STUB }""",
    "android/os/Build.java": """package android.os;
public class Build {
    private static String s() { return null; }
    public static final String MODEL = s(), DISPLAY = s(), BOARD = s(), HARDWARE = s(), CPU_ABI = s();
    public static class VERSION {
        private static int i() { return 0; }
        public static final int SDK_INT = i();
        public static final String RELEASE = s();
    }
}""",
    "android/text/Editable.java": "package android.text;\npublic interface Editable extends CharSequence {}",
    "android/text/InputType.java": """package android.text;
public interface InputType {
    int TYPE_CLASS_TEXT = 1, TYPE_CLASS_NUMBER = 2, TYPE_TEXT_VARIATION_URI = 0x10, TYPE_TEXT_FLAG_MULTI_LINE = 0x20000;
}""",
    "android/util/Log.java": """package android.util;
public final class Log {
    public static int i(String t, String m) STUB
    public static int w(String t, String m) STUB
}""",
    "android/view/MotionEvent.java": """package android.view;
public final class MotionEvent {
    public static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_CANCEL = 3;
    public final int getAction() STUB
}""",
    "android/view/View.java": """package android.view;
import android.content.Context;
public class View {
    public static final int FOCUS_DOWN = 130;
    public View(Context c) STUB
    public interface OnClickListener { void onClick(View v); }
    public interface OnTouchListener { boolean onTouch(View v, MotionEvent e); }
    public void setPadding(int l, int t, int r, int b) STUB
    public void setBackgroundColor(int c) STUB
    public void setOnClickListener(OnClickListener l) STUB
    public void setOnTouchListener(OnTouchListener l) STUB
    public boolean post(Runnable r) STUB
}""",
    "android/view/ViewGroup.java": """package android.view;
import android.content.Context;
public abstract class ViewGroup extends View {
    public ViewGroup(Context c) { super(c); }
    public void addView(View v) STUB
    public void addView(View v, LayoutParams p) STUB
    public static class LayoutParams {
        public static final int MATCH_PARENT = -1, WRAP_CONTENT = -2;
        public LayoutParams(int w, int h) STUB
    }
    public static class MarginLayoutParams extends LayoutParams {
        public MarginLayoutParams(int w, int h) { super(w, h); }
    }
}""",
    "android/widget/LinearLayout.java": """package android.widget;
import android.content.Context; import android.view.ViewGroup;
public class LinearLayout extends ViewGroup {
    public static final int HORIZONTAL = 0, VERTICAL = 1;
    public LinearLayout(Context c) { super(c); }
    public void setOrientation(int o) STUB
    public static class LayoutParams extends ViewGroup.MarginLayoutParams {
        public LayoutParams(int w, int h, float weight) { super(w, h); }
    }
}""",
    "android/widget/FrameLayout.java": """package android.widget;
import android.content.Context; import android.view.ViewGroup;
public class FrameLayout extends ViewGroup { public FrameLayout(Context c) { super(c); } }""",
    "android/widget/ScrollView.java": """package android.widget;
import android.content.Context;
public class ScrollView extends FrameLayout {
    public ScrollView(Context c) { super(c); }
    public boolean fullScroll(int d) STUB
}""",
    "android/widget/TextView.java": """package android.widget;
import android.content.Context; import android.view.View;
public class TextView extends View {
    public TextView(Context c) { super(c); }
    public final void setText(CharSequence t) STUB
    public final void setHint(CharSequence t) STUB
    public void setTextSize(float s) STUB
    public void setTextColor(int c) STUB
    public final void append(CharSequence t) STUB
    public int length() STUB
    public void setTextIsSelectable(boolean s) STUB
    public void setInputType(int t) STUB
    public CharSequence getText() STUB
}""",
    "android/widget/EditText.java": """package android.widget;
import android.content.Context; import android.text.Editable;
public class EditText extends TextView {
    public EditText(Context c) { super(c); }
    @Override public Editable getText() STUB
    public void setSelection(int index) {}
}""",
    "android/widget/Button.java": """package android.widget;
import android.content.Context;
public class Button extends TextView { public Button(Context c) { super(c); } }""",
    "android/widget/CompoundButton.java": """package android.widget;
import android.content.Context;
public abstract class CompoundButton extends Button {
    public CompoundButton(Context c) { super(c); }
    public void setChecked(boolean b) STUB
    public boolean isChecked() STUB
}""",
    "android/widget/CheckBox.java": """package android.widget;
import android.content.Context;
public class CheckBox extends CompoundButton { public CheckBox(Context c) { super(c); } }""",
    "android/webkit/WebSettings.java": """package android.webkit;
public abstract class WebSettings { public String getUserAgentString() STUB }""",
    "android/webkit/WebView.java": """package android.webkit;
import android.content.Context; import android.view.ViewGroup;
public class WebView extends ViewGroup {
    public WebView(Context c) { super(c); }
    public WebSettings getSettings() STUB
    public void destroy() STUB
}""",
    "android/media/AudioFormat.java": """package android.media;
public class AudioFormat {
    public static final int ENCODING_PCM_16BIT = 2, CHANNEL_IN_MONO = 16, CHANNEL_OUT_MONO = 4, CHANNEL_OUT_STEREO = 12;
}""",
    "android/media/AudioManager.java": "package android.media;\npublic class AudioManager { public static final int STREAM_MUSIC = 3; }",
    "android/media/MediaRecorder.java": """package android.media;
public class MediaRecorder {
    public final class AudioSource { public static final int MIC = 1, VOICE_RECOGNITION = 6; private AudioSource() {} }
}""",
    "android/media/AudioRecord.java": """package android.media;
public class AudioRecord {
    public static final int STATE_INITIALIZED = 1;
    public AudioRecord(int src, int hz, int ch, int enc, int buf) STUB
    public static int getMinBufferSize(int hz, int ch, int enc) STUB
    public int getState() STUB
    public void startRecording() STUB
    public int read(short[] a, int o, int n) STUB
    public void stop() STUB
    public void release() STUB
}""",
    "android/media/AudioTrack.java": """package android.media;
public class AudioTrack {
    public static final int MODE_STATIC = 0, MODE_STREAM = 1, STATE_INITIALIZED = 1;
    public AudioTrack(int stream, int hz, int ch, int enc, int buf, int mode) STUB
    public static int getMinBufferSize(int hz, int ch, int enc) STUB
    public static int getNativeOutputSampleRate(int stream) STUB
    public int getState() STUB
    public void play() STUB
    public int write(byte[] a, int o, int n) STUB
    public void stop() STUB
    public void release() STUB
}""",
    "org/json/JSONException.java": """package org.json;
public class JSONException extends Exception { public JSONException(String s) { super(s); } }""",
    "org/json/JSONArray.java": """package org.json;
public class JSONArray {
    public JSONArray() STUB
    public int length() STUB
    public String getString(int i) throws JSONException STUB
    public String optString(int i) STUB
    public JSONObject getJSONObject(int i) throws JSONException STUB
    public JSONArray put(Object o) STUB
}""",
    "org/json/JSONObject.java": """package org.json;
public class JSONObject {
    public JSONObject() STUB
    public JSONObject(String s) throws JSONException STUB
    public String optString(String k) STUB
    public String optString(String k, String d) STUB
    public String getString(String k) throws JSONException STUB
    public JSONArray optJSONArray(String k) STUB
    public JSONObject put(String k, Object v) throws JSONException STUB
    public JSONObject put(String k, int v) throws JSONException STUB
    public JSONObject put(String k, long v) throws JSONException STUB
    public JSONObject put(String k, boolean v) throws JSONException STUB
    public JSONArray names() STUB
    public Object opt(String k) STUB
}""",
}


def generar(destino: Path) -> list[Path]:
    out = []
    for rel, src in STUBS.items():
        p = destino / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src.replace("STUB", X) + "\n", encoding="utf-8")
        out.append(p)
    return out


if __name__ == "__main__":
    print(len(generar(Path(sys.argv[1]))))
