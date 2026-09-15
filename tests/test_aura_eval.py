# tests/test_aura_eval.py — harness scoring with scripted model output (no server needed)
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell"))
sys.path.insert(0, str(ROOT / "tests"))
import aura_llm
import aura_eval

TOOLS = aura_llm.load_tools()

def call_returning(text):
    return lambda system, user, **kw: text

def test_load_cases_reads_all_73():
    assert len(aura_eval.load_cases()) == 73

def test_args_match():
    assert aura_eval.args_match({"name": "Text Editor"}, {"name": "  text   editor "})
    assert aura_eval.args_match({"percent": 40}, {"percent": "40"})
    assert not aura_eval.args_match({"percent": 40}, {"percent": "forty"})
    assert not aura_eval.args_match({"name": "files"}, {})

def test_correct_tool_case():
    case = {"say": "set brightness to 40", "kind": "tool", "expect": "set_brightness", "args": {"percent": 40}}
    raw = '{"reply": "Done.", "tool_calls": [{"cmd": "set_brightness", "args": {"percent": 40}}]}'
    row = aura_eval.evaluate_case(aura_llm, TOOLS, case, call_returning(raw))
    assert row["model_correct"] and row["pipeline_correct"] and row["args_correct"] and row["valid_response_json"]
    assert row["bad_reply"] is False

def test_invented_action_on_chit_chat_counts_at_model_level_only():
    case = {"say": "hi", "kind": "negative", "expect": "none"}
    raw = '{"reply": "Hello!", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}'
    row = aura_eval.evaluate_case(aura_llm, TOOLS, case, call_returning(raw))
    assert row["model_false_action"] is True
    assert row["pipeline_false_action"] is False  # _ACTION_CUE drops it

def test_server_error_row():
    case = {"say": "open a terminal", "kind": "tool", "expect": "open_terminal"}
    row = aura_eval.evaluate_case(aura_llm, TOOLS, case, call_returning(None))
    assert row["server_error"] is True
    assert row["model_correct"] is False and row["valid_response_json"] is False

def test_call_llama_restored_after_case():
    original = aura_llm.call_llama
    aura_eval.evaluate_case(aura_llm, TOOLS, {"say": "hi", "kind": "negative", "expect": "none"},
                            call_returning("Hello"))
    assert aura_llm.call_llama is original

def test_summarize_and_table():
    rows = [
        {"kind": "tool", "expect": "system_status", "server_error": False, "latency_ms": 100.0,
         "model_correct": True, "pipeline_correct": True, "valid_response_json": True, "bad_reply": False},
        {"kind": "tool", "expect": "system_status", "server_error": False, "latency_ms": 300.0,
         "model_correct": False, "pipeline_correct": False, "valid_response_json": False, "bad_reply": True},
        {"kind": "negative", "server_error": False, "latency_ms": 200.0, "model_false_action": True,
         "pipeline_false_action": False, "bad_reply": False},
    ]
    m = aura_eval.summarize(rows)
    assert m["tool_accuracy_model"] == {"count": 1, "total": 2, "rate": 0.5}
    assert m["false_action_model"] == {"count": 1, "total": 1, "rate": 1.0}
    assert m["args_accuracy_model"] == {"count": 0, "total": 0, "rate": None}
    assert m["latency_ms_p50"] == 200.0 and m["latency_ms_p95"] == 300.0
    assert m["by_tool"] == {"system_status": {"cases": 2, "model_correct": 1, "pipeline_correct": 1}}
    assert m["gate_dropped_correct_calls"] == 0
    result = {"meta": {"model_name": "m", "decoding": "free", "date": "2026-09-15"}, "metrics": m}
    table = aura_eval.format_table([result], markdown=True)
    assert table.splitlines()[0].startswith("| model | decoding | date |")
    assert "50.0% (1/2)" in table

def test_format_table_no_results():
    assert aura_eval.format_table([], markdown=False) == "no results"

