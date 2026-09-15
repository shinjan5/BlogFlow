from typing import Any, TypedDict


class BlogState(TypedDict, total=False):
    topic: str
    blog_outline: str
    outline_validation: str
    outline_approved: bool
    blog_post: str
    blog_validation: str
    blog_approved: bool
    extras: str
    planner_attempts: int
    writer_attempts: int
    # Running token/cost totals for the whole generation, accumulated
    # node-by-node. Shape: {input_tokens, output_tokens, total_tokens,
    # cost_usd, by_node: {node_name: {input_tokens, output_tokens,
    # total_tokens, cost_usd, calls}}}
    token_usage: dict[str, Any]