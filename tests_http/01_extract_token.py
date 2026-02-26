"""
Step 1: Extract the bearer token from a ChatGPT browser session.

Launches the browser briefly using the saved profile, grabs the accessToken
from /api/auth/session, then closes the browser. Saves the token to token.txt.
"""
import asyncio
import json
from pathlib import Path
from patchright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".ghostgpt" / "profile"
TOKEN_FILE = Path(__file__).parent / "token.json"


async def extract_token():
    print(f"Launching browser with profile: {PROFILE_DIR}")
    pw = await async_playwright().start()

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        no_viewport=True,
    )

    page = await context.new_page()

    # Navigate to ChatGPT
    print("Navigating to chatgpt.com...")
    await page.goto("https://chatgpt.com", wait_until="load", timeout=60000)

    # Wait for Cloudflare if needed
    for i in range(15):
        title = await page.title()
        if "just a moment" not in title.lower():
            break
        print(f"  Cloudflare challenge... ({i+1}s)")
        await asyncio.sleep(1)

    # Grab the session token
    print("Fetching /api/auth/session...")
    result = await page.evaluate('''async () => {
        try {
            const resp = await fetch("/api/auth/session", {credentials: "include"});
            if (!resp.ok) return {error: "HTTP " + resp.status};
            const data = await resp.json();
            return {
                accessToken: data.accessToken,
                user: data.user?.name || "unknown",
                email: data.user?.email || "unknown",
                expires: data.expires,
            };
        } catch(e) {
            return {error: e.message};
        }
    }''')

    # Also grab cookies for potential future use
    cookies = await context.cookies("https://chatgpt.com")
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    # Close browser immediately
    await context.close()
    await pw.stop()
    print("Browser closed.\n")

    if "error" in result:
        print(f"FAILED: {result['error']}")
        return

    # Save token data
    token_data = {
        "accessToken": result["accessToken"],
        "user": result["user"],
        "email": result["email"],
        "expires": result["expires"],
        "cookies": {
            # Only save relevant auth cookies
            k: v for k, v in cookie_dict.items()
            if k.startswith("__Secure") or k.startswith("__Host") or k == "_puid"
        },
    }

    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"User: {result['user']} ({result['email']})")
    print(f"Token expires: {result['expires']}")
    print(f"Token length: {len(result['accessToken'])} chars")
    print(f"Cookies saved: {list(token_data['cookies'].keys())}")
    print(f"\nSaved to: {TOKEN_FILE}")


if __name__ == "__main__":
    asyncio.run(extract_token())
