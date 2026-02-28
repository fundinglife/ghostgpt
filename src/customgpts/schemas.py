"""
OpenAI-compatible request/response Pydantic models.

Defines the data models used by the API server to accept requests and return
responses in a format compatible with the OpenAI Python client library. This
allows any application using `openai.ChatCompletion.create()` to work with
CustomGPTs by simply pointing the base_url to this server.

Models are organized into:
  - Request models: ChatMessage, ChatCompletionRequest
  - Non-streaming response: ChatCompletionResponse, ChatCompletionChoice, UsageInfo
  - Streaming response: ChatCompletionChunk, StreamChoice, DeltaContent
  - Model listing: ModelObject, ModelListResponse
"""

from typing import Optional
from pydantic import BaseModel


# ── Request ──────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    """A single message in a chat conversation.

    Attributes:
        role: The message author's role ("system", "user", or "assistant").
        content: The text content of the message.
    """
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """Incoming chat completion request (OpenAI-compatible).

    Extends the standard OpenAI format with an optional conversation_id field
    for multi-turn conversation support.

    Attributes:
        model: The model to use. Maps to GPT nicknames (e.g., "chatgpt", "teacher").
        messages: The conversation history as a list of ChatMessage objects.
        stream: Whether to stream the response as SSE events. Defaults to False.
        temperature: Ignored (ChatGPT controls this). Accepted for compatibility.
        max_tokens: Ignored (ChatGPT controls this). Accepted for compatibility.
        top_p: Ignored (ChatGPT controls this). Accepted for compatibility.
        conversation_id: Optional ID to reuse an existing conversation tab.
                         If provided, follow-up messages stay in the same chat thread.
    """
    model: str = "chatgpt"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    conversation_id: Optional[str] = None


# ── Response (non-streaming) ─────────────────────────────────────────

class UsageInfo(BaseModel):
    """Token usage statistics (placeholder — actual usage is unknown via scraping).

    Attributes:
        prompt_tokens: Always 0 (actual count unavailable via web scraping).
        completion_tokens: Always 0 (actual count unavailable via web scraping).
        total_tokens: Always 0 (actual count unavailable via web scraping).
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(BaseModel):
    """A single completion choice in a non-streaming response.

    Attributes:
        index: The index of this choice in the choices array. Always 0 (single choice).
        message: The assistant's response message.
        finish_reason: Why the response ended. Always "stop" for complete responses.
    """
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    """Complete non-streaming chat completion response (OpenAI-compatible).

    Attributes:
        id: Unique identifier for this completion (e.g., "chatcmpl-abc123").
        object: Always "chat.completion" per OpenAI spec.
        created: Unix timestamp of when the completion was created.
        model: The model that generated the response.
        choices: List of completion choices (always contains exactly one).
        usage: Token usage statistics (placeholder values).
        conversation_id: The conversation ID for follow-up messages.
    """
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo = UsageInfo()
    conversation_id: Optional[str] = None


# ── Response (streaming) ─────────────────────────────────────────────

class DeltaContent(BaseModel):
    """A content delta for streaming responses.

    Each streaming chunk contains a delta with either a role announcement or
    new content text. Both fields are optional because each chunk only contains
    one type of update.

    Attributes:
        role: The assistant role (sent only in the first chunk).
        content: New text content since the last chunk (sent in subsequent chunks).
    """
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChoice(BaseModel):
    """A single choice in a streaming response chunk.

    Attributes:
        index: The index of this choice. Always 0 (single choice).
        delta: The content delta for this chunk.
        finish_reason: Set to "stop" in the final chunk, None otherwise.
    """
    index: int = 0
    delta: DeltaContent
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """A single streaming chunk in SSE format (OpenAI-compatible).

    Sent as the data field of an SSE event. Multiple chunks are sent during
    streaming, each containing a delta with new content.

    Attributes:
        id: Same completion ID across all chunks in a single response.
        object: Always "chat.completion.chunk" per OpenAI spec.
        created: Unix timestamp of when the completion started.
        model: The model that generated the response.
        choices: List of stream choices (always contains exactly one).
        conversation_id: The conversation ID for follow-up messages.
    """
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]
    conversation_id: Optional[str] = None


# ── Models list ──────────────────────────────────────────────────────

class ModelObject(BaseModel):
    """A single model entry in the models list response.

    Attributes:
        id: The model identifier (e.g., "chatgpt", "teacher").
        object: Always "model" per OpenAI spec.
        owned_by: Always "customgpts" to identify this server.
    """
    id: str
    object: str = "model"
    owned_by: str = "customgpts"


class ModelListResponse(BaseModel):
    """Response for the GET /v1/models endpoint.

    Attributes:
        object: Always "list" per OpenAI spec.
        data: List of available model objects.
    """
    object: str = "list"
    data: list[ModelObject]
