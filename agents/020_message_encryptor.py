#!/usr/bin/env python3
"""
Agent 020 — Message Encryptor
Role: Encrypts/decrypts sensitive messages using shared secret.
Listens for: encrypt <text>, decrypt <ciphertext>, send_secure <to> <text>, secure_channel <instance_id>
Emits: encrypted messages, decrypted content replies
"""
import os
import sys
import json
import time
import base64
import hashlib
import hmac
import secrets
import requests
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connect

BROKER_HTTP = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_020_message_encryptor"
AGENT_NAME = "Agent 020 — Message Encryptor"
ROOM = os.environ.get("MESH_ROOM", "system")

_lock = threading.Lock()
# Secure sessions: instance_id -> session_key (bytes)
_sessions: dict = {}
# Session nonces to prevent replay: frozenset of seen nonces
_used_nonces: set = set()


def get(path):
    return requests.get(f"{BROKER_HTTP}{path}", timeout=5).json()


def post(path, data):
    return requests.post(f"{BROKER_HTTP}{path}", json=data, timeout=5).json()


def _get_key() -> bytes:
    """Get encryption key from MESH_TOKEN env var, or use a default."""
    token = os.environ.get("MESH_TOKEN", "agent-mesh-default-key-2024")
    # Derive a 32-byte key from the token using SHA-256
    return hashlib.sha256(token.encode("utf-8")).digest()


def _xor_encrypt(plaintext: str, key: bytes) -> str:
    """XOR-encrypt plaintext with key (repeated), return base64-encoded ciphertext."""
    plaintext_bytes = plaintext.encode("utf-8")
    key_repeated = bytes([key[i % len(key)] for i in range(len(plaintext_bytes))])
    cipher_bytes = bytes([p ^ k for p, k in zip(plaintext_bytes, key_repeated)])
    # Include a nonce for replay protection
    nonce = secrets.token_hex(8)
    payload = json.dumps({
        "nonce": nonce,
        "cipher": base64.b64encode(cipher_bytes).decode("ascii"),
        "hmac": _compute_hmac(cipher_bytes, key, nonce),
    })
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _xor_decrypt(ciphertext_b64: str, key: bytes) -> str:
    """Decrypt base64-encoded XOR ciphertext. Returns plaintext or raises."""
    try:
        payload_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
        nonce = payload["nonce"]
        cipher_bytes = base64.b64decode(payload["cipher"].encode("ascii"))
        mac = payload.get("hmac", "")

        # Verify HMAC
        expected_mac = _compute_hmac(cipher_bytes, key, nonce)
        if not hmac.compare_digest(mac, expected_mac):
            raise ValueError("HMAC verification failed — message may be tampered")

        # Replay protection
        with _lock:
            if nonce in _used_nonces:
                raise ValueError("Replay detected — nonce already used")
            _used_nonces.add(nonce)
            # Prune nonces to avoid unbounded growth
            if len(_used_nonces) > 10000:
                to_remove = list(_used_nonces)[:5000]
                for n in to_remove:
                    _used_nonces.discard(n)

        # Decrypt
        key_repeated = bytes([key[i % len(key)] for i in range(len(cipher_bytes))])
        plain_bytes = bytes([c ^ k for c, k in zip(cipher_bytes, key_repeated)])
        return plain_bytes.decode("utf-8")
    except (KeyError, json.JSONDecodeError):
        # Legacy fallback: raw base64 XOR without nonce/HMAC
        cipher_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
        key_repeated = bytes([key[i % len(key)] for i in range(len(cipher_bytes))])
        plain_bytes = bytes([c ^ k for c, k in zip(cipher_bytes, key_repeated)])
        return plain_bytes.decode("utf-8")


def _compute_hmac(data: bytes, key: bytes, nonce: str) -> str:
    """Compute HMAC-SHA256 over data + nonce."""
    mac_input = data + nonce.encode("utf-8")
    return hmac.new(key, mac_input, hashlib.sha256).hexdigest()


def _generate_session_key() -> bytes:
    """Generate a fresh session key for a secure channel."""
    return secrets.token_bytes(32)


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")
    key = _get_key()

    if text.startswith("encrypt "):
        plaintext = text[len("encrypt "):].strip()
        try:
            ciphertext = _xor_encrypt(plaintext, key)
            reply = json.dumps({
                "status": "encrypted",
                "ciphertext": ciphertext,
                "note": "XOR-encrypted with MESH_TOKEN key",
            })
        except Exception as e:
            reply = json.dumps({"status": "error", "message": str(e)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("decrypt "):
        ciphertext = text[len("decrypt "):].strip()
        try:
            plaintext = _xor_decrypt(ciphertext, key)
            reply = json.dumps({
                "status": "decrypted",
                "plaintext": plaintext,
            })
        except Exception as e:
            reply = json.dumps({"status": "error", "message": str(e)})
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("send_secure "):
        rest = text[len("send_secure "):].strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2:
            reply = "usage: send_secure <to_instance_id> <text>"
            try:
                post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
            except Exception:
                pass
            return
        target_id = parts[0]
        plaintext = parts[1]

        # Check for a session key for this target
        with _lock:
            session_key = _sessions.get(target_id, key)

        try:
            ciphertext = _xor_encrypt(plaintext, session_key)
            encrypted_payload = json.dumps({
                "type": "secure_message",
                "from": sender,
                "ciphertext": ciphertext,
                "ts": datetime.utcnow().isoformat(),
            })
            post("/api/send", {"to": target_id, "text": encrypted_payload, "from": AGENT_ID})
            reply = f"secure message sent to {target_id}"
        except Exception as e:
            reply = f"send_secure failed: {e}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass

    elif text.startswith("secure_channel "):
        target_id = text[len("secure_channel "):].strip()
        session_key = _generate_session_key()
        with _lock:
            _sessions[target_id] = session_key

        # Send the session key to the target (encrypted with the master key)
        session_key_b64 = base64.b64encode(session_key).decode("ascii")
        encrypted_session = _xor_encrypt(session_key_b64, key)
        handshake_msg = json.dumps({
            "type": "secure_channel_handshake",
            "from": AGENT_ID,
            "session_key_encrypted": encrypted_session,
            "ts": datetime.utcnow().isoformat(),
        })
        try:
            post("/api/send", {"to": target_id, "text": handshake_msg, "from": AGENT_ID})
            reply = f"secure channel established with {target_id}. Session key exchanged."
        except Exception as e:
            reply = f"secure channel setup failed: {e}"
        try:
            post("/api/send", {"to": sender, "text": reply, "from": AGENT_ID})
        except Exception:
            pass


def run_cycle():
    # Reactive agent — prune expired nonces periodically
    with _lock:
        if len(_used_nonces) > 5000:
            to_remove = list(_used_nonces)[:2500]
            for n in to_remove:
                _used_nonces.discard(n)
    print(f"[{AGENT_ID}] ready — {len(_sessions)} active secure channels, {len(_used_nonces)} tracked nonces")


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
