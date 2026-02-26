from typing import Optional
from pathlib import Path
from .browser import BrowserManager
from .driver import ChatGPTDriver
from loguru import logger

class GhostGPT:
    def __init__(self, profile_dir: Optional[Path] = None, headless: bool = False, visible: bool = False):
        self.browser_manager = BrowserManager(profile_dir=profile_dir, headless=headless, visible=visible)
        self.driver: Optional[ChatGPTDriver] = None

    async def __aenter__(self):
        context = await self.browser_manager.start()
        self.driver = ChatGPTDriver(context)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.browser_manager.stop()

    async def _ensure_driver(self):
        if not self.driver:
            context = await self.browser_manager.start()
            self.driver = ChatGPTDriver(context)

    async def list_gpts(self) -> list[dict]:
        """Fetch all available GPTs from the ChatGPT account."""
        await self._ensure_driver()
        return await self.driver.list_gpts()

    async def search_gpts(self, query: str, limit: int = 20) -> list[dict]:
        """Search the GPT Store for any public GPT by keyword."""
        await self._ensure_driver()
        return await self.driver.search_gpts(query, limit=limit)

    async def ask(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False) -> str:
        """
        Sends a prompt and returns the answer.
        Set continue_conversation=True to stay in the same chat thread.
        """
        await self._ensure_driver()

        try:
            return await self.driver.send_prompt(prompt, gpt_id=gpt_id, continue_conversation=continue_conversation)
        except Exception as e:
            logger.error(f"Error during ask: {e}")
            return f"Error: {str(e)}"
        finally:
            # If we started it manually here (not context manager), should we stop it?
            # User might want to keep it warm. For now, let's keep it open if it was opened here.
            pass

    async def close(self):
        """Closes the browser."""
        await self.browser_manager.stop()
        self.driver = None
