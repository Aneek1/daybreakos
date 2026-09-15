# Aura evaluation, power safety and model comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure Aura's model properly, stop power actions from running without a confirming click, bring the test suite in line with the native desktop, then pick the best shippable model with evidence.

**Architecture:** A stdlib evaluation harness (`tests/aura_eval.py`) runs a 73-case test set against a real llama.cpp `b4589` server, and writes JSON results that generate the README table. Power requests are recognised by a new `shell/aura_power.py`; `/ask` returns a `confirm` object, and the native Aura panel shows Power off / Cancel buttons that call the root service's existing `/system/power`. Schema-constrained output and model choice are switched only when the recorded results support it.

**Tech Stack:** Python 3 standard library (shell and harness), pytest (host tests), C + GTK3 + gtk-layer-shell (native shell), llama.cpp `b4589` prebuilt `llama-server`, bartowski Q4_K_M GGUFs.

**Spec:** `docs/superpowers/specs/2026-09-15-aura-eval-and-safety-design.md`

---

## Rules for whoever executes this plan

- **Branch** `aura-eval-safety`. Never commit to `master`. Never push.
- **Commits:** the repo-local identity is already set (`Aneek Chattopadhyay <40447609+Aneek1@users.noreply.github.com>`); don't change it. **No `Co-Authored-By` or any other trailer.** One task, one commit, unless a task says otherwise.
- **Host tests:** `python -m pytest tests -q` with the Windows Python (3.13), from the repo root. `tests/test_build_conf.sh` is not part of this suite.
- **`shell/*.py` and `tests/aura_eval.py` are standard library only.**
- **Windows consoles:** set `PYTHONUTF8=1` for scripts that print model output.
- **Git Bash quirk:** it rewrites arguments that look like paths when calling `wsl.exe`. Prefix such commands with `MSYS_NO_PATHCONV=1`, and run scripts rather than inline `$`-heavy commands.
- **Model and llama.cpp files** live outside the repo, in `$HOME/aura-eval` (`*.gguf` is git-ignored anyway).

## File map

| File | Change | Responsibility |
|---|---|---|
| `tests/aura_eval_cases.jsonl` | create | 73 evaluation cases (tool / negative / power) |
| `tests/test_aura_eval_cases.py` | create | Checks the case file's shape and counts |
| `tests/aura_eval.py` | create | Harness: run cases, score, write results, print summary |
| `tests/test_aura_eval.py` | create | Harness unit tests with scripted model output |
| `tests/results/*.json` | create | Recorded evaluation runs |
| `tests/aura_intents.jsonl`, `tests/test_aura_llm_live.sh` | delete | Replaced by the harness |
| `shell/aura_power.py` | create | Recognise power requests; build the `/ask` confirm payload |
| `tests/test_aura_power.py` | create | Unit tests, including the exact JSON text the C parser reads |
| `config/aura-tools.json` | modify | Remove `power` (Task 5); add per-tool `schema` (Task 9) |
| `shell/aurorad.py` | modify | Drop the `power` executor; `/ask` returns the confirm payload |
| `tests/test_aurorad_ask.py` | rewrite | Black-box tests for tool execution and power confirmation |
| `tests/test_aura_llm.py`, `tests/test_aura_tools.py` | modify | Match the native desktop's contract |
| `shell/aurora-desktop/aurora-shell.c`, `style.css` | modify | Confirm buttons in the Aura panel |
| `scripts/check-shell-build.sh`, `.gitattributes` | create | Compile-check the shell in WSL; keep `.sh` files LF |
| `shell/aura_llm.py` | modify | Schema mode (Task 9); hint and comment text if the model changes (Task 12) |
| `README.md`, `shell/index.html`, `shell/aurora-bridge.js`, `docs/superpowers/specs/2026-07-10-aura-local-llm-design.md` | modify | Correct model claim, legacy labels, supersession note, generated results table |
| `scripts/02-download-sources.sh`, `scripts/10-aurora-shell.sh` | modify (conditional) | Model switch, only if Task 12 chooses Qwen2.5-1.5B |

---

### Task 1: Evaluation test set

**Files:**
- Create: `tests/aura_eval_cases.jsonl`, `tests/test_aura_eval_cases.py`

- [ ] **Step 1: Write the failing test**

`tests/test_aura_eval_cases.py`:

```python
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
    for c in _cases():
        if c["expect"] == "open_app":
            assert c.get("args", {}).get("name"), c
        if c["expect"] == "set_brightness":
            assert isinstance(c.get("args", {}).get("percent"), int), c

def test_no_duplicate_utterances():
    seen = set()
    for c in _cases():
        say = c["say"].lower()
        assert say not in seen, c
        seen.add(say)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_aura_eval_cases.py -q`
Expected: 5 failed (`FileNotFoundError` for `aura_eval_cases.jsonl`)

- [ ] **Step 3: Write the case file**

`tests/aura_eval_cases.jsonl` (exactly 73 lines):

```
{"say": "open a terminal", "kind": "tool", "expect": "open_terminal"}
{"say": "i need a terminal window", "kind": "tool", "expect": "open_terminal"}
{"say": "launch the terminal please", "kind": "tool", "expect": "open_terminal"}
{"say": "can you open a shell for me", "kind": "tool", "expect": "open_terminal"}
{"say": "start a new terminal", "kind": "tool", "expect": "open_terminal"}
{"say": "opne a terminal", "kind": "tool", "expect": "open_terminal"}
{"say": "open foot", "kind": "tool", "expect": "open_terminal"}
{"say": "give me a command line", "kind": "tool", "expect": "open_terminal"}
{"say": "open the text editor", "kind": "tool", "expect": "open_app", "args": {"name": "text editor"}}
{"say": "launch firefox", "kind": "tool", "expect": "open_app", "args": {"name": "firefox"}}
{"say": "start the file manager", "kind": "tool", "expect": "open_app", "args": {"name": "file manager"}}
{"say": "open settings", "kind": "tool", "expect": "open_app", "args": {"name": "settings"}}
{"say": "can you open the calculator", "kind": "tool", "expect": "open_app", "args": {"name": "calculator"}}
{"say": "run steam", "kind": "tool", "expect": "open_app", "args": {"name": "steam"}}
{"say": "open the web browser", "kind": "tool", "expect": "open_app", "args": {"name": "web browser"}}
{"say": "lauch aurora settings", "kind": "tool", "expect": "open_app", "args": {"name": "aurora settings"}}
{"say": "what apps do i have", "kind": "tool", "expect": "list_apps"}
{"say": "list my applications", "kind": "tool", "expect": "list_apps"}
{"say": "show me installed programs", "kind": "tool", "expect": "list_apps"}
{"say": "which apps are installed", "kind": "tool", "expect": "list_apps"}
{"say": "what software is on this computer", "kind": "tool", "expect": "list_apps"}
{"say": "lsit my apps", "kind": "tool", "expect": "list_apps"}
{"say": "show the app list", "kind": "tool", "expect": "list_apps"}
{"say": "can you list all my apps", "kind": "tool", "expect": "list_apps"}
{"say": "how is the system doing", "kind": "tool", "expect": "system_status"}
{"say": "what's my uptime", "kind": "tool", "expect": "system_status"}
{"say": "is the network up", "kind": "tool", "expect": "system_status"}
{"say": "system status please", "kind": "tool", "expect": "system_status"}
{"say": "how much battery is left", "kind": "tool", "expect": "system_status"}
{"say": "give me a status report", "kind": "tool", "expect": "system_status"}
{"say": "sytem status", "kind": "tool", "expect": "system_status"}
{"say": "check the system health", "kind": "tool", "expect": "system_status"}
{"say": "set brightness to 40", "kind": "tool", "expect": "set_brightness", "args": {"percent": 40}}
{"say": "dim the screen to 20 percent", "kind": "tool", "expect": "set_brightness", "args": {"percent": 20}}
{"say": "brightness 75", "kind": "tool", "expect": "set_brightness", "args": {"percent": 75}}
{"say": "make the screen brightness 100", "kind": "tool", "expect": "set_brightness", "args": {"percent": 100}}
{"say": "turn brightness down to 10", "kind": "tool", "expect": "set_brightness", "args": {"percent": 10}}
{"say": "set the display to 55% brightness", "kind": "tool", "expect": "set_brightness", "args": {"percent": 55}}
{"say": "brightness to forty", "kind": "tool", "expect": "set_brightness", "args": {"percent": 40}}
{"say": "brightnes to 5", "kind": "tool", "expect": "set_brightness", "args": {"percent": 5}}
{"say": "hi", "kind": "negative", "expect": "none"}
{"say": "hello there", "kind": "negative", "expect": "none"}
{"say": "thanks!", "kind": "negative", "expect": "none"}
{"say": "good morning", "kind": "negative", "expect": "none"}
{"say": "what is a terminal?", "kind": "negative", "expect": "none"}
{"say": "how do i change brightness myself?", "kind": "negative", "expect": "none"}
{"say": "tell me a joke", "kind": "negative", "expect": "none"}
{"say": "what's the capital of france", "kind": "negative", "expect": "none"}
{"say": "explain what an operating system is", "kind": "negative", "expect": "none"}
{"say": "who made you", "kind": "negative", "expect": "none"}
{"say": "are you running in the cloud?", "kind": "negative", "expect": "none"}
{"say": "what does uptime mean", "kind": "negative", "expect": "none"}
{"say": "i love this desktop", "kind": "negative", "expect": "none"}
{"say": "how do apps get installed on linux", "kind": "negative", "expect": "none"}
{"say": "what time is it", "kind": "negative", "expect": "none"}
{"say": "write a haiku about the sea", "kind": "negative", "expect": "none"}
{"say": "turn off wi-fi", "kind": "negative", "expect": "none"}
{"say": "switch to light mode", "kind": "negative", "expect": "none"}
{"say": "tile my windows", "kind": "negative", "expect": "none"}
{"say": "lock the screen", "kind": "negative", "expect": "none"}
{"say": "what is brightness measured in", "kind": "negative", "expect": "none"}
{"say": "never mind", "kind": "negative", "expect": "none"}
{"say": "ok", "kind": "negative", "expect": "none"}
{"say": "why is the sky blue", "kind": "negative", "expect": "none"}
{"say": "what can you do?", "kind": "negative", "expect": "none"}
{"say": "shut down", "kind": "power", "expect": "none"}
{"say": "shut down the computer", "kind": "power", "expect": "none"}
{"say": "power off now", "kind": "power", "expect": "none"}
{"say": "restart the computer", "kind": "power", "expect": "none"}
{"say": "reboot", "kind": "power", "expect": "none"}
{"say": "please restart", "kind": "power", "expect": "none"}
{"say": "turn off the computer", "kind": "power", "expect": "none"}
{"say": "switch off the pc", "kind": "power", "expect": "none"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_aura_eval_cases.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/aura_eval_cases.jsonl tests/test_aura_eval_cases.py
git commit -m "tests: add a 73-case evaluation set for Aura"
```

