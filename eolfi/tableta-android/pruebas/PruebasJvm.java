import com.celtiaia.eolfi.tableta.Cliente;
import com.celtiaia.eolfi.tableta.Reglas;
import com.celtiaia.eolfi.tableta.Wav;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Pruebas de la parte sin Android de la app, en la JVM y sin dependencias.
 *   java PruebasJvm unidad
 *   java PruebasJvm cliente URL CODIGO     (contra un panel real de pruebas que levanta pytest)
 * Termina con código 0 si todo pasa; imprime cada fallo.
 */
public final class PruebasJvm {
    private static int fallos, total;

    private static void ok(boolean c, String que) {
        total++;
        if (!c) {
            fallos++;
            System.out.println("FALLA: " + que);
        }
    }

    private static void lanza(Runnable r, String que) {
        try {
            r.run();
            ok(false, que + " (no lanzó)");
        } catch (IllegalArgumentException e) {
            ok(true, que);
        }
    }

    public static void main(String[] a) throws Exception {
        if (a.length > 0 && a[0].equals("cliente")) cliente(a[1], a[2]);
        else unidad();
        System.out.println((fallos == 0 ? "OK " : "FALLOS " + fallos + " de ") + total + " comprobaciones");
        System.exit(fallos == 0 ? 0 : 1);
    }

