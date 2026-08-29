#!/usr/bin/env python3
"""Tests for the personal agent — memory, backends, tool dispatch, chat loop.

No API key and no network needed; the provider SDKs are stubbed.

    python test_personal_agent.py
"""

import json
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path

import tools.memory_tools as mem

_TMP = Path(tempfile.mkdtemp(prefix="personal_agent_test_"))
mem.DB_PATH = _TMP / "memory.db"

import llm  # noqa: E402
import personal_agent as pa  # noqa: E402  (imported after DB_PATH is redirected)


class _Obj:
    """Attribute bag standing in for an SDK response object."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- fake backend, for exercising the agent loop -----------------------------


class FakeBackend(llm.Backend):
    """Answers with a `remember` tool call, then a plain reply."""

    provider = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = []

    def run(self, system, messages, tools, on_text=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if len(self.calls) == 1:
            text = "Got it. "
            calls = [llm.ToolCall(id="t1", name="remember",
                                  arguments={"content": "Name is Sam.", "category": "profile"},
                                  raw_arguments="{}")]
        else:
            text, calls = "Nice to meet you, Sam.", []
        if on_text and text:
            on_text(text)
        return llm.Reply(text=text, tool_calls=calls, raw=None)

    def assistant_message(self, reply):
        return {"role": "assistant", "content": reply.text}

    def tool_result_messages(self, results):
        return [{"role": "tool", "tool_call_id": c.id, "content": json.dumps(r, default=str)}
                for c, r in results]


# --- stub Anthropic SDK ------------------------------------------------------


class _AnthropicStream:
    def __init__(self, message):
        self._message = message
        self.text_stream = (b.text for b in message.content if b.type == "text")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class _AnthropicMessages:
    def __init__(self, message):
        self._message = message
        self.requests = []

    @contextmanager
    def stream(self, **kwargs):
        self.requests.append(kwargs)
        yield _AnthropicStream(self._message)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._message


# --- stub OpenAI SDK (DeepSeek speaks this) ----------------------------------


def _chunk(content=None, tool_calls=None):
    return _Obj(choices=[_Obj(delta=_Obj(content=content, tool_calls=tool_calls))])


def _tool_delta(index, call_id=None, name=None, args=None):
    return _Obj(index=index, id=call_id, function=_Obj(name=name, arguments=args))


class _Completions:
    def __init__(self, stream_chunks=None, message=None):
        self._chunks = stream_chunks or []
        self._message = message
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs.get("stream"):
            return iter(self._chunks)
        return _Obj(choices=[_Obj(message=self._message)])


def _deepseek_backend(completions) -> llm.DeepSeekBackend:
    backend = llm.DeepSeekBackend.__new__(llm.DeepSeekBackend)
    backend.client = _Obj(chat=_Obj(completions=completions))
    backend.model = "deepseek-chat"
    backend.stream = True
    return backend


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
    agent = pa.PersonalAgent(backend=FakeBackend(), resume=False)
    assert {t["name"] for t in agent.tools} == set(agent.handlers)


def test_chat_runs_tools_and_streams():
    backend = FakeBackend()
    agent = pa.PersonalAgent(backend=backend, agent_name="Ava", user_name="Sam", resume=False)

    streamed = []
    reply = agent.chat("Hi, I'm Sam.", on_text=streamed.append)

    assert reply == "Got it. \nNice to meet you, Sam."
    assert "".join(streamed) == "Got it. Nice to meet you, Sam."
    assert len(backend.calls) == 2, "tool result should drive a second turn"
    assert [m["role"] for m in agent.history] == ["user", "assistant", "tool", "assistant"]
    assert mem.recall("Sam")["total"] >= 1, "the tool call should have written to the DB"

    system = backend.calls[-1]["system"]
    assert "Sam" in system and "(profile) Name is Sam." in system, "known facts belong in the prompt"


def test_tool_errors_are_returned_not_raised():
    agent = pa.PersonalAgent(backend=FakeBackend(), resume=False)
    assert "Unknown tool" in agent._run_tool("no_such_tool", {})["error"]
    assert "Bad arguments" in agent._run_tool("remember", {"wrong_arg": 1})["error"]


def test_unparseable_tool_arguments_go_back_to_the_model():
    """A malformed argument string must reach the model as an error, not crash."""

    class BadArgsBackend(FakeBackend):
        def run(self, system, messages, tools, on_text=None):
            self.calls.append({"system": system, "messages": list(messages), "tools": tools})
            if len(self.calls) == 1:
                bad = llm.DeepSeekBackend._to_tool_call("t1", "remember", "{not json")
                assert bad.error, "the backend should flag the parse failure"
                return llm.Reply(text="", tool_calls=[bad])
            return llm.Reply(text="Sorry, let me try that again.")

    backend = BadArgsBackend()
    agent = pa.PersonalAgent(backend=backend, resume=False)
    assert agent.chat("hi") == "Sorry, let me try that again."

    sent_back = json.loads(backend.calls[-1]["messages"][-1]["content"])
    assert "Could not parse arguments" in sent_back["error"], sent_back


# --- DeepSeek backend --------------------------------------------------------


def test_deepseek_tool_schema_translation():
    translated = llm.DeepSeekBackend.translate_tools(pa.CORE_TOOLS)
    assert len(translated) == len(pa.CORE_TOOLS)
    first = translated[0]
    assert first["type"] == "function"
    assert first["function"]["name"] == pa.CORE_TOOLS[0]["name"]
    assert first["function"]["parameters"] == pa.CORE_TOOLS[0]["input_schema"]
    # A tool declaring no inputs still needs a valid schema object.
    empty = llm.DeepSeekBackend.translate_tools([{"name": "ping", "description": "d"}])
    assert empty[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_deepseek_reassembles_streamed_tool_calls():
    """Names and JSON arguments arrive split across chunks, one slot per index."""
    completions = _Completions(stream_chunks=[
        _chunk(content="Sure. "),
        _chunk(tool_calls=[_tool_delta(0, call_id="call_1", name="remem", args='{"conte')]),
        _chunk(tool_calls=[_tool_delta(0, name="ber", args='nt": "Name is Sam."}')]),
        _chunk(tool_calls=[_tool_delta(1, call_id="call_2", name="list_tasks", args="")]),
        _chunk(content="One moment."),
    ])
    backend = _deepseek_backend(completions)

    streamed = []
    reply = backend.run("sys", [{"role": "user", "content": "hi"}], pa.CORE_TOOLS, on_text=streamed.append)

    assert "".join(streamed) == "Sure. One moment."
    assert reply.text == "Sure. One moment."
    assert [(c.id, c.name) for c in reply.tool_calls] == [("call_1", "remember"), ("call_2", "list_tasks")]
    assert reply.tool_calls[0].arguments == {"content": "Name is Sam."}
    assert reply.tool_calls[1].arguments == {}, "empty argument string means no arguments"
    assert not any(c.error for c in reply.tool_calls)

    request = completions.requests[0]
    assert request["stream"] is True
    assert request["messages"][0] == {"role": "system", "content": "sys"}
    assert request["tools"][0]["type"] == "function"


def test_deepseek_non_streaming_path():
    message = _Obj(
        content="Here you go.",
        tool_calls=[_Obj(id="call_9", function=_Obj(name="list_tasks", arguments='{"status": "pending"}'))],
    )
    backend = _deepseek_backend(_Completions(message=message))
    backend.stream = False

    streamed = []
    reply = backend.run("sys", [], pa.CORE_TOOLS, on_text=streamed.append)

    assert reply.text == "Here you go." and streamed == ["Here you go."]
    assert reply.tool_calls[0].arguments == {"status": "pending"}
    assert not backend.client.chat.completions.requests[0].get("stream")


def test_deepseek_message_bookkeeping():
    backend = _deepseek_backend(_Completions())
    call = llm.ToolCall(id="call_1", name="list_tasks", arguments={"status": "pending"},
                        raw_arguments='{"status": "pending"}')

    assistant = backend.assistant_message(llm.Reply(text="checking", tool_calls=[call]))
    assert assistant["role"] == "assistant" and assistant["content"] == "checking"
    assert assistant["tool_calls"] == [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "list_tasks", "arguments": '{"status": "pending"}'},
    }], "the model's own argument string must be echoed back verbatim"

    results = backend.tool_result_messages([(call, {"tasks": []})])
    assert results == [{"role": "tool", "tool_call_id": "call_1", "content": '{"tasks": []}'}]

    plain = backend.assistant_message(llm.Reply(text="hello"))
    assert "tool_calls" not in plain


def test_deepseek_rejects_non_object_arguments():
    bad = llm.DeepSeekBackend._to_tool_call("t1", "remember", "[1, 2]")
    assert "must be a JSON object" in bad.error and bad.arguments == {}


# --- Anthropic backend -------------------------------------------------------


def test_anthropic_backend_round_trip():
    message = _Obj(content=[
        _Obj(type="text", text="Sure."),
        _Obj(type="tool_use", id="tu_1", name="list_tasks", input={"status": "pending"}),
    ])
    backend = llm.AnthropicBackend.__new__(llm.AnthropicBackend)
    backend.client = _Obj(messages=_AnthropicMessages(message))
    backend.model = "claude-sonnet-5"
    backend.stream = True

    streamed = []
    reply = backend.run("sys", [{"role": "user", "content": "hi"}], pa.CORE_TOOLS, on_text=streamed.append)

    assert reply.text == "Sure." and streamed == ["Sure."]
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [("tu_1", "list_tasks", {"status": "pending"})]
    # Tools go over the wire in Anthropic's native shape, not OpenAI's.
    assert backend.client.messages.requests[0]["tools"][0]["name"] == pa.CORE_TOOLS[0]["name"]

    assert backend.assistant_message(reply) == {"role": "assistant", "content": message.content}
    results = backend.tool_result_messages([(reply.tool_calls[0], {"tasks": []})])
    assert len(results) == 1 and results[0]["role"] == "user", "Anthropic batches results into one turn"
    assert results[0]["content"][0]["tool_use_id"] == "tu_1"


# --- provider selection ------------------------------------------------------


def test_provider_selection(monkeyenv=None):
    import os

    saved = {k: os.environ.pop(v, None) for k, v in llm.ENV_KEYS.items()}
    try:
        assert llm.detect_provider() == ""
        try:
            llm.build_backend()
            raise AssertionError("expected MissingAPIKey")
        except llm.MissingAPIKey as e:
            assert "DEEPSEEK_API_KEY" in str(e) and "ANTHROPIC_API_KEY" in str(e)

        os.environ["ANTHROPIC_API_KEY"] = "x"
        assert llm.detect_provider() == "anthropic"
        os.environ["DEEPSEEK_API_KEY"] = "y"
        assert llm.detect_provider() == "deepseek", "DeepSeek wins when both keys are set"

        try:
            llm.build_backend(provider="mistral")
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "Unknown provider" in str(e)

        backend = llm.build_backend(provider="deepseek", model="deepseek-reasoner")
        assert backend.provider == "deepseek" and backend.model == "deepseek-reasoner"
        assert llm.build_backend(provider="deepseek").model == "deepseek-chat", "sane default model"
    finally:
        for provider, key in llm.ENV_KEYS.items():
            os.environ.pop(key, None)
            if saved[provider] is not None:
                os.environ[key] = saved[provider]


def test_google_tools_attach_only_when_configured():
    fake_module = types.SimpleNamespace(
        SCHEMAS=[{"name": n, "input_schema": {}} for n in ("get_emails", "send_email")],
        HANDLERS={n: (lambda n: lambda i: {"called": n})(n) for n in ("get_emails", "send_email")},
    )
    fake_tools_pkg = types.ModuleType("tools")
    fake_tools_pkg.__path__ = []  # keep `tools` a package for the real submodules
    saved_tools = sys.modules["tools"]
    original = pa._google_ready
    try:
        pa._google_ready = lambda: True
        sys.modules["tools.google_tools"] = fake_module
        setattr(saved_tools, "google_tools", fake_module)

        schemas, handlers = pa._load_google_tools()
        assert sorted(t["name"] for t in schemas) == ["get_emails", "send_email"]
        # each handler must stay bound to its own tool name
        assert handlers["get_emails"]({})["called"] == "get_emails"
        assert handlers["send_email"]({})["called"] == "send_email"

        pa._google_ready = lambda: False
        assert pa._load_google_tools() == ([], {}), "no credentials -> no email/calendar tools offered"
    finally:
        pa._google_ready = original
        sys.modules.pop("tools.google_tools", None)
        if hasattr(saved_tools, "google_tools"):
            delattr(saved_tools, "google_tools")


def test_google_and_agent_tools_stay_in_sync():
    """Both agents must expose the same Google schemas without duplicating them."""
    source = Path(__file__).parent / "tools" / "google_tools.py"
    text = source.read_text()
    for name in ("get_emails", "send_email", "get_morning_brief", "create_calendar_event"):
        assert f'"name": "{name}"' in text, f"{name} schema should live in tools/google_tools.py"
    assert '"name": "get_emails"' not in (Path(__file__).parent / "agent.py").read_text(), \
        "agent.py should import the Google schemas, not restate them"


def test_conversation_survives_a_restart():
    mem.clear_history()
    agent = pa.PersonalAgent(backend=FakeBackend(), resume=False)
    agent.chat("Hi, I'm Sam.")

    assert [m["role"] for m in mem.recent_messages(10)] == ["user", "assistant"]
    assert pa.PersonalAgent(backend=FakeBackend(), resume=True).resumed_turns == 2
    assert pa.PersonalAgent(backend=FakeBackend(), resume=False).resumed_turns == 0

    facts_before = mem.stats()["facts"]
    assert mem.clear_history()["success"]
    assert mem.recent_messages(10) == []
    assert mem.stats()["facts"] == facts_before, "clearing chat history must not drop known facts"



# --- CLI error reporting -----------------------------------------------------


def test_api_errors_are_explained_not_dumped():
    """The first thing a new user hits is a bad key; it must read as advice."""
    import chat

    class AuthenticationError(Exception): pass
    class APIConnectionError(Exception): pass
    class RateLimitError(Exception): pass
    class NotFoundError(Exception): pass

    assert "DEEPSEEK_API_KEY" in chat._explain(AuthenticationError("401"), "deepseek")
    assert "internet" in chat._explain(APIConnectionError("boom"), "deepseek")
    assert "credit" in chat._explain(RateLimitError("429"), "deepseek")
    assert "--model" in chat._explain(NotFoundError("no model"), "deepseek")
    # Anything unrecognised still surfaces the real error rather than swallowing it.
    assert "kaboom" in chat._explain(ValueError("kaboom"), "deepseek")


def test_cli_exits_nonzero_without_a_key():
    import os
    import chat

    saved = {v: os.environ.pop(v, None) for v in llm.ENV_KEYS.values()}
    try:
        assert chat.run(["hi"]) == 1, "a missing key must be an error exit, not a crash"
    finally:
        for var, value in saved.items():
            if value is not None:
                os.environ[var] = value


def main() -> int:
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
