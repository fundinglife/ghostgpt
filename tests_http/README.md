# HTTP-Only Experiments (v2 Research)

Testing whether GhostGPT can work without browser automation using pure HTTP + `curl_cffi`.

## Results

### What works via HTTP (no browser needed)
- `/api/auth/session` — session validation
- `/backend-api/gizmos/bootstrap` — list pinned GPTs
- `/backend-api/gizmos/snorlax/sidebar` — list custom GPTs
- `/backend-api/gizmos/search?q=` — search GPT Store
- `/backend-api/models` — list available models (gpt-5-2, gpt-5, o3, etc.)
- `/backend-api/accounts/check/v4-2023-04-27` — account/plan info

### What does NOT work via HTTP
- `/backend-api/conversation` — **403 Forbidden**

### Why conversation fails
The `/backend-api/sentinel/chat-requirements` endpoint reveals two required challenges:

1. **Proof of Work** — SHA3-512 hash puzzle (seed + difficulty). Solvable in Python.
   Reference: https://github.com/leetanshaj/openai-sentinel
2. **Cloudflare Turnstile** — CAPTCHA-like challenge returning an encrypted `dx` blob.
   Much harder to solve without a browser.

Arkose Labs is **not required** for paid accounts (returns `null`).

### Key requirement: `curl_cffi`
Standard `httpx` gets blocked by Cloudflare TLS fingerprinting (all 403s).
`curl_cffi` with `impersonate="chrome131"` bypasses this completely for all endpoints.

## Test Scripts

| Script | What it does |
|--------|-------------|
| `01_extract_token.py` | Opens browser briefly, grabs bearer token + cookies, saves to `token.json` |
| `02_test_api.py` | Tests API with `httpx` (all fail — Cloudflare blocks it) |
| `02b_test_api_curl.py` | Tests API with `curl_cffi` (all pass) |
| `02c_test_requirements.py` | Investigates sentinel requirements (PoW + Turnstile) |
| `03_test_conversation.py` | Attempts to send a prompt via HTTP (fails — needs PoW + Turnstile) |
| `04_test_followup.py` | Follow-up message test (not yet tested, depends on 03) |

## Future v2 Options
1. **Hybrid** — HTTP for read-only (list/search GPTs, models), browser for conversations
2. **Full HTTP** — Solve PoW in Python + find Turnstile bypass
3. **Browser token relay** — Open browser once to solve Turnstile, then use HTTP for everything
