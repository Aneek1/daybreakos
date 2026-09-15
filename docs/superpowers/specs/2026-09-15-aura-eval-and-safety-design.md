# Aura evaluation, power safety and model comparison: design

**Date:** 2026-09-15
**Status:** Approved 2026-09-15; §5.2 amended the same day (confirmation handled by the panel and the root service, no server-side token)
**Depends on:** `shell/aura_llm.py`, `shell/aurorad.py` (`/ask`, `/system/power`), `shell/aurora-desktop/aurora-shell.c` (Aura panel), `config/aura-tools.json`, llama.cpp pinned at `b4589`
**Supersedes, in part:** `2026-07-10-aura-local-llm-design.md` (tool routing and the shared web-shell registry, see §2)

## 1. Why

Aura works, but nothing measures how well, and three problems are documented:

- **Invented actions:** the bundled Llama-3.2-1B emits tool calls for chit-chat ("hi" opened a terminal; commit f4e8f94). `_ACTION_CUE` patches over it with a keyword regex.
- **Unreliable output:** broken JSON and echoed prompt placeholders (`aurorad.py:906-908`, commit ce27fea).
- **Power can be triggered without confirmation**, in three places:
  - `power` is in the model's tool list (`config/aura-tools.json`), against the July spec's own safety rule.
  - `aurorad` has a `power` executor (`aurorad.py:888-899`).
  - The regex shortcut in `/ask` (`aurorad.py:925-928`) turns "shut down", "power off", "turn off", "restart" or "reboot" into `systemctl` immediately. "Turn off wi-fi" matches "turn off". It also runs `systemctl` from the non-root session service (port 7212), which systemd denies without polkit, so typed power requests most likely fail silently today.

The current test fixture cannot measure anything:
- 8 of the 10 expected tools in `tests/aura_intents.jsonl` are not in the registry.
- `tests/test_aura_llm_live.sh` breaks on apostrophes.
- No results were ever recorded.
- 9 of 31 tests fail on `master` (46a4e28), including the black-box `tests/test_aurorad_ask.py`.

The README says Aura runs "Qwen2.5-3B"; every script actually ships Llama-3.2-1B-Instruct Q4_K_M.

## 2. What is true today, and what this spec treats as correct

There are two shells:

| Shell | Built by | Reads `/ask` | Runs `ran:false` actions |
|---|---|---|---|
| Native C desktop (`aurora-shell.c`) | `scripts/13-aurora-desktop.sh` | only the `"a"` reply text | no |
| Legacy web shell (`index.html` + `aurora-bridge.js`) | `scripts/10`, `12` | `a` and `actions` | yes, via `Aura.exec` |

