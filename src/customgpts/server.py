"""
OpenAI-compatible API server for CustomGPTs.

Provides a Starlette-based HTTP server that exposes ChatGPT via an API compatible
with the OpenAI client library format. This allows any application that uses the
OpenAI SDK to seamlessly use ChatGPT through this server.

Endpoints:
    GET  /health                  — Health check (returns {"status": "ok"})
    GET  /v1/models               — List available models (GPT nicknames from config)
    POST /v1/chat/completions     — Chat completion (supports streaming and non-streaming)

Architecture:
    - The browser is launched ONCE at server startup (via Starlette on_startup event).
    - All requests share the same browser context but get their own page/tab.
    - A semaphore (asyncio.Semaphore(1)) serializes requests because ChatGPT only
      generates one response at a time per account.
    - Conversations are tracked by conversation_id. Tabs with a conversation_id stay
      open for follow-up messages; others are stored for potential reuse.
    - Idle conversations are cleaned up after 30 minutes.

Usage:
    from customgpts.server import app, configure
    import uvicorn

    configure(visible=False)
    uvicorn.run(app, host="0.0.0.0", port=5124)
"""

import asyncio
import time
from uuid import uuid4
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from .browser import BrowserManager
from .driver import ChatGPTDriver
from .config import load_config, resolve_gpt
from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatMessage,
    DeltaContent,
    StreamChoice,
    ModelObject,
    ModelListResponse,
)

# ── Server state (set by configure() before uvicorn starts) ──────────

_browser_manager: Optional[BrowserManager] = None  # Browser lifecycle manager
_context = None  # BrowserContext — launched once at startup, shared by all requests
_visible = False  # Whether the browser window is visible to the user
_request_sem = asyncio.Semaphore(1)  # Serializes requests — ChatGPT only generates one response at a time

# Active conversations: conversation_id -> (ChatGPTDriver, last_used_timestamp)
# Each conversation has its own browser tab managed by a separate ChatGPTDriver instance.
_conversations: dict[str, tuple[ChatGPTDriver, float]] = {}

# Close conversation tabs that have been idle for more than 30 minutes
IDLE_TIMEOUT = 1800


def configure(visible: bool = False):
    """Initialize the server's browser manager before starting uvicorn.

    Must be called before the server starts. Sets up the BrowserManager with the
    desired visibility setting. The browser itself is launched later during the
    Starlette on_startup event.

    Args:
        visible: Whether to show the browser window. Defaults to False (hidden).
    """
    global _browser_manager, _visible
    _visible = visible
    _browser_manager = BrowserManager(headless=False, visible=visible)


async def _startup():
    """Starlette on_startup event handler: launch the browser.

    Called once when the server starts. Launches Chromium with the persistent
    profile and stores the BrowserContext for use by all request handlers.
    """
    global _context
    _context = await _browser_manager.start()
    logger.info("Browser launched and ready")


async def _cleanup_idle():
    """Close conversation tabs that have been idle longer than IDLE_TIMEOUT.

    Called at the start of each chat completion request. Iterates through all
    tracked conversations and closes any whose last activity was more than
    30 minutes ago, freeing browser resources.
    """
    now = time.time()
    to_remove = []
    for conv_id, (driver, last_used) in _conversations.items():
        if now - last_used > IDLE_TIMEOUT:
            to_remove.append(conv_id)
    for conv_id in to_remove:
        driver, _ = _conversations.pop(conv_id)
        try:
            if driver.page:
                await driver.page.close()
        except Exception:
            pass
        logger.info(f"Closed idle conversation: {conv_id}")


def _flatten_messages(messages: list[ChatMessage]) -> str:
    """Extract a single prompt string from an OpenAI-format messages array.

    Combines system messages and extracts the last user message. ChatGPT receives
    a single prompt (not a structured messages array), so this function flattens
    the OpenAI format into a single string.

    Strategy:
      - Collect all system message contents.
      - Take the last user message content.
      - If both exist, join them with double newlines.
      - If only one exists, use that.
      - As a final fallback, use the last message regardless of role.

    Args:
        messages: A list of ChatMessage objects with role and content fields.

    Returns:
        str: The flattened prompt string to send to ChatGPT.
    """
    system_parts = []
    last_user = ""
    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        elif msg.role == "user":
            last_user = msg.content

    if system_parts and last_user:
        return "\n\n".join(system_parts) + "\n\n" + last_user
    return last_user or messages[-1].content