def test_gate_dropped_calls_and_per_tool_table():
    # a correct model call that the keyword gate dropped, and one it kept
    rows = [
        {"kind": "tool", "expect": "system_status", "server_error": False, "latency_ms": 1.0,
         "model_correct": True, "pipeline_correct": False, "valid_response_json": True, "bad_reply": False},
        {"kind": "tool", "expect": "open_terminal", "server_error": False, "latency_ms": 1.0,
         "model_correct": True, "pipeline_correct": True, "valid_response_json": True, "bad_reply": False},
    ]
    m = aura_eval.summarize(rows)
    assert m["gate_dropped_correct_calls"] == 1
    result = {"meta": {"model_name": "m", "decoding": "free", "date": "2026-09-15"}, "metrics": m}
    table = aura_eval.format_tool_table([result])
    assert table.splitlines()[0] == "| model | decoding | tool | cases | model correct | pipeline correct |"
    assert "| m | free | system_status | 1 | 1 | 0 |" in table
    assert aura_eval.format_tool_table([]) == "no per-tool results"

def test_server_errors_count_neither_right_nor_wrong():
    rows = [
        {"kind": "negative", "expect": "none", "server_error": True, "latency_ms": 0.0,
         "model_false_action": False, "pipeline_false_action": False, "bad_reply": False},
        {"kind": "negative", "expect": "none", "server_error": False, "latency_ms": 5.0,
         "model_false_action": True, "pipeline_false_action": False, "bad_reply": False},
        {"kind": "tool", "expect": "list_apps", "server_error": True, "latency_ms": 0.0,
         "model_correct": False, "pipeline_correct": False, "valid_response_json": False, "bad_reply": True},
    ]
    m = aura_eval.summarize(rows)
    assert m["server_errors"] == 2
    assert m["false_action_model"] == {"count": 1, "total": 1, "rate": 1.0}
    assert m["tool_accuracy_model"] == {"count": 0, "total": 0, "rate": None}
    assert m["by_tool"] == {}

def test_results_problem_refuses_failed_requests_and_overwrites(tmp_path):
    out = tmp_path / "aura-eval-x.json"
    assert "1 of 3 requests failed" in aura_eval.results_problem({"server_errors": 1, "cases": 3}, out)
    assert aura_eval.results_problem({"server_errors": 0, "cases": 3}, out) is None
    out.write_text("{}", encoding="utf-8")
    assert "already exists" in aura_eval.results_problem({"server_errors": 0, "cases": 3}, out)

def test_health_url_ignores_the_path():
    assert aura_eval.health_url("http://127.0.0.1:8080/v1/chat/completions") == "http://127.0.0.1:8080/health"
    assert aura_eval.health_url("http://localhost:9000/proxy/chat") == "http://localhost:9000/health"

def test_system_facts_without_tool_flags_invented_readings():
    assert aura_eval.states_system_facts("Battery: 92%, Network: 4.2 Mbps", [])
    assert not aura_eval.states_system_facts("Battery: 92%", [{"cmd": "system_status", "args": {}, "ran": True}])
    assert not aura_eval.states_system_facts("Opening a terminal.", [])
    assert not aura_eval.states_system_facts("Hello! I can do 3 things.", [])
    case = {"say": "how much battery is left", "kind": "tool", "expect": "system_status"}
    row = aura_eval.evaluate_case(aura_llm, TOOLS, case, call_returning('{"reply": "Battery level: 100%"}'))
    assert row["system_facts_without_tool"] is True

def test_system_facts_scores_the_model_not_the_fallback():
    # ask() fills an empty or placeholder reply from the harness's own FAKE_STATUS; the model invented nothing
    battery = {"say": "how much battery is left", "kind": "tool", "expect": "system_status"}
    brightness = {"say": "what's the brightness", "kind": "negative", "expect": "none"}
    for case, raw in [(battery, '{"reply": ""}'), (battery, '{"reply": "<short confirmation>"}'),
                      (battery, '{"tool_calls": [{"cmd": "system_status"}], "reply": ""}'),
                      (brightness, '{"reply": ""}')]:
        row = aura_eval.evaluate_case(aura_llm, TOOLS, case, call_returning(raw))
        assert row["system_facts_without_tool"] is False, (case["say"], raw, row["reply"])

def test_table_reads_results_recorded_before_the_system_facts_metric():
    m = aura_eval.summarize([{"kind": "negative", "expect": "none", "server_error": False, "latency_ms": 1.0,
                              "model_false_action": False, "pipeline_false_action": False, "bad_reply": False}])
    m.pop("system_facts_without_tool")
    result = {"meta": {"model_name": "old", "decoding": "free", "date": "2026-09-15"}, "metrics": m}
    assert "| old | free |" in aura_eval.format_table([result], markdown=True)