The July spec and the failing tests were written for the web shell (UI-side `open_app` with an `app` argument, every tool name present in `index.html`'s `COMMANDS`). The native desktop is what DaybreakOS runs now, so **the native desktop is the source of truth**:

- `open_terminal`, `open_app` (argument `name`), `list_apps`, `system_status` and `set_brightness` stay `side: system`, executed by `aurorad`.
- `index.html` and `aurora-bridge.js` are labelled as the legacy web shell. They are not deleted, and no longer drive the tool registry or its tests.

## 3. Scope

In scope:
1. An evaluation harness and a real test set, with a recorded baseline for the current code.
2. Power safety: no model access to power, and a two-button confirmation for power requests typed into Aura.
3. Test suite brought back in line with the native desktop.
4. Schema-constrained output, adopted only if the evaluation shows it helps.
5. A model comparison: Llama-3.2-1B vs Qwen2.5-1.5B vs Qwen2.5-3B, with only permissive licences eligible to ship.
6. README corrections.

Out of scope:
- Fine-tuning (LoRA) is considered only if gaps remain after phase E, in a separate spec.
- Upgrading llama.cpp beyond `b4589`, or Qwen3 (needs a newer converter and runtime).
- GPU inference.
- Web-shell feature parity in the native desktop (`tile_windows`, `set_theme`, …).
- Protecting `/system/power` from other local processes. It keeps its current trust boundary (127.0.0.1, same as all `aurorad` endpoints). The Daybreak menu's power items are explicit clicks and stay as they are. Web pages are not local processes in this sense; see §5.4.

## 4. Evaluation harness (phase A)

### 4.1 Test set: `tests/aura_eval_cases.jsonl`

One JSON object per line, with `say`, `expect` and optional `args`. It replaces `tests/aura_intents.jsonl`.

- **Tool cases (40):** 8 for each of the 5 model-callable tools. They vary wording, include arguments where the tool has them (`open_app` names such as "text editor", "the terminal app"; `set_brightness` numbers written as "40", "forty percent", "dim it to 20"), and include misspellings.
- **Negative cases (25), which must produce no tool call:**
  - greetings and thanks
  - general questions
  - questions *about* tools ("what is a terminal?", "how do I change brightness myself?")
  - requests Aura has no tool for ("turn off wi-fi", "switch to light mode")
- **Power cases (8):** "shut down", "restart the computer", "power off now", and similar. At the model level the expected result is no tool call. At the `/ask` level the expected result is a confirmation response, and nothing executed.

`expect` is a tool name or `"none"`. `args` holds the expected argument values: `open_app.name` is compared case-insensitively after trimming, and `set_brightness.percent` as an integer.

### 4.2 Harness: `tests/aura_eval.py`

- **Standard library only**, matching `aura_llm.py`. It runs on the host against a real `llama-server`.
- **Call levels:** each case is run at two levels.
  - **model level:** `call_llama` + `parse_model_output`, before the `_ACTION_CUE` gate
  - **pipeline level:** `ask()` with recording executors, so nothing really runs
- **Metrics per condition:**
  - tool accuracy on tool cases (right `cmd`)
  - argument accuracy on tool cases with args
  - false-action rate on negative and power cases (any tool call)
  - valid response-JSON rate on tool cases (a JSON object shaped like Aura's response, whether or not it calls a tool)
  - bad-reply rate (`_reply_is_bad`)
  - wall-clock latency p50 and p95
  - per-tool model and pipeline accuracy, and how many correct model calls the `_ACTION_CUE` keyword gate dropped (some realistic requests contain no action word, so pipeline accuracy is capped below model accuracy)
  - replies stating system facts without a tool call (digits plus battery, uptime or network words; a heuristic for invented readings, which `bad_reply` cannot see)
- **Conditions:** `--model <gguf>` and `--decoding free|schema`. The server is started by the caller, and the harness records the server's reported model path.
- **Output:** `tests/results/aura-eval-<date>-<model>-<decoding>.json`, with the date, git commit, host CPU, model file SHA-256, llama.cpp tag, every case's raw output and the metrics. `--summary` prints a table from all result files. Requests that fail at the server are counted separately and excluded from every rate; a run with any failed request, or one that would overwrite an existing results file, is not saved.
- **Replaces `tests/test_aura_llm_live.sh`** (its quoting bug goes with it).

### 4.3 Measuring setup

- **Server:** the prebuilt `llama-b4589-bin-win-avx2-x64.zip` (or the Ubuntu/macOS arm64 build of the same tag), with the distro's flags: `llama-server --model <gguf> --host 127.0.0.1 --port 8080 --ctx-size 2048`, no `--jinja`.
- **Comparability:** prebuilt binaries are compiled differently from the distro's CMake build. Output quality matches; speed is reported as host-relative only, with the CPU recorded.
- **Quant source:** the same for all models (bartowski Q4_K_M), so the comparison is like for like.
- **Baseline first:** phase A records `llama-3.2-1b / free` against commit `46a4e28` (the code before any change in this spec), running from a separate worktree if phase B has already started.

## 5. Power safety (phase B)

### 5.1 The model can no longer touch power

- Remove `power` from `config/aura-tools.json`.
- Remove the `power` entry from the `/ask` executors in `aurorad.py`.
- `validate_call` then drops any model-emitted `power` call, as the existing whitelist rule intends.

### 5.2 Typed power requests ask for confirmation

`aurorad` runs as two processes: the session service on port 7212 handles `/ask`, and the root service on port 7213 (`systemd/aurorad-system.service`) handles `/system/*`, including `/system/power`. A confirmation token created by one could not be redeemed by the other, so confirmation lives in the panel.

- **Recognising the request:** new stdlib module `shell/aura_power.py`.
  - `power_request(text) -> "poweroff" | "reboot" | None` replaces the regex in `/ask`. "Turn off" and "switch off" only count with a device word ("the computer/pc/laptop/machine/system"), so "turn off wi-fi" and "turn off night light" no longer match.
  - `confirm_payload(action)` returns the `/ask` response:

    ```json
    {"a": "Power off now?", "actions": [], "confirm": {"action": "poweroff", "label": "Power off", "expires_in": 30}}
    ```

    ("Restart now?" / `reboot` / "Restart" for restart requests.)
- **`/ask`:** checks `power_request` before any other shortcut and returns the payload. It never runs `systemctl` itself any more; it previously did, from the non-root session service, where systemd denies it.
- **Native shell (`aurora-shell.c`):**
  - The worker keeps the raw `/ask` JSON and extracts the optional `confirm` fields (`action`, `label`, `expires_in`) with the same minimal string scanning it uses for `"a"`.
  - `aura_apply_result` adds a button row under the reply: **[label]** and **[Cancel]**.
  - The action button calls the existing `power_action()`, which posts to the root service's `/system/power`, the same path as the Daybreak menu's Restart and Shut Down items. Cancel appends "Cancelled."
  - A `g_timeout_add_seconds(expires_in)` disables both buttons and appends "Expired." if neither was clicked.
- **Legacy web shell:** it ignores `confirm`, so it shows the question with no buttons. Nothing runs, which is the safe default.
- **Trust boundary:** `/system/power` stays callable by local processes, as it already is (§3), but not by web pages (§5.4).

### 5.3 Tests

- **`tests/test_aura_power.py`:** power phrases recognised; near-misses ("turn off wi-fi", "switch off bluetooth", "power saving mode") ignored; the exact `confirm` JSON text the C parser relies on.
- **`tests/test_aurorad_ask.py`:** a black-box test that a typed "shut down" returns the confirmation payload even when the stub model asks for a tool.
- **`tests/test_aura_tools.py`:**
  - keep `test_no_power_tool_exposed`
  - replace `test_names_match_index_commands` with `test_every_tool_has_an_aurorad_executor`, which checks the `executors = {…}` block in `aurorad.py`
- **Shortcut regex:** tests that "turn off wi-fi" is not a power request and "shut down" is.
- **C change:** compiled in WSL Ubuntu with the same flags as the ISO build before it is committed, then a VM smoke test: ask "shut down", click Cancel, nothing happens; ask again and wait 30 s, the buttons disable.

### 5.4 Web pages cannot call aurorad

Found in code review of phase B (2026-09-15). `aurorad` answered every request with `Access-Control-Allow-Origin: *` and parsed any request body as JSON. A web page open in a browser on the machine could therefore POST a `text/plain` body, which browsers send without a CORS preflight, to `/system/power`, `/power`, `/system/install` or `/launch`, with no click. Trusting local processes (§3) never meant trusting every page a browser loads.

- Every POST is refused with 403, before its body is read, if it carries an `Origin` header, has a Content-Type other than `application/json`, or names a Host other than `127.0.0.1`, `localhost` or `[::1]`. The Host check stops DNS rebinding, where a page reaches 127.0.0.1 under its own domain.
- Every GET naming a Host other than those three is refused with 403 too. A rebinding page is same-origin under its own domain, so CORS would not stop it reading replies such as `/files`, `/system/disks` or `/system/shares`.
- Responses carry no CORS headers and OPTIONS preflights get 403, so other origins cannot read responses such as `/files` either.
- Native clients already qualify: `aurora-shell.c` and `shell/daybreak` send JSON with no Origin. `aurora-settings.c` sent `Host: x` and now sends `Host: 127.0.0.1`.
- The legacy web shell is a `file://` page in Firefox, so it can no longer reach `aurorad`. It is labelled legacy (§9).
- Tests (`tests/test_aurorad_http.py`) start a real `aurorad` and check that native headers are accepted and every refusal case, POST and GET, gets 403. They use the `lock` action, which only answers ok, so a broken check can never power anything off.
- Not covered: another local user or process can still call `aurorad` directly (§3).

## 6. Test suite realignment (phase B, same change)

The 8 failing tests are updated to the native desktop's contract (§2):

- `open_app` examples use `{"name": …}`, and `side: system` expectations apply.
- **UI deferral stays tested,** using a small inline registry with a `ui` tool, not the real registry.
- The prompt test checks for "never invent" case-insensitively.
- The power tests pass once §5.1 lands.

**Gate:** `python -m pytest tests` passes with no failures on the host Python (Windows), including `tests/test_aurorad_ask.py`.

## 7. Schema-constrained output (phase C)

- `call_llama` optionally sends `response_format: {"type": "json_schema", "json_schema": {"schema": …}}`, which is supported at b4589 (`utils.hpp:610-614`).
- **Schema:** an object with `reply` (string) and `tool_calls` (array of `{cmd, args}`), where `cmd` is an enum of registry tool names and `set_brightness.percent` is an integer from 0 to 100. Chat replies come back as `{"reply": "...", "tool_calls": []}`.
- **Switch:** controlled by `AURA_LLM_SCHEMA` (`1` or `0`).
- **Default:** set only after measurement. Schema mode becomes the default if, versus free mode on the same model and averaged over three runs of each, its false-action rate is lower and its tool accuracy is not more than 2 points worse. Otherwise the default stays free, and the results file is the record of why.
- `parse_model_output` already handles both shapes. `_reply_is_bad` stays as a last line of defence.

## 8. Model comparison and choice (phases D-E)

| Model | Q4_K_M file | Licence | Can ship |
|---|---|---|---|
| Llama-3.2-1B-Instruct | 808 MB | Llama 3.2 Community | yes (current) |
| Qwen2.5-1.5B-Instruct | 986 MB | Apache-2.0 | yes |
| Qwen2.5-3B-Instruct | 1.93 GB | Qwen Research (non-commercial only) | **no: comparison baseline only** |

- **Runs:** each model is run three times in each decoding mode, because the model samples at temperature 0.2 and one tool case is worth 2.5 points. Decisions use the means; every run is published.
- **Selection** is among shippable models:
  - highest tool accuracy, with false-action rate as the tie-breaker
  - p95 latency must stay within 2× of Llama-3.2-1B on the same host
- **If Qwen2.5-1.5B is chosen:**
  - update `scripts/02-download-sources.sh`, `scripts/10-aurora-shell.sh` and `shell/aurorad.py` (download URL and filename)
  - change the size hint in `aura_llm.py` (~0.8 GB → ~1.0 GB)
  - update the comments that say "1B"
- **Qwen2.5-3B** is never bundled or auto-downloaded. The README may mention how it compared.
- **LoRA** is written up as a follow-up spec if the chosen model still shows a false-action rate above 5% or tool accuracy below 90%.

## 9. README and documentation

- Correct the model claim to the shipped model, and link the latest evaluation summary.
- Add a short "Aura evaluation" section generated from `tests/results/` (`python tests/aura_eval.py --summary --markdown`), with no hand-typed numbers.
- Note in `2026-07-10-aura-local-llm-design.md` that §2 of this spec supersedes its tool-routing section.

## 10. Phases and order

| Phase | Deliverable | Depends on |
|---|---|---|
| A | Test set, harness, baseline results for current code | — |
| B | Power safety + test realignment | — (may run in parallel with A) |
| C | Schema mode + measurement + default decision | A |
| D | Model comparison runs | A, C |
| E | Model choice applied, README updated | D |

## 11. Risks

- **Small test set:** 73 cases give coarse percentages (one case is 1.4 points). Results are reported with counts, not just percentages.
- **Host vs distro speed:** only relative comparisons on one host are claimed.
- **Minimal JSON scanning in C:** the `confirm` parser relies on `aurorad` emitting that exact shape. A unit test on the Python side pins the shape.
- **Schema mode and chat quality:** forcing JSON may make chat replies terser; the bad-reply rate and a manual read of chat cases are recorded. The JSON wrapper also costs tokens, so schema mode gets a larger `max_tokens` (192 against 128), and a reply cut off inside its `reply` string is shown cut short, as in free mode. Without that it would be replaced by the "still warming up" fallback, which `bad_reply` scores as clean.
