#!/usr/bin/env python3
"""Agent 058 — Vote Tallier
Role: Tallies votes and determines outcomes.
Listens for: tally <vote_id>, final_tally <vote_id>, vote_history
Emits: tally reports, vote results
"""
import os, sys, json, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_058_vote_tallier"
AGENT_NAME = "Agent 058 — Vote Tallier"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

INBOX_DIR = os.path.expanduser("~/.agent-mesh-inbox")
VOTES_FILE = os.path.join(INBOX_DIR, "votes.json")

# vote_id -> {"closed": bool, "winner": str, "final_tally": dict}
_closed_votes = []


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


def _tally(vote_id, ballots_dict):
    tally = {}
    for instance_id, option in ballots_dict.items():
        tally[option] = tally.get(option, 0) + 1
    winner = max(tally, key=lambda k: tally[k]) if tally else None
    return tally, winner


def run_cycle():
    status_data = api("/api/status")
    if not isinstance(status_data, dict):
        return

    votes_data = status_data.get("votes", [])
    instances = status_data.get("instances", [])
    online_count = sum(1 for i in instances if i.get("online"))
    quorum = max(1, online_count // 2 + 1)

    local_votes = _load_votes()

    for vote in votes_data:
        vid = vote.get("id", "")
        if not vid:
            continue
        if any(cv.get("vote_id") == vid for cv in _closed_votes):
            continue  # already closed

        # Combine broker ballots with local votes
        broker_ballots = {b.get("by", ""): b.get("option", "") for b in vote.get("ballots", [])}
        local_ballots = local_votes.get(vid, {})
        combined = {**broker_ballots, **local_ballots}

        if len(combined) >= quorum:
            tally, winner = _tally(vid, combined)
            import datetime
            _closed_votes.append({
                "vote_id": vid,
                "question": vote.get("question", "?"),
                "winner": winner,
                "tally": tally,
                "total_votes": len(combined),
                "closed_at": datetime.datetime.utcnow().isoformat() + "Z",
            })
            broadcast(
                f"[vote_tallier] VOTE CLOSED: '{vote.get('question','?')}' (id={vid}) | "
                f"Winner: '{winner}' | Tally: {tally} | {len(combined)} votes cast"
            )

    active = len(votes_data) - len(_closed_votes)
    print(f"[{AGENT_ID}] {active} active votes, quorum={quorum}, {len(_closed_votes)} closed")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    to = msg.get("to", "")
    if to not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text.startswith("tally "):
        vote_id = text.split(" ", 1)[1].strip()
        # Get from broker
        status_data = api("/api/status")
        votes_data = status_data.get("votes", []) if isinstance(status_data, dict) else []
        vote = next((v for v in votes_data if v.get("id") == vote_id), None)

        local_votes = _load_votes()
        local_ballots = local_votes.get(vote_id, {})

        broker_ballots = {}
        if vote:
            broker_ballots = {b.get("by", ""): b.get("option", "") for b in vote.get("ballots", [])}

        combined = {**broker_ballots, **local_ballots}
        if not combined:
            send(sender, f"no votes found for vote '{vote_id}'")
            return

        tally, winner = _tally(vote_id, combined)
        send(sender, json.dumps({
            "vote_id": vote_id,
            "question": vote.get("question", "?") if vote else "?",
            "tally": tally,
            "leading": winner,
            "total_votes": len(combined),
            "voters": combined,
        }))

    elif text.startswith("final_tally "):
        vote_id = text.split(" ", 1)[1].strip()
        status_data = api("/api/status")
        votes_data = status_data.get("votes", []) if isinstance(status_data, dict) else []
        vote = next((v for v in votes_data if v.get("id") == vote_id), None)

        local_votes = _load_votes()
        local_ballots = local_votes.get(vote_id, {})
        broker_ballots = {}
        if vote:
            broker_ballots = {b.get("by", ""): b.get("option", "") for b in vote.get("ballots", [])}

        combined = {**broker_ballots, **local_ballots}
        tally, winner = _tally(vote_id, combined)
        import datetime
        result = {
            "vote_id": vote_id,
            "question": vote.get("question", "?") if vote else "?",
            "final_tally": tally,
            "winner": winner,
            "total_votes": len(combined),
            "closed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        _closed_votes.append(result)
        broadcast(f"[vote_tallier] FINAL TALLY: vote '{vote_id}' | Winner: '{winner}' | Tally: {tally}")
        send(sender, json.dumps(result))

    elif text == "vote_history":
        recent = _closed_votes[-10:]
        if not recent:
            send(sender, "no vote history yet")
            return
        lines = ["Recent votes:"]
        for cv in reversed(recent):
            lines.append(f"  [{cv['vote_id']}] '{cv.get('question','?')}' -> winner: {cv.get('winner','?')} | {cv.get('tally',{})}")
        send(sender, "\n".join(lines))


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
        time.sleep(30)


if __name__ == "__main__":
    main()
