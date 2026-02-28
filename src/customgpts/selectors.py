"""
Centralized CSS selectors for ChatGPT DOM interaction.

All CSS selectors used to interact with the ChatGPT web interface are defined here.
When ChatGPT updates its UI and breaks the scraper, this is the first file to update.

Each element type has:
  - A primary selector (the most reliable/current one)
  - A fallback array (tried in order if the primary fails)

The driver (driver.py) uses _find_visible() to try fallback selectors in order,
providing resilience against ChatGPT UI changes.

Selector sources and references:
  - cbusillo/chatgpt-automation-mcp
  - ugorsahin/TalkingHeads
  - iamseyedalipro/ChatGPTAutomation
  - daily-coding-problem/chatgpt-scraper-lib
  - Michelangelo27/chatgpt_selenium_automation
"""

# ── URLs ──────────────────────────────────────────────────────────────

# Base URL for ChatGPT — all navigation starts here
BASE_URL = "https://chatgpt.com"

# ── Prompt textarea / input ───────────────────────────────────────────
# The text input area where the user types their message.
# Has changed between <textarea> and <div contenteditable="true"> across UI versions.

PROMPT_TEXTAREA = "#prompt-textarea"
PROMPT_FALLBACKS = [
    "#prompt-textarea",
    "textarea#prompt-textarea",
    'div#prompt-textarea[contenteditable="true"]',
    'div[contenteditable="true"]',
    'input[placeholder*="Ask"]',                   # landing page variant
]

# ── Send button ───────────────────────────────────────────────────────
# The button clicked to submit the prompt. Falls back to pressing Enter if not found.

SEND_BUTTON = 'button[data-testid="send-button"]'
SEND_BUTTON_FALLBACKS = [
    'button[data-testid="send-button"]',
    '[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send message"]',
]

# ── Stop button (visible while streaming) ─────────────────────────────
# Appears while ChatGPT is generating a response. Can be clicked to stop generation.

STOP_BUTTON = 'button[data-testid="stop-button"]'
STOP_BUTTON_FALLBACKS = [
    'button[data-testid="stop-button"]',
    '[data-testid="stop-button"]',
    'button:has-text("Stop generating")',
]

# ── Thinking / generation state ───────────────────────────────────────
# Indicators that ChatGPT is actively processing (thinking models like o1).

THINKING_INDICATORS = [
    '[data-testid="thinking-indicator"]',
    '.result-thinking',                              # GPT thinking/reasoning block
    '.animate-pulse',
]

# ── Response completion indicators ────────────────────────────────────
# Action buttons that appear on the last assistant message ONLY after generation
# is complete. The driver checks for these to know when a response is finished.
# These appear within the parent <article> element of each assistant message.

COMPLETION_INDICATORS = [
    'article button[aria-label="Copy"]',
    'article button[aria-label="Read aloud"]',
    'article button[aria-label="Good response"]',
    'article button[aria-label="Bad response"]',
]

# ── Assistant messages ────────────────────────────────────────────────
# Selectors for finding assistant (ChatGPT) response message elements in the DOM.
# The driver counts these to detect when a new response appears and extracts text
# from the last one.

ASSISTANT_MESSAGES = '[data-message-author-role="assistant"]'
ASSISTANT_FALLBACKS = [
    '[data-message-author-role="assistant"]',
    'div[data-message-author-role="assistant"]',
    'main article',                                # newer UI structure
    'div.markdown',                                # rendered markdown content
]

# ── Onboarding / dialog dismiss ──────────────────────────────────────
# Buttons that appear in first-time-use onboarding dialogs. The driver clicks
# these to dismiss them before interacting with the chat interface.

ONBOARDING_BUTTONS = [
    "button:has-text('Okay, let\\'s go')",
    "button:has-text('Okay')",
    "button:has-text('Continue')",
    "button:has-text('Dismiss')",
    "button:has-text('Done')",
    "button:has-text('Stay logged out')",
]

# localStorage keys set via page.evaluate() to suppress onboarding dialogs
# before they even appear. More reliable than clicking dismiss buttons.
ONBOARDING_LOCALSTORAGE_BYPASS = {
    "oai/apps/hasSeenOnboarding/chat": "true",
    "oai/apps/hasUserContextFirstTime/2023-06-29": "true",
}

# ── Login detection ──────────────────────────────────────────────────
# If any of these elements are visible, the user is NOT logged in.
# The driver checks for these after navigation and raises an error.

LOGIN_INDICATORS = [
    'button:has-text("Log in")',
    'button:has-text("Sign up")',
    'input[type="email"]',
]

# ── New chat ─────────────────────────────────────────────────────────
# Button to start a new conversation. Used when navigating away from an existing chat.

NEW_CHAT_BUTTON_FALLBACKS = [
    '[data-testid="create-new-chat-button"]',
    'button:has-text("New chat")',
    '[data-testid="new-chat-button"]',
]

# ── Images in assistant messages ─────────────────────────────────────
# Selectors for finding images generated by DALL-E or included in responses.
# The driver searches for these within assistant message elements.

IMAGE_SELECTORS = [
    'img[src*="oaidalleapi"]',          # DALL-E CDN
    'img[src*="openai"]',               # OpenAI hosted
    'img[src*="blob.core.windows"]',    # Azure blob storage
    'img[alt]',                         # any image with alt text (fallback)
]

# Default directory for downloaded images from DALL-E responses
IMAGE_DOWNLOAD_DIR = "~/.customgpts/images"
