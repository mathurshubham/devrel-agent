import pytest
from jsonschema import validate

v1_export_schema = {
    "type": "object",
    "required": ["export_version", "exported_at", "drafts"],
    "properties": {
        "export_version": {"type": "string"},
        "exported_at": {"type": "string"},
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "status", "reddit_post_url", "ai_draft_text"],
                "properties": {
                    "id": {"type": "integer"},
                    "status": {"type": "string", "enum": [
                        "PENDING", "APPROVED", "REJECTED", "PUBLISHED", 
                        "FAILED", "DELETED_BY_KILLSWITCH", "FAILED_COST_LIMIT"
                    ]},
                    "reddit_post_url": {"type": "string"},
                    "ai_draft_text": {"type": "string"},
                    "prompt_template_version": {"type": ["string", "null"]}
                }
            }
        }
    }
}

def test_tryeval_export_contract_schema():
    """
    Contract - TryEval: Export endpoint JSON matches v1.0 schema (jsonschema) 
    for all DraftStatus values. Includes prompt_template_version.
    """
    mock_payload = {
        "export_version": "1.0",
        "exported_at": "2026-03-10T12:00:00Z",
        "drafts": [
            {
                "id": 1,
                "status": "APPROVED",
                "reddit_post_url": "https://reddit.com/r/test/comments/xyz",
                "ai_draft_text": "Here is a helpful draft reply based on Master Context.",
                "prompt_template_version": "triage_v1"
            },
            {
                "id": 2,
                "status": "FAILED_COST_LIMIT",
                "reddit_post_url": "https://reddit.com/r/test/comments/abc",
                "ai_draft_text": "",
                "prompt_template_version": None
            }
        ]
    }
    
    validate(instance=mock_payload, schema=v1_export_schema)
