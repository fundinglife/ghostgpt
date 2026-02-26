"""
Step 4: Test follow-up message in an existing conversation.

Uses the conversation_id and parent_message_id from step 3
to continue the same conversation thread.
"""
import asyncio
import json
import uuid
from pathlib import Path
import httpx

TOKEN_FILE = Path(__file__).parent / "token.json"
STATE_FILE = Path(__file__).parent / "conversation_state.json"
BASE = "https://chatgpt.com"


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"Run 01_extract_token.py first.")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"Run 03_test_conversation.py first.")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


async def send_followup(prompt: str):
    token_data = load_token()
    state = load_state()
    token = token_data["accessToken"]
    cookies = token_data.get("cookies", {})

    print(f"Continuing conversation: {state['conversation_id']}")
    print(f"Parent message: {state['parent_message_id']}")
    print(f"Prompt: {prompt}\n")

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": f"https://chatgpt.com/c/{state['conversation_id']}",
    }

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if cookie_str:
        headers["Cookie"] = cookie_str

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
        "conversation_id": state["conversation_id"],
        "parent_message_id": state["parent_message_id"],
        "model": state.get("model", "auto"),
        "timezone_offset_min": -60,
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_use_sse": True,
    }

    full_response = ""
    message_id = None

    async with httpx.AsyncClient(
        base_url=BASE,
        headers=headers,
        timeout=120.0,
        follow_redirects=True,
    ) as client:
        async with client.stream("POST", "/backend-api/conversation", json=payload) as resp:
            print(f"Status: {resp.status_code}")

            if resp.status_code != 200:
                body = await resp.aread()
                print(f"ERROR: {body.decode()[:500]}")
                return

            print("--- Streaming response ---\n")

            async for line in resp.aiter_lines():
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

                msg = data.get("message", {})
                if msg.get("author", {}).get("role") == "assistant":
                    message_id = msg.get("id")
                    parts = msg.get("content", {}).get("parts", [])
                    if parts and isinstance(parts[0], str):
                        new_text = parts[0]
                        if len(new_text) > len(full_response):
                            print(new_text[len(full_response):], end="", flush=True)
                            full_response = new_text

    print(f"\n\nResponse length: {len(full_response)} chars")

    # Update state for next follow-up
    if message_id:
        state["parent_message_id"] = message_id
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"State updated (new parent: {message_id})")


if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What did I just ask you?"
    asyncio.run(send_followup(prompt))
