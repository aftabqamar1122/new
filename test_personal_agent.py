#!/usr/bin/env python3
"""Tests for the personal agent — memory, tool dispatch, and the chat loop.

No API key and no network needed; the Anthropic client is stubbed.

    python test_personal_agent.py
"""

import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path

import tools.memory_tools as mem

_TMP = Path(tempfile.mkdtemp(prefix="personal_agent_test_"))
mem.DB_PATH = _TMP / "memory.db"

import personal_agent as pa  # noqa: E402  (imported after DB_PATH is redirected)


# --- stub Anthropic client ---------------------------------------------------


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Message:
    def __init__(self, content):
        self.content = content


class _Stream:
    def __init__(self, message):
        self._message = message
        self.text_stream = (b.text for b in message.content if b.type == "text")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _Messages:
    """Replies with a tool call first, then a plain text answer."""

    def __init__(self):
        self.calls = []

    @contextmanager
    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            message = _Message([
                _Block(type="text", text="Got it. "),
                _Block(type="tool_use", id="t1", name="remember",
                       input={"content": "Name is Sam.", "category": "profile"}),
            ])
        else:
            message = _Message([_Block(type="text", text="Nice to meet you, Sam.")])
        yield _Stream(message)


class _Client:
    def __init__(self, **kwargs):
        self.messages = _Messages()


# --- tests -------------------------------------------------------------------


def test_memory_crud():
    assert mem.remember("Name is Sam.", "profile")["success"]
    assert mem.remember("Name is Sam.", "profile")["message"] == "Already remembered."
    mem.remember("Works on the Almeria project.", "project")
    mem.remember("Prefers concise answers.", "preference")

    found = mem.recall("almeria")
    assert found["total"] == 1, found
    assert mem.recall(category="preference")["total"] == 1
    assert mem.recall("almeria", category="profile")["total"] == 0, "category must narrow keyword hits"

    memory_id = found["memories"][0]["id"]
    assert mem.update_memory(memory_id, "Leads the Almeria project.")["success"]
    assert "Leads" in mem.recall("almeria")["memories"][0]["content"]
    assert "error" in mem.update_memory(9999, "nope")
    assert "error" in mem.forget(9999)
    assert mem.forget(memory_id)["success"]
    assert mem.recall("almeria")["total"] == 0
    assert "(profile) Name is Sam." in mem.profile_summary()


def test_history_is_api_safe():
    """A session that died mid-reply can leave a dangling user turn."""
    cleaned = pa._alternating([
        {"role": "assistant", "content": "orphan reply"},
        {"role": "user", "content": "first"},
        {"role": "user", "content": "unanswered retry"},
        {"role": "assistant", "content": "reply"},
    ])
    assert [m["role"] for m in cleaned] == ["user", "assistant"], cleaned
    assert cleaned[0]["content"] == "unanswered retry", cleaned
    assert pa._alternating([]) == []


def test_every_tool_has_a_handler():
    agent = pa.PersonalAgent(api_key="test", resume=False)
    assert {t["name"] for t in agent.tools} == set(agent.handlers)


def test_chat_runs_tools_and_streams():
    agent = pa.PersonalAgent(api_key="test", agent_name="Ava", user_name="Sam", resume=False)

    streamed = []
    reply = agent.chat("Hi, I'm Sam.", on_text=streamed.append)

    assert reply == "Got it. \nNice to meet you, Sam."
    assert "".join(streamed) == "Got it. Nice to meet you, Sam."
    assert len(agent.client.messages.calls) == 2, "tool result should drive a second turn"
    assert [m["role"] for m in agent.history] == ["user", "assistant", "user", "assistant"]
    assert mem.recall("Sam")["total"] >= 1, "the tool call should have written to the DB"

    system = agent.client.messages.calls[-1]["system"]
    assert "Sam" in system and "(profile) Name is Sam." in system, "known facts belong in the prompt"


def test_tool_errors_are_returned_not_raised():
    agent = pa.PersonalAgent(api_key="test", resume=False)
    assert "Unknown tool" in agent._run_tool("no_such_tool", {})["error"]
    assert "Bad arguments" in agent._run_tool("remember", {"wrong_arg": 1})["error"]


def test_google_tools_attach_only_when_configured():
    fake_agent = types.SimpleNamespace(
        TOOLS=[{"name": n, "input_schema": {}} for n in ("get_emails", "send_email", "add_task")],
        _execute_tool=lambda name, inputs: {"called": name, "inputs": inputs},
    )
    sys.modules["agent"] = fake_agent
    original = pa._google_ready
    try:
        pa._google_ready = lambda: True
        schemas, handlers = pa._load_google_tools()
        assert sorted(t["name"] for t in schemas) == ["get_emails", "send_email"], "task tools must not double-load"
        # each handler must be bound to its own tool name
        assert handlers["get_emails"]({})["called"] == "get_emails"
        assert handlers["send_email"]({})["called"] == "send_email"

        pa._google_ready = lambda: False
        assert pa._load_google_tools() == ([], {})
    finally:
        pa._google_ready = original
        sys.modules.pop("agent", None)


def test_conversation_survives_a_restart():
    mem.clear_history()
    agent = pa.PersonalAgent(api_key="test", resume=False)
    agent.chat("Hi, I'm Sam.")

    assert [m["role"] for m in mem.recent_messages(10)] == ["user", "assistant"]
    assert pa.PersonalAgent(api_key="test", resume=True).resumed_turns == 2
    assert pa.PersonalAgent(api_key="test", resume=False).resumed_turns == 0

    facts_before = mem.stats()["facts"]
    assert mem.clear_history()["success"]
    assert mem.recent_messages(10) == []
    assert mem.stats()["facts"] == facts_before, "clearing chat history must not drop known facts"


def main() -> int:
    pa.anthropic = types.SimpleNamespace(Anthropic=_Client)

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {test.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {test.__name__}: {type(e).__name__}: {e}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for leftover in _TMP.glob("*"):
            leftover.unlink()
        _TMP.rmdir()
