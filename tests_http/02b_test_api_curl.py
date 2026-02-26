"""
Step 2b: Test ChatGPT backend API using curl_cffi (browser TLS fingerprinting).

Same tests as 02_test_api.py but using curl_cffi instead of httpx
to bypass Cloudflare's TLS fingerprint detection.
"""
import asyncio
import json
import sys
from pathlib import Path
from curl_cffi.requests import AsyncSession

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN_FILE = Path(__file__).parent / "token.json"
BASE = "https://chatgpt.com"


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Run 01_extract_token.py first.")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


async def test_api():
    token_data = load_token()
    token = token_data["accessToken"]
    cookies = token_data.get("cookies", {})

    print(f"Using token for: {token_data['user']} ({token_data['email']})")
    print(f"Token: {token[:20]}...{token[-10:]}")
    print(f"Cookies: {list(cookies.keys())}\n")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
    }

    async with AsyncSession(
        headers=headers,
        cookies=cookies,
        impersonate="chrome131",
        timeout=30,
    ) as client:

        # --- Test 1: Session check ---
        print("=" * 50)
        print("TEST 1: /api/auth/session")
        print("=" * 50)
        resp = await client.get(f"{BASE}/api/auth/session")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"User: {data.get('user', {}).get('name', '?')}")
            print(f"Email: {data.get('user', {}).get('email', '?')}")
            print(f"Expires: {data.get('expires', '?')}")
        else:
            print(f"Body: {resp.text[:200]}")
        print()

        # --- Test 2: List pinned GPTs ---
        print("=" * 50)
        print("TEST 2: /backend-api/gizmos/bootstrap")
        print("=" * 50)
        resp = await client.get(f"{BASE}/backend-api/gizmos/bootstrap")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            gizmos = data.get("gizmos", [])
            print(f"Found {len(gizmos)} pinned GPTs:")
            for g in gizmos[:5]:
                gizmo = g.get("resource", {}).get("gizmo", g)
                name = gizmo.get("display", {}).get("name", "?")
                gid = gizmo.get("id", "?")
                print(f"  - {name} ({gid})")
            if len(gizmos) > 5:
                print(f"  ... and {len(gizmos) - 5} more")
        else:
            print(f"Body: {resp.text[:300]}")
        print()

        # --- Test 3: List custom GPTs ---
        print("=" * 50)
        print("TEST 3: /backend-api/gizmos/snorlax/sidebar")
        print("=" * 50)
        resp = await client.get(f"{BASE}/backend-api/gizmos/snorlax/sidebar")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            print(f"Found {len(items)} custom GPTs:")
            for item in items[:5]:
                gizmo = item.get("gizmo", {})
                name = gizmo.get("display", {}).get("name", "?")
                gid = gizmo.get("id", "?")
                print(f"  - {name} ({gid})")
        else:
            print(f"Body: {resp.text[:300]}")
        print()

        # --- Test 4: Search GPT Store ---
        print("=" * 50)
        print("TEST 4: /backend-api/gizmos/search?q=code+review")
        print("=" * 50)
        resp = await client.get(f"{BASE}/backend-api/gizmos/search?q=code+review")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("items", data.get("items", []))
            print(f"Found {len(hits)} search results:")
            for item in hits[:3]:
                gizmo = item.get("resource", {}).get("gizmo", item.get("gizmo", item))
                name = gizmo.get("display", {}).get("name", "?")
                gid = gizmo.get("id", "?")
                author = gizmo.get("author", {}).get("display_name", "?")
                print(f"  - {name} by {author} ({gid})")
        else:
            print(f"Body: {resp.text[:300]}")
        print()

        # --- Test 5: Get available models ---
        print("=" * 50)
        print("TEST 5: /backend-api/models")
        print("=" * 50)
        resp = await client.get(f"{BASE}/backend-api/models?history_and_training_disabled=false")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Keys: {list(data.keys())}")
            models = data.get("models", data.get("categories", []))
            if isinstance(models, list):
                print(f"Found {len(models)} models:")
                for m in models[:10]:
                    if isinstance(m, dict):
                        print(f"  - {m.get('slug', m.get('name', m.get('title', '?')))}")
                    else:
                        print(f"  - {m}")
            else:
                print(json.dumps(data, indent=2)[:500])
        else:
            print(f"Body: {resp.text[:300]}")
        print()


if __name__ == "__main__":
    asyncio.run(test_api())
