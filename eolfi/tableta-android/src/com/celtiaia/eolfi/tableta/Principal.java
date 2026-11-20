package com.celtiaia.eolfi.tableta;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.text.InputType;
import android.util.Log;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.io.File;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * Eolfi Tableta: satélite de voz y terminal del chat de Eolas para la Galaxy Tab 2 (Android 4.1, API 16).
 * Interfaz hecha en código (sin recursos), un solo Activity, todo el trabajo de red fuera del hilo de la interfaz.
 */
public class Principal extends Activity {
    static final String TAG = "EolfiTableta";
    private static final int MAX_GRABACION_S = 30;

    private SharedPreferences prefs;
    private EditText campoPanel, campoCodigo, campoMensaje;
    private TextView estado, conversacion;
    private TextView tituloConversacion;
    private ScrollView desplazable;
    private CheckBox leer, directo;
    private Button hablar;
    private final Audio audio = new Audio();
    private Conversaciones conversaciones;
    private boolean historialProtegido;
    private ArchivoConversaciones archivoConversaciones;
    private String lugarHistorial;
    private volatile boolean ocupado;
    /** Semidúplex: mientras suena la respuesta no se graba (el micrófono se oiría a sí mismo y se reenviaría). */
    private volatile boolean hablando;
    private volatile boolean grabando;
    private volatile boolean transcribiendo;
    private int sesionGrabacion;

    @Override
    protected void onCreate(Bundle guardado) {
        super.onCreate(guardado);
        System.setProperty("http.keepAlive", "false");   // el HttpURLConnection de 4.1 reutiliza mal las conexiones
        prefs = getSharedPreferences("eolfi", MODE_PRIVATE);
        archivoConversaciones = new ArchivoConversaciones(carpetaHistorial());
        try {
            conversaciones = Conversaciones.cargar(archivoConversaciones.existe() ? archivoConversaciones.leer()
                    : prefs.getString("conversaciones_v1", null));
        } catch (Exception e) {
            conversaciones = Conversaciones.cargar(null);
            historialProtegido = true; // Conservar el original ilegible: nunca sustituirlo silenciosamente.
        }
        setContentView(interfaz());
        pintarEstado();
        mostrarConversacion();
        if (historialProtegido) decir("Aviso", "No se pudo leer el historial guardado; se conserva sin sobrescribirlo.");
        if (!conversaciones.activa().pendiente.isEmpty()) {
            devolverACaja(conversaciones.activa().pendiente);
            decir("Aviso", "Quedó un mensaje pendiente. Revisa Trabajos antes de reenviarlo.");
        }
        recuperarChatAnterior();
        if (getIntent() != null && getIntent().getBooleanExtra("diagnostico", false)) diagnostico();
    }

    // ── Interfaz ─────────────────────────────────────────────────────────────────────────────────────────────────

    private View interfaz() {
        LinearLayout raiz = vertical();
        raiz.setPadding(16, 12, 16, 12);
        raiz.setBackgroundColor(0xff10141a);

        TextView titulo = texto("Eolfi · tableta satélite", 22);
        raiz.addView(titulo);

        LinearLayout fila1 = horizontal();
        campoPanel = campo("https://192.168.1.133:8777", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        campoPanel.setText(prefs.getString("url", ""));
        fila1.addView(campoPanel, peso(3));
        campoCodigo = campo("código de 6 cifras", InputType.TYPE_CLASS_NUMBER);
        fila1.addView(campoCodigo, peso(1.4f));
        fila1.addView(boton("Vincular", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                vincular();
            }
        }), peso(1));
        raiz.addView(fila1);

        estado = texto("", 15);
        raiz.addView(estado);

