"""Destino Rust (PLAN_DEFINITIVO.md, D2; 18/11/2026): herramienta de línea de comandos en Rust para Windows, macOS y
Linux, con la misma interfaz que el destino `cli` de Python.

- Un subcomando por recurso detectado en las fuentes (`list`, `add`, `show`, `remove`), `info`, `--json`,
  `--version` y `--help`; códigos de salida 0 (bien), 1 (no existe o error de datos) y 2 (uso incorrecto).
- Datos en la carpeta del usuario de cada sistema (%APPDATA%, ~/Library/Application Support, $XDG_DATA_HOME) con
  escritura atómica; una variable de entorno la cambia (las pruebas la usan).
- Solo dos dependencias, `serde` y `serde_json`; los argumentos se leen sin bibliotecas. `cargo build --release`
  deja un ejecutable único; el CI lo prueba en los tres sistemas.
"""
from __future__ import annotations

import json
import re
from typing import Any

from eolfi.generador.generators import Writer

# Nombres que no pueden ser el crate (palabras reservadas de Rust y crates que el proyecto usa o que vienen con Rust).
_RESERVADOS = {"as", "break", "const", "continue", "crate", "else", "enum", "extern", "false", "fn", "for", "if",
               "impl", "in", "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return", "self", "static",
               "struct", "super", "trait", "true", "type", "unsafe", "use", "where", "while", "async", "await",
               "dyn", "abstract", "become", "box", "do", "final", "macro", "override", "priv", "typeof", "unsized",
               "virtual", "yield", "try", "gen", "std", "core", "alloc", "proc_macro", "test", "serde", "serde_json"}


def command_name(spec: dict[str, Any]) -> str:
    c = re.sub(r"[^a-z0-9-]", "-", str(spec.get("name") or "app").lower()).strip("-")
    c = re.sub(r"-+", "-", c) or "app"
    if not c[0].isalpha() or c.replace("-", "_") in _RESERVADOS:
        c = "app-" + c
    return c


