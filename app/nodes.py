from typing import Any

from langgraph.types import interrupt

from .llm import llm, validator_llm
from .state import BlogState

from .prompts import (
    PLANNER_PROMPT,
    OUTLINE_VALIDATOR_PROMPT,
    WRITER_PROMPT,
    BLOG_VALIDATOR_PROMPT,
    EXTRAS_PROMPT,
)

_planner_chain = PLANNER_PROMPT | llm
_outline_validator_chain = OUTLINE_VALIDATOR_PROMPT | validator_llm
_writer_chain = WRITER_PROMPT | llm
_blog_validator_chain = BLOG_VALIDATOR_PROMPT | validator_llm
_extras_chain = EXTRAS_PROMPT | llm


def _feedback_section(validation: str | None) -> str:
    if not validation:
        return ""

    return f"""
Your previous attempt was rejected by the reviewer for this reason:
{validation}

Revise your output so it directly addresses that feedback.
"""


_EMPTY_USAGE = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}


def _usage_from_message(message: Any) -> dict[str, float]:
    """Pull token counts (and $ cost, if OpenRouter reported one) off an AIMessage."""
    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    cost = response_metadata.get("cost")

    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
        "cost_usd": float(cost) if cost is not None else 0.0,
    }


def _accumulate_usage(state: BlogState, node_name: str, message: Any) -> dict[str, Any]:
    """Fold this node's usage into the state's running token_usage totals.

    Nodes in this graph run strictly sequentially (no fan-out), so reading the
    current total from `state` and returning an updated replacement is safe
    and avoids needing a custom LangGraph reducer.
    """
    call_usage = _usage_from_message(message)
    current = state.get("token_usage") or {**_EMPTY_USAGE, "by_node": {}}

    by_node = dict(current.get("by_node", {}))
    node_totals = dict(
        by_node.get(node_name, {**_EMPTY_USAGE, "calls": 0})
    )
    node_totals["input_tokens"] += call_usage["input_tokens"]
    node_totals["output_tokens"] += call_usage["output_tokens"]
    node_totals["total_tokens"] += call_usage["total_tokens"]
    node_totals["cost_usd"] += call_usage["cost_usd"]
    node_totals["calls"] += 1
    by_node[node_name] = node_totals

    return {
        "input_tokens": current.get("input_tokens", 0) + call_usage["input_tokens"],
        "output_tokens": current.get("output_tokens", 0) + call_usage["output_tokens"],
        "total_tokens": current.get("total_tokens", 0) + call_usage["total_tokens"],
        "cost_usd": current.get("cost_usd", 0.0) + call_usage["cost_usd"],
        "by_node": by_node,
    }


async def planner_node(state: BlogState) -> BlogState:
    response = await _planner_chain.ainvoke(
        {
            "topic": state["topic"],
            "feedback_section": _feedback_section(state.get("outline_validation")),
        }
    )

    attempts = state.get("planner_attempts", 0) + 1

    return {
        "blog_outline": response.content,
        "planner_attempts": attempts,
        "token_usage": _accumulate_usage(state, "planner", response),
    }


async def outline_validator_node(state: BlogState) -> BlogState:
    raw_result = await _outline_validator_chain.ainvoke({"blog_outline": state["blog_outline"]})
    result = raw_result["parsed"]

    validation = "OK" if result.status == "OK" else f"RETRY:\n{result.reason or ''}"

    return {
        "outline_validation": validation,
        "token_usage": _accumulate_usage(state, "outline_validator", raw_result["raw"]),
    }


def outline_review_node(state: BlogState) -> BlogState:
    decision = interrupt(
        {
            "type": "outline_review",
            "topic": state["topic"],
            "outline": state["blog_outline"],
            "attempts": state.get("planner_attempts", 0),
            "token_usage": state.get("token_usage") or _EMPTY_USAGE,
        }
    )

    if decision.get("approved"):
        return {"outline_approved": True}

    feedback = (decision.get("feedback") or "").strip()

    return {
        "outline_approved": False,
        "outline_validation": f"RETRY:\n{feedback}",
    }


async def writer_node(state: BlogState) -> BlogState:
    response = await _writer_chain.ainvoke(
        {
            "topic": state["topic"],
            "blog_outline": state["blog_outline"],
            "feedback_section": _feedback_section(state.get("blog_validation")),
        }
    )

    attempts = state.get("writer_attempts", 0) + 1

    return {
        "blog_post": response.content,
        "writer_attempts": attempts,
        "token_usage": _accumulate_usage(state, "writer", response),
    }


async def blog_validator_node(state: BlogState) -> BlogState:
    raw_result = await _blog_validator_chain.ainvoke({"blog_post": state["blog_post"]})
    result = raw_result["parsed"]

    validation = "OK" if result.status == "OK" else f"RETRY:\n{result.reason or ''}"

    return {
        "blog_validation": validation,
        "token_usage": _accumulate_usage(state, "blog_validator", raw_result["raw"]),
    }


def blog_review_node(state: BlogState) -> BlogState:
    decision = interrupt(
        {
            "type": "blog_review",
            "topic": state["topic"],
            "blog_post": state["blog_post"],
            "attempts": state.get("writer_attempts", 0),
            "token_usage": state.get("token_usage") or _EMPTY_USAGE,
        }
    )

    if decision.get("approved"):
        return {"blog_approved": True}

    feedback = (decision.get("feedback") or "").strip()

    return {
        "blog_approved": False,
        "blog_validation": f"RETRY:\n{feedback}",
    }


async def extras_node(state: BlogState) -> BlogState:
    response = await _extras_chain.ainvoke(
        {"topic": state["topic"], "blog_outline": state["blog_outline"]}
    )

    return {
        "extras": response.content,
        "token_usage": _accumulate_usage(state, "extras", response),
    }