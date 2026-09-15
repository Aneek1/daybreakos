# tests/test_aura_eval_cases.py — shape of the evaluation test set
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "tests/aura_eval_cases.jsonl"
MODEL_TOOLS = ("open_terminal", "open_app", "list_apps", "system_status", "set_brightness")

def _cases():
    return [json.loads(l) for l in CASES_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

def test_case_counts():
    kinds = [c["kind"] for c in _cases()]
    assert (kinds.count("tool"), kinds.count("negative"), kinds.count("power")) == (40, 25, 8)

def test_eight_cases_per_model_callable_tool():
    expected = [c["expect"] for c in _cases() if c["kind"] == "tool"]
    for name in MODEL_TOOLS:
        assert expected.count(name) == 8, name

def test_expectations_are_valid():
    for c in _cases():
        assert set(c) <= {"say", "kind", "expect", "args"}, c
        if c["kind"] == "tool":
            assert c["expect"] in MODEL_TOOLS, c
        else:
            assert c["expect"] == "none", c

def test_argument_cases():
    cases = _cases()
    assert all(c["args"]["name"] for c in cases if c["expect"] == "open_app")
    assert all(isinstance(c["args"]["percent"], int) for c in cases if c["expect"] == "set_brightness")

def test_no_duplicate_utterances():
    says = [c["say"].lower() for c in _cases()]
    assert len(says) == len(set(says))
