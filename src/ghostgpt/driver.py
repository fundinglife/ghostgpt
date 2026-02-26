import asyncio
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional
from patchright.async_api import BrowserContext, Page
from loguru import logger
from .selectors import (
    PROMPT_FALLBACKS,
    SEND_BUTTON_FALLBACKS,
    ASSISTANT_FALLBACKS,
    COMPLETION_INDICATORS,
    ONBOARDING_BUTTONS,
    ONBOARDING_LOCALSTORAGE_BYPASS,
    LOGIN_INDICATORS,
    BASE_URL,
    IMAGE_SELECTORS,
    IMAGE_DOWNLOAD_DIR,
)

MAX_RESPONSE_WAIT = 300  # seconds (5 min for thinking models)


class ChatGPTDriver:
    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Optional[Page] = None
        self._in_conversation = False
        self._msg_count = 0

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


    async def list_gpts(self) -> list[dict]:
        """Fetch all available GPTs from the ChatGPT backend API."""
        await self._ensure_page()

        result = await self.page.evaluate('''async () => {
            const sessionResp = await fetch("/api/auth/session", {credentials: "include"});
            if (!sessionResp.ok) return {error: "Failed to get session"};
            const session = await sessionResp.json();
            const token = session.accessToken;
            const headers = {"Authorization": "Bearer " + token};

            const gpts = [];

            // Pinned/store GPTs
            try {
                const resp = await fetch("/backend-api/gizmos/bootstrap", {credentials: "include", headers});
                if (resp.ok) {
                    const data = await resp.json();
                    for (const g of (data.gizmos || [])) {
                        const gizmo = g.resource?.gizmo || g;
                        gpts.push({
                            id: gizmo.id,
                            name: gizmo.display?.name || "Unknown",
                            type: "pinned"
                        });
                    }
                }
            } catch(e) {}

            // Custom-built GPTs (Projects)
            try {
                const resp = await fetch("/backend-api/gizmos/snorlax/sidebar", {credentials: "include", headers});
                if (resp.ok) {
                    const data = await resp.json();
                    for (const item of (data.items || [])) {
                        gpts.push({
                            id: item.gizmo.id,
                            name: item.gizmo.display?.name || "Unknown",
                            type: "custom"
                        });
                    }
                }
            } catch(e) {}

            return gpts;
        }''')

        if isinstance(result, dict) and "error" in result:
            raise Exception(result["error"])

        return result

    async def search_gpts(self, query: str, limit: int = 20) -> list[dict]:
        """Search the GPT Store for any public GPT by keyword."""
        await self._ensure_page()

        result = await self.page.evaluate('''async (args) => {
            const query = args.query;
            const limit = args.limit;

            const sessionResp = await fetch("/api/auth/session", {credentials: "include"});
            if (!sessionResp.ok) return {error: "Failed to get session"};
            const session = await sessionResp.json();
            const token = session.accessToken;
            const headers = {"Authorization": "Bearer " + token};

            const gpts = [];
            let cursor = null;

            while (gpts.length < limit) {
                let url = "/backend-api/gizmos/search?q=" + encodeURIComponent(query);
                if (cursor) url += "&cursor=" + encodeURIComponent(cursor);

                const resp = await fetch(url, {credentials: "include", headers});
                if (!resp.ok) return {error: "Search failed: " + resp.status};
                const data = await resp.json();

                const items = data.hits?.items || data.items || [];
                if (items.length === 0) break;

                for (const item of items) {
                    const gizmo = item.resource?.gizmo || item.gizmo || item;
                    gpts.push({
                        id: gizmo.id || gizmo.short_url || "unknown",
                        name: gizmo.display?.name || "Unknown",
                        description: (gizmo.display?.description || "").slice(0, 100),
                        author: gizmo.author?.display_name || "Unknown",
                    });
                    if (gpts.length >= limit) break;
                }

                cursor = data.hits?.cursor || data.cursor;
                if (!cursor) break;
            }

            return gpts;
        }''', {"query": query, "limit": limit})

        if isinstance(result, dict) and "error" in result:
            raise Exception(result["error"])

        return result

    async def _count_messages(self) -> int:
        """Count current assistant messages in the DOM."""
        for s in ASSISTANT_FALLBACKS:
            try:
                msgs = await self.page.query_selector_all(s)
                if msgs:
                    return len(msgs)
            except Exception:
                continue
        return 0

    async def _wait_for_response(self, prev_count: int):
        """Wait for a NEW assistant message to finish generating."""
        logger.info(f"Waiting for new response (prev messages: {prev_count})...")

        # Phase 1: wait for a new assistant message to appear
        for i in range(60):  # up to 30s for response to start
            await asyncio.sleep(0.5)
            current = await self._count_messages()
            if current > prev_count:
                logger.info(f"New message appeared ({(i+1)*0.5:.0f}s)")
                break
        else:
            logger.warning("No new assistant message appeared")
            return

        # Phase 2: wait for the LAST message to have completion indicators
        for i in range(MAX_RESPONSE_WAIT * 2):  # poll every 0.5s
            await asyncio.sleep(0.5)

            # Get the last assistant message and check for completion buttons inside it
            try:
                for s in ASSISTANT_FALLBACKS:
                    msgs = await self.page.query_selector_all(s)
                    if msgs:
                        last_msg = msgs[-1]
                        # Check for completion buttons within this specific message's parent
                        parent = await last_msg.evaluate_handle("el => el.closest('article') || el.parentElement")
                        for indicator in COMPLETION_INDICATORS:
                            btn = await parent.query_selector(indicator.replace("article ", ""))
                            if btn:
                                logger.info(f"Completion detected ({(i+1)*0.5:.0f}s)")
                                await asyncio.sleep(0.3)
                                return
                        break
            except Exception as e:
                logger.debug(f"Completion check error: {e}")
                continue

        logger.warning(f"Response wait timed out after {MAX_RESPONSE_WAIT}s")

    async def send_prompt(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False) -> str:
        """Sends a prompt and returns the assistant's response."""
        if not (continue_conversation and self._in_conversation):
            await self._ensure_page(gpt_id)

        # Find the prompt input
        prompt_selector = await self._find_visible(PROMPT_FALLBACKS)
        if not prompt_selector:
            raise Exception("Prompt box not visible.")

        logger.info(f"Typing prompt via {prompt_selector}: {prompt[:50]}...")

        # Count existing messages before sending
        prev_count = await self._count_messages()

        # Type the prompt
        await self.page.click(prompt_selector)
        await self.page.keyboard.type(prompt)
        await asyncio.sleep(0.3)

        # Click send
        send_selector = await self._find_visible(SEND_BUTTON_FALLBACKS)
        if send_selector:
            logger.info(f"Clicking send button: {send_selector}")
            await self.page.click(send_selector)
        else:
            logger.warning("Send button not found after typing, pressing Enter.")
            await self.page.press(prompt_selector, "Enter")

        # Wait for response to complete via DOM indicators
        await self._wait_for_response(prev_count)

        self._in_conversation = True
        self._msg_count += 1

        return await self._extract_response()

    async def _download_image(self, url: str, index: int) -> Optional[Path]:
        """Download an image from URL using the browser context and save to disk."""
        save_dir = Path(IMAGE_DOWNLOAD_DIR).expanduser()
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            b64_data = await self.page.evaluate('''async (url) => {
                try {
                    const resp = await fetch(url, {credentials: "include"});
                    if (!resp.ok) return null;
                    const blob = await resp.blob();
                    return await new Promise((resolve) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    });
                } catch(e) { return null; }
            }''', url)

            if not b64_data:
                logger.warning(f"Failed to fetch image: {url}")
                return None

            # Parse data URI: "data:image/png;base64,..."
            header, data = b64_data.split(",", 1)
            ext = "png"
            if "image/jpeg" in header or "image/jpg" in header:
                ext = "jpg"
            elif "image/webp" in header:
                ext = "webp"
            elif "image/gif" in header:
                ext = "gif"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ghostgpt_{timestamp}_{self._msg_count}_{index}.{ext}"
            filepath = save_dir / filename
            filepath.write_bytes(base64.b64decode(data))

            logger.info(f"Image saved: {filepath}")
            return filepath

        except Exception as e:
            logger.warning(f"Image download failed: {e}")
            return None

    async def _extract_images(self, message_element) -> list[dict]:
        """Find all images within an assistant message element."""
        images = []
        for selector in IMAGE_SELECTORS:
            try:
                img_elements = await message_element.query_selector_all(selector)
                for img in img_elements:
                    src = await img.get_attribute("src")
                    alt = await img.get_attribute("alt") or ""
                    if src and src not in [i["url"] for i in images]:
                        images.append({"url": src, "alt": alt})
            except Exception:
                continue
        return images

    async def _extract_response(self) -> str:
        """Extract text and images from the last assistant message element."""
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

        # Get text content
        content = await last_message.inner_text()
        if not content or not content.strip():
            content = await last_message.inner_html()
            logger.info("inner_text() empty, used inner_html()")

        result = content.strip()

        # Check for images
        images = await self._extract_images(last_message)
        if images:
            logger.info(f"Found {len(images)} image(s) in response")
            for i, img in enumerate(images):
                filepath = await self._download_image(img["url"], i)
                result += f"\n\n[Image {i+1}]"
                if img["alt"]:
                    result += f" {img['alt']}"
                if filepath:
                    result += f"\n  Saved: {filepath}"
                result += f"\n  URL: {img['url']}"

        return result
