"""Per-call LiteLLM transport for the reply pipeline (PRD V7 §5.3/§2 D6).

Every call resolves its ``api_key``/``api_base`` from the org's BYOK vault
(``OrgLLMConfig``, Fernet-decrypted) with an ``OPENROUTER_API_KEY`` env
fallback for orgs that haven't configured one yet. ``os.environ`` is never
mutated -- multi-tenant safety depends on every call carrying its own key.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.models import OrgLLMConfig
from backend.utils.encryption import decrypt

logger = logging.getLogger(__name__)

#: Used when an org has no OrgLLMConfig row, or the row has no model_name set.
DEFAULT_PIPELINE_MODEL = "openrouter/google/gemini-2.5-flash"

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def extract_usage(response: Any) -> Optional[dict]:
    """Best-effort ``{"prompt_tokens", "completion_tokens"}`` off a litellm response.

    Used to meter *actual* scout/strategist LLM usage into the org's
    recorded spend (see ``backend.utils.cost_guard.record_llm_usage``) --
    persist_gate's own cost check only ever estimated the strategist's
    per-draft prompt+response tokens, so the scout call (one LLM call per
    poll, over every prefiltered post) and any batch/fallback strategist
    calls were previously invisible to the org's cost tracking entirely.
    Returns ``None`` when the response has no usable usage info (a fake in
    a unit test, a provider that omits it, ...).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt_tokens is None and completion_tokens is None:
        return None
    return {
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
    }


def resolve_model(llm_config: Optional[OrgLLMConfig]) -> str:
    if llm_config and llm_config.model_name:
        return llm_config.model_name
    return DEFAULT_PIPELINE_MODEL


def llm_call_kwargs(llm_config: Optional[OrgLLMConfig]) -> dict:
    """Build per-call LiteLLM kwargs. Never mutates os.environ."""
    kwargs: dict = {}
    if llm_config and llm_config.encrypted_api_key:
        kwargs["api_key"] = decrypt(
            llm_config.encrypted_api_key, version=llm_config.encrypted_with_key_version
        )
    elif os.environ.get("OPENROUTER_API_KEY"):
        kwargs["api_key"] = os.environ["OPENROUTER_API_KEY"]

    if llm_config and llm_config.custom_base_url:
        kwargs["api_base"] = llm_config.custom_base_url

    return kwargs


def _strip_code_fences(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


async def structured_completion(
    prompt: str,
    model: str,
    schema: Type[T],
    call_kwargs: dict,
    *,
    acompletion_fn=None,
) -> tuple[T, Any]:
    """Request JSON, validate via Pydantic, with exactly one corrective retry.

    Returns ``(parsed, raw_response)``. Raises the last error if both the
    initial call and the single retry fail to produce a valid payload.
    """
    if acompletion_fn is None:
        from litellm import acompletion as acompletion_fn  # local import: keep litellm out of import-time cost for callers that mock this

    messages: list[dict] = [{"role": "user", "content": prompt}]
    last_exc: Optional[Exception] = None

    for attempt in range(2):
        try:
            response = await acompletion_fn(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                **call_kwargs,
            )
        except Exception as exc:  # some providers/models reject response_format
            if attempt == 0 and ("json" in str(exc).lower() or "400" in str(exc)):
                try:
                    response = await acompletion_fn(model=model, messages=messages, **call_kwargs)
                except Exception as exc2:
                    last_exc = exc2
                    continue
            else:
                last_exc = exc
                if attempt == 0:
                    continue
                raise

        content = response.choices[0].message.content if response.choices else None
        if not content:
            last_exc = ValueError("LLM returned empty content")
        else:
            content = _strip_code_fences(content)
            try:
                parsed = schema.model_validate_json(content)
                return parsed, response
            except (ValidationError, json.JSONDecodeError) as exc:
                last_exc = exc
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That was not valid JSON matching the required schema "
                            f"({exc}). Return ONLY the corrected JSON object."
                        ),
                    }
                )

        if attempt == 1:
            break

    assert last_exc is not None
    raise last_exc


async def text_completion(
    prompt: str,
    model: str,
    call_kwargs: dict,
    *,
    acompletion_fn=None,
) -> tuple[str, Any]:
    """Plain-text (non-JSON) completion -- used by nodes that render prose
    rather than a structured payload (e.g. the Analyst pipeline's Intel
    Brief). Returns ``(text, raw_response)``; raises on any LLM failure or
    empty content, same as ``structured_completion``."""
    if acompletion_fn is None:
        from litellm import acompletion as acompletion_fn  # local import: see structured_completion

    # One retry on empty content, mirroring structured_completion: reasoning
    # models (e.g. openrouter/stealth/ox-alpha) intermittently return an empty
    # content channel after a long reasoning pass.
    last_exc: Exception | None = None
    for _attempt in range(2):
        response = await acompletion_fn(
            model=model, messages=[{"role": "user", "content": prompt}], **call_kwargs
        )
        content = response.choices[0].message.content if response.choices else None
        if content:
            return content.strip(), response
        last_exc = ValueError("LLM returned empty content")
    assert last_exc is not None
    raise last_exc
