"""Recognise typed power requests and describe the confirmation Aura shows for them.
Stdlib only (ships to the LFS target).

Nothing here powers anything off. /ask runs in the unprivileged session aurorad;
the Aura panel shows Power off / Cancel and, on a click, calls the root service's
/system/power itself."""
import re

CONFIRM_SECONDS = 30

# "turn off" / "switch off" alone also covers wi-fi, night light, bluetooth...
_DEVICE = r"(?:the\s+|my\s+|this\s+)?(?:computer|pc|laptop|machine|system)"
_POWEROFF = re.compile(r"\b(?:shut\s?down|power\s?off|(?:turn|switch)\s+off\s+" + _DEVICE + r")\b", re.I)
_REBOOT = re.compile(r"\b(?:restart|reboot)\b", re.I)

_PROMPTS = {
    "poweroff": ("Power off now?", "Power off"),
    "reboot": ("Restart now?", "Restart"),
}


def power_request(text):
    """'poweroff', 'reboot', or None."""
    text = text or ""
    if _POWEROFF.search(text):
        return "poweroff"
    if _REBOOT.search(text):
        return "reboot"
    return None


def confirm_payload(action):
    if action not in _PROMPTS:
        raise ValueError(f"not a power action: {action!r}")
    question, label = _PROMPTS[action]
    return {"a": question, "actions": [],
            "confirm": {"action": action, "label": label, "expires_in": CONFIRM_SECONDS}}
