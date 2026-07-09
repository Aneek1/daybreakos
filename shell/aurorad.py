#!/usr/bin/env python3
"""aurorad — AuroraOS system bridge.

Tiny localhost HTTP API the web shell talks to. Root service, binds
127.0.0.1:7212 ONLY. Endpoints:

  GET  /status            battery, brightness, hostname, load, uptime, net
  GET  /files?path=~/x    list a directory (confined to /home and /usr/share/aurora)
  POST /brightness        {"percent": 0-100}
  POST /power             {"action": "poweroff"|"reboot"|"lock"}
  POST /launch            {"app": "<whitelisted>"}
  POST /ask               {"q": "..."} -> heuristic reply (drop an LLM here later)
"""
import json, os, glob, subprocess, time, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 7212
LAUNCH_WHITELIST = {"terminal": ["foot"], "editor": ["foot", "vi"]}
START = time.time()

def read1(path):
    try:
        with open(path) as f: return f.read().strip()
    except OSError: return None

def battery():
    for supply in glob.glob("/sys/class/power_supply/*"):
        if read1(supply + "/type") == "Battery":
            cap = read1(supply + "/capacity")
            return {"percent": int(cap) if cap else None,
                    "status": read1(supply + "/status")}
    return {"percent": None, "status": "AC"}

def backlight_dev():
    devs = glob.glob("/sys/class/backlight/*")
    return devs[0] if devs else None

def brightness_get():
    d = backlight_dev()
    if not d: return None
    cur, mx = read1(d + "/brightness"), read1(d + "/max_brightness")
    return round(int(cur) / int(mx) * 100) if cur and mx else None

def brightness_set(pct):
    d = backlight_dev()
    if not d: return False
    mx = int(read1(d + "/max_brightness") or 100)
    val = max(1, min(mx, round(mx * pct / 100)))
    with open(d + "/brightness", "w") as f: f.write(str(val))
    return True

def net_up():
    for iface in glob.glob("/sys/class/net/*"):
        if os.path.basename(iface) != "lo" and read1(iface + "/operstate") == "up":
            return os.path.basename(iface)
    return None

def safe_path(p):
    p = os.path.realpath(os.path.expanduser(p or "~"))
    if p.startswith(("/home", "/usr/share/aurora", "/tmp")): return p
    return "/home"

class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self): self._send({})

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/status":
            self._send({"battery": battery(), "brightness": brightness_get(),
                        "hostname": read1("/etc/hostname") or "aurora",
                        "load": os.getloadavg()[0], "uptime": int(time.time() - START),
                        "net": net_up(),
                        "os": "AuroraOS 1.0 (daybreak)"})
        elif url.path == "/files":
            path = safe_path(q.get("path", ["~"])[0])
            try:
                items = [{"name": e.name, "dir": e.is_dir()}
                         for e in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name))
                         if not e.name.startswith(".")][:200]
                self._send({"path": path, "items": items})
            except OSError as e:
                self._send({"error": str(e)}, 404)
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try: data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError: return self._send({"error": "bad json"}, 400)
        if self.path == "/brightness":
            ok = brightness_set(int(data.get("percent", 50)))
            self._send({"ok": ok})
        elif self.path == "/power":
            act = data.get("action")
            if act in ("poweroff", "reboot"):
                self._send({"ok": True})
                subprocess.Popen(["systemctl", act])
            elif act == "lock":
                self._send({"ok": True})  # shell handles its own lock UI
            else:
                self._send({"error": "bad action"}, 400)
        elif self.path == "/launch":
            cmd = LAUNCH_WHITELIST.get(data.get("app", ""))
            if cmd:
                subprocess.Popen(cmd, env={**os.environ, "WAYLAND_DISPLAY": "wayland-0"})
                self._send({"ok": True})
            else:
                self._send({"error": "not whitelisted"}, 403)
        elif self.path == "/ask":
            qs = (data.get("q") or "").lower()
            if "battery" in qs:
                b = battery()
                r = (f"Battery is at {b['percent']}% ({b['status']})."
                     if b["percent"] is not None else "No battery — running on AC power.")
            elif "bright" in qs:
                r = f"Brightness is {brightness_get() or 'not controllable on this device'}%."
            elif any(k in qs for k in ("off", "shutdown", "power")):
                r = "Say the word — POST /power with poweroff. Or use the start-menu power button."
            else:
                r = ("I'm the stub where an on-device model plugs in. Right now I can report "
                     "battery, brightness, and system status — the rest of AuroraOS is yours to build.")
            self._send({"a": r})
        else:
            self._send({"error": "not found"}, 404)

    def log_message(self, *a): pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
