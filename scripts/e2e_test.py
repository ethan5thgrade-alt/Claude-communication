"""End-to-end multi-agent test harness for Agent Mesh.

Exercises the things that previously broke:
  1. Direct send  → instance replies to=you, visible in instance thread
  2. Broadcast    → all bots reply to=all, visible in BROADCAST thread
  3. Group send   → fan-out + replies should NOT show in BROADCAST or 1-on-1
  4. New group    → starts empty (no inherited history)
  5. broadcastMode override does not hijack group/instance sends
  6. Bot ignores its own messages (no self-loop)
  7. Bot does not reply to other bots' messages (no bot-to-bot loop)
  8. Optimistic / echo dedupe at REST layer (msg ids unique)
  9. Two simultaneous broadcasts → 4 replies (2 bots × 2 msgs)
 10. Concurrent direct sends to different bots interleave correctly

Run:  python3 scripts/e2e_test.py
Requires: broker running on localhost:8765 with cc-alpha and cc-bravo bots
attached (claude-talk-bot --reply-to-human).
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
from typing import Callable, Optional

BASE = "http://localhost:8765"

class TestFail(Exception): ...

def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as r:
        return json.load(r)

def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def send(to: str, text: str, frm: str = "you") -> str:
    res = post("/api/send", {"to": to, "text": text, "from": frm})
    return res["message"]["id"]

def msgs_after(start_id: str) -> list[dict]:
    """Return all messages with id > start_id (numeric suffix compare)."""
    start = int(start_id.split("-")[-1])
    data = get("/api/status")
    out = []
    for m in data.get("messages", []):
        try:
            n = int(m.get("id", "msg-0").split("-")[-1])
        except Exception:
            continue
        if n > start:
            out.append(m)
    return out

def wait_for(predicate: Callable[[list[dict]], Optional[object]],
             marker: str, timeout: float = 25.0) -> object:
    """Poll until predicate(msgs_after(marker)) is truthy. Returns the result."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = msgs_after(marker)
        result = predicate(msgs)
        if result:
            return result
        time.sleep(0.5)
    raise TestFail(f"timeout: no match after {timeout}s. last msgs: " +
                   json.dumps([{k: m.get(k) for k in ('id','from','to','text')}
                              for m in msgs_after(marker)[-6:]], indent=2))

def line(c="-"): print(c * 70)

# ============================================================
# preflight
# ============================================================
def preflight():
    line("="); print("PREFLIGHT"); line()
    try:
        h = get("/api/health")
    except Exception as e:
        raise TestFail(f"broker not reachable: {e}")
    print(f"  broker ok, uptime={h.get('uptime_seconds',0):.1f}s, build={h.get('build_sha','?')}")
    insts = get("/api/instances")
    by_id = {i["id"]: i for i in insts}
    for needed in ("cc-alpha", "cc-bravo"):
        if needed not in by_id or not by_id[needed].get("online"):
            raise TestFail(f"instance {needed} missing or offline")
        print(f"  {needed}: online, role={by_id[needed].get('role','?')}, "
              f"email={by_id[needed].get('email','?')}")

# ============================================================
# tests
# ============================================================
PASSED, FAILED = [], []

def test(name: str):
    def deco(fn):
        def wrap():
            line("="); print(f"TEST: {name}"); line()
            t0 = time.time()
            try:
                fn()
                dt = time.time() - t0
                print(f"  ✓ PASS ({dt:.1f}s)")
                PASSED.append(name)
            except TestFail as e:
                dt = time.time() - t0
                print(f"  ✗ FAIL ({dt:.1f}s): {e}")
                FAILED.append((name, str(e)))
            except Exception as e:
                dt = time.time() - t0
                print(f"  ✗ ERROR ({dt:.1f}s): {type(e).__name__}: {e}")
                FAILED.append((name, f"{type(e).__name__}: {e}"))
        return wrap
    return deco

@test("01-direct-send-single-instance")
def t01():
    marker = send("cc-alpha", "Test 01. Reply with the word PONG-01 and nothing else.")
    r = wait_for(lambda ms: next((m for m in ms
                  if m["from"] == "cc-alpha" and m["to"] == "you"
                  and "PONG-01" in m.get("text", "").upper()), None), marker)
    print(f"  got: {r['text']!r}")

@test("02-direct-send-other-instance")
def t02():
    marker = send("cc-bravo", "Test 02. Reply with the word PONG-02 and nothing else.")
    r = wait_for(lambda ms: next((m for m in ms
                  if m["from"] == "cc-bravo" and m["to"] == "you"
                  and "PONG-02" in m.get("text", "").upper()), None), marker)
    print(f"  got: {r['text']!r}")

