"""
CustomGPTs — A stealth ChatGPT web scraper and OpenAI-compatible API server.

Uses patchright (stealth Playwright fork) with persistent Chromium profiles to
bypass anti-bot detection. Log in once, then interact via CLI, Python API, or
any OpenAI client library.

Public API:
    from customgpts import CustomGPTs

    async with CustomGPTs() as client:
        answer = await client.ask("Hello!")
"""

from .client import CustomGPTs

__all__ = ["CustomGPTs"]
