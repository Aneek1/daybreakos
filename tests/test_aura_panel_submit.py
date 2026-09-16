# tests/test_aura_panel_submit.py — the Aura panel must send the text the user typed
#
# The C shell has no test harness, so these read the source. That is weaker than running
# it, but it catches the defect that shipped: every message left the panel as {"q": ""}.
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHELL = ROOT / "shell/aurora-desktop/aurora-shell.c"


def _aura_submit_body():
    text = SHELL.read_text(encoding="utf-8")
    start = text.index("static void aura_submit(")
    end = text.index("\n}", start)
    return text[start:end]


def test_the_typed_text_is_copied_before_the_entry_is_cleared():
    """gtk_entry_get_text returns the entry's own buffer, not a copy. aura_submit clears
    the entry before building the request, so the text has to be owned first. Copying it
    afterwards sent an empty question: the user's bubble still looked right, because it is
    drawn before the clear, but aurorad received {"q": ""} and answered an empty turn."""
    body = _aura_submit_body()
    copy = body.index("g_strdup(gtk_entry_get_text")
    clear = body.index("gtk_entry_set_text")
    assert copy < clear, "aura_submit clears the entry before copying the typed text"


def test_the_job_takes_the_owned_copy_rather_than_a_borrowed_pointer():
    body = _aura_submit_body()
    assert "const char *q = gtk_entry_get_text" not in body, (
        "aura_submit holds a borrowed pointer into the entry buffer")
    assert re.search(r"j->q\s*=\s*q\s*;", body), (
        "j->q must take the owned copy; copying again leaks the first one")
