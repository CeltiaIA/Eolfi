"""Destino .NET: app de escritorio nativa en C# con Avalonia para Windows, macOS y Linux.

- Interfaz nativa (no web) construida en código: pestañas por página, secciones con los
  textos de ejemplo de la especificación, tema claro/oscuro del sistema (Fluent).
- Proyecto de pruebas xUnit sobre el modelo de contenido (sin abrir ventanas).
- `APP_SMOKE=1` abre la ventana, comprueba que se mostró y sale (prueba de humo real).
- `dotnet publish -r <rid>` crea un ejecutable autocontenido por sistema
  (win-x64, osx-arm64, linux-x64); el CI generado lo hace en los tres.
Las versiones de los paquetes NuGet se piden como «la última estable» y la verificación
las fija en el .csproj con la versión realmente restaurada.
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import Writer, _page_sections, _routes, content_for
from eolfi.generador.generators_desktop import app_id

PACKAGES = ["Avalonia", "Avalonia.Desktop", "Avalonia.Themes.Fluent", "Avalonia.Fonts.Inter"]
TEST_PACKAGES = ["Microsoft.NET.Test.Sdk", "xunit", "xunit.runner.visualstudio"]


def project_name(slug: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", slug) if p]
    name = "".join(p[:1].upper() + p[1:] for p in parts) or "App"
    # Un espacio de nombres igual a uno del framework («System», «Avalonia»…) rompe la compilación (A12).
    clash = name.split(".")[0].lower() in {"system", "microsoft", "avalonia", "xunit", "windows", "mono",
                                           "netstandard", "mscorlib", "program", "tests"}
    return name if name[0].isalpha() and not clash else "App" + name


def _cs(s: Any) -> str:
    """Literal de cadena C# seguro (json.dumps produce comillas y escapes compatibles)."""
    return json.dumps(str(s), ensure_ascii=False)


def _section_text(name: str, data: Any) -> tuple[str, list[str]]:
    """Título y líneas de texto de una sección a partir de su contenido de ejemplo."""
    lines: list[str] = []
    title = name

    def walk(v: Any) -> None:
        if isinstance(v, str):
            if 0 < len(v) <= 300 and not v.startswith(("/", "#", "http")):
                lines.append(v)
        elif isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, list):
            for vv in v[:6]:
                walk(vv)

    if isinstance(data, dict):
        title = str(data.get("title") or data.get("heading") or name)
        walk({k: v for k, v in data.items() if k not in ("title", "heading")})
    else:
        walk(data)
    return title, lines[:8]


def gen_dotnet(spec: dict[str, Any], w: Writer) -> None:
    name = project_name(spec["name"])
    content = content_for(spec)
    pages = []
    for slug, _path, title in _routes(spec):
        secs = []
        for s in _page_sections(spec, slug):
            t, lines = _section_text(s, content.get(s))
            secs.append((t, lines))
        pages.append((title, secs))

    model = ",\n".join(
        f"        new Page({_cs(title)}, new Section[] {{\n" + ",\n".join(
            f"            new Section({_cs(t)}, new[] {{ {', '.join(_cs(x) for x in lines) or _cs('')} }})"
            for t, lines in secs) + "\n        })"
        for title, secs in pages)

    w(f"src/{name}/{name}.csproj", f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
    <AssemblyName>{name}</AssemblyName>
    <RootNamespace>{name}</RootNamespace>
    <ApplicationTitle>{spec['title']}</ApplicationTitle>
    <BuiltInComInteropSupport>true</BuiltInComInteropSupport>
    <ApplicationManifest>app.manifest</ApplicationManifest>
  </PropertyGroup>
  <ItemGroup>
{chr(10).join(f'    <PackageReference Include="{p}" Version="*" />' for p in PACKAGES)}
  </ItemGroup>
</Project>
""")
    w(f"src/{name}/app.manifest", f"""<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <assemblyIdentity version="1.0.0.0" name="{app_id(spec['name'])}" />
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}}" />
    </application>
  </compatibility>
</assembly>
""")
    w(f"src/{name}/Content.cs", f"""namespace {name};

