"""Pydantic models for Local Responses API.

Contains request/response schemas and message model.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Represents a chat message.

    role: one of system, user, assistant, tool
    content: raw content string or serialized text
    name: optional tool or speaker name
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = Field(default=None)


class CreateResponseRequest(BaseModel):
    """Request to create a response from user input.

    - thread_id: optional explicit thread
    - previous_response_id: optional to infer thread from a previous response
    - store: whether to persist messages/response
    - input_text: user prompt
    """

    thread_id: Optional[str] = Field(default=None)
    previous_response_id: Optional[str] = Field(default=None)
    store: bool = Field(default=True)
    input_text: str


class CreateResponseResult(BaseModel):
    """Result of creating a response."""

    response_id: str
    thread_id: str
    output_text: str
    status: Literal["completed", "error"]
    usage: Dict[str, Any]


# Backward-compatibility models used elsewhere in the codebase
class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# Aliases for existing imports
ResponseRequest = CreateResponseRequest
ResponsePayload = CreateResponseResult
