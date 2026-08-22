"""Token vault tests: validation, credit maths, Redis caching, selection."""

import json

import httpx
import pytest
import respx

from backend.ingestion.tokens import (
    ApifyTokenService,
    CREDIT_CACHE_TTL_SECONDS,
    NoUsableTokenError,
    VaultToken,
    dev_fallback_token,
    is_valid_apify_token,
    mask_token,
    token_fingerprint,
)

USAGE_URL = "https://api.apify.com/v2/users/me/usage/monthly"


def _usage(used_usd, cycle=True):
    data = {"totalUsageCreditsUsdAfterVolumeDiscount": used_usd}
    if cycle:
        data["usageCycle"] = {"startAt": "2026-08-01T00:00:00Z", "endAt": "2026-08-31T23:59:59Z"}
    return {"data": data}


def _route_per_token(mapping):
    """Route the usage endpoint by Authorization header."""

    def responder(request):
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ")
        response = mapping.get(token)
        if response is None:
            return httpx.Response(401, json={"error": "unauthorized"})
        return response

    respx.get(USAGE_URL).mock(side_effect=responder)


# --- validation / helpers ---------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("apify_api_abcdef123456", True),
        ("  apify_api_padded  ", True),
        ("not_an_apify_token", False),
        ("APIFY_API_UPPER", False),
        ("", False),
        (None, False),
    ],
)
def test_token_prefix_validation(token, expected):
    assert is_valid_apify_token(token) is expected


def test_mask_token_shows_only_the_last_four_characters():
    assert mask_token("apify_api_supersecret9876") == "••••9876"
    assert "supersecret" not in mask_token("apify_api_supersecret9876")
    assert mask_token("ab") == "••••"


def test_token_fingerprint_is_stable_and_not_the_token():
    token = "apify_api_secret"
    assert token_fingerprint(token) == token_fingerprint("  apify_api_secret  ")
    assert token not in token_fingerprint(token)


def test_dev_fallback_token_reads_the_env_var(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    assert dev_fallback_token() is None

    monkeypatch.setenv("APIFY_TOKEN", "not-a-token")
    assert dev_fallback_token() is None

    monkeypatch.setenv("APIFY_TOKEN", "apify_api_fromenv")
    fallback = dev_fallback_token()
    assert fallback.token == "apify_api_fromenv"
    assert fallback.label == "env:APIFY_TOKEN"


# --- credit summaries -------------------------------------------------------


@respx.mock
async def test_remaining_credit_is_plan_cap_minus_usage(fake_redis):
    respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(1.25)))
    service = ApifyTokenService(redis_client=fake_redis)

    summary = await service.fetch_credit_summary(
        VaultToken(token="apify_api_a", token_id=1, label="main", plan_cap_usd=5.0)
    )

    assert summary.used_usd == 1.25
    assert summary.remaining_usd == 3.75
    assert summary.pct_used == 25.0
    assert summary.is_usable is True
    assert summary.usage_cycle_start == "2026-08-01T00:00:00Z"


@respx.mock
async def test_token_with_less_than_a_cent_left_is_unusable(fake_redis):
    respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(4.999)))
    service = ApifyTokenService(redis_client=fake_redis)

    summary = await service.fetch_credit_summary(
        VaultToken(token="apify_api_a", plan_cap_usd=5.0)
    )

    assert summary.remaining_usd < 0.01
    assert summary.is_usable is False


@respx.mock
async def test_plan_cap_is_per_token(fake_redis):
    respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(10.0)))
    service = ApifyTokenService(redis_client=fake_redis)

    free_tier = await service.fetch_credit_summary(
        VaultToken(token="apify_api_a", plan_cap_usd=5.0), use_cache=False
    )
    paid_tier = await service.fetch_credit_summary(
        VaultToken(token="apify_api_b", plan_cap_usd=49.0), use_cache=False
    )

    assert free_tier.is_usable is False
    assert paid_tier.is_usable is True
    assert paid_tier.remaining_usd == 39.0


async def test_a_malformed_token_never_reaches_the_network(fake_redis):
    # respx is not active here, so any HTTP call would raise.
    summary = await ApifyTokenService(redis_client=fake_redis).fetch_credit_summary(
        VaultToken(token="nope", token_id=7, label="bad")
    )
    assert summary.is_usable is False
    assert "Apify API token" in summary.error


@respx.mock
async def test_unauthorized_token_is_reported_and_its_cache_entry_dropped(fake_redis):
    token = "apify_api_revoked"
    fake_redis.store[ApifyTokenService._cache_key(token)] = json.dumps(
        {"totalUsageCreditsUsdAfterVolumeDiscount": 0.0}
    )
    respx.get(USAGE_URL).mock(return_value=httpx.Response(401, json={"error": "nope"}))

    service = ApifyTokenService(redis_client=fake_redis)
    summary = await service.fetch_credit_summary(
        VaultToken(token=token, label="revoked"), use_cache=False
    )

    assert summary.is_usable is False
    assert "invalid or unauthorized" in summary.error
    assert ApifyTokenService._cache_key(token) not in fake_redis.store


@respx.mock
async def test_transport_failure_is_reported_as_unusable(fake_redis):
    respx.get(USAGE_URL).mock(side_effect=httpx.ConnectError("dns blew up"))

    summary = await ApifyTokenService(redis_client=fake_redis).fetch_credit_summary(
        VaultToken(token="apify_api_a")
    )

    assert summary.is_usable is False
    assert summary.error == "Could not reach the Apify API"


