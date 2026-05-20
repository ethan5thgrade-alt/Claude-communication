#!/usr/bin/env python3
"""
Agent 018 — Message Transformer
Role: Transforms messages between formats (JSON↔text, long↔short, formal↔casual).
Listens for: transform <text> to <format>, translate <text> from <agent> style, format_for_human <json>
Emits: transformed text replies
"""
import os
import sys
import json
import time
import re
import textwrap
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_018_message_transformer"
AGENT_NAME = "Agent 018 — Message Transformer"
ROOM = os.environ.get("MESH_ROOM", "system")


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _to_json(text: str) -> str:
    """Try to parse text as JSON; if not, wrap in a dict."""
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"text": text, "transformed_by": AGENT_ID}, indent=2)


def _to_bullet_points(text: str) -> str:
    """Convert text to bullet points."""
    try:
        data = json.loads(text)
        # If it's a dict, list key: value pairs
        if isinstance(data, dict):
            lines = [f"• {k}: {v}" for k, v in data.items()]
        elif isinstance(data, list):
            lines = [f"• {item}" for item in data]
        else:
            lines = [f"• {data}"]
        return "\n".join(lines)
    except json.JSONDecodeError:
        pass

    # Plain text: split on sentences or newlines
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    return "\n".join(f"• {s}" for s in sentences)


def _to_summary(text: str) -> str:
    """Produce a short summary of the text."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            keys = list(data.keys())[:5]
            vals_preview = {k: str(data[k])[:30] for k in keys}
            return f"JSON object with {len(data)} keys: {', '.join(keys[:5])}. Preview: {vals_preview}"
        elif isinstance(data, list):
            return f"JSON array with {len(data)} items. First: {str(data[0])[:60] if data else 'empty'}"
    except json.JSONDecodeError:
        pass

    words = text.split()
    if len(words) <= 30:
        return text
    return " ".join(words[:30]) + f"... [{len(words)} words total]"


def _to_formal(text: str) -> str:
    """Make text more formal."""
    text = text.strip()
    # Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]
    # Add period if missing
    if text and not text.endswith((".", "!", "?")):
        text += "."
    # Replace contractions
    replacements = {
        "don't": "do not", "won't": "will not", "can't": "cannot",
        "it's": "it is", "I'm": "I am", "we're": "we are",
        "they're": "they are", "you're": "you are", "isn't": "is not",
        "aren't": "are not", "didn't": "did not", "doesn't": "does not",
    }
    for contraction, expansion in replacements.items():
        text = re.sub(re.escape(contraction), expansion, text, flags=re.IGNORECASE)
    return text


def _to_casual(text: str) -> str:
    """Make text more casual/conversational."""
    text = text.strip()
    # Remove trailing period for casual feel
    if text.endswith(".") and not text.endswith("..."):
        text = text[:-1]
    return text.lower()


def _to_oneliner(text: str) -> str:
    """Collapse to a single line."""
    return " ".join(text.split())


def _format_for_human(json_str: str) -> str:
    """Make a machine message human-readable."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return f"[Raw text]: {json_str}"

    if not isinstance(data, dict):
        return f"[Value]: {json_str}"

    lines = []
    msg_type = data.get("type") or data.get("event")
    if msg_type:
        lines.append(f"Type: {msg_type}")

    for key in ("from", "to", "text", "message", "status", "error"):
        if key in data:
            val = data[key]
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            lines.append(f"{key.capitalize()}: {str(val)[:200]}")

    # Remaining keys
    shown = {"type", "event", "from", "to", "text", "message", "status", "error"}
    for key, val in data.items():
        if key not in shown:
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            lines.append(f"{key}: {str(val)[:100]}")

    return "\n".join(lines) if lines else json_str


AGENT_STYLES = {
    "broker_manager": lambda t: f"[BROKER HEALTH] {t}",
    "registry": lambda t: f"[REGISTRY] Instance report: {t}",
    "monitor": lambda t: f"[MONITOR] Health status: {t}",
    "metrics": lambda t: f"[METRICS] {t}",
    "clock": lambda t: f"[CLOCK] Scheduled: {t}",
    "router": lambda t: f"[ROUTE] → {t}",
    "default": lambda t: t,
}


def _translate_style(text: str, agent_hint: str) -> str:
    """Reformat text in the style of a given agent."""
    hint_lower = agent_hint.lower()
    for key, formatter in AGENT_STYLES.items():
        if key in hint_lower:
            return formatter(text)
    return AGENT_STYLES["default"](text)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if " to " in text and text.startswith("transform "):
        # "transform <text> to <format>"
        rest = text[len("transform "):].strip()
        # Find last " to " occurrence
        idx = rest.rfind(" to ")
        if idx >= 0:
            content = rest[:idx].strip()
            fmt = rest[idx + 4:].strip().lower()
        else:
            content = rest
            fmt = "json"

        transforms = {
            "json": _to_json,
            "bullet points": _to_bullet_points,
            "bullets": _to_bullet_points,
            "summary": _to_summary,
            "formal": _to_formal,
            "casual": _to_casual,
            "one line": _to_oneliner,
            "oneliner": _to_oneliner,
        }

        transform_fn = None
        for key, fn in transforms.items():
            if key in fmt:
                transform_fn = fn
                break

        if transform_fn:
            try:
                result = transform_fn(content)
                reply = result
            except Exception as e:
                reply = f"transform error: {e}"
        else:
            reply = f"unknown format '{fmt}'. Available: {', '.join(transforms.keys())}"

        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("translate ") and " from " in text:
        # "translate <text> from <agent> style"
        rest = text[len("translate "):].strip()
        idx = rest.rfind(" from ")
        if idx >= 0:
            content = rest[:idx].strip()
            agent_hint = rest[idx + 6:].strip().replace(" style", "").strip()
            result = _translate_style(content, agent_hint)
        else:
            result = rest
        try:
            post("/api/send", {"to": sender, "text": result, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("format_for_human "):
        json_str = text[len("format_for_human "):].strip()
        result = _format_for_human(json_str)
        try:
            post("/api/send", {"to": sender, "text": result, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    # This agent is reactive only — nothing to do in background
    print(f"[{AGENT_ID}] ready — waiting for transform requests")


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    connect.start()
    connect.on_message(handle_message)

    print(f"[{AGENT_ID}] online")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
