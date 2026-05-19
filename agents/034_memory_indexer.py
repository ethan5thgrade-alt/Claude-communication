#!/usr/bin/env python3
"""Agent 034 — Memory Indexer
Role: Builds and maintains a search index over memory entries.
Listens for: search_memory <query>, rebuild_index, index_stats
Emits: search results
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_034_memory_indexer"
AGENT_NAME = "Agent 034 — Memory Indexer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

CYCLE_INTERVAL = 600  # 10 minutes
INDEX_PATH = os.path.expanduser("~/Claude-communication/memory_index.json")

# In-memory index: word -> [key, key, ...]
_index = {}
_last_built = 0
_indexed_count = 0


def api(path, method="GET", data=None):
    url = f"{BROKER}{path}"
    try:
        if method == "GET":
            return requests.get(url, headers=HEADERS, timeout=5).json()
        return requests.post(url, json=data, headers=HEADERS, timeout=5).json()
    except Exception as e:
        print(f"[{AGENT_ID}] api error: {e}")
        return {}


def send(to, text):
    api("/api/send", "POST", {"to": to, "from": AGENT_ID, "text": text, "room": ROOM})


def get_memory():
    result = api("/api/memory")
    if isinstance(result, list):
        return result
    return result.get("memory", []) if isinstance(result, dict) else []


def tokenize(text):
    """Simple word tokenizer: lowercase, split on non-alphanumeric."""
    import re
    return set(re.findall(r'[a-z0-9]+', str(text).lower()))


def build_index(entries):
    global _index, _last_built, _indexed_count
    _index = {}
    for entry in entries:
        key = entry.get("key", "")
        value = entry.get("value", "")
        words = tokenize(key) | tokenize(value) | tokenize(entry.get("type", ""))
        for word in words:
            if len(word) < 2:
                continue
            if word not in _index:
                _index[word] = []
            if key not in _index[word]:
                _index[word].append(key)
    _last_built = time.time()
    _indexed_count = len(entries)

    # Persist to disk
    try:
        with open(INDEX_PATH, "w") as f:
            json.dump({
                "built_at": _last_built,
                "indexed_count": _indexed_count,
                "index": _index,
            }, f)
    except Exception as e:
        print(f"[{AGENT_ID}] failed to save index: {e}")

    print(f"[{AGENT_ID}] index built: {len(_index)} words, {_indexed_count} entries")


def run_cycle():
    entries = get_memory()
    build_index(entries)


def search(query):
    """Return keys of memory entries matching the query."""
    words = tokenize(query)
    if not words:
        return []
    # Score each key by how many query words match
    scores = {}
    for word in words:
        for key in _index.get(word, []):
            scores[key] = scores.get(key, 0) + 1
    sorted_keys = sorted(scores.items(), key=lambda x: -x[1])
    return [k for k, _ in sorted_keys[:10]]


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("search_memory "):
        query = text[len("search_memory "):].strip()
        if not _index:
            send(sender, "index not built yet; rebuilding now")
            run_cycle()

        matching_keys = search(query)
        if not matching_keys:
            send(sender, f"no results for '{query}'")
            return

        # Retrieve full entries for matching keys
        entries = get_memory()
        entry_map = {e.get("key"): e for e in entries}
        results = []
        for key in matching_keys:
            entry = entry_map.get(key)
            if entry:
                results.append({
                    "key": key,
                    "value": str(entry.get("value", ""))[:300],
                    "type": entry.get("type"),
                })
        send(sender, json.dumps(results))

    elif text == "rebuild_index":
        run_cycle()
        send(sender, f"index rebuilt: {len(_index)} words, {_indexed_count} entries")

    elif text == "index_stats":
        send(sender, json.dumps({
            "word_count": len(_index),
            "indexed_entries": _indexed_count,
            "last_built_ts": _last_built,
            "index_path": INDEX_PATH,
        }))


import connect as _connect_mod


def main():
    os.environ["INSTANCE_ID"] = AGENT_ID
    os.environ["INSTANCE_NAME"] = AGENT_NAME
    os.environ["INSTANCE_ROOM"] = ROOM
    _connect_mod.start()
    _connect_mod.on_message(handle_message)

    print(f"[{AGENT_ID}] online in room '{ROOM}'")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[{AGENT_ID}] cycle error: {e}")
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
