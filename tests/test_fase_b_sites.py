"""Fase B del plan de mejoras: sites y flows (M32–M39)."""
import os
import sys
import time
from pathlib import Path

import pytest


def test_cookies_are_not_mixed_up():
    """M32: los atributos de cada Set-Cookie se quedan con su cookie."""
    from eolfi.sites.webpage import _headers_report

    r = _headers_report({"set-cookie": "a=1; Secure; SameSite=Lax\nb=2; HttpOnly; Expires=Wed, 21 Oct 2026 07:28:00 GMT"})
    a, b = r["cookies"]
    assert (a["name"], a["secure"], a["httponly"]) == ("a", True, False)
    assert (b["name"], b["secure"], b["httponly"]) == ("b", False, True)


def test_old_clones_are_pruned_but_foreign_folders_are_kept(tmp_path, monkeypatch):
    """M33: los clones de más de 7 días se borran; una carpeta ajena nunca."""
    from eolfi.sites import repo

    clone_dir = tmp_path / "proyecto-0123456789-abc_12"
    mine = tmp_path / "mis-fotos"
    for d in (clone_dir, mine):
        d.mkdir()
        old = time.time() - 30 * 24 * 3600
        os.utime(d, (old, old))
    monkeypatch.setattr(repo.shutil, "which", lambda _n: "git")
    monkeypatch.setattr(repo, "safe_git", lambda *a, **k: (_ for _ in ()).throw(OSError("sin red")))
    with pytest.raises(Exception):
        repo.clone("https://github.com/x/y", tmp_path)
    assert not clone_dir.exists() and mine.exists()


def test_walk_prunes_node_modules(tmp_path):
    """M35: recorrido con poda y con tope."""
    from eolfi.sites.webpage import walk_files

    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "a.html").write_text("x", encoding="utf-8")
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    for i in range(30):
        (tmp_path / f"p{i}.html").write_text("x", encoding="utf-8")
    got = list(walk_files(tmp_path, suffixes=(".html",), limit=10))
    assert len(got) == 10 and all("node_modules" not in p.relative_to(tmp_path).parts for p in got)


def test_diff_compares_beyond_the_first_4_mb(tmp_path):
    """M36: dos salidas iguales en los primeros 4 MB y distintas al final no son «equivalentes»."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.diff_flow import run_diff

    (tmp_path / "in.txt").write_text("x", encoding="utf-8")
    ref = tmp_path / "ref.py"
    cand = tmp_path / "cand.py"
    ref.write_text("import sys; sys.stdout.write('a' * 5_000_000 + 'FIN')", encoding="utf-8")
    cand.write_text("import sys; sys.stdout.write('a' * 5_000_000 + 'OTRO')", encoding="utf-8")
    r = run_diff([sys.executable, str(ref), "{input}"], [sys.executable, str(cand), "{input}"],
                 tmp_path / "in.txt", EvidenceStore(str(tmp_path / "e.db")))
    assert r["mismatches"] == 1 and r["passed"] is False


def test_stack_detection_fixes():
    """M37: csproj, gradle, Flutter, Hugo/Jekyll, subcadenas e implies transitivo."""
    from eolfi.sites.repo import parse_csproj, parse_gradle
    from eolfi.sites.stack import BY_NAME, _apply_implies, detect_repo

    names = lambda deps, paths=(): {t["name"] for t in detect_repo(deps, set(paths))}  # noqa: E731
    wpf, _ = parse_csproj('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>')
    web, _ = parse_csproj('<Project Sdk="Microsoft.NET.Sdk.Web"></Project>')
    assert "WPF" in names({"nuget": wpf}) and "ASP.NET" in names({"nuget": web})
    gradle = parse_gradle('plugins { id("com.android.application") }\ndependencies { implementation(libs.androidx.core.ktx) }')
    assert "plugin:com.android.application" in gradle and "libs:androidx.core.ktx" in gradle
    assert "Android (Gradle)" in names({"maven": gradle})
    assert "Flutter Web" not in names({"pub": {"flutter"}}, ["pubspec.yaml", "lib/main.dart"])
    assert "Flutter Web" in names({"pub": {"flutter"}}, ["pubspec.yaml", "web/index.html"])
    assert "Hugo" not in names({}, ["config.toml"]) and "Jekyll" not in names({}, ["_config.yml"])
    assert "Hugo" in names({}, ["config.toml", "content/a.md", "layouts/x.html"])
    assert "Echo" not in names({"go": {"github.com/x/echoserver"}})
    assert "Echo" in names({"go": {"github.com/labstack/echo/v4"}})
    found = {}
    from eolfi.sites.stack import _add
    _add(found, BY_NAME["Expo"], "x")
    _apply_implies(found)
    assert "React Native" in found


def test_repo_ignores_example_manifests(tmp_path):
    """M37: el package.json de examples/ no es la pila del proyecto."""
    from eolfi.sites.repo import analyze_repo

    (tmp_path / "examples" / "demo").mkdir(parents=True)
    (tmp_path / "examples" / "demo" / "package.json").write_text('{"dependencies": {"express": "1"}}', encoding="utf-8")
    (tmp_path / "README.md").write_text("# x", encoding="utf-8")
    _s, findings = analyze_repo(str(tmp_path))
    stack = next(f for f in findings if f["operation"] == "repo_stack")["result"]["technologies"]
    assert "Express" not in {t["name"] for t in stack}


def test_summarize_survives_incomplete_evidence(tmp_path):
    """M38."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.core.models import Authority, Confidence, Evidence
    from eolfi.flows.triage_flow import summarize

    s = EvidenceStore(str(tmp_path / "e.db"))
    s.add_evidence(Evidence(subject="a" * 64, provider="x", provider_version="1", operation="archive_inventory",
                            params={}, result={"sin": "kind"}, authority=list(Authority)[0], confidence=list(Confidence)[0]))
    out = summarize(s, "a" * 64)
    assert "summary_error" in out


def test_compare_with_mixed_types():
    """M39: sorted() con tipos mezclados y listas enormes recortadas."""
    from eolfi.flows.compare_flow import _dict_diff, _set_diff

    assert _set_diff([1, "1", None], ["x"])["added"] == ["x"]
    d = _dict_diff({"a": list(range(10_000)), 1: "x"}, {"a": [], "b": 2})
    assert len(d["a"]["before"]) <= 51
