from dotenv import load_dotenv
from langchain_openrouter import ChatOpenRouter

from .config import get_settings
from .schemas import Validation

load_dotenv()

settings = get_settings()

_base_llm = ChatOpenRouter(
    model=settings.openrouter_model,
    api_key=settings.openrouter_api_key,
    temperature=0.7,
    max_tokens=4096,
)

llm = _base_llm.with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)

# include_raw=True keeps the underlying AIMessage (and its usage_metadata)
# alongside the parsed Validation object, so nodes.py can still report token
# usage for validator calls instead of only for planner/writer/extras.
validator_llm = _base_llm.with_structured_output(Validation, include_raw=True).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)