from typing import Optional
from pathlib import Path
from .browser import BrowserManager
from .driver import ChatGPTDriver
from loguru import logger

class GhostGPT:
    def __init__(self, profile_dir: Optional[Path] = None, headless: bool = True):
        self.browser_manager = BrowserManager(profile_dir=profile_dir, headless=headless)
        self.driver: Optional[ChatGPTDriver] = None

    async def __aenter__(self):
        context = await self.browser_manager.start()
        self.driver = ChatGPTDriver(context)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.browser_manager.stop()

    async def ask(self, prompt: str, gpt_id: Optional[str] = None) -> str:
        """
        Sends a prompt and returns the answer.
        This is the main API method.
        """
        if not self.driver:
            # If not using as context manager, start it now
            context = await self.browser_manager.start()
            self.driver = ChatGPTDriver(context)
        
        try:
            return await self.driver.send_prompt(prompt, gpt_id=gpt_id)
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
