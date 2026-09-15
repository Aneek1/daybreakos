"""Recognise typed power requests and describe the confirmation Aura shows for them.
Stdlib only (ships to the LFS target).

Nothing here powers anything off. /ask runs in the unprivileged session aurorad;
the Aura panel shows Power off / Cancel and, on a click, calls the root service's
/system/power itself."""
import re

CONFIRM_SECONDS = 30

# "turn off" / "switch off" alone also covers wi-fi, night light, bluetooth...
# The lookahead keeps "turn off the system sounds" / "my laptop screen" from counting.
_DEVICE = (r"(?:the\s+|my\s+|this\s+)?(?:computer|pc|laptop|machine|system)\b"
           r"(?!\s+(?:sounds?|settings?|notifications?|tray|preferences?|updates?|logs?|volume"
           r"|screen|display|monitor))")
# Bare "shut down" / "power off" stay unanchored on purpose (product default).
_POWEROFF = re.compile(
    r"\b(?:shut\s?down|power\s?(?:off|down))\b"
    r"|\b(?:turn|switch)\s+off\s+" + _DEVICE +
    r"|\b(?:turn|switch)\s+" + _DEVICE + r"\s+off\b"
    r"|\bshut\s+" + _DEVICE + r"\s+down\b", re.I)
# Reboot needs a command form: the whole message is the bare command (with optional
# please / can you / now and trailing punctuation), or it names the device.
# "restart firefox" and "what does reboot mean" are not requests.
_REBOOT_COMMAND = re.compile(
    r"^\s*(?:(?:please|can\s+you|could\s+you)\s+)?(?:reboot|restart)"
    r"(?:\s+now)?(?:\s+please)?\s*[.!?]*\s*$", re.I)
_REBOOT_DEVICE = re.compile(r"\b(?:restart|reboot)\s+" + _DEVICE, re.I)

_PROMPTS = {
    "poweroff": ("Power off now?", "Power off"),
    "reboot": ("Restart now?", "Restart"),
}


def power_request(text):
    """'poweroff', 'reboot', or None."""
    text = text or ""
    if _POWEROFF.search(text):
        return "poweroff"
    if _REBOOT_COMMAND.match(text) or _REBOOT_DEVICE.search(text):
        return "reboot"
    return None


def confirm_payload(action):
    if action not in _PROMPTS:
        raise ValueError(f"not a power action: {action!r}")
    question, label = _PROMPTS[action]
    return {"a": question, "actions": [],
            "confirm": {"action": action, "label": label, "expires_in": CONFIRM_SECONDS}}
