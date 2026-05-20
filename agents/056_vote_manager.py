#!/usr/bin/env python3
"""Agent 056 — Vote Manager
Role: Creates and manages voting sessions.
Listens for: vote <question> <opt1> <opt2> [opt3...], quick_vote <yes/no question>, active_votes
Emits: vote open announcements, vote results
"""
import os, sys, json, time
import requests
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_056_vote_manager"
AGENT_NAME = "Agent 056 — Vote Manager"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

# Local vote tracking: vote_id -> {question, options, created_at, closed, winner}
_votes = {}


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


def _create_vote(question, options):
    result = api("/api/vote", "POST", {
        "question": question,
        "options": options,
        "room": ROOM,
        "created_by": AGENT_ID,
    })
    vote_id = result.get("vote_id") or result.get("id", "")
    if not vote_id:
        # Fallback: generate local ID
        import uuid
        vote_id = str(uuid.uuid4())[:8]

    _votes[vote_id] = {
        "question": question,
        "options": options,
        "created_at": time.time(),
        "closed": False,
        "winner": None,
    }
    return vote_id


def _announce_vote(vote_id, question, options):
    opts_str = " | ".join(f"({i+1}) {o}" for i, o in enumerate(options))
    broadcast(
        f"[VOTE OPEN] id={vote_id} | {question} | Options: {opts_str} | "
        f"Vote by sending: vote_yes {vote_id} / vote_no {vote_id} / vote {vote_id} <option>"
    )


def run_cycle():
    # Check broker for resolved votes
    status_data = api("/api/status")
    votes_data = status_data.get("votes", []) if isinstance(status_data, dict) else []
    instances = status_data.get("instances", []) if isinstance(status_data, dict) else []
    online_count = sum(1 for i in instances if i.get("online"))

    for vote in votes_data:
        vid = vote.get("id", "")
        if not vid or _votes.get(vid, {}).get("closed"):
            continue

        ballots = vote.get("ballots", [])
        options = vote.get("options", [])
        quorum = max(1, online_count // 2 + 1)

        if len(ballots) >= quorum:
            # Tally and announce winner
            tally = {}
            for b in ballots:
                opt = b.get("option", "")
                tally[opt] = tally.get(opt, 0) + 1

            if tally:
                winner = max(tally, key=lambda k: tally[k])
                if vid in _votes:
                    _votes[vid]["closed"] = True
                    _votes[vid]["winner"] = winner
                broadcast(
                    f"[VOTE CLOSED] id={vid} | Winner: '{winner}' ({tally[winner]}/{len(ballots)} votes) | Full tally: {tally}"
                )

    active = sum(1 for v in _votes.values() if not v.get("closed"))
    print(f"[{AGENT_ID}] {active} active votes, {online_count} online")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("vote ") and not text.startswith("vote_"):
        # vote <question> <opt1> <opt2> [opt3...]
        parts = text.split()
        if len(parts) < 4:
            send(sender, "usage: vote <question> <option1> <option2> [option3...]")
            return
        question = parts[1]
        options = parts[2:]
        vote_id = _create_vote(question, options)
        _announce_vote(vote_id, question, options)
        send(sender, f"vote created: id={vote_id}")

    elif text.startswith("quick_vote "):
        question = text[len("quick_vote "):].strip()
        vote_id = _create_vote(question, ["yes", "no"])
        _announce_vote(vote_id, question, ["yes", "no"])
        send(sender, f"quick vote created: id={vote_id}")

    elif text == "active_votes":
        active = {vid: v for vid, v in _votes.items() if not v.get("closed")}
        if not active:
            send(sender, "no active votes")
            return

        # Get tallies from broker
        status_data = api("/api/status")
        broker_votes = {v.get("id"): v for v in status_data.get("votes", [])} if isinstance(status_data, dict) else {}

        lines = []
        for vid, v in active.items():
            bv = broker_votes.get(vid, {})
            ballots = bv.get("ballots", [])
            tally = {}
            for b in ballots:
                opt = b.get("option", "")
                tally[opt] = tally.get(opt, 0) + 1
            lines.append(f"  [{vid}] {v['question']} | tally: {tally}")

        send(sender, "Active votes:\n" + "\n".join(lines))


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
        time.sleep(60)


if __name__ == "__main__":
    main()
