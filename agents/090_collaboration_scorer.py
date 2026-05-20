#!/usr/bin/env python3
"""Agent 090 — Collaboration Scorer
Role: Measures and scores how well Claude instances are collaborating.
"""
import os, sys, json, time, requests, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BROKER = os.environ.get("BROKER_URL_HTTP", "http://localhost:8765")
AGENT_ID = "agent_090_collaboration_scorer"
AGENT_NAME = "Agent 090 — Collaboration Scorer"
ROOM = os.environ.get("MESH_ROOM", "system")
TOKEN = os.environ.get("MESH_TOKEN", "")
HEADERS = {"X-Mesh-Token": TOKEN} if TOKEN else {}

LOG_PATH = os.path.expanduser("~/Claude-communication/logs/collab_score.jsonl")


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


def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def _calc_score(messages, tasks, memories):
    """Calculate collaboration score 0-100 with breakdown."""
    if not messages:
        return {"total": 0, "reciprocity": 0, "task_sharing": 0,
                "memory_contribution": 0, "conflict_rate": 0}

    # Reciprocity: measure A->B and B->A pairs
    pair_counts = {}
    for m in messages:
        frm = m.get("from", "")
        to = m.get("to", "")
        if frm and to and to not in ("all", ""):
            key = frozenset([frm, to])
            pair_counts[key] = pair_counts.get(key, 0) + 1
    reciprocal_pairs = sum(1 for k, v in pair_counts.items() if v >= 2)
    total_pairs = max(len(pair_counts), 1)
    reciprocity_score = min(100, int(reciprocal_pairs / total_pairs * 100))

    # Task sharing: tasks with different creators and assignees
    shared_tasks = [t for t in tasks if t.get("created_by") != t.get("assignee")
                    and t.get("assignee")]
    task_sharing_score = min(100, len(shared_tasks) * 10)

    # Memory contribution: unique contributors to memory
    contributors = {m.get("by") for m in memories if m.get("by")}
    memory_score = min(100, len(contributors) * 20)

    # Conflict rate: scan messages for conflict indicators
    conflict_msgs = [m for m in messages if "conflict" in m.get("text", "").lower()
                     or "collision" in m.get("text", "").lower()]
    conflict_rate = max(0, 100 - len(conflict_msgs) * 10)

    total = int((reciprocity_score + task_sharing_score + memory_score + conflict_rate) / 4)
    return {
        "total": total,
        "reciprocity": reciprocity_score,
        "task_sharing": task_sharing_score,
        "memory_contribution": memory_score,
        "conflict_rate": conflict_rate,
    }


def run_cycle():
    _ensure_log_dir()
    data = api("/api/status")
    messages = data.get("messages", [])
    tasks = api("/api/tasks").get("tasks", [])
    memories = api("/api/memory").get("memory", [])

    score = _calc_score(messages, tasks, memories)
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "score": score,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    broadcast(f"[COLLAB SCORE] Overall: {score['total']}/100 | "
              f"Reciprocity: {score['reciprocity']} | "
              f"Task sharing: {score['task_sharing']} | "
              f"Memory: {score['memory_contribution']} | "
              f"Conflict: {score['conflict_rate']}")
    print(f"[{AGENT_ID}] collab score: {score['total']}")


def handle_message(msg):
    if msg.get("type") != "message":
        return
    if msg.get("to") not in (AGENT_ID, "all"):
        return
    text = msg.get("text", "").strip()
    sender = msg.get("from", "unknown")

    if text == "collab_score":
        data = api("/api/status")
        messages = data.get("messages", [])
        tasks = api("/api/tasks").get("tasks", [])
        memories = api("/api/memory").get("memory", [])
        score = _calc_score(messages, tasks, memories)
        send(sender, f"Collaboration Score: {score['total']}/100\n"
                     f"  Reciprocity:         {score['reciprocity']}/100\n"
                     f"  Task Sharing:        {score['task_sharing']}/100\n"
                     f"  Memory Contribution: {score['memory_contribution']}/100\n"
                     f"  Conflict Rate:       {score['conflict_rate']}/100")

    elif text == "collab_report":
        _ensure_log_dir()
        try:
            with open(LOG_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            send(sender, "No collaboration history logged yet.")
            return
        entries = [json.loads(l) for l in lines[-10:] if l.strip()]
        if not entries:
            send(sender, "No collaboration history logged yet.")
            return
        report_lines = [f"Collaboration Analytics (last {len(entries)} samples):"]
        for e in entries:
            ts = e.get("ts", "")[:19]
            s = e.get("score", {})
            report_lines.append(f"  [{ts}] total={s.get('total')} "
                                 f"recip={s.get('reciprocity')} "
                                 f"tasks={s.get('task_sharing')} "
                                 f"mem={s.get('memory_contribution')}")
        send(sender, "\n".join(report_lines))

    elif text == "collab_tips":
        data = api("/api/status")
        messages = data.get("messages", [])
        tasks = api("/api/tasks").get("tasks", [])
        memories = api("/api/memory").get("memory", [])
        score = _calc_score(messages, tasks, memories)
        tips = ["Collaboration Tips:"]
        if score["reciprocity"] < 50:
            tips.append("  - Improve reciprocity: instances should reply to each other more often.")
        if score["task_sharing"] < 50:
            tips.append("  - Improve task sharing: assign tasks across different instances.")
        if score["memory_contribution"] < 50:
            tips.append("  - More instances should write to shared memory (context/learned).")
        if score["conflict_rate"] < 70:
            tips.append("  - Reduce conflicts: use handoffs and specialization to avoid overlap.")
        if len(tips) == 1:
            tips.append("  - Collaboration looks good! Keep it up.")
        send(sender, "\n".join(tips))


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
            print(f"[{AGENT_ID}] error: {e}")
        time.sleep(3600)


if __name__ == "__main__":
    main()
