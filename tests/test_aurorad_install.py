# tests/test_aurorad_install.py — every local module aurorad imports is installed beside it
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD_SCRIPTS = ["scripts/10-aurora-shell.sh", "scripts/13-aurora-desktop.sh"]

def test_build_scripts_install_every_aura_module_aurorad_imports():
    source = (ROOT / "shell" / "aurorad.py").read_text(encoding="utf-8")
    modules = sorted(set(re.findall(r"^\s*import (aura_\w+)", source, re.M)))
    assert modules, "aurorad imports no aura_* modules; the pattern is stale"
    for script in BUILD_SCRIPTS:
        text = (ROOT / script).read_text(encoding="utf-8")
        for mod in modules:
            line = re.compile(r"^\s*install\b.*\s/aurora/shell/%s\.py\s+/usr/lib/aurora/%s\.py\s*$" % (mod, mod), re.M)
            assert line.search(text), "%s does not install %s.py next to aurorad" % (script, mod)
