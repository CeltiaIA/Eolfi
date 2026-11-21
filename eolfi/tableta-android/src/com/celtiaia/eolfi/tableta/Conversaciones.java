package com.celtiaia.eolfi.tableta;

import java.io.IOException;
import java.io.StringReader;
import java.io.StringWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.UUID;

/** Historial local acotado. No contiene el token ni la huella del vínculo. */
public final class Conversaciones {
    public static final int MAX_GUARDADO = 8 * 1024 * 1024;
    private final int limite;
    public int recortes;
    private final List<Charla> charlas = new ArrayList<Charla>();
    private Charla actual;
    public Conversaciones() { this(MAX_GUARDADO); }
    public Conversaciones(int limite) {
        if (limite < 1024 || limite > MAX_GUARDADO) throw new IllegalArgumentException("límite de historial no válido");
        this.limite = limite;
    }

    public static final class Charla {
        public final String id;
        public String titulo = "Nueva conversación", vista = "", borrador = "", pendiente = "";
        public final List<String[]> mensajes = new ArrayList<String[]>();
        private Charla(String id) { this.id = id; }
        public List<String[]> contexto() {
            List<String[]> copia = new ArrayList<String[]>();
            for (String[] m : mensajes) copia.add(m.clone());
            return copia;
        }
        public void respuesta(String pregunta, String respuesta) {
            if (mensajes.isEmpty()) titulo = pregunta.replaceAll("\\s+", " ").trim();
            if (titulo.length() > 60) titulo = titulo.substring(0, 60) + "…";
            mensajes.add(new String[] {"user", pregunta});
            mensajes.add(new String[] {"assistant", respuesta});
            pendiente = "";
        }
    }

    public Charla nueva() {
        actual = new Charla(UUID.randomUUID().toString());
        charlas.add(actual);
        return actual;
    }
    public Charla activa() { return actual; }
    public List<Charla> lista() { return new ArrayList<Charla>(charlas); }
    public void seleccionar(String id) {
        for (Charla c : charlas) if (c.id.equals(id)) { actual = c; return; }
        throw new IllegalArgumentException("conversación desconocida");
    }

    public String guardar() {
        for (;;) {
            String s = serializar();
            try { if (s.getBytes("UTF-8").length <= limite) return s; }
            catch (IOException e) { throw new IllegalArgumentException("UTF-8 no disponible", e); }
            if (charlas.size() > 1) {
                int i = charlas.get(0) == actual ? 1 : 0;
                charlas.remove(i); recortes++;
            } else if (actual != null && actual.mensajes.size() > 2) {
                actual.mensajes.remove(0); actual.mensajes.remove(0); recortes++;
                actual.vista = "[Se conserva la parte más reciente por el límite del historial.]";
                for (String[] m : actual.mensajes) actual.vista += "\n\n" + ("user".equals(m[0]) ? "Tú" : "Eolas") + ": " + m[1];
            } else if (actual != null && actual.vista.length() > 512) {
                actual.vista = "[…]\n" + actual.vista.substring(actual.vista.length() / 2); recortes++;
            } else {
                // Una sola respuesta descomunal tampoco puede superar la memoria disponible.
                boolean reducido = false;
                if (actual != null) {
                    for (String[] m : actual.mensajes) if (m[1].length() > 128) {
                        m[1] = "[…]" + m[1].substring(m[1].length() / 2); reducido = true;
                    }
                    if (actual.borrador.length() > 512) { actual.borrador = actual.borrador.substring(0, 512); reducido = true; }
                    if (actual.pendiente.length() > 512) { actual.pendiente = actual.pendiente.substring(0, 512); reducido = true; }
                }
                if (!reducido) throw new IllegalArgumentException("no cabe una conversación en el límite del historial");
                recortes++;
            }
        }
    }

