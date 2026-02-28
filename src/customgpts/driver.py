"""
ChatGPT DOM interaction driver.

This is the core module that handles all direct interaction with the ChatGPT web interface:
  - Navigation to ChatGPT (with Cloudflare challenge handling)
  - Prompt input (keyboard typing when visible, clipboard paste when hidden)
  - Send button detection and clicking
  - Response completion detection via DOM polling (Copy/Read aloud button presence)
  - Response text extraction from assistant message elements
  - Streaming via repeated DOM text polling with delta computation
  - Image detection and download from DALL-E responses
  - GPT listing and GPT Store search via ChatGPT's internal backend API
  - Onboarding modal dismissal and login state detection

The driver operates on a single browser tab (Page) and tracks conversation state
to support multi-turn conversations within the same tab.

Key design decisions:
  - Completion is detected by checking for action buttons (Copy, Read aloud) on the
    last <article> element, NOT by waiting for a timeout.
  - A message count guard prevents false completion detection when GPT actions cause
    transient DOM elements that briefly appear and disappear.
  - Streaming polls inner_text() every 0.3s and yields text deltas (difference from
    previous poll), providing real-time output without WebSocket access.
  - Input method switches based on visibility: keyboard.type() when visible (more
    natural), clipboard paste when hidden (more reliable without focus).
"""

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

# Maximum time (seconds) to wait for ChatGPT to finish generating a response.
# Set high (5 min) to accommodate thinking models like o1 that can take minutes.
MAX_RESPONSE_WAIT = 300