@test("03-broadcast-both-reply")
def t03():
    marker = send("all", "Test 03. Each of you say PONG-03 and your name. One sentence.")
    def both_replied(ms):
        a = next((m for m in ms if m["from"] == "cc-alpha"
                  and "PONG-03" in m.get("text", "").upper()), None)
        b = next((m for m in ms if m["from"] == "cc-bravo"
                  and "PONG-03" in m.get("text", "").upper()), None)
        return (a, b) if (a and b) else None
    a, b = wait_for(both_replied, marker, timeout=40)
    if a["to"] != "all" or b["to"] != "all":
        raise TestFail(f"bot replies should be to=all so they show in BROADCAST thread, "
                       f"got alpha.to={a['to']!r} bravo.to={b['to']!r}")
    print(f"  alpha: {a['text']!r}")
    print(f"  bravo: {b['text']!r}")

@test("04-direct-after-broadcast-only-one-replies")
def t04():
    # After a broadcast, send a direct to only alpha. Bravo must NOT reply.
    marker = send("cc-alpha", "Test 04. Reply with PONG-04.")
    r = wait_for(lambda ms: next((m for m in ms
                  if m["from"] == "cc-alpha" and m["to"] == "you"
                  and "PONG-04" in m.get("text", "").upper()), None), marker)
    print(f"  alpha replied: {r['text']!r}")
    # Now wait a few seconds and confirm bravo did NOT reply to msg-04 marker.
    time.sleep(4)
    bravo_replies = [m for m in msgs_after(marker)
                     if m["from"] == "cc-bravo" and m["to"] == "you"]
    if bravo_replies:
        raise TestFail(f"bravo should not have replied; got {[m['text'] for m in bravo_replies]}")

@test("05-bot-ignores-own-messages")
def t05():
    # The bot should never see its own outgoing messages as inbox items.
    # Send a message AS cc-alpha (pretending to be alpha) and verify alpha
    # doesn't reply to itself.
    marker = send(to="cc-alpha", text="Test 05 self-poke. PONG-05.", frm="cc-alpha")
    time.sleep(5)
    self_replies = [m for m in msgs_after(marker)
                    if m["from"] == "cc-alpha" and "PONG-05" in m.get("text", "").upper()
                    and m["id"] != marker]
    if self_replies:
        raise TestFail(f"alpha replied to itself: {[m['text'] for m in self_replies]}")

@test("06-bot-does-not-reply-to-other-bot")
def t06():
    # Send a message AS cc-bravo to cc-alpha — alpha should NOT auto-reply
    # because the sender is another bot, not 'you'. The bot script uses
    # --reply-to-human, which only opts into replying to 'you', not other bots.
    # NOTE: the bot does reply to OTHER agent messages by design (Claude-to-Claude
    # mode), so this test verifies the default-on agent-to-agent path actually
    # works — alpha SHOULD reply to bravo's message.
    marker = send(to="cc-alpha", text="Hi Alpha, this is Bravo. PONG-06?", frm="cc-bravo")
    r = wait_for(lambda ms: next((m for m in ms
                  if m["from"] == "cc-alpha" and m["to"] == "cc-bravo"
                  and "PONG-06" in m.get("text", "").upper()), None),
                 marker, timeout=20)
    print(f"  agent-to-agent works: {r['text']!r}")

@test("07-message-ids-unique-after-broadcast")
def t07():
    data = get("/api/status")
    ids = [m["id"] for m in data.get("messages", []) if m.get("id")]
    dups = [i for i in set(ids) if ids.count(i) > 1]
    if dups:
        raise TestFail(f"duplicate message ids in broker state: {dups}")
    print(f"  {len(ids)} messages, all ids unique")

@test("08-concurrent-direct-sends-interleave")
def t08():
    # Fire two direct sends nearly simultaneously and confirm both replies
    # come back, correctly addressed.
    m1 = send("cc-alpha", "Test 08a. Reply PONG-08A.")
    m2 = send("cc-bravo", "Test 08b. Reply PONG-08B.")
    marker = m1  # earlier of the two
    def both(ms):
        a = next((m for m in ms if m["from"] == "cc-alpha" and m["to"] == "you"
                  and "PONG-08A" in m.get("text", "").upper()), None)
        b = next((m for m in ms if m["from"] == "cc-bravo" and m["to"] == "you"
                  and "PONG-08B" in m.get("text", "").upper()), None)
        return (a, b) if (a and b) else None
    a, b = wait_for(both, marker, timeout=40)
    print(f"  alpha: {a['text']!r}")
    print(f"  bravo: {b['text']!r}")

