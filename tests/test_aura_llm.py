# tests/test_aura_llm.py
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "shell"))
import aura_llm

def test_load_tools_reads_registry():
    tools = aura_llm.load_tools()
    names = {t["name"] for t in tools}
    assert "set_brightness" in names and "open_app" in names

def test_build_prompt_lists_tools_and_forbids_invention():
    tools = aura_llm.load_tools()
    system, user = aura_llm.build_prompt(tools, "open files")
    assert "set_brightness" in system and "open_app" in system
    assert "never invent" in system.lower()
    assert user == "open files"

def test_parse_extracts_tool_calls():
    out = '{"reply":"On it.","tool_calls":[{"cmd":"open_app","args":{"app":"files"}}]}'
    r = aura_llm.parse_model_output(out)
    assert r["reply"] == "On it."
    assert r["tool_calls"] == [{"cmd": "open_app", "args": {"app": "files"}}]

def test_parse_json_embedded_in_prose():
    out = 'Sure!\n{"reply":"Opening.","tool_calls":[{"cmd":"browse","args":{"q":"bbc.com"}}]}\nDone.'
    r = aura_llm.parse_model_output(out)
    assert r["tool_calls"][0]["cmd"] == "browse"

def test_parse_plain_chat_has_no_tool_calls():
    r = aura_llm.parse_model_output("The capital of France is Paris.")
    assert r["tool_calls"] == []
    assert "Paris" in r["reply"]

def test_parse_malformed_json_degrades_to_chat():
    r = aura_llm.parse_model_output('{"reply": "oops", "tool_calls": [broken')
    assert r["tool_calls"] == []

def test_validate_accepts_known_tool_with_known_args():
    tools = aura_llm.load_tools()
    assert aura_llm.validate_call({"cmd": "set_brightness", "args": {"percent": 40}}, tools)

def test_validate_rejects_unknown_tool():
    tools = aura_llm.load_tools()
    assert not aura_llm.validate_call({"cmd": "delete_everything", "args": {}}, tools)

def test_validate_rejects_power_even_if_model_emits_it():
    tools = aura_llm.load_tools()
    assert not aura_llm.validate_call({"cmd": "power", "args": {"action": "poweroff"}}, tools)

def test_validate_rejects_unknown_arg_keys():
    tools = aura_llm.load_tools()
    assert not aura_llm.validate_call({"cmd": "open_app", "args": {"rm": "-rf"}}, tools)

def test_route_executes_system_tool_and_marks_ran():
    tools = aura_llm.load_tools()
    calls = []
    execs = {"set_brightness": lambda args: calls.append(args) or "brightness 40%"}
    actions, notes = aura_llm.route(
        [{"cmd": "set_brightness", "args": {"percent": 40}}], tools, execs)
    assert calls == [{"percent": 40}]
    assert actions == [{"cmd": "set_brightness", "args": {"percent": 40}, "ran": True}]
    assert "brightness 40%" in notes[0]

UI_TOOLS = [{"name": "show_panel", "side": "ui", "description": "Show a shell panel.",
             "args": {"panel": "panel name"}}]

def test_route_defers_ui_tool_unrun():
    # The native registry has no UI-side tools; the routing rule is still tested with one.
    actions, notes = aura_llm.route(
        [{"cmd": "show_panel", "args": {"panel": "widgets"}}], UI_TOOLS, {})
    assert actions == [{"cmd": "show_panel", "args": {"panel": "widgets"}, "ran": False}]

def test_route_drops_invalid_calls():
    tools = aura_llm.load_tools()
    actions, notes = aura_llm.route([{"cmd": "power", "args": {}}], tools, {})
    assert actions == []

def test_fallback_reports_battery():
    r = aura_llm.heuristic_fallback("what's my battery",
                                    status={"battery": {"percent": 88, "status": "Discharging"}})
    assert "88%" in r

def test_fallback_default_message():
    r = aura_llm.heuristic_fallback("tell me a joke", status={})
    assert "battery" in r.lower() or "status" in r.lower()

def test_call_llama_posts_messages_and_reads_content(monkeypatch):
    captured = {}
    class FakeResp:
        def read(self): return b'{"choices":[{"message":{"content":"hi there"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        return FakeResp()
    monkeypatch.setattr(aura_llm.urllib.request, "urlopen", fake_urlopen)
    out = aura_llm.call_llama("SYS", "hello")
    assert out == "hi there"
    body = aura_llm.json.loads(captured["body"])
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "hello"

def test_call_llama_returns_none_on_connection_error(monkeypatch):
    def boom(req, timeout=None):
        raise aura_llm.urllib.error.URLError("refused")
    monkeypatch.setattr(aura_llm.urllib.request, "urlopen", boom)
    assert aura_llm.call_llama("SYS", "hello") is None

def _tools(): return aura_llm.load_tools()