# ── Endpoints ────────────────────────────────────────────────────────

async def health(request: Request) -> JSONResponse:
    """Health check endpoint.

    Args:
        request: The incoming HTTP request (unused).

    Returns:
        JSONResponse: {"status": "ok"} with 200 status.
    """
    return JSONResponse({"status": "ok"})


async def list_models(request: Request) -> JSONResponse:
    """List available models (GPT nicknames from config).

    Always includes "chatgpt" as the base model. Additionally lists any GPT
    nicknames saved via 'customgpts star' as separate model entries.

    Args:
        request: The incoming HTTP request (unused).

    Returns:
        JSONResponse: An OpenAI-compatible model list response with model objects.
    """
    config = load_config()
    models = [ModelObject(id="chatgpt")]

    # Add saved GPT nicknames as models
    for nickname in config.get("gpts", {}):
        models.append(ModelObject(id=nickname))

    return JSONResponse(
        ModelListResponse(data=models).model_dump()
    )


async def chat_completions(request: Request) -> JSONResponse:
    """Handle a chat completion request (OpenAI-compatible).

    Accepts the standard OpenAI chat completion format with an additional optional
    'conversation_id' field for multi-turn conversation support.

    Flow:
      1. Clean up idle conversations.
      2. Parse and validate the request body.
      3. Resolve the model name to a GPT ID (if using a custom GPT).
      4. Flatten the messages array into a single prompt string.
      5. Find or create a ChatGPTDriver for the conversation.
      6. Acquire the request semaphore (serializes all requests).
      7. Delegate to streaming or non-streaming handler.

    Args:
        request: The incoming HTTP POST request with JSON body.

    Returns:
        JSONResponse: An OpenAI-compatible chat completion response, or an
                      EventSourceResponse for streaming requests.
    """
    await _cleanup_idle()

    body = await request.json()
    req = ChatCompletionRequest(**body)

    # Resolve model name to GPT ID (e.g., "teacher" -> "g-XXXXX")
    gpt_id = resolve_gpt(req.model if req.model != "chatgpt" else None)

    # Flatten messages to a single prompt string for ChatGPT
    prompt = _flatten_messages(req.messages)
    if not prompt:
        return _error_response("No user message found in messages array", 400)

    completion_id = f"chatcmpl-{uuid4().hex[:12]}"
    created = int(time.time())

    # Determine if this is a continuing conversation
    conv_id = req.conversation_id
    continue_conv = False
    driver = None

    if conv_id and conv_id in _conversations:
        # Reuse existing conversation tab
        driver, _ = _conversations[conv_id]
        _conversations[conv_id] = (driver, time.time())
        continue_conv = True
        logger.info(f"Reusing conversation: {conv_id}")
    else:
        # Create a new tab for this request
        driver = ChatGPTDriver(_context, visible=_visible)
        if conv_id:
            # Client wants a new conversation with this specific ID
            _conversations[conv_id] = (driver, time.time())
            logger.info(f"New conversation: {conv_id}")
        else:
            # Auto-generate an ID — client can use it for follow-ups
            conv_id = f"conv-{uuid4().hex[:12]}"

    try:
        # ChatGPT only generates one response at a time per account,
        # so we serialize all requests with a semaphore
        async with _request_sem:
            logger.info(f"Processing request: {prompt[:50]}...")
            if req.stream:
                return await _handle_streaming(
                    driver, prompt, gpt_id, continue_conv,
                    completion_id, created, req.model, conv_id,
                    close_tab=(req.conversation_id is None),
                )
            else:
                return await _handle_non_streaming(
                    driver, prompt, gpt_id, continue_conv,
                    completion_id, created, req.model, conv_id,
                    close_tab=(req.conversation_id is None),
                )
    except Exception as e:
        logger.error(f"Request error: {e}")
        return _error_response(str(e), 500)


