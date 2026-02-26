import asyncio
from typing import Optional
from patchright.async_api import BrowserContext, Page
from loguru import logger
from .selectors import (
    PROMPT_FALLBACKS,
    SEND_BUTTON_FALLBACKS,
    STOP_BUTTON, STOP_BUTTON_FALLBACKS,
    ASSISTANT_FALLBACKS,
    COMPLETION_INDICATORS,
    THINKING_INDICATORS,
    ONBOARDING_BUTTONS,
    ONBOARDING_LOCALSTORAGE_BYPASS,
    LOGIN_INDICATORS,
    BASE_URL,
)

MAX_RESPONSE_WAIT = 120  # seconds


class ChatGPTDriver:
    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Optional[Page] = None

    async def _wait_for_cloudflare(self):
        """Wait for Cloudflare challenge to resolve (up to 30s)."""
        for i in range(30):
            title = await self.page.title()
            if "just a moment" not in title.lower():
                return
            logger.info(f"Cloudflare challenge detected, waiting... ({i+1}s)")
            await asyncio.sleep(1)
        raise Exception(
            "Stuck on Cloudflare challenge. Try 'ghostgpt ask --no-headless' or run 'ghostgpt login' first."
        )

    async def _ensure_page(self, gpt_id: Optional[str] = None):
        """Ensures the page is navigated to the correct URL."""
        if not self.page:
            self.page = await self.context.new_page()

        target_url = f"{BASE_URL}/g/{gpt_id}" if gpt_id else BASE_URL

        if self.page.url != target_url:
            logger.info(f"Navigating to {target_url}")
            await self.page.goto(target_url, wait_until="load", timeout=60000)

            # Handle Cloudflare challenge if present
            await self._wait_for_cloudflare()

            # Bypass onboarding via localStorage
            try:
                for key, value in ONBOARDING_LOCALSTORAGE_BYPASS.items():
                    await self.page.evaluate(
                        f"window.localStorage.setItem('{key}', '{value}')"
                    )
            except Exception:
                pass

            # Dismiss any onboarding modals
            for btn in ONBOARDING_BUTTONS:
                try:
                    if await self.page.is_visible(btn, timeout=800):
                        logger.info(f"Dismissing onboarding: {btn}")
                        await self.page.click(btn)
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Check for login page
            for indicator in LOGIN_INDICATORS:
                try:
                    if await self.page.is_visible(indicator, timeout=1000):
                        raise Exception(
                            "User appears to be logged out. Run 'ghostgpt login' first."
                        )
                except Exception as e:
                    if "logged out" in str(e):
                        raise
                    pass

            # Wait for prompt area
            found = False
            for selector in PROMPT_FALLBACKS:
                try:
                    logger.info(f"Looking for prompt: {selector}")
                    await self.page.wait_for_selector(
                        selector, timeout=3000, state="visible"
                    )
                    found = True
                    logger.info(f"Found prompt textarea: {selector}")
                    break
                except Exception:
                    continue

            if not found:
                raise Exception("Timed out waiting for prompt textarea.")

    async def _find_visible(self, selectors: list[str]) -> Optional[str]:
        """Return the first visible selector from a list, or None."""
        for s in selectors:
            try:
                if await self.page.is_visible(s):
                    return s
            except Exception:
                continue
        return None

    async def _is_response_complete(self) -> bool:
        """Check whether the assistant has finished generating."""
        # 1. Stop button gone?
        for s in STOP_BUTTON_FALLBACKS:
            try:
                if await self.page.is_visible(s):
                    return False
            except Exception:
                pass

        # 2. Thinking indicator still present?
        for s in THINKING_INDICATORS:
            try:
                if await self.page.is_visible(s):
                    return False
            except Exception:
                pass

        # 3. Completion action buttons appeared? (Copy, Read aloud, etc.)
        for s in COMPLETION_INDICATORS:
            try:
                if await self.page.is_visible(s):
                    return True
            except Exception:
                pass

        # 4. Send button re-enabled as final fallback
        send = await self._find_visible(SEND_BUTTON_FALLBACKS)
        if send:
            try:
                if await self.page.is_enabled(send):
                    return True
            except Exception:
                pass

        return False

    async def send_prompt(self, prompt: str, gpt_id: Optional[str] = None) -> str:
        """Sends a prompt and returns the assistant's response."""
        await self._ensure_page(gpt_id)

        # Find the prompt input
        prompt_selector = await self._find_visible(PROMPT_FALLBACKS)
        if not prompt_selector:
            raise Exception("Prompt box not visible.")

        logger.info(f"Typing prompt via {prompt_selector}: {prompt[:50]}...")

        # Type the prompt — click first, then type (works for both textarea and contenteditable)
        await self.page.click(prompt_selector)
        await self.page.keyboard.type(prompt)
        await asyncio.sleep(0.3)  # let send button appear after typing

        # Click send — button only appears after text is entered
        send_selector = await self._find_visible(SEND_BUTTON_FALLBACKS)
        if send_selector:
            logger.info(f"Clicking send button: {send_selector}")
            await self.page.click(send_selector)
        else:
            logger.warning("Send button not found after typing, pressing Enter.")
            await self.page.press(prompt_selector, "Enter")

        # Wait for generation to start (stop button or thinking indicator appears)
        generation_started = False
        try:
            for s in STOP_BUTTON_FALLBACKS + THINKING_INDICATORS:
                try:
                    await self.page.wait_for_selector(s, timeout=5000, state="visible")
                    generation_started = True
                    logger.info(f"Generation started (saw {s})")
                    break
                except Exception:
                    continue
        except Exception:
            pass

        if not generation_started:
            logger.warning("No generation indicator appeared; polling anyway.")

        # Poll for completion
        logger.info("Waiting for response completion...")
        elapsed = 0.0
        while elapsed < MAX_RESPONSE_WAIT:
            if await self._is_response_complete():
                break
            await asyncio.sleep(0.5)
            elapsed += 0.5
        else:
            logger.warning(f"Response wait timed out after {MAX_RESPONSE_WAIT}s")

        # Small buffer for DOM to settle
        await asyncio.sleep(0.3)

        # Extract the last assistant message
        return await self._extract_response()

    async def _extract_response(self) -> str:
        """Extract text from the last assistant message element."""
        logger.info("Extracting assistant message...")
        messages = []
        used_selector = None
        for s in ASSISTANT_FALLBACKS:
            try:
                msgs = await self.page.query_selector_all(s)
                if msgs:
                    messages = msgs
                    used_selector = s
                    logger.info(f"Found {len(msgs)} messages via {s}")
                    break
            except Exception:
                continue

        if not messages:
            return "Error: No assistant message found."

        last_message = messages[-1]

        # Get content as text first, fall back to innerHTML
        content = await last_message.inner_text()
        if not content or not content.strip():
            content = await last_message.inner_html()
            logger.info("inner_text() empty, used inner_html()")

        return content.strip()
