"""Graph #1 -- the reply pipeline (PRD V7 §5.3).

ingest -> prefilter -> scout -> token_budget -> strategist -> finalize -> persist_gate

Replaces backend/agent/ (the V6-era schema-adapted stubs).
"""
