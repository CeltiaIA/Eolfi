package com.celtiaia.eolfi.tableta;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/** Archivo acotado en almacenamiento interno o SD. Sustitución con recuperación ante escritura incompleta. */
public final class ArchivoConversaciones {
    private final File archivo;
    public ArchivoConversaciones(File carpeta) { archivo = new File(carpeta, "historial.properties"); }
    public boolean existe() { return archivo.isFile() || new File(archivo + ".bak").isFile(); }
    public String leer() throws IOException {
        File f = archivo.isFile() ? archivo : new File(archivo + ".bak");
        return leerAcotado(f, Conversaciones.MAX_GUARDADO);
    }
    public String leerRecuperacion(File compartida) throws IOException {
        File local = new File(archivo.getParentFile(), "recuperar-chat.txt");
        return leerAcotado(local.isFile() ? local : new File(compartida, "Download/eolfi-recuperar-chat.txt"), 1024 * 1024);
    }
    private static String leerAcotado(File f, int limite) throws IOException {
        if (!f.isFile()) return null;
        if (f.length() > limite) throw new IOException("archivo mayor del límite de lectura");
        FileInputStream in = new FileInputStream(f);
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] b = new byte[8192];
            for (int n; (n = in.read(b)) != -1;) {
                if (out.size() + n > limite) throw new IOException("archivo mayor del límite de lectura");
                out.write(b, 0, n);
            }
            return new String(out.toByteArray(), "UTF-8");
        } finally { in.close(); }
    }
    public void guardar(String texto) throws IOException {
        byte[] b = texto.getBytes("UTF-8");
        if (b.length > Conversaciones.MAX_GUARDADO) throw new IOException("historial mayor de 8 MiB");
        File carpeta = archivo.getParentFile();
        if (!carpeta.isDirectory() && !carpeta.mkdirs()) throw new IOException("almacenamiento no disponible");
        File tmp = new File(archivo + ".tmp"), bak = new File(archivo + ".bak");
        FileOutputStream out = new FileOutputStream(tmp);
        try { out.write(b); out.flush(); out.getFD().sync(); } finally { out.close(); }
        if (archivo.exists()) {
            if (bak.exists() && !bak.delete()) throw new IOException("no se pudo sustituir la copia anterior");
            if (!archivo.renameTo(bak)) throw new IOException("no se pudo preparar el guardado");
        }
        if (!tmp.renameTo(archivo)) {
            if (bak.exists() && !archivo.exists()) bak.renameTo(archivo);
            throw new IOException("no se pudo completar el guardado");
        }
        // Copia temporal solo durante la sustitución; el historial completo no se duplica permanentemente.
        if (bak.exists() && !bak.delete()) throw new IOException("historial guardado, pero no se pudo retirar su copia temporal");
    }
}