async def _handle_non_streaming(
    driver, prompt, gpt_id, continue_conv,
    completion_id, created, model, conv_id, close_tab,
) -> JSONResponse:
    """Handle a non-streaming chat completion request.

    Sends the prompt, waits for the full response, then returns it as a single
    JSON response in OpenAI format.

    Args:
        driver: The ChatGPTDriver instance for this conversation.
        prompt: The flattened prompt string.
        gpt_id: The resolved GPT ID, or None for default ChatGPT.
        continue_conv: Whether this is a follow-up in an existing conversation.
        completion_id: Unique ID for this completion (e.g., "chatcmpl-abc123").
        created: Unix timestamp of when the request was received.
        model: The model name from the original request.
        conv_id: The conversation ID for tracking.
        close_tab: Whether to close the tab after the response (False if client
                   provided a conversation_id for reuse).

    Returns:
        JSONResponse: An OpenAI-compatible chat completion response with the
                      x-conversation-id header set.
    """
    answer = await driver.send_prompt(
        prompt, gpt_id=gpt_id, continue_conversation=continue_conv
    )

    if close_tab and driver.page:
        # Store the tab for potential reuse even if client didn't request it
        _conversations[conv_id] = (driver, time.time())

    resp = ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=answer)
            )
        ],
        conversation_id=conv_id,
    )
    return JSONResponse(
        resp.model_dump(),
        headers={"x-conversation-id": conv_id},
    )


async def _handle_streaming(
    driver, prompt, gpt_id, continue_conv,
    completion_id, created, model, conv_id, close_tab,
):
    """Handle a streaming chat completion request via Server-Sent Events (SSE).

    Sends the prompt and streams the response as SSE events in OpenAI chunk format.
    Each chunk contains a delta with new text content.

    SSE event sequence:
      1. First chunk: role="assistant" (identifies the speaker)
      2. Content chunks: delta text as it generates
      3. Final chunk: finish_reason="stop"
      4. [DONE] sentinel

    Args:
        driver: The ChatGPTDriver instance for this conversation.
        prompt: The flattened prompt string.
        gpt_id: The resolved GPT ID, or None for default ChatGPT.
        continue_conv: Whether this is a follow-up in an existing conversation.
        completion_id: Unique ID for this completion.
        created: Unix timestamp of when the request was received.
        model: The model name from the original request.
        conv_id: The conversation ID for tracking.
        close_tab: Whether to close the tab after the response.

    Returns:
        EventSourceResponse: An SSE response that streams chat completion chunks.
    """
    async def event_generator():
        """Async generator that yields SSE events for the streaming response."""
        # First chunk: role announcement
        first = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(role="assistant"))],
            conversation_id=conv_id,
        )
        yield {"data": first.model_dump_json()}

        # Stream content deltas from the DOM polling
        try:
            async for delta_text in driver.send_prompt_streaming(
                prompt, gpt_id=gpt_id, continue_conversation=continue_conv
            ):
                chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=model,
                    choices=[StreamChoice(delta=DeltaContent(content=delta_text))],
                )
                yield {"data": chunk.model_dump_json()}
        except Exception as e:
            logger.error(f"Stream error: {e}")

        # Final chunk with finish_reason="stop"
        final = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(), finish_reason="stop")],
        )
        yield {"data": final.model_dump_json()}
        yield {"data": "[DONE]"}

        # Store conversation for potential reuse
        if close_tab:
            _conversations[conv_id] = (driver, time.time())

    return EventSourceResponse(
        event_generator(),
        headers={"x-conversation-id": conv_id},
    )


def _error_response(message: str, status_code: int = 500) -> JSONResponse:
    """Create an OpenAI-compatible error response.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code. Defaults to 500.

    Returns:
        JSONResponse: An error response in OpenAI format with the error object
                      containing message, type, and code fields.
    """
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": "server_error",
                "code": "internal_error",
            }
        },
        status_code=status_code,
    )


# ── App ──────────────────────────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/v1/models", list_models, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
    ],
    on_startup=[_startup],
)
