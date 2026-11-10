"""Destino móvil: app Expo (React Native + TypeScript) para Android, iOS y web.

Solo se fija `expo`; el resto de paquetes (react, react-native, react-native-web…)
los resuelve `npx expo install`, que elige las versiones compatibles con el SDK.
La verificación instala, comprueba tipos, ejecuta Jest y exporta la versión web.
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import Writer, _page_sections, _routes
from eolfi.generador.templates import content_for

# Paquetes que `expo install` debe alinear con el SDK.
EXPO_DEPS = ["react", "react-native", "react-dom", "react-native-web", "@expo/metro-runtime", "expo-status-bar"]
EXPO_DEV = ["typescript", "@types/react", "jest-expo", "jest", "@testing-library/react-native"]

# Campos que muestra cada sección de lista: (principal, secundario, terciario).
LIST_FIELDS = {
    "Features": ("title", "text", "icon"), "CardGrid": ("title", "text", None),
    "Testimonials": ("text", "author", None), "Team": ("name", "role", "initials"),
    "PostList": ("title", "excerpt", "date"), "Pricing": ("name", "price", "text"),
    "Faq": ("q", "a", None), "LogoCloud": ("name", None, None), "Stats": ("value", "label", None),
}


EAS_CONFIG = {
    "cli": {"version": ">= 16.0.0", "appVersionSource": "remote"},
    "build": {
        # APK instalable directamente para probar en el móvil.
        "preview": {"distribution": "internal", "android": {"buildType": "apk"}},
        # Para las tiendas: AAB en Android, versión de compilación autoincremental.
        "production": {"autoIncrement": True},
    },
    "submit": {"production": {}},
}


def app_identifier(slug: str) -> str:
    """Identificador nativo válido en Android e iOS: com.eolfi.<segmento>, solo [a-z0-9]."""
    seg = re.sub(r"[^a-z0-9]", "", slug.lower())[:40]
    if not seg or not seg[0].isalpha() or seg in _JAVA_RESERVED:
        seg = "app" + seg   # «class», «new»… invalidarían el paquete de Android
    return f"com.eolfi.{seg}"


_JAVA_RESERVED = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const", "continue",
    "default", "do", "double", "else", "enum", "extends", "final", "finally", "float", "for", "goto", "if",
    "implements", "import", "instanceof", "int", "interface", "long", "native", "new", "package", "private",
    "protected", "public", "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while", "true", "false", "null", "var",
    "record", "yield", "sealed", "permits"}


def gen_expo(spec: dict[str, Any], w: Writer) -> None:
    routes = _routes(spec)
    pal = spec["design"]["palette"]
    resources = spec["api"]["resources"]
    slug = spec["name"]
    bundle_id = app_identifier(slug)
    w("package.json", json.dumps({
        "name": slug, "version": "1.0.0", "private": True, "main": "index.ts",
        "scripts": {
            "setup": f"expo install {' '.join(EXPO_DEPS)} && expo install {' '.join(EXPO_DEV)} -- --save-dev",
            "start": "expo start", "android": "expo start --android", "ios": "expo start --ios",
            "web": "expo start --web", "typecheck": "tsc --noEmit", "test": "jest --ci",
            "build:web": "expo export --platform web --output-dir dist",
            # Compilaciones nativas en EAS (requiere cuenta Expo: npx eas-cli login).
            "build:android": "npx eas-cli build --platform android --profile preview",
            "build:ios": "npx eas-cli build --platform ios --profile preview",
            "build:release": "npx eas-cli build --platform all --profile production",
        },
        "dependencies": {"expo": "latest"},
        "jest": {"preset": "jest-expo"},
    }, indent=2))
    w("app.json", json.dumps({"expo": {
        "name": spec["title"], "slug": slug, "version": "1.0.0", "orientation": "portrait",
        "userInterfaceStyle": "automatic", "web": {"output": "single", "bundler": "metro"},
        "ios": {"bundleIdentifier": bundle_id, "supportsTablet": True},
        "android": {"package": bundle_id},
    }}, indent=2, ensure_ascii=False))
    w("eas.json", json.dumps(EAS_CONFIG, indent=2))
    w("tsconfig.json", json.dumps({"extends": "expo/tsconfig.base", "compilerOptions": {"strict": True}}, indent=2))
    w("index.ts", """import { registerRootComponent } from "expo";
import App from "./App";

registerRootComponent(App);
""")
    w("src/content.ts", """// Textos de ejemplo: cámbialos por los tuyos.
export type Item = Record<string, string>;
export type SectionData = { items?: Item[] } & Record<string, string | Item[] | undefined>;