def _res(r: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", r.lower())


def _rust_str(s: str) -> str:
    """Literal de cadena de Rust (sin caracteres de control)."""
    s = "".join(ch for ch in s if ch >= " " and ch != "\x7f")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


CARGO_TOML = """[package]
name = "__CMD__"
version = "0.1.0"
edition = "2021"
description = __DESC__
publish = false

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"

[profile.release]
strip = true
lto = true
"""

LIB_RS = r'''//! __DOC__: herramienta de línea de comandos (Windows, macOS y Linux).
//!
//! Toda la lógica está aquí para poder probarla; `main.rs` solo pasa los argumentos y el código de salida.
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;
use std::path::PathBuf;

pub const APP: &str = "__CMD__";
pub const TITLE: &str = __TITLE__;
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const RESOURCES: &[&str] = &[__RESOURCES__];
/// Variable de entorno que cambia la carpeta de datos (las pruebas la usan).
pub const DATA_ENV: &str = "__ENV__";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Item {
    pub id: u64,
    pub name: String,
    #[serde(default)]
    pub description: String,
}

/// Windows: %APPDATA%; macOS: ~/Library/Application Support; Linux: $XDG_DATA_HOME o ~/.local/share.
pub fn data_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os(DATA_ENV).filter(|v| !v.is_empty()) {
        return PathBuf::from(dir);
    }
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let base = if cfg!(windows) {
        std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| home.join("AppData").join("Roaming"))
    } else if cfg!(target_os = "macos") {
        home.join("Library").join("Application Support")
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local").join("share"))
    };
    base.join(APP)
}

/// Una lista de elementos por recurso en un archivo JSON; escritura atómica (temporal + renombrar).
pub struct Store {
    path: PathBuf,
}

impl Store {
    pub fn new(resource: &str) -> Self {
        Store { path: data_dir().join(format!("{resource}.json")) }
    }

    fn load(&self) -> Result<Vec<Item>, String> {
        match fs::read_to_string(&self.path) {
            Ok(text) => serde_json::from_str(&text)
                .map_err(|e| format!("no se pudo leer {}: {e}", self.path.display())),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
            Err(e) => Err(format!("no se pudo leer {}: {e}", self.path.display())),
        }
    }

    fn save(&self, items: &[Item]) -> Result<(), String> {
        let fail = |e: &dyn std::fmt::Display| format!("no se pudo guardar {}: {e}", self.path.display());
        let dir = self.path.parent().map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
        fs::create_dir_all(&dir).map_err(|e| fail(&e))?;
        let tmp = dir.join(format!(".tmp-{}.json", std::process::id()));
        let text = serde_json::to_string_pretty(items).map_err(|e| fail(&e))?;
        fs::write(&tmp, text).map_err(|e| fail(&e))?;
        fs::rename(&tmp, &self.path).map_err(|e| {
            let _ = fs::remove_file(&tmp);
            fail(&e)
        })
    }

    pub fn list(&self) -> Result<Vec<Item>, String> {
        self.load()
    }

    pub fn add(&self, name: &str, description: &str) -> Result<Item, String> {
        let mut items = self.load()?;
        let id = items.iter().map(|i| i.id).max().unwrap_or(0) + 1;
        let item = Item { id, name: name.to_string(), description: description.to_string() };
        items.push(item.clone());
        self.save(&items)?;
        Ok(item)
    }

    pub fn get(&self, id: u64) -> Result<Option<Item>, String> {
        Ok(self.load()?.into_iter().find(|i| i.id == id))
    }

    pub fn remove(&self, id: u64) -> Result<bool, String> {
        let items = self.load()?;
        let keep: Vec<Item> = items.iter().filter(|i| i.id != id).cloned().collect();
        if keep.len() == items.len() {
            return Ok(false);
        }
        self.save(&keep)?;
        Ok(true)
    }
}

/// Nombre de un elemento: sin espacios a los lados y de 1 a 200 caracteres.
pub fn valid_name(value: &str) -> Result<String, String> {
    let v = value.trim();
    let n = v.chars().count();
    if n == 0 || n > 200 {
        return Err("el nombre debe tener entre 1 y 200 caracteres".to_string());
    }
    Ok(v.to_string())
}

pub fn usage() -> String {
    let mut s = format!("{APP} {VERSION}: {TITLE}\n\n");
    s.push_str(&format!("Uso: {APP} [--json] RECURSO ACCIÓN\n\n"));
    s.push_str("  info                    versión, sistema y carpeta de datos\n");
    for r in RESOURCES {
        s.push_str(&format!("  {r} list | add NOMBRE [-d DESCRIPCIÓN] | show ID | remove ID\n"));
    }
    s.push('\n');
    s.push_str("Opciones: --json salida en JSON (para scripts), --version, --help\n");
    s
}

enum Out {
    Items(Vec<Item>),
    Item(Item),
    Value(serde_json::Value),
}

fn print(out: &mut dyn Write, value: Out, json: bool) {
    let _ = if json {
        let v = match value {
            Out::Items(items) => serde_json::to_value(items).unwrap_or_default(),
            Out::Item(item) => serde_json::to_value(item).unwrap_or_default(),
            Out::Value(v) => v,
        };
        writeln!(out, "{}", serde_json::to_string_pretty(&v).unwrap_or_default())
    } else {
        match value {
            Out::Items(items) if items.is_empty() => writeln!(out, "(vacío)"),
            Out::Items(items) => items.iter().try_for_each(|i| {
                if i.description.is_empty() {
                    writeln!(out, "{:>4}  {}", i.id, i.name)
                } else {
                    writeln!(out, "{:>4}  {}  — {}", i.id, i.name, i.description)
                }
            }),
            Out::Item(i) => writeln!(out, "id: {}\nname: {}\ndescription: {}", i.id, i.name, i.description),
            Out::Value(serde_json::Value::Object(map)) => map.iter().try_for_each(|(k, v)| match v {
                serde_json::Value::String(s) => writeln!(out, "{k}: {s}"),
                other => writeln!(out, "{k}: {other}"),
            }),
            Out::Value(v) => writeln!(out, "{v}"),
        }
    };
}

/// Ejecuta la orden y devuelve el código de salida: 0 bien, 1 no existe o error de datos, 2 uso incorrecto.
pub fn run(args: &[String], out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let mut json = false;
    let mut words: Vec<String> = Vec::new();
    let mut description: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--json" => json = true,
            "--version" | "-V" => {
                let _ = writeln!(out, "{APP} {VERSION}");
                return 0;
            }
            "--help" | "-h" => {
                let _ = write!(out, "{}", usage());
                return 0;
            }
            "-d" | "--description" => {
                i += 1;
                match args.get(i) {
                    Some(d) => description = Some(d.clone()),
                    None => return fail_usage(err, "falta la descripción tras -d"),
                }
            }
            other => words.push(other.to_string()),
        }
        i += 1;
    }
    let words: Vec<&str> = words.iter().map(String::as_str).collect();
    match words.as_slice() {
        [] => {
            let _ = write!(out, "{}", usage());
            0
        }
        ["info"] => {
            let info = serde_json::json!({
                "version": VERSION, "platform": std::env::consts::OS, "data_dir": data_dir().display().to_string()
            });
            print(out, Out::Value(info), json);
            0
        }
        [res, action, rest @ ..] if RESOURCES.contains(res) => {
            let store = Store::new(res);
            let result = match (*action, rest) {
                ("list", []) => store.list().map(|items| Some(Out::Items(items))),
                ("add", [name]) => match valid_name(name) {
                    Ok(name) => store.add(&name, description.as_deref().unwrap_or("")).map(|i| Some(Out::Item(i))),
                    Err(e) => return fail_usage(err, &e),
                },
                ("show", [id]) | ("remove", [id]) => {
                    let id = match id.parse::<u64>() {
                        Ok(id) => id,
                        Err(_) => return fail_usage(err, &format!("id no válido: {id}")),
                    };
                    if *action == "show" {
                        store.get(id).map(|found| found.map(Out::Item))
                    } else {
                        store.remove(id).map(|ok| ok.then(|| Out::Value(serde_json::json!({"removed": id}))))
                    }
                }
                _ => return fail_usage(err, "orden desconocida"),
            };
            match result {
                Ok(Some(value)) => {
                    print(out, value, json);
                    0
                }
                Ok(None) => {
                    let _ = writeln!(err, "error: no existe {res} {}", rest.first().unwrap_or(&""));
                    1
                }
                Err(e) => {
                    let _ = writeln!(err, "error: {e}");
                    1
                }
            }
        }
        _ => fail_usage(err, "orden desconocida"),
    }
}

fn fail_usage(err: &mut dyn Write, msg: &str) -> i32 {
    let _ = write!(err, "error: {msg}\n\n{}", usage());
    2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valida_el_nombre() {
        assert_eq!(valid_name("  Bici  ").unwrap(), "Bici");
        assert!(valid_name("   ").is_err());
        assert!(valid_name(&"x".repeat(201)).is_err());
        assert!(valid_name(&"€".repeat(200)).is_ok()); // caracteres, no bytes
        assert!(valid_name(&"€".repeat(201)).is_err());
    }

    #[test]
    fn la_ayuda_lista_los_recursos() {
        let u = usage();
        assert!(RESOURCES.iter().all(|r| u.contains(r)));
    }
}
'''

MAIN_RS = '''//! Punto de entrada: lee los argumentos (también si no son UTF-8) y sale con el código de `run`.
fn main() {
    let args: Vec<String> = std::env::args_os().skip(1).map(|a| a.to_string_lossy().into_owned()).collect();
    let code = __CRATE__::run(&args, &mut std::io::stdout().lock(), &mut std::io::stderr().lock());
    std::process::exit(code);
}
'''

TEST_RS = r'''//! Pruebas del ejecutable de verdad, con una carpeta de datos temporal por prueba.
use std::path::PathBuf;
use std::process::Command;

fn data(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("__CMD__-test-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn run(dir: &PathBuf, args: &[&str]) -> (i32, String, String) {
    let o = Command::new(env!("CARGO_BIN_EXE___CMD__")).args(args).env("__ENV__", dir).output().unwrap();
    (o.status.code().unwrap_or(-1), String::from_utf8(o.stdout).unwrap(), String::from_utf8(o.stderr).unwrap())
}

#[test]
fn ciclo_completo() {
    let d = data("ciclo");
    let (code, out, _) = run(&d, &["--json", "__FIRST__", "add", "Primero", "-d", "detalle"]);
    let item: serde_json::Value = serde_json::from_str(&out).unwrap();
    assert_eq!((code, item["id"].as_u64()), (0, Some(1)));
    let (code, out, _) = run(&d, &["--json", "__FIRST__", "list"]);
    let items: Vec<serde_json::Value> = serde_json::from_str(&out).unwrap();
    assert_eq!((code, items.len(), items[0]["name"].as_str()), (0, 1, Some("Primero")));
    assert_eq!(run(&d, &["__FIRST__", "show", "1"]).0, 0);
    assert_eq!(run(&d, &["__FIRST__", "remove", "1"]).0, 0);
    let (code, _, err) = run(&d, &["__FIRST__", "show", "1"]);
    assert_eq!(code, 1, "{err}");
    assert!(err.starts_with("error:"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn valida_entradas() {
    let d = data("valida");
    for args in [&["__FIRST__", "add", "   "][..], &["__FIRST__", "show", "abc"], &["no-existe", "list"],
                 &["__FIRST__", "borrar", "1"], &["__FIRST__", "add", "x", "-d"]] {
        assert_eq!(run(&d, args).0, 2, "{args:?}");
    }
    assert_eq!(run(&d, &["--json", "__FIRST__", "list"]).1.trim(), "[]");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn info_version_y_ayuda() {
    let d = data("info");
    let (code, out, _) = run(&d, &["--json", "info"]);
    let info: serde_json::Value = serde_json::from_str(&out).unwrap();
    assert_eq!(code, 0);
    assert_eq!(info["platform"].as_str(), Some(std::env::consts::OS));
    assert_eq!(info["data_dir"].as_str(), Some(d.to_str().unwrap()));
    assert!(run(&d, &["--version"]).1.starts_with("__CMD__ "));
    assert!(run(&d, &["--help"]).1.contains("__FIRST__"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn json_en_utf8() {
    let d = data("utf8");
    let (code, out, _) = run(&d, &["--json", "__FIRST__", "add", "Canción ñandú"]);
    let item: serde_json::Value = serde_json::from_str(&out).unwrap();
    assert_eq!((code, item["name"].as_str()), (0, Some("Canción ñandú")));
    let _ = std::fs::remove_dir_all(&d);
}
'''


def gen_rust(spec: dict[str, Any], w: Writer) -> None:
    cmd = command_name(spec)
    crate = cmd.replace("-", "_")
    env = crate.upper() + "_DATA_DIR"
    resources = [_res(r) for r in (spec["api"]["resources"] or ["items"])][:6] or ["items"]
    title = spec["title"]
    doc = "".join(ch for ch in title if ch >= " ").replace("*/", "")

    def fill(t: str) -> str:
        return (t.replace("__CMD__", cmd).replace("__CRATE__", crate).replace("__ENV__", env)
                 .replace("__FIRST__", resources[0]).replace("__DOC__", doc).replace("__TITLE__", _rust_str(title))
                 .replace("__RESOURCES__", ", ".join(json.dumps(r) for r in resources)))

    w("Cargo.toml", CARGO_TOML.replace("__CMD__", cmd)
      .replace("__DESC__", json.dumps(f"{title}: herramienta de línea de comandos", ensure_ascii=False)))
    w("src/lib.rs", fill(LIB_RS))
    w("src/main.rs", fill(MAIN_RS))
    w("tests/cli.rs", fill(TEST_RS))
    w(".gitignore.extra", "target/\n")
