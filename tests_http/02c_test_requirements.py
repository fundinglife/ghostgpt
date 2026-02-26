"""
Step 2c: Investigate what ChatGPT requires for the conversation endpoint.

Check for requirements tokens, device IDs, and other anti-bot headers
that the conversation endpoint needs beyond the bearer token.
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from curl_cffi.requests import AsyncSession

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN_FILE = Path(__file__).parent / "token.json"
BASE = "https://chatgpt.com"


def load_token() -> dict:
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


async def investigate():
    token_data = load_token()
    token = token_data["accessToken"]
    cookies = token_data.get("cookies", {})

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
    }

    device_id = str(uuid.uuid4())

    async with AsyncSession(
        headers=headers,
        cookies=cookies,
        impersonate="chrome131",
        timeout=30,
    ) as client:

        # --- Test: Chat requirements token ---
        print("=" * 50)
        print("TEST: /backend-api/sentinel/chat-requirements")
        print("=" * 50)
        resp = await client.post(
            f"{BASE}/backend-api/sentinel/chat-requirements",
            json={"p": None},
            headers={**headers, "oai-device-id": device_id, "oai-language": "en-US"},
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Keys: {list(data.keys())}")
            print(json.dumps(data, indent=2)[:1000])
        else:
            print(f"Body: {resp.text[:500]}")
        print()

        # --- Test: Accounts check ---
        print("=" * 50)
        print("TEST: /backend-api/accounts/check/v4-2023-04-27")
        print("=" * 50)
        resp = await client.get(
            f"{BASE}/backend-api/accounts/check/v4-2023-04-27",
            headers={**headers, "oai-device-id": device_id, "oai-language": "en-US"},
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            plan = data.get("accounts", {})
            print(f"Keys: {list(data.keys())}")
            # Show account/plan info
            for acc_id, acc in plan.items():
                account = acc.get("account", {})
                print(f"  Account: {account.get('account_user_id', '?')}")
                print(f"  Plan: {account.get('plan_type', '?')}")
                print(f"  Is paid: {account.get('is_most_recent_expired_subscription_gratis', '?')}")
                entitlements = acc.get("entitlement", {})
                print(f"  Entitlements: {list(entitlements.keys())}")
        else:
            print(f"Body: {resp.text[:300]}")
        print()

        # --- Test: Conversation with requirements token ---
        print("=" * 50)
        print("TEST: conversation with chat-requirements token")
        print("=" * 50)
        # First get the requirements token
        req_resp = await client.post(
            f"{BASE}/backend-api/sentinel/chat-requirements",
            json={"p": None},
            headers={**headers, "oai-device-id": device_id, "oai-language": "en-US"},
        )
        if req_resp.status_code != 200:
            print(f"Failed to get requirements: {req_resp.status_code}")
            return

        req_data = req_resp.json()
        requirements_token = req_data.get("token", "")
        print(f"Got requirements token: {requirements_token[:50]}...")
        print(f"Arkose required: {req_data.get('arkose', {})}")
        print(f"Turnstile required: {req_data.get('turnstile', {})}")
        print(f"Proofofwork required: {req_data.get('proofofwork', {})}")
        print()

        # Now try conversation with the token
        conv_headers = {
            **headers,
            "Accept": "text/event-stream",
            "oai-device-id": device_id,
            "oai-language": "en-US",
            "openai-sentinel-chat-requirements-token": requirements_token,
        }

        payload = {
            "action": "next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": ["What is 2+2? One word answer."]},
                "metadata": {},
            }],
            "parent_message_id": str(uuid.uuid4()),
            "model": "auto",
            "timezone_offset_min": -60,
            "history_and_training_disabled": False,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_use_sse": True,
        }

        resp = await client.post(
            f"{BASE}/backend-api/conversation",
            json=payload,
            headers=conv_headers,
            stream=True,
        )
        print(f"Conversation Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")

        if resp.status_code == 200:
            full_response = ""
            async for chunk in resp.aiter_content():
                text = chunk.decode("utf-8", errors="replace")
                for line in text.split("\n"):
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    msg = data.get("message", {})
                    if msg.get("author", {}).get("role") == "assistant":
                        parts = msg.get("content", {}).get("parts", [])
                        if parts and isinstance(parts[0], str):
                            new_text = parts[0]
                            if len(new_text) > len(full_response):
                                print(new_text[len(full_response):], end="", flush=True)
                                full_response = new_text

            print(f"\n\nFull response: {full_response}")
            print("SUCCESS - Pure HTTP conversation works!")
        else:
            body = resp.text[:500] if hasattr(resp, 'text') else ""
            print(f"Body: {body}")
        print()


if __name__ == "__main__":
    asyncio.run(investigate())
