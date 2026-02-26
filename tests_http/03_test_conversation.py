"""
Step 3: Test sending a prompt to ChatGPT via pure HTTP (no browser).

Uses curl_cffi to bypass Cloudflare TLS fingerprinting.
Streams the response via SSE from /backend-api/conversation.
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path
from curl_cffi.requests import AsyncSession

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN_FILE = Path(__file__).parent / "token.json"
BASE = "https://chatgpt.com"


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Run 01_extract_token.py first. Missing: {TOKEN_FILE}")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


async def send_prompt(prompt: str, model: str = "auto"):
    token_data = load_token()
    token = token_data["accessToken"]
    cookies = token_data.get("cookies", {})

    print(f"User: {token_data['email']}")
    print(f"Model: {model}")
    print(f"Prompt: {prompt}\n")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
    }

    # ChatGPT conversation payload
    payload = {
        "action": "next",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "content": {
                    "content_type": "text",
                    "parts": [prompt],
                },
                "metadata": {},
            }
        ],
        "parent_message_id": str(uuid.uuid4()),
        "model": model,
        "timezone_offset_min": -60,
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_paragen": False,
        "force_paragen_model_slug": "",
        "force_nulligen": False,
        "force_rate_limit": False,
        "reset_rate_limits": False,
        "suggestions": [],
        "force_use_sse": True,
    }

    print("=" * 50)
    print("Sending to /backend-api/conversation ...")
    print("=" * 50)

    full_response = ""
    conversation_id = None
    message_id = None

    async with AsyncSession(
        headers=headers,
        cookies=cookies,
        impersonate="chrome131",
        timeout=120,
    ) as client:
        resp = await client.post(
            f"{BASE}/backend-api/conversation",
            json=payload,
            stream=True,
        )

        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")
        print()

        if resp.status_code != 200:
            print(f"ERROR: {resp.text[:500]}")
            return

        print("--- Streaming response ---\n")

        # curl_cffi streaming: iterate over content
        async for chunk in resp.aiter_content():
            text = chunk.decode("utf-8", errors="replace")
            for line in text.split("\n"):
                line = line.strip()
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]

                if data_str == "[DONE]":
                    print("\n\n--- [DONE] ---")
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Extract conversation metadata
                if not conversation_id and data.get("conversation_id"):
                    conversation_id = data["conversation_id"]

                msg = data.get("message", {})
                if msg.get("author", {}).get("role") == "assistant":
                    message_id = msg.get("id")
                    parts = msg.get("content", {}).get("parts", [])
                    if parts:
                        new_text = parts[0]
                        if isinstance(new_text, str) and len(new_text) > len(full_response):
                            delta = new_text[len(full_response):]
                            print(delta, end="", flush=True)
                            full_response = new_text

    print(f"\n\n{'=' * 50}")
    print(f"Conversation ID: {conversation_id}")
    print(f"Message ID: {message_id}")
    print(f"Response length: {len(full_response)} chars")
    print(f"{'=' * 50}")

    # Save conversation state for follow-up testing
    state_file = Path(__file__).parent / "conversation_state.json"
    state_file.write_text(json.dumps({
        "conversation_id": conversation_id,
        "parent_message_id": message_id,
        "model": model,
    }, indent=2), encoding="utf-8")
    print(f"\nConversation state saved to: {state_file}")


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is 2+2? Answer in one sentence."
    asyncio.run(send_prompt(prompt))
