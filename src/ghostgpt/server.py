"""OpenAI-compatible API server for GhostGPT."""
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

# ── Server state (set by configure()) before uvicorn starts ──────────

_browser_manager: Optional[BrowserManager] = None
_context = None  # BrowserContext — launched once at startup
_visible = False  # Whether browser window is visible
_request_sem = asyncio.Semaphore(1)  # ChatGPT only generates one response at a time

# conversation_id -> (ChatGPTDriver, last_used_timestamp)
_conversations: dict[str, tuple[ChatGPTDriver, float]] = {}

IDLE_TIMEOUT = 1800  # 30 min — close idle conversation tabs


def configure(visible: bool = False):
    """Set up the browser manager (called before server starts)."""
    global _browser_manager, _visible
    _visible = visible
    _browser_manager = BrowserManager(headless=False, visible=visible)


async def _startup():
    """Launch the browser once at server startup."""
    global _context
    _context = await _browser_manager.start()
    logger.info("Browser launched and ready")


async def _cleanup_idle():
    """Close conversation tabs idle for more than IDLE_TIMEOUT."""
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
    """Extract the prompt from an OpenAI messages array."""
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
    return JSONResponse({"status": "ok"})


async def list_models(request: Request) -> JSONResponse:
    config = load_config()
    models = [ModelObject(id="chatgpt")]

    # Add saved GPT nicknames as models
    for nickname in config.get("gpts", {}):
        models.append(ModelObject(id=nickname))

    return JSONResponse(
        ModelListResponse(data=models).model_dump()
    )


async def chat_completions(request: Request) -> JSONResponse:
    await _cleanup_idle()

    body = await request.json()
    req = ChatCompletionRequest(**body)

    # Resolve model name to GPT ID
    gpt_id = resolve_gpt(req.model if req.model != "chatgpt" else None)

    # Flatten messages to prompt
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
        driver, _ = _conversations[conv_id]
        _conversations[conv_id] = (driver, time.time())
        continue_conv = True
        logger.info(f"Reusing conversation: {conv_id}")
    else:
        # New tab for this request
        driver = ChatGPTDriver(_context, visible=_visible)
        if conv_id:
            # Client wants a new conversation with this ID
            _conversations[conv_id] = (driver, time.time())
            logger.info(f"New conversation: {conv_id}")
        else:
            # Generate an ID — client can use it for follow-ups
            conv_id = f"conv-{uuid4().hex[:12]}"

    try:
        # ChatGPT only generates one response at a time per account,
        # so we serialize requests with a semaphore
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
    answer = await driver.send_prompt(
        prompt, gpt_id=gpt_id, continue_conversation=continue_conv
    )

    if close_tab and driver.page:
        # Keep the tab open so we can store it for potential reuse
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
    async def event_generator():
        # First chunk: role
        first = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(role="assistant"))],
            conversation_id=conv_id,
        )
        yield {"data": first.model_dump_json()}

        # Stream content deltas
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

        # Final chunk with finish_reason
        final = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(), finish_reason="stop")],
        )
        yield {"data": final.model_dump_json()}
        yield {"data": "[DONE]"}

        # Store conversation for reuse
        if close_tab:
            _conversations[conv_id] = (driver, time.time())

    return EventSourceResponse(
        event_generator(),
        headers={"x-conversation-id": conv_id},
    )


def _error_response(message: str, status_code: int = 500) -> JSONResponse:
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
