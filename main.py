import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import sessions, storage
from app.checkpointer import init_checkpointer, close_checkpointer
from app.config import get_settings
from app.graph import compile_graphs

logger = logging.getLogger(__name__)

settings = get_settings()

_graphs: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpointer = await init_checkpointer()
    await storage.init_db()
    _graphs.update(compile_graphs(checkpointer))

    yield

    await close_checkpointer()


app = FastAPI(
    title="Blog Generation Agent",
    description="LangGraph multi-agent technical blog generation API",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BlogRequest(BaseModel):
    topic: str = Field(..., min_length=1)


class BlogResponse(BaseModel):
    id: int
    blog_post: str
    extras: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class HistoryItem(BaseModel):
    id: int
    topic: str
    created_at: str
    total_tokens: int = 0
    cost_usd: float = 0.0


class HistoryDetail(HistoryItem):
    blog_post: str
    extras: str
    input_tokens: int = 0
    output_tokens: int = 0


class OutlineStartRequest(BaseModel):
    topic: str = Field(..., min_length=1)


class OutlineFeedbackRequest(BaseModel):
    session_id: str
    approved: bool
    feedback: str | None = None


class BlogFeedbackRequest(BaseModel):
    session_id: str
    approved: bool
    feedback: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _run_and_stream(graph, graph_input, config, session_id: str, on_complete=None):
    interrupted = False

    async for mode, payload in graph.astream(graph_input, config, stream_mode=["messages", "updates"]):
        if mode == "messages":
            message_chunk, metadata = payload
            node = metadata.get("langgraph_node")
            content = getattr(message_chunk, "content", "")

            if node in ("planner", "writer", "extras") and content:
                yield _sse("token", {"session_id": session_id, "node": node, "content": content})

        elif mode == "updates":
            for node_name, node_update in payload.items():
                if node_name == "__interrupt__":
                    interrupted = True
                    interrupt_payload = node_update[0].value
                    yield _sse("interrupt", {"session_id": session_id, **interrupt_payload})
                else:
                    yield _sse("node_complete", {"session_id": session_id, "node": node_name})

                    usage = isinstance(node_update, dict) and node_update.get("token_usage")
                    if usage:
                        yield _sse(
                            "usage",
                            {
                                "session_id": session_id,
                                "node": node_name,
                                "input_tokens": usage.get("input_tokens", 0),
                                "output_tokens": usage.get("output_tokens", 0),
                                "total_tokens": usage.get("total_tokens", 0),
                                "cost_usd": usage.get("cost_usd", 0.0),
                            },
                        )

    if not interrupted and on_complete is not None:
        result = await on_complete(config)
        yield _sse("complete", {"session_id": session_id, **result})

    yield _sse("end", {"session_id": session_id})


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/generate", response_model=BlogResponse)
async def generate_blog(request: BlogRequest):
    try:
        initial_state = {
            "topic": request.topic,
            "planner_attempts": 0,
            "writer_attempts": 0,
        }

        final_state = await _graphs["full"].ainvoke(initial_state)
        usage = final_state.get("token_usage") or {}

        generation_id = await storage.save_generation(
            topic=request.topic,
            blog_post=final_state["blog_post"],
            extras=final_state["extras"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=usage.get("cost_usd", 0.0),
        )

        return BlogResponse(
            id=generation_id,
            blog_post=final_state["blog_post"],
            extras=final_state["extras"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=usage.get("cost_usd", 0.0),
        )

    except Exception as e:
        logger.exception("Blog generation failed for topic=%r", request.topic)
        raise HTTPException(status_code=500, detail=f"Blog generation failed: {str(e)}")


@app.post("/outline/start")
async def start_outline(request: OutlineStartRequest):
    thread_id = sessions.new_thread_id()
    config = sessions.thread_config(thread_id)

    initial_state = {
        "topic": request.topic,
        "planner_attempts": 0,
        "writer_attempts": 0,
    }

    return StreamingResponse(
        _run_and_stream(_graphs["review"], initial_state, config, thread_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/outline/feedback")
async def submit_outline_feedback(request: OutlineFeedbackRequest):
    config = sessions.thread_config(request.session_id)

    if not await sessions.has_pending_session(_graphs["review"], request.session_id):
        raise HTTPException(
            status_code=404,
            detail=(
                "No pending outline found for that session — it may "
                "have already been approved, or the session id is "
                "invalid."
            ),
        )

    if not request.approved and (not request.feedback or not request.feedback.strip()):
        raise HTTPException(status_code=400, detail="Feedback is required when rejecting an outline.")

    resume_value = {"approved": request.approved, "feedback": request.feedback}

    return StreamingResponse(
        _run_and_stream(
            _graphs["review"],
            Command(resume=resume_value),
            config,
            request.session_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/blog/feedback")
async def submit_blog_feedback(request: BlogFeedbackRequest):
    config = sessions.thread_config(request.session_id)

    if not await sessions.has_pending_session(_graphs["review"], request.session_id):
        raise HTTPException(
            status_code=404,
            detail=(
                "No pending draft found for that session — it may "
                "have already been approved, or the session id is "
                "invalid."
            ),
        )

    if not request.approved and (not request.feedback or not request.feedback.strip()):
        raise HTTPException(status_code=400, detail="Feedback is required when rejecting a draft blog post.")

    resume_value = {"approved": request.approved, "feedback": request.feedback}

    async def _finalize(cfg):
        snapshot = await _graphs["review"].aget_state(cfg)
        final_state = snapshot.values
        usage = final_state.get("token_usage") or {}

        generation_id = await storage.save_generation(
            topic=final_state["topic"],
            blog_post=final_state["blog_post"],
            extras=final_state["extras"],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=usage.get("cost_usd", 0.0),
        )

        await sessions.delete_session(_graphs["review"], request.session_id)

        return {
            "id": generation_id,
            "blog_post": final_state["blog_post"],
            "extras": final_state["extras"],
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "cost_usd": usage.get("cost_usd", 0.0),
        }

    return StreamingResponse(
        _run_and_stream(
            _graphs["review"],
            Command(resume=resume_value),
            config,
            request.session_id,
            on_complete=_finalize,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/history", response_model=list[HistoryItem])
async def get_history(limit: int = 20):
    return await storage.list_generations(limit=limit)


@app.get("/history/{generation_id}", response_model=HistoryDetail)
async def get_history_item(generation_id: int):
    generation = await storage.get_generation(generation_id)

    if generation is None:
        raise HTTPException(status_code=404, detail=f"No generation found with id {generation_id}")

    return generation


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)