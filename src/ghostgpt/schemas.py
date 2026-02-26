"""OpenAI-compatible request/response models."""
from typing import Optional
from pydantic import BaseModel


# ── Request ──────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "chatgpt"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    conversation_id: Optional[str] = None


# ── Response (non-streaming) ─────────────────────────────────────────

class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo = UsageInfo()
    conversation_id: Optional[str] = None


# ── Response (streaming) ─────────────────────────────────────────────

class DeltaContent(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaContent
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]
    conversation_id: Optional[str] = None


# ── Models list ──────────────────────────────────────────────────────

class ModelObject(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "ghostgpt"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelObject]