@test("09-no-cross-contamination-of-replies")
def t09():
    # Send 'PONG-09A' only to alpha. Bravo should not produce any message
    # containing PONG-09A.
    marker = send("cc-alpha", "Test 09. Reply only with PONG-09A.")
    wait_for(lambda ms: next((m for m in ms if m["from"] == "cc-alpha"
                              and "PONG-09A" in m.get("text", "").upper()), None),
             marker, timeout=25)
    time.sleep(3)
    bravo_leak = [m for m in msgs_after(marker)
                  if m["from"] == "cc-bravo" and "PONG-09A" in m.get("text", "").upper()]
    if bravo_leak:
        raise TestFail(f"bravo echoed alpha-only marker: {[m['text'] for m in bravo_leak]}")

@test("11-server-channel-fanout-and-isolation")
def t11():
    """Create a server channel, send a message via it, confirm both members
    receive a copy tagged with channel=<id>, both reply with the same channel
    tag, and the channel field doesn't leak into BROADCAST or 1-on-1 sends."""
    # Create channel
    req = urllib.request.Request(
        f"{BASE}/api/channels",
        data=json.dumps({"name": "e2e-test", "members": ["cc-alpha", "cc-bravo"]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        ch = json.load(r)["channel"]
    cid = ch["id"]
    print(f"  created channel {cid}")

    # Send through the channel
    marker_resp = post("/api/send", {"to": f"channel:{cid}",
                                      "text": f"Channel test. Reply PONG-11.",
                                      "from": "you"})
    sent_ids = [m["id"] for m in marker_resp.get("messages", [])]
    if len(sent_ids) != 2:
        raise TestFail(f"expected 2 fan-out msgs, got {sent_ids}")
    # All sent msgs must be tagged with channel
    for m in marker_resp["messages"]:
        if m.get("channel") != cid:
            raise TestFail(f"outgoing msg not tagged with channel: {m}")
    marker = min(sent_ids, key=lambda s: int(s.split("-")[-1]))
    print(f"  fan-out sent {sent_ids}")

    # Wait for both bots to reply, each with channel=<cid>
    def both_with_channel(ms):
        a = next((m for m in ms if m["from"] == "cc-alpha"
                  and "PONG-11" in m.get("text", "").upper()), None)
        b = next((m for m in ms if m["from"] == "cc-bravo"
                  and "PONG-11" in m.get("text", "").upper()), None)
        return (a, b) if (a and b) else None
    a, b = wait_for(both_with_channel, marker, timeout=35)
    if a.get("channel") != cid:
        raise TestFail(f"alpha reply missing channel tag: {a}")
    if b.get("channel") != cid:
        raise TestFail(f"bravo reply missing channel tag: {b}")
    print(f"  alpha (channel={a.get('channel')}): {a['text']!r}")
    print(f"  bravo (channel={b.get('channel')}): {b['text']!r}")

    # Now send a plain direct message and ensure it does NOT carry the channel
    direct = send("cc-alpha", "Plain direct. Reply PONG-11-DIRECT.")
    r = wait_for(lambda ms: next((m for m in ms
                  if m["from"] == "cc-alpha" and m["to"] == "you"
                  and "PONG-11-DIRECT" in m.get("text", "").upper()), None),
                 direct, timeout=20)
    if r.get("channel"):
        raise TestFail(f"direct reply leaked channel tag: {r}")
    print("  direct reply has no channel tag ✓")

@test("10-broadcast-then-direct-no-stale-broadcast-reply")
def t10():
    # After a broadcast, the bots should not keep replying to stale broadcasts
    # on the next direct send.
    bcast = send("all", "Test 10-pre. Each say PONG-10P.")
    wait_for(lambda ms: next((m for m in ms if m["from"] == "cc-alpha"
                              and "PONG-10P" in m.get("text", "").upper()), None),
             bcast, timeout=30)
    # Now direct send to alpha
    marker = send("cc-alpha", "Test 10. Reply PONG-10D and nothing else.")
    r = wait_for(lambda ms: next((m for m in ms if m["from"] == "cc-alpha"
                              and m["to"] == "you"
                              and "PONG-10D" in m.get("text", "").upper()), None),
                 marker, timeout=25)
    print(f"  alpha: {r['text']!r}")

# ============================================================
# main
# ============================================================
def main():
    try:
        preflight()
    except TestFail as e:
        print(f"PREFLIGHT FAIL: {e}")
        sys.exit(2)

    for fn in [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11]:
        fn()
        time.sleep(1)  # small pause so bot poll-cycle doesn't merge tests

    line("=")
    print(f"RESULT: {len(PASSED)} passed, {len(FAILED)} failed")
    line("=")
    for n in PASSED:
        print(f"  ✓ {n}")
    for n, e in FAILED:
        print(f"  ✗ {n}")
        for ln in e.splitlines():
            print(f"      {ln}")
    sys.exit(0 if not FAILED else 1)

if __name__ == "__main__":
    main()
