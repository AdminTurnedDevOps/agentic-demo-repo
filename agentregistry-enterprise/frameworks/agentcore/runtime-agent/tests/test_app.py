import ast

import pytest
from fastapi import HTTPException

from runtime_agent.app import InvocationBody, extract_prompt, invoke, reply_text
from runtime_agent.tools import _eval, calculate, current_time


def test_extract_prompt_accepts_agentregistry_shape() -> None:
    assert extract_prompt(InvocationBody(prompt="What can you do?")) == "What can you do?"


def test_extract_prompt_accepts_nested_input() -> None:
    assert extract_prompt(InvocationBody(input={"prompt": "hi"})) == "hi"


def test_extract_prompt_rejects_empty() -> None:
    assert extract_prompt(InvocationBody()) == ""


def test_reply_text_flattens_strands_message() -> None:
    message = {"role": "assistant", "content": [{"text": "hello"}, {"text": "there"}]}
    assert reply_text(message) == "hello\nthere"


def test_calculate_arithmetic() -> None:
    assert calculate("(2 + 3) * 4") == "20"


def test_calculate_rejects_names() -> None:
    assert calculate("__import__('os')").startswith("cannot evaluate")


def test_eval_rejects_calls() -> None:
    with pytest.raises(ValueError):
        _eval(ast.parse("abs(1)", mode="eval"))


def test_current_time_is_utc() -> None:
    assert current_time().endswith("+00:00")


def test_invoke_requires_prompt() -> None:
    with pytest.raises(HTTPException) as error:
        invoke(InvocationBody())
    assert error.value.status_code == 400


def test_invoke_returns_string_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        message = {"role": "assistant", "content": [{"text": "four"}]}

    class _Agent:
        def __call__(self, prompt: str) -> _Result:
            assert prompt == "2+2"
            return _Result()

    monkeypatch.setattr("runtime_agent.app.get_agent", lambda: _Agent())
    assert invoke(InvocationBody(prompt="2+2")) == {"output": "four"}
