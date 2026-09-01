#!/usr/bin/env python3
"""Scaffold and verify the local environment.

Creates .env from a template if missing, then checks each credential against
the service it belongs to. Run it after cloning, after rotating a key, or any
time the digest fails in a way that smells like auth.

  python setup_env.py          check what's configured
  python setup_env.py --init   write a .env template if none exists
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ENV_PATH = Path(__file__).parent / ".env"

TEMPLATE = """# Telegram delivery -- from @BotFather, and getUpdates for the chat id
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Anthropic API -- console.anthropic.com
ANTHROPIC_API_KEY=

# Yahoo Fantasy -- pending API access approval
YAHOO_CLIENT_ID=
YAHOO_CLIENT_SECRET=
YAHOO_REFRESH_TOKEN=
YAHOO_LEAGUE_KEY=
"""


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def init() -> None:
    if ENV_PATH.exists():
        print(f".env already exists at {ENV_PATH} -- leaving it alone")
        return
    ENV_PATH.write_text(TEMPLATE)
    ENV_PATH.chmod(0o600)
    print(f"wrote {ENV_PATH} (mode 600) -- fill it in")


def check_gitignore() -> tuple[bool, str]:
    gi = Path(__file__).parent / ".gitignore"
    if not gi.exists():
        return False, "no .gitignore"
    if ".env" not in gi.read_text():
        return False, ".env NOT ignored -- fix before committing"
    return True, "ignored"


def check_telegram() -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        return False, "TELEGRAM_BOT_TOKEN not set"
    if not chat:
        return False, "TELEGRAM_CHAT_ID not set"
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=20)
        body = r.json()
    except Exception as exc:
        return False, f"request failed: {exc}"
    if not body.get("ok"):
        return False, f"rejected: {body.get('description')}"
    return True, f"@{body['result']['username']}, chat {chat}"


def check_anthropic() -> tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return False, "ANTHROPIC_API_KEY not set"
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-6", "max_tokens": 4,
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=30,
        )
    except Exception as exc:
        return False, f"request failed: {exc}"
    if r.status_code == 200:
        return True, "key valid"
    body = r.json() if r.content else {}
    return False, (f"HTTP {r.status_code}: "
                   f"{body.get('error', {}).get('message', r.text[:120])}")


def check_yahoo() -> tuple[bool, str]:
    have = [k for k in ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET",
                        "YAHOO_REFRESH_TOKEN", "YAHOO_LEAGUE_KEY")
            if os.environ.get(k)]
    if not have:
        return False, "not configured (pending API access approval)"
    missing = [k for k in ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET",
                           "YAHOO_REFRESH_TOKEN", "YAHOO_LEAGUE_KEY")
               if not os.environ.get(k)]
    if missing:
        return False, f"partial -- missing {', '.join(missing)}"
    return True, "configured (token exchange untested)"


CHECKS = [
    (".gitignore", check_gitignore, True),
    ("telegram", check_telegram, True),
    ("anthropic", check_anthropic, True),
    ("yahoo", check_yahoo, False),   # not required yet
]


def main() -> int:
    if "--init" in sys.argv:
        init()
        return 0

    if not ENV_PATH.exists():
        print("no .env found -- run: python setup_env.py --init")
        return 1

    load_env()
    print(f"reading {ENV_PATH}\n")

    required_failed = False
    for name, fn, required in CHECKS:
        ok, detail = fn()
        mark = "ok  " if ok else ("FAIL" if required else "--  ")
        print(f"  {mark} {name:12} {detail}")
        if required and not ok:
            required_failed = True

    print()
    if required_failed:
        print("not ready -- fix the failures above")
        return 1
    print("ready. try: python digest.py --ask")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
