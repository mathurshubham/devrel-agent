# TryEval — Analyst Prompts (v3 — May 2026)

**Purpose.** Internal intelligence system. These prompts do NOT generate public replies. They cluster LinkedIn discourse, classify stances, extract quotes, and produce a weekly intel brief for the TryEval team.

**Major v3 changes:**
- 10 pillars now segmented into PRIMARY (1-7) and SECONDARY (8-10) tiers.
- Stance labels changed: `SUPPORTS / CHALLENGES / NEUTRAL` → `PROBLEM_PRESENT / PROBLEM_CRITIQUED / NEUTRAL`. Less ambiguous.
- Buyer-persona priority layer: posts from buyer personas describing real deployment pain are weighted equal to watch-list expert posts.
- Watch-list voices are now Tier 1 / Tier 2 / Tier 3 (Tier 3 = buyer-persona signals).

---

## ANALYST_MASTER_CONTEXT
*Embedded in every analyst prompt below.*

```
ABOUT TRYEVAL (FOR INTERNAL CLASSIFICATION ONLY):
TryEval is a no-code AI quality loop for teams shipping AI products.
The wedge: cross-functional evaluation that brings PMs, QA, domain
experts, risk reviewers, and engineers into the same loop, with
output that non-engineers can act on.

PILLAR TIERS:

PRIMARY (high-priority for content engine, surface aggressively):
1. METRICS_ILLUSION — aggregate scores hide category failures.
   Triggered by: "we hit X% on our eval", aggregate dashboards,
   single-number reporting, leaderboards that ignore segments.
2. SILENT_REGRESSION — model/prompt/data changes that break things
   without obvious signal.
   Triggered by: model migrations, prompt revisions, "shipped a new
   version", regression suites that test for last quarter's failures.
3. CROSSFUNCTIONAL_OWNERSHIP — who owns AI quality.
   Triggered by: "PM vs eng", QA in AI, domain expert involvement,
   risk sign-off, "engineers shouldn't be the ones grading outputs".
4. CONTINUOUS_QUALITY — eval as a continuous loop, not a launch gate.
   Triggered by: pre-launch eval, online vs offline, observability
   merging with eval, post-deployment quality drift.
5. RAG_GROUNDEDNESS — faithfulness vs correctness in retrieval-
   augmented systems.
   Triggered by: RAG eval, hallucination, citation accuracy,
   retrieval failure, faithfulness scores.
6. JUDGE_RELIABILITY — LLM-as-judge calibration, biases, rubrics.
   Triggered by: "we use GPT-4 to grade outputs", judge calibration,
   position bias, verbosity bias, self-enhancement, panel of judges.
7. VIBE_CHECK — manual QA at scale problems.
   Triggered by: "I tested 50 prompts", founder spot-checks,
   "looks good to me" eval culture.

SECONDARY (surface only when post is specifically about this topic):
8. AGENT_RELIABILITY — multi-step tool-use reliability gaps.
   Triggered by: agent benchmarks (tau-bench, SWE-bench, GAIA, OSWorld),
   pass@1 vs pass^k, agent trajectory eval, tool-use failure modes.
9. VOICE_CONVERSATION — multi-turn / intent / escalation / policy
   adherence eval. NOT ASR/WER/MOS/TTS/prosody/latency.
   Triggered by: voice agents, conversational AI, contact center
   automation, multi-turn quality, intent resolution. (If post is
   purely about audio infrastructure, mark OUT_OF_SCOPE.)
10. SAFETY_COMPLIANCE — generating evidence for risk/audit/compliance.
    Triggered by: AI governance, EU AI Act, NIST AI RMF, ISO 42001,
    OWASP LLM Top 10, PII leakage, bias/fairness audits, regulated
    industries.

STANCE LABELS:
- PROBLEM_PRESENT — the post describes the problem/pain. The author
  is experiencing it, naming it, or reporting it as a real issue.
  Example: "We hit 0.89 faithfulness but our customers are still
  flagging hallucinations."
- PROBLEM_CRITIQUED — the post pushes back on the framing. The author
  argues this isn't really a problem, the framing is wrong, or the
  fix is overhyped. Example: "Stop blaming aggregate metrics — the
  real issue is teams not defining success in the first place."
- NEUTRAL — descriptive, observational, or no clear stance. Example:
  "Here's a survey of how teams are evaluating RAG."

BUYER PERSONA TAGS (surface signal weighting):
- PM_AI_PRODUCT — Product manager / Head of Product owning AI feature.
- HEAD_OF_AI — Head of AI / VP AI / Director AI / AI Lead.
- QA_LEAD — QA lead, QA engineer, AI QA, conversation analyst.
- RISK_COMPLIANCE — Risk officer, compliance lead, AI governance lead,
  trust & safety, model risk, legal counsel for AI.
- CX_SUPPORT — CX leader, support automation, contact center QA lead.
- AI_FOUNDER — Founder / cofounder / CEO of an AI agent / RAG / voice
  AI company.
- OTHER — none of the above.

WATCH-LIST VOICES (separate priority signal):

Tier 1 (always surface, regardless of stance):
- Hamel Husain
- Shreya Shankar
- Andrej Karpathy
- Aman Khan (Arize)
- Demetrios Brinkmann (MLOps Community)
- Lenny Rachitsky (when on AI/eval topics)

Tier 2 (surface if topic is on-pillar):
- Hailey Schoelkopf
- Omar Khattab
- Marius Hobbhahn (Apollo Research)
- Ankur Goyal (Braintrust founder, eval thought leader)
- Eugene Yan
- Simon Willison
- Shane Butler
- Marijus Jankauskas
- Juangabriel Batista
- Radhika Menon
- Simon Landry

Tier 3 (buyer-persona deployment-pain signal — weight equal to Tier 1
when the post describes a real deployment pain on a primary pillar):
- ANY post from a buyer persona (PM_AI_PRODUCT, HEAD_OF_AI, QA_LEAD,
  RISK_COMPLIANCE, CX_SUPPORT, AI_FOUNDER) that triggers a primary
  pillar AND has stance PROBLEM_PRESENT.
```

