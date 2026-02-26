# GhostGPT

A stealth ChatGPT web scraper that doubles as an **OpenAI-compatible API server**. Uses patchright (stealth Playwright fork) with persistent Chromium profiles to bypass anti-bot detection. Log in once, then use via CLI, Python API, or any OpenAI client.

## Features

- **Stealth browser** — patchright with `--disable-blink-features=AutomationControlled`
- **Persistent session** — log in once, reuse the profile forever
- **Hidden browser** — Win32 `ShowWindow(SW_HIDE)` hides from taskbar and Alt+Tab
- **OpenAI-compatible API** — `POST /v1/chat/completions` with streaming SSE
- **Conversation continuity** — reuse tabs via `conversation_id`
- **Custom GPT support** — star GPTs with nicknames, set defaults
- **GPT Store search** — find and use any public GPT
- **Image extraction** — downloads DALL-E images from responses

## Install

```bash
pip install .
patchright install chromium
```

## Quick Start

### 1. Login (one time)

```bash
ghostgpt login
```

A browser window opens. Log in to ChatGPT, then close the window.

### 2. Ask a question

```bash
ghostgpt ask "What is the capital of France?"
```

### 3. Interactive chat

```bash
ghostgpt chat
```

### 4. Use a custom GPT

```bash
# By raw ID
ghostgpt ask "Analyze this" --gpt g-XXXXX

# Or star it with a nickname first
ghostgpt star g-XXXXX teacher
ghostgpt ask "Explain calculus" --gpt teacher

# Set a default GPT
ghostgpt default teacher
ghostgpt ask "Explain calculus"  # uses teacher automatically
```

## API Server

Start an OpenAI-compatible server:

```bash
ghostgpt serve
```

Server runs on `http://localhost:5124` with a hidden browser.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | Chat completion (streaming + non-streaming) |
| `GET` | `/v1/models` | List available models (GPT nicknames) |
| `GET` | `/health` | Health check |

### Non-streaming request

```bash
curl -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

### Streaming request

```bash
curl -N -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt",
    "messages": [{"role": "user", "content": "Count to 5"}],
    "stream": true
  }'
```

### Conversation continuity

Send `conversation_id` to reuse the same chat tab:

```bash
# First message — server returns a conversation_id
curl -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt",
    "messages": [{"role": "user", "content": "My name is Alice"}],
    "conversation_id": "my-session-1"
  }'

# Follow-up — same conversation_id reuses the tab
curl -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt",
    "messages": [{"role": "user", "content": "What is my name?"}],
    "conversation_id": "my-session-1"
  }'
```

### Use with OpenAI Python client

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5124/v1", api_key="unused")

response = client.chat.completions.create(
    model="chatgpt",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### Use a custom GPT as a model

The `model` field maps to GPT nicknames from `ghostgpt star`:

```bash
ghostgpt star g-XXXXX teacher
curl -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "teacher", "messages": [{"role": "user", "content": "Explain gravity"}]}'
```

## Python API

```python
import asyncio
from ghostgpt import GhostGPT

async def main():
    async with GhostGPT() as client:
        # Single question
        answer = await client.ask("Hello!")
        print(answer)

        # Multi-turn conversation
        answer1 = await client.ask("My name is Bob")
        answer2 = await client.ask("What's my name?", continue_conversation=True)

        # List available GPTs
        gpts = await client.list_gpts()

        # Search the GPT Store
        results = await client.search_gpts("code review")

asyncio.run(main())
```

## All CLI Commands

```
ghostgpt login                    # Open browser for manual login
ghostgpt ask "prompt"             # Send prompt, print response
ghostgpt chat                     # Interactive chat session
ghostgpt serve                    # Start OpenAI-compatible API server
ghostgpt gpts                     # List available GPTs from your account
ghostgpt search "query"           # Search the GPT Store
ghostgpt star <id> <nickname>     # Save a GPT with a nickname
ghostgpt unstar <nickname>        # Remove a saved nickname
ghostgpt default <nickname>       # Set default GPT
```

### Common flags

```
--gpt <nickname|id>    Use a specific GPT
--visible              Show the browser window
--verbose / -v         Enable debug logging
--port <port>          API server port (default: 5124)
--host <host>          API server host (default: 0.0.0.0)
```

## How It Works

1. **BrowserManager** launches Chromium once at server startup with a persistent profile at `~/.ghostgpt/profile/`
2. **Win32 API** hides the browser window (`ShowWindow(SW_HIDE)` + `WS_EX_TOOLWINDOW`)
3. **ChatGPTDriver** navigates to ChatGPT, inputs prompts (clipboard paste when hidden, keyboard when visible), clicks send
4. **Request serialization** — ChatGPT only generates one response at a time, so requests are queued via `asyncio.Semaphore(1)`
5. **DOM polling** detects response completion via Copy/Read aloud buttons on the last `<article>`, with a message count guard against transient DOM elements
6. **Streaming** polls `inner_text()` every 0.3s and yields text deltas as SSE chunks
7. **Selectors** are centralized in `selectors.py` with fallback arrays for resilience

## License

MIT