export const content: Record<string, SectionData> = """
      + json.dumps(content_for(spec), indent=2, ensure_ascii=False) + ";\n\n"
      + "export const text = (d: SectionData | undefined, key: string): string => {\n"
      + "  const v = d?.[key];\n  return typeof v === \"string\" ? v : \"\";\n};\n")
    w("src/theme.ts", f"""// Paleta aprendida de las fuentes (modo claro) y variante oscura.
import {{ useColorScheme }} from "react-native";

const light = {{
  primary: {json.dumps(pal["primary"])}, accent: {json.dumps(pal["accent"])},
  onPrimary: {json.dumps(pal.get("on_primary", "#ffffff"))},
  background: {json.dumps(pal["background"])}, surface: {json.dumps(pal["surface"])},
  text: {json.dumps(pal["text"])}, muted: {json.dumps(pal["muted"])},
}};
const dark = {{ ...light, background: "#12141a", surface: "#1b1e26", text: "#e8eaf0", muted: "#a0a7b4" }};

export type Theme = typeof light;
export function useTheme(): Theme {{
  return useColorScheme() === "dark" ? dark : light;
}}
""")
    fields = json.dumps({k: [f for f in v if f] for k, v in LIST_FIELDS.items()})
    w("src/components/Section.tsx", f"""import {{ useState }} from "react";
import {{ Pressable, StyleSheet, Text, TextInput, View }} from "react-native";
import {{ content, text, type Item }} from "../content";
import {{ useTheme, type Theme }} from "../theme";

// Campos visibles en las secciones de lista: [principal, secundario, terciario].
const FIELDS: Record<string, string[]> = {fields};

function Card({{ item, keys, t }}: {{ item: Item; keys: string[]; t: Theme }}) {{
  const [main, second, third] = keys;
  return (
    <View style={{[styles.card, {{ backgroundColor: t.surface }}]}}>
      {{third ? <Text style={{[styles.small, {{ color: t.muted }}]}}>{{item[third]}}</Text> : null}}
      <Text style={{[styles.cardTitle, {{ color: t.text }}]}}>{{item[main]}}</Text>
      {{second ? <Text style={{{{ color: t.muted }}}}>{{item[second]}}</Text> : null}}
    </View>
  );
}}

function ContactForm({{ t }}: {{ t: Theme }}) {{
  const d = content.ContactForm;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const send = () => {{
    if (!name.trim() || !/^[^@\\s]+@[^@\\s]+$/.test(email) || !message.trim()) {{
      setStatus("Revisa los campos: todos son obligatorios y el correo debe ser válido.");
      return;
    }}
    setName(""); setEmail(""); setMessage("");
    setStatus(text(d, "thanks"));
  }};
  const input = [styles.input, {{ color: t.text, borderColor: t.muted }}];
  return (
    <View style={{styles.section}}>
      <Text style={{[styles.h2, {{ color: t.text }}]}}>{{text(d, "title")}}</Text>
      <Text style={{{{ color: t.muted, marginBottom: 8 }}}}>{{text(d, "subtitle")}}</Text>
      <TextInput accessibilityLabel={{text(d, "name_label")}} placeholder={{text(d, "name_label")}}
        placeholderTextColor={{t.muted}} style={{input}} value={{name}} onChangeText={{setName}} />
      <TextInput accessibilityLabel={{text(d, "email_label")}} placeholder={{text(d, "email_label")}}
        placeholderTextColor={{t.muted}} style={{input}} value={{email}} onChangeText={{setEmail}}
        keyboardType="email-address" autoCapitalize="none" />
      <TextInput accessibilityLabel={{text(d, "message_label")}} placeholder={{text(d, "message_label")}}
        placeholderTextColor={{t.muted}} style={{[...input, {{ minHeight: 90 }}]}} value={{message}}
        onChangeText={{setMessage}} multiline />
      <Pressable role="button" onPress={{send}} style={{[styles.button, {{ backgroundColor: t.primary }}]}}>
        <Text style={{[styles.buttonText, {{ color: t.onPrimary }}]}}>{{text(d, "button")}}</Text>
      </Pressable>
      {{status ? <Text accessibilityLiveRegion="polite" style={{{{ color: t.primary, marginTop: 8 }}}}>{{status}}</Text> : null}}
    </View>
  );
}}