---

### Task 2: Evaluation harness

**Files:**
- Create: `tests/aura_eval.py`, `tests/test_aura_eval.py`
- Delete: `tests/aura_intents.jsonl`, `tests/test_aura_llm_live.sh`

- [ ] **Step 1: Write the failing tests**

`tests/test_aura_eval.py`:

```python
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
    assert row["model_correct"] and row["pipeline_correct"] and row["args_correct"] and row["valid_json"]
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
    assert row["model_correct"] is False and row["valid_json"] is False

def test_call_llama_restored_after_case():
    original = aura_llm.call_llama
    aura_eval.evaluate_case(aura_llm, TOOLS, {"say": "hi", "kind": "negative", "expect": "none"},
                            call_returning("Hello"))
    assert aura_llm.call_llama is original

def test_summarize_and_table():
    rows = [
        {"kind": "tool", "expect": "system_status", "server_error": False, "latency_ms": 100.0,
         "model_correct": True, "pipeline_correct": True, "valid_json": True, "bad_reply": False},
        {"kind": "tool", "expect": "system_status", "server_error": False, "latency_ms": 300.0,
         "model_correct": False, "pipeline_correct": False, "valid_json": False, "bad_reply": True},
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
         "model_correct": True, "pipeline_correct": False, "valid_json": True, "bad_reply": False},
        {"kind": "tool", "expect": "open_terminal", "server_error": False, "latency_ms": 1.0,
         "model_correct": True, "pipeline_correct": True, "valid_json": True, "bad_reply": False},
    ]
    m = aura_eval.summarize(rows)
    assert m["gate_dropped_correct_calls"] == 1
    result = {"meta": {"model_name": "m", "decoding": "free", "date": "2026-09-15"}, "metrics": m}
    table = aura_eval.format_tool_table([result])
    assert table.splitlines()[0] == "| model | decoding | tool | cases | model correct | pipeline correct |"
    assert "| m | free | system_status | 1 | 1 | 0 |" in table
    assert aura_eval.format_tool_table([]) == "no per-tool results"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_aura_eval.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'aura_eval'`

- [ ] **Step 3: Write the harness**

`tests/aura_eval.py`:

```python
#!/usr/bin/env python3
"""Evaluate Aura's language model on tests/aura_eval_cases.jsonl.

Needs a running llama-server (see Task 3 of docs/superpowers/plans/2026-09-15-aura-eval-and-safety.md).

  python tests/aura_eval.py --model-name llama-3.2-1b-q4km --model-file PATH --decoding free
  python tests/aura_eval.py --summary [--markdown]
"""
import argparse, hashlib, json, os, platform, subprocess, sys, time, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "aura_eval_cases.jsonl"
RESULTS_DIR = ROOT / "tests" / "results"
FAKE_STATUS = {"battery": {"percent": 80, "status": "Discharging"}, "brightness": 50,
               "net": True, "os": "DaybreakOS"}


def load_cases(path=CASES_PATH):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(value):
    return " ".join(str(value).lower().split())


def args_match(expected, actual):
    """open_app names compare case- and whitespace-insensitively; percents as integers."""
    for key, want in expected.items():
        got = actual.get(key)
        if key == "percent":
            try:
                if int(got) != int(want):
                    return False
            except (TypeError, ValueError):
                return False
        elif got is None or _norm(got) != _norm(want):
            return False
    return True


def valid_tool_json(llm, raw):
    for candidate in llm._json_candidates(raw or ""):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict) and ("tool_calls" in obj or "reply" in obj):
            return True
    return False


def evaluate_case(llm, tools, case, call, clock=time.perf_counter):
    """Score one case at model level (raw output) and pipeline level (ask(), nothing really runs).

    `call(system, user, **kw)` returns the model's raw text, or None on failure."""
    schema_on = getattr(llm, "schema_enabled", lambda: False)()
    started = clock()
    if schema_on:
        schema = llm.response_schema(tools)
        system, user = llm.build_prompt(tools, case["say"], schema_mode=True)
        raw = call(system, user, schema=schema)
    else:
        system, user = llm.build_prompt(tools, case["say"])
        raw = call(system, user)
    latency_ms = (clock() - started) * 1000

    parsed = llm.parse_model_output(raw) if raw is not None else {"reply": "", "tool_calls": []}
    first = parsed["tool_calls"][0] if parsed["tool_calls"] else None

    executors = {t["name"]: (lambda args, name=t["name"]: f"(eval) {name}") for t in tools}
    real_call = llm.call_llama
    llm.call_llama = lambda system, user, **kw: raw
    try:
        out = llm.ask(case["say"], executors=executors, status=FAKE_STATUS, tools=tools)
    finally:
        llm.call_llama = real_call

    row = {
        "say": case["say"], "kind": case["kind"], "expect": case["expect"],
        "raw": raw, "latency_ms": round(latency_ms, 1), "server_error": raw is None,
        "model_cmd": first["cmd"] if first else None,
        "model_args": first["args"] if first else None,
        "pipeline_cmd": out["actions"][0]["cmd"] if out["actions"] else None,
        "reply": out["a"], "bad_reply": llm._reply_is_bad(out["a"]),
    }
    if case["kind"] == "tool":
        row["model_correct"] = row["model_cmd"] == case["expect"]
        row["pipeline_correct"] = row["pipeline_cmd"] == case["expect"]
        row["valid_json"] = valid_tool_json(llm, raw)
        if "args" in case:
            row["args_correct"] = row["model_correct"] and args_match(case["args"], row["model_args"] or {})
    else:
        row["model_false_action"] = row["model_cmd"] is not None
        row["pipeline_false_action"] = row["pipeline_cmd"] is not None
    return row


def _rate(rows, key):
    values = [bool(r[key]) for r in rows if key in r]
    count = sum(values)
    return {"count": count, "total": len(values), "rate": round(count / len(values), 4) if values else None}


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def _by_tool(rows):
    tools = {}
    for r in rows:
        if r["kind"] != "tool":
            continue
        entry = tools.setdefault(r["expect"], {"cases": 0, "model_correct": 0, "pipeline_correct": 0})
        entry["cases"] += 1
        entry["model_correct"] += int(bool(r["model_correct"]))
        entry["pipeline_correct"] += int(bool(r["pipeline_correct"]))
    return tools


def summarize(rows):
    latencies = [r["latency_ms"] for r in rows if not r["server_error"]]
    return {
        "cases": len(rows),
        "server_errors": sum(1 for r in rows if r["server_error"]),
        "tool_accuracy_model": _rate(rows, "model_correct"),
        "tool_accuracy_pipeline": _rate(rows, "pipeline_correct"),
        "args_accuracy_model": _rate(rows, "args_correct"),
        "false_action_model": _rate(rows, "model_false_action"),
        "false_action_pipeline": _rate(rows, "pipeline_false_action"),
        "valid_json_on_tool_cases": _rate(rows, "valid_json"),
        "bad_reply": _rate(rows, "bad_reply"),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        # _ACTION_CUE drops a call when the request has no action word; count correct calls it dropped
        "gate_dropped_correct_calls": sum(
            1 for r in rows if r.get("model_correct") and not r.get("pipeline_correct")),
        "by_tool": _by_tool(rows),
    }


HEADER = ["model", "decoding", "date", "tool acc (model)", "tool acc (pipeline)", "args acc",
          "false action (model)", "false action (pipeline)", "valid JSON", "bad reply", "p50 ms", "p95 ms"]


def _pct(metric):
    if metric["rate"] is None:
        return "-"
    return f"{100 * metric['rate']:.1f}% ({metric['count']}/{metric['total']})"


def _ms(value):
    return "-" if value is None else f"{value:.0f}"


def format_table(results, markdown):
    if not results:
        return "no results"
    rows = []
    for result in results:
        meta, m = result["meta"], result["metrics"]
        rows.append([meta["model_name"], meta["decoding"], meta["date"],
                     _pct(m["tool_accuracy_model"]), _pct(m["tool_accuracy_pipeline"]),
                     _pct(m["args_accuracy_model"]), _pct(m["false_action_model"]),
                     _pct(m["false_action_pipeline"]), _pct(m["valid_json_on_tool_cases"]),
                     _pct(m["bad_reply"]), _ms(m["latency_ms_p50"]), _ms(m["latency_ms_p95"])])
    if markdown:
        lines = ["| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    widths = [max(len(HEADER[i]), *(len(row[i]) for row in rows)) for i in range(len(HEADER))]
    fmt = "  ".join("{:<%d}" % w for w in widths)
    return "\n".join([fmt.format(*HEADER)] + [fmt.format(*row) for row in rows])


TOOL_HEADER = ["model", "decoding", "tool", "cases", "model correct", "pipeline correct"]


def format_tool_table(results):
    lines = ["| " + " | ".join(TOOL_HEADER) + " |", "|" + "---|" * len(TOOL_HEADER)]
    for result in results:
        meta = result["meta"]
        for tool, e in sorted(result["metrics"].get("by_tool", {}).items()):
            lines.append(f"| {meta['model_name']} | {meta['decoding']} | {tool} | {e['cases']} "
                         f"| {e['model_correct']} | {e['pipeline_correct']} |")
    return "\n".join(lines) if len(lines) > 2 else "no per-tool results"


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def server_ready(chat_url):
    try:
        with urllib.request.urlopen(chat_url.split("/v1/")[0] + "/health", timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def run(args):
    sys.path.insert(0, str(Path(args.shell_dir).resolve()))
    os.environ["AURA_LLM_SCHEMA"] = "1" if args.decoding == "schema" else "0"
    import aura_llm

    if args.decoding == "schema" and not hasattr(aura_llm, "schema_enabled"):
        sys.exit("this aura_llm.py has no schema mode; use --decoding free")
    if not server_ready(aura_llm.LLAMA_URL):
        sys.exit(f"llama-server is not answering at {aura_llm.LLAMA_URL}; start it first")

    tools = aura_llm.load_tools()
    cases = load_cases()[: args.limit] if args.limit else load_cases()
    rows = []
    for number, case in enumerate(cases, start=1):
        rows.append(evaluate_case(aura_llm, tools, case, aura_llm.call_llama))
        print(f"[{number}/{len(cases)}] {case['kind']:8} {case['say'][:40]:40} -> {rows[-1]['model_cmd']}",
              flush=True)

    metrics = summarize(rows)
    if metrics["server_errors"] == len(rows):
        sys.exit("every request failed; check the llama-server log (not writing a results file)")
    result = {
        "meta": {
            "date": date.today().isoformat(), "model_name": args.model_name,
            "model_file": Path(args.model_file).name, "model_sha256": sha256_file(args.model_file),
            "decoding": args.decoding, "llama_cpp": args.llama_tag, "limit": args.limit,
            "git_commit": _git("rev-parse", "HEAD"),
            "shell_commit": _git("log", "-1", "--format=%H", "--", "shell", "config"),
            "host": {"platform": platform.platform(), "processor": platform.processor(),
                     "python": platform.python_version()},
            "llm_url": aura_llm.LLAMA_URL,
        },
        "metrics": metrics,
        "cases": rows,
    }
    if args.limit:
        print(format_table([result], markdown=False))
        print("(--limit run: not writing a results file)")
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"aura-eval-{result['meta']['date']}-{args.model_name}-{args.decoding}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}")
    print(format_table([result], markdown=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", action="store_true", help="print a table of all recorded results")
    parser.add_argument("--markdown", action="store_true", help="with --summary: markdown table")
    parser.add_argument("--model-name", help="short name used in the results file name")
    parser.add_argument("--model-file", help="path to the GGUF the server is running (hashed into the results)")
    parser.add_argument("--decoding", choices=["free", "schema"], default="free")
    parser.add_argument("--llama-tag", default="b4589")
    parser.add_argument("--shell-dir", default=str(ROOT / "shell"), help="where to import aura_llm from")
    parser.add_argument("--limit", type=int, default=0, help="smoke-test the first N cases without saving")
    args = parser.parse_args(argv)

    if args.summary:
        results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS_DIR.glob("aura-eval-*.json"))]
        print(format_table(results, markdown=args.markdown))
        if args.markdown and results:
            print()
            print(format_tool_table(results))
        return
    if not (args.model_name and args.model_file):
        parser.error("--model-name and --model-file are required unless --summary is given")
    run(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_aura_eval.py -q`
