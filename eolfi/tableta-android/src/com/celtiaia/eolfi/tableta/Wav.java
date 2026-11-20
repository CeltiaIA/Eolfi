package com.celtiaia.eolfi.tableta;

/** WAV PCM de 16 bits: lo que acepta /api/voz/transcribir y lo que devuelve /api/voz/hablar. Sin Android: se prueba en la JVM. */
public final class Wav {
    private Wav() {}

    /** Muestras mono de 16 bits → WAV completo (cabecera RIFF de 44 bytes). */
    public static byte[] codificar(short[] muestras, int n, int hz) {
        if (n < 0 || n > muestras.length) throw new IllegalArgumentException("n fuera de rango");
        int datos = n * 2;
        byte[] out = new byte[44 + datos];
        escribir(out, 0, "RIFF");
        le32(out, 4, 36 + datos);
        escribir(out, 8, "WAVE");
        escribir(out, 12, "fmt ");
        le32(out, 16, 16);
        le16(out, 20, 1);            // PCM
        le16(out, 22, 1);            // mono
        le32(out, 24, hz);
        le32(out, 28, hz * 2);       // bytes por segundo
        le16(out, 32, 2);            // bloque
        le16(out, 34, 16);           // bits
        escribir(out, 36, "data");
        le32(out, 40, datos);
        for (int i = 0; i < n; i++) le16(out, 44 + i * 2, muestras[i]);
        return out;
    }

    /** Pico absoluto de las primeras n muestras (0..32767; 32768 se recorta). */
    public static int pico(short[] muestras, int n) {
        int p = 0;
        for (int i = 0; i < n; i++) {
            int v = Math.abs((int) muestras[i]);
            if (v > p) p = v;
        }
        return Math.min(p, 32767);
    }

    /** Formato leído de un WAV PCM 16 bits: {hz, canales, desplazamiento de datos, bytes de datos}. */
    public static int[] leer(byte[] wav) {
        if (wav == null || wav.length < 44 || !"RIFF".equals(texto(wav, 0)) || !"WAVE".equals(texto(wav, 8)))
            throw new IllegalArgumentException("no es un WAV");
        int pos = 12, hz = -1, canales = -1, bits = -1, codec = -1;
        while (pos + 8 <= wav.length) {
            String id = texto(wav, pos);
            long tam = u32(wav, pos + 4);
            if (tam < 0 || tam > Integer.MAX_VALUE) throw new IllegalArgumentException("trozo inválido");
            if ("fmt ".equals(id) && tam >= 16 && pos + 24 <= wav.length) {
                codec = u16(wav, pos + 8);
                canales = u16(wav, pos + 10);
                hz = (int) u32(wav, pos + 12);
                bits = u16(wav, pos + 22);
            } else if ("data".equals(id)) {
                if (codec != 1 || bits != 16 || (canales != 1 && canales != 2) || hz < 8000 || hz > 48000)
                    throw new IllegalArgumentException("se esperaba PCM 16 bits mono o estéreo de 8 a 48 kHz");
                int ini = pos + 8;
                int len = (int) Math.min(tam, (long) wav.length - ini);
                len -= len % (2 * canales);
                return new int[] {hz, canales, ini, len};
            }
            pos += 8 + (int) tam + (int) (tam & 1);
        }
        throw new IllegalArgumentException("WAV sin datos");
    }

    private static String texto(byte[] b, int i) {
        char[] c = new char[4];
        for (int k = 0; k < 4; k++) c[k] = (char) (b[i + k] & 0xff);
        return new String(c);
    }

    private static void escribir(byte[] b, int i, String s) {
        for (int k = 0; k < 4; k++) b[i + k] = (byte) s.charAt(k);
    }

    private static void le16(byte[] b, int i, int v) {
        b[i] = (byte) v;
        b[i + 1] = (byte) (v >> 8);
    }

    private static void le32(byte[] b, int i, int v) {
        le16(b, i, v);
        le16(b, i + 2, v >> 16);
    }

    private static int u16(byte[] b, int i) {
        return (b[i] & 0xff) | (b[i + 1] & 0xff) << 8;
    }

    private static long u32(byte[] b, int i) {
        return (u16(b, i) | (long) u16(b, i + 2) << 16) & 0xffffffffL;
    }
}