export default function Section({{ kind }}: {{ kind: string }}) {{
  const t = useTheme();
  const d = content[kind];
  if (kind === "ContactForm") return <ContactForm t={{t}} />;
  if (kind === "Hero") {{
    return (
      <View style={{[styles.hero, {{ backgroundColor: t.surface }}]}}>
        <Text style={{[styles.eyebrow, {{ color: t.primary }}]}}>{{text(d, "eyebrow")}}</Text>
        <Text accessibilityRole="header" style={{[styles.h1, {{ color: t.text }}]}}>{{text(d, "title")}}</Text>
        <Text style={{{{ color: t.muted, fontSize: 16 }}}}>{{text(d, "subtitle")}}</Text>
        <View style={{[styles.button, {{ backgroundColor: t.primary, alignSelf: "flex-start" }}]}}>
          <Text style={{[styles.buttonText, {{ color: t.onPrimary }}]}}>{{text(d, "cta")}}</Text>
        </View>
      </View>
    );
  }}
  if (kind === "CallToAction") {{
    return (
      <View style={{[styles.cta, {{ backgroundColor: t.primary }}]}}>
        <Text style={{[styles.h2, {{ color: t.onPrimary }}]}}>{{text(d, "title")}}</Text>
        <Text style={{{{ color: t.onPrimary }}}}>{{text(d, "text")}}</Text>
      </View>
    );
  }}
  const keys = FIELDS[kind] ?? ["title", "text"];
  return (
    <View style={{styles.section}}>
      {{text(d, "title") ? <Text accessibilityRole="header" style={{[styles.h2, {{ color: t.text }}]}}>{{text(d, "title")}}</Text> : null}}
      {{(d?.items ?? []).map((item, i) => <Card key={{i}} item={{item}} keys={{keys}} t={{t}} />)}}
    </View>
  );
}}

const styles = StyleSheet.create({{
  section: {{ paddingHorizontal: 20, paddingVertical: 24, gap: 10 }},
  hero: {{ paddingHorizontal: 20, paddingVertical: 36, gap: 10 }},
  cta: {{ margin: 20, padding: 24, borderRadius: 16, gap: 6 }},
  eyebrow: {{ fontWeight: "700" }},
  h1: {{ fontSize: 32, fontWeight: "800" }},
  h2: {{ fontSize: 24, fontWeight: "700", marginBottom: 4 }},
  card: {{ padding: 16, borderRadius: 12, gap: 4 }},
  cardTitle: {{ fontSize: 17, fontWeight: "700" }},
  small: {{ fontSize: 12 }},
  input: {{ borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8 }},
  button: {{ paddingVertical: 12, paddingHorizontal: 18, borderRadius: 999, marginTop: 6, alignItems: "center" }},
  buttonText: {{ color: "#fff", fontWeight: "700" }},
}});
""")
    if resources:
        w("src/api.ts", f"""// Nota: el APK de producción y el de «preview» bloquean http:// en claro: usa https:// para
// EXPO_PUBLIC_API_URL fuera de desarrollo (o el plugin expo-build-properties con usesCleartextTraffic).
// API del backend generado con Eolfi (FastAPI/Express). Configura EXPO_PUBLIC_API_URL,
// p. ej. EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 (en el móvil, la IP de tu equipo).
export type ApiItem = {{ id: number; name: string; description?: string }};
export const resources = {json.dumps(resources)} as const;
export const apiUrl = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\\/$/, "");

export async function list(resource: string): Promise<ApiItem[]> {{
  const res = await fetch(`${{apiUrl}}/api/${{resource}}`);
  if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
  return (await res.json()) as ApiItem[];
}}
""")
        w("src/components/ApiDemo.tsx", """import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { apiUrl, list, resources, type ApiItem } from "../api";
import { useTheme } from "../theme";

function Resource({ name }: { name: string }) {
  const t = useTheme();
  const [items, setItems] = useState<ApiItem[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!apiUrl) { setError("Configura EXPO_PUBLIC_API_URL para ver datos en vivo"); return; }
    list(name).then(setItems).catch((e: Error) => setError(e.message));
  }, [name]);
  return (
    <View style={[styles.card, { backgroundColor: t.surface }]}>
      <Text style={{ color: t.text, fontWeight: "700" }}>{name}</Text>
      {error ? <Text style={{ color: t.muted }}>{error}</Text> : null}
      {!error && items === null ? <Text style={{ color: t.muted }}>Cargando…</Text> : null}
      {items?.map((it) => <Text key={it.id} style={{ color: t.text }}>· {it.name}</Text>)}
    </View>
  );
}

export default function ApiDemo() {
  const t = useTheme();
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={{ color: t.text, fontSize: 24, fontWeight: "700" }}>Datos en vivo</Text>
      {resources.map((r) => <Resource key={r} name={r} />)}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { paddingHorizontal: 20, paddingVertical: 24, gap: 10 },
  card: { padding: 16, borderRadius: 12, gap: 4 },
});
""")
    pages = []
    for slug_, path, title in routes:
        secs = _page_sections(spec, slug_)
        pages.append({"slug": slug_, "title": title, "sections": secs, "home": slug_ == "home"})
    w("App.tsx", f"""import {{ useState }} from "react";
