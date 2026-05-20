"""Demo workflow — exercises every persistent primitive via REST.

Run against a live broker on localhost:8765:

    python3 examples/demo_workflow.py

After this script completes, the dashboard's TASKS / MEMORY / FLOWS / CONTROL
tabs will all show real entries instead of being empty. Useful for proving
the full surface works end-to-end without needing a Claude Code session.

No LLM cost: this script only POSTs to the broker. It does NOT trigger bots.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("MESH_BASE", "http://localhost:8765")
TOKEN = os.environ.get("MESH_TOKEN", "")


def _hdr() -> dict:
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["X-Mesh-Token"] = TOKEN
    return h


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), headers=_hdr())
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e), "body": e.read().decode("utf-8", "replace")}


def delete(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", headers=_hdr(), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e)}


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    section("1. Memory: write a shared contract")
    mem = post("/api/memory", {
        "key": "DEMO_SSE_FORMAT",
        "value": '{"pct": float, "ticker": string}',
        "mem_type": "contract",
    })
    print(json.dumps(mem, indent=2))

    section("2. Task: create one for cc-alpha")
    task = post("/api/task", {
        "title": "Write CSV parser per DEMO_SSE_FORMAT",
        "assignee": "cc-alpha",
        "priority": "high",
    })
    print(json.dumps(task, indent=2))

    section("3. Approval: request and respond")
    ap = post("/api/approval", {
        "from": "cc-alpha",
        "action": "DROP TABLE staging_old",
        "risk": "high",
        "detail": "abandoned table, 0 reads in 30 days",
    })
    print("created:", json.dumps(ap, indent=2))
    ap_id = ap.get("approval", {}).get("id")
    if ap_id:
        resp = post(f"/api/approval/{ap_id}/respond", {"approved": True})
        print("decided:", json.dumps(resp, indent=2))

    section("4. Vote: 3-way choice")
    vote = post("/api/vote", {
        "question": "Which deploy strategy?",
        "options": ["blue-green", "canary", "rolling"],
        "from": "you",
    })
    print("opened:", json.dumps(vote, indent=2))
    vote_id = vote.get("vote", {}).get("id")
    if vote_id:
        post(f"/api/vote/{vote_id}/cast",
             {"voter": "cc-alpha", "option": "canary"})
        cast = post(f"/api/vote/{vote_id}/cast",
                    {"voter": "cc-bravo", "option": "canary"})
        print("after 2 casts:", json.dumps(cast, indent=2))

    section("5. Flow: create, fire, delete")
    flow = post("/api/flow", {
        "name": "demo-on-message",
        "trigger": "message:*",
        "action": "log to audit",
        "color": "#ff6",
    })
    print("created:", json.dumps(flow, indent=2))
    fid = flow.get("flow", {}).get("id")
    if fid:
        fire = post(f"/api/flow/{fid}/fire", {})
        print("fired:", json.dumps(fire, indent=2))
        rm = delete(f"/api/flow/{fid}")
        print("deleted:", json.dumps(rm, indent=2))

    section("Done — open the dashboard to see populated tabs")
    print(f"  {BASE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
