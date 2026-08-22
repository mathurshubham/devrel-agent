from backend.pipeline.analyst_pillars import (
    DEFAULT_PILLAR_TAXONOMY,
    get_pillar_taxonomy,
    pillar_tags,
    pillar_tier,
    taxonomy_block,
)
from backend.pipeline.analyst_schemas import confidence_to_float


def test_get_pillar_taxonomy_defaults_when_org_settings_missing():
    assert get_pillar_taxonomy(None) == DEFAULT_PILLAR_TAXONOMY


def test_get_pillar_taxonomy_defaults_when_unset_on_settings():
    class FakeSettings:
        pillar_taxonomy = None

    assert get_pillar_taxonomy(FakeSettings()) == DEFAULT_PILLAR_TAXONOMY


def test_get_pillar_taxonomy_honours_org_customization():
    class FakeSettings:
        pillar_taxonomy = [{"tag": "CUSTOM_PILLAR", "tier": "PRIMARY"}]

    result = get_pillar_taxonomy(FakeSettings())
    assert result == [{"tag": "CUSTOM_PILLAR", "tier": "PRIMARY"}]


def test_pillar_tags_extracts_tag_list():
    tags = pillar_tags(DEFAULT_PILLAR_TAXONOMY)
    assert "METRICS_ILLUSION" in tags
    assert "SAFETY_COMPLIANCE" in tags
    assert len(tags) == 10


def test_pillar_tier_looks_up_tier_for_tag():
    assert pillar_tier(DEFAULT_PILLAR_TAXONOMY, "METRICS_ILLUSION") == "PRIMARY"
    assert pillar_tier(DEFAULT_PILLAR_TAXONOMY, "AGENT_RELIABILITY") == "SECONDARY"
    assert pillar_tier(DEFAULT_PILLAR_TAXONOMY, "NOT_A_PILLAR") is None


def test_taxonomy_block_renders_org_tags_and_tiers():
    block = taxonomy_block([{"tag": "CUSTOM", "tier": "PRIMARY"}])
    assert "CUSTOM (PRIMARY)" in block
    assert "ORG PILLAR TAXONOMY" in block


def test_taxonomy_block_empty_for_no_taxonomy():
    assert taxonomy_block([]) == ""


def test_confidence_to_float_maps_categorical_values():
    assert confidence_to_float("HIGH") == 0.9
    assert confidence_to_float("MEDIUM") == 0.6
    assert confidence_to_float("MED") == 0.6
    assert confidence_to_float("LOW") == 0.3
    assert confidence_to_float("unrecognized") == 0.5


def test_confidence_to_float_passes_through_fractional_numbers():
    assert confidence_to_float(0.75) == 0.75


def test_confidence_to_float_normalizes_percentages():
    assert confidence_to_float(90) == 0.9
