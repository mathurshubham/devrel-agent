"""
Seeds system-default PromptTemplate rows (org_id = NULL) from the prompt
corpus in backend/prompts/*_v3.md.

Ported from social-agent/backend/scripts/init_db.py's parsing conventions,
adapted to the V7 PromptTemplate model (platform + type columns, single
`name`/`content` pair instead of title/category/prompt_body).

Run as: python -m backend.seed
"""
import asyncio
import glob
import os
import re

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import PromptTemplate, PromptType, PlatformEnum

# Only these three platforms are in scope for V7 (HackerNews/Mastodon prompt
# files from the reference corpus are intentionally not carried over).
SUPPORTED_PLATFORMS = {"REDDIT", "LINKEDIN", "TWITTER"}

PROMPT_GLOB = "TryEval_*_Reply_Prompts_v3.md"
ANALYST_PROMPTS_FILE = "TryEval_Analyst_Prompts_v3.md"

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def _platform_slug(filename: str) -> str:
    """
    Extract the platform slug from a prompt filename, e.g.
    "TryEval_LinkedIn_Reply_Prompts_v3.md" -> "LINKEDIN".
    """
    base = os.path.basename(filename)
    match = re.match(r"TryEval_(\w+)_Reply_Prompts(?:_v\d+)?\.md", base, re.IGNORECASE)
    return match.group(1).upper() if match else "GENERIC"


def parse_platform_markdown(content: str, platform_slug: str):
    """
    Parse a TryEval_<Platform>_Reply_Prompts_v3.md file into
    (master_context, [{"name": angle_name, "content": body}, ...]).
    """
    master_context_match = re.search(r"## MASTER CONTEXT BLOCK.*?```(.*?)```", content, re.DOTALL)
    master_context = master_context_match.group(1).strip() if master_context_match else None

    angles = []
    prompt_sections = re.findall(r"## PROMPT #?(\d+) — (.*?)\n.*?```(.*?)```", content, re.DOTALL)
    for num, name, body in prompt_sections:
        angle_name = f"{platform_slug}-ANGLE-{num}: {name.strip()}"
        angles.append({"name": angle_name, "content": body.strip()})

    return master_context, angles


def parse_analyst_prompts(content: str):
    """
    Parse TryEval_Analyst_Prompts_v3.md.
    Each ## ANALYST_{NAME} section becomes {"name": "ANALYST-{NAME}", "content": str}.
    """
    results = []
    sections = re.split(r"^## (ANALYST_\w+)", content, flags=re.MULTILINE)
    it = iter(sections[1:])
    for section_name, body in zip(it, it):
        name = f"ANALYST-{section_name.strip()}"
        fence = re.search(r"```(.*?)```", body, re.DOTALL)
        body_clean = fence.group(1).strip() if fence else body.strip().rstrip("-").strip()
        results.append({"name": name, "content": body_clean})
    return results


async def _upsert_prompt_template(session, *, name: str, content: str, type_: PromptType, platform=None):
    """Idempotent upsert keyed by name (org_id is always NULL for seeded templates).

    Uses an explicit SELECT-then-update/insert rather than an ON CONFLICT
    upsert: Postgres unique constraints treat NULL org_id values as distinct
    from each other, so `uq_org_prompt_name (org_id, name)` alone can't be
    relied on to deduplicate system-default rows across repeated seed runs.
    """
    result = await session.execute(
        select(PromptTemplate).where(PromptTemplate.org_id.is_(None), PromptTemplate.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.content = content
        existing.type = type_
        existing.platform = platform
    else:
        session.add(PromptTemplate(
            org_id=None,
            platform=platform,
            type=type_,
            name=name,
            content=content,
        ))


async def seed():
    async with SessionLocal() as session:
        print("Seeding prompt templates (upserting)...")

        prompt_files = sorted(glob.glob(os.path.join(PROMPTS_DIR, PROMPT_GLOB)))
        if not prompt_files:
            print(f"WARNING: No prompt files found matching {os.path.join(PROMPTS_DIR, PROMPT_GLOB)}")

        for filepath in prompt_files:
            slug = _platform_slug(filepath)
            if slug not in SUPPORTED_PLATFORMS:
                print(f"  Skipping {os.path.basename(filepath)} (platform '{slug}' not in scope for V7)")
                continue

            print(f"  Loading prompts from {os.path.basename(filepath)} (platform={slug})")
            with open(filepath, "r") as f:
                content = f.read()

            master_context, angles = parse_platform_markdown(content, slug)
            platform_enum = PlatformEnum[slug]

            if master_context:
                await _upsert_prompt_template(
                    session,
                    name=f"{slug}-MASTER_CONTEXT",
                    content=master_context,
                    type_=PromptType.MASTER_CONTEXT,
                    platform=platform_enum,
                )

            for angle in angles:
                await _upsert_prompt_template(
                    session,
                    name=angle["name"],
                    content=angle["content"],
                    type_=PromptType.ANGLE,
                    platform=platform_enum,
                )

        # Analyst prompts (platform-agnostic).
        analyst_file = os.path.join(PROMPTS_DIR, ANALYST_PROMPTS_FILE)
        if os.path.exists(analyst_file):
            print(f"  Loading analyst prompts from {ANALYST_PROMPTS_FILE}")
            with open(analyst_file, "r") as f:
                analyst_content = f.read()

            for section in parse_analyst_prompts(analyst_content):
                await _upsert_prompt_template(
                    session,
                    name=section["name"],
                    content=section["content"],
                    type_=PromptType.ANALYST,
                    platform=None,
                )
        else:
            print(f"WARNING: {ANALYST_PROMPTS_FILE} not found at {analyst_file}")

        await session.commit()
        print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed())
