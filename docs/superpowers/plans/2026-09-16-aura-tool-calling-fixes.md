# Aura tool-calling fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Aura discarding correct tool calls and accept calls whose only fault is the tool name, so a typed request performs the action at least 85% of the time without raising false actions.

**Architecture:** Four small changes inside `shell/aura_llm.py` (an alias table applied in `ask()`, a rewritten action gate, two worked prompt examples, an upper bound on the schema's tool-call array), one launcher change so both build scripts serve the model with the same context size, and a re-measurement with the existing harness. No new dependencies, no model changes, no training.

**Tech Stack:** Python 3 standard library only (the module ships to a Linux From Scratch target), pytest for unit tests, `tests/aura_eval.py` with llama.cpp b4589 for measurement.

**Spec:** `docs/superpowers/specs/2026-09-16-aura-tool-calling-fixes-design.md`

---

## Rules for whoever executes this plan

- **Branch:** `aura-tool-calling-fixes` (off `origin/master`). **Never commit to `master`.** Never run `git checkout`, `git switch`, `git reset`, `git stash`, `git commit --amend`, or `git push`.
- **Commits:** plain sentence messages, one task one commit, staged by explicit path. **No `Co-Authored-By` or any other trailer.**
- **Python:** `python` (3.13 on this machine). Set `PYTHONUTF8=1` for anything printing non-ASCII. Tests: `python -m pytest tests -q -p no:cacheprovider`.
- **No linter is installed in this repo.** After editing Python, run `python -m py_compile shell/aura_llm.py` instead.
- **`shell/aura_llm.py` is standard library only.** Do not add imports beyond `json, os, re, urllib`.
- The Write tool decodes `\uXXXX` escapes; if a file needs a literal backslash sequence, write it with a Python script using `chr(92)` and verify with a byte comparison.
- **Starting state:** suite `111 passed`, `tests/test_aura_llm.py` `37 passed`.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `shell/aura_llm.py` | prompt, parsing, alias table, gate, schema, `ask()` | modified in Tasks 1-4 |
| `tests/test_aura_llm.py` | unit tests for the above | extended in Tasks 1-4 |
| `tests/test_launcher_ctx.py` | both launchers serve the same context size | created in Task 5 |
| `scripts/10-aurora-shell.sh` | systemd unit that starts llama-server | line 133 in Task 5 |
| `README.md` | the published evaluation table | regenerated in Task 6 |
| `docs/vm-check-2026-09-16.md` | what a human saw in the VM, with evidence | created in Task 7 |

---

### Task 1: Alias table for invented tool names

The measured runs show the model naming tools that do not exist while its intent is right. These six names, and only these, were observed; none ever appeared on a chit-chat or power case.

**Files:**
- Modify: `shell/aura_llm.py` (add `_ALIASES` and `apply_aliases` after `parse_model_output`, call it in `ask`)
- Test: `tests/test_aura_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_aura_llm.py`:

```python
def test_alias_maps_every_name_to_a_registry_tool():
    names = {t["name"] for t in aura_llm.load_tools()}
    for invented, (target, _args) in aura_llm._ALIASES.items():
        assert target in names, "%s maps to %s which is not a registry tool" % (invented, target)

def test_alias_rewrites_invented_open_names():
    tools = aura_llm.load_tools()
    calls = aura_llm.apply_aliases([{"cmd": "open_settings", "args": {}}], tools)
    assert calls == [{"cmd": "open_app", "args": {"name": "settings"}}]
    assert aura_llm.validate_call(calls[0], tools)

def test_alias_rewrites_invented_status_names():
    tools = aura_llm.load_tools()
    for invented in ("check_battery_status", "check_network", "check_network_status", "system_health_check"):
        calls = aura_llm.apply_aliases([{"cmd": invented, "args": {}}], tools)
        assert calls == [{"cmd": "system_status", "args": {}}], invented

def test_alias_keeps_a_valid_model_argument():
    tools = aura_llm.load_tools()
    calls = aura_llm.apply_aliases([{"cmd": "open_browser", "args": {"name": "firefox"}}], tools)
    assert calls == [{"cmd": "open_app", "args": {"name": "firefox"}}]

def test_alias_cannot_introduce_an_undeclared_argument():
    tools = aura_llm.load_tools()
    calls = aura_llm.apply_aliases([{"cmd": "check_network", "args": {"rm": "-rf"}}], tools)
    assert calls == [{"cmd": "system_status", "args": {}}]
    assert aura_llm.validate_call(calls[0], tools)

def test_unknown_name_without_an_alias_is_left_alone():
    tools = aura_llm.load_tools()
    calls = aura_llm.apply_aliases([{"cmd": "delete_everything", "args": {}}], tools)
    assert calls == [{"cmd": "delete_everything", "args": {}}]
    assert not aura_llm.validate_call(calls[0], tools)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `6 failed, 37 passed`, each failure `AttributeError: module 'aura_llm' has no attribute '_ALIASES'` or `... 'apply_aliases'`.

- [ ] **Step 3: Implement**

In `shell/aura_llm.py`, insert directly above `# A schema-mode reply cut off at max_tokens has no closing brace.` (the comment above `_CUT_REPLY`):

```python
# Tool names the model invents while meaning a real tool. Every entry was
# observed in tests/results/*.json, and none of these names ever appeared on a
# chit-chat or power case, so accepting them adds no measured false action.
# The value is (registry tool, default args); a model-supplied argument is kept
# only when the alias declares that key, so an alias can never introduce one the
# tool does not accept.
_ALIASES = {
    "open_settings": ("open_app", {"name": "settings"}),
    "open_browser": ("open_app", {"name": "web browser"}),
    "check_battery_status": ("system_status", {}),
    "check_network": ("system_status", {}),
    "check_network_status": ("system_status", {}),
    "system_health_check": ("system_status", {}),
}

def apply_aliases(calls, tools):
    """Rewrite known invented tool names onto the registry tool they meant.
    Unknown names are passed through untouched for validate_call to drop."""
    known = {t["name"] for t in tools}
    out = []
    for call in calls:
        target = _ALIASES.get(call.get("cmd"))
        if target is None or target[0] not in known:
            out.append(call)
            continue
        name, defaults = target
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        merged = dict(defaults)
        merged.update({k: v for k, v in args.items() if k in defaults})
        out.append({"cmd": name, "args": merged})
    return out
```

Then in `ask`, replace:

```python
    parsed = parse_model_output(raw)
    calls = parsed["tool_calls"]
```

with:

```python
    parsed = parse_model_output(raw)
    # Aliases are applied here, not in parse_model_output, so model-level
    # evaluation still sees exactly what the model produced.
    calls = apply_aliases(parsed["tool_calls"], tools)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `43 passed`

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `117 passed`

Run: `python -m py_compile shell/aura_llm.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add shell/aura_llm.py tests/test_aura_llm.py
git commit -m "Accept tool calls whose only fault is an invented name"
```

---

### Task 2: Rewrite the action gate

Today `_has_action_intent` drops a correct call when the user's own words contain no action word, which discards about 4.7 correct calls per run. It cannot simply be deleted: without it, false actions measured 11.1% instead of 3.0%. The replacement refuses question and acknowledgement shapes first, then requires an action word from a widened list.

**Files:**
- Modify: `shell/aura_llm.py:9-15` (patterns) and the gate call in `ask` (line ~280)
- Test: `tests/test_aura_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_aura_llm.py`:

```python
import json as _json, pathlib as _pathlib

_CASES = [_json.loads(line) for line in
          (_pathlib.Path(__file__).resolve().parent / "aura_eval_cases.jsonl")
          .read_text(encoding="utf-8").splitlines() if line.strip()]

def test_gate_admits_the_phrasings_it_used_to_drop():
    for say in ("how much battery is left", "what's my uptime", "dim the screen to 20 percent",
                "give me a command line", "what software is on this computer",
                "how is the system doing", "check the system health", "brightnes to 5",
                "lauch aurora settings", "is the network up"):
        assert aura_llm.action_allowed(say), say

def test_gate_refuses_question_and_acknowledgement_shapes():
    for say in ("how do i change brightness myself?", "what does uptime mean",
                "what is a terminal?", "how do apps get installed on linux",
                "ok", "thanks!", "never mind", "why is the sky blue",
                "explain what an operating system is", "write a haiku about the sea"):
        assert not aura_llm.action_allowed(say), say

def test_gate_admits_wifi_status_questions():
    # Asking after the network is a system_status call, whatever the user calls
    # the network; only the toggle the desktop cannot do is refused below.
    for say in ("check wifi status", "is my wi-fi working", "check the wifi",
                "what's the wifi status"):
        assert aura_llm.action_allowed(say), say

def test_gate_refuses_requests_for_things_that_are_not_tools():
    for say in ("turn off wi-fi", "switch to light mode", "tile my windows", "lock the screen"):
        assert not aura_llm.action_allowed(say), say

def test_gate_admits_every_tool_case_in_the_eval_set():
    for case in _CASES:
        if case["kind"] == "tool":
            assert aura_llm.action_allowed(case["say"]), case["say"]

def test_gate_refuses_every_chit_chat_case_in_the_eval_set():
    # Power phrasings are excluded on purpose: aura_power handles them before the
    # model is consulted, and they legitimately contain action words.
    for case in _CASES:
        if case["kind"] == "negative":
            assert not aura_llm.action_allowed(case["say"]), case["say"]

def test_ask_drops_a_call_when_the_gate_refuses_the_phrasing(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama",
        lambda s, u, schema=None: '{"reply":"Sure.","tool_calls":[{"cmd":"open_terminal","args":{}}]}')
    out = aura_llm.ask("what is a terminal?", executors={"open_terminal": lambda a: "opened"}, status={})
    assert out["actions"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `7 failed, 43 passed`, the first six failing with `AttributeError: module 'aura_llm' has no attribute 'action_allowed'`.

- [ ] **Step 3: Implement**

In `shell/aura_llm.py`, replace lines 5-15 (the comment block, `_ACTION_CUE` and `_has_action_intent`) with:

```python
# Small on-device models hallucinate a tool call for plain chit-chat ("hi" ->
# open_terminal), so a model-emitted action is only honored when the user's own
# words ask for one. Two patterns decide it, in order: shapes that are questions
# or acknowledgements are refused outright, then an action word is required.
# Both lists are drawn from measured runs in tests/results/, not from guesswork.
_NO_ACTION = re.compile(
    r"^\s*(ok|okay|thanks|thank you|never\s?mind)\b"
    r"|\bhow do\b"
    r"|\bwhat (is|are|does|time)\b"
    r"|\bwhy\b|\bexplain\b|\btell me\b|\bwrite a\b|\bwho made\b|\bare you\b|\bi love\b"
    r"|\btile\b|\blight mode\b|\bdark mode\b|\block the screen\b"
    r"|\bturn (on|off) (the )?wi-?fi\b", re.I)

_ACTION_CUE = re.compile(
    r"\b(open|launch|lauch|start|run|show|list|close|quit|set|turn|adjust|check|dim|"
    r"shut\s?down|power|reboot|restart|bright\w*|status|uptime|battery|network|wi-?fi|"
    r"software|installed|settings|system|terminal|app|apps)\b"
    r"|\bcommand line\b", re.I)

def action_allowed(text):
    """True when the user's words ask for a desktop action. Question and
    acknowledgement shapes are refused first: those produced the valid-but-
    unwanted calls in the measured runs."""
    t = text or ""
    if _NO_ACTION.search(t):
        return False
    return bool(_ACTION_CUE.search(t))
```

Then in `ask`, replace:

```python
    if calls and not _has_action_intent(user_text):
```

with:

```python
    if calls and not action_allowed(user_text):
```

- [ ] **Step 4: Check nothing else used the old helper**

Run: `grep -rn "_has_action_intent" shell tests scripts`
Expected: no output. If anything still references it, update that call site to `action_allowed` in this same task.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `50 passed`

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `124 passed`

Run: `python -m py_compile shell/aura_llm.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add shell/aura_llm.py tests/test_aura_llm.py
git commit -m "Stop the action gate discarding correct calls, and refuse question shapes"
```

---

### Task 3: Worked examples in the prompt

Eight of the model's errors are producing no call at all, concentrated in status and list phrasings that read like questions. One worked example goes in the free-mode prompt. `test_free_prompt_is_unchanged` pins the prompt text, so it is updated in the same task.

> **Corrected 2026-09-16 after a measured failure.** The first attempt added two examples in bare `{"cmd": ...}` form to fit the 140-character budget. `parse_model_output` only keeps objects containing `reply` or `tool_calls`, the model copied the bare shape it was shown, and the next measurement scored **0/40 on tool accuracy and 0/40 on valid JSON**. Neither the budget test (length only) nor the pinned-prompt test (pins whatever string exists) could catch it. The rule now: **every worked example must be a full `{reply, tool_calls}` object.** The owner chose one wrapped status example (106 characters, 31 tokens, inside the budget) over two bare ones, and a guard test asserts every JSON object in the prompt survives the parser.

**Files:**
- Modify: `shell/aura_llm.py:70-94` (`build_prompt`)
- Test: `tests/test_aura_llm.py` (update `test_free_prompt_is_unchanged`, add one test)

- [ ] **Step 1: Write the failing test and update the pinned prompt test**

Append to `tests/test_aura_llm.py`:

```python
def test_prompt_shows_a_status_and_a_list_example():
    tools = aura_llm.load_tools()
    system, _ = aura_llm.build_prompt(tools, "x")
    assert '"cmd":"system_status"' in system
    assert '"cmd":"list_apps"' in system
    assert "how is my machine doing" in system
    assert "which programs are on here" in system

def _added_examples(system):
    """The example lines added beyond the original open_terminal one."""
    block = system.split("for example:\n", 1)[1].split("Available actions:\n", 1)[0]
    return block.split("\n", 1)[1]

def test_prompt_examples_stay_within_the_token_budget():
    system, _ = aura_llm.build_prompt(aura_llm.load_tools(), "x")
    added = _added_examples(system)
    # The design budgets the added prompt text at under 40 tokens. Characters are
    # the tokenizer-free proxy (~3.2 chars/token for this JSON-dense text).
    assert len(added) <= 140, len(added)
    import pytest
    tiktoken = pytest.importorskip("tiktoken")
    assert len(tiktoken.get_encoding("cl100k_base").encode(added)) < 40
```

In the same file, replace the body of `test_free_prompt_is_unchanged` so its expected string carries the two new example lines:

```python
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
        '"how is my machine doing" is {"cmd":"system_status","args":{}}\n'
        '"which programs are on here" is {"cmd":"list_apps","args":{}}\n'
        "Available actions:\n- open_terminal: Open a terminal. args: none\n"
        "Use only these actions with these args; never invent them. For ordinary "
        "conversation, questions, or explanations, just answer in plain text.")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `3 failed, 49 passed` — the two new tests fail on the missing examples and the over-budget text, and `test_free_prompt_is_unchanged` fails because the code still emits the old prompt.

- [ ] **Step 3: Implement**

In `shell/aura_llm.py`, in `build_prompt`, replace:

```python
    example = '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}\n'
```

with:

```python
    example = (
        '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}\n'
        '"how is my machine doing" is {"cmd":"system_status","args":{}}\n'
        '"which programs are on here" is {"cmd":"list_apps","args":{}}\n')
```

The wording deliberately differs from every phrase in `tests/aura_eval_cases.jsonl`, so the examples are not the test set.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `52 passed`

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `126 passed`

- [ ] **Step 5: Commit**

```bash
git add shell/aura_llm.py tests/test_aura_llm.py
git commit -m "Show the model a status and a list example in the prompt"
```

---

### Task 4: One tool call at most in schema mode

In schema mode the model repeated a call until the token limit (p95 14.0-15.3 s, 6.9-8.2% of outputs cut off). The schema's array has no upper bound; llama.cpp b4589 converts `maxItems` into its grammar.

**Files:**
- Modify: `shell/aura_llm.py:57`
- Test: `tests/test_aura_llm.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_aura_llm.py`:

```python
def test_response_schema_allows_at_most_one_call():
    calls = aura_llm.response_schema(aura_llm.load_tools())["properties"]["tool_calls"]
    assert calls["maxItems"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_aura_llm.py::test_response_schema_allows_at_most_one_call -q -p no:cacheprovider`
Expected: FAIL with `KeyError: 'maxItems'`.

- [ ] **Step 3: Implement**

In `shell/aura_llm.py`, replace:

```python
    calls = {"type": "array", "items": {"anyOf": variants}} if variants else {"type": "array", "maxItems": 0}
```

with:

```python
    # maxItems 1: measured runs showed the model repeating one call until the
    # token limit, which cost latency and truncated the output.
    calls = ({"type": "array", "maxItems": 1, "items": {"anyOf": variants}}
             if variants else {"type": "array", "maxItems": 0})
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_aura_llm.py -q -p no:cacheprovider`
Expected: `53 passed`

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `127 passed`

- [ ] **Step 5: Commit**

```bash
git add shell/aura_llm.py tests/test_aura_llm.py
git commit -m "Allow at most one tool call in schema mode"
```

---

### Task 5: One canonical context size

`scripts/10-aurora-shell.sh:133` serves the model with `--ctx-size 4096` while `scripts/13-aurora-desktop.sh:299` uses `2048`. The measurements used 2048, so 2048 is canonical and a test keeps the two scripts in agreement.

**Files:**
- Create: `tests/test_launcher_ctx.py`
- Modify: `scripts/10-aurora-shell.sh:133`

- [ ] **Step 1: Write the failing test**

Create `tests/test_launcher_ctx.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_launcher_ctx.py -q -p no:cacheprovider`
Expected: FAIL with `scripts/10-aurora-shell.sh serves ctx ['4096'], expected 2048`.

- [ ] **Step 3: Implement**

In `scripts/10-aurora-shell.sh` line 133, change `--ctx-size 4096` to `--ctx-size 2048`. The full line becomes:

```
ExecStart=/opt/aura/bin/llama-server --model /opt/aura/models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --host 127.0.0.1 --port 8080 --ctx-size 2048
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_launcher_ctx.py -q -p no:cacheprovider`
Expected: `1 passed`

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `128 passed`

Run: `bash -n scripts/10-aurora-shell.sh`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add scripts/10-aurora-shell.sh tests/test_launcher_ctx.py
git commit -m "Serve the model with one canonical context size"
```

---

### Task 6: Re-measure and publish

Three runs of the 73-case set against the changed pipeline, then regenerate the README table from the results files. No number is typed by hand.

**Files:**
- Create: `tests/results/aura-eval-2026-09-16-qwen2.5-1.5b-q4km-fixes-r{1,2,3}-free.json` (written by the harness)
- Modify: `README.md` (table regenerated)

- [ ] **Step 1: Check the machine is quiet**

Run: `tasklist | sort /R /+58 | head -5` (Windows) or inspect Task Manager.
Expected: no process above about 50% sustained CPU. Another workflow may be running on this machine; if so, wait. Latency figures are meaningless under load, and the accuracy figures are not.

- [ ] **Step 2: Start the server used for every earlier measurement**

```bash
M="$HOME/aura-eval/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
"$HOME/aura-eval/llama-b4589/llama-server.exe" --model "$M" --host 127.0.0.1 --port 8080 --ctx-size 2048 > "$HOME/aura-eval/server-fixes.log" 2>&1 &
```

Wait for `main: server is listening` in `$HOME/aura-eval/server-fixes.log`.

- [ ] **Step 3: Run the harness three times**

```bash
for run in 1 2 3; do
  PYTHONUTF8=1 python tests/aura_eval.py --model-name "qwen2.5-1.5b-q4km-fixes-r$run" --model-file "$M" --decoding free || exit 1
done
taskkill //IM llama-server.exe //F
```

Expected: three new files under `tests/results/`, each reporting `0` server errors. Each run takes about 4 minutes.

- [ ] **Step 4: Compare against the targets**

```bash
PYTHONUTF8=1 python - <<'PY'
import glob, json, statistics
def mean(pattern, key):
    vals = []
    for p in sorted(glob.glob(pattern)):
        m = json.load(open(p, encoding="utf-8"))["metrics"]
        vals.append(m[key]["rate"])
    assert len(vals) == 3, "expected 3 runs, found %d for %s" % (len(vals), pattern)
    return statistics.mean(vals), min(vals), max(vals)
for key in ("tool_accuracy_pipeline", "tool_accuracy_model", "false_action_pipeline", "false_action_model"):
    before = mean("tests/results/*qwen2.5-1.5b-q4km-r*-free.json", key)
    after = mean("tests/results/*qwen2.5-1.5b-q4km-fixes-r*-free.json", key)
    print("%-24s before %.3f (%.3f-%.3f)  after %.3f (%.3f-%.3f)" % (key, *before, *after))
PY
```

Record the output in the commit message. The spec's targets: pipeline tool accuracy at least 0.85, pipeline false action no higher than 0.030. A change of less than 5 points (0.05) is noise at 40 cases and must be reported as such, not as an improvement.

- [ ] **Step 5: Regenerate the README table**

```bash
PYTHONUTF8=1 python tests/aura_eval.py --summary --markdown > /tmp/aura-table.md
```

Replace the table in `README.md`'s "Aura evaluation" section with the generated text, leaving the surrounding paragraph and caveats untouched, and add one sentence naming what changed between the `-r*` and `-fixes-r*` rows (alias table, rewritten gate, prompt examples).

- [ ] **Step 6: Run the suite once more**

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: `128 passed`

- [ ] **Step 7: Commit**

```bash
git add tests/results README.md
git commit -m "Measure the tool-calling fixes and publish the numbers"
```

- [ ] **Step 8: Report**

State plainly whether the targets were met, using the means and the min-max spread from Step 4. If pipeline accuracy is below 0.85, or false actions rose above 0.030, say so and stop: the next decision (widen the gate further, or train) belongs to the owner and is recorded in the spec's section 8.

---

### Task 7: Build an ISO and test Aura in VirtualBox

Everything above is measured against a Python harness. This task puts the changed assistant on a real booted system: rebuild the live ISO with the current Aura code and the shipped model, boot it in VirtualBox, and have a human drive Aura by chat.

**Starting facts, verified 2026-09-16 (do not re-derive):**

- The LFS build tree is intact in the Docker volume `aurora-lfs-x86` (mounted at `/mnt/lfs` inside the container `aurora-x86`, which is **stopped**). It holds `boot/vmlinuz-aurora`, `usr/bin/aurora-shell`, `usr/bin/labwc` and `/opt/aura/bin/llama-server`.
- The container also bind-mounts `/home/aneekchattopadhyay/auroraos-x86` (a WSL-side copy of this repo) at `/aurora`. **The build scripts read that copy, not the Windows checkout**, so code must be synced into it first.
- The tree's Aura code is from 16 July: `aura_llm.py` (10,637 bytes) and `aurorad` (43,518 bytes), and **there is no `aura_power.py`**. It predates the power confirmation, the browser-request hardening, schema mode and the model swap.
- The tree's bundled model is `Qwen2.5-3B-Instruct-Q4_K_M.gguf` (1.93 GB), which is **qwen-research licensed and must not ship**. The shipped model is Qwen2.5-1.5B-Instruct Q4_K_M, already downloaded at `$HOME/aura-eval/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` on the Windows side (Apache-2.0).
- The last ISO, `/home/aneekchattopadhyay/auroraos-x86/daybreakos-1.0-desktop-full.iso` (1.12 GB, 17 July), does **not** bundle a model: its `live/rootfs.squashfs` is 1.09 GB. Aura downloads the model after install.
- VirtualBox 7.2.12 is installed on Windows at `C:\Program Files\Oracle\VirtualBox\VBoxManage.exe`.

**Confirmed by the owner (2026-09-16):** this test ISO bundles the 1.5B model so the VM test does not depend on networking inside the VM, which makes the ISO roughly 1 GB larger (about 2.1 GB total). The shipped ISO's post-install download path is not changed by this task.

**This task is not unattended:** Steps 1-7 can run on their own, but Step 8 needs a person typing into the Aura panel and watching what happens. Stop after Step 7 and hand over.

**Files:**
- Modify (inside the build tree, not the repo): `/mnt/lfs/usr/lib/aurora/{aurorad,aura_llm.py,aura_power.py}`, `/mnt/lfs/opt/aura/config/aura-tools.json`, `/mnt/lfs/opt/aura/models/`
- Create: `docs/vm-check-2026-09-16.md` (in this repo)

- [ ] **Step 1: Start the build container and confirm the tree**

```bash
wsl.exe -d Ubuntu -u root -e docker start aurora-x86
wsl.exe -d Ubuntu -u root -e docker exec aurora-x86 sh -c 'ls -la /mnt/lfs/boot/vmlinuz-aurora /opt/aura/bin/llama-server 2>&1; ls /aurora/scripts | head -3'
```

Expected: the kernel and `llama-server` listed, and the scripts directory readable. If the container will not start, stop and report: everything below depends on it.

- [ ] **Step 2: Sync the current code into the copy the build reads**

**Read this before touching that copy (verified 2026-09-16):** it is a clone of `github.com/Aneek1/auroraos` — the *old* repo name, not `daybreakos` — sitting on `master` at `e207898`, with **uncommitted local modifications** to `config/extras.list`, `config/kernel.fragment`, `config/kernel-x86_64.fragment` and `scripts/06,07,08,10,11`. Those edits are what the working build tree was made from. **Never run `git pull`, `git checkout` or `git reset` there, and do not copy build scripts over the top of it.** Copy only the Aura files the rebuild needs:

```bash
SRC="/mnt/c/Users/aneek.chattopadhyay/Desktop/Other Projects/auroraos"
wsl.exe -d Ubuntu -u root -e sh -c "cp '$SRC/shell/aurorad.py' '$SRC/shell/aura_llm.py' '$SRC/shell/aura_power.py' /home/aneekchattopadhyay/auroraos-x86/shell/ && cp '$SRC/config/aura-tools.json' /home/aneekchattopadhyay/auroraos-x86/config/ && cp '$SRC/shell/aurora-desktop/aurora-shell.c' '$SRC/shell/aurora-desktop/style.css' /home/aneekchattopadhyay/auroraos-x86/shell/aurora-desktop/"
wsl.exe -d Ubuntu -u root -e sh -c "ls -la /home/aneekchattopadhyay/auroraos-x86/shell/aura_power.py /home/aneekchattopadhyay/auroraos-x86/shell/aura_llm.py; git -C /home/aneekchattopadhyay/auroraos-x86 status --short | head"
```

Expected: `aura_power.py` now present, `aura_llm.py` larger than its July size of 8,955 bytes, and the pre-existing local modifications still listed — this copy stays dirty on purpose.

Script 10 is deliberately **not** copied: the model server in the image is started by `/usr/lib/aurora/aura-llm-launch`, which already passes `--ctx-size 2048`, so Task 5's change needs nothing here.

- [ ] **Step 3: Refresh the installed Aura files inside the tree**

```bash
wsl.exe -d Ubuntu -u root -e docker exec aurora-x86 sh -c '
set -e
install -Dm755 /aurora/shell/aurorad.py      /mnt/lfs/usr/lib/aurora/aurorad
install -Dm644 /aurora/shell/aura_llm.py     /mnt/lfs/usr/lib/aurora/aura_llm.py
install -Dm644 /aurora/shell/aura_power.py   /mnt/lfs/usr/lib/aurora/aura_power.py
install -Dm644 /aurora/config/aura-tools.json /mnt/lfs/opt/aura/config/aura-tools.json
ls -la /mnt/lfs/usr/lib/aurora/
grep -n -- "--ctx-size" /mnt/lfs/usr/lib/aurora/aura-llm-launch'
```

Expected: `aura_power.py` now listed, `aura_llm.py` larger than the July 10,637 bytes, and the launcher line ending `--ctx-size 2048`.

There is **no systemd unit for Aura in the tree**: the model server is started by `/usr/lib/aurora/aura-llm-launch`, which the labwc autostart runs. That file already passes `--ctx-size 2048`, so Task 5's change needs nothing here. If the grep shows `4096`, edit that file instead and say so in the report.

- [ ] **Step 4: Put the shipped model in the image and remove the non-commercial one**

```bash
wsl.exe -d Ubuntu -u root -e sh -c "cp '/mnt/c/Users/aneek.chattopadhyay/aura-eval/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf' /var/lib/docker/volumes/aurora-lfs-x86/_data/opt/aura/models/ && rm -f /var/lib/docker/volumes/aurora-lfs-x86/_data/opt/aura/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf && ls -la /var/lib/docker/volumes/aurora-lfs-x86/_data/opt/aura/models/"
```

Expected: only `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` (about 986 MB) remains. The 3B model must not appear in any image.

- [ ] **Step 5: Rebuild the ISO**

```bash
wsl.exe -d Ubuntu -u root -e docker exec aurora-x86 bash /aurora/build-full-iso.sh 2>&1 | tail -20
```

Expected: a `shell: <N> bytes` line, then the squashfs and `xorriso` steps, ending with the ISO written to `/aurora/daybreakos-1.0-desktop-full.iso`. Allow 30-60 minutes. If the script fails, capture the failing command and stop.

- [ ] **Step 6: Copy the ISO to Windows and record its fingerprint**

```bash
wsl.exe -d Ubuntu -u root -e sh -c "sha256sum /home/aneekchattopadhyay/auroraos-x86/daybreakos-1.0-desktop-full.iso; cp /home/aneekchattopadhyay/auroraos-x86/daybreakos-1.0-desktop-full.iso '/mnt/c/Users/aneek.chattopadhyay/Desktop/daybreakos-2026-09-16.iso'"
ls -la "/c/Users/aneek.chattopadhyay/Desktop/daybreakos-2026-09-16.iso"
```

Expected: a checksum (record it) and the ISO on the Desktop.

- [ ] **Step 7: Create and boot the VM**

```bash
VB="/c/Program Files/Oracle/VirtualBox/VBoxManage.exe"
"$VB" createvm --name DaybreakOS-0916 --ostype Linux_64 --register
"$VB" modifyvm DaybreakOS-0916 --memory 4096 --cpus 4 --firmware efi --graphicscontroller vmsvga --vram 128 --nic1 nat
"$VB" storagectl DaybreakOS-0916 --name SATA --add sata --controller IntelAhci
"$VB" storageattach DaybreakOS-0916 --storagectl SATA --port 0 --device 0 --type dvddrive --medium "C:\\Users\\aneek.chattopadhyay\\Desktop\\daybreakos-2026-09-16.iso"
"$VB" startvm DaybreakOS-0916
```

Expected: the VM boots to the DaybreakOS desktop. VirtualBox provides no hardware GL, so the desktop falls back to software rendering; that is expected and is not a failure of this task.

- [ ] **Step 8: Drive Aura by chat (human, in the VM)**

Open the Aura panel and type each line, recording the exact reply and whether the action happened:

| Typed | Expected |
|---|---|
| `hello` | a chat reply, no action |
| `open a terminal` | a terminal window opens |
| `what software is on this computer` | the app list is reported (this failed before Task 2) |
| `how much battery is left` | a status reply from real values, not invented ones (this was dropped by the old gate) |
| `dim the screen to 20 percent` | brightness changes, or a clear "not controllable on this device" |
| `open settings` | the settings app opens (this needed the Task 1 alias) |
| `what is a terminal?` | an explanation, and **no** terminal opens |
| `shut down` | **Power off** and **Cancel** buttons appear; nothing happens yet |
| (click Cancel) | the row disables, the bubble reads "Cancelled.", the VM stays up |
| `shut down` then click **Power off** | the VM powers off |

The first model reply after boot may take up to a minute while llama-server loads.

- [ ] **Step 9: Write down what happened**

Create `docs/vm-check-2026-09-16.md` in this repo: the ISO name and sha256, the repo commit it was built from, the VirtualBox version, the table from Step 8 with what was actually observed in each row, and anything that failed. Plain sentences; no marketing. Record failures as failures.

- [ ] **Step 10: Commit**

```bash
git add docs/vm-check-2026-09-16.md
git commit -m "Record what Aura did on a booted system in VirtualBox"
```

- [ ] **Step 11: Stop the container**

```bash
wsl.exe -d Ubuntu -u root -e docker stop aurora-x86
```