Expected: `9 passed`

- [ ] **Step 5: Remove the old live fixture and script**

```bash
git rm -q tests/aura_intents.jsonl tests/test_aura_llm_live.sh
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: `9 failed, 36 passed` (the 9 failures are the pre-existing ones fixed in Tasks 5-6)

- [ ] **Step 7: Commit**

```bash
git add tests/aura_eval.py tests/test_aura_eval.py
git commit -m "tests: add Aura evaluation harness; replace the live intent script"
```

---

### Task 3: Baseline measurement (current model, current code)

No code changes. Record how the code at `46a4e28` performs before anything else changes.

**Files:**
- Create: `tests/results/aura-eval-<today>-llama-3.2-1b-q4km-baseline-free.json`

- [ ] **Step 1: Confirm the shell code is still the baseline**

```bash
git diff --quiet 46a4e28 -- shell config && echo "shell/config unchanged since 46a4e28"
```

Expected: `shell/config unchanged since 46a4e28`. If it prints nothing, Tasks 4+ have already started: create a worktree with `git worktree add ../auroraos-baseline 46a4e28` and add `--shell-dir ../auroraos-baseline/shell` to the command in Step 5.

- [ ] **Step 2: Download llama.cpp b4589 and the current model**

```bash
E="$HOME/aura-eval" && mkdir -p "$E" && cd "$E"
curl -fL -o llama-b4589-win.zip https://github.com/ggml-org/llama.cpp/releases/download/b4589/llama-b4589-bin-win-avx2-x64.zip
powershell.exe -NoProfile -Command "Expand-Archive -Force -Path llama-b4589-win.zip -DestinationPath llama-b4589"
curl -fL -o Llama-3.2-1B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf
ls -l "$E"/*.gguf; find "$E/llama-b4589" -name llama-server.exe
```

Expected: a GGUF of 807,694,464 bytes and one `llama-server.exe` path.

- [ ] **Step 3: Start the server with the distro's flags** (run in the background)

```bash
E="$HOME/aura-eval"; LLAMA=$(find "$E/llama-b4589" -name llama-server.exe | head -1)
"$LLAMA" --model "$E/Llama-3.2-1B-Instruct-Q4_K_M.gguf" --host 127.0.0.1 --port 8080 --ctx-size 2048 > "$E/server-llama1b.log" 2>&1
```

- [ ] **Step 4: Wait for it to be ready**

```bash
curl -sf --retry 60 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health && echo ready
```

Expected: `{"status":"ok"}ready`

- [ ] **Step 5: Smoke-test, then run the full baseline**

```bash
cd "/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
PYTHONUTF8=1 python tests/aura_eval.py --model-name llama-3.2-1b-q4km-baseline --model-file "$HOME/aura-eval/Llama-3.2-1B-Instruct-Q4_K_M.gguf" --decoding free --limit 3
PYTHONUTF8=1 python tests/aura_eval.py --model-name llama-3.2-1b-q4km-baseline --model-file "$HOME/aura-eval/Llama-3.2-1B-Instruct-Q4_K_M.gguf" --decoding free
```

Expected: the smoke test prints a 3-case table without writing a file; the full run prints `[73/73]`, `wrote tests\results\aura-eval-<today>-llama-3.2-1b-q4km-baseline-free.json` and a one-row table. Whatever the numbers are, they are the baseline; do not rerun to get better ones.

- [ ] **Step 6: Stop the server**

```bash
taskkill //IM llama-server.exe //F
```

- [ ] **Step 7: Commit**

```bash
git add tests/results
git commit -m "tests: record Aura baseline (Llama-3.2-1B Q4_K_M, free decoding, code at 46a4e28)"
```

---

### Task 4: Power request recognition

**Files:**
- Create: `shell/aura_power.py`, `tests/test_aura_power.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_aura_power.py`:

```python
# tests/test_aura_power.py — typed power requests and the confirmation payload
import json, pathlib, sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "shell"))
import aura_power

@pytest.mark.parametrize("text", ["shut down", "Shutdown now", "power off", "poweroff please",
                                  "turn off the computer", "switch off the pc", "please turn off my laptop"])
def test_poweroff_requests(text):
    assert aura_power.power_request(text) == "poweroff"

@pytest.mark.parametrize("text", ["restart", "reboot the computer", "please restart"])
def test_reboot_requests(text):
    assert aura_power.power_request(text) == "reboot"

@pytest.mark.parametrize("text", ["turn off wi-fi", "turn off night light", "switch off bluetooth",
                                  "power saving mode", "hello", "", None])
def test_not_power_requests(text):
    assert aura_power.power_request(text) is None

def test_confirm_payloads():
    assert aura_power.confirm_payload("poweroff") == {
        "a": "Power off now?", "actions": [],
        "confirm": {"action": "poweroff", "label": "Power off", "expires_in": 30}}
    assert aura_power.confirm_payload("reboot") == {
        "a": "Restart now?", "actions": [],
        "confirm": {"action": "reboot", "label": "Restart", "expires_in": 30}}

def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        aura_power.confirm_payload("hibernate")

def test_serialized_shape_matches_the_shell_parser():
    # aurora-shell.c finds "a", then "confirm" followed by "action", "label" and "expires_in".
    text = json.dumps(aura_power.confirm_payload("poweroff"), ensure_ascii=False)
    assert text == ('{"a": "Power off now?", "actions": [], '
                    '"confirm": {"action": "poweroff", "label": "Power off", "expires_in": 30}}')
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_aura_power.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'aura_power'`

- [ ] **Step 3: Implement**

`shell/aura_power.py`:

```python
"""Recognise typed power requests and describe the confirmation Aura shows for them.
Stdlib only (ships to the LFS target).

Nothing here powers anything off. /ask runs in the unprivileged session aurorad;
the Aura panel shows Power off / Cancel and, on a click, calls the root service's
/system/power itself."""
import re

CONFIRM_SECONDS = 30

# "turn off" / "switch off" alone also covers wi-fi, night light, bluetooth...
_DEVICE = r"(?:the\s+|my\s+|this\s+)?(?:computer|pc|laptop|machine|system)"
_POWEROFF = re.compile(r"\b(?:shut\s?down|power\s?off|(?:turn|switch)\s+off\s+" + _DEVICE + r")\b", re.I)
_REBOOT = re.compile(r"\b(?:restart|reboot)\b", re.I)

_PROMPTS = {
    "poweroff": ("Power off now?", "Power off"),
    "reboot": ("Restart now?", "Restart"),
}


def power_request(text):
    """'poweroff', 'reboot', or None."""
    text = text or ""
    if _POWEROFF.search(text):
        return "poweroff"
    if _REBOOT.search(text):
        return "reboot"
    return None


def confirm_payload(action):
    if action not in _PROMPTS:
        raise ValueError(f"not a power action: {action!r}")
    question, label = _PROMPTS[action]
    return {"a": question, "actions": [],
            "confirm": {"action": action, "label": label, "expires_in": CONFIRM_SECONDS}}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_aura_power.py -q`
Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add shell/aura_power.py tests/test_aura_power.py
git commit -m "Aura: recognise typed power requests and build a confirmation payload"
```

---

### Task 5: Take power away from the model; confirm typed requests in /ask

**Files:**
- Modify: `config/aura-tools.json`, `shell/aurorad.py`
- Rewrite: `tests/test_aurorad_ask.py`

- [ ] **Step 1: Rewrite the black-box tests**

`tests/test_aurorad_ask.py` (whole file):

```python
# tests/test_aurorad_ask.py — black-box tests hitting a live aurorad with a stub model
import json, os, subprocess, sys, time, urllib.request, pathlib, socket

ROOT = pathlib.Path(__file__).resolve().parents[1]

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def _start(tmp_path, model_reply):
    """A stub llama-server that always returns model_reply, and aurorad pointed at it."""
    port = _free_port()
    (tmp_path / "reply.txt").write_text(model_reply, encoding="utf-8")
    stub = tmp_path / "stub.py"
    stub.write_text(
        "import json, pathlib\n"
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "REPLY = (pathlib.Path(__file__).parent / 'reply.txt').read_text(encoding='utf-8')\n"
        "class H(BaseHTTPRequestHandler):\n"
        "  def do_POST(self):\n"
        "    n=int(self.headers.get('Content-Length',0)); self.rfile.read(n)\n"
        "    b=json.dumps({'choices':[{'message':{'content':REPLY}}]}).encode()\n"
        "    self.send_response(200); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)\n"
        "  def log_message(self,*a): pass\n"
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n")
    sm = subprocess.Popen([sys.executable, str(stub)])
    dport = _free_port()
    env = {**os.environ,
           "AURA_LLM_URL": f"http://127.0.0.1:{port}/v1/chat/completions",
           "AURORAD_PORT": str(dport)}
    dm = subprocess.Popen([sys.executable, str(ROOT / "shell/aurorad.py")], env=env)
    time.sleep(1.0)
    return sm, dm, dport

def _ask(dport, q):
    req = urllib.request.Request(f"http://127.0.0.1:{dport}/ask",
                                 data=json.dumps({"q": q}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())

def test_ask_runs_system_tool_from_stub_model(tmp_path):
    # On a host with no .desktop files, "open files" misses the app shortcut and reaches the model.
    sm, dm, dport = _start(tmp_path, '{"reply":"Opening.","tool_calls":[{"cmd":"open_app","args":{"name":"files"}}]}')
    try:
        out = _ask(dport, "open files")
        assert out["actions"][0]["cmd"] == "open_app"
        assert out["actions"][0]["ran"] is True
    finally:
        dm.terminate(); sm.terminate()

def test_typed_power_request_returns_confirmation_and_skips_model(tmp_path):
    sm, dm, dport = _start(tmp_path, '{"reply":"Bye.","tool_calls":[{"cmd":"power","args":{"action":"poweroff"}}]}')
    try:
        assert _ask(dport, "shut down the computer") == {
            "a": "Power off now?", "actions": [],
            "confirm": {"action": "poweroff", "label": "Power off", "expires_in": 30}}
        assert _ask(dport, "please restart")["confirm"]["action"] == "reboot"
        wifi = _ask(dport, "turn off wi-fi")          # not a power request; the stub's power call is dropped
        assert "confirm" not in wifi and wifi["actions"] == []
    finally:
        dm.terminate(); sm.terminate()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_aurorad_ask.py -q`
Expected: `1 failed, 1 passed`. `test_ask_runs_system_tool_from_stub_model` already passes, since the registry's `open_app` takes `name`. `test_typed_power_request_returns_confirmation_and_skips_model` fails, because `/ask` currently runs `_power` instead of returning `confirm`.

- [ ] **Step 3: Remove `power` from the registry**

In `config/aura-tools.json`, replace:

```
  {"name": "set_brightness", "side": "system", "description": "Set screen brightness on real hardware.",
   "args": {"percent": "integer 0-100"}},
  {"name": "power", "side": "system", "description": "Power off or restart the computer.",
   "args": {"action": "one of: poweroff, reboot"}}
]
```

with:

```
  {"name": "set_brightness", "side": "system", "description": "Set screen brightness on real hardware.",
   "args": {"percent": "integer 0-100"}}
]
```

- [ ] **Step 4: Edit `shell/aurorad.py`**

1. After `import aura_llm` (line 15), add:

```python
import aura_power
```

2. Delete the `_power` helper (lines 888-893, plus the blank line after it):

```python
            def _power(a):
                act = a.get("action")
                if act in ("poweroff", "reboot"):
                    subprocess.Popen(["systemctl", act])
                    return "Shutting down…" if act == "poweroff" else "Restarting…"
                return "I can power off or restart — which would you like?"
```

3. In the `executors = {` dict, delete the line:

```python
                "power": _power,
```

4. Replace:

```python
            ql = q.strip().lower()
            shortcut = None
```

with:

```python
            ql = q.strip().lower()
            # Power never runs from /ask (this is the unprivileged session aurorad):
            # the Aura panel asks Power off / Cancel, then calls the root /system/power.
            power = aura_power.power_request(ql)
            if power:
                self._send(aura_power.confirm_payload(power))
                return
            shortcut = None
```

5. Delete these four lines from the shortcut chain:

```python
            elif re.search(r"\b(shut\s?down|power\s?off|turn\s?off)\b", ql):
                shortcut = _power({"action": "poweroff"})
            elif re.search(r"\b(restart|reboot)\b", ql):
                shortcut = _power({"action": "reboot"})
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_aurorad_ask.py -q`
Expected: `2 passed`

- [ ] **Step 6: Confirm no power path remains in `/ask`**

```bash
grep -n "_power\|systemctl" shell/aurorad.py
```

Expected: only the `/system/power` and `/power` endpoint handlers (the `subprocess.Popen(["systemctl", act])` lines inside `do_POST` around lines 807-829) and the `aura_power.` calls; no `_power(` helper or executor.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: `5 failed, 61 passed`. The remaining failures are:
- `test_build_prompt_lists_tools_and_forbids_invention`
- `test_route_defers_ui_tool_unrun`
- `test_ask_happy_path_executes_and_returns_actions`
- `test_ask_merges_system_notes_into_reply`
- `test_names_match_index_commands`

- [ ] **Step 8: Commit**

```bash
git add config/aura-tools.json shell/aurorad.py tests/test_aurorad_ask.py
git commit -m "Aura: remove power from the model's tools; /ask asks for confirmation instead"
```

---

### Task 6: Align the unit tests with the native desktop

**Files:**
- Modify: `tests/test_aura_llm.py`, `tests/test_aura_tools.py`

- [ ] **Step 1: Edit `tests/test_aura_llm.py`**

1. In `test_build_prompt_lists_tools_and_forbids_invention`, replace `    assert "Never invent" in system` with:

```python
    assert "never invent" in system.lower()
```

2. Replace the whole `test_route_defers_ui_tool_unrun` function with:

```python
UI_TOOLS = [{"name": "show_panel", "side": "ui", "description": "Show a shell panel.",
             "args": {"panel": "panel name"}}]

def test_route_defers_ui_tool_unrun():
    # The native registry has no UI-side tools; the routing rule is still tested with one.
    actions, notes = aura_llm.route(
        [{"cmd": "show_panel", "args": {"panel": "widgets"}}], UI_TOOLS, {})
    assert actions == [{"cmd": "show_panel", "args": {"panel": "widgets"}, "ran": False}]
```

3. Replace the whole `test_ask_happy_path_executes_and_returns_actions` function with:

```python
def test_ask_happy_path_executes_and_returns_actions(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama",
        lambda s, u: '{"reply":"Opening Files.","tool_calls":[{"cmd":"open_app","args":{"name":"files"}}]}')
    out = aura_llm.ask("open files", executors={"open_app": lambda a: None}, status={})
    assert out["actions"] == [{"cmd": "open_app", "args": {"name": "files"}, "ran": True}]
    assert "Opening Files" in out["a"]
```

4. In `test_ask_merges_system_notes_into_reply`, replace `    out = aura_llm.ask("dim to 40", executors=execs, status={})` with:

```python
    out = aura_llm.ask("set brightness to 40", executors=execs, status={})
```

- [ ] **Step 2: Edit `tests/test_aura_tools.py`**

Replace the whole `test_names_match_index_commands` function with:

```python
def test_every_tool_has_an_aurorad_executor():
    """The native desktop runs every registry tool through aurorad's /ask executors."""
    src = (ROOT / "shell/aurorad.py").read_text(encoding="utf-8")
    start = src.index("executors = {")
    block = src[start: src.index("\n            }", start)]
    names = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    for t in TOOLS:
        assert t["name"] in names, f"{t['name']} has no executor in aurorad.py"
```

- [ ] **Step 3: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: `66 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/test_aura_llm.py tests/test_aura_tools.py
git commit -m "tests: align Aura tests with the native desktop's tool contract"
```

---

### Task 7: Power off / Cancel buttons in the Aura panel

**Files:**
- Create: `scripts/check-shell-build.sh`, `.gitattributes`
- Modify: `shell/aurora-desktop/aurora-shell.c`, `shell/aurora-desktop/style.css`

**Prerequisite:** WSL Ubuntu with the build packages installed. If `pkg-config --modversion gtk+-3.0` fails inside WSL, stop and report BLOCKED so the owner can run:
`wsl -d Ubuntu -- sudo apt-get install -y build-essential pkg-config libgtk-3-dev libgtk-layer-shell-dev libwayland-dev`

- [ ] **Step 1: Add the build-check script and LF rule**

`.gitattributes`:

```
*.sh text eol=lf
```

`scripts/check-shell-build.sh`:

```bash
#!/bin/bash
# Compile-check aurora-shell with the same steps as scripts/build-full-iso.sh.
# Needs: build-essential pkg-config libgtk-3-dev libgtk-layer-shell-dev libwayland-dev
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../shell/aurora-desktop" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
XML="$SRC/protocols/wlr-foreign-toplevel-management-unstable-v1.xml"
wayland-scanner client-header "$XML" "$OUT/wlr-foreign-toplevel-management-unstable-v1-client-protocol.h"
wayland-scanner private-code "$XML" "$OUT/wlr-foreign-toplevel-management-unstable-v1-protocol.c"
if ! cc -Wall -Wno-unused-parameter "$SRC/aurora-shell.c" \
        "$OUT/wlr-foreign-toplevel-management-unstable-v1-protocol.c" -I"$OUT" -O2 -o "$OUT/aurora-shell" \
        $(pkg-config --cflags --libs gtk+-3.0 gtk-layer-shell-0 wayland-client) -lm 2> "$OUT/cc.txt"; then
    cat "$OUT/cc.txt"; exit 1
fi
echo "aurora-shell built: $(stat -c %s "$OUT/aurora-shell") bytes, $(grep -c 'warning:' "$OUT/cc.txt" || true) warnings"
grep 'warning:' "$OUT/cc.txt" | sed 's#^.*/##' | sort | uniq || true
```

- [ ] **Step 2: Build the unmodified shell and keep the warning list**

```bash
cd "/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -e bash "/mnt/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos/scripts/check-shell-build.sh" | tee "$HOME/aura-eval/shell-warnings-before.txt"
```

Expected: `aurora-shell built: <N> bytes, <W> warnings`, followed by the warning lines. W may be non-zero; that is the baseline.

- [ ] **Step 3: Add a forward declaration**

In `aurora-shell.c`, directly above `/* ----- Aura: POST /ask to aurorad, return reply text ----- */`, insert:

```c
static void power_action(const char *act);   /* defined with the system menu */

