from typing import Literal

from pydantic import BaseModel, Field


class Validation(BaseModel):
    status: Literal["OK", "RETRY"]
    reason: str | None = Field(default=None)