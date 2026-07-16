# Aura Local LLM — Design Spec

**Date:** 2026-07-10
**Status:** Approved (design)
**Author:** DaybreakOS
**Depends on:** existing `shell/aurorad.py` (`/ask` endpoint), `shell/index.html` (`Aura` object + `COMMANDS` registry), `shell/aurora-bridge.js`, `config/extras.list`

## Goal

Replace Aura's canned/heuristic `/ask` responses with a **real on-device neural network** — a small quantized LLM running locally on the CPU — that (a) understands natural language, (b) emits **structured tool calls** into Aura's existing deterministic command registry, and (c) holds ordinary conversation. Fully offline. No cloud, no telemetry.

**Decisions locked:** **Llama-3.2-1B-Instruct**, **4-bit quantized** (Q4_K_M GGUF, ~0.8 GB), **bundled into the ISO** (works offline on first boot). (Llama's smallest tier is 1B — there is no Llama-3.2-1.5B; 1B is the intended "small, fast intent-router" size.)

## Why this shape

The current `Aura` object already models every shell action as a named tool (`open_app`, `set_brightness`, …) — it was built as the tool surface a future LLM would call. This spec fills in that model. The LLM never touches the system directly: it **proposes** a tool call, the existing deterministic registry **validates and executes**. That keeps a hallucinated action from ever running unchecked, and gives us a graceful fallback to the rule engine when the model is unsure or unavailable.

## Non-goals

- GPU/Neural-Engine acceleration (no M4 GPU driver in scope → CPU inference only).
- Training or fine-tuning a model (we ship an off-the-shelf instruct model).
- Multi-turn memory across sessions / RAG over user files (phase 2).
- Streaming token-by-token UI (phase 2 nicety; v1 returns the full reply).

## Model choice

| Property | Choice | Rationale |
|---|---|---|
| Model | **Llama-3.2-1B-Instruct** | Instruct-tuned, strong tool-calling, Llama Community License; smallest fast tier |
| Size | 1B params | Fast enough for intent-parsing + light chat on M4 CPU; lightest ISO cost |
| Quant | Q4_K_M (GGUF) | ~0.8 GB on disk; best size/quality knee for llama.cpp |
| Runtime | **llama.cpp** (server mode) | Plain CMake C++, NEON/dot-prod optimized for aarch64, no CUDA; proven-buildable pattern (same as the labwc/foot stack) |

**Footprint:** llama.cpp binary (~a few MB) + one GGUF (~0.8 GB). ISO grows by ~0.8 GB — acceptable for the offline-first requirement.

**License note:** Llama 3.2 ships under the Llama Community License (not OSI-free). Fine for personal/dual-boot use; if DaybreakOS is ever redistributed publicly, revisit (Qwen2.5-1.5B is Apache-2.0 and a drop-in swap — same GGUF/llama.cpp path).

## Architecture

```
┌─ browser (shell/index.html) ─────────────────────────────┐
│  Aura.interpret(text)                                     │
│    ├─ fast rule match?  ── yes ──► COMMANDS[cmd](args)    │  (unchanged: instant, deterministic)
│    └─ no / low-conf ────────────► aura-bridge /ask ──┐    │
│  applyAction({cmd,args})  ◄──────────────────────────┼──┐ │
└──────────────────────────────────────────────────────┼──┼─┘
                                                        │  │  UI tools run HERE (browser only)
        ┌───────────────────────────────────────────────▼──┼─┐
        │  aurorad.py  POST /ask                            │ │
        │    llama.cpp (127.0.0.1:8080, localhost only)     │ │
        │    prompt = SYSTEM + TOOLS + user text            │ │
        │    model → {reply, tool_call?}                    │ │
        │    if tool is SYSTEM-side (brightness/power/       │ │
        │       launch/status) → execute here, confirm      │ │
        │    if tool is UI-side → return it for the browser ─┘ │
        │    else → return plain {a: reply}                    │
        └─────────────────────────────────────────────────────┘
```

### Tool routing — the crux

Aura's tools split by **who can execute them**:

- **UI tools (browser-only):** `open_app`, `close_app`, `tile_windows`, `set_theme`, `minimize_all`, `summarize_notifications`, `browse`, `show_panel`, `lock`. These manipulate the shell DOM — `aurorad` cannot run them. `/ask` returns them as a structured action; `aurora-bridge.js` executes them against the in-page `COMMANDS` registry.
- **System tools (server-side):** `set_brightness`, `set_volume`, `toggle_setting` (where hardware-backed), `system_status`, `search_files`, `open_app`→native `launch`. `aurorad` runs these directly through its existing helpers and returns the result text.
- **Chat (no tool):** model reply passed straight through.

`set_brightness`/`set_volume` exist on **both** sides today (the shell has a slider; the hardware has a backlight). Resolution: `aurorad` executes the real hardware change AND echoes the action back so the browser syncs its slider UI. One source of truth (hardware), UI mirrors it.

### Request / response contract

`POST /ask` request unchanged: `{"q": "<user text>"}`.

Response extended (backward-compatible — old clients read `a`):
```json
{
  "a": "Opened Files and set brightness to 40%.",
  "actions": [
    {"cmd": "set_brightness", "args": {"percent": 40}, "ran": true},
    {"cmd": "open_app", "args": {"app": "files"}, "ran": false}
  ]
}
```
- `ran: true` → `aurorad` already executed it (system tool); browser need not.
- `ran: false` → UI tool; `aurora-bridge.js` calls `Aura.run(cmd, args)` / `COMMANDS[cmd](args)`.

## Prompt design

System prompt pins the model to DaybreakOS's tool vocabulary and forces JSON tool-calls for actions:

```
You are Aura, the on-device assistant for DaybreakOS. You can either answer in prose,
or call ONE OR MORE tools by emitting a JSON block. Tools: <auto-generated list from
the COMMANDS registry with arg schemas>. Only use listed tools with listed args.
If the user is just chatting, answer normally with no JSON. Never invent tools or args.
```

Tool list is **generated from a single source** (`config/aura-tools.json`) consumed by both the browser (`Aura`) and `aurorad` (prompt builder), so the registry never drifts between UI and prompt.

## Safety / guardrails

- Model bound to **127.0.0.1** only (llama.cpp `--host 127.0.0.1`), same trust boundary as `aurorad`.
- **Whitelist enforcement:** `aurorad` executes a returned tool ONLY if `cmd` is in the known registry and args validate; unknown → dropped, logged, plain reply returned. The model can never produce an arbitrary command string (mirrors the existing `/launch` id-only rule).
- **No destructive tools exposed.** `power` (poweroff/reboot) is deliberately NOT in the tool list — it stays a manual start-menu action so the model can't trigger it.
- **Deterministic fallback:** if llama.cpp is down, slow (>N s timeout), or returns malformed JSON, `/ask` falls back to today's heuristic replies. Aura always answers.
- Every executed tool appended to the existing Aura audit `log()`.

## Build integration

1. **`config/extras.list`** — add llama.cpp source (pinned release tag) + the GGUF model URL (or a `models/` fetch step). Because the model is *bundled*, script 02 downloads the GGUF into `$LFS/opt/aura/models/` and verifies its SHA256.
2. **`scripts/10-aurora-shell.sh`** — build llama.cpp (`cmake -DGGML_NATIVE=ON`), install `llama-server` to `/opt/aura/bin/`, place model, drop `aura-tools.json`.
3. **New systemd unit `aura-llm.service`** — starts `llama-server --model /opt/aura/models/<gguf> --host 127.0.0.1 --port 8080 --ctx-size 4096` as the unprivileged `aura` user; `aurorad.service` gains `Wants=aura-llm.service`.
4. **`shell/aurorad.py`** — `/ask` rewritten: build prompt from `aura-tools.json`, call llama.cpp, parse tool JSON, route system-side vs UI-side, fallback on failure.
5. **`shell/aurora-bridge.js`** — on `/ask` response, execute any `ran:false` actions via `Aura.run`; keep passing `a` to the chat panel.
6. **`shell/index.html`** — factor the `COMMANDS` arg-shapes into / from `aura-tools.json` so browser and server share one definition.

## Testing

- **Offline unit (host):** feed 20 canned user utterances → assert the model emits the expected `{cmd,args}` for command intents and prose for chat; run against a real `llama-server` on the build host (x86 is fine — model behavior is arch-independent). Gate: ≥90% intent match on the fixture set.
- **Fallback test:** kill `llama-server`, confirm `/ask` still returns a sane heuristic reply and never 500s.
- **Whitelist test:** inject a response naming a non-existent tool and a `power` tool → assert both are dropped, plain reply returned, nothing executed.
- **aarch64 build proof:** compile llama.cpp in the arm64 container (same harness that proved the labwc stack) — confirm `llama-server` builds and loads the GGUF.
- **In-VM smoke:** on the UTM VM, say "open files and dim the screen" → Files window opens, brightness slider moves.

## Performance expectations

- 1B Q4 on M4 CPU: first-token latency ~0.2–0.6 s, ~15–35 tok/s → a short assistant reply in ~1–2 s. Acceptable for a non-streaming v1.
- `--ctx-size 4096` keeps RAM modest (~1–1.5 GB resident incl. model). Fits comfortably.
- Idle cost: `llama-server` holds the model in RAM but uses ~0 CPU when not inferring.

## Open items for the plan

- Whether `search_files` runs server-side (aurorad has fs access) — lean yes.
- Streaming responses + multi-turn context = explicit phase 2, out of this spec.
