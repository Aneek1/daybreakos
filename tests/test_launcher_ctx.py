# tests/test_launcher_ctx.py — both launchers must serve the model the same way
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ["scripts/10-aurora-shell.sh", "scripts/13-aurora-desktop.sh"]
CANONICAL_CTX = "2048"

def test_launcher_scripts_agree_on_the_canonical_context_size():
    seen = {}
    for script in SCRIPTS:
        text = (ROOT / script).read_text(encoding="utf-8")
        sizes = re.findall(r"--ctx-size\s+(\d+)", text)
        assert sizes, "%s does not pass --ctx-size to llama-server" % script
        seen[script] = set(sizes)
    for script, sizes in seen.items():
        assert sizes == {CANONICAL_CTX}, "%s serves ctx %s, expected %s" % (
            script, sorted(sizes), CANONICAL_CTX)
