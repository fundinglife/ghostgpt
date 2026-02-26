import json
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".ghostgpt" / "config.json"

DEFAULT_CONFIG = {
    "default_gpt": None,
    "gpts": {},
}


def load_config() -> dict:
    """Load config from ~/.ghostgpt/config.json, returning defaults if missing."""
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Write config to ~/.ghostgpt/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_gpt(name: Optional[str], config: Optional[dict] = None) -> Optional[str]:
    """Resolve a GPT nickname or raw ID to a gpt_id.

    Priority:
      1. If name looks like a raw ID (starts with 'g-'), use it directly.
      2. If name is a saved nickname, return the mapped ID.
      3. If name is None, use default_gpt from config (resolved as nickname).
      4. Otherwise return None (use regular ChatGPT).
    """
    if config is None:
        config = load_config()

    if name is None:
        # Use default if set
        default = config.get("default_gpt")
        if default:
            return config.get("gpts", {}).get(default, default)
        return None

    # Raw ID passthrough
    if name.startswith("g-"):
        return name

    # Nickname lookup
    gpt_id = config.get("gpts", {}).get(name)
    if gpt_id:
        return gpt_id

    # Not found
    return None
