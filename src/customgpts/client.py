"""
Public Python API for CustomGPTs.

Provides the CustomGPTs class — an async context manager that composes BrowserManager
(browser lifecycle) and ChatGPTDriver (DOM interaction) into a simple interface for
sending prompts to ChatGPT and receiving responses.

Usage as context manager (recommended):
    async with CustomGPTs() as client:
        answer = await client.ask("What is the capital of France?")
        print(answer)

Usage without context manager:
    client = CustomGPTs()
    answer = await client.ask("Hello!")
    await client.close()
"""

from typing import Optional
from pathlib import Path
from .browser import BrowserManager
from .driver import ChatGPTDriver
from loguru import logger


class CustomGPTs:
    """High-level async client for interacting with ChatGPT via browser automation.

    Wraps BrowserManager (launches/hides Chromium) and ChatGPTDriver (navigates ChatGPT,
    sends prompts, extracts responses) into a single interface. Supports single questions,
    multi-turn conversations, GPT Store search, and custom GPT usage.

    Attributes:
        browser_manager (BrowserManager): Manages the Chromium browser lifecycle.
        driver (ChatGPTDriver | None): The DOM interaction driver, created after start.

    Example:
        async with CustomGPTs(visible=True) as client:
            answer = await client.ask("Hello!")
            follow_up = await client.ask("Tell me more", continue_conversation=True)
    """

    def __init__(self, profile_dir: Optional[Path] = None, headless: bool = False, visible: bool = False):
        """Initialize the CustomGPTs client.

        Args:
            profile_dir: Path to the Chromium user data directory for persistent sessions.
                         Defaults to ~/.customgpts/profile/ if not specified.
            headless: Whether to run the browser in headless mode (no GUI). Defaults to
                      False because ChatGPT's anti-bot detection blocks headless browsers.
            visible: Whether to show the browser window to the user. When False, the
                     browser is hidden via Win32 API (Windows) or runs on Xvfb (Linux/Docker).
        """
        self.browser_manager = BrowserManager(profile_dir=profile_dir, headless=headless, visible=visible)
        self.driver: Optional[ChatGPTDriver] = None

    async def __aenter__(self):
        """Async context manager entry: start the browser and create the driver.

        Returns:
            CustomGPTs: This client instance, ready for use.
        """
        context = await self.browser_manager.start()
        self.driver = ChatGPTDriver(context)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit: stop the browser and release resources."""
        await self.browser_manager.stop()

    async def _ensure_driver(self):
        """Lazily initialize the driver if not already started.

        Called internally before each operation to support usage without the
        context manager pattern. If the browser hasn't been started yet,
        this method starts it and creates the ChatGPTDriver.
        """
        if not self.driver:
            context = await self.browser_manager.start()
            self.driver = ChatGPTDriver(context)

    async def list_gpts(self) -> list[dict]:
        """Fetch all available GPTs from the user's ChatGPT account.

        Queries ChatGPT's internal backend API for pinned GPTs and custom-built GPTs.

        Returns:
            list[dict]: A list of GPT objects, each containing:
                - id (str): The GPT identifier (e.g., "g-XXXXX").
                - name (str): The display name of the GPT.
                - type (str): Either "pinned" or "custom".
        """
        await self._ensure_driver()
        return await self.driver.list_gpts()

    async def search_gpts(self, query: str, limit: int = 20) -> list[dict]:
        """Search the GPT Store for public GPTs by keyword.

        Args:
            query: The search keyword (e.g., "code review", "image generator").
            limit: Maximum number of results to return. Defaults to 20.

        Returns:
            list[dict]: A list of GPT objects, each containing:
                - id (str): The GPT identifier.
                - name (str): The display name.
                - description (str): Brief description (truncated to 100 chars).
                - author (str): The GPT author's display name.
        """
        await self._ensure_driver()
        return await self.driver.search_gpts(query, limit=limit)

    async def ask(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False) -> str:
        """Send a prompt to ChatGPT and return the full response text.

        Args:
            prompt: The user message to send to ChatGPT.
            gpt_id: Optional GPT identifier to use a specific custom GPT (e.g., "g-XXXXX").
                    If None, uses the default ChatGPT model.
            continue_conversation: If True, continue in the same chat thread as the
                                   previous message. If False, starts a new conversation.

        Returns:
            str: The assistant's response text. May include image download paths if the
                 response contained DALL-E generated images.
        """
        await self._ensure_driver()

        try:
            return await self.driver.send_prompt(prompt, gpt_id=gpt_id, continue_conversation=continue_conversation)
        except Exception as e:
            logger.error(f"Error during ask: {e}")
            return f"Error: {str(e)}"

    async def close(self):
        """Manually close the browser and release resources.

        Use this when not using the async context manager pattern. After calling
        close(), the client cannot be used again without re-initialization.
        """
        await self.browser_manager.stop()
        self.driver = None