```

- [ ] **Step 4: Replace the Aura request and result code**

Replace everything from the line `/* ----- Aura: POST /ask to aurorad, return reply text ----- */` down to and including the closing `}` of `aura_worker` (the function ending with `g_free(j); return NULL; }` just before `static void aura_submit`) with:

```c
/* ----- Aura: POST /ask to aurorad ----- */

/* Minimal JSON string reader: finds "key" at or after `from` and returns its
 * unescaped string value (caller frees), or NULL. aurorad writes flat UTF-8
 * JSON (ensure_ascii=False), so a full parser isn't needed. */
static char *json_string_after(const char *from, const char *key) {
    char *quoted = g_strdup_printf("\"%s\"", key);
    const char *p = strstr(from, quoted);
    g_free(quoted);
    if (!p) return NULL;
    p = strchr(p, ':'); if (!p) return NULL; p++;
    while (*p == ' ') p++;
    if (*p != '"') return NULL;
    p++;
    GString *out = g_string_new("");
    for (; *p && *p != '"'; p++) {
        if (*p == '\\' && p[1]) { p++;
            if (*p == 'n') g_string_append_c(out, '\n');
            else g_string_append_c(out, *p);
        } else g_string_append_c(out, *p);
    }
    return g_string_free(out, FALSE);
}

