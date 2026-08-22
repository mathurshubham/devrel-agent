"""
Unit tests for the draft status machine and lock-enforcement guards in
backend/api/inbox.py. These operate on plain (unpersisted) DraftReply ORM
instances, so they run against no database at all -- the guards themselves
are pure functions of the draft's in-memory status/lock fields.

Postgres-specific behavior (the ON CONFLICT DO NOTHING idempotency of the
PostedHistory insert, and the cascade-delete FK) is covered separately in
test_postgres_integration.py against a real Postgres instance.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.api.inbox import (
    _CONFIRM_POSTED_FROM,
    _EDITABLE_FROM,
    _IGNORE_FROM,
    _LOCK_FROM,
    _OPEN_COPY_FROM,
    _REJECT_FROM,
    _UNCONFIRM_FROM,
    _enforce_and_take_over_lock,
    _escape_like,
    _require_status,
    LOCK_DURATION,
)
from backend.models import DraftReply, DraftStatus


def _draft(status: DraftStatus, **kwargs) -> DraftReply:
    return DraftReply(status=status, **kwargs)


# ── Status machine ────────────────────────────────────────────────────────────

ALL_STATUSES = list(DraftStatus)


@pytest.mark.parametrize(
    "allowed,action",
    [
        (_EDITABLE_FROM, "edit"),
        (_OPEN_COPY_FROM, "open-copy"),
        (_CONFIRM_POSTED_FROM, "confirm-posted"),
        (_UNCONFIRM_FROM, "unconfirm"),
        (_REJECT_FROM, "reject"),
        (_IGNORE_FROM, "ignore"),
        (_LOCK_FROM, "lock"),
    ],
)
def test_status_machine_allows_only_declared_statuses(allowed, action):
    for status in ALL_STATUSES:
        draft = _draft(status)
        if status in allowed:
            _require_status(draft, allowed, action)  # must not raise
        else:
            with pytest.raises(HTTPException) as exc_info:
                _require_status(draft, allowed, action)
            assert exc_info.value.status_code == 409


def test_confirm_posted_only_from_awaiting_confirm():
    assert _CONFIRM_POSTED_FROM == {DraftStatus.AWAITING_CONFIRM}
    for bad_status in (DraftStatus.PENDING, DraftStatus.POSTED, DraftStatus.REJECTED,
                        DraftStatus.IGNORED, DraftStatus.FAILED, DraftStatus.FAILED_COST_LIMIT):
        with pytest.raises(HTTPException) as exc_info:
            _require_status(_draft(bad_status), _CONFIRM_POSTED_FROM, "confirm-posted")
        assert exc_info.value.status_code == 409


def test_unconfirm_only_from_awaiting_confirm():
    assert _UNCONFIRM_FROM == {DraftStatus.AWAITING_CONFIRM}
    with pytest.raises(HTTPException):
        _require_status(_draft(DraftStatus.PENDING), _UNCONFIRM_FROM, "unconfirm")
    _require_status(_draft(DraftStatus.AWAITING_CONFIRM), _UNCONFIRM_FROM, "unconfirm")


def test_open_copy_allows_retry_from_awaiting_confirm():
    # open-copy is re-callable while AWAITING_CONFIRM (retry), and from PENDING.
    _require_status(_draft(DraftStatus.PENDING), _OPEN_COPY_FROM, "open-copy")
    _require_status(_draft(DraftStatus.AWAITING_CONFIRM), _OPEN_COPY_FROM, "open-copy")
    with pytest.raises(HTTPException):
        _require_status(_draft(DraftStatus.POSTED), _OPEN_COPY_FROM, "open-copy")


def test_reject_and_ignore_from_pending_or_awaiting_confirm():
    for allowed in (_REJECT_FROM, _IGNORE_FROM):
        assert allowed == {DraftStatus.PENDING, DraftStatus.AWAITING_CONFIRM}
        with pytest.raises(HTTPException):
            _require_status(_draft(DraftStatus.POSTED), allowed, "reject")
        with pytest.raises(HTTPException):
            _require_status(_draft(DraftStatus.IGNORED), allowed, "reject")


# ── Lock enforcement ──────────────────────────────────────────────────────────

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_lock_free_draft_is_taken_over():
    draft = _draft(DraftStatus.PENDING, locked_by_user_id=None, locked_at=None)
    _enforce_and_take_over_lock(draft, user_id=42, now=NOW)
    assert draft.locked_by_user_id == 42
    assert draft.locked_at == NOW


def test_lock_held_by_other_user_within_window_is_409():
    draft = _draft(
        DraftStatus.PENDING,
        locked_by_user_id=7,
        locked_at=NOW - timedelta(minutes=5),
    )
    with pytest.raises(HTTPException) as exc_info:
        _enforce_and_take_over_lock(draft, user_id=42, now=NOW)
    assert exc_info.value.status_code == 409
    # Lock must NOT have been taken over.
    assert draft.locked_by_user_id == 7


def test_lock_held_by_other_user_but_expired_is_taken_over():
    draft = _draft(
        DraftStatus.PENDING,
        locked_by_user_id=7,
        locked_at=NOW - LOCK_DURATION - timedelta(seconds=1),
    )
    _enforce_and_take_over_lock(draft, user_id=42, now=NOW)
    assert draft.locked_by_user_id == 42
    assert draft.locked_at == NOW


def test_lock_held_by_same_user_is_refreshed_not_blocked():
    draft = _draft(
        DraftStatus.PENDING,
        locked_by_user_id=42,
        locked_at=NOW - timedelta(minutes=1),
    )
    _enforce_and_take_over_lock(draft, user_id=42, now=NOW)
    assert draft.locked_by_user_id == 42
    assert draft.locked_at == NOW


def test_lock_boundary_at_exactly_15_minutes_is_expired():
    # (now - locked_at) < LOCK_DURATION is the "still locked" condition, so
    # exactly LOCK_DURATION elapsed must count as expired.
    draft = _draft(
        DraftStatus.PENDING,
        locked_by_user_id=7,
        locked_at=NOW - LOCK_DURATION,
    )
    _enforce_and_take_over_lock(draft, user_id=42, now=NOW)
    assert draft.locked_by_user_id == 42


def test_lock_naive_datetime_is_treated_as_utc():
    # locked_at coming back from a driver/session without tzinfo must not
    # blow up the (now - locked_at) comparison.
    naive_locked_at = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
    draft = _draft(DraftStatus.PENDING, locked_by_user_id=7, locked_at=naive_locked_at)
    with pytest.raises(HTTPException):
        _enforce_and_take_over_lock(draft, user_id=42, now=NOW)


# ── Search escaping ───────────────────────────────────────────────────────────

def test_escape_like_neutralizes_wildcards():
    assert _escape_like("50%_off") == "50\\%\\_off"
    assert _escape_like("plain text") == "plain text"
    assert _escape_like("back\\slash") == "back\\\\slash"
