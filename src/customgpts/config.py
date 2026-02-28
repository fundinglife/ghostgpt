"""
GPT nickname configuration management.

Manages a JSON config file at ~/.customgpts/config.json that stores:
  - GPT nicknames: short names mapped to GPT IDs (e.g., "teacher" -> "g-XXXXX")
  - Default GPT: the nickname to use when --gpt is not specified

Config file format:
    {
        "default_gpt": "teacher",
        "gpts": {
            "teacher": "g-abc123",
            "coder": "g-def456"
        }
    }
"""

import json
from pathlib import Path
from typing import Optional

# Config file location — alongside the browser profile in ~/.customgpts/
CONFIG_PATH = Path.home() / ".customgpts" / "config.json"

# Default config when no config file exists or it's corrupted
DEFAULT_CONFIG = {
    "default_gpt": None,
    "gpts": {},
}


def load_config() -> dict:
    """Load the configuration from disk.

    Reads and parses ~/.customgpts/config.json. Returns a copy of DEFAULT_CONFIG
    if the file doesn't exist or can't be parsed.

    Returns:
        dict: The configuration dictionary with "default_gpt" and "gpts" keys.
    """
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Write the configuration to disk.

    Creates the parent directory (~/.customgpts/) if it doesn't exist. Writes
    the config as pretty-printed JSON with UTF-8 encoding.

    Args:
        config: The configuration dictionary to save. Should contain "default_gpt"
                and "gpts" keys.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_gpt(name: Optional[str], config: Optional[dict] = None) -> Optional[str]:
    """Resolve a GPT name (nickname or raw ID) to a GPT identifier.

    Resolution priority:
      1. If name starts with "g-", it's a raw GPT ID — return it directly.
      2. If name is a saved nickname in config, return the mapped GPT ID.
      3. If name is None, check for a default GPT in config and resolve it.
      4. Otherwise, return None (use regular ChatGPT without a custom GPT).

    Args:
        name: A GPT nickname (e.g., "teacher"), a raw GPT ID (e.g., "g-XXXXX"),
              or None to use the default.
        config: Optional pre-loaded config dict. If None, loads from disk.

    Returns:
        str | None: The resolved GPT ID (e.g., "g-XXXXX"), or None if no GPT
                    should be used (fall back to regular ChatGPT).
    """
    if config is None:
        config = load_config()

    if name is None:
        # Use default if set
        default = config.get("default_gpt")
        if default:
            return config.get("gpts", {}).get(default, default)
        return None

    # Raw ID passthrough (e.g., "g-abc123")
    if name.startswith("g-"):
        return name

    # Nickname lookup
    gpt_id = config.get("gpts", {}).get(name)
    if gpt_id:
        return gpt_id

    # Not found
    return None
