# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GhostGPT is a stealth ChatGPT web scraper that works as a CLI tool, Python library, and OpenAI-compatible API server. It uses patchright (a stealth Playwright fork) with persistent Chromium profiles to bypass anti-bot detection. Users log in manually once; subsequent interactions reuse the saved session.

## Build & Install

```bash
pip install .                    # Install package
pip install -e .                 # Install in editable/dev mode
patchright install chromium      # Required: install browser
```

## CLI Usage

```bash
ghostgpt login                   # Open browser for manual ChatGPT login
ghostgpt ask "prompt"            # Send prompt, print response
ghostgpt ask "prompt" --gpt teacher  # Use a saved GPT nickname
ghostgpt chat                    # Interactive multi-turn chat
ghostgpt serve                   # Start OpenAI-compatible API server (port 5124)
ghostgpt gpts                    # List available GPTs
ghostgpt search "query"          # Search GPT Store
ghostgpt star <id> <nickname>    # Save GPT with nickname
ghostgpt default <nickname>      # Set default GPT
```

## Architecture

Modules in `src/ghostgpt/` using a src-layout:

- **cli.py** — Typer CLI app with all commands. Wraps async calls with `asyncio.run()`.
- **client.py** — `GhostGPT` class, the public API. Async context manager composing `BrowserManager` + `ChatGPTDriver`.
- **browser.py** — `BrowserManager` wraps patchright to launch persistent Chromium contexts. Default profile: `~/.ghostgpt/profile/`. Win32 API hides browser window and removes from taskbar.
- **driver.py** — `ChatGPTDriver` handles all ChatGPT DOM interaction: navigation, prompt input, send, response extraction, streaming. Largest module.
- **selectors.py** — Centralized CSS selectors with fallback arrays. When ChatGPT UI changes break the scraper, update selectors here first.
- **config.py** — GPT nickname management. Config at `~/.ghostgpt/config.json`.
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
- **Win32 window hiding**: `ShowWindow(SW_HIDE)` + `WS_EX_TOOLWINDOW` to hide browser from user, taskbar, and Alt+Tab.
- **Persistent profiles**: Browser sessions persist via patchright's `user_data_dir`.

## Deployment

- API server: `ghostgpt serve` on port 5124
- Auto-start: `start_hidden.vbs` in Windows Startup folder
- External access: cloudflared tunnel at `ghostgpt.rohitsoni.com`
- Tunnel config: `C:\_projects_\cliproxy\cloudflared-config.yml`

## Dependencies

Python >=3.10. Key deps: `patchright` (browser automation), `typer[all]` (CLI), `loguru` (logging), `starlette` + `uvicorn` (API server), `sse-starlette` (streaming), `pydantic` (schemas).
