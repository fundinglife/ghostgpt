# GhostGPT 👻

A stealth ChatGPT web scraper using `patchright` + persistent Chromium profiles. Bypasses anti-bot detections by using a real browser session that you log into manually.

## Features

- **Stealthy**: Uses `patchright`, a stealth Playwright fork.
- **Persistent Session**: No need to automate login or fight Cloudflare. Log in once, stay logged in.
- **Headless**: Runs in the background after the initial login.
- **Custom GPT Support**: Works with standard ChatGPT and custom GPT URLs.
- **Simple Python API**: Clean async API for integration into other projects.

## Installation

```bash
# Clone the repository
git clone https://github.com/youruser/ghostgpt.git
cd ghostgpt

# Install dependencies
pip install .

# Install patchright browsers
patchright install chromium
```

## Quick Start

### 1. Login
First, you need to log in manually to save the session to your profile.
```bash
ghostgpt login
```
A browser window will open. Log in to ChatGPT and then close the browser window.

### 2. Ask a question
```bash
ghostgpt ask "What is the capital of France?"
```

### 3. Use a custom GPT
```bash
ghostgpt ask "Analyze this" --gpt g-XXXXX
```

## Python API

```python
import asyncio
from ghostgpt import GhostGPT

async def main():
    async with GhostGPT() as client:
        answer = await client.ask("Hello, ChatGPT!")
        print(answer)

if __name__ == "__main__":
    asyncio.run(main())
```

## How It Works

1. **Browser Manager**: Launches Chromium with a persistent context in `~/.ghostgpt/profile/`.
2. **ChatGPT Driver**: Navigates to ChatGPT, types into the prompt textarea, and clicks send.
3. **Response Detection**: Polls the DOM for the "Stop generating" button. Once it disappears and the send button is re-enabled, the response is extracted from the last assistant message.
4. **Selectors**: All CSS selectors are centralized in `selectors.py` for easy updates.

## License
MIT