static int json_int_after(const char *from, const char *key, int fallback) {
    char *quoted = g_strdup_printf("\"%s\"", key);
    const char *p = strstr(from, quoted);
    g_free(quoted);
    if (!p || !(p = strchr(p, ':'))) return fallback;
    return atoi(p + 1);
}

/* raw /ask response body, or NULL if aurorad isn't up yet (caller frees) */
static char *aura_ask_json(const char *q) {
    char *jq = g_strescape(q, "");           /* escape \, ", control chars */
    char *body = g_strdup_printf("{\"q\":\"%s\"}", jq);
    g_free(jq);
    char *json = aurorad_send("POST", "/ask", body);
    g_free(body);
    return json;
}

/* aurorad's /ask returns {"a": "<reply>", "actions": [...]}, so "a" is the
 * primary key; the others are accepted for forward-compat with other bridges. */
static char *aura_reply_text(const char *json) {
    if (!json) return g_strdup("(Aura is still waking up…)");
    const char *keys[] = {"a", "reply", "answer", "text", NULL};
    for (int k = 0; keys[k]; k++) {
        char *reply = json_string_after(json, keys[k]);
        if (reply) return reply;
    }
    return g_strndup(json, 400);
}

static char *aura_ask(const char *q) {
    char *json = aura_ask_json(q);
    char *reply = aura_reply_text(json);
    g_free(json);
    return reply;
}

static GtkWidget *aura_add_msg(const char *text, gboolean user) {
    GtkWidget *row = gtk_label_new(text);
    gtk_label_set_line_wrap(GTK_LABEL(row), TRUE);
    gtk_label_set_xalign(GTK_LABEL(row), user ? 1.0 : 0.0);
    gtk_widget_set_halign(row, user ? GTK_ALIGN_END : GTK_ALIGN_START);
    GtkStyleContext *sc = gtk_widget_get_style_context(row);
    gtk_style_context_add_class(sc, user ? "msg-u" : "msg-a");
    gtk_widget_set_margin_top(row, 4);
    gtk_widget_set_margin_bottom(row, 4);
    gtk_box_pack_start(GTK_BOX(g_aura_log), row, FALSE, FALSE, 0);
    gtk_widget_show_all(row);
    return row;
}

/* Aura runs the LLM request on a worker thread so a slow on-device model never
 * freezes the desktop. The worker builds a result and hands it back to the GTK
 * main thread via g_idle_add (all widget access stays on the main thread). */
typedef struct { char *q; GtkWidget *bubble; GtkWidget *entry; } AuraJob;
typedef struct {
    char *reply; GtkWidget *bubble; GtkWidget *entry;
    char *confirm_action, *confirm_label; int confirm_secs;   /* confirm_action NULL: no buttons */
} AuraResult;

/* Power off / Cancel under a reply. Nothing runs until the button is clicked;
 * the struct is freed by its expiry timeout. */
typedef struct { char *action; GtkWidget *row; GtkWidget *bubble; gboolean settled; } AuraConfirm;

static void aura_confirm_settle(AuraConfirm *c, const char *note) {
    if (c->settled || !c->row) return;
    c->settled = TRUE;
    gtk_widget_set_sensitive(c->row, FALSE);
    char *text = g_strdup_printf("%s\n%s", gtk_label_get_text(GTK_LABEL(c->bubble)), note);
    gtk_label_set_text(GTK_LABEL(c->bubble), text);
    g_free(text);
}

static void on_aura_confirm_ok(GtkButton *b, gpointer u) {
    AuraConfirm *c = u;
    if (c->settled) return;
    aura_confirm_settle(c, g_str_equal(c->action, "reboot") ? "Restarting…" : "Shutting down…");
    power_action(c->action);                 /* root service /system/power */
}

static void on_aura_confirm_cancel(GtkButton *b, gpointer u) { aura_confirm_settle(u, "Cancelled."); }

static void on_aura_confirm_row_destroy(GtkWidget *w, gpointer u) {
    AuraConfirm *c = u;
    c->row = NULL;
    c->settled = TRUE;
}

static gboolean aura_confirm_expire(gpointer u) {
    AuraConfirm *c = u;
    aura_confirm_settle(c, "Expired.");
    g_free(c->action);
    g_free(c);
    return G_SOURCE_REMOVE;
}

