# CustomGPTs

A stealth ChatGPT web scraper that doubles as an **OpenAI-compatible API server**. Uses patchright (stealth Playwright fork) with persistent Chromium profiles to bypass anti-bot detection. Log in once, then use via CLI, Python API, or any OpenAI client.

## Features

- **Stealth browser** — patchright with `--disable-blink-features=AutomationControlled`
- **Persistent session** — log in once, reuse the profile forever
- **Hidden browser** — Win32 window hiding or Xvfb virtual display in Docker
- **OpenAI-compatible API** — `POST /v1/chat/completions` with streaming SSE
- **Conversation continuity** — reuse tabs via `conversation_id`
- **Custom GPT support** — star GPTs with nicknames, set defaults
- **GPT Store search** — find and use any public GPT
- **Image extraction** — downloads DALL-E images from responses

## Docker Deployment (Recommended)

Run as a Docker container with VNC for login and cloudflared tunnel for external access.

### Setup

```bash
docker compose build
docker compose up -d
```

### Login (one time)

1. Open `http://localhost:6080` in your browser (noVNC)
2. You'll see Chromium on the virtual desktop — log in to ChatGPT
3. Close the VNC tab. The session persists in a Docker volume.

### Test

```bash
curl http://localhost:5124/health
curl http://localhost:5124/v1/models
```

### Configuration

Environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `VNC_PASSWORD` | (none) | Optional password for VNC access |
| `DISPLAY_WIDTH` | 1280 | Virtual display width |
| `DISPLAY_HEIGHT` | 720 | Virtual display height |

The cloudflared tunnel config is at `docker/cloudflared.yml`. Tunnel credentials are mounted from the `capi_multi` project.

### Ports

| Port | Service |
|------|---------|
| 5124 | API server |
| 6080 | noVNC web interface |

## Local Install (Alternative)

```bash
pip install .
patchright install chromium
```

### Login (one time)

```bash
customgpts login
```

A browser window opens. Log in to ChatGPT, then close the window.

### 2. Ask a question

```bash
customgpts ask "What is the capital of France?"
```

### 3. Interactive chat

```bash
customgpts chat
```

### 4. Use a custom GPT

```bash
# By raw ID
customgpts ask "Analyze this" --gpt g-XXXXX

# Or star it with a nickname first
customgpts star g-XXXXX teacher
customgpts ask "Explain calculus" --gpt teacher

# Set a default GPT
customgpts default teacher
customgpts ask "Explain calculus"  # uses teacher automatically
```

## API Server

Start an OpenAI-compatible server:

```bash
customgpts serve
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

The `model` field maps to GPT nicknames from `customgpts star`:

```bash
customgpts star g-XXXXX teacher
curl -X POST http://localhost:5124/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "teacher", "messages": [{"role": "user", "content": "Explain gravity"}]}'
```

## Python API

```python
import asyncio
from customgpts import CustomGPTs

async def main():
    async with CustomGPTs() as client:
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
customgpts login                    # Open browser for manual login
customgpts ask "prompt"             # Send prompt, print response
customgpts chat                     # Interactive chat session
customgpts serve                    # Start OpenAI-compatible API server
customgpts gpts                     # List available GPTs from your account
customgpts search "query"           # Search the GPT Store
customgpts star <id> <nickname>     # Save a GPT with a nickname
customgpts unstar <nickname>        # Remove a saved nickname
customgpts default <nickname>       # Set default GPT
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

1. **BrowserManager** launches Chromium once at server startup with a persistent profile at `~/.customgpts/profile/`. On Windows, Win32 API hides the window. In Docker, Xvfb provides a virtual display.
2. **ChatGPTDriver** navigates to ChatGPT, inputs prompts (clipboard paste when hidden, keyboard when visible), clicks send
3. **Request serialization** — ChatGPT only generates one response at a time, so requests are queued via `asyncio.Semaphore(1)`
4. **DOM polling** detects response completion via Copy/Read aloud buttons on the last `<article>`, with a message count guard against transient DOM elements
5. **Streaming** polls `inner_text()` every 0.3s and yields text deltas as SSE chunks
6. **Selectors** are centralized in `selectors.py` with fallback arrays for resilience

## License

MIT