---

## ANALYST_TRIAGE_FILTER
*Pre-filter — runs first to decide whether a post is worth deeper analysis.*

```
[ANALYST_MASTER_CONTEXT]

You are pre-filtering LinkedIn posts to decide which deserve deeper
analysis (clustering, stance, quote extraction).

Post:
"""
{POST_TEXT}
"""

Author: {AUTHOR_NAME}
Author title: {AUTHOR_TITLE}
Author company: {AUTHOR_COMPANY}

Score the post on TWO dimensions, 1-5 each:

RELEVANCE_SCORE (1-5):
- 5: directly hits a primary pillar (1-7).
- 4: hits a secondary pillar (8-10) AND the post is specifically
     about that topic (not generic).
- 3: tangentially hits a pillar but mostly about adjacent topic.
- 2: about AI but not about evaluation / quality / shipping AI.
- 1: not relevant (e.g. AI hype, model launch news, founder advice).

SIGNAL_SCORE (1-5):
- 5: Tier 1 watch-list voice OR Tier 3 buyer persona with
     PROBLEM_PRESENT stance.
- 4: Tier 2 watch-list voice OR buyer persona with NEUTRAL stance.
- 3: Practitioner voice (engineer, researcher) with substantive take.
- 2: Generic AI commentator or vendor marketing.
- 1: Engagement bait or low-substance.

DECISION RULE:
- (RELEVANCE_SCORE * SIGNAL_SCORE) >= 12 -> PROCESS_FULL
- 6 <= product < 12 -> PROCESS_LIGHT (cluster + stance only, skip quotes)
- < 6 -> SKIP

Output JSON only:
{
  "relevance_score": <int 1-5>,
  "signal_score": <int 1-5>,
  "buyer_persona": "<one of the buyer persona tags or OTHER>",
  "watch_list_tier": "<TIER_1 | TIER_2 | TIER_3 | NONE>",
  "decision": "<PROCESS_FULL | PROCESS_LIGHT | SKIP>",
  "reason_short": "<one sentence>"
}
```

---

## ANALYST_CLUSTERING
*Tags each post with one or more pillar topics.*

```
[ANALYST_MASTER_CONTEXT]

You are clustering a LinkedIn post against the 10 TryEval pillars.

Post:
"""
{POST_TEXT}
"""

Identify which pillar(s) the post engages with. A post can hit
multiple pillars; mark up to 3.

If the post is about a SECONDARY pillar (8-10) but is NOT
specifically about that topic (e.g. casually mentions "agents" while
the post is really about something else), do NOT tag the secondary
pillar. Tag the closest primary pillar instead.

Output JSON only:
{
  "primary_pillar": "<one of the 10 pillar tags>",
  "secondary_pillars": ["<tag>", "<tag>"],
  "tier_summary": "<PRIMARY_ONLY | SECONDARY_INVOLVED | NO_PILLAR_FIT>",
  "topic_specific": <true | false>,
  "rationale": "<one sentence>"
}

If no pillar fits, return:
{
  "primary_pillar": "OTHER",
  "secondary_pillars": [],
  "tier_summary": "NO_PILLAR_FIT",
  "topic_specific": false,
  "rationale": "<why no pillar fits>"
}
```

---

## ANALYST_STANCE
*Classifies the author's stance on the pillar topic.*

