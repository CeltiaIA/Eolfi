package com.celtiaia.eolfi.tableta;

import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;

/** Micrófono (AudioRecord, 16 kHz mono) y altavoz (AudioTrack) de la tableta. Una grabación a la vez. */
final class Audio {
    static final int HZ = 16000;

    private final Object cerrojo = new Object();
    private AudioRecord rec;
    private Thread hilo;
    private volatile boolean grabando;
    private short[] muestras;
    private int n;

    /** Empieza a grabar hasta `maxSegundos`. Devuelve null si todo fue bien o el motivo del fallo. */
    String empezar(int maxSegundos) {
        synchronized (cerrojo) {
            if (grabando) return "ya se está grabando";
            int min = AudioRecord.getMinBufferSize(HZ, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (min <= 0) return "el micrófono no admite 16 kHz mono (" + min + ")";
            AudioRecord r = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, HZ,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(min, HZ));
            if (r.getState() != AudioRecord.STATE_INITIALIZED) {
                r.release();
                return "no se pudo abrir el micrófono (¿lo usa otra app?)";
            }
            rec = r;
            muestras = new short[HZ * maxSegundos];
            n = 0;
            grabando = true;
            r.startRecording();
            hilo = new Thread(new Runnable() {
                @Override
                public void run() {
                    short[] trozo = new short[1024];
                    while (grabando) {
                        int leidas = rec.read(trozo, 0, trozo.length);
                        if (leidas <= 0) continue;
                        synchronized (cerrojo) {
                            int cabe = Math.min(leidas, muestras.length - n);
                            System.arraycopy(trozo, 0, muestras, n, cabe);
                            n += cabe;
                            if (n >= muestras.length) grabando = false;
                        }
                    }
                }
            }, "eolfi-microfono");
            hilo.start();
            return null;
        }
    }

    /** Para y devuelve el WAV grabado (o null si no había nada). `pico[0]` recibe el pico absoluto. */
    byte[] parar(int[] pico) {
        Thread h;
        synchronized (cerrojo) {
            if (rec == null) return null;
            grabando = false;
            h = hilo;
        }
        try {
            if (h != null) h.join(1500);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        synchronized (cerrojo) {
            try {
                rec.stop();
            } catch (IllegalStateException ignorada) {
                // ya estaba parado
            }
            rec.release();
            rec = null;
            if (pico != null && pico.length > 0) pico[0] = Wav.pico(muestras, n);
            return n == 0 ? null : Wav.codificar(muestras, n, HZ);
        }
    }

    /** Grabación de prueba para el diagnóstico: {pico, muestras leídas} o null si no se pudo abrir. */
    static int[] prueba(int ms) {
        Audio a = new Audio();
        if (a.empezar(1 + ms / 1000) != null) return null;
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        int[] pico = new int[1];
        byte[] wav = a.parar(pico);
        return new int[] {pico[0], wav == null ? 0 : (wav.length - 44) / 2};
    }

    /** Reproduce un WAV PCM 16 bits por el altavoz (bloquea hasta terminar; llamar fuera del hilo de la interfaz). */
    static void reproducir(byte[] wav) {
        int[] f = Wav.leer(wav);
        int canales = f[1] == 2 ? AudioFormat.CHANNEL_OUT_STEREO : AudioFormat.CHANNEL_OUT_MONO;
        int min = AudioTrack.getMinBufferSize(f[0], canales, AudioFormat.ENCODING_PCM_16BIT);
        if (min <= 0) throw new IllegalStateException("el altavoz no admite " + f[0] + " Hz");
        AudioTrack t = new AudioTrack(AudioManager.STREAM_MUSIC, f[0], canales, AudioFormat.ENCODING_PCM_16BIT,
                min * 4, AudioTrack.MODE_STREAM);
        try {
            if (t.getState() != AudioTrack.STATE_INITIALIZED) throw new IllegalStateException("altavoz no disponible");
            t.play();
            int pos = f[2];
            int fin = f[2] + f[3];
            while (pos < fin) {
                int w = t.write(wav, pos, Math.min(8192, fin - pos));
                if (w <= 0) break;
                pos += w;
            }
            // En modo flujo stop() deja sonar lo ya escrito; se espera lo que cabe en el búfer antes de liberar.
            t.stop();
            Thread.sleep(1000L * min * 4 / (f[0] * 2 * f[1]) + 200);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            t.release();
        }
    }
}
