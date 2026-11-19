package com.celtiaia.eolfi.tableta;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Socket;
import java.net.URL;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * HTTP(S) hacia el panel de Eolfi, sin Android (solo java.* y javax.*): se prueba en la JVM contra el servidor real.
 *
 * <p>HTTPS: el panel usa un certificado propio, así que no se confía en ninguna CA. Se fija la huella SHA-256 del
 * certificado. La primera vez (al vincular) se acepta la que presente el panel y la tableta la muestra para que el
 * titular la compare con la del equipo; después, una huella distinta corta la conexión.
 *
 * <p>Android 4.1 trae TLS 1.1/1.2 (OpenSSL 1.0.1c) pero no los activa por defecto en los sockets cliente; el panel
 * exige TLS 1.2 como mínimo, así que se activan aquí.
 */
public final class Cliente {
    public static final class Respuesta {
        public final int estado;
        public final byte[] cuerpo;
        public final String tipo;

        Respuesta(int estado, byte[] cuerpo, String tipo) {
            this.estado = estado;
            this.cuerpo = cuerpo;
            this.tipo = tipo == null ? "" : tipo;
        }

        public String texto() {
            try {
                return new String(cuerpo, "UTF-8");
            } catch (java.io.UnsupportedEncodingException e) {
                throw new IllegalStateException(e);
            }
        }

        public boolean ok() {
            return estado >= 200 && estado < 300;
        }
    }

    public static final int MAX_RESPUESTA = 8 * 1024 * 1024;

    private final String base;
    private final String token;
    private final String huellaFijada;
    private final boolean aceptarPrimera;
    private volatile String huellaVista;

    /**
     * @param base dirección normalizada (Reglas.direccion)
     * @param token token del vínculo o null (solo para canjear el código)
     * @param huella huella fijada o null
     * @param aceptarPrimera sin huella fijada, aceptar la que presente el panel (solo al vincular)
     */
    public Cliente(String base, String token, String huella, boolean aceptarPrimera) {
        if (Reglas.direccion(base) == null) throw new IllegalArgumentException("dirección inválida");
        this.base = Reglas.direccion(base);
        this.token = token;
        this.huellaFijada = huella;
        this.aceptarPrimera = aceptarPrimera;
    }

    /** Huella del certificado que presentó el panel en la última conexión HTTPS (null en HTTP). */
    public String huellaVista() {
        return huellaVista;
    }

    public boolean cifrado() {
        return base.startsWith("https://");
    }

    public Respuesta pedir(String metodo, String ruta, byte[] cuerpo, String tipo, int plazoMs) throws IOException {
        if (!ruta.startsWith("/api/")) throw new IllegalArgumentException("ruta fuera de la API");
        HttpURLConnection c = (HttpURLConnection) new URL(base + ruta).openConnection();
        try {
            if (c instanceof HttpsURLConnection) {
                HttpsURLConnection s = (HttpsURLConnection) c;
                s.setSSLSocketFactory(fabrica());
                s.setHostnameVerifier(new HostnameVerifier() {
                    // La identidad es la huella fijada que ya comprobó el TrustManager, no el nombre (el panel va por IP).
                    @Override
                    public boolean verify(String host, SSLSession sesion) {
                        return huellaVista != null;
                    }
                });
            }
            c.setConnectTimeout(8000);
            c.setReadTimeout(plazoMs);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            c.setRequestMethod(metodo);
            c.setRequestProperty("X-Eolfi", "1");
            c.setRequestProperty("X-Eolfi-Client", "tableta");
            c.setRequestProperty("Accept-Language", "es");
            c.setRequestProperty("Connection", "close");
            if (token != null) c.setRequestProperty("Authorization", "Bearer " + token);
            if (cuerpo != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", tipo == null ? "application/json; charset=utf-8" : tipo);
                c.setFixedLengthStreamingMode(cuerpo.length);
                OutputStream o = c.getOutputStream();
                try {
                    o.write(cuerpo);
                } finally {
                    o.close();
                }
            }
            int estado = c.getResponseCode();
            InputStream in = estado >= 400 ? c.getErrorStream() : c.getInputStream();
            byte[] datos = in == null ? new byte[0] : leer(in);
            return new Respuesta(estado, datos, c.getContentType());
        } finally {
            c.disconnect();
        }
    }

    public Respuesta json(String metodo, String ruta, String cuerpo, int plazoMs) throws IOException {
        return pedir(metodo, ruta, cuerpo == null ? null : cuerpo.getBytes("UTF-8"), null, plazoMs);
    }

    static byte[] leer(InputStream in) throws IOException {
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) {
                if (out.size() + n > MAX_RESPUESTA) throw new IOException("respuesta demasiado grande");
                out.write(buf, 0, n);
            }
            return out.toByteArray();
        } finally {
            in.close();
        }
    }

    private SSLSocketFactory fabrica() throws IOException {
        try {
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[] {new Fijador()}, null);
            return new ConTls12(ctx.getSocketFactory());
        } catch (java.security.GeneralSecurityException e) {
            throw new IOException("TLS no disponible: " + e);
        }
    }

    private final class Fijador implements X509TrustManager {
        @Override
        public void checkClientTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
            throw new CertificateException("no se aceptan clientes");
        }

        @Override
        public void checkServerTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
            if (cadena == null || cadena.length == 0) throw new CertificateException("sin certificado");
            String h = Reglas.sha256(cadena[0].getEncoded());
            if (huellaFijada == null ? !aceptarPrimera : !Reglas.mismaHuella(h, huellaFijada)) {
                huellaVista = null;
                throw new CertificateException("la huella del panel no coincide (" + Reglas.huellaCorta(h) + ")");
            }
            huellaVista = h;
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() {
            return new X509Certificate[0];
        }
    }

    /** Envuelve la fábrica del sistema para activar TLS 1.2/1.1 (y quitar SSLv3) en cada socket. */
    static final class ConTls12 extends SSLSocketFactory {
        private final SSLSocketFactory d;

        ConTls12(SSLSocketFactory d) {
            this.d = d;
        }

        static String[] protocolos(String[] soportados) {
            List<String> out = new ArrayList<String>();
            List<String> s = Arrays.asList(soportados);
            for (String p : new String[] {"TLSv1.2", "TLSv1.1", "TLSv1"}) if (s.contains(p)) out.add(p);
            return out.toArray(new String[0]);
        }

        private Socket ajustar(Socket s) {
            if (s instanceof SSLSocket) {
                SSLSocket ss = (SSLSocket) s;
                ss.setEnabledProtocols(protocolos(ss.getSupportedProtocols()));
            }
            return s;
        }

        @Override
        public String[] getDefaultCipherSuites() {
            return d.getDefaultCipherSuites();
        }

        @Override
        public String[] getSupportedCipherSuites() {
            return d.getSupportedCipherSuites();
        }

        @Override
        public Socket createSocket(Socket s, String host, int port, boolean auto) throws IOException {
            return ajustar(d.createSocket(s, host, port, auto));
        }

        @Override
        public Socket createSocket(String host, int port) throws IOException {
            return ajustar(d.createSocket(host, port));
        }

        @Override
        public Socket createSocket(String host, int port, InetAddress local, int lport) throws IOException {
            return ajustar(d.createSocket(host, port, local, lport));
        }

        @Override
        public Socket createSocket(InetAddress host, int port) throws IOException {
            return ajustar(d.createSocket(host, port));
        }

        @Override
        public Socket createSocket(InetAddress host, int port, InetAddress local, int lport) throws IOException {
            return ajustar(d.createSocket(host, port, local, lport));
        }
    }
}
