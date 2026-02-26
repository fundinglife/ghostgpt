"""
Centralized CSS selectors for ChatGPT DOM interaction.
Sources: cbusillo/chatgpt-automation-mcp, ugorsahin/TalkingHeads,
         iamseyedalipro/ChatGPTAutomation, daily-coding-problem/chatgpt-scraper-lib,
         Michelangelo27/chatgpt_selenium_automation
"""

# ── URLs ──────────────────────────────────────────────────────────────
BASE_URL = "https://chatgpt.com"

# ── Prompt textarea / input ───────────────────────────────────────────
PROMPT_TEXTAREA = "#prompt-textarea"
PROMPT_FALLBACKS = [
    "#prompt-textarea",
    "textarea#prompt-textarea",
    'div#prompt-textarea[contenteditable="true"]',
    'div[contenteditable="true"]',
    'input[placeholder*="Ask"]',                   # landing page variant
]

# ── Send button ───────────────────────────────────────────────────────
SEND_BUTTON = 'button[data-testid="send-button"]'
SEND_BUTTON_FALLBACKS = [
    'button[data-testid="send-button"]',
    '[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send message"]',
]

# ── Stop button (visible while streaming) ─────────────────────────────
STOP_BUTTON = 'button[data-testid="stop-button"]'
STOP_BUTTON_FALLBACKS = [
    'button[data-testid="stop-button"]',
    '[data-testid="stop-button"]',
    'button:has-text("Stop generating")',
]

# ── Thinking / generation state ───────────────────────────────────────
THINKING_INDICATORS = [
    '[data-testid="thinking-indicator"]',
    '.animate-pulse',
]

# ── Response completion indicators ────────────────────────────────────
# These action buttons appear on the last assistant message once generation finishes.
COMPLETION_INDICATORS = [
    'article button[aria-label="Copy"]',
    'article button[aria-label="Read aloud"]',
    'article button[aria-label="Good response"]',
    'article button[aria-label="Bad response"]',
]

# ── Assistant messages ────────────────────────────────────────────────
ASSISTANT_MESSAGES = '[data-message-author-role="assistant"]'
ASSISTANT_FALLBACKS = [
    '[data-message-author-role="assistant"]',
    'div[data-message-author-role="assistant"]',
    'main article',                                # newer UI structure
    'div.markdown',                                # rendered markdown content
]

# ── Onboarding / dialog dismiss ──────────────────────────────────────
ONBOARDING_BUTTONS = [
    "button:has-text('Okay, let\\'s go')",
    "button:has-text('Okay')",
    "button:has-text('Continue')",
    "button:has-text('Dismiss')",
    "button:has-text('Done')",
    "button:has-text('Stay logged out')",
]

# localStorage keys to bypass onboarding (set via page.evaluate)
ONBOARDING_LOCALSTORAGE_BYPASS = {
    "oai/apps/hasSeenOnboarding/chat": "true",
    "oai/apps/hasUserContextFirstTime/2023-06-29": "true",
}

# ── Login detection ──────────────────────────────────────────────────
LOGIN_INDICATORS = [
    'button:has-text("Log in")',
    'button:has-text("Sign up")',
    'input[type="email"]',
]

# ── New chat ─────────────────────────────────────────────────────────
NEW_CHAT_BUTTON_FALLBACKS = [
    '[data-testid="create-new-chat-button"]',
    'button:has-text("New chat")',
    '[data-testid="new-chat-button"]',
]