static void aura_add_confirm(AuraResult *r) {
    AuraConfirm *c = g_new0(AuraConfirm, 1);
    c->action = g_strdup(r->confirm_action);
    c->bubble = r->bubble;
    c->row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_widget_set_halign(c->row, GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(c->row), "aura-confirm");
    GtkWidget *ok = gtk_button_new_with_label(r->confirm_label ? r->confirm_label : "Confirm");
    GtkWidget *cancel = gtk_button_new_with_label("Cancel");
    gtk_style_context_add_class(gtk_widget_get_style_context(ok), "destructive-action");
    g_signal_connect(ok, "clicked", G_CALLBACK(on_aura_confirm_ok), c);
    g_signal_connect(cancel, "clicked", G_CALLBACK(on_aura_confirm_cancel), c);
    g_signal_connect(c->row, "destroy", G_CALLBACK(on_aura_confirm_row_destroy), c);
    gtk_box_pack_start(GTK_BOX(c->row), ok, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(c->row), cancel, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(g_aura_log), c->row, FALSE, FALSE, 0);
    gtk_widget_show_all(c->row);
    g_timeout_add_seconds(r->confirm_secs > 0 ? r->confirm_secs : 30, aura_confirm_expire, c);
}

static gboolean aura_apply_result(gpointer data) {
    AuraResult *r = data;
    gtk_label_set_text(GTK_LABEL(r->bubble), r->reply ? r->reply : "(no reply)");
    if (r->confirm_action) aura_add_confirm(r);
    gtk_widget_set_sensitive(r->entry, TRUE);
    gtk_widget_grab_focus(r->entry);
    g_free(r->reply);
    g_free(r->confirm_action);
    g_free(r->confirm_label);
    g_free(r);
    return G_SOURCE_REMOVE;
}

static gpointer aura_worker(gpointer data) {
    AuraJob *j = data;
    char *json = aura_ask_json(j->q);      /* blocking socket I/O, off the UI thread */
    AuraResult *r = g_new0(AuraResult, 1);
    r->reply = aura_reply_text(json);
    r->bubble = j->bubble;
    r->entry = j->entry;
    const char *confirm = json ? strstr(json, "\"confirm\"") : NULL;
    if (confirm) {
        r->confirm_action = json_string_after(confirm, "action");
        r->confirm_label = json_string_after(confirm, "label");
        r->confirm_secs = json_int_after(confirm, "expires_in", 30);
    }
    /* only the two power actions are ever confirmed from the panel */
    if (r->confirm_action && !g_str_equal(r->confirm_action, "poweroff")
                          && !g_str_equal(r->confirm_action, "reboot"))
        g_clear_pointer(&r->confirm_action, g_free);
    g_free(json);
    g_idle_add(aura_apply_result, r);
    g_free(j->q);
    g_free(j);
    return NULL;
}
```

- [ ] **Step 5: Style the buttons**

Append to `shell/aurora-desktop/style.css`:

```css
.aura-confirm button { border-radius: 10px; padding: 6px 14px; }
.aura-confirm button.destructive-action { background-color: #e0564f; color: #ffffff; }
```

- [ ] **Step 6: Build again and compare warnings**

```bash
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -e bash "/mnt/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos/scripts/check-shell-build.sh" | tee "$HOME/aura-eval/shell-warnings-after.txt"
diff <(tail -n +2 "$HOME/aura-eval/shell-warnings-before.txt" | sed 's/:[0-9]*:[0-9]*:/:/') <(tail -n +2 "$HOME/aura-eval/shell-warnings-after.txt" | sed 's/:[0-9]*:[0-9]*:/:/') && echo "no new warnings"
```

Expected: `aurora-shell built: ...`, then `no new warnings`. Line numbers are stripped before comparing because the edit shifts them. Any new warning in the replaced code must be fixed before committing.

- [ ] **Step 7: Run the Python suite (unchanged by this task)**

Run: `python -m pytest tests -q`
Expected: `66 passed`

- [ ] **Step 8: Commit**

```bash
git add .gitattributes scripts/check-shell-build.sh shell/aurora-desktop/aurora-shell.c shell/aurora-desktop/style.css
git commit -m "Aura panel: confirm power requests with Power off / Cancel buttons"
```

- [ ] **Step 9: Manual VM check (owner, next ISO build)**

Not automated; record the result in the owner's notes:
1. Ask Aura "shut down", then click **Cancel**. The bubble reads "Cancelled." and nothing happens.
2. Ask "restart the computer" and wait 30 s. Both buttons disable and the bubble reads "Expired."
3. Ask "turn off wi-fi". No buttons appear.

---

### Task 8: Correct the README and label the legacy web shell

**Files:**
- Modify: `README.md`, `shell/index.html`, `shell/aurora-bridge.js`, `docs/superpowers/specs/2026-07-10-aura-local-llm-design.md`

- [ ] **Step 1: README line 8**

Replace `(llama.cpp + a bundled Qwen2.5 model) that both chats and controls the desktop —` with:

```
(llama.cpp + a quantized Llama-3.2-1B-Instruct model) that both chats and controls the desktop —
```

- [ ] **Step 2: README Aura bullet (lines 78-83)**

Replace:

```
- **Aura is a real on-device LLM.** Script 13 builds `llama-server` (llama.cpp)
  and bundles a quantized **Qwen2.5-3B-Instruct** GGUF. `aurorad` exposes `/ask`,
  which runs deterministic fast-paths for common commands (open terminal, open
  app, status, brightness, power) and defers open-ended chat to the model. It's
  a small model on CPU, so answers are useful but not cloud-grade; swap the GGUF
  in `/opt/aura/models` for a larger one if you have the RAM.
```

with:

```
- **Aura is a real on-device LLM.** Script 13 builds `llama-server` (llama.cpp).
  The model is **Llama-3.2-1B-Instruct** (Q4_K_M, about 0.8 GB), bundled by
  script 02 or downloaded after install with "Set up Aura (AI)". `aurorad`
  exposes `/ask`, which runs deterministic fast-paths for common commands (open
  terminal, open app, status, brightness) and defers open-ended chat to the
  model. Power off and restart never run from Aura directly: it asks, and only a
  click on its Power off / Restart button does it. It's a small model on CPU, so
  answers are useful but not cloud-grade; swap the GGUF in `/opt/aura/models`
  for a larger one if you have the RAM.
```

- [ ] **Step 3: Label the legacy web shell**

In `shell/index.html`, insert after line 1 (`<!doctype html>`):

```html
<!-- Legacy web shell (Firefox kiosk, scripts 10 and 12). The current desktop is shell/aurora-desktop/aurora-shell.c. -->
```

In `shell/aurora-bridge.js`, replace the first two lines:

```js
/* aurora-bridge.js — wires the concept shell to the real system via aurorad.
   Loaded after the shell's own script; degrades silently in a plain browser. */
```

with:

```js
/* aurora-bridge.js — wires the concept shell to the real system via aurorad.
   Legacy web shell only (Firefox kiosk, scripts 10 and 12); the current desktop
   is shell/aurora-desktop/aurora-shell.c. Loaded after the shell's own script;
   degrades silently in a plain browser. */
```

- [ ] **Step 4: Note the supersession in the July spec**

In `docs/superpowers/specs/2026-07-10-aura-local-llm-design.md`, insert directly below the heading `### Tool routing — the crux`:

```markdown
> **Superseded 2026-09-15** by `2026-09-15-aura-eval-and-safety-design.md` §2: the native desktop runs every tool in `aurorad`; the UI-side routing below applies only to the legacy web shell.
```

- [ ] **Step 5: Check nothing else still claims Qwen**

```bash
grep -rn "Qwen2.5-3B\|Qwen2.5 model" README.md shell scripts config
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add README.md shell/index.html shell/aurora-bridge.js docs/superpowers/specs/2026-07-10-aura-local-llm-design.md
git commit -m "docs: correct Aura's model in the README and mark the web shell as legacy"
```

---

### Task 9: Schema-constrained output (off by default)

**Files:**
- Modify: `config/aura-tools.json`, `shell/aura_llm.py`, `tests/test_aura_llm.py`, `tests/test_aura_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_aura_tools.py`:

```python
def test_every_tool_declares_a_schema_matching_its_args():
    for t in TOOLS:
        assert isinstance(t.get("schema"), dict), t["name"]
        assert set(t["schema"]) == set(t["args"]), t["name"]
```

Append to `tests/test_aura_llm.py`:

```python
def test_response_schema_limits_commands_and_argument_types():
    schema = aura_llm.response_schema(aura_llm.load_tools())
    variants = schema["properties"]["tool_calls"]["items"]["anyOf"]
    names = {v["properties"]["cmd"]["const"] for v in variants}
    assert names == {t["name"] for t in aura_llm.load_tools()}
    assert "power" not in names
    brightness = next(v for v in variants if v["properties"]["cmd"]["const"] == "set_brightness")
    assert brightness["properties"]["args"]["properties"]["percent"] == {"type": "integer", "minimum": 0, "maximum": 100}
    assert brightness["properties"]["args"]["additionalProperties"] is False
    assert schema["required"] == ["reply", "tool_calls"]

def test_response_schema_without_tools_allows_no_calls():
    assert aura_llm.response_schema([])["properties"]["tool_calls"] == {"type": "array", "maxItems": 0}

def test_free_prompt_is_unchanged():
    tools = [{"name": "open_terminal", "side": "system", "description": "Open a terminal.", "args": {}}]
    system, _ = aura_llm.build_prompt(tools, "x")
    assert system == (
        "You are Aura, the friendly on-device AI assistant built into DaybreakOS, a "
        "Linux desktop. You run entirely on the user's own device — no cloud. "
        "Chat naturally and helpfully, and keep answers concise (1-3 sentences "
        "unless the user asks for more).\n"
        "Only when the user clearly asks you to perform a desktop action, reply with "
        "a single JSON object and nothing else, for example:\n"
        '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}\n'
        "Available actions:\n- open_terminal: Open a terminal. args: none\n"
        "Use only these actions with these args; never invent them. For ordinary "
        "conversation, questions, or explanations, just answer in plain text.")

def test_schema_prompt_asks_for_json_every_time():
    system, _ = aura_llm.build_prompt(aura_llm.load_tools(), "x", schema_mode=True)
    assert "Always reply with one JSON object" in system
    assert "just answer in plain text" not in system

def test_call_llama_sends_response_format_only_with_schema(monkeypatch):
    bodies = []
    class FakeResp:
        def read(self): return b'{"choices":[{"message":{"content":"{}"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(aura_llm.urllib.request, "urlopen",
                        lambda req, timeout=None: bodies.append(aura_llm.json.loads(req.data)) or FakeResp())
    aura_llm.call_llama("S", "U")
    aura_llm.call_llama("S", "U", schema={"type": "object"})
    assert "response_format" not in bodies[0]
    assert bodies[1]["response_format"] == {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}

def test_ask_uses_schema_only_when_enabled(monkeypatch):
    seen = []
    monkeypatch.setattr(aura_llm, "call_llama",
                        lambda s, u, schema=None: seen.append((s, schema)) or '{"reply": "Hi.", "tool_calls": []}')
    monkeypatch.setenv("AURA_LLM_SCHEMA", "0")
    aura_llm.ask("hello", executors={}, status={})
    monkeypatch.setenv("AURA_LLM_SCHEMA", "1")
    aura_llm.ask("hello", executors={}, status={})
    assert seen[0][1] is None and "plain text" in seen[0][0]
    assert seen[1][1]["required"] == ["reply", "tool_calls"] and "Always reply with one JSON object" in seen[1][0]

def test_schema_default(monkeypatch):
    monkeypatch.delenv("AURA_LLM_SCHEMA", raising=False)
    assert aura_llm.schema_enabled() is (aura_llm.SCHEMA_DEFAULT == "1")
```

Also update the four existing `call_llama` stubs to accept the new keyword argument. In `test_ask_happy_path_executes_and_returns_actions`, `test_ask_merges_system_notes_into_reply`, `test_ask_falls_back_when_model_down` and `test_ask_falls_back_on_garbage`, change each `lambda s, u:` to `lambda s, u, schema=None:`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_aura_llm.py tests/test_aura_tools.py -q`
Expected: 7 failures (`AttributeError` for `response_schema`, `schema_enabled`, `SCHEMA_DEFAULT`; `TypeError` for `schema_mode`; the registry `schema` test).

- [ ] **Step 3: Add schemas to the registry**

`config/aura-tools.json` (whole file):

```json
[
  {"name": "open_terminal", "side": "system", "description": "Open a terminal window (the foot terminal).",
   "args": {}, "schema": {}},
  {"name": "open_app", "side": "system", "description": "Open an installed application by name (for example a terminal or a text editor).",
   "args": {"name": "the application name to open"},
   "schema": {"name": {"type": "string", "minLength": 1}}},
  {"name": "list_apps", "side": "system", "description": "List the applications installed on this system.",
   "args": {}, "schema": {}},
  {"name": "system_status", "side": "system", "description": "Report battery, network, and uptime from real hardware.",
   "args": {}, "schema": {}},
  {"name": "set_brightness", "side": "system", "description": "Set screen brightness on real hardware.",
   "args": {"percent": "integer 0-100"},
   "schema": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}}}
]
```

- [ ] **Step 4: Implement schema mode in `shell/aura_llm.py`**

1. After `LLAMA_TIMEOUT = ...` (line 33), add:

```python
# "1" sends a JSON schema so llama-server can only produce {reply, tool_calls}
# with registry tools; see tests/results for the measurement behind the default.
SCHEMA_DEFAULT = "0"

