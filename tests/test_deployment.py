"""
Deployment integration tests for CustomGPTs.

Tests the running Docker container's API server, VNC access, and cloudflared
tunnel endpoints. These are NOT unit tests — they require the container to be
running (`docker compose up -d`).

Run all tests:
    python -m pytest tests/test_deployment.py -v

Run a specific test group:
    python -m pytest tests/test_deployment.py -v -k "local"      # Local endpoints only
    python -m pytest tests/test_deployment.py -v -k "tunnel"     # Tunnel endpoints only
    python -m pytest tests/test_deployment.py -v -k "chat"       # Chat completions only

Skip slow tests (chat completions that hit ChatGPT):
    python -m pytest tests/test_deployment.py -v -m "not slow"
"""

import json
import subprocess
import pytest
import httpx

# ── Configuration ────────────────────────────────────────────────────

LOCAL_API = "http://localhost:5124"
LOCAL_VNC = "http://localhost:6080"
TUNNEL_API = "https://customgpts.rohitsoni.com"
TUNNEL_VNC = "https://vnc.rohitsoni.com"

# Timeout for chat completions — ChatGPT can take a while, especially thinking models
CHAT_TIMEOUT = 120.0


# ── Helpers ──────────────────────────────────────────────────────────

def curl_get(url: str, timeout: int = 10) -> tuple[int, str]:
    """Make a GET request via curl (bypasses httpx TLS fingerprint issues with Cloudflare).

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        tuple: (http_status_code, response_body)
    """
    result = subprocess.run(
        ["curl", "-s", "-o", "-", "-w", "\n%{http_code}", url],
        capture_output=True, text=True, timeout=timeout,
    )
    lines = result.stdout.rsplit("\n", 1)
    body = lines[0] if len(lines) > 1 else ""
    status = int(lines[-1]) if lines[-1].strip().isdigit() else 0
    return status, body


def curl_post(url: str, data: dict, timeout: int = 120) -> tuple[int, str]:
    """Make a POST request via curl with JSON body.

    Args:
        url: The URL to post to.
        data: Dictionary to send as JSON body.
        timeout: Request timeout in seconds.

    Returns:
        tuple: (http_status_code, response_body)
    """
    result = subprocess.run(
        ["curl", "-s", "-o", "-", "-w", "\n%{http_code}",
         "-X", "POST", "-H", "Content-Type: application/json",
         "-d", json.dumps(data), url],
        capture_output=True, text=True, timeout=timeout,
    )
    lines = result.stdout.rsplit("\n", 1)
    body = lines[0] if len(lines) > 1 else ""
    status = int(lines[-1]) if lines[-1].strip().isdigit() else 0
    return status, body


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """Shared HTTP client for local endpoint tests.

    Uses httpx for local tests (no Cloudflare in the way).
    Tunnel tests use curl helpers instead to avoid Cloudflare TLS fingerprint blocking.
    """
    with httpx.Client(timeout=CHAT_TIMEOUT, follow_redirects=True) as c:
        yield c


# ── Local endpoint tests ─────────────────────────────────────────────