        LinearLayout fila2 = horizontal();
        hablar = boton("Mantén para hablar", null);
        hablar.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                if (e.getAction() == MotionEvent.ACTION_DOWN) empezarHablar();
                else if (e.getAction() == MotionEvent.ACTION_UP || e.getAction() == MotionEvent.ACTION_CANCEL) terminarHablar();
                return false;
            }
        });
        fila2.addView(hablar, peso(2));
        leer = new CheckBox(this);
        leer.setText("Leer respuestas");
        leer.setTextColor(0xffe8eef5);
        leer.setChecked(prefs.getBoolean("leer", true));
        fila2.addView(leer, peso(1.3f));
        // A9: por defecto el dictado se muestra en la caja para revisarlo; con esta casilla se envía al soltar.
        directo = new CheckBox(this);
        directo.setText("Enviar al soltar");
        directo.setTextColor(0xffe8eef5);
        directo.setChecked(prefs.getBoolean("directo", false));
        fila2.addView(directo, peso(1.3f));
        fila2.addView(boton("Trabajos", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                trabajos();
            }
        }), peso(1));
        fila2.addView(boton("Diagnóstico", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                diagnostico();
            }
        }), peso(1));
        raiz.addView(fila2);

        LinearLayout fila3 = horizontal();
        campoMensaje = campo("Escribe a Eolas…", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        fila3.addView(campoMensaje, peso(4));
        fila3.addView(boton("Enviar", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (ocupado) { decir("Aviso", "Espera a que Eolas termine la respuesta anterior"); return; }
                String t = campoMensaje.getText().toString();
                if (t.trim().isEmpty()) return;
                campoMensaje.setText("");
                enviar(t);
            }
        }), peso(1));
        raiz.addView(fila3);

        LinearLayout filaChats = horizontal();
        filaChats.addView(boton("Nueva conversación", new View.OnClickListener() {
            @Override public void onClick(View v) {
                if (!puedeCambiarConversacion()) return;
                guardarConversaciones();
                conversaciones.nueva();
                mostrarConversacion();
                guardarConversaciones();
            }
        }), peso(1));
        filaChats.addView(boton("Historial", new View.OnClickListener() {
            @Override public void onClick(View v) { elegirConversacion(); }
        }), peso(1));
        raiz.addView(filaChats);
        tituloConversacion = texto("", 15);
        raiz.addView(tituloConversacion);

        desplazable = new ScrollView(this);
        conversacion = texto("", 17);
        conversacion.setTextIsSelectable(true);
        desplazable.addView(conversacion);
        raiz.addView(desplazable, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        return raiz;
    }

    private LinearLayout vertical() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    private LinearLayout horizontal() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        return l;
    }

    private static LinearLayout.LayoutParams peso(float p) {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, p);
    }

    private TextView texto(String s, float tam) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(tam);
        t.setTextColor(0xffe8eef5);
        t.setPadding(4, 6, 4, 6);
        return t;
    }

    private EditText campo(String pista, int tipo) {
        EditText e = new EditText(this);
        e.setHint(pista);
        e.setInputType(tipo);
        e.setTextSize(16);
        return e;
    }

    private Button boton(String s, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(s);
        b.setTextSize(16);
        if (l != null) b.setOnClickListener(l);
        return b;
    }

    private void ui(final Runnable r) {
        runOnUiThread(r);
    }

    private void decir(final String quien, final String que) {
        ui(new Runnable() {
            @Override
            public void run() {
                conversacion.append((conversacion.length() > 0 ? "\n\n" : "") + quien + ": " + que);
                conversaciones.activa().vista = conversacion.getText().toString();
                guardarConversaciones();
                desplazable.post(new Runnable() {
                    @Override
                    public void run() {
                        desplazable.fullScroll(View.FOCUS_DOWN);
                    }
                });
            }
        });
    }

    private boolean puedeCambiarConversacion() {
        if (ocupado || hablando || grabando || transcribiendo) {
            decir("Aviso", "Espera a que termine la respuesta o la grabación antes de cambiar de conversación.");
            return false;
        }
        return true;
    }

    private void guardarConversaciones() {
        conversaciones.activa().borrador = campoMensaje.getText().toString();
        if (historialProtegido) return;
        try {
            int antes = conversaciones.recortes;
            archivoConversaciones.guardar(conversaciones.guardar());
            if (!conversacion.getText().toString().equals(conversaciones.activa().vista))
                conversacion.setText(conversaciones.activa().vista);
            if (conversaciones.recortes != antes)
                estado.setText("Límite del historial alcanzado: se conserva lo más reciente (8 MiB, " + lugarHistorial + ").");
        } catch (Exception e) {
            estado.setText("No se pudo guardar el historial: " + e.getMessage());
        }
    }

    private void mostrarConversacion() {
        Conversaciones.Charla c = conversaciones.activa();
        conversacion.setText(c.vista);
        campoMensaje.setText(c.borrador);
        tituloConversacion.setText(c.titulo + " · " + lugarHistorial + " · máximo 8 MiB");
    }

    private File carpetaHistorial() {
        // API 16 no tiene getExternalFilesDirs: Samsung declara la tarjeta extra en SECONDARY_STORAGE.
        String extra = System.getenv("SECONDARY_STORAGE");
        if (extra != null) for (String raiz : extra.split(File.pathSeparator)) {
            File base = new File(raiz);
            if (base.isDirectory() && base.canWrite()) {
                File d = new File(base, "Android/data/com.celtiaia.eolfi.tableta/files/conversaciones");
                if (d.isDirectory() || d.mkdirs()) { lugarHistorial = "tarjeta SD"; return d; }
            }
        }
        File d = getExternalFilesDir("conversaciones");
        if (d != null && (d.isDirectory() || d.mkdirs())) { lugarHistorial = "almacenamiento SD"; return d; }
        lugarHistorial = "memoria interna";
        return new File(getFilesDir(), "conversaciones");
    }

    private void elegirConversacion() {
        if (!puedeCambiarConversacion()) return;
        guardarConversaciones();
        final List<Conversaciones.Charla> lista = conversaciones.lista();
        CharSequence[] nombres = new CharSequence[lista.size()];
        for (int i = 0; i < lista.size(); i++) {
            Conversaciones.Charla c = lista.get(lista.size() - 1 - i);
            nombres[i] = (c == conversaciones.activa() ? "● " : "") + c.titulo;
        }
        new AlertDialog.Builder(this).setTitle("Retomar conversación").setItems(nombres,
                new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        if (!puedeCambiarConversacion()) return;
                        conversaciones.seleccionar(lista.get(lista.size() - 1 - which).id);
                        mostrarConversacion();
                        guardarConversaciones();
                    }
                }).setNegativeButton("Cerrar", null).show();
    }

    /** Recuperación explícita del chat anterior a esta versión, leída por ADB antes de actualizar. */
    private void recuperarChatAnterior() {
        if (getIntent() == null || !getIntent().getBooleanExtra("recuperar_chat_archivo", false)) return;
        getIntent().removeExtra("recuperar_chat_archivo");
        try {
            final String texto = archivoConversaciones.leerRecuperacion(Environment.getExternalStorageDirectory());
            if (texto == null) throw new IllegalArgumentException("no hay chat guardado para recuperar");
            new AlertDialog.Builder(this).setTitle("Recuperar conversación anterior")
                .setMessage("¿Guardar el chat anterior recuperado del dispositivo en el historial? No se enviará a Eolas.")
                .setPositiveButton("Guardar", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        if (!puedeCambiarConversacion()) return;
                        guardarConversaciones(); conversaciones.importar(texto);
                        mostrarConversacion(); guardarConversaciones();
                    }
                }).setNegativeButton("Cancelar", null).show();
        } catch (Exception e) { decir("Aviso", "No se pudo recuperar el chat anterior: " + e.getMessage()); }
    }

    private void pintarEstado() {
        String url = prefs.getString("url", null);
        String tok = prefs.getString("token", null);
        String h = prefs.getString("huella", null);
        estado.setText(tok == null ? "Sin vincular. En el panel del equipo: Proveedores → Vincular VS Code, y escribe aquí el código."
                : "Vinculada a " + url + (h != null ? "  ·  huella " + Reglas.huellaCorta(h) : "  ·  sin cifrar (http)"));
    }

    // ── Red ──────────────────────────────────────────────────────────────────────────────────────────────────────

    private Cliente cliente() {
        String url = prefs.getString("url", null);
        String tok = prefs.getString("token", null);
        if (url == null || tok == null) throw new IllegalStateException("primero vincula la tableta con el panel");
        return new Cliente(url, tok, prefs.getString("huella", null), false);
    }

    private static String error(Cliente.Respuesta r) {
        try {
            return "HTTP " + r.estado + ": " + new JSONObject(r.texto()).optString("error", r.texto());
        } catch (JSONException e) {
            return "HTTP " + r.estado;
        }
    }

    private void enSegundoPlano(final String nombre, final Runnable r) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    r.run();
                } catch (RuntimeException e) {
                    Log.w(TAG, nombre + ": " + e);
                    decir("Aviso", nombre + ": " + e.getMessage());
                }
            }
        }, "eolfi-" + nombre).start();
    }

    private void vincular() {
        if (!puedeCambiarConversacion()) return;
        final String url = Reglas.direccion(campoPanel.getText().toString());
        final String codigo = Reglas.codigo(campoCodigo.getText().toString());
        if (url == null) {
            decir("Aviso", "Dirección del panel no válida: usa https://IP:puerto o http://IP:puerto");
            return;
        }
        if (codigo == null) {
            decir("Aviso", "El código son 6 cifras: lo genera el panel del equipo");
            return;
        }
        enSegundoPlano("vincular", new Runnable() {
            @Override
            public void run() {
                try {
                    Cliente c = new Cliente(url, null, null, true);
                    String cuerpo = "{\"code\":" + Reglas.json(codigo) + ",\"name\":"
                            + Reglas.json("Tableta " + Build.MODEL) + ",\"scope\":\"tableta\"}";
                    Cliente.Respuesta r = c.json("POST", "/api/clients/token", cuerpo, 15000);
                    if (!r.ok()) {
                        decir("Aviso", "No se pudo vincular: " + error(r));
                        return;
                    }
                    JSONObject o = new JSONObject(r.texto());
                    if (!"tableta".equals(o.optString("scope"))) {
                        decir("Aviso", "El panel no conoce el vínculo de tableta: actualiza Eolfi en el equipo");
                        return;
                    }
                    prefs.edit().putString("url", url).putString("token", o.getString("token"))
                            .putString("huella", c.huellaVista()).commit();
                    ui(new Runnable() {
                        @Override
                        public void run() {
                            campoCodigo.setText("");
                            guardarConversaciones(); conversaciones.nueva();
                            mostrarConversacion(); guardarConversaciones();
                            pintarEstado();
                        }
                    });
                    decir("Eolfi", c.cifrado()
                            ? "Vinculada. Comprueba que la huella " + Reglas.huellaCorta(c.huellaVista())
                              + " coincide con la del certificado del panel."
                            : "Vinculada SIN CIFRAR (http): úsalo solo en tu red de casa.");
                    Log.i(TAG, "vinculada a " + url);
                } catch (Exception e) {
                    decir("Aviso", "No se pudo vincular: " + e.getMessage());
                }
            }
        });
    }

    private void enviar(final String texto) {
        if (ocupado) {
            decir("Aviso", "Espera a que Eolas termine la respuesta anterior");
            return;
        }
        ocupado = true;
        final Conversaciones.Charla charla = conversaciones.activa();
        final List<String[]> contexto = charla.contexto();
        charla.pendiente = texto;
        decir("Tú", texto);
        enSegundoPlano("chat", new Runnable() {
            @Override
            public void run() {
                // Si Eolas no llega a responder, el texto vuelve a la caja para reenviarlo (no se pierde el dictado).
                boolean devolver = true;
                try {
                    Cliente c = cliente();
                    Cliente.Respuesta r = c.json("POST", "/api/tableta/chat", Reglas.cuerpoChat(texto, contexto), 20000);
                    if (!r.ok()) {
                        decir("Aviso", error(r));
                        return;
                    }
                    String id = new JSONObject(r.texto()).getString("id");
                    String ultimoAviso = "";
                    long limite = System.currentTimeMillis() + 15 * 60 * 1000L;
                    while (System.currentTimeMillis() < limite) {
                        Thread.sleep(1500);
                        Cliente.Respuesta e = c.json("GET", "/api/tableta/chat?id=" + id, null, 20000);
                        if (!e.ok()) {
                            decir("Aviso", error(e));
                            return;
                        }
                        JSONObject o = new JSONObject(e.texto());
                        JSONArray av = o.optJSONArray("avisos");
                        if (av != null && av.length() > 0 && !av.getString(av.length() - 1).equals(ultimoAviso)) {
                            ultimoAviso = av.getString(av.length() - 1);
                            final String a = ultimoAviso;
                            ui(new Runnable() {
                                @Override
                                public void run() {
                                    estado.setText("Eolas: " + a);
                                }
                            });
                        }
                        String st = o.optString("status");
                        if ("done".equals(st)) {
                            final String resp = o.optString("texto", "(sin texto)");
                            ui(new Runnable() {
                                @Override public void run() {
                                    charla.respuesta(texto, resp);
                                    tituloConversacion.setText(charla.titulo + " · " + lugarHistorial + " · máximo 8 MiB");
                                }
                            });
                            devolver = false;
                            decir("Eolas", resp);
                            if (leer.isChecked()) leerEnVoz(c, resp);
                            return;
                        }
                        if ("error".equals(st) || "cancelled".equals(st)) {
                            decir("Aviso", Reglas.avisoChatFallido(o.optString("error")));
                            return;
                        }
                    }
                    devolver = false;   // sigue en marcha: la respuesta quedará en el panel
                    decir("Aviso", "Eolas tarda demasiado (15 min); la respuesta quedará en el panel");
                } catch (Exception e) {
                    decir("Aviso", "Chat: " + e.getMessage());
                } finally {
                    final boolean recuperar = devolver;
                    ui(new Runnable() {
                        @Override
                        public void run() {
                            pintarEstado();
                            if (recuperar) devolverACaja(texto);
                            if (recuperar) charla.pendiente = "";
                            guardarConversaciones();
                            ocupado = false;
                        }
                    });
                }
            }
        });
    }

    /** Pone el texto no respondido en la caja (delante de lo que ya hubiera escrito) para reenviarlo con «Enviar». */
    private void devolverACaja(String texto) {
        String actual = campoMensaje.getText().toString().trim();
        if (actual.contains(texto.trim())) return;
        campoMensaje.setText(actual.isEmpty() ? texto : texto + " " + actual);
        campoMensaje.setSelection(campoMensaje.getText().length());
    }

    private void leerEnVoz(Cliente c, String texto) {
        try {
            String t = texto.length() > 1500 ? texto.substring(0, 1500) : texto;
            Cliente.Respuesta r = c.json("POST", "/api/voz/hablar", "{\"texto\":" + Reglas.json(t) + "}", 120000);
            if (!r.ok()) {
                decir("Aviso", "Voz: " + error(r));
                return;
            }
            hablando = true;
            try {
                Audio.reproducir(r.cuerpo);
            } finally {
                hablando = false;
            }
        } catch (Exception e) {
            decir("Aviso", "Voz: " + e.getMessage());
        }
    }

    /**
     * Android 6+ (p. ej. el Redmi con Android 14): el micrófono se concede en tiempo de ejecución. Se llama por
     * reflexión para seguir compilando contra la API 16 de la tableta, donde el permiso ya viene de la instalación.
     * Devuelve true si ya se puede grabar.
     */
    private boolean microfonoConcedido(boolean pedir) {
        if (Build.VERSION.SDK_INT < 23) return true;
        String permiso = "android.permission.RECORD_AUDIO";
        try {
            Object r = Activity.class.getMethod("checkSelfPermission", String.class).invoke(this, permiso);
            if (((Integer) r).intValue() == 0) return true;
            if (pedir) Activity.class.getMethod("requestPermissions", String[].class, int.class)
                    .invoke(this, new String[] {permiso}, 7);
        } catch (Exception e) {
            Log.w(TAG, "permiso de micrófono: " + e);
        }
        return false;
    }

    private void empezarHablar() {
        if (grabando) return;
        if (!microfonoConcedido(true)) {
            decir("Aviso", "Concede el permiso del micrófono y vuelve a mantener el botón para hablar.");
            return;
        }
        String no = Reglas.motivoParaNoGrabar(hablando, ocupado);
        String fallo = no != null ? no : audio.empezar(MAX_GRABACION_S);
        if (fallo != null) {
            decir("Aviso", fallo);
            return;
        }
        grabando = true;
        final int sesion = ++sesionGrabacion;
        hablar.setText(directo.isChecked() ? "● Grabando… suelta para enviar" : "● Grabando… suelta para transcribir");
        // Si nunca llega el «soltar» (toque perdido), la grabación se cierra y se envía al llegar al máximo.
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep(MAX_GRABACION_S * 1000L + 300);
                } catch (InterruptedException e) {
                    return;
                }
                ui(new Runnable() {
                    @Override
                    public void run() {
                        if (grabando && sesion == sesionGrabacion) terminarHablar();
                    }
                });
            }
        }, "eolfi-tope-grabacion").start();
    }

    private void terminarHablar() {
        if (!grabando) return;
        grabando = false;
        hablar.setText("Mantén para hablar");
        final int[] pico = new int[1];
        final byte[] wav = audio.parar(pico);
        if (wav == null) return;
        if (wav.length < 44 + Audio.HZ / 2) {
            decir("Aviso", "Grabación demasiado corta: mantén pulsado mientras hablas");
            return;
        }
        if (pico[0] < 200) {
            decir("Aviso", "El micrófono solo captó silencio (pico " + pico[0] + "): habla más cerca");
            return;
        }
        transcribiendo = true;
        enSegundoPlano("voz", new Runnable() {
            @Override
            public void run() {
                try {
                    Cliente.Respuesta r = cliente().pedir("POST", "/api/voz/transcribir?idioma=es-ES", wav, "audio/wav", 120000);
                    if (!r.ok()) {
                        decir("Aviso", "Transcribir: " + error(r));
                        return;
                    }
                    String t = new JSONObject(r.texto()).optString("texto", "").trim();
                    if (t.isEmpty()) {
                        decir("Aviso", "No se entendió nada");
                        return;
                    }
                    Log.i(TAG, "DICTADO caracteres=" + t.length() + " pico=" + pico[0] + " directo=" + directo.isChecked());
                    final String dictado = t;
                    ui(new Runnable() {
                        @Override
                        public void run() {
                            if (directo.isChecked()) { enviar(dictado); return; }
                            String previo = campoMensaje.getText().toString().trim();
                            campoMensaje.setText(previo.isEmpty() ? dictado : previo + " " + dictado);
                            campoMensaje.setSelection(campoMensaje.getText().length());
                            estado.setText("Dictado listo: revísalo y pulsa Enviar");
                            guardarConversaciones();
                        }
                    });
                } catch (Exception e) {
                    decir("Aviso", "Transcribir: " + e.getMessage());
                } finally {
                    ui(new Runnable() { @Override public void run() { transcribiendo = false; } });
                }
            }
        });
    }

    private void trabajos() {
        enSegundoPlano("trabajos", new Runnable() {
            @Override
            public void run() {
                try {
                    Cliente.Respuesta r = cliente().json("GET", "/api/tableta/trabajos", null, 20000);
                    if (!r.ok()) {
                        decir("Aviso", error(r));
                        return;
                    }
                    JSONObject o = new JSONObject(r.texto());
                    StringBuilder sb = new StringBuilder();
                    JSONArray t = o.optJSONArray("trabajos");
                    for (int i = 0; t != null && i < t.length(); i++) {
                        JSONObject j = t.getJSONObject(i);
                        sb.append("\n• ").append(j.optString("kind")).append(" · ").append(j.optString("status"))
                                .append(" · ").append(j.optString("label"));
                    }
                    JSONArray e = o.optJSONArray("encargos");
                    for (int i = 0; e != null && i < e.length(); i++) {
                        JSONObject j = e.getJSONObject(i);
                        sb.append("\n◦ encargo ").append(j.optString("estado")).append(" · ").append(j.optString("titulo"));
                    }
                    decir("Panel", sb.length() == 0 ? "No hay trabajos ni encargos." : "Trabajos y encargos:" + sb);
                } catch (Exception ex) {
                    decir("Aviso", "Trabajos: " + ex.getMessage());
                }
            }
        });
    }

    // ── Diagnóstico: lo que la tableta mide de sí misma ─────────────────────────────────────────────────────────

    private void diagnostico() {
        final JSONObject d = new JSONObject();
        try {
            WebView w = new WebView(this);   // el agente de usuario solo se puede leer en el hilo de la interfaz
            d.put("webview.ua", w.getSettings().getUserAgentString());
            w.destroy();
        } catch (Exception e) {
            poner(d, "webview.error", String.valueOf(e));
        }
        enSegundoPlano("diagnostico", new Runnable() {
            @Override
            public void run() {
                try {
                    d.put("android.sdk", Build.VERSION.SDK_INT);
                    d.put("android.version", Build.VERSION.RELEASE);
                    d.put("android.build", Build.DISPLAY);
                    d.put("equipo.modelo", Build.MODEL);
                    d.put("equipo.placa", Build.BOARD);
                    d.put("equipo.hardware", Build.HARDWARE);
                    d.put("cpu.abi", Build.CPU_ABI);
                    d.put("java.heap_max_mb", Runtime.getRuntime().maxMemory() / (1024 * 1024));
                    d.put("cpu.nucleos", Runtime.getRuntime().availableProcessors());
                    SSLSocket s = (SSLSocket) SSLSocketFactory.getDefault().createSocket();
                    d.put("tls.soportados", lista(s.getSupportedProtocols()));
                    d.put("tls.por_defecto", lista(s.getEnabledProtocols()));
                    d.put("tls.tras_activar", lista(Cliente.ConTls12.protocolos(s.getSupportedProtocols())));
                    List<String> cif = Arrays.asList(s.getSupportedCipherSuites());
                    d.put("tls.cifrados_n", cif.size());
                    List<String> modernos = new ArrayList<String>();
                    for (String x : cif) if (x.contains("ECDHE") || x.contains("GCM")) modernos.add(x);
                    d.put("tls.cifrados_ecdhe_gcm", lista(modernos.toArray(new String[0])));
                    s.close();
                    d.put("audio.salida_hz", android.media.AudioTrack.getNativeOutputSampleRate(
                            android.media.AudioManager.STREAM_MUSIC));
                    int[] mic = Audio.prueba(1500);
                    d.put("mic.abre", mic != null);
                    if (mic != null) {
                        d.put("mic.pico", mic[0]);
                        d.put("mic.muestras", mic[1]);
                    }
                } catch (Exception e) {
                    poner(d, "diagnostico.error", String.valueOf(e));
                }
                Log.i(TAG, "DIAGNOSTICO " + d.toString());
                decir("Diagnóstico", formatear(d));
                if (prefs.getString("token", null) != null) {
                    try {
                        Cliente.Respuesta r = cliente().json("POST", "/api/tableta/diagnostico", d.toString(), 20000);
                        decir("Panel", r.ok() ? "Diagnóstico guardado en el equipo" : error(r));
                    } catch (Exception e) {
                        decir("Aviso", "No se pudo mandar el diagnóstico: " + e.getMessage());
                    }
                }
            }
        });
    }

    private static void poner(JSONObject o, String k, Object v) {
        try {
            o.put(k, v);
        } catch (JSONException ignorada) {
            // clave fija, no falla
        }
    }

    private static JSONArray lista(String[] xs) {
        JSONArray a = new JSONArray();
        for (String x : xs) a.put(x);
        return a;
    }

    private static String formatear(JSONObject d) {
        StringBuilder sb = new StringBuilder();
        JSONArray nombres = d.names();
        for (int i = 0; nombres != null && i < nombres.length(); i++) {
            String k = nombres.optString(i);
            sb.append("\n").append(k).append(" = ").append(d.opt(k));
        }
        return sb.toString();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (leer != null) prefs.edit().putBoolean("leer", leer.isChecked()).putBoolean("directo", directo.isChecked()).commit();
        if (conversaciones != null && campoMensaje != null) guardarConversaciones();
        grabando = false;
        if (hablar != null) hablar.setText("Mantén para hablar");
        audio.parar(null);
    }
}
