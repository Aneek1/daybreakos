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
