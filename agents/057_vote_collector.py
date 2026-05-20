#!/usr/bin/env python3
"""Agent 057 — Vote Collector
Role: Collects and validates votes from instances.
Listens for: vote_yes <vote_id>, vote_no <vote_id>, vote <vote_id> <option>,
             change_vote <vote_id> <new_option>
Emits: vote confirmations, tally updates
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_057_vote_collector"
AGENT_NAME = "Agent 057 — Vote Collector"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

INBOX_DIR = os.path.expanduser("~/.agent-mesh-inbox")
VOTES_FILE = os.path.join(INBOX_DIR, "votes.json")


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


def broadcast(text):
    send("all", text)


def _load_votes():
    if os.path.exists(VOTES_FILE):
        try:
            with open(VOTES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_votes(votes):
    os.makedirs(INBOX_DIR, exist_ok=True)
    with open(VOTES_FILE, "w") as f:
        json.dump(votes, f, indent=2)


def _register_vote(vote_id, instance_id, option):
    votes = _load_votes()
    if vote_id not in votes:
        votes[vote_id] = {}
    votes[vote_id][instance_id] = option
    _save_votes(votes)

    # Also POST to broker
    api("/api/vote/cast", "POST", {
        "vote_id": vote_id,
        "option": option,
        "by": instance_id,
        "room": ROOM,
    })
    return votes[vote_id]


def _get_tally(vote_id):
    votes = _load_votes()
    ballots = votes.get(vote_id, {})
    tally = {}
    for _, opt in ballots.items():
        tally[opt] = tally.get(opt, 0) + 1
    return tally, ballots


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("vote_yes "):
        vote_id = text.split(" ", 1)[1].strip()
        ballots = _register_vote(vote_id, sender, "yes")
        tally, _ = _get_tally(vote_id)
        send(sender, f"vote recorded: YES for vote '{vote_id}'. Current tally: {tally}")

    elif text.startswith("vote_no "):
        vote_id = text.split(" ", 1)[1].strip()
        ballots = _register_vote(vote_id, sender, "no")
        tally, _ = _get_tally(vote_id)
        send(sender, f"vote recorded: NO for vote '{vote_id}'. Current tally: {tally}")

    elif text.startswith("vote ") and not text.startswith("vote_"):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: vote <vote_id> <option>")
            return
        vote_id, option = parts[1], parts[2]
        ballots = _register_vote(vote_id, sender, option)
        tally, _ = _get_tally(vote_id)
        send(sender, f"vote recorded: '{option}' for vote '{vote_id}'. Current tally: {tally}")

    elif text.startswith("change_vote "):
        parts = text.split()
        if len(parts) < 3:
            send(sender, "usage: change_vote <vote_id> <new_option>")
            return
        vote_id, new_option = parts[1], parts[2]

        votes = _load_votes()
        if vote_id not in votes:
            send(sender, f"no vote found for id '{vote_id}'")
            return

        old_option = votes[vote_id].get(sender, None)
        ballots = _register_vote(vote_id, sender, new_option)
        tally, _ = _get_tally(vote_id)
        send(sender, f"vote changed from '{old_option}' to '{new_option}' for vote '{vote_id}'. New tally: {tally}")


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
            time.sleep(30)
        except Exception as e:
            print(f"[{AGENT_ID}] error: {e}")


if __name__ == "__main__":
    main()
