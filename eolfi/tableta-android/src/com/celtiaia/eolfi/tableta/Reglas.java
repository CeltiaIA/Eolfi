package com.celtiaia.eolfi.tableta;

import java.security.MessageDigest;

/** Reglas puras (sin Android) del cliente: dirección del panel, código, huella TLS y JSON mínimo. Se prueban en la JVM. */
public final class Reglas {
    private Reglas() {}

    public static final int MAX_TEXTO = 2000;
    public static final int MAX_HISTORIAL = 12;

    /**
     * Normaliza la dirección del panel: http(s)://host[:puerto] sin ruta ni credenciales. Sin esquema se asume
     * https. Devuelve null si no es válida.
     */
    public static String direccion(String entrada) {
        if (entrada == null) return null;
        String s = entrada.trim();
        if (s.isEmpty() || s.length() > 200) return null;
        if (!s.contains("://")) s = "https://" + s;
        String esquema = s.substring(0, s.indexOf("://")).toLowerCase();
        if (!esquema.equals("http") && !esquema.equals("https")) return null;
        String resto = s.substring(s.indexOf("://") + 3);
        while (resto.endsWith("/")) resto = resto.substring(0, resto.length() - 1);
        if (resto.isEmpty() || resto.contains("/") || resto.contains("@") || resto.contains("?") || resto.contains("#")
                || resto.contains(" ")) return null;
        String host = resto;
        String puerto = null;
        int dos = resto.lastIndexOf(':');
        if (dos >= 0 && !resto.endsWith("]")) {
            host = resto.substring(0, dos);
            puerto = resto.substring(dos + 1);
            if (puerto.isEmpty() || puerto.length() > 5) return null;
            for (int i = 0; i < puerto.length(); i++) if (!Character.isDigit(puerto.charAt(i))) return null;
            int p = Integer.parseInt(puerto);
            if (p < 1 || p > 65535) return null;
        }
        if (host.isEmpty()) return null;
        for (int i = 0; i < host.length(); i++) {
            char c = host.charAt(i);
            if (!(Character.isLetterOrDigit(c) || c == '.' || c == '-' || c == '[' || c == ']' || c == ':')) return null;
        }
        return esquema + "://" + host.toLowerCase() + (puerto != null ? ":" + Integer.parseInt(puerto) : "");
    }

    /** El código de vinculación del panel: exactamente 6 dígitos (se toleran espacios). */
    public static String codigo(String entrada) {
        if (entrada == null) return null;
        String s = entrada.replace(" ", "").trim();
        if (s.length() != 6) return null;
        for (int i = 0; i < 6; i++) if (!Character.isDigit(s.charAt(i))) return null;
        return s;
    }

    /** SHA-256 en hexadecimal (minúsculas): la huella con la que se fija el certificado del panel. */
    public static String sha256(byte[] datos) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-256").digest(datos);
            StringBuilder sb = new StringBuilder(64);
            for (byte b : h) {
                sb.append(Character.forDigit((b >> 4) & 0xf, 16)).append(Character.forDigit(b & 0xf, 16));
            }
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Huella legible para comparar a ojo con la del equipo: grupos de 4, solo los 16 primeros caracteres. */
    public static String huellaCorta(String hex) {
        if (hex == null || hex.length() < 16) return "?";
        return hex.substring(0, 4) + " " + hex.substring(4, 8) + " " + hex.substring(8, 12) + " " + hex.substring(12, 16);
    }

    /** Comparación en tiempo constante de dos huellas. */
    public static boolean mismaHuella(String a, String b) {
        if (a == null || b == null || a.length() != b.length()) return false;
        int d = 0;
        for (int i = 0; i < a.length(); i++) d |= a.charAt(i) ^ b.charAt(i);
        return d == 0;
    }

    /** Cadena JSON con escape completo (incluye controles y separadores de línea Unicode). */
    public static String json(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 2).append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20 || c == 0x2028 || c == 0x2029) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    /**
     * Cuerpo de POST /api/tableta/chat. `historial` alterna usuario/asistente; se recortan los más antiguos para
     * respetar el máximo del servidor y se descartan los vacíos.
     */
    public static String cuerpoChat(String texto, java.util.List<String[]> historial) {
        String t = texto == null ? "" : texto.trim();
        if (t.isEmpty()) throw new IllegalArgumentException("mensaje vacío");
        if (t.length() > MAX_TEXTO) t = t.substring(0, MAX_TEXTO);
        StringBuilder sb = new StringBuilder("{\"texto\":").append(json(t)).append(",\"historial\":[");
        java.util.List<String[]> h = new java.util.ArrayList<String[]>();
        for (String[] m : historial) {
            if (m != null && m.length == 2 && ("user".equals(m[0]) || "assistant".equals(m[0]))
                    && m[1] != null && !m[1].trim().isEmpty()) h.add(m);
        }
        int desde = Math.max(0, h.size() - MAX_HISTORIAL);
        for (int i = desde; i < h.size(); i++) {
            if (i > desde) sb.append(',');
            String c = h.get(i)[1];
            if (c.length() > MAX_TEXTO * 2) c = c.substring(0, MAX_TEXTO * 2);
            sb.append("{\"role\":").append(json(h.get(i)[0])).append(",\"content\":").append(json(c)).append('}');
        }
        return sb.append("]}").toString();
    }

    /** Clave aceptada por /api/tableta/diagnostico. */
    public static boolean claveDiagnostico(String k) {
        if (k == null || k.isEmpty() || k.length() > 41) return false;
        if (k.charAt(0) < 'a' || k.charAt(0) > 'z') return false;
        for (int i = 1; i < k.length(); i++) {
            char c = k.charAt(i);
            if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '.')) return false;
        }
        return true;
    }

    /** Semidúplex: no se graba mientras suena la respuesta ni mientras Eolas responde. null = se puede grabar. */
    public static String motivoParaNoGrabar(boolean hablando, boolean ocupado) {
        if (hablando) return "Espera a que termine de leer la respuesta";
        if (ocupado) return "Espera a que Eolas termine la respuesta anterior";
        return null;
    }

    /** Aviso para un chat que terminó sin respuesta. Si Eolas estaba atendiendo otra petición, se dice que el mensaje
     *  vuelve a la caja para reenviarlo; en otro caso, el error tal cual. */
    public static String avisoChatFallido(String error) {
        String e = error == null ? "" : error.trim();
        if (e.contains("está respondiendo una petición") || e.contains("is answering a request")) {
            return "Eolas está ocupado con otra petición. Tu mensaje vuelve a la caja: pulsa Enviar en un momento";
        }
        return "Eolas no pudo responder: " + (e.isEmpty() ? "sin detalle" : e) + ". Tu mensaje vuelve a la caja";
    }
}