import {{ Pressable, ScrollView, StyleSheet, Text, View }} from "react-native";
import {{ StatusBar }} from "expo-status-bar";
import Section from "./src/components/Section";
{'import ApiDemo from "./src/components/ApiDemo";' if resources else ''}
import {{ useTheme }} from "./src/theme";

// Páginas generadas a partir de las fuentes analizadas (navegación por pestañas, sin dependencias).
export const pages = {json.dumps(pages, ensure_ascii=False, indent=2)};

export default function App() {{
  const t = useTheme();
  const [current, setCurrent] = useState(pages[0].slug);
  const page = pages.find((p) => p.slug === current) ?? pages[0];
  return (
    <View style={{[styles.root, {{ backgroundColor: t.background }}]}}>
      <StatusBar style="auto" />
      <View style={{[styles.header, {{ borderColor: t.surface }}]}}>
        <Text style={{[styles.brand, {{ color: t.text }}]}}>{spec["title"]}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={{false}} contentContainerStyle={{styles.tabs}}>
          {{pages.map((p) => (
            <Pressable key={{p.slug}} role="tab" aria-selected={{p.slug === current}}
              onPress={{() => setCurrent(p.slug)}}
              style={{[styles.tab, p.slug === current && {{ backgroundColor: t.primary }}]}}>
              <Text style={{{{ color: p.slug === current ? t.onPrimary : t.text }}}}>{{p.title}}</Text>
            </Pressable>
          ))}}
        </ScrollView>
      </View>
      <ScrollView contentContainerStyle={{{{ paddingBottom: 40 }}}}>
        {{!page.home ? (
          <View style={{styles.pageHeader}}>
            <Text accessibilityRole="header" style={{[styles.pageTitle, {{ color: t.text }}]}}>{{page.title}}</Text>
            <Text style={{{{ color: t.muted }}}}>Página de ejemplo: cambia este texto.</Text>
          </View>
        ) : null}}
        {{page.sections.map((s) => <Section key={{s}} kind={{s}} />)}}
        {'{page.home ? <ApiDemo /> : null}' if resources else ''}
        <Text style={{[styles.footer, {{ color: t.muted }}]}}>© {spec["title"]} · Hecho con código nuevo.</Text>
      </ScrollView>
    </View>
  );
}}

const styles = StyleSheet.create({{
  root: {{ flex: 1, paddingTop: 48 }},
  header: {{ paddingHorizontal: 16, paddingBottom: 8, borderBottomWidth: 1, gap: 8 }},
  brand: {{ fontSize: 18, fontWeight: "800" }},
  tabs: {{ gap: 8 }},
  tab: {{ paddingVertical: 6, paddingHorizontal: 12, borderRadius: 999 }},
  pageHeader: {{ paddingHorizontal: 20, paddingTop: 24, gap: 6 }},
  pageTitle: {{ fontSize: 28, fontWeight: "800" }},
  footer: {{ textAlign: "center", marginTop: 24 }},
}});
""")
    second = next((p for p in pages if not p["home"]), None)
    nav_test = f"""
test("la pestaña {second['title']} muestra su página", async () => {{
  await render(<App />);
  await fireEvent.press(screen.getByRole("tab", {{ name: {json.dumps(second['title'], ensure_ascii=False)} }}));
  expect(screen.getAllByText({json.dumps(second['title'], ensure_ascii=False)}).length).toBeGreaterThan(1);
}});
""" if second else ""
    form_test = """
test("el formulario valida y da las gracias", async () => {
  await render(<App />);
  await fireEvent.press(screen.getByRole("button", { name: content.ContactForm.button as string }));
  expect(screen.getByText(/Revisa los campos/)).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText(content.ContactForm.name_label as string), "Ana");
  await fireEvent.changeText(screen.getByLabelText(content.ContactForm.email_label as string), "ana@example.com");
  await fireEvent.changeText(screen.getByLabelText(content.ContactForm.message_label as string), "Mensaje de prueba");
  await fireEvent.press(screen.getByRole("button", { name: content.ContactForm.button as string }));
  expect(screen.getByText(content.ContactForm.thanks as string)).toBeTruthy();
});
""" if "ContactForm" in spec["sections"] else ""
    w("__tests__/App.test.tsx", f"""import {{ expect, test }} from "@jest/globals";
import {{ fireEvent, render, screen }} from "@testing-library/react-native";
import App, {{ pages }} from "../App";
import {{ content }} from "../src/content";

test("la portada muestra el título y todas las pestañas", async () => {{
  await render(<App />);
  expect(screen.getAllByText({json.dumps(spec["title"], ensure_ascii=False)}).length).toBeGreaterThan(0);
  expect(screen.getAllByRole("tab")).toHaveLength(pages.length);
}});
{nav_test}{form_test}""")
