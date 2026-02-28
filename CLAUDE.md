# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CustomGPTs is a stealth ChatGPT web scraper that works as a CLI tool, Python library, and OpenAI-compatible API server. It uses patchright (a stealth Playwright fork) with persistent Chromium profiles to bypass anti-bot detection. Users log in manually once; subsequent interactions reuse the saved session.

## Build & Install

```bash
pip install .                    # Install package
pip install -e .                 # Install in editable/dev mode
patchright install chromium      # Required: install browser
```

## CLI Usage

```bash
customgpts login                   # Open browser for manual ChatGPT login
customgpts ask "prompt"            # Send prompt, print response
customgpts ask "prompt" --gpt teacher  # Use a saved GPT nickname
customgpts chat                    # Interactive multi-turn chat
customgpts serve                   # Start OpenAI-compatible API server (port 5124)
customgpts gpts                    # List available GPTs
customgpts search "query"          # Search GPT Store
customgpts star <id> <nickname>    # Save GPT with nickname
customgpts default <nickname>      # Set default GPT
```

## Architecture

Modules in `src/customgpts/` using a src-layout:

- **cli.py** — Typer CLI app with all commands. Wraps async calls with `asyncio.run()`.
- **client.py** — `CustomGPTs` class, the public API. Async context manager composing `BrowserManager` + `ChatGPTDriver`.
- **browser.py** — `BrowserManager` wraps patchright to launch persistent Chromium contexts. Default profile: `~/.customgpts/profile/`. Win32 API hides browser window on Windows; Xvfb provides virtual display in Docker.
- **driver.py** — `ChatGPTDriver` handles all ChatGPT DOM interaction: navigation, prompt input, send, response extraction, streaming. Largest module.
- **selectors.py** — Centralized CSS selectors with fallback arrays. When ChatGPT UI changes break the scraper, update selectors here first.
- **config.py** — GPT nickname management. Config at `~/.customgpts/config.json`.
- **schemas.py** — Pydantic models for OpenAI-compatible request/response format.
- **server.py** — Starlette API server with `/v1/chat/completions`, `/v1/models`, `/health`.

## Key Design Patterns

- **Fully async**: All browser interaction uses async/await. CLI bridges with `asyncio.run()`.
- **Fallback selectors**: Each DOM element has a fallback list (e.g., `PROMPT_FALLBACKS`). The driver tries each in order.
- **DOM completion detection**: Counts assistant messages before/after sending. Waits for completion indicators (Copy/Read aloud buttons) on the last message's parent `<article>`. Includes a message count guard — if count drops back (transient DOM elements from GPT actions), keeps waiting instead of false-detecting on an old message.
- **Streaming via DOM polling**: `send_prompt_streaming()` polls `inner_text()` every 0.3s, yields text deltas.
- **Request serialization**: `asyncio.Semaphore(1)` in server.py — ChatGPT only generates one response at a time per account.
- **Browser at startup**: Browser launches once via Starlette `on_startup` event, not lazily per-request.
- **Input method switching**: `keyboard.type()` when browser is visible; clipboard paste (`navigator.clipboard.writeText` + Ctrl+V) when hidden. Clipboard paste is more reliable for hidden browsers.
- **One tab per request**: API server opens a new tab for each request. Tabs with `conversation_id` stay open for follow-ups; others close after response.
- **Window hiding**: On Windows, `ShowWindow(SW_HIDE)` + `WS_EX_TOOLWINDOW` hides browser from taskbar/Alt+Tab. PID-based watcher ensures only patchright windows are hidden. On Linux/Docker, Xvfb provides a virtual display instead.
- **Persistent profiles**: Browser sessions persist via patchright's `user_data_dir`.

## Deployment

- **Docker (primary)**: `docker compose up -d` runs API server, Xvfb, noVNC, and cloudflared in a single container
- **Ports**: 5124 (API), 6080 (noVNC for login/debug)
- **VNC login**: Open `http://localhost:6080` to log in to ChatGPT via browser
- **Tunnel**: cloudflared inside container, config at `docker/cloudflared.yml`, creds mounted from `../capi_multi/`
- **External access**: `customgpts.rohitsoni.com`
- **Data persistence**: Bind mount `./.customgpts` -> `/root/.customgpts` (profile, config, images). Survives `docker compose down -v`.

### Docker files

- `Dockerfile` — Multi-stage build: Python 3.12-slim + Chromium deps + Xvfb + noVNC + cloudflared
- `docker-compose.yml` — Single service, 2g shm_size, named volume, port mappings
- `docker/entrypoint.sh` — Directory setup, optional VNC password, launches supervisord
- `docker/supervisord.conf` — Process manager: Xvfb → x11vnc → noVNC → customgpts serve → cloudflared
- `docker/cloudflared.yml` — Tunnel config for `customgpts.rohitsoni.com`

## Dependencies

Python >=3.10. Key deps: `patchright` (browser automation), `typer[all]` (CLI), `loguru` (logging), `starlette` + `uvicorn` (API server), `sse-starlette` (streaming), `pydantic` (schemas).
