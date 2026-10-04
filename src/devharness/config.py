"""Settings: real environment variables first, then ~/.agents/env."""

import os
from pathlib import Path

ENV_FILE = Path.home() / ".agents" / "env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


BASE_URL = os.environ.get("BASE_URL_GAP", "https://api.gapgpt.app/v1")
MODEL = os.environ.get("MODEL_GAP", "deepseek-v4-flash")
API_KEY = os.environ["API_Key_GAP"]

if __name__ == "__main__":
    print(BASE_URL, API_KEY, MODEL)