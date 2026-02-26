"""Test SSE stream capture approaches."""
import asyncio
import json
from patchright.async_api import async_playwright


chunks = []
done_event = asyncio.Event()


async def test_response_listener():
    """Test page.on('response') approach with response.finished() + response.body()."""
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=r"C:\Users\rohit\.ghostgpt\profile",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--window-position=-3000,-3000",
            "--window-size=1280,720",
        ],
        no_viewport=True,
    )
    page = await ctx.new_page()

    # Navigate
    await page.goto("https://chatgpt.com", timeout=60000, wait_until="load")
    title = await page.title()
    print(f"Navigated: {title}")

    # Wait for prompt
    await page.wait_for_selector("#prompt-textarea", timeout=10000, state="visible")
    print("Prompt textarea visible")

    # Set up response listener
    sse_body = None
    sse_done = asyncio.Event()

    async def on_response(response):
        nonlocal sse_body
        url = response.url
        if "/backend-api/conversation" not in url:
            return
        ct = response.headers.get("content-type", "")
        print(f"  [Response] {response.status} {ct[:50]} url={url[:80]}")

        if response.status != 200:
            return
        if "text/event-stream" not in ct:
            return

        print("  [Response] SSE stream detected! Waiting for completion...")
        try:
            await response.finished()
            body = (await response.body()).decode("utf-8", errors="replace")
            sse_body = body
            print(f"  [Response] SSE body captured: {len(body)} bytes")
        except Exception as e:
            print(f"  [Response] Error: {e}")
        finally:
            sse_done.set()

    page.on("response", on_response)

    # Type and send
    await page.click("#prompt-textarea")
    await page.keyboard.type("Say hello in exactly 5 words")
    await asyncio.sleep(0.3)

    send = await page.query_selector('button[data-testid="send-button"]')
    if send:
        await send.click()
        print("Sent prompt via send button")
    else:
        await page.press("#prompt-textarea", "Enter")
        print("Sent prompt via Enter")

    # Wait for SSE completion
    print("Waiting for SSE response (120s timeout)...")
    try:
        await asyncio.wait_for(sse_done.wait(), timeout=120)

        if sse_body:
            print(f"\nSSE body: {len(sse_body)} bytes")
            print(f"First 200 chars: {sse_body[:200]}")
            print(f"Last 200 chars: {sse_body[-200:]}")

            # Parse SSE
            full_text = ""
            event_count = 0
            for line in sse_body.split("\n"):
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                d = line[6:]
                if d == "[DONE]":
                    break
                event_count += 1
                try:
                    data = json.loads(d)
                    msg = data.get("message", {})
                    if msg.get("author", {}).get("role") == "assistant":
                        parts = msg.get("content", {}).get("parts", [])
                        if parts and isinstance(parts[0], str):
                            full_text = parts[0]
                except (json.JSONDecodeError, ValueError):
                    continue

            print(f"\nParsed {event_count} SSE events")
            print(f"Response: {full_text}")
        else:
            print("SSE done but no body captured")
    except asyncio.TimeoutError:
        print("Timeout waiting for SSE!")

    page.remove_listener("response", on_response)
    await ctx.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(test_response_listener())
