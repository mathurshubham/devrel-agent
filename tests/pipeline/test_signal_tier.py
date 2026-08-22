from backend.pipeline.signal_tier import compute_signal_tier


def test_watch_list_author_is_always_high():
    post = {"author_name": "Jane Q. Practitioner", "engagement_score": 0}
    assert compute_signal_tier(post, watch_names=["jane q. practitioner"]) == "HIGH"


def test_watch_list_match_is_case_insensitive_and_substring():
    post = {"author": "hamel_husain", "engagement_score": 0}
    assert compute_signal_tier(post, watch_names=["Hamel Husain"]) is None  # no substring overlap
    post2 = {"author_name": "Hamel Husain", "engagement_score": 0}
    assert compute_signal_tier(post2, watch_names=["hamel husain"]) == "HIGH"


def test_buyer_persona_headline_with_engagement_is_high():
    post = {
        "author_name": "Someone",
        "author_headline": "VP AI at BigCo",
        "engagement_score": 15,
    }
    assert compute_signal_tier(post, watch_names=[]) == "HIGH"


def test_buyer_persona_headline_without_enough_engagement_is_not_high():
    post = {
        "author_name": "Someone",
        "author_headline": "VP AI at BigCo",
        "engagement_score": 5,
    }
    assert compute_signal_tier(post, watch_names=[]) is None


def test_high_engagement_alone_is_medium():
    post = {"author_name": "Rando", "engagement_score": 75}
    assert compute_signal_tier(post, watch_names=[]) == "MEDIUM"


def test_low_engagement_and_no_signals_is_none():
    post = {"author_name": "Rando", "engagement_score": 3}
    assert compute_signal_tier(post, watch_names=[]) is None


def test_empty_watch_names_are_ignored_safely():
    post = {"author_name": "Rando", "engagement_score": 3}
    assert compute_signal_tier(post, watch_names=["", None, "   "]) is None


def test_falls_back_to_author_when_author_name_missing():
    post = {"author": "watchedhandle", "engagement_score": 0}
    assert compute_signal_tier(post, watch_names=["watchedhandle"]) == "HIGH"
