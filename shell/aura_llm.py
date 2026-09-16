"""Aura's on-device LLM layer: prompt -> llama.cpp -> validated tool calls.
Stdlib only (ships to the LFS target). aurorad.py calls ask()."""
import json, os, re, urllib.request, urllib.error

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

HERE = os.path.dirname(os.path.abspath(__file__))

def _default_tools_path():
    """Find aura-tools.json across the layouts it ships in (installed vs repo).
    Returning a real path matters: a missing file made every /ask raise."""
    for c in (os.path.join(HERE, "config", "aura-tools.json"),
              os.path.join(HERE, "..", "config", "aura-tools.json"),
              "/opt/aura/config/aura-tools.json",
              "/usr/share/aurora/config/aura-tools.json",
              "/aurora/config/aura-tools.json"):
        if os.path.exists(c):
            return c
    return os.path.join(HERE, "config", "aura-tools.json")

TOOLS_PATH = os.environ.get("AURA_TOOLS", _default_tools_path())
LLAMA_URL = os.environ.get("AURA_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
LLAMA_TIMEOUT = float(os.environ.get("AURA_LLM_TIMEOUT", "90"))

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
    # maxItems 1: measured runs showed the model repeating one call until the
    # token limit, which cost latency and truncated the output.
    calls = ({"type": "array", "maxItems": 1, "items": {"anyOf": variants}}
             if variants else {"type": "array", "maxItems": 0})
    return {"type": "object",
            "properties": {"reply": {"type": "string"}, "tool_calls": calls},
            "required": ["reply", "tool_calls"]}

def load_tools(path=None):
    """Load the tool registry; return [] if it can't be read so /ask never 500s."""
    try:
        with open(path or TOOLS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []

def build_prompt(tools, user_text, schema_mode=False):
    lines = []
    for t in tools:
        args = ", ".join(f"{k} ({v})" for k, v in t["args"].items()) or "none"
        lines.append(f'- {t["name"]}: {t["description"]} args: {args}')
    example = (
        '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_terminal", "args": {}}]}\n'
        '"how is my machine doing" is {"cmd":"system_status","args":{}}\n'
        '"which programs are on here" is {"cmd":"list_apps","args":{}}\n')
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

def _json_candidates(text):
    """Yield each top-level {...} substring via a brace-depth scan, so multiple
    JSON objects in the text are tried independently (not greedily merged).
    String-literal edge cases (braces inside strings) are acceptable to ignore for v1."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                yield text[start:i + 1]
                start = -1

def parse_model_output(text):
    """Return {'reply': str, 'tool_calls': [{'cmd','args'}]}. Never raises."""
    text = (text or "").strip()
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and ("tool_calls" in obj or "reply" in obj):
            calls = obj.get("tool_calls") or []
            if not isinstance(calls, list):
                calls = []
            clean = [{"cmd": c.get("cmd"),
                      "args": c.get("args") if isinstance(c.get("args"), dict) else {}}
                     for c in calls if isinstance(c, dict) and c.get("cmd")]
            return {"reply": str(obj.get("reply") or "").strip(), "tool_calls": clean}
    cut = _cut_off_reply(text)
    if cut is not None:
        return {"reply": cut, "tool_calls": []}
    return {"reply": text, "tool_calls": []}

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

# A schema-mode reply cut off at max_tokens has no closing brace. When the cut is
# inside the "reply" string, keep that text (free mode shows the same text cut
# short). If the reply string closed and the cut is later, a tool call may be
# half written, so nothing is recovered and the reply is treated as bad.
_CUT_REPLY = re.compile(r'\s*\{\s*"reply"\s*:\s*"((?:[^"\\]|\\u[0-9a-fA-F]{4}|\\[^u])*)(\\(?:u[0-9a-fA-F]{0,3})?)?$')

def _cut_off_reply(text):
    m = _CUT_REPLY.match(text)
    if not m:
        return None
    try:
        return json.loads('"' + m.group(1) + '"').strip()
    except ValueError:
        return None

def _tool_index(tools):
    return {t["name"]: t for t in tools}

def validate_call(call, tools):
    """True only if cmd is a registry tool and every arg key is declared.
    NOTE: this validates arg *keys* only. Executors MUST sanitize arg *values*
    (the registry's "integer 0-100" prose is descriptive, not enforced here)."""
    idx = _tool_index(tools)
    spec = idx.get(call.get("cmd"))
    if not spec:
        return False
    args = call.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return False
    allowed = set(spec["args"].keys())
    return all(k in allowed for k in args)

def route(calls, tools, executors):
    """Execute system-side tools now; mark UI-side tools for the browser.
    Returns (actions, notes) where notes are server-side result strings."""
    idx = _tool_index(tools)
    actions, notes = [], []
    for call in calls:
        if not validate_call(call, tools):
            continue
        spec = idx[call["cmd"]]
        args = call.get("args") or {}
        if spec["side"] == "system":
            fn = executors.get(call["cmd"])
            ran = False
            if fn:
                try:
                    note = fn(args)
                    ran = True
                    if note:
                        notes.append(note)
                except Exception:
                    notes.append("Couldn't complete that action.")
            actions.append({"cmd": call["cmd"], "args": args, "ran": ran})
        else:
            actions.append({"cmd": call["cmd"], "args": args, "ran": False})
    return actions, notes

MODEL_DIR = os.environ.get("AURA_MODEL_DIR", "/opt/aura/models")

def model_installed():
    """True if a .gguf model is on disk. Distinguishes 'still loading' (be
    patient) from 'never downloaded' (tell the user to run Set up Aura)."""
    try:
        return any(f.endswith(".gguf") for f in os.listdir(MODEL_DIR))
    except OSError:
        return False

_SETUP_HINT = ('I don\'t have my language model on this machine yet — open the '
               'Daybreak menu and choose "Set up Aura (AI)" to download it '
               '(~1.0 GB, one time). Until then I can still open apps and '
               'report system status.')

def heuristic_fallback(user_text, status=None):
    """Deterministic reply when the model is unavailable or produced garbage."""
    # Strip punctuation so "hi!", "Hey :)" etc. still match the greeting.
    qs = re.sub(r"[^a-z0-9' ]+", " ", (user_text or "").lower()).strip()
    status = status or {}
    if any(qs == g or qs.startswith(g + " ") for g in ("hi", "hello", "hey", "yo", "hiya", "sup")):
        hello = "Hi! I'm Aura, your on-device assistant. Ask me anything, or tell me to open an app or check the system."
        return hello if model_installed() else hello + " " + _SETUP_HINT
    if "battery" in qs:
        b = status.get("battery") or {}
        pct = b.get("percent")
        return (f"Battery is at {pct}% ({b.get('status','')})." if pct is not None
                else "No battery — running on AC power.")
    if "bright" in qs:
        return f"Brightness is {status.get('brightness') or 'not controllable on this device'}%."
    if any(k in qs for k in ("off", "shutdown", "power")):
        return "You can shut down or restart from the power controls, or just ask me to."
    if not model_installed():
        return _SETUP_HINT
    return ("I'm still warming up — the on-device model is loading. Give me a few "
            "seconds and ask again. Meanwhile I can open apps, open a terminal, "
            "and report system status.")

def _reply_is_bad(reply):
    """True if the text is empty, leaked JSON, or an unfilled prompt placeholder
    (small models sometimes echo the template, e.g. '<short confirmation>')."""
    r = (reply or "").strip()
    if not r:
        return True
    if r.startswith("{") or r.startswith("["):
        return True
    if "<short confirmation>" in r or "<tool>" in r or "<reply>" in r:
        return True
    if r.startswith("<") and r.endswith(">") and len(r) < 60:
        return True
    return False

def call_llama(system, user, schema=None):
    """POST to llama-server; return assistant content or None on any failure."""
    payload = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        # Schema mode spends ~10 tokens on the JSON wrapper around the same reply.
        "max_tokens": 128 if schema is None else 192,
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

def ask(user_text, executors=None, status=None, tools=None):
    """Full pipeline: model -> parse -> validate/route -> reply. Always returns
    {'a': str, 'actions': [...]}. Falls back to heuristics if the model fails."""
    executors = executors or {}
    tools = tools if tools is not None else load_tools()
    schema = response_schema(tools) if schema_enabled() else None
    system, user = build_prompt(tools, user_text, schema_mode=schema is not None)
    raw = call_llama(system, user, schema=schema)
    if raw is None:
        return {"a": heuristic_fallback(user_text, status), "actions": []}
    parsed = parse_model_output(raw)
    # Aliases are applied here, not in parse_model_output, so model-level
    # evaluation still sees exactly what the model produced.
    calls = apply_aliases(parsed["tool_calls"], tools)
    if calls and not action_allowed(user_text):
        calls = []   # model invented an action for conversational input — ignore it
    actions, notes = route(calls, tools, executors)
    reply = parsed["reply"] or ""
    if notes:
        reply = (reply + " " + " ".join(notes)).strip()
    # Small models sometimes leak raw/partial JSON or echo the prompt template
    # (e.g. "<short confirmation>"). Never surface that — fall back to clean text.
    # If an action actually ran, keep the note text even if the model's prose was bad.
    if _reply_is_bad(reply):
        reply = " ".join(notes).strip() if notes else heuristic_fallback(user_text, status)
    return {"a": reply, "actions": actions}
