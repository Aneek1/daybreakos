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