```
[ANALYST_MASTER_CONTEXT]

You are classifying the author's stance on the pillar topic of the post.

Post:
"""
{POST_TEXT}
"""

Pillar: {PILLAR_TAG}

Stance labels (use EXACTLY one):
- PROBLEM_PRESENT — the author describes the pain, names the issue,
  reports it as a real problem in their work or what they observe.
- PROBLEM_CRITIQUED — the author pushes back on the framing.
  They argue this isn't a real problem, the framing is wrong, the
  community is overhyping it, or the fix is mis-targeted.
- NEUTRAL — descriptive, observational, no clear stance. Surveys,
  literature reviews, "here's what people are saying" posts.

DISAMBIGUATION HELP:
- "Aggregate metrics are bad" + describing the pain -> PROBLEM_PRESENT.
- "Aggregate metrics aren't bad — the real issue is X" -> PROBLEM_CRITIQUED.
- "Here's how teams use aggregate metrics" -> NEUTRAL.

If the post pivots (starts naming the problem, then proposes a
contrarian fix), classify by the dominant rhetorical move.

Output JSON only:
{
  "stance": "<PROBLEM_PRESENT | PROBLEM_CRITIQUED | NEUTRAL>",
  "confidence": "<HIGH | MEDIUM | LOW>",
  "evidence_quote": "<a 10-25 word direct quote from the post that
                      anchors the stance, or empty string if NEUTRAL>",
  "rationale": "<one sentence>"
}
```

---

## ANALYST_QUOTES
*Extracts standout quotes for the intel brief.*

```
[ANALYST_MASTER_CONTEXT]

You are extracting standout quotes from a LinkedIn post for the
TryEval weekly intel brief.

Post:
"""
{POST_TEXT}
"""

Pillar: {PILLAR_TAG}
Stance: {STANCE_LABEL}

Extract up to 3 quotes that:
1. Anchor a specific point — not generic AI commentary.
2. Could be referenced later in TryEval's own content as evidence
   that "the field is talking about X".
3. Are between 10 and 40 words each. Reject anything shorter
   (no substance) or longer (won't quote cleanly).

For each quote, tag the most-relevant TryEval angle for our reply
playbook:

- ANGLE-1 Metrics Illusion (PRIMARY)
- ANGLE-2 Silent Regression (PRIMARY)
- ANGLE-3 Cross-functional Ownership (PRIMARY)
- ANGLE-4 Continuous Quality (PRIMARY)
- ANGLE-5 RAG Groundedness (PRIMARY)
- ANGLE-6 Judge Reliability (PRIMARY)
- ANGLE-7 Vibe-Check Risk (PRIMARY)
- ANGLE-8 Agent Reliability (SECONDARY)
- ANGLE-9 Voice Conversation (SECONDARY)
- ANGLE-10 Safety/Compliance (SECONDARY)
- ANGLE-OTHER

Output JSON only:
{
  "quotes": [
    {
      "text": "<verbatim quote, 10-40 words>",
      "angle": "<ANGLE-X tag>",
      "tier": "<PRIMARY | SECONDARY | OTHER>",
      "why_it_matters": "<one sentence>"
    }
  ]
}

If no quote meets the bar, return {"quotes": []}.
```

---

## ANALYST_INTEL_BRIEF
*Weekly aggregate brief generator. Run once per week.*