class TestLocalHealth:
    """Test the local API health endpoint."""

    def test_health_returns_ok(self, client):
        """GET /health should return {"status": "ok"} with 200."""
        resp = client.get(f"{LOCAL_API}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestLocalModels:
    """Test the local models listing endpoint."""

    def test_models_returns_list(self, client):
        """GET /v1/models should return an OpenAI-format model list."""
        resp = client.get(f"{LOCAL_API}/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_models_includes_chatgpt(self, client):
        """The models list should always include the base 'chatgpt' model."""
        resp = client.get(f"{LOCAL_API}/v1/models")
        data = resp.json()
        model_ids = [m["id"] for m in data["data"]]
        assert "chatgpt" in model_ids

    def test_model_object_format(self, client):
        """Each model object should have id, object, and owned_by fields."""
        resp = client.get(f"{LOCAL_API}/v1/models")
        data = resp.json()
        for model in data["data"]:
            assert "id" in model
            assert model["object"] == "model"
            assert model["owned_by"] == "customgpts"


class TestLocalVNC:
    """Test the local noVNC web interface."""

    def test_vnc_returns_200(self, client):
        """GET localhost:6080 should return 200 (noVNC web page)."""
        resp = client.get(LOCAL_VNC)
        assert resp.status_code == 200

    def test_vnc_serves_html(self, client):
        """The VNC endpoint should serve HTML content."""
        resp = client.get(LOCAL_VNC)
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type


# ── Tunnel endpoint tests (use curl to bypass Cloudflare TLS fingerprinting) ──

class TestTunnelAPI:
    """Test the API through the cloudflared tunnel."""

    def test_tunnel_health(self):
        """Health check through the tunnel should return ok."""
        status, body = curl_get(f"{TUNNEL_API}/health")
        assert status == 200
        data = json.loads(body)
        assert data["status"] == "ok"

    def test_tunnel_models(self, client):
        """Models endpoint through the tunnel should return the same data."""
        local = client.get(f"{LOCAL_API}/v1/models").json()
        status, body = curl_get(f"{TUNNEL_API}/v1/models")
        assert status == 200
        tunnel = json.loads(body)
        # Same model IDs should be available
        local_ids = sorted(m["id"] for m in local["data"])
        tunnel_ids = sorted(m["id"] for m in tunnel["data"])
        assert local_ids == tunnel_ids


class TestTunnelVNC:
    """Test the VNC through the cloudflared tunnel."""

    def test_vnc_tunnel_returns_200(self):
        """VNC through the tunnel should return 200."""
        status, _ = curl_get(TUNNEL_VNC)
        assert status == 200

    def test_vnc_tunnel_serves_html(self):
        """VNC tunnel should serve HTML content (noVNC web page)."""
        status, body = curl_get(TUNNEL_VNC)
        assert status == 200
        # noVNC page should contain HTML
        assert "<html" in body.lower() or "<!doctype" in body.lower()


# ── Chat completion tests (slow — hit actual ChatGPT) ────────────────

@pytest.mark.slow
class TestChatCompletion:
    """Test chat completions against the running API server.

    These tests send actual prompts to ChatGPT through the browser scraper,
    so they are slow (10-60s each) and require a logged-in session.
    """

    def test_non_streaming_response(self, client):
        """Non-streaming chat completion should return a valid response."""
        resp = client.post(
            f"{LOCAL_API}/v1/chat/completions",
            json={
                "model": "chatgpt",
                "messages": [{"role": "user", "content": "Reply with exactly: TEST_OK"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify OpenAI-compatible response structure
        assert data["object"] == "chat.completion"
        assert "id" in data
        assert "created" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"

        # Verify we got actual content back
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0

    def test_non_streaming_has_conversation_id(self, client):
        """Non-streaming response should include a conversation_id."""
        resp = client.post(
            f"{LOCAL_API}/v1/chat/completions",
            json={
                "model": "chatgpt",
                "messages": [{"role": "user", "content": "Reply with exactly: CONV_TEST"}],
            },
        )
        data = resp.json()
        assert "conversation_id" in data
        assert data["conversation_id"] is not None

        # Also check the header
        assert "x-conversation-id" in resp.headers

    def test_streaming_response(self, client):
        """Streaming chat completion should return valid SSE chunks."""
        with client.stream(
            "POST",
            f"{LOCAL_API}/v1/chat/completions",
            json={
                "model": "chatgpt",
                "messages": [{"role": "user", "content": "Reply with exactly: STREAM_OK"}],
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200

            chunks = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    chunks.append(line[6:])

        # Should have at least: role chunk, content chunk(s), stop chunk, [DONE]
        assert len(chunks) >= 3
        assert chunks[-1] == "[DONE]"

        # First data chunk should have role="assistant"
        first = json.loads(chunks[0])
        assert first["choices"][0]["delta"]["role"] == "assistant"

    def test_error_on_empty_messages(self, client):
        """Should return 400 error when messages array has no user message."""
        resp = client.post(
            f"{LOCAL_API}/v1/chat/completions",
            json={
                "model": "chatgpt",
                "messages": [],
            },
        )
        # Should be an error (either 400 or 422 validation error)
        assert resp.status_code >= 400


@pytest.mark.slow
class TestChatCompletionTunnel:
    """Test chat completions through the cloudflared tunnel."""

    def test_tunnel_non_streaming(self):
        """Chat completion through the tunnel should work end-to-end."""
        status, body = curl_post(
            f"{TUNNEL_API}/v1/chat/completions",
            {"model": "chatgpt", "messages": [{"role": "user", "content": "Reply with exactly: TUNNEL_OK"}]},
        )
        assert status == 200
        data = json.loads(body)
        assert len(data["choices"]) == 1
        assert len(data["choices"][0]["message"]["content"]) > 0
