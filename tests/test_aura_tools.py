# tests/test_aura_tools.py
import json, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = json.loads((ROOT / "config/aura-tools.json").read_text(encoding="utf-8"))

VALID_SIDES = {"system", "ui"}

def test_every_tool_has_required_fields():
    for t in TOOLS:
        assert set(t) >= {"name", "side", "description", "args"}, t
        assert t["side"] in VALID_SIDES, t
        assert isinstance(t["args"], dict)

def test_no_power_tool_exposed():
    names = {t["name"] for t in TOOLS}
    assert "power" not in names and "poweroff" not in names and "reboot" not in names

def test_every_tool_has_an_aurorad_executor():
    """The native desktop runs every registry tool through aurorad's /ask executors."""
    src = (ROOT / "shell/aurorad.py").read_text(encoding="utf-8")
    start = src.index("executors = {")
    block = src[start: src.index("\n            }", start)]
    names = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    for t in TOOLS:
        assert t["name"] in names, f"{t['name']} has no executor in aurorad.py"

def test_every_tool_declares_a_schema_matching_its_args():
    for t in TOOLS:
        assert isinstance(t.get("schema"), dict), t["name"]
        assert set(t["schema"]) == set(t["args"]), t["name"]