    static void unidad() {
        // WAV: ida y vuelta, cabecera exacta y pico.
        short[] m = {0, 1000, -32768, 32767, -5};
        byte[] w = Wav.codificar(m, 5, 16000);
        ok(w.length == 54, "wav: 44 + 2*n bytes");
        ok(new String(w, 0, 4).equals("RIFF") && new String(w, 8, 4).equals("WAVE"), "wav: RIFF/WAVE");
        int[] f = Wav.leer(w);
        ok(f[0] == 16000 && f[1] == 1 && f[2] == 44 && f[3] == 10, "wav: leer formato " + Arrays.toString(f));
        ok((w[46] & 0xff) == (1000 & 0xff) && w[47] == (byte) (1000 >> 8), "wav: little endian");
        ok(Wav.pico(m, 5) == 32767, "wav: pico recorta -32768");
        ok(Wav.pico(m, 2) == 1000, "wav: pico de las n primeras");
        lanza(new Runnable() { public void run() { Wav.leer(new byte[10]); } }, "wav: corto");
        final byte[] mal = w.clone();
        mal[34] = 8;   // 8 bits
        lanza(new Runnable() { public void run() { Wav.leer(mal); } }, "wav: 8 bits rechazado");
        final byte[] trozo = w.clone();
        trozo[16] = (byte) 0xff; trozo[17] = (byte) 0xff; trozo[18] = (byte) 0xff; trozo[19] = (byte) 0xff;
        lanza(new Runnable() { public void run() { Wav.leer(trozo); } }, "wav: trozo gigante rechazado");
        lanza(new Runnable() { public void run() { Wav.codificar(new short[2], 3, 16000); } }, "wav: n > longitud");

        // Dirección del panel.
        ok("https://192.168.1.133:8777".equals(Reglas.direccion(" 192.168.1.133:8777/ ")), "dir: https por defecto");
        ok("http://pc.local:80".equals(Reglas.direccion("HTTP://PC.local:080")), "dir: minúsculas y puerto");
        ok("https://[fe80::1]".equals(Reglas.direccion("https://[fe80::1]")), "dir: IPv6");
        for (String x : new String[] {null, "", "ftp://x", "https://x/ruta", "https://u@x", "https://x:0",
                "https://x:70000", "https://x:12a", "https://x?y", "https://", "https://x y", "javascript:alert(1)"}) {
            ok(Reglas.direccion(x) == null, "dir: rechaza " + x);
        }
        // Código.
        ok("012345".equals(Reglas.codigo(" 012 345 ")), "código: espacios");
        ok(Reglas.codigo("12345") == null && Reglas.codigo("12345a") == null && Reglas.codigo("1234567") == null,
                "código: solo 6 cifras");
        // Huellas.
        String h = Reglas.sha256("abc".getBytes());
        ok(h.equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"), "sha256 conocido");
        ok(Reglas.huellaCorta(h).equals("ba78 16bf 8f01 cfea"), "huella corta");
        ok(Reglas.mismaHuella(h, h) && !Reglas.mismaHuella(h, h.replace('b', 'c')) && !Reglas.mismaHuella(h, null),
                "misma huella");
        // JSON y cuerpo del chat.
        ok(Reglas.json("a\"b\\c\n\u0001 ").equals("\"a\\\"b\\\\c\\n\\u0001\\u2028\""), "json escape");
        List<String[]> hist = new ArrayList<String[]>();
        for (int i = 0; i < 20; i++) hist.add(new String[] {i % 2 == 0 ? "user" : "assistant", "m" + i});
        hist.add(new String[] {"system", "inyección"});
        hist.add(new String[] {"user", "   "});
        String c = Reglas.cuerpoChat("  hola  ", hist);
        ok(c.startsWith("{\"texto\":\"hola\",\"historial\":[{\"role\":\"user\",\"content\":\"m8\"}"), "chat: últimos 12 " + c);
        ok(!c.contains("system") && !c.contains("inyección") && c.endsWith("{\"role\":\"assistant\",\"content\":\"m19\"}]}"),
                "chat: descarta roles extraños y vacíos");
        lanza(new Runnable() { public void run() { Reglas.cuerpoChat("  ", new ArrayList<String[]>()); } }, "chat: vacío");
        char[] largo = new char[3000];
        Arrays.fill(largo, 'x');
        ok(Reglas.cuerpoChat(new String(largo), new ArrayList<String[]>()).length() < 2100, "chat: recorta a 2000");
        // Diagnóstico.
        ok(Reglas.claveDiagnostico("tls.por_defecto") && !Reglas.claveDiagnostico("Tls") && !Reglas.claveDiagnostico("a b")
                && !Reglas.claveDiagnostico("1x") && !Reglas.claveDiagnostico(""), "claves de diagnóstico");
        // Semidúplex.
        ok(Reglas.motivoParaNoGrabar(false, false) == null, "semidúplex: libre");
        ok(Reglas.motivoParaNoGrabar(true, false) != null && Reglas.motivoParaNoGrabar(false, true) != null,
                "semidúplex: no graba mientras habla o espera");
        // Cliente: rutas fuera de la API y direcciones malas.
        lanza(new Runnable() { public void run() { new Cliente("ftp://x", null, null, false); } }, "cliente: dirección");
        try {
            new Cliente("http://127.0.0.1:9", null, null, false).pedir("GET", "/otra", null, null, 1000);
            ok(false, "cliente: ruta fuera de /api/");
        } catch (IllegalArgumentException e) {
            ok(true, "cliente: ruta fuera de /api/");
        } catch (java.io.IOException e) {
            ok(false, "cliente: debió fallar antes de conectar");
        }
    }

    static void cliente(String url, String codigo) throws Exception {
        // 1) Sin huella y sin permitir la primera: no se conecta (no hay CA en la que confiar).
        try {
            new Cliente(url, null, null, false).json("GET", "/api/health", null, 5000);
            ok(false, "tls: sin huella debe fallar");
        } catch (java.io.IOException e) {
            ok(true, "tls: sin huella falla");
        }
        // 2) Vincular aceptando la primera huella.
        Cliente v = new Cliente(url, null, null, true);
        Cliente.Respuesta r = v.json("POST", "/api/clients/token",
                "{\"code\":" + Reglas.json(codigo) + ",\"name\":\"Tableta JVM\",\"scope\":\"tableta\"}", 10000);
        ok(r.ok() && r.texto().contains("\"scope\": \"tableta\""), "vincular: " + r.estado + " " + r.texto());
        String huella = v.huellaVista();
        ok(huella != null && huella.length() == 64, "vincular: huella vista");
        String token = r.texto().replaceAll("(?s).*\"token\": \"(ect_[^\"]+)\".*", "$1");
        ok(token.startsWith("ect_"), "vincular: token");
        // 3) Con la huella fijada: su superficie sí, lo demás 403.
        Cliente c = new Cliente(url, token, huella, false);
        Cliente.Respuesta e = c.json("GET", "/api/tableta/estado", null, 10000);
        ok(e.ok() && e.texto().contains("\"scope\": \"tableta\""), "estado: " + e.estado);
        ok(c.json("GET", "/api/subjects", null, 10000).estado == 403, "fuera de superficie: 403");
        Cliente.Respuesta d = c.json("POST", "/api/tableta/diagnostico", "{\"jvm.prueba\": true}", 10000);
        ok(d.ok(), "diagnóstico: " + d.estado);
        // 4) Huella distinta: se corta la conexión aunque el token sea bueno.
        String otra = (huella.charAt(0) == 'a' ? "b" : "a") + huella.substring(1);
        try {
            new Cliente(url, token, otra, false).json("GET", "/api/tableta/estado", null, 5000);
            ok(false, "huella distinta debe fallar");
        } catch (java.io.IOException ex) {
            ok(true, "huella distinta falla");
        }
        // 5) Token mal: 401.
        ok(new Cliente(url, token + "x", huella, false).json("GET", "/api/tableta/estado", null, 5000).estado == 401,
                "token malo: 401");
    }
}
