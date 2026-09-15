from langgraph.graph import StateGraph, START, END

from .state import BlogState

from .nodes import (
    planner_node,
    outline_validator_node,
    outline_review_node,
    writer_node,
    blog_validator_node,
    blog_review_node,
    extras_node,
)


def route_after_outline_validation(state: BlogState):
    validation = state["outline_validation"].strip().upper()

    if validation.startswith("OK"):
        return "review"

    if state.get("planner_attempts", 0) < 3:
        return "retry"

    return "review"


def route_after_outline_review(state: BlogState):
    if state.get("outline_approved"):
        return "approved"

    return "rejected"


def route_after_blog_validation(state: BlogState):
    validation = state["blog_validation"].strip().upper()

    if validation.startswith("OK"):
        return "review"

    if state.get("writer_attempts", 0) < 3:
        return "retry"

    return "review"


def route_after_blog_review(state: BlogState):
    if state.get("blog_approved"):
        return "approved"

    return "rejected"


_review_builder = StateGraph(BlogState)

_review_builder.add_node("planner", planner_node)
_review_builder.add_node("outline_validator", outline_validator_node)
_review_builder.add_node("outline_review", outline_review_node)
_review_builder.add_node("writer", writer_node)
_review_builder.add_node("blog_validator", blog_validator_node)
_review_builder.add_node("blog_review", blog_review_node)
_review_builder.add_node("extras", extras_node)

_review_builder.add_edge(START, "planner")
_review_builder.add_edge("planner", "outline_validator")

_review_builder.add_conditional_edges(
    "outline_validator",
    route_after_outline_validation,
    {
        "retry": "planner",
        "review": "outline_review",
    },
)

_review_builder.add_conditional_edges(
    "outline_review",
    route_after_outline_review,
    {
        "approved": "writer",
        "rejected": "planner",
    },
)

_review_builder.add_edge("writer", "blog_validator")

_review_builder.add_conditional_edges(
    "blog_validator",
    route_after_blog_validation,
    {
        "retry": "writer",
        "review": "blog_review",
    },
)

_review_builder.add_conditional_edges(
    "blog_review",
    route_after_blog_review,
    {
        "approved": "extras",
        "rejected": "writer",
    },
)

_review_builder.add_edge("extras", END)


def route_after_outline_validation_full(state: BlogState):
    validation = state["outline_validation"].strip().upper()

    if validation.startswith("OK"):
        return "writer"

    if state.get("planner_attempts", 0) < 3:
        return "planner"

    return "writer"


def route_after_blog_validation_full(state: BlogState):
    validation = state["blog_validation"].strip().upper()

    if validation.startswith("OK"):
        return "extras"

    if state.get("writer_attempts", 0) < 3:
        return "writer"

    return "extras"


_full_builder = StateGraph(BlogState)

_full_builder.add_node("planner", planner_node)
_full_builder.add_node("outline_validator", outline_validator_node)
_full_builder.add_node("writer", writer_node)
_full_builder.add_node("blog_validator", blog_validator_node)
_full_builder.add_node("extras", extras_node)

_full_builder.add_edge(START, "planner")
_full_builder.add_edge("planner", "outline_validator")

_full_builder.add_conditional_edges(
    "outline_validator",
    route_after_outline_validation_full,
    {
        "planner": "planner",
        "writer": "writer",
    },
)

_full_builder.add_edge("writer", "blog_validator")

_full_builder.add_conditional_edges(
    "blog_validator",
    route_after_blog_validation_full,
    {
        "writer": "writer",
        "extras": "extras",
    },
)

_full_builder.add_edge("extras", END)


def compile_graphs(checkpointer) -> dict:
    return {
        "review": _review_builder.compile(checkpointer=checkpointer),
        "full": _full_builder.compile(),
    }