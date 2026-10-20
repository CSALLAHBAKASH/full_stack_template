import sys
from collections import defaultdict
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from fastapi.testclient import TestClient

import auth
from agentic_ai import step_01_llm_chat as chatbot
from agentic_ai import step_02_llm_with_tools as llm_with_tool
from agentic_ai import step_03_langchain_agent as langchain_agent
from agentic_ai.tools import __main__ as tools_cli
from agentic_ai.tools import standard as standard_tools
import main
import security
from database import Base, engine
from main import app


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.expirations: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def getex(self, key: str, ex: int) -> str | None:
        value = self.values.get(key)
        if value is not None:
            self.expirations[key] = ex
        return value

    def getdel(self, key: str) -> str | None:
        self.expirations.pop(key, None)
        return self.values.pop(key, None)

    def delete(self, key: str) -> int:
        self.expirations.pop(key, None)
        return int(self.values.pop(key, None) is not None)

    def incr(self, key: str) -> int:
        self.counters[key] += 1
        return self.counters[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fake_redis = MemoryRedis()
    monkeypatch.setattr(security, "redis_client", fake_redis)
    monkeypatch.setattr(auth, "redis_client", fake_redis)
    monkeypatch.setattr(main, "redis_client", fake_redis)
    app.state.fake_redis = fake_redis
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def sign_in_admin(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": "local-admin-password-change-me",
        },
    )
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()


def test_admin_can_create_user_and_role_is_enforced(client: TestClient) -> None:
    sign_in_admin(client)
    created = client.post(
        "/users",
        json={
            "email": "member@example.com",
            "full_name": "Workspace Member",
            "password": "a-long-member-password",
            "role": "user",
        },
    )
    assert created.status_code == 201
    assert created.json()["role"] == "user"
    assert "password_hash" not in created.json()

    client.cookies.clear()
    login = client.post(
        "/auth/login",
        json={"email": "member@example.com", "password": "a-long-member-password"},
    )
    assert login.status_code == 200
    assert client.get("/users").status_code == 403
    assert client.get("/auth/me").json()["email"] == "member@example.com"


def test_last_admin_cannot_disable_themselves(client: TestClient) -> None:
    sign_in_admin(client)
    me = client.get("/auth/me").json()

    response = client.patch(f"/users/{me['id']}", json={"is_active": False})

    assert response.status_code == 400
    assert "own active administrator" in response.json()["detail"]


def test_invalid_credentials_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "incorrect-password"},
    )

    assert response.status_code == 401


def test_chat_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 401


def test_authenticated_user_can_chat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_in_admin(client)
    monkeypatch.setattr(
        chatbot,
        "generate_chat_response",
        lambda messages: f"Echo: {messages[-1].content}",
    )

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "Echo: Hello"}


def test_chat_reports_missing_provider_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_in_admin(client)
    monkeypatch.setattr(chatbot.settings, "groq_api_key", "")

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_chat_cli_reports_provider_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_chat(prompt: str) -> str:
        raise HTTPException(status_code=503, detail="Set GROQ_API_KEY.")

    monkeypatch.setattr(chatbot, "run_cli_chat", fail_chat)
    monkeypatch.setattr(sys, "argv", ["step_01_llm_chat", "hello"])

    with pytest.raises(SystemExit) as error:
        chatbot.run_cli()

    assert error.value.code == 1
    assert "Unable to run chat: Set GROQ_API_KEY." in capsys.readouterr().err


def test_chat_rejects_invalid_conversation(client: TestClient) -> None:
    sign_in_admin(client)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "assistant", "content": "Hello"}]},
    )

    assert response.status_code == 422


def test_tool_chat_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/chat/tools",
        json={"messages": [{"role": "user", "content": "What is 2 plus 2?"}]},
    )

    assert response.status_code == 401


def test_authenticated_user_can_use_tool_chat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_in_admin(client)
    monkeypatch.setattr(
        llm_with_tool,
        "generate_tool_chat_response",
        lambda messages: f"Calculated: {messages[-1].content}",
    )

    response = client.post(
        "/chat/tools",
        json={"messages": [{"role": "user", "content": "What is 2 plus 2?"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "Calculated: What is 2 plus 2?"}


def test_langchain_agent_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/chat/agent",
        json={"messages": [{"role": "user", "content": "What is 2 plus 2?"}]},
    )

    assert response.status_code == 401


def test_authenticated_user_can_use_langchain_agent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_in_admin(client)

    class FakeAgent:
        def invoke(self, state):
            assert state["messages"][-1].content == "What is 2 plus 2?"
            return {"messages": [AIMessage(content="2 + 2 = **4**.")]}

    def fake_create_agent(**kwargs):
        assert kwargs["tools"] == langchain_agent.AGENT_TOOLS
        assert kwargs["tools"][: len(llm_with_tool.tools)] == llm_with_tool.tools
        assert kwargs["system_prompt"] == langchain_agent.SYSTEM_PROMPT
        return FakeAgent()

    monkeypatch.setattr(langchain_agent.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(langchain_agent, "create_agent", fake_create_agent)

    response = client.post(
        "/chat/agent",
        json={"messages": [{"role": "user", "content": "What is 2 plus 2?"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "2 + 2 = **4**."}


def test_langchain_agent_requires_provider_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sign_in_admin(client)
    monkeypatch.setattr(langchain_agent.settings, "groq_api_key", "")

    response = client.post(
        "/chat/agent",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    ("calculator", "arguments", "expected"),
    [
        (llm_with_tool.add_numbers, {"first": 8, "second": 3}, 11),
        (llm_with_tool.subtract_numbers, {"first": 8, "second": 3}, 5),
        (llm_with_tool.multiply_numbers, {"first": 8, "second": 3}, 24),
        (llm_with_tool.divide_numbers, {"first": 8, "second": 2}, 4),
    ],
)
def test_arithmetic_tools(
    calculator,
    arguments: dict[str, int],
    expected: int,
) -> None:
    assert calculator.invoke(arguments) == expected


def test_standard_tools_include_datetime_wikipedia_and_file_operations() -> None:
    assert {tool.name for tool in standard_tools.standard_tools} == {
        "get_current_datetime",
        "search_wikipedia",
        "create_text_file",
        "read_text_file",
        "append_to_text_file",
        "replace_text_in_file",
        "delete_text_file",
    }
    assert standard_tools.get_current_datetime.invoke({}).count("T") == 1


def test_wikipedia_tool_returns_article_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"query":{"pages":{"1":{"title":"Python (programming language)",'
                b'"extract":"Python is a programming language."}}}}'
            )

    monkeypatch.setattr(standard_tools, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = standard_tools.search_wikipedia.invoke({"query": "Python"})

    assert "Python is a programming language." in result
    assert (
        "https://en.wikipedia.org/wiki/Python_%28programming_language%29"
        in result
    )


def test_workspace_file_tools_create_read_append_modify_and_delete(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standard_tools, "AGENT_WORKSPACE", tmp_path)

    assert standard_tools.create_text_file.invoke(
        {"file_path": "notes.txt", "content": "hello"}
    ) == "Created notes.txt."
    assert standard_tools.read_text_file.invoke({"file_path": "notes.txt"}) == "hello"
    standard_tools.append_to_text_file.invoke(
        {"file_path": "notes.txt", "content": " world"}
    )
    standard_tools.replace_text_in_file.invoke(
        {"file_path": "notes.txt", "old_text": "world", "new_text": "agent"}
    )
    assert standard_tools.read_text_file.invoke({"file_path": "notes.txt"}) == "hello agent"
    assert standard_tools.delete_text_file.invoke({"file_path": "notes.txt"}) == "Deleted notes.txt."
    assert not (tmp_path / "notes.txt").exists()


@pytest.mark.parametrize("file_path", ["../outside.txt", "/tmp/outside.txt", "notes.md"])
def test_workspace_file_tools_reject_paths_outside_text_workspace(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    file_path: str,
) -> None:
    monkeypatch.setattr(standard_tools, "AGENT_WORKSPACE", tmp_path)

    with pytest.raises(ValueError):
        standard_tools.read_text_file.invoke({"file_path": file_path})


def test_tools_cli_runs_an_arithmetic_tool(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["agentic_ai.tools", "add_numbers", "12", "8"],
    )

    tools_cli.main()

    assert capsys.readouterr().out == "20.0\n"


def test_tools_cli_parses_keyword_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agentic_ai.tools",
            "add_numbers",
            "12",
            "--kwargs",
            '{"second": 8}',
        ],
    )

    tools_cli.main()

    assert capsys.readouterr().out == "20.0\n"


def test_tools_cli_rejects_non_object_keyword_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["agentic_ai.tools", "add_numbers", "12", "--kwargs", "[8]"],
    )

    with pytest.raises(SystemExit) as error:
        tools_cli.main()

    assert error.value.code == 2
    assert "--kwargs must be a JSON object." in capsys.readouterr().err


def test_tools_cli_reports_invalid_arithmetic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["agentic_ai.tools", "divide_numbers", "12", "0"],
    )

    with pytest.raises(SystemExit) as error:
        tools_cli.main()

    assert error.value.code == 2
    assert "Cannot divide by zero." in capsys.readouterr().err


def test_division_tool_rejects_division_by_zero() -> None:
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        llm_with_tool.divide_numbers.invoke({"first": 1, "second": 0})


def test_tool_chat_executes_model_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_with_tool.settings, "groq_api_key", "test-key")

    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0
            self.bound_tools = []
            self.messages = []

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        def invoke(self, messages):
            self.calls += 1
            self.messages = messages
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "add_numbers",
                            "args": {"first": 2, "second": 2},
                            "id": "call-add",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="2 + 2 = 4.")

    fake_model = FakeModel()
    monkeypatch.setattr(
        llm_with_tool.ChatGroq,
        "__new__",
        lambda cls, **kwargs: fake_model,
    )

    reply = llm_with_tool.generate_tool_chat_response(
        [chatbot.ChatMessage(role="user", content="What is 2 plus 2?")]
    )

    assert reply == "2 + 2 = 4."
    assert {calculator.name for calculator in fake_model.bound_tools} == {
        "add_numbers",
        "subtract_numbers",
        "multiply_numbers",
        "divide_numbers",
    }
    tool_messages = [message for message in fake_model.messages if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "4.0"


def test_run_tool_chat_builds_a_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages = []

    def fake_generate(messages):
        captured_messages.extend(messages)
        return "The result is 20."

    monkeypatch.setattr(llm_with_tool, "generate_tool_chat_response", fake_generate)

    assert llm_with_tool.run_tool_chat("What is 12 plus 8?") == "The result is 20."
    assert len(captured_messages) == 1
    assert captured_messages[0].role == "user"
    assert captured_messages[0].content == "What is 12 plus 8?"


def test_authenticated_request_refreshes_idle_session_expiry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security.settings, "session_ttl_seconds", 300)
    sign_in_admin(client)
    token = client.cookies.get(security.settings.session_cookie_name)
    assert token is not None
    key = security.session_key(token)
    fake_redis = client.app.state.fake_redis
    assert fake_redis.expirations[key] == 300

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert fake_redis.expirations[key] == 300
    assert "max-age=300" in response.headers["set-cookie"].lower()
