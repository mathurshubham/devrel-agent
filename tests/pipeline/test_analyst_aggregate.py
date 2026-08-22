"""Pure-Python aggregation/momentum math for the Analyst pipeline's
aggregate node (PRD V7 §5.6) -- no DB involved."""

from datetime import date

from backend.pipeline.analyst_nodes import compute_momentum, compute_pillar_counts, week_of_monday


def test_week_of_monday_normalizes_to_the_week_start():
    # 2026-08-22 is a Saturday.
    assert week_of_monday(date(2026, 8, 22)) == date(2026, 8, 17)
    assert week_of_monday(date(2026, 8, 17)) == date(2026, 8, 17)  # already Monday


def test_compute_pillar_counts_groups_by_primary_pillar_with_stance_breakdown():
    processed = [
        {"post_id": "p1", "primary_pillar": "METRICS_ILLUSION", "stance": "PROBLEM_PRESENT"},
        {"post_id": "p2", "primary_pillar": "METRICS_ILLUSION", "stance": "NEUTRAL"},
        {"post_id": "p3", "primary_pillar": "RAG_GROUNDEDNESS", "stance": "PROBLEM_CRITIQUED"},
    ]
    result = compute_pillar_counts(processed)

    assert result["METRICS_ILLUSION"]["count"] == 2
    assert result["METRICS_ILLUSION"]["stance_counts"] == {"PROBLEM_PRESENT": 1, "NEUTRAL": 1}
    assert result["METRICS_ILLUSION"]["post_ids"] == ["p1", "p2"]
    assert result["RAG_GROUNDEDNESS"]["count"] == 1


def test_compute_pillar_counts_defaults_missing_pillar_to_other():
    processed = [{"post_id": "p1", "primary_pillar": None, "stance": "NEUTRAL"}]
    result = compute_pillar_counts(processed)
    assert "OTHER" in result
    assert result["OTHER"]["count"] == 1


def test_compute_pillar_counts_empty_input():
    assert compute_pillar_counts([]) == {}


def test_compute_momentum_computes_delta_for_every_pillar_seen():
    prev = {"METRICS_ILLUSION": 3, "RAG_GROUNDEDNESS": 5}
    curr = {"METRICS_ILLUSION": 7, "JUDGE_RELIABILITY": 2}

    momentum = compute_momentum(prev, curr)

    assert momentum["METRICS_ILLUSION"] == {"prev": 3, "curr": 7, "delta": 4}
    assert momentum["RAG_GROUNDEDNESS"] == {"prev": 5, "curr": 0, "delta": -5}
    assert momentum["JUDGE_RELIABILITY"] == {"prev": 0, "curr": 2, "delta": 2}


def test_compute_momentum_empty_both_sides():
    assert compute_momentum({}, {}) == {}
