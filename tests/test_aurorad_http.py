# tests/test_aurorad_http.py - aurorad refuses requests a web page could send (spec 5.4)
import http.client, os, pathlib, socket, subprocess, sys, time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JSON = "application/json"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def port():
    p = _free_port()
    env = {**os.environ, "AURORAD_PORT": str(p), "AURA_LLM_URL": "http://127.0.0.1:9/v1/chat/completions"}
    proc = subprocess.Popen([sys.executable, str(ROOT / "shell/aurorad.py")], env=env)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", p), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield p
    proc.kill()
    proc.wait()


def _post(port, headers, body=b'{"action": "lock"}', path="/power"):
    """POST with exactly these headers. The "lock" action only answers ok; it runs nothing."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
    for key, value in headers.items():
        conn.putheader(key, value)
    conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}


def test_native_client_headers_are_accepted(port):
    for headers in ({"Host": "127.0.0.1", "Content-Type": JSON},
                    {"Host": f"127.0.0.1:{port}", "Content-Type": JSON},
                    {"Host": "localhost", "Content-Type": "application/json; charset=utf-8"}):
        assert _post(port, headers)[0] == 200, headers


def test_request_with_an_origin_is_refused(port):
    for origin in ("https://example.com", "null"):
        assert _post(port, {"Host": "127.0.0.1", "Content-Type": JSON, "Origin": origin})[0] == 403, origin


def test_non_json_content_type_is_refused(port):
    for headers in ({"Host": "127.0.0.1", "Content-Type": "text/plain"},
                    {"Host": "127.0.0.1", "Content-Type": "application/x-www-form-urlencoded"},
                    {"Host": "127.0.0.1"}):
        assert _post(port, headers)[0] == 403, headers


def test_foreign_host_is_refused(port):
    # A DNS-rebinding page reaches 127.0.0.1 under its own host name.
    for host in ("attacker.example", "x"):
        assert _post(port, {"Host": host, "Content-Type": JSON})[0] == 403, host


def test_refusal_happens_before_the_body_is_read(port):
    status, _ = _post(port, {"Host": "127.0.0.1", "Content-Type": "text/plain", "Origin": "null"}, body=b"not json")
    assert status == 403


def test_responses_carry_no_cors_headers(port):
    status, headers = _post(port, {"Host": "127.0.0.1", "Content-Type": JSON})
    assert status == 200
    assert "access-control-allow-origin" not in headers
