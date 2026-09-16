# tests/test_iso_tool_registry.py — the image must never ship a registry offering power
#
# power was removed from the model's tool list deliberately: no path may run from typed text
# to a power state without a click. The registry the model sees is chosen by
# aura_llm._default_tools_path(), which checks its OWN directory before /opt/aura/config, so
# a leftover file next to aura_llm.py silently outranks the correct one whenever AURA_TOOLS
# is not exported. Two such files (871 bytes, July, listing power) were found in a built tree.
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ISO_SCRIPT = (ROOT / "scripts/build-full-iso.sh").read_text(encoding="utf-8")
STALE = "/usr/lib/aurora/config/aura-tools.json"


def test_the_registry_in_this_repo_does_not_offer_power_to_the_model():
    tools = json.loads((ROOT / "config/aura-tools.json").read_text(encoding="utf-8"))
    names = [t["name"] for t in tools]
    assert "power" not in names, "the model is being offered %s" % names


def test_the_iso_build_deletes_stale_registries_beside_aura_llm():
    assert STALE in ISO_SCRIPT, (
        "build-full-iso.sh must delete %s; a stale copy there outranks /opt/aura/config" % STALE)


def test_the_autostart_names_the_registry_instead_of_inheriting_it():
    """aurora-session exports AURA_TOOLS, but the ISO's labwc autostart starts aurorad
    directly. If that path is ever reached without the export, the search order decides."""
    assert "export AURA_TOOLS=/opt/aura/config/aura-tools.json" in ISO_SCRIPT