// Textos de ejemplo de la app (cámbialos por los tuyos). Sin lógica de interfaz: se prueba aparte.
public sealed record Section(string Title, string[] Lines);
public sealed record Page(string Title, Section[] Sections);

public static class Content
{{
    public const string AppTitle = {_cs(spec['title'])};

    public static readonly Page[] Pages =
    {{
{model}
    }};
}}
""")
    w(f"src/{name}/Program.cs", f"""using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Themes.Fluent;

namespace {name};

public sealed class App : Application
{{
    public override void Initialize() => Styles.Add(new FluentTheme());   // claro/oscuro según el sistema

    public override void OnFrameworkInitializationCompleted()
    {{
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {{
            var window = MainWindow.Create();
            desktop.MainWindow = window;
            if (Environment.GetEnvironmentVariable("APP_SMOKE") == "1")
            {{
                // Prueba de humo: la ventana se abre con su contenido y la app sale con código 0.
                window.Opened += (_, _) =>
                {{
                    var ok = window.Content is TabControl tabs && tabs.ItemCount == Content.Pages.Length;
                    Console.WriteLine($"{{{{\\"smoke\\":{{(ok ? "true" : "false")}},\\"title\\":\\"{{window.Title}}\\"}}}}");
                    desktop.Shutdown(ok ? 0 : 1);
                }};
            }}
        }}
        base.OnFrameworkInitializationCompleted();
    }}
}}

public static class MainWindow
{{
    public static Window Create()
    {{
        var tabs = new TabControl {{ Margin = new Thickness(12) }};
        foreach (var page in Content.Pages)
        {{
            var stack = new StackPanel {{ Spacing = 18, Margin = new Thickness(8, 16) }};
            foreach (var section in page.Sections)
            {{
                var box = new StackPanel {{ Spacing = 6 }};
                box.Children.Add(new TextBlock {{ Text = section.Title, FontSize = 22, FontWeight = FontWeight.SemiBold }});
                foreach (var line in section.Lines.Where(l => l.Length > 0))
                    box.Children.Add(new TextBlock {{ Text = line, TextWrapping = TextWrapping.Wrap, MaxWidth = 760,
                                                     HorizontalAlignment = HorizontalAlignment.Left }});
                stack.Children.Add(box);
            }}
            tabs.Items.Add(new TabItem {{ Header = page.Title, Content = new ScrollViewer {{ Content = stack }} }});
        }}
        return new Window
        {{
            Title = Content.AppTitle,
            Width = 1100, Height = 760, MinWidth = 360, MinHeight = 480,
            Content = tabs,
        }};
    }}
}}

public static class Program
{{
    [STAThread]
    public static int Main(string[] args) => BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UsePlatformDetect().WithInterFont().LogToTrace();
}}
""")
    w(f"tests/{name}.Tests/{name}.Tests.csproj", f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
{chr(10).join(f'    <PackageReference Include="{p}" Version="*" />' for p in TEST_PACKAGES)}
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="../../src/{name}/{name}.csproj" />
  </ItemGroup>
</Project>
""")
    w(f"tests/{name}.Tests/ContentTests.cs", f"""using Xunit;

namespace {name}.Tests;

public class ContentTests
{{
    [Fact]
    public void HayPaginasYSecciones()
    {{
        Assert.NotEmpty(Content.Pages);
        Assert.All(Content.Pages, p => Assert.False(string.IsNullOrWhiteSpace(p.Title)));
        Assert.Contains(Content.Pages, p => p.Sections.Length > 0);
    }}

    [Fact]
    public void TitulosDeSeccionNoVacios()
    {{
        foreach (var page in Content.Pages)
            Assert.All(page.Sections, s => Assert.False(string.IsNullOrWhiteSpace(s.Title)));
    }}
}}
""")
    w(f"{name}.slnx", f"""<Solution>
  <Project Path="src/{name}/{name}.csproj" />
  <Project Path="tests/{name}.Tests/{name}.Tests.csproj" />
</Solution>
""")
    w("global.json", json.dumps({"sdk": {"version": "10.0.100", "rollForward": "latestFeature"}}, indent=2))
    w(".gitignore.extra", "bin/\nobj/\npublish/\n")