def test_ask_happy_path_executes_and_returns_actions(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama",
        lambda s, u, schema=None: '{"reply":"Opening Files.","tool_calls":[{"cmd":"open_app","args":{"name":"files"}}]}')
    out = aura_llm.ask("open files", executors={"open_app": lambda a: None}, status={})
    assert out["actions"] == [{"cmd": "open_app", "args": {"name": "files"}, "ran": True}]
    assert "Opening Files" in out["a"]

def test_ask_merges_system_notes_into_reply(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama",
        lambda s, u, schema=None: '{"reply":"Done.","tool_calls":[{"cmd":"set_brightness","args":{"percent":40}}]}')
    execs = {"set_brightness": lambda a: "brightness set to 40%"}
    out = aura_llm.ask("set brightness to 40", executors=execs, status={})
    assert out["actions"][0]["ran"] is True
    assert "brightness set to 40%" in out["a"]

def test_ask_falls_back_when_model_down(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama", lambda s, u, schema=None: None)
    out = aura_llm.ask("what's my battery",
                       executors={}, status={"battery": {"percent": 55, "status": "Full"}})
    assert "55%" in out["a"]
    assert out["actions"] == []

def test_ask_falls_back_on_garbage(monkeypatch):
    monkeypatch.setattr(aura_llm, "call_llama", lambda s, u, schema=None: "%%% not json %%%")
    out = aura_llm.ask("hello", executors={}, status={})
    assert out["actions"] == []
    assert out["a"]  # non-empty prose (the model's own text)

def test_route_system_tool_without_executor_is_not_ran():
    tools = aura_llm.load_tools()
    actions, notes = aura_llm.route([{"cmd": "system_status", "args": {}}], tools, {})
    assert actions == [{"cmd": "system_status", "args": {}, "ran": False}]

def test_route_executor_exception_is_guarded():
    tools = aura_llm.load_tools()
    def boom(a): raise RuntimeError("hardware fault")
    actions, notes = aura_llm.route(
        [{"cmd": "set_brightness", "args": {"percent": 40}}], tools, {"set_brightness": boom})
    assert actions[0]["ran"] is False
    assert notes  # a short error note was recorded

def test_validate_rejects_non_dict_args():
    tools = aura_llm.load_tools()
    assert not aura_llm.validate_call({"cmd": "set_brightness", "args": ["percent"]}, tools)

def test_parse_non_dict_args_coerced_to_empty():
    out = '{"reply":"x","tool_calls":[{"cmd":"set_brightness","args":["percent"]}]}'
    r = aura_llm.parse_model_output(out)
    assert r["tool_calls"] == [{"cmd": "set_brightness", "args": {}}]

def test_parse_tool_call_object_followed_by_more_json():
    out = '{"reply":"On it.","tool_calls":[{"cmd":"open_app","args":{"app":"files"}}]} then {"x":1}'
    r = aura_llm.parse_model_output(out)
    assert r["tool_calls"] == [{"cmd": "open_app", "args": {"app": "files"}}]
    assert r["reply"] == "On it."

def test_call_llama_returns_none_on_non_dict_json(monkeypatch):
    class FakeResp:
        def read(self): return b'[1, 2, 3]'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(aura_llm.urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    assert aura_llm.call_llama("SYS", "hello") is None

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

CUT_OFF = ('{"reply": "Photosynthesis is the process by which green plants use sunlight '
           'to turn water and carbon dioxide into')

def test_ask_keeps_a_schema_reply_cut_off_at_the_token_limit(monkeypatch):
    monkeypatch.setenv("AURA_LLM_SCHEMA", "1")
    monkeypatch.setattr(aura_llm, "model_installed", lambda: True)
    monkeypatch.setattr(aura_llm, "call_llama", lambda s, u, schema=None: CUT_OFF)
    out = aura_llm.ask("explain photosynthesis", executors={}, status={})
    assert out["a"].startswith("Photosynthesis") and "warming up" not in out["a"]
    assert out["actions"] == []

def test_parse_cut_off_reply_decodes_escapes_but_never_half_written_calls():
    bs = chr(92)
    assert aura_llm.parse_model_output('{"reply": "Say ' + bs + '"hi' + bs + '" now' + bs) == \
        {"reply": 'Say "hi" now', "tool_calls": []}
    assert aura_llm.parse_model_output('{"reply": "Caf' + bs + 'u00e9 ' + bs + 'u00')["reply"] == "Café"
    half_call = '{"reply": "Opening a terminal.", "tool_calls": [{"cmd": "open_te'
    assert aura_llm.parse_model_output(half_call)["reply"] == half_call

def test_call_llama_gives_schema_mode_room_for_the_json_wrapper(monkeypatch):
    bodies = []
    class FakeResp:
        def read(self): return b'{"choices":[{"message":{"content":"{}"}}]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(aura_llm.urllib.request, "urlopen",
                        lambda req, timeout=None: bodies.append(aura_llm.json.loads(req.data)) or FakeResp())
    aura_llm.call_llama("S", "U")
    aura_llm.call_llama("S", "U", schema={"type": "object"})
    assert bodies[0]["max_tokens"] == 128
    assert bodies[1]["max_tokens"] == 192

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