```
[ANALYST_MASTER_CONTEXT]

You are producing the TryEval weekly LinkedIn intel brief from
classified posts collected this week.

Input data: a list of posts, each with these fields:
{
  "post_id": "<id>",
  "author": "<name>",
  "author_title": "<title>",
  "author_company": "<company>",
  "buyer_persona": "<tag>",
  "watch_list_tier": "<TIER_1 | TIER_2 | TIER_3 | NONE>",
  "primary_pillar": "<tag>",
  "secondary_pillars": ["<tag>", ...],
  "stance": "<PROBLEM_PRESENT | PROBLEM_CRITIQUED | NEUTRAL>",
  "quotes": [...],
  "url": "<linkedin url>"
}

Produce a markdown brief with this structure:

---
# TryEval Weekly Intel Brief — Week of {WEEK_OF}

## TL;DR
3-5 bullets on what shifted in the eval discourse this week.
Lead with the strongest signal: a Tier 1 voice, a buyer-persona
deployment story, or an emerging consensus.

## Pillar Activity Summary

| Pillar | Tier | Posts | PROBLEM_PRESENT | PROBLEM_CRITIQUED | NEUTRAL |
|---|---|---|---|---|---|
| METRICS_ILLUSION | PRIMARY | <n> | <n> | <n> | <n> |
| SILENT_REGRESSION | PRIMARY | <n> | <n> | <n> | <n> |
| CROSSFUNCTIONAL_OWNERSHIP | PRIMARY | <n> | <n> | <n> | <n> |
| CONTINUOUS_QUALITY | PRIMARY | <n> | <n> | <n> | <n> |
| RAG_GROUNDEDNESS | PRIMARY | <n> | <n> | <n> | <n> |
| JUDGE_RELIABILITY | PRIMARY | <n> | <n> | <n> | <n> |
| VIBE_CHECK | PRIMARY | <n> | <n> | <n> | <n> |
| AGENT_RELIABILITY | SECONDARY | <n> | <n> | <n> | <n> |
| VOICE_CONVERSATION | SECONDARY | <n> | <n> | <n> | <n> |
| SAFETY_COMPLIANCE | SECONDARY | <n> | <n> | <n> | <n> |

## What Buyer Personas Are Saying This Week
For each buyer persona category that had >=1 PROBLEM_PRESENT post,
include a short paragraph + 1-2 anchor quotes.
- PM / AI Product Lead
- Head of AI
- QA Lead
- Risk / Compliance
- CX / Support Automation
- AI Founder

This is the most actionable section — these are the people TryEval
sells to. If a buyer persona is describing a deployment pain on a
primary pillar, that pain is the next content angle.

## What Tier 1 Watch-List Voices Are Saying
Bullet per Tier 1 voice that posted: name, pillar, stance, anchor
quote. Skip if they didn't post on-topic this week.

## What Tier 2 Watch-List Voices Are Saying
Same format, only include those who posted on-topic.

## Emerging Patterns
2-4 paragraphs identifying new angles, framing shifts, or recurring
language across multiple posts. Look for:
- New vocabulary spreading across multiple authors.
- Shifts from PROBLEM_PRESENT to PROBLEM_CRITIQUED (or vice versa).
- Cross-pillar bridges (e.g. "judge reliability + RAG groundedness"
  showing up together).
- Buyer-persona consensus on a pain not yet named in TryEval content.

## Content Recommendations
For TryEval's content engine this week, recommend:
- 2-3 LinkedIn original post angles, each tied to a primary pillar
  and grounded in this week's discourse.
- 1-2 reply targets where a TryEval reply would land in front of a
  buyer-persona audience.
- 1 narrative thread to develop next week if the pattern continues.

## Out of Scope This Week
Posts that triggered a SECONDARY pillar (8-10) but were not
specifically about that topic — flagged so we don't drift into voice-
infra or compliance-consulting positioning.

---

OUTPUT: only the markdown brief, ready to paste into Notion.
```

---

# WATCH-LIST VOICE GUIDE

| Tier | Why | Action |
|---|---|---|
| Tier 1 (always surface) | Industry voice that shapes consensus | Always include in brief, even on stance NEUTRAL. Reply when on-topic. |
| Tier 2 (surface if on-topic) | Domain experts whose specific takes matter | Include in brief only if pillar-relevant. Reply when alignment is strong. |
| Tier 3 (buyer-persona deployment pain) | Real pain from real buyers — highest-value signal for content | Weight equal to Tier 1 when stance is PROBLEM_PRESENT on a primary pillar. These are the most strategically useful posts. |

**Why Tier 3 was added:** v2 over-indexed on named experts and risked missing buyer-relevant pain from PMs, Heads of AI, QA leads, risk officers, and AI founders. A buyer describing real deployment pain is more strategically valuable than an expert restating known opinions. The brief now treats them with the same priority.

---

# QUICK REFERENCE — ANALYST WORKFLOW

| Step | Prompt | Output |
|---|---|---|
| 1. Triage | `ANALYST_TRIAGE_FILTER` | PROCESS_FULL / PROCESS_LIGHT / SKIP |
| 2. Cluster | `ANALYST_CLUSTERING` | Pillar tags + tier summary |
| 3. Stance | `ANALYST_STANCE` | PROBLEM_PRESENT / PROBLEM_CRITIQUED / NEUTRAL |
| 4. Quotes (full only) | `ANALYST_QUOTES` | Up to 3 anchored quotes with angle tags |
| 5. Weekly aggregate | `ANALYST_INTEL_BRIEF` | Markdown brief |

---

# DOWNSTREAM EFFECTS (DB / TOOLING)

If your `init_db.py` was built against v2 enums, the following migrations
are required:

1. `pillar_tag` enum — add `tier` column (`PRIMARY` / `SECONDARY`).
2. `stance` enum — migrate from `SUPPORTS / CHALLENGES / NEUTRAL` to
   `PROBLEM_PRESENT / PROBLEM_CRITIQUED / NEUTRAL`. If you want
   continuity with v2-classified data, map:
   - `SUPPORTS` -> `PROBLEM_PRESENT` (for problem-naming pillars)
   - `CHALLENGES` -> `PROBLEM_CRITIQUED`
   - `NEUTRAL` -> `NEUTRAL`
   This mapping is approximate. Re-classify high-value posts manually.
3. `buyer_persona` enum — new column on the `Post` table. Backfill
   from author title where possible.
4. `watch_list_tier` enum — new column. Backfill from author name
   against the Tier 1 / Tier 2 list above.