    private String serializar() {
        Properties p = new Properties();
        p.setProperty("version", "1");
        p.setProperty("total", String.valueOf(charlas.size()));
        p.setProperty("activa", actual == null ? "" : actual.id);
        for (int i = 0; i < charlas.size(); i++) {
            Charla c = charlas.get(i);
            String k = "c." + i + ".";
            p.setProperty(k + "id", c.id); p.setProperty(k + "titulo", c.titulo);
            p.setProperty(k + "vista", c.vista); p.setProperty(k + "borrador", c.borrador);
            p.setProperty(k + "pendiente", c.pendiente);
            p.setProperty(k + "mensajes", String.valueOf(c.mensajes.size()));
            for (int j = 0; j < c.mensajes.size(); j++) {
                p.setProperty(k + j + ".rol", c.mensajes.get(j)[0]);
                p.setProperty(k + j + ".texto", c.mensajes.get(j)[1]);
            }
        }
        try {
            StringWriter s = new StringWriter(); p.store(s, "Eolfi conversaciones v1");
            String texto = s.toString();
            return texto;
        } catch (IOException e) { throw new IllegalArgumentException("no se pudo guardar el historial", e); }
    }

    private static String exigir(Properties p, String k) {
        String v = p.getProperty(k);
        if (v == null) throw new IllegalArgumentException("historial incompleto: " + k);
        return v;
    }
    private static int cantidad(Properties p, String k, int max) {
        int n = Integer.parseInt(exigir(p, k));
        if (n < 0 || n > max) throw new IllegalArgumentException("historial no válido: " + k);
        return n;
    }
    public static Conversaciones cargar(String texto) {
        Conversaciones h = new Conversaciones();
        if (texto == null || texto.isEmpty()) { h.nueva(); return h; }
        if (texto.length() > MAX_GUARDADO) throw new IllegalArgumentException("historial demasiado grande");
        try {
            Properties p = new Properties(); p.load(new StringReader(texto));
            if (!"1".equals(exigir(p, "version"))) throw new IllegalArgumentException("versión de historial desconocida");
            int n = cantidad(p, "total", MAX_GUARDADO / 32);
            for (int i = 0; i < n; i++) {
                String k = "c." + i + ".";
                Charla c = new Charla(exigir(p, k + "id"));
                if (c.id.isEmpty()) throw new IllegalArgumentException("conversación sin identificador");
                for (Charla previa : h.charlas) if (previa.id.equals(c.id)) throw new IllegalArgumentException("identificador duplicado");
                c.titulo = exigir(p, k + "titulo"); c.vista = exigir(p, k + "vista");
                c.borrador = exigir(p, k + "borrador"); c.pendiente = exigir(p, k + "pendiente");
                int m = cantidad(p, k + "mensajes", MAX_GUARDADO / 32);
                for (int j = 0; j < m; j++) {
                    String rol = exigir(p, k + j + ".rol");
                    if (!"user".equals(rol) && !"assistant".equals(rol)) throw new IllegalArgumentException("rol no permitido");
                    c.mensajes.add(new String[] {rol, exigir(p, k + j + ".texto")});
                }
                h.charlas.add(c);
            }
            h.seleccionar(exigir(p, "activa"));
            return h;
        } catch (IOException e) { throw new IllegalArgumentException("historial ilegible", e); }
    }

    /** Importación manual del texto visible antiguo. Nunca acepta mensajes de sistema. */
    public Charla importar(String texto) {
        if (texto == null || texto.length() > 1024 * 1024) throw new IllegalArgumentException("chat a recuperar demasiado grande");
        Charla c = nueva(); c.titulo = "Conversación recuperada"; c.vista = texto;
        for (String parte : texto.split("\\n\\n(?=Tú: |Eolas: )")) {
            if (parte.startsWith("Tú: ")) c.mensajes.add(new String[] {"user", parte.substring(4)});
            else if (parte.startsWith("Eolas: ")) c.mensajes.add(new String[] {"assistant", parte.substring(7)});
        }
        return c;
    }
}
