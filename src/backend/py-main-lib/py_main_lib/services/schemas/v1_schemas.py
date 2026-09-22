"""ModelFamily Schema."""

from typing import Any

from pydantic import BaseModel, Field


class MessagesV1(BaseModel):
    """MessagesV1"""

    INFO: list = Field(default_factory=list)
    WARNING: list = Field(default_factory=list)
    ERROR: list = Field(default_factory=list)


class SuccessfulResponseV1(BaseModel):
    messages: MessagesV1 = Field(default_factory=MessagesV1)
    payload: Any


class ErrorResponseV1(BaseModel):
    messages: MessagesV1
    payload: None = None
