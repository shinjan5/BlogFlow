import uuid


def new_thread_id() -> str:
    return str(uuid.uuid4())


def thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def has_pending_session(graph, thread_id: str) -> bool:
    snapshot = await graph.aget_state(thread_config(thread_id))
    return bool(snapshot.next)


async def delete_session(graph, thread_id: str) -> None:
    checkpointer = getattr(graph, "checkpointer", None)

    if checkpointer is None:
        return

    if hasattr(checkpointer, "adelete_thread"):
        await checkpointer.adelete_thread(thread_id)
    elif hasattr(checkpointer, "delete_thread"):
        checkpointer.delete_thread(thread_id)