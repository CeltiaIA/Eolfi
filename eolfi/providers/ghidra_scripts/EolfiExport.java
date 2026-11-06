// Exporta programa, funciones y símbolos externos a JSON para Eolfi.
// Uso (lo invoca GhidraProvider): -postScript EolfiExport.java <salida.json> [funciones]
// [funciones]: lista separada por comas de nombres o direcciones a decompilar;
// "entry" = funciones en los puntos de entrada del programa.
// Java: funciona en Ghidra 10.x-12.x sin extensiones (Ghidra 12 ya no trae Jython).
// @category Eolfi
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Language;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class EolfiExport extends GhidraScript {
    private static final int MAX_FUNCTIONS = 5000;
    private static final int MAX_EXTERNALS = 20000;
    private static final int MAX_DECOMPILE = 25;
    private static final int MAX_C_CHARS = 60000;

    private static String q(String s) {
        if (s == null) {
            return "null";
        }
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        b.append(String.format("\\u%04x", (int) c));
                    } else {
                        b.append(c);
                    }
            }
        }
        return b.append('"').toString();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            throw new IllegalArgumentException("falta la ruta de salida");
        }
        Language lang = currentProgram.getLanguage();
        StringBuilder out = new StringBuilder();
        out.append("{\"program\":{");
        out.append("\"name\":").append(q(currentProgram.getName()));
        out.append(",\"format\":").append(q(currentProgram.getExecutableFormat()));
        out.append(",\"language\":").append(q(lang.getLanguageID().toString()));
        out.append(",\"processor\":").append(q(lang.getProcessor().toString()));
        out.append(",\"address_size\":").append(lang.getLanguageDescription().getSize());
        out.append(",\"big_endian\":").append(lang.isBigEndian());
        out.append(",\"compiler\":").append(q(currentProgram.getCompiler()));
        out.append(",\"image_base\":").append(q(currentProgram.getImageBase().toString()));
        out.append("},\"functions\":[");

        int total = 0;
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Function f = it.next();
            total++;
            if (total > MAX_FUNCTIONS) {
                continue;
            }
            if (total > 1) {
                out.append(',');
            }
            out.append("{\"name\":").append(q(f.getName()));
            out.append(",\"entry\":").append(q(f.getEntryPoint().toString()));
            out.append(",\"size\":").append(f.getBody().getNumAddresses());
            out.append(",\"thunk\":").append(f.isThunk());
            out.append(",\"calling_convention\":").append(q(f.getCallingConventionName()));
            out.append(",\"signature\":").append(q(f.getSignature().getPrototypeString()));
            out.append('}');
        }
        out.append("],\"function_count\":").append(total);
        out.append(",\"truncated\":").append(total > MAX_FUNCTIONS);
        out.append(",\"external_symbols\":[");
        int n = 0;
        SymbolIterator ext = currentProgram.getSymbolTable().getExternalSymbols();
        while (ext.hasNext() && n < MAX_EXTERNALS) {
            Symbol s = ext.next();
            if (n++ > 0) {
                out.append(',');
            }
            out.append(q(s.getName(true)));
        }
        out.append("],\"decompiled\":[");
        if (args.length > 1 && !args[1].isEmpty()) {
            decompile(args[1], out);
        }
        out.append("]}");

        try (Writer w = new OutputStreamWriter(new FileOutputStream(args[0]), StandardCharsets.UTF_8)) {
            w.write(out.toString());
        }
    }

    private List<Function> resolve(String spec) {
        List<Function> found = new ArrayList<>();
        for (String raw : spec.split(",")) {
            String name = raw.trim();
            if (name.isEmpty() || found.size() >= MAX_DECOMPILE) {
                continue;
            }
            if (name.equals("entry")) {
                for (Address a : currentProgram.getSymbolTable().getExternalEntryPointIterator()) {
                    Function f = getFunctionAt(a);
                    if (f != null && !found.contains(f) && found.size() < MAX_DECOMPILE) {
                        found.add(f);
                    }
                }
                continue;
            }
            Function f = null;
            try {
                Address a = toAddr(name);
                if (a != null) {
                    f = getFunctionContaining(a);
                }
            } catch (Exception e) {
                // no es una dirección: se busca por nombre
            }
            if (f == null) {
                List<Function> byName = getGlobalFunctions(name);
                if (!byName.isEmpty()) {
                    f = byName.get(0);
                }
            }
            if (f != null && !found.contains(f)) {
                found.add(f);
            }
        }
        return found;
    }

    private void decompile(String spec, StringBuilder out) {
        DecompInterface ifc = new DecompInterface();
        try {
            ifc.openProgram(currentProgram);
            boolean first = true;
            for (Function f : resolve(spec)) {
                if (monitor.isCancelled()) {
                    break;
                }
                DecompileResults res = ifc.decompileFunction(f, 60, monitor);
                String c = res.decompileCompleted() && res.getDecompiledFunction() != null
                    ? res.getDecompiledFunction().getC() : null;
                if (!first) {
                    out.append(',');
                }
                first = false;
                out.append("{\"name\":").append(q(f.getName()));
                out.append(",\"entry\":").append(q(f.getEntryPoint().toString()));
                out.append(",\"ok\":").append(c != null);
                if (c != null && c.length() > MAX_C_CHARS) {
                    c = c.substring(0, MAX_C_CHARS) + "\n/* ... truncado ... */";
                }
                out.append(",\"c\":").append(q(c));
                out.append(",\"error\":").append(q(c == null ? res.getErrorMessage() : null));
                out.append('}');
            }
        } finally {
            ifc.dispose();
        }
    }
}