def schema_enabled():
    return os.environ.get("AURA_LLM_SCHEMA", SCHEMA_DEFAULT) == "1"

def response_schema(tools):
    """JSON schema for llama-server's response_format: a reply plus tool calls
    restricted to registry tools and their declared argument types."""
    variants = []
    for t in tools:
        props = t.get("schema", {})
        variants.append({
            "type": "object",
            "properties": {
                "cmd": {"const": t["name"]},
                "args": {"type": "object", "properties": props,
                         "required": sorted(props), "additionalProperties": False},
            },
            "required": ["cmd", "args"],
        })
    calls = {"type": "array", "items": {"anyOf": variants}} if variants else {"type": "array", "maxItems": 0}
    return {"type": "object",
            "properties": {"reply": {"type": "string"}, "tool_calls": calls},
            "required": ["reply", "tool_calls"]}
```

2. Replace the whole `build_prompt` function with:

```python
def build_prompt(tools, user_text, schema_mode=False):
    lines = []
    for t in tools:
        args = ", ".join(f"{k} ({v})" for k, v in t["args"].items()) or "none"
        lines.append(f'- {t["name"]}: {t["description"]} args: {args}')
    example = '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}\n'
    intro = (
        "You are Aura, the friendly on-device AI assistant built into DaybreakOS, a "
        "Linux desktop. You run entirely on the user's own device — no cloud. "
        "Chat naturally and helpfully, and keep answers concise (1-3 sentences "
        "unless the user asks for more).\n"
    )
    if schema_mode:
        rule = ("Always reply with one JSON object that has a \"reply\" string and a \"tool_calls\" "
                "list. Leave tool_calls empty for ordinary conversation, questions, or explanations. "
                "Add a tool call only when the user clearly asks you to perform a desktop action, "
                "for example:\n")
        closing = "Use only these actions with these args; never invent them."
    else:
        rule = ("Only when the user clearly asks you to perform a desktop action, reply with "
                "a single JSON object and nothing else, for example:\n")
        closing = ("Use only these actions with these args; never invent them. For ordinary "
                   "conversation, questions, or explanations, just answer in plain text.")
    system = intro + rule + example + "Available actions:\n" + "\n".join(lines) + "\n" + closing
    return system, user_text
```

3. Replace the whole `call_llama` function with:

```python
def call_llama(system, user, schema=None):
    """POST to llama-server; return assistant content or None on any failure."""
    payload = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 128,
    }
    if schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    req = urllib.request.Request(LLAMA_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=LLAMA_TIMEOUT) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]
    except Exception:
        # Contract: return content or None on ANY failure (URLError, OSError,
        # IncompleteRead/HTTPException, non-dict JSON -> TypeError, missing keys, etc.).
        return None
```

4. In `ask`, replace:

```python
    system, user = build_prompt(tools, user_text)
    raw = call_llama(system, user)
```

with:

```python
    schema = response_schema(tools) if schema_enabled() else None
    system, user = build_prompt(tools, user_text, schema_mode=schema is not None)
    raw = call_llama(system, user, schema=schema)
```

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests -q`
Expected: `74 passed`

- [ ] **Step 6: Commit**

```bash
git add config/aura-tools.json shell/aura_llm.py tests/test_aura_llm.py tests/test_aura_tools.py
git commit -m "Aura: optional schema-constrained output (AURA_LLM_SCHEMA, off by default)"
```

---

### Task 10: Measure free vs schema decoding on Llama-3.2-1B and set the default

**Files:**
- Create: two results files in `tests/results/`
- Modify (only if schema wins): `shell/aura_llm.py`

- [ ] **Step 1: Start the server** (background; same command as Task 3 Step 3), then wait for it

```bash
curl -sf --retry 60 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health && echo ready
```

- [ ] **Step 2: Check that b4589 accepts the schema**

```bash
cd "/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
PYTHONUTF8=1 python tests/aura_eval.py --model-name llama-3.2-1b-q4km --model-file "$HOME/aura-eval/Llama-3.2-1B-Instruct-Q4_K_M.gguf" --decoding schema --limit 3
```

Expected: a 3-row table with `server_errors` 0 in each case, meaning replies were produced.
- If it exits with "every request failed", read `$HOME/aura-eval/server-llama1b.log`.
- A grammar error there means b4589 rejects part of the schema. Stop and report BLOCKED with the log lines.

- [ ] **Step 3: Record both runs**

```bash
M="$HOME/aura-eval/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
PYTHONUTF8=1 python tests/aura_eval.py --model-name llama-3.2-1b-q4km --model-file "$M" --decoding free
PYTHONUTF8=1 python tests/aura_eval.py --model-name llama-3.2-1b-q4km --model-file "$M" --decoding schema
taskkill //IM llama-server.exe //F
```

- [ ] **Step 4: Apply the decision rule**

The spec's rule, using model-level metrics: schema wins if its false-action rate is lower and its tool accuracy is no more than 2 points below free.

```bash
PYTHONUTF8=1 python - <<'PY'
import json, pathlib
def latest(name, decoding):
    files = sorted(pathlib.Path("tests/results").glob(f"aura-eval-*-{name}-{decoding}.json"))
    return json.loads(files[-1].read_text(encoding="utf-8"))["metrics"]
free, schema = latest("llama-3.2-1b-q4km", "free"), latest("llama-3.2-1b-q4km", "schema")
fa_f, fa_s = free["false_action_model"]["rate"], schema["false_action_model"]["rate"]
acc_f, acc_s = free["tool_accuracy_model"]["rate"], schema["tool_accuracy_model"]["rate"]
decision = "schema" if (fa_s < fa_f and acc_s >= acc_f - 0.02) else "free"
summary = (f"false action: free {fa_f:.3f}, schema {fa_s:.3f}; "
           f"tool accuracy: free {acc_f:.3f}, schema {acc_s:.3f}")
print(summary)
print("DECISION:", decision)
(pathlib.Path.home() / "aura-eval" / "commit-msg.txt").write_text(
    f"tests: measure free vs schema decoding on Llama-3.2-1B\n\n{summary}\nDecision: {decision}\n",
    encoding="utf-8", newline="\n")
PY
```

