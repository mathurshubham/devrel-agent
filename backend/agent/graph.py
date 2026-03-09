from langgraph.graph import StateGraph, END
from backend.agent.state import AgentState
from backend.agent.nodes.scraper import reddit_post_fetch, keyword_matcher
from backend.agent.nodes.triage import llm_intent_classifier, tokenizer_and_truncator
from backend.agent.nodes.generator import draft_generator, confidence_gate
from backend.models import DraftStatus

# Define workflow
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("fetch_reddit", reddit_post_fetch)
workflow.add_node("match_keywords", keyword_matcher)
workflow.add_node("classify_intent", llm_intent_classifier)
workflow.add_node("truncate_context", tokenizer_and_truncator)
workflow.add_node("generate_draft", draft_generator)
workflow.add_node("confidence_gate", confidence_gate)

# Set entry point
workflow.set_entry_point("fetch_reddit")

# Routing Logic
def route_after_keyword_match(state: AgentState):
    if state["pre_filter_pass"]:
        return "classify_intent"
    return END

def route_after_intent_classify(state: AgentState):
    if state["confidence_score"] >= 0.3:
        return "truncate_context"
    return END

# Add edges
workflow.add_edge("fetch_reddit", "match_keywords")
workflow.add_conditional_edges(
    "match_keywords",
    route_after_keyword_match,
    {
        "classify_intent": "classify_intent",
        END: END
    }
)
workflow.add_conditional_edges(
    "classify_intent",
    route_after_intent_classify,
    {
        "truncate_context": "truncate_context",
        END: END
    }
)
workflow.add_edge("truncate_context", "generate_draft")
workflow.add_edge("generate_draft", "confidence_gate")
workflow.add_edge("confidence_gate", END)

# Compile
app = workflow.compile()

async def run_agent_pipeline(campaign_id: int, post_id: str) -> dict:
    """
    Main entry point for the LangGraph pipeline.
    Initializes state and invokes the graph.
    """
    initial_state: AgentState = {
        "campaign_id": campaign_id,
        "reddit_post_id": post_id,
        "post_url": "",
        "original_text": "",
        "matched_keywords": [],
        "pre_filter_pass": False,
        "confidence_score": 0.0,
        "triage_reasoning": "",
        "truncation_applied": False,
        "truncation_details": {},
        "ai_draft_text": "",
        "model_payload_token_count": 0,
        "final_status": DraftStatus.PENDING
    }
    
    # Run the graph
    # LangGraph app.ainvoke is used for async execution
    final_state = await app.ainvoke(initial_state)
    return final_state
