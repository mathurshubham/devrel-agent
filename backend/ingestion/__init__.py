"""Apify ingestion layer (PRD V7 M1).

Submodules:
    runner    — generic Apify REST run/poll/fetch engine
    tokens    — multi-token vault selection + Redis-cached credit summaries
    inputs    — per-platform actor input builders + actor registry
    normalize — per-platform normalizers to the shared post contract
    service   — orchestration (token pick -> budget guard -> run -> normalize)

Nothing is re-exported here on purpose: importing the package must not pull in
SQLAlchemy models or Redis, so that ``backend.ingestion.inputs`` and
``backend.ingestion.normalize`` stay importable in a bare unit-test process.
"""
