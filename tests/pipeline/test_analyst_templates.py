"""backend.pipeline.analyst_templates against an in-memory SQLite session --
PromptTemplate has no JSONB columns, so (unlike PostClassification/
TopicCluster) it's fully portable."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.models import Base, PromptTemplate, PromptType
from backend.pipeline.analyst_templates import get_analyst_templates, render


@pytest.fixture
async def sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[PromptTemplate.__table__])

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def test_render_substitutes_known_placeholders_leaves_unknown_intact():
    out = render("Hello {NAME}, pillar={PILLAR}", {"{NAME}": "World"})
    assert out == "Hello World, pillar={PILLAR}"


async def test_get_analyst_templates_inlines_master_context(sqlite_session):
    sqlite_session.add_all(
        [
            PromptTemplate(org_id=None, type=PromptType.ANALYST, name="ANALYST-ANALYST_MASTER_CONTEXT", content="MASTER TEXT"),
            PromptTemplate(
                org_id=None, type=PromptType.ANALYST, name="ANALYST-ANALYST_TRIAGE_FILTER",
                content="[ANALYST_MASTER_CONTEXT]\n\nScore this post.",
            ),
        ]
    )
    await sqlite_session.commit()

    templates = await get_analyst_templates(sqlite_session, org_id=1)

    assert templates["master"] == "MASTER TEXT"
    assert templates["triage"] == "MASTER TEXT\n\nScore this post."
    assert templates["cluster"] == ""  # not seeded in this test -> degrades to empty


async def test_get_analyst_templates_org_override_wins_over_system_default(sqlite_session):
    sqlite_session.add_all(
        [
            PromptTemplate(org_id=None, type=PromptType.ANALYST, name="ANALYST-ANALYST_STANCE", content="SYSTEM DEFAULT"),
            PromptTemplate(org_id=7, type=PromptType.ANALYST, name="ANALYST-ANALYST_STANCE", content="ORG CUSTOM"),
        ]
    )
    await sqlite_session.commit()

    templates = await get_analyst_templates(sqlite_session, org_id=7)
    assert templates["stance"] == "ORG CUSTOM"

    templates_other_org = await get_analyst_templates(sqlite_session, org_id=999)
    assert templates_other_org["stance"] == "SYSTEM DEFAULT"


async def test_get_analyst_templates_missing_entirely_returns_empty_strings(sqlite_session):
    templates = await get_analyst_templates(sqlite_session, org_id=1)
    assert templates == {"master": "", "triage": "", "cluster": "", "stance": "", "quotes": "", "brief": ""}
