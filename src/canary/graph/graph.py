"""LangGraph graph assembly for the CANARY pipeline."""

from langgraph.graph import END, StateGraph

from canary.graph.nodes import (
    detect_change,
    extract_obligations,
    fetch_source,
    output_results,
    verify_citations_node,
    write_to_vault,
)
from canary.graph.state import CANARYState


def should_extract(state: CANARYState) -> str:
    """Conditional edge: skip LLM extraction if no change detected."""
    if state.get("changed"):
        return "extract"
    return "output"


def build_graph() -> StateGraph:
    """Build and compile the CANARY pipeline graph.

    Pipeline:
      fetch → detect → [if changed] → extract → verify → output → vault
                         [if unchanged] → output → vault
    """
    builder = StateGraph(CANARYState)

    builder.add_node("fetch_source", fetch_source)
    builder.add_node("detect_change", detect_change)
    builder.add_node("extract_obligations", extract_obligations)
    builder.add_node("verify_citations", verify_citations_node)
    builder.add_node("output_results", output_results)
    builder.add_node("write_to_vault", write_to_vault)

    builder.set_entry_point("fetch_source")
    builder.add_edge("fetch_source", "detect_change")
    builder.add_conditional_edges(
        "detect_change",
        should_extract,
        {"extract": "extract_obligations", "output": "output_results"},
    )
    builder.add_edge("extract_obligations", "verify_citations")
    builder.add_edge("verify_citations", "output_results")
    builder.add_edge("output_results", "write_to_vault")
    builder.add_edge("write_to_vault", END)

    return builder.compile()
