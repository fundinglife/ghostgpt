# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GhostGPT is a stealth ChatGPT web scraper CLI tool and Python library. It uses patchright (a stealth Playwright fork) with persistent Chromium profiles to bypass anti-bot detection. Users log in manually once; subsequent interactions reuse the saved session.

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
ghostgpt ask "prompt" --gpt g-XXXXX   # Use a custom GPT
ghostgpt ask "prompt" --verbose  # Enable debug logging
ghostgpt ask "prompt" --no-headless    # Show browser window
```

## Architecture

The codebase is ~350 lines across 6 modules in `src/ghostgpt/` using a src-layout:

- **cli.py** — Typer CLI app with `login` and `ask` commands. Wraps async calls with `asyncio.run()`.
- **client.py** — `GhostGPT` class, the public API. Async context manager that composes `BrowserManager` + `ChatGPTDriver`.
- **browser.py** — `BrowserManager` wraps patchright to launch persistent Chromium contexts. Default profile: `~/.ghostgpt/profile/`. Uses `--disable-blink-features=AutomationControlled` for stealth.
- **driver.py** — `ChatGPTDriver` handles all ChatGPT DOM interaction: navigation, prompt input, send, and response extraction. Polls for the stop button disappearing to detect response completion. Largest module.
- **selectors.py** — Centralized CSS selectors with fallback arrays for robustness against ChatGPT UI changes. When ChatGPT's UI changes break the scraper, update selectors here first.

## Key Design Patterns

- **Fully async**: All browser interaction uses async/await. CLI bridges with `asyncio.run()`.
- **Fallback selectors**: Each DOM element has a primary selector and a fallback list (e.g., `PROMPT_FALLBACKS`, `SEND_BUTTON_FALLBACKS`). The driver tries each in order.
- **Response detection**: Polls DOM — waits for stop button to appear (streaming started), then waits for it to disappear and send button to reappear (response complete).
- **Persistent profiles**: Browser sessions persist via patchright's `user_data_dir`, avoiding re-authentication.

## Testing

No test infrastructure exists yet. No `tests/` directory, pytest config, or CI pipeline.

## Dependencies

Python >=3.10. Key deps: `patchright` (browser automation), `typer[all]` (CLI), `loguru` (logging), `httpx` (HTTP client).
