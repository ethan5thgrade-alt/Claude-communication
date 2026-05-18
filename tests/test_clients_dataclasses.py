"""Unit tests for the typed event dataclasses in connect.py (roadmap item 94).

These exercise the from_payload() classmethods and the parse_event() dispatcher
without spinning up a broker. We import connect via importlib with a stub for
the `websockets` module so the import doesn't require the dep — but the
in-repo websockets is already installed for the other test modules, so a plain
import works. We do, however, want to avoid the module's side-effect of
spawning the background loop on import; the daemon thread is harmless, but
we'd rather not have it racing against the test. The thread will idle reconnect
against ws://localhost:8766 in the background; since that port isn't bound in
this test process the connect attempt will just keep failing — fine for our
pure-data tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import connect  # noqa: E402


def test_message_event_from_payload_maps_from_keyword():
    p = {
        "type": "message",
        "from": "cc2",
        "to": "cc1",
        "text": "hi there",
        "ts": "2026-05-18T00:00:00Z",
        "id": "m_001",
    }
    ev = connect.MessageEvent.from_payload(p)
    assert isinstance(ev, connect.MessageEvent)
    assert ev.from_ == "cc2"
    assert ev.to == "cc1"
    assert ev.text == "hi there"
    assert ev.ts == "2026-05-18T00:00:00Z"
    assert ev.id == "m_001"


def test_message_event_handles_missing_fields():
    ev = connect.MessageEvent.from_payload({"type": "message"})
    assert ev.from_ == ""
    assert ev.to == ""
    assert ev.text == ""
    assert ev.ts == ""
    assert ev.id == ""


def test_task_assigned_event_from_payload():
    p = {
        "type": "task_assigned",
        "task": {"id": "T001", "title": "Write parser", "created_by": "cc1"},
        "ts": "2026-05-18T00:00:01Z",
    }
    ev = connect.TaskAssignedEvent.from_payload(p)
    assert isinstance(ev, connect.TaskAssignedEvent)
    assert ev.task["id"] == "T001"
    assert ev.task["title"] == "Write parser"
    assert ev.ts == "2026-05-18T00:00:01Z"


def test_task_assigned_defaults_empty_task():
    ev = connect.TaskAssignedEvent.from_payload({"type": "task_assigned"})
    assert ev.task == {}
    assert ev.ts == ""


def test_task_completed_event_from_payload():
    p = {
        "type": "task_completed",
        "task": {"id": "T002", "done_by": "cc2", "result": "merged"},
        "ts": "2026-05-18T00:00:02Z",
    }
    ev = connect.TaskCompletedEvent.from_payload(p)
    assert isinstance(ev, connect.TaskCompletedEvent)
    assert ev.task["done_by"] == "cc2"
    assert ev.task["result"] == "merged"
    assert ev.ts == "2026-05-18T00:00:02Z"


def test_memory_event_wrapped_under_memory_key():
    p = {
        "type": "memory_write",
        "memory": {
            "id": "mem_1",
            "key": "SSE_FORMAT",
            "value": {"pct": "float", "ticker": "str"},
            "type": "contract",
            "by": "cc1",
            "ts": "2026-05-18T00:00:03Z",
        },
    }
    ev = connect.MemoryEvent.from_payload(p)
    assert isinstance(ev, connect.MemoryEvent)
    assert ev.id == "mem_1"
    assert ev.key == "SSE_FORMAT"
    assert ev.value == {"pct": "float", "ticker": "str"}
    assert ev.type == "contract"
    assert ev.by == "cc1"
    assert ev.ts == "2026-05-18T00:00:03Z"


def test_memory_event_flat_payload_fallback():
    p = {
        "type": "memory_write",
        "id": "mem_2",
        "key": "flag",
        "value": True,
        "type": "config",
        "by": "cc2",
        "ts": "2026-05-18T00:00:04Z",
    }
    ev = connect.MemoryEvent.from_payload(p)
    assert ev.key == "flag"
    assert ev.value is True
    assert ev.by == "cc2"


def test_memory_event_value_supports_any_type():
    # value: Any — confirm list/dict/None/scalar all flow through unchanged
    for v in [42, "str", [1, 2, 3], {"k": "v"}, None, 3.14, True]:
        ev = connect.MemoryEvent.from_payload(
            {"type": "memory_write", "memory": {"key": "k", "value": v}}
        )
        assert ev.value == v


def test_approval_decision_event_approved():
    p = {
        "type": "approval_decision",
        "id": "ap_42",
        "decision": True,
        "action": "Drop prod table",
    }
    ev = connect.ApprovalDecisionEvent.from_payload(p)
    assert isinstance(ev, connect.ApprovalDecisionEvent)
    assert ev.id == "ap_42"
    assert ev.decision is True
    assert ev.action == "Drop prod table"


def test_approval_decision_event_rejected_coerces_bool():
    ev = connect.ApprovalDecisionEvent.from_payload(
        {"type": "approval_decision", "id": "ap_7", "decision": 0, "action": "X"}
    )
    assert ev.decision is False


def test_vote_resolved_event_from_payload():
    p = {
        "type": "vote_resolved",
        "vote_id": "v_abc",
        "winner": "yes",
        "vote": {"id": "v_abc", "question": "Ship M5?", "options": ["yes", "no"]},
    }
    ev = connect.VoteResolvedEvent.from_payload(p)
    assert isinstance(ev, connect.VoteResolvedEvent)
    assert ev.vote_id == "v_abc"
    assert ev.winner == "yes"
    assert ev.vote["question"] == "Ship M5?"


def test_vote_resolved_defaults_empty_vote():
    ev = connect.VoteResolvedEvent.from_payload(
        {"type": "vote_resolved", "vote_id": "v_x", "winner": "no"}
    )
    assert ev.vote == {}


def test_plugin_invoke_result_event_from_payload():
    p = {
        "type": "plugin_invoke_result",
        "request_id": "req_1",
        "plugin": "apple-hig-expert",
        "tool": "apple-hig-expert",
        "kind": "skill",
        "status": "discovered",
        "path": "/Users/x/.claude/plugins/cache/m/apple-hig-expert/1.0/skills/apple-hig-expert",
        "manifest": {"name": "apple-hig-expert", "version": "1.0"},
    }
    ev = connect.PluginInvokeResultEvent.from_payload(p)
    assert isinstance(ev, connect.PluginInvokeResultEvent)
    assert ev.request_id == "req_1"
    assert ev.plugin == "apple-hig-expert"
    assert ev.tool == "apple-hig-expert"
    assert ev.kind == "skill"
    assert ev.status == "discovered"
    assert ev.path.endswith("apple-hig-expert")
    assert ev.manifest["version"] == "1.0"


def test_plugin_invoke_result_event_not_found_minimal():
    ev = connect.PluginInvokeResultEvent.from_payload(
        {
            "type": "plugin_invoke_result",
            "plugin": "missing",
            "tool": "missing",
            "status": "not_found",
        }
    )
    assert ev.status == "not_found"
    assert ev.path == ""
    assert ev.manifest == {}


# --------------------- parse_event dispatcher ---------------------------


def test_parse_event_dispatches_message():
    ev = connect.parse_event({"type": "message", "from": "cc2", "text": "hi"})
    assert isinstance(ev, connect.MessageEvent)
    assert ev.from_ == "cc2"


def test_parse_event_dispatches_task_assigned():
    ev = connect.parse_event({"type": "task_assigned", "task": {"id": "T1"}})
    assert isinstance(ev, connect.TaskAssignedEvent)
    assert ev.task["id"] == "T1"


def test_parse_event_dispatches_task_completed():
    ev = connect.parse_event({"type": "task_completed", "task": {"id": "T2"}})
    assert isinstance(ev, connect.TaskCompletedEvent)


def test_parse_event_dispatches_memory_write():
    ev = connect.parse_event(
        {"type": "memory_write", "memory": {"key": "k", "value": 1}}
    )
    assert isinstance(ev, connect.MemoryEvent)
    assert ev.key == "k"


def test_parse_event_dispatches_approval_decision():
    ev = connect.parse_event(
        {"type": "approval_decision", "id": "ap_1", "decision": True, "action": "go"}
    )
    assert isinstance(ev, connect.ApprovalDecisionEvent)
    assert ev.decision is True


def test_parse_event_dispatches_vote_resolved():
    ev = connect.parse_event(
        {"type": "vote_resolved", "vote_id": "v1", "winner": "yes"}
    )
    assert isinstance(ev, connect.VoteResolvedEvent)
    assert ev.winner == "yes"


def test_parse_event_dispatches_plugin_invoke_result():
    ev = connect.parse_event(
        {
            "type": "plugin_invoke_result",
            "plugin": "p",
            "tool": "t",
            "status": "discovered",
        }
    )
    assert isinstance(ev, connect.PluginInvokeResultEvent)
    assert ev.plugin == "p"


def test_parse_event_returns_none_for_unknown_type():
    assert connect.parse_event({"type": "definitely_unknown_event"}) is None


def test_parse_event_returns_none_for_missing_type():
    assert connect.parse_event({}) is None


def test_parse_event_returns_none_for_non_dict():
    assert connect.parse_event(None) is None  # type: ignore[arg-type]
    assert connect.parse_event("not a dict") is None  # type: ignore[arg-type]
    assert connect.parse_event(["list"]) is None  # type: ignore[arg-type]