- [ ] **Step 5: If the decision is `schema`, make it the default**

In `shell/aura_llm.py`, change `SCHEMA_DEFAULT = "0"` to `SCHEMA_DEFAULT = "1"`, then run `python -m pytest tests -q` (expected `74 passed`). If the decision is `free`, change nothing.

- [ ] **Step 6: Commit**

```bash
git add tests/results shell/aura_llm.py
git commit -F "$HOME/aura-eval/commit-msg.txt"
```

The message file was written by Step 4 and holds the measured numbers and the decision.

---

### Task 11: Measure Qwen2.5-1.5B and Qwen2.5-3B

Qwen2.5-3B is measured for comparison only. It is never bundled or downloaded by DaybreakOS, because its licence is non-commercial.

**Files:**
- Create: four results files in `tests/results/`

- [ ] **Step 1: Download both models**

```bash
cd "$HOME/aura-eval"
curl -fL -o Qwen2.5-1.5B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
curl -fL -o Qwen2.5-3B-Instruct-Q4_K_M.gguf https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf
ls -l Qwen2.5-*.gguf
```

Expected sizes: 986,048,768 and 1,929,903,264 bytes.

- [ ] **Step 2: For each model, start the server, run both decodings, stop the server**

For `Qwen2.5-1.5B` (model name `qwen2.5-1.5b-q4km`), then for `Qwen2.5-3B` (model name `qwen2.5-3b-q4km`):

```bash
E="$HOME/aura-eval"; LLAMA=$(find "$E/llama-b4589" -name llama-server.exe | head -1)
"$LLAMA" --model "$E/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf" --host 127.0.0.1 --port 8080 --ctx-size 2048 > "$E/server-qwen15.log" 2>&1
```
(run in the background), then:

```bash
curl -sf --retry 60 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health && echo ready
cd "/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
M="$HOME/aura-eval/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
PYTHONUTF8=1 python tests/aura_eval.py --model-name qwen2.5-1.5b-q4km --model-file "$M" --decoding free
PYTHONUTF8=1 python tests/aura_eval.py --model-name qwen2.5-1.5b-q4km --model-file "$M" --decoding schema
taskkill //IM llama-server.exe //F
```

Repeat with `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, `server-qwen3b.log` and `--model-name qwen2.5-3b-q4km`.

- [ ] **Step 3: Print the summary**

Run: `PYTHONUTF8=1 python tests/aura_eval.py --summary`
Expected: 7 rows (baseline, Llama free and schema, Qwen 1.5B free and schema, Qwen 3B free and schema).

- [ ] **Step 4: Commit**

```bash
git add tests/results
git commit -m "tests: measure Qwen2.5-1.5B and Qwen2.5-3B (3B as a comparison only)"
```

---

### Task 12: Choose the shipped model and publish the results

**Files:**
- Modify: `README.md`
- Modify (only if Qwen2.5-1.5B is chosen): `scripts/02-download-sources.sh`, `scripts/10-aurora-shell.sh`, `shell/aurorad.py`, `shell/aura_llm.py`

- [ ] **Step 1: Apply the selection rule**

The rule, among shippable models only, in the decoding chosen in Task 10:
- highest model-level tool accuracy, with false-action rate as the tie-breaker
- p95 latency within 2× of Llama-3.2-1B

```bash
cd "/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
PYTHONUTF8=1 python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "shell")
import aura_llm
decoding = "schema" if aura_llm.SCHEMA_DEFAULT == "1" else "free"
def latest(name):
    files = sorted(pathlib.Path("tests/results").glob(f"aura-eval-*-{name}-{decoding}.json"))
    return json.loads(files[-1].read_text(encoding="utf-8"))["metrics"]
shippable = {n: latest(n) for n in ("llama-3.2-1b-q4km", "qwen2.5-1.5b-q4km")}
limit = 2 * shippable["llama-3.2-1b-q4km"]["latency_ms_p95"]
eligible = {n: m for n, m in shippable.items() if m["latency_ms_p95"] <= limit}
best = max(eligible, key=lambda n: (eligible[n]["tool_accuracy_model"]["rate"],
                                    -eligible[n]["false_action_model"]["rate"]))
m = eligible[best]
print("decoding:", decoding)
print("CHOSEN:", best)
print("LoRA follow-up spec needed:", m["false_action_model"]["rate"] > 0.05 or m["tool_accuracy_model"]["rate"] < 0.90)
ref = latest("qwen2.5-3b-q4km")
print(f"reference (not shippable) qwen2.5-3b: tool accuracy {ref['tool_accuracy_model']['rate']}, "
      f"false action {ref['false_action_model']['rate']}")
lora = m["false_action_model"]["rate"] > 0.05 or m["tool_accuracy_model"]["rate"] < 0.90
(pathlib.Path.home() / "aura-eval" / "commit-msg.txt").write_text(
    "Aura: choose the shipped model from the evaluation and publish the results\n\n"
    f"Decoding: {decoding}\nChosen: {best}\nLoRA follow-up spec needed: {lora}\n",
    encoding="utf-8", newline="\n")
PY
```

- [ ] **Step 2: If `CHOSEN: llama-3.2-1b-q4km`, skip to Step 7.**

- [ ] **Step 3 (Qwen2.5-1.5B only): `scripts/02-download-sources.sh`**

Replace:

```bash
AURA_MODEL="Llama-3.2-1B-Instruct-Q4_K_M.gguf"
AURA_MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/${AURA_MODEL}"
```

with:

```bash
AURA_MODEL="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
AURA_MODEL_URL="https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/${AURA_MODEL}"
```

- [ ] **Step 4 (Qwen2.5-1.5B only): `scripts/10-aurora-shell.sh` line 132**

Replace `--model /opt/aura/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf` with `--model /opt/aura/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`.

- [ ] **Step 5 (Qwen2.5-1.5B only): `shell/aurorad.py`**

1. Replace `# Aura downloads a ~0.8 GB model on demand; aura-llm-launch then serves it.` with `# Aura downloads a ~1.0 GB model on demand; aura-llm-launch then serves it.`
2. Replace:

```python
    "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/"
    "resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf")
```

with:

```python
    "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/"
    "resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
```

3. Replace `    dest = os.path.join(AURA_MODEL_DIR, "Llama-3.2-1B-Instruct-Q4_K_M.gguf")` with `    dest = os.path.join(AURA_MODEL_DIR, "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")`.
4. Replace `            # Fast-path obvious imperative commands. The bundled 1B model is not` with `            # Fast-path obvious imperative commands. The bundled small model is not`.

The launcher picks the largest GGUF, so an installed system that still has the 1B file will serve the larger Qwen file.

- [ ] **Step 6 (Qwen2.5-1.5B only): `shell/aura_llm.py` and README model text**

1. Replace `# The bundled 1B model frequently hallucinates a tool call for plain chit-chat` with `# Small on-device models can hallucinate a tool call for plain chit-chat`.
2. Replace `'(~0.8 GB, one time). Until then I can still open apps and '` with `'(~1.0 GB, one time). Until then I can still open apps and '`.
3. In `README.md`:
   - replace `a quantized Llama-3.2-1B-Instruct model` with `a quantized Qwen2.5-1.5B-Instruct model`
   - replace `The model is **Llama-3.2-1B-Instruct** (Q4_K_M, about 0.8 GB), bundled by` with `The model is **Qwen2.5-1.5B-Instruct** (Q4_K_M, about 1.0 GB, Apache-2.0), bundled by`

Then run `python -m pytest tests -q`. Expected: `74 passed`.

- [ ] **Step 7: Add the generated results table to the README**

Insert this block directly above the line `## After first boot`:

```markdown
## Aura evaluation

73 cases: 40 tool requests, 25 messages that must not trigger a tool, 8 power requests. Measured with llama.cpp `b4589` on the development host; latency is only comparable within this table. Generated by `python tests/aura_eval.py --summary --markdown`.

*Model* columns score the model's own output. *Pipeline* columns run that same output through `aura_llm.ask()`, whose keyword gate (`_ACTION_CUE`) drops a tool call when the request contains no action word. Some realistic requests, such as "how much battery is left", have none, so pipeline accuracy sits below model accuracy by design; the per-tool table shows where. Not covered by these cases: out-of-range brightness values and empty input.

<!-- aura-eval:start -->
<!-- aura-eval:end -->

```

Then fill it from the recorded results (no hand-typed numbers):

```bash
PYTHONUTF8=1 python - <<'PY'
import pathlib, re, subprocess, sys
table = subprocess.run([sys.executable, "tests/aura_eval.py", "--summary", "--markdown"],
                       capture_output=True, text=True, check=True).stdout.strip()
readme = pathlib.Path("README.md")
text = readme.read_text(encoding="utf-8")
new = re.sub(r"<!-- aura-eval:start -->.*?<!-- aura-eval:end -->",
             lambda _: "<!-- aura-eval:start -->\n" + table + "\n<!-- aura-eval:end -->", text, flags=re.S)
assert new != text, "markers not found"
readme.write_text(new, encoding="utf-8", newline="\n")
print(table)
PY
```

- [ ] **Step 8: Commit**

```bash
git add README.md scripts/02-download-sources.sh scripts/10-aurora-shell.sh shell/aurorad.py shell/aura_llm.py
git commit -F "$HOME/aura-eval/commit-msg.txt"
```

`git add` stages nothing for files this task didn't change. The message file was written by Step 1.

- [ ] **Step 9: Report**

Tell the owner:
- the chosen model and decoding
- the LoRA follow-up flag
- the README table
- that the VM check from Task 7 Step 9 is still pending, if it hasn't been done
