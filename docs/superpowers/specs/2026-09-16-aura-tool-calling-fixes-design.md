# Aura tool calling: fixes before training

**Date:** 2026-09-16
**Status:** approved in brainstorming (owner chose "cheap fixes first, then decide"), awaiting owner review of this document
**Depends on:** `shell/aura_llm.py`, `config/aura-tools.json`, `tests/aura_eval.py`, `tests/aura_eval_cases.jsonl`, `scripts/10-aurora-shell.sh`, `scripts/13-aurora-desktop.sh`
**Follows:** `2026-09-15-aura-eval-and-safety-design.md` (merged as PR #1)
**Does not cover:** LoRA fine-tuning. That is a separate spec, to be written only if the numbers here leave a gap worth the GPU time.

## 1. Why

After the model change to Qwen2.5-1.5B, Aura performs a requested desktop action about 70% of the time (pipeline level), while the model itself produces the right call 81.7% of the time. Research on 2026-09-16 established where the remaining errors come from, using the stored rows of the three free-decoding runs in `tests/results/`:

- **The 11.7-point gap between model and pipeline is our own filter.** `_ACTION_CUE` (`shell/aura_llm.py:9-15`, applied at `:280-281`) drops a correct call when the user's own words contain no action word. The pattern has no `dim` and no `battery`, so "dim the screen to 20 percent" and "how much battery is left" are discarded after the model got them right. That is about 4.7 correct calls per run of 40 tool cases.
- **The filter cannot simply be deleted.** On the 99 negative rows (3 runs x 33), the model emitted some call 41 times. `validate_call` (`:152-166`) already rejects 30 of those as invented names. Removing `_ACTION_CUE` and relying on validation alone takes pipeline false actions from 3.0% to 11.1%.
- **Half the model's own errors are a naming mismatch, not a misunderstanding.** Of 22 wrong attempts across the three runs, 11 name a tool that does not exist while the intent is right: `open_settings` and `open_browser` (meaning `open_app`), `check_battery_status`, `check_network`, `check_network_status` and `system_health_check` (meaning `system_status`). None of those six names ever appears on a chit-chat or power row in any free-decoding run of any measured model.
- The remaining 11 errors are 8 cases where no call is produced ("give me a command line", "what software is on this computer", "how is the system doing") and 3 where `open_terminal` is returned for "can you list all my apps".

So the work that does not need a GPU is: stop discarding correct calls, accept calls whose only fault is the label, and give the model one worked example of the shapes it misses.

## 2. Scope

In scope:

1. An alias table mapping known invented names onto registry tools.
2. A rewrite of the action filter so it stops discarding correct calls without raising false actions.
3. Prompt changes: one or two worked examples covering the missed shapes.
4. `maxItems: 1` on the schema-mode tool-call array, so schema mode stops repeating a call until the token limit.
5. One canonical context size for the served model.
6. Re-measurement and a README update from the generated table.

Out of scope:

- LoRA or any training (separate spec, decided on these results).
- Moving off llama.cpp b4589.
- Multi-turn conversation. `build_prompt` (`:70-94`) sends the system prompt plus the current user text only; nothing in the pipeline carries history.
- Changing the tool registry itself, or adding tools.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| 1 | Cheap fixes first; training decided afterwards on measured results | Half the model errors and the whole model-to-pipeline gap are fixable in code |
| 2 | Canonical context size is **2048** | It is what the measurements used and what `scripts/13-aurora-desktop.sh:299` ships; Aura is single-turn with a 128-token reply cap. `scripts/10-aurora-shell.sh:133` currently says 4096 and changes to match |
| 3 | Aliases are a static table, not fuzzy matching | Every alias is a name actually observed in the runs, mapped to one registry tool. No guessing at names nobody has produced |
| 4 | The filter keeps a gate, rewritten | Deleting it is measured at 11.1% false actions; the target is to keep false actions at or below today's 3.0% |
| 5 | Schema mode stays off by default | It lowers model-level false actions but costs latency (p95 14.0-15.3 s); `maxItems` is fixed here so the option is usable later |

## 4. Design

### 4.1 Alias table (`shell/aura_llm.py`)

A module-level dict maps an invented name to a registry tool and, where needed, fills arguments:

```
open_settings        -> open_app{name: "settings"}
open_browser         -> open_app{name: "firefox"}
check_battery_status -> system_status{}
check_network        -> system_status{}
check_network_status -> system_status{}
system_health_check  -> system_status{}
```

Applied in `parse_model_output` after JSON parsing and before `validate_call`, so routing, the schema path and the evaluation harness all see the corrected call. An alias never invents an argument the tool does not declare; `open_app`'s `name` value comes from the alias entry. Any alias whose target is absent from the registry is ignored, so a trimmed registry cannot resurrect a tool.

### 4.2 The action gate

`_has_action_intent` is replaced by a decision on three inputs, in order:

1. **Registry validity.** A call that fails `validate_call` never runs (unchanged).
2. **A negative pattern.** Question and acknowledgement shapes that produced the 11 valid-but-wrong chit-chat calls are refused: "how do I ... myself", bare acknowledgements ("ok", "thanks"), and requests for features that are not tools ("tile my windows", "switch to light mode").
3. **A widened action pattern.** The current words plus the ones the measurements show missing: `dim`, `brighten`, `bright`, `battery`, `network`, `wifi`, `uptime`, `software`, `installed`, `command line`, and the "how is/how's the system" shape.

The gate is data, not scattered conditionals: two compiled patterns and a short list, so a future change is one edit and one test.

### 4.3 Prompt

`build_prompt` gains one worked example of a status request phrased without an action word, and one of a list request, chosen from the failing phrasings but **not** copied verbatim from `tests/aura_eval_cases.jsonl`. The system prompt keeps its current structure; total added length is under 40 tokens, measured before and after.

### 4.4 Schema mode

`response_schema` (`:57`) currently builds `{"type": "array", "items": {...}}` with no upper bound. It gains `"maxItems": 1`. llama.cpp at b4589 supports `minItems`/`maxItems` in its JSON-schema-to-grammar conversion, so this is enforced at generation time.

### 4.5 Context size

`scripts/10-aurora-shell.sh:133` changes from `--ctx-size 4096` to `--ctx-size 2048`, matching `scripts/13-aurora-desktop.sh:299`. A test asserts both scripts pass the same value, so the baseline belongs to a known configuration.

## 5. Error handling

| Situation | Behaviour |
|---|---|
| Model names an unknown tool with no alias | Dropped by `validate_call`, as today; the reply text still reaches the user |
| Alias target missing from the registry | Alias ignored; no call |
| Alias would fill an argument the tool does not declare | Rejected by `validate_call`; no silent argument invention |
| Gate refuses a call | Nothing runs; the model's reply text is returned unchanged |
| Model returns no JSON | Existing cut-off recovery and `heuristic_fallback` paths, unchanged |

## 6. Testing

Unit tests (`tests/test_aura_llm.py`, stdlib + pytest, no model needed):

- every alias maps to a tool present in `config/aura-tools.json`
- an aliased call routes exactly as the real tool would
- an alias cannot introduce an undeclared argument
- each newly added action word admits its measured phrasing
- each negative shape is refused
- `response_schema` emits `maxItems: 1`
- both launcher scripts pass the same `--ctx-size`

Measurement (`tests/aura_eval.py`, 73 cases, three runs, free decoding, ctx 2048, no other heavy process on the machine):

- **Targets:** pipeline tool accuracy **>= 85%** (today 70%), pipeline false actions **<= 3.0%** (today 3.03%), model-level tool accuracy no worse than today's 81.7%, p95 latency unchanged.
- **Interpretation rule, fixed before the run:** 40 tool cases means one case is 2.5 points, and the unchanged model already swings 87.5 / 80.0 / 77.5 across runs. A change below 5 points is noise and is reported as such, not as an improvement.
- The README table is regenerated by `--summary --markdown`; numbers are never typed by hand.

## 7. Risks

- **The gate rewrite trades accuracy for false actions.** Mitigated by re-measuring after each iteration and by the fixed targets above; if false actions exceed 3.0%, the widened words are cut back rather than the target moved.
- **Aliases hide a real model failure.** They are recorded as aliases in the results notes, so "how often did an alias save us" stays visible and the training decision is made on unaliased model output as well.
- **The eval set is small.** Even with every fix, the instrument cannot resolve differences under about 5 points. Stated in the README beside the table.
- **Aliases are drawn from the same runs used to measure improvement.** This is fitting to the observed sample; the honest check is that the aliased names never appeared on negative rows, and that the gain is re-measured on fresh runs rather than the stored ones.

## 8. What would justify training afterwards

Written down now so the decision is not made in hindsight: if after these fixes the model-level false-action rate is still around 40%, the gate cannot be removed, and the pipeline stays below about 90%, then a LoRA aimed at false actions is worth the GPU time. That spec would also need a fresh held-out case set written by the owner before any data generation.