class ChatGPTDriver:
    """Drives all DOM interactions with the ChatGPT web interface.

    Handles prompt input, response extraction, streaming, image downloads, and
    GPT Store queries. Operates on a single browser page/tab and tracks conversation
    state for multi-turn support.

    Attributes:
        context (BrowserContext): The patchright browser context for creating pages.
        visible (bool): Whether the browser window is visible to the user.
            Affects input method: keyboard.type() when visible, clipboard paste when hidden.
        page (Page | None): The active browser page/tab.
        _in_conversation (bool): Whether we're in an active multi-turn conversation.
        _msg_count (int): Running count of messages sent in the current session.
    """

    def __init__(self, context: BrowserContext, visible: bool = False):
        """Initialize the ChatGPT driver.

        Args:
            context: The patchright BrowserContext to create pages from.
            visible: Whether the browser is visible to the user. Controls input
                     method selection (keyboard vs clipboard paste).
        """
        self.context = context
        self.visible = visible
        self.page: Optional[Page] = None
        self._in_conversation = False
        self._msg_count = 0

    async def _wait_for_cloudflare(self):
        """Wait for a Cloudflare challenge page to resolve before proceeding.

        Polls the page title every second for up to 30 seconds, looking for the
        "Just a moment" title that Cloudflare displays during its challenge.

        Raises:
            Exception: If the Cloudflare challenge doesn't resolve within 30 seconds.
                       Suggests running in non-headless mode or logging in first.
        """
        for i in range(30):
            title = await self.page.title()
            if "just a moment" not in title.lower():
                return
            logger.info(f"Cloudflare challenge detected, waiting... ({i+1}s)")
            await asyncio.sleep(1)
        raise Exception(
            "Stuck on Cloudflare challenge. Try 'customgpts ask --no-headless' or run 'customgpts login' first."
        )

    async def _ensure_page(self, gpt_id: Optional[str] = None):
        """Ensure the browser page is navigated to the correct ChatGPT URL.

        Creates a new page/tab if none exists, navigates to the appropriate URL
        (base ChatGPT or a specific custom GPT), handles Cloudflare challenges,
        dismisses onboarding modals, checks for login state, and waits for the
        prompt textarea to become visible.

        Args:
            gpt_id: Optional GPT identifier. If provided, navigates to
                    https://chatgpt.com/g/{gpt_id} instead of the base URL.

        Raises:
            Exception: If the user appears to be logged out (login page detected).
            Exception: If the prompt textarea doesn't appear within the timeout.
        """
        if not self.page:
            self.page = await self.context.new_page()

        target_url = f"{BASE_URL}/g/{gpt_id}" if gpt_id else BASE_URL

        if self.page.url != target_url:
            logger.info(f"Navigating to {target_url}")
            await self.page.goto(target_url, wait_until="load", timeout=60000)

            # Handle Cloudflare challenge if present
            await self._wait_for_cloudflare()

            # Bypass onboarding via localStorage — prevents first-time-use dialogs
            try:
                for key, value in ONBOARDING_LOCALSTORAGE_BYPASS.items():
                    await self.page.evaluate(
                        f"window.localStorage.setItem('{key}', '{value}')"
                    )
            except Exception:
                pass

            # Dismiss any onboarding modals that appear despite localStorage bypass
            for btn in ONBOARDING_BUTTONS:
                try:
                    if await self.page.is_visible(btn, timeout=800):
                        logger.info(f"Dismissing onboarding: {btn}")
                        await self.page.click(btn)
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Check for login page — if detected, the session has expired
            for indicator in LOGIN_INDICATORS:
                try:
                    if await self.page.is_visible(indicator, timeout=1000):
                        raise Exception(
                            "User appears to be logged out. Run 'customgpts login' first."
                        )
                except Exception as e:
                    if "logged out" in str(e):
                        raise
                    pass

            # Wait for the prompt textarea to become visible
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
        """Find the first visible element from a list of CSS selectors.

        Tries each selector in order and returns the first one that matches a
        visible element on the page. Used to handle ChatGPT UI variations where
        elements may have different selectors across versions.

        Args:
            selectors: An ordered list of CSS selector strings to try.

        Returns:
            str | None: The first selector that matches a visible element,
                        or None if no selector matches.
        """
        for s in selectors:
            try:
                if await self.page.is_visible(s):
                    return s
            except Exception:
                continue
        return None


    async def list_gpts(self) -> list[dict]:
        """Fetch all available GPTs from the user's ChatGPT account.

        Queries two ChatGPT backend API endpoints using the browser's session:
          1. /backend-api/gizmos/bootstrap — returns pinned/store GPTs
          2. /backend-api/gizmos/snorlax/sidebar — returns custom-built GPTs

        Returns:
            list[dict]: A list of GPT objects, each containing:
                - id (str): The GPT identifier (e.g., "g-XXXXX").
                - name (str): The display name of the GPT.
                - type (str): Either "pinned" (from store) or "custom" (user-built).

        Raises:
            Exception: If the session token cannot be retrieved.
        """
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
        """Search the GPT Store for public GPTs by keyword.

        Uses ChatGPT's internal search API with cursor-based pagination to fetch
        up to `limit` results.

        Args:
            query: The search keyword (e.g., "code review", "image generator").
            limit: Maximum number of results to return. Defaults to 20.

        Returns:
            list[dict]: A list of GPT objects, each containing:
                - id (str): The GPT identifier or short URL.
                - name (str): The display name.
                - description (str): Brief description (truncated to 100 chars).
                - author (str): The GPT author's display name.

        Raises:
            Exception: If the search request fails or session is invalid.
        """
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
        """Count the number of assistant messages currently visible in the DOM.

        Tries each selector in ASSISTANT_FALLBACKS to find assistant message elements.
        Uses the first selector that returns results.

        Returns:
            int: The number of assistant message elements found, or 0 if none.
        """
        for s in ASSISTANT_FALLBACKS:
            try:
                msgs = await self.page.query_selector_all(s)
                if msgs:
                    return len(msgs)
            except Exception:
                continue
        return 0

    async def _auto_allow_actions(self):
        """Auto-click permission buttons for GPT actions that require user approval.

        Some custom GPTs trigger actions (web browsing, code execution) that display
        an "Allow" or "Always allow" button. This method clicks them automatically
        so the response can continue generating.

        Returns:
            bool: True if an allow button was found and clicked, False otherwise.
        """
        allow_selectors = [
            'button:has-text("Allow")',
            'button:has-text("Always allow")',
            '[data-testid="allow-action-button"]',
        ]
        for sel in allow_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    logger.info(f"Auto-clicking action permission: {sel}")
                    await btn.click()
                    await asyncio.sleep(1)
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_response(self, prev_count: int):
        """Wait for a new assistant message to appear and finish generating.

        Two-phase wait:
          Phase 1 (up to 60s): Wait for a new assistant message to appear in the DOM.
                  Checks every 0.5s if the message count exceeds prev_count.
          Phase 2 (up to MAX_RESPONSE_WAIT): Wait for completion indicators (Copy,
                  Read aloud buttons) to appear on the last message's parent <article>.
                  Includes a message count guard — if the count drops back to prev_count
                  (due to transient DOM elements from GPT actions), keeps waiting instead
                  of falsely detecting completion on an old message.

        Args:
            prev_count: The number of assistant messages before sending the prompt.
                        Used to detect when a NEW message appears.
        """
        logger.info(f"Waiting for new response (prev messages: {prev_count})...")

        # Phase 1: wait for a new assistant message to appear
        for i in range(120):  # up to 60s for response to start
            await asyncio.sleep(0.5)
            current = await self._count_messages()
            if current > prev_count:
                logger.info(f"New message appeared ({(i+1)*0.5:.0f}s)")
                break
        else:
            logger.warning("No new assistant message appeared")
            return

        # Phase 2: wait for the LAST message to have completion indicators
        # Key: only check completion if message count is still > prev_count
        # (transient DOM elements from GPT actions can appear and disappear)
        for i in range(MAX_RESPONSE_WAIT * 2):  # poll every 0.5s
            await asyncio.sleep(0.5)

            try:
                for s in ASSISTANT_FALLBACKS:
                    msgs = await self.page.query_selector_all(s)
                    if msgs:
                        # Guard: ensure we still have MORE messages than before
                        if len(msgs) <= prev_count:
                            logger.debug(f"Message count dropped to {len(msgs)}, waiting...")
                            break  # break inner for, continue outer poll loop

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

    async def _send_and_get_prev_count(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False) -> int:
        """Shared logic for sending a prompt: navigate, type, click send.

        This is the common setup used by both send_prompt() and send_prompt_streaming().
        It navigates to the correct page, types the prompt, and clicks the send button.

        Input method:
          - Visible mode: keyboard.type() — types character by character (more natural).
          - Hidden mode: clipboard paste — writes to clipboard via JS API, then Ctrl+V.
            This is more reliable when the browser window doesn't have OS-level focus.

        Args:
            prompt: The user message to send.
            gpt_id: Optional GPT identifier for custom GPT navigation.
            continue_conversation: If True, skip navigation (stay in current chat tab).

        Returns:
            int: The number of assistant messages BEFORE sending, used to detect
                 when the new response appears.

        Raises:
            Exception: If the prompt textarea is not visible on the page.
        """
        if not (continue_conversation and self._in_conversation):
            await self._ensure_page(gpt_id)

        prompt_selector = await self._find_visible(PROMPT_FALLBACKS)
        if not prompt_selector:
            raise Exception("Prompt box not visible.")

        logger.info(f"Typing prompt via {prompt_selector}: {prompt[:50]}...")

        prev_count = await self._count_messages()

        await self.page.click(prompt_selector)
        if self.visible:
            # Visible mode: type normally via keyboard events
            await self.page.keyboard.type(prompt)
        else:
            # Hidden mode: clipboard paste is more reliable without OS-level window focus
            await self.page.evaluate("(text) => navigator.clipboard.writeText(text)", prompt)
            await self.page.keyboard.press("Control+KeyV")
        await asyncio.sleep(0.3)

        # Click the send button, or fall back to Enter key
        send_selector = await self._find_visible(SEND_BUTTON_FALLBACKS)
        if send_selector:
            logger.info(f"Clicking send button: {send_selector}")
            await self.page.click(send_selector)
        else:
            logger.warning("Send button not found after typing, pressing Enter.")
            await self.page.press(prompt_selector, "Enter")

        return prev_count

    async def send_prompt(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False) -> str:
        """Send a prompt to ChatGPT and wait for the complete response.

        Navigates to the appropriate page, types the prompt, sends it, waits for the
        response to finish generating, then extracts and returns the full response text
        (including any downloaded images).

        Args:
            prompt: The user message to send to ChatGPT.
            gpt_id: Optional GPT identifier for using a custom GPT.
            continue_conversation: If True, continue in the same chat thread.

        Returns:
            str: The complete assistant response text, possibly including image
                 download paths and URLs if DALL-E images were generated.
        """
        prev_count = await self._send_and_get_prev_count(prompt, gpt_id, continue_conversation)

        await self._wait_for_response(prev_count)

        self._in_conversation = True
        self._msg_count += 1

        return await self._extract_response()

    async def send_prompt_streaming(self, prompt: str, gpt_id: Optional[str] = None, continue_conversation: bool = False):
        """Send a prompt and yield response text as it generates (async generator).

        Similar to send_prompt() but instead of waiting for the full response, this
        method polls the DOM every 0.3 seconds and yields text deltas (the new text
        since the last poll). Used by the API server for SSE streaming.

        Two-phase operation:
          Phase 1 (up to 60s): Wait for a new assistant message element to appear.
          Phase 2: Poll inner_text() of the last assistant message every 0.3s.
                   Yield the delta (new characters) each time. Stop when completion
                   indicators (Copy/Read aloud buttons) are detected.

        Args:
            prompt: The user message to send to ChatGPT.
            gpt_id: Optional GPT identifier for using a custom GPT.
            continue_conversation: If True, continue in the same chat thread.

        Yields:
            str: Text deltas — the new portion of the response since the last poll.
                 Concatenating all deltas produces the full response text.
        """
        prev_count = await self._send_and_get_prev_count(prompt, gpt_id, continue_conversation)

        # Phase 1: wait for new assistant message to appear
        for i in range(120):  # up to 60s
            await asyncio.sleep(0.5)
            current = await self._count_messages()
            if current > prev_count:
                logger.info(f"New message appeared ({(i+1)*0.5:.0f}s)")
                break
        else:
            logger.warning("No new assistant message appeared")
            return

        # Phase 2: poll DOM for growing text, yield deltas
        prev_text = ""
        for i in range(MAX_RESPONSE_WAIT * 3):  # poll every ~0.3s
            await asyncio.sleep(0.3)

            try:
                # Get current text of last assistant message
                current_text = ""
                completed = False
                for s in ASSISTANT_FALLBACKS:
                    msgs = await self.page.query_selector_all(s)
                    if msgs:
                        # Guard: ensure message count is still > prev_count
                        if len(msgs) <= prev_count:
                            break  # transient element gone, keep waiting

                        last_msg = msgs[-1]
                        current_text = (await last_msg.inner_text() or "").strip()

                        # Check for completion indicators on the message's parent article
                        parent = await last_msg.evaluate_handle(
                            "el => el.closest('article') || el.parentElement"
                        )
                        for indicator in COMPLETION_INDICATORS:
                            btn = await parent.query_selector(indicator.replace("article ", ""))
                            if btn:
                                completed = True
                                break
                        break

                # Yield delta if text grew since last poll
                if len(current_text) > len(prev_text):
                    delta = current_text[len(prev_text):]
                    prev_text = current_text
                    yield delta

                if completed:
                    # Yield any remaining text after completion detection
                    if len(current_text) > len(prev_text):
                        yield current_text[len(prev_text):]
                    logger.info(f"Stream complete ({(i+1)*0.3:.0f}s)")
                    break
            except Exception as e:
                logger.debug(f"Stream poll error: {e}")
                continue

        self._in_conversation = True
        self._msg_count += 1

    async def _download_image(self, url: str, index: int) -> Optional[Path]:
        """Download an image from a URL using the browser's authenticated session.

        Fetches the image via the browser's fetch() API (to include session cookies),
        converts it to a base64 data URI, then decodes and saves to disk.

        Args:
            url: The image URL to download (typically a DALL-E CDN or Azure blob URL).
            index: The image index within the current response (used in filename).

        Returns:
            Path | None: The local file path where the image was saved, or None if
                         the download failed. Images are saved to ~/.customgpts/images/
                         with filenames like "customgpts_20240101_120000_1_0.png".
        """
        save_dir = Path(IMAGE_DOWNLOAD_DIR).expanduser()
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Fetch the image in-browser to include session cookies
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

            # Parse data URI: "data:image/png;base64,..." -> determine extension
            header, data = b64_data.split(",", 1)
            ext = "png"
            if "image/jpeg" in header or "image/jpg" in header:
                ext = "jpg"
            elif "image/webp" in header:
                ext = "webp"
            elif "image/gif" in header:
                ext = "gif"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"customgpts_{timestamp}_{self._msg_count}_{index}.{ext}"
            filepath = save_dir / filename
            filepath.write_bytes(base64.b64decode(data))

            logger.info(f"Image saved: {filepath}")
            return filepath

        except Exception as e:
            logger.warning(f"Image download failed: {e}")
            return None

    async def _extract_images(self, message_element) -> list[dict]:
        """Find all images within an assistant message DOM element.

        Searches for <img> elements matching IMAGE_SELECTORS (DALL-E CDN, OpenAI hosted,
        Azure blob, or any image with alt text). Deduplicates by URL.

        Args:
            message_element: A patchright ElementHandle for the assistant message container.

        Returns:
            list[dict]: A list of image objects, each containing:
                - url (str): The image source URL.
                - alt (str): The image alt text (may be empty).
        """
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
        """Extract text and images from the last assistant message in the DOM.

        Finds all assistant message elements using ASSISTANT_FALLBACKS selectors,
        takes the last one, extracts its text content via inner_text() (falling back
        to inner_html() if empty), then checks for and downloads any images.

        Returns:
            str: The assistant's response text. If images were found, appends image
                 metadata (alt text, local save path, original URL) to the text.
                 Returns an error message if no assistant message is found.
        """
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

        # Get text content — prefer inner_text() for clean text, fall back to inner_html()
        content = await last_message.inner_text()
        if not content or not content.strip():
            content = await last_message.inner_html()
            logger.info("inner_text() empty, used inner_html()")

        result = content.strip()

        # Check for and download any images in the response
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