# --- Redis caching ----------------------------------------------------------


@respx.mock
async def test_credit_summary_is_cached_for_ten_minutes(fake_redis):
    route = respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(2.0)))
    service = ApifyTokenService(redis_client=fake_redis)
    vault_token = VaultToken(token="apify_api_a", plan_cap_usd=5.0)

    first = await service.fetch_credit_summary(vault_token)
    second = await service.fetch_credit_summary(vault_token)

    assert route.call_count == 1, "second lookup should be served from Redis"
    assert first.remaining_usd == second.remaining_usd == 3.0

    key = ApifyTokenService._cache_key(vault_token.token)
    assert fake_redis.expirations[key] == CREDIT_CACHE_TTL_SECONDS


@respx.mock
async def test_cache_is_keyed_by_token_so_tokens_do_not_share_summaries(fake_redis):
    _route_per_token(
        {
            "apify_api_a": httpx.Response(200, json=_usage(1.0)),
            "apify_api_b": httpx.Response(200, json=_usage(4.0)),
        }
    )
    service = ApifyTokenService(redis_client=fake_redis)

    a = await service.fetch_credit_summary(VaultToken(token="apify_api_a", plan_cap_usd=5.0))
    b = await service.fetch_credit_summary(VaultToken(token="apify_api_b", plan_cap_usd=5.0))

    assert (a.remaining_usd, b.remaining_usd) == (4.0, 1.0)


@respx.mock
async def test_a_cap_change_takes_effect_without_a_cache_miss(fake_redis):
    route = respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(6.0)))
    service = ApifyTokenService(redis_client=fake_redis)

    before = await service.fetch_credit_summary(
        VaultToken(token="apify_api_a", plan_cap_usd=5.0)
    )
    after = await service.fetch_credit_summary(
        VaultToken(token="apify_api_a", plan_cap_usd=49.0)
    )

    assert route.call_count == 1
    assert before.is_usable is False
    assert after.remaining_usd == 43.0


async def test_caching_is_skipped_entirely_when_redis_is_unavailable(monkeypatch):
    service = ApifyTokenService()
    monkeypatch.setattr(service, "_redis_resolved", True)
    monkeypatch.setattr(service, "_redis", None)

    assert await service._cache_read("apify_api_a") is None
    await service._cache_write("apify_api_a", {"x": 1})  # must not raise
    await service.invalidate("apify_api_a")  # must not raise


# --- selection --------------------------------------------------------------


@respx.mock
async def test_select_best_token_picks_the_most_remaining_credit(fake_redis):
    _route_per_token(
        {
            "apify_api_low": httpx.Response(200, json=_usage(4.5)),
            "apify_api_best": httpx.Response(200, json=_usage(0.5)),
            "apify_api_mid": httpx.Response(200, json=_usage(2.0)),
        }
    )
    tokens = [
        VaultToken(token="apify_api_low", token_id=1, label="low"),
        VaultToken(token="apify_api_best", token_id=2, label="best"),
        VaultToken(token="apify_api_mid", token_id=3, label="mid"),
    ]

    chosen, summary = await ApifyTokenService(redis_client=fake_redis).select_best_token(tokens)

    assert chosen.label == "best"
    assert summary.remaining_usd == 4.5


@respx.mock
async def test_select_best_token_skips_exhausted_and_invalid_tokens(fake_redis):
    _route_per_token(
        {
            "apify_api_exhausted": httpx.Response(200, json=_usage(5.0)),
            "apify_api_broken": httpx.Response(500, json={"error": "boom"}),
            "apify_api_ok": httpx.Response(200, json=_usage(4.0)),
        }
    )
    tokens = [
        VaultToken(token="apify_api_exhausted", token_id=1, label="exhausted"),
        VaultToken(token="apify_api_broken", token_id=2, label="broken"),
        VaultToken(token="apify_api_revoked", token_id=3, label="revoked"),  # 401 by default
        VaultToken(token="apify_api_ok", token_id=4, label="ok"),
    ]

    chosen, summary = await ApifyTokenService(redis_client=fake_redis).select_best_token(tokens)

    assert chosen.label == "ok"
    assert summary.remaining_usd == 1.0


@respx.mock
async def test_select_best_token_raises_when_every_token_is_spent(fake_redis):
    respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(5.0)))
    tokens = [
        VaultToken(token="apify_api_a", token_id=1, label="a"),
        VaultToken(token="apify_api_b", token_id=2, label="b"),
    ]

    with pytest.raises(NoUsableTokenError) as excinfo:
        await ApifyTokenService(redis_client=fake_redis).select_best_token(tokens)

    assert len(excinfo.value.summaries) == 2
    assert "a" in str(excinfo.value)


@respx.mock
async def test_empty_vault_falls_back_to_the_env_token(fake_redis, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_fromenv")
    respx.get(USAGE_URL).mock(return_value=httpx.Response(200, json=_usage(0.1)))

    chosen, summary = await ApifyTokenService(redis_client=fake_redis).select_best_token([])

    assert chosen.token == "apify_api_fromenv"
    assert summary.is_usable is True


async def test_empty_vault_without_the_env_token_raises(fake_redis, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    with pytest.raises(NoUsableTokenError):
        await ApifyTokenService(redis_client=fake_redis).select_best_token([])
