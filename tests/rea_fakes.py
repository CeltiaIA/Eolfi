"""Dobles de REA compartidos por las pruebas de Python y el e2e del panel (C5), sin depender de pytest: el job e2e
de la CI no lo instala. Devuelven las formas reales de las respuestas de REA."""
import json


class FakeAndroid:
    """REA: inspect_android_package (resumen de JADX), sesión, inventario y grafo, con las formas reales del 14/11."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        comps = [
            {"kind": "activity", "name": "a.Main", "exported": True, "exported_default": True, "permission": None,
             "actions": ["android.intent.action.MAIN"], "categories": ["android.intent.category.LAUNCHER"]},
            {"kind": "activity", "name": "a.Interna", "exported": False, "exported_default": False, "permission": None},
            {"kind": "provider", "name": "a.Datos", "exported": None, "exported_default": True, "permission": None,
             "authorities": ["a.datos"]},
            {"kind": "service", "name": "a.Sync", "exported": True, "exported_default": False,
             "permission": "a.permission.SYNC"},
            {"kind": "receiver", "name": "a.Boot", "exported": True, "exported_default": True, "permission": None,
             "actions": ["android.intent.action.BOOT_COMPLETED"]},
        ]
        results = {
            "inspect_android_package": {"summary": {
                "engine": {"name": "jadx-headless-mcp", "version": "0.7.1"}, "package_name": "a", "version_name": "1.0",
                "version_code": "1", "min_sdk": "26", "target_sdk": "33", "class_count": 10, "resource_count": 5,
                "permissions": ["android.permission.CAMERA", "android.permission.INTERNET"],
                "components": {"status": "complete", "items": comps}, "signature_verification": "not_performed"}},
            "open_binary": {"result": {}},
            "inspect_artifact": {"evidence_id": "ev_inv"},
            "project_android_application_graph": {
                "root_sha256": "ef" * 32, "runtime_families": ["dalvik-art", "native"], "bridge_candidates": [],
                "components": {"dex": [{"path": "classes.dex"}], "native_libraries": [{"path": "lib/arm64-v8a/libx.so"}]},
                "coverage": {"status": "complete-within-inventory"}},
            "close_binary": {},
        }
        if name == "project_android_application_graph":
            assert args["inventory_evidence"] == [{"evidence_id": "ev_inv"}]
        return json.dumps({"normalized_result": results[name]} if name != "inspect_artifact" else results[name]), True


class FakeCallGraph:
    """REA con Ghidra: list_procedures y get_call_graph por niveles (formas reales con whoami.exe, 14/11/2026)."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append((name, args))
        procs = [{"address": "0x10", "value": "entry"}, {"address": "0x20", "value": "FUN_20"},
                 {"address": "0x30", "value": 'raro"[x]'}, {"address": "EXTERNAL:0x1", "value": "KERNEL32.DLL::Sleep"},
                 {"address": "0x40", "value": "MSVCRT.DLL::exit"}]
        if name == "list_procedures":
            r = procs
        elif name == "get_call_graph":
            if args["direction"] == "backward":   # quién llama a 0x20: entry
                r = {"graph": {"0": [{"address": args["address"], "status": "ok", "calls": ["0x10"]}],
                               "1": [{"address": "0x10", "status": "ok", "calls": []}]}}
            else:
                r = {"graph": {"0": [{"address": args["address"], "status": "ok", "calls": ["0x20", "0x30"]}],
                               "1": [{"address": "0x20", "status": "ok", "calls": ["EXTERNAL:0x1", "0x40"]},
                                     {"address": "0x30", "status": "error", "calls": []}],
                               "2": [{"address": "EXTERNAL:0x1", "status": "ok", "calls": []},
                                     {"address": "0x40", "status": "ok", "calls": []}]}}
        else:
            r = {"result": {}}
        return json.dumps({"normalized_result": r}), True


class FakeApple:
    """REA simulado: inventario y proyección de una app de Apple con un bundle principal y un servicio XPC."""

    def __init__(self):
        self.calls = []

    def call(self, name, args, limit=None):
        self.calls.append(name)
        if name == "open_binary":
            return json.dumps({"result": {"format": "zip"}}), True
        if name == "close_binary":
            return json.dumps({"result": None}), True
        if name == "inspect_artifact":
            return json.dumps({"inspection_id": "ai_1"}), True
        assert name == "project_apple_application_graph" and args["inventory_evidence"] == [{"inspection_id": "ai_1"}]
        out = {"root_sha256": "ee" * 32, "root_format": "zip", "platforms": ["macos"], "application_roots": ["X.app"],
               "bundles": [{"path": "X.app", "role": "application", "info_plist_path": "X.app/Contents/Info.plist",
                            "executable_candidates": ["X.app/Contents/MacOS/X"], "signing_paths": ["s"]},
                           {"path": "X.app/Contents/XPCServices/H.xpc", "role": "xpc-service",
                            "info_plist_path": "X.app/Contents/XPCServices/H.xpc/Contents/Info.plist",
                            "executable_candidates": [], "signing_paths": []}],
               "components": {"executables": [{"path": "X.app/Contents/MacOS/X", "format": "mach-o-universal"}],
                              "privileged_helpers": [], "launchd_plists": [{"path": "X.app/Contents/L.plist"}]},
               "symlinks": ["a"], "runtime_families": ["native"], "bridge_candidates": [],
               "coverage": {"status": "complete-within-inventory"}}
        return json.dumps({"normalized_result": out}), True


def _info_plist():
    import plistlib

    return plistlib.dumps({"CFBundleIdentifier": "org.x", "CFBundleShortVersionString": "1.0", "LSUIElement": "1",
                           "NSCameraUsageDescription": "Para escanear", "SUFeedURL": "https://x.test/appcast.xml",
                           "CFBundleURLTypes": [{"CFBundleURLSchemes": ["xapp"]}],
                           "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True,
                                                      "NSExceptionDomains": {"b.test": {}}}})
