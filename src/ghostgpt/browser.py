from pathlib import Path
from patchright.async_api import async_playwright, BrowserContext
from loguru import logger


DEFAULT_PROFILE_DIR = Path.home() / ".ghostgpt" / "profile"

class BrowserManager:
    def __init__(self, profile_dir: Path = None, headless: bool = True):
        self.profile_dir = profile_dir or DEFAULT_PROFILE_DIR
        self.headless = headless
        self._patchright = None
        self._browser_context: BrowserContext = None

        # Ensure profile directory exists
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def start(self) -> BrowserContext:
        """Launches Chromium with a persistent context."""
        logger.info(f"Launching browser with profile: {self.profile_dir} (headless={self.headless})")
        
        self._patchright = await async_playwright().start()
        self._browser_context = await self._patchright.chromium.launch_persistent_context(

            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
            no_viewport=True,
        )
        return self._browser_context

    async def stop(self):
        """Stops the browser and patchright."""
        if self._browser_context:
            await self._browser_context.close()
        if self._patchright:
            await self._patchright.stop()
        logger.info("Browser stopped.")

    @property
    def context(self) -> BrowserContext:
        return self._browser_context
