import json

import pytest
from pydantic import BaseModel

from backend.pipeline.llm_transport import (
    DEFAULT_PIPELINE_MODEL,
    llm_call_kwargs,
    resolve_model,
    structured_completion,
)


class _Schema(BaseModel):
    ok: bool
    value: int


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _acompletion_returning(*payloads):
    """Stub acompletion_fn that returns each payload (a JSON string or an
    Exception instance to raise) in order across successive calls."""
    calls = {"n": 0}

    async def _fn(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        payload = payloads[min(i, len(payloads) - 1)]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)

    _fn.calls = calls
    return _fn


# --- resolve_model / llm_call_kwargs ------------------------------------------


class _FakeLLMConfig:
    def __init__(self, model_name=None, encrypted_api_key=None, custom_base_url=None, key_version=1):
        self.model_name = model_name
        self.encrypted_api_key = encrypted_api_key
        self.encrypted_with_key_version = key_version
        self.custom_base_url = custom_base_url


def test_resolve_model_defaults_when_no_config():
    assert resolve_model(None) == DEFAULT_PIPELINE_MODEL


def test_resolve_model_defaults_when_model_name_unset():
    assert resolve_model(_FakeLLMConfig(model_name=None)) == DEFAULT_PIPELINE_MODEL


def test_resolve_model_uses_org_configured_model():
    assert resolve_model(_FakeLLMConfig(model_name="openrouter/anthropic/claude-3-haiku")) == (
        "openrouter/anthropic/claude-3-haiku"
    )


def test_llm_call_kwargs_falls_back_to_env_when_no_org_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env-fallback")
    kwargs = llm_call_kwargs(None)
    assert kwargs == {"api_key": "sk-env-fallback"}


def test_llm_call_kwargs_never_touches_os_environ(monkeypatch):
    # decrypt() would raise on garbage ciphertext; patch it to prove the
    # function reads the org's vault entry rather than falling back to env,
    # without needing a real Fernet key round-trip in this unit test.
    import backend.pipeline.llm_transport as transport

    monkeypatch.setattr(transport, "decrypt", lambda token, version=1: "sk-org-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-should-not-be-used")

    config = _FakeLLMConfig(model_name="openrouter/x", encrypted_api_key="ciphertext", custom_base_url="https://x.example.com")
    kwargs = llm_call_kwargs(config)
    assert kwargs == {"api_key": "sk-org-real-key", "api_base": "https://x.example.com"}
    # Never mutated into the environment.
    assert __import__("os").environ.get("OPENROUTER_API_KEY") == "sk-should-not-be-used"


# --- structured_completion -----------------------------------------------------


async def test_structured_completion_parses_valid_json_first_try():
    fn = _acompletion_returning(json.dumps({"ok": True, "value": 3}))
    parsed, _resp = await structured_completion("prompt", "model-x", _Schema, {}, acompletion_fn=fn)
    assert parsed.ok is True
    assert parsed.value == 3
    assert fn.calls["n"] == 1


async def test_structured_completion_strips_code_fences():
    fn = _acompletion_returning("```json\n" + json.dumps({"ok": True, "value": 7}) + "\n```")
    parsed, _resp = await structured_completion("prompt", "model-x", _Schema, {}, acompletion_fn=fn)
    assert parsed.value == 7


async def test_structured_completion_retries_once_on_invalid_json():
    fn = _acompletion_returning("not json at all", json.dumps({"ok": False, "value": 1}))
    parsed, _resp = await structured_completion("prompt", "model-x", _Schema, {}, acompletion_fn=fn)
    assert parsed.ok is False
    assert fn.calls["n"] == 2


async def test_structured_completion_retries_once_on_schema_mismatch():
    fn = _acompletion_returning(
        json.dumps({"wrong_field": 1}), json.dumps({"ok": True, "value": 9})
    )
    parsed, _resp = await structured_completion("prompt", "model-x", _Schema, {}, acompletion_fn=fn)
    assert parsed.value == 9
    assert fn.calls["n"] == 2


async def test_structured_completion_raises_after_the_retry_also_fails():
    fn = _acompletion_returning("still not json", "still not json either")
    with pytest.raises(Exception):
        await structured_completion("prompt", "model-x", _Schema, {}, acompletion_fn=fn)
    assert fn.calls["n"] == 2
