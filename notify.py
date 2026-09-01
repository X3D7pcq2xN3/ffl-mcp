"""Send the weekly digest to Telegram.

Telegram is the delivery layer because a local Android notification fails
silently when the OS kills the process -- and a scheduled job whose only
output is a notification you never see is worse than no job at all. This
module treats delivery as something that can fail and says so.

Setup:
  1. Message @BotFather, /newbot, copy the token.
  2. Send your new bot any message.
  3. GET https://api.telegram.org/bot<TOKEN>/getUpdates and read
     result[0].message.chat.id
  4. Put both in .env (already gitignored):
       TELEGRAM_BOT_TOKEN=...
       TELEGRAM_CHAT_ID=...
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096  # Telegram's per-message limit


def load_env(path: Path | None = None) -> None:
    """Minimal .env reader -- avoids a dependency for four lines of parsing."""
    path = path or Path(__file__).parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _credentials() -> tuple[str, str]:
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env "
            "or the environment"
        )
    return token, chat_id


def _chunk(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on paragraph boundaries so a long digest stays readable."""
    if len(text) <= limit:
        return [text]

    chunks, current = [], ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > limit:
            if current:
                chunks.append(current.rstrip())
            current = ""
            while len(block) > limit:  # single oversized block
                chunks.append(block[:limit])
                block = block[limit:]
        current += block + "\n\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def send(text: str, silent: bool = False, markdown: bool = True) -> list[dict]:
    """Send a message, splitting if needed. Raises on delivery failure.

    A scheduled job should let this raise -- a swallowed exception here means
    you believe you were notified when you weren't.
    """
    token, chat_id = _credentials()
    url = API.format(token=token, method="sendMessage")
    results = []

    for chunk in _chunk(text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_notification": silent,
        }
        if markdown:
            payload["parse_mode"] = "Markdown"

        resp = requests.post(url, data=payload, timeout=30)
        body = resp.json() if resp.content else {}

        if not body.get("ok"):
            # Markdown parse errors are common with player names containing
            # underscores or asterisks. Retry once as plain text rather than
            # losing the digest entirely.
            if markdown and "parse" in str(body.get("description", "")).lower():
                payload.pop("parse_mode")
                resp = requests.post(url, data=payload, timeout=30)
                body = resp.json() if resp.content else {}

        if not body.get("ok"):
            raise RuntimeError(
                f"Telegram delivery failed (HTTP {resp.status_code}): "
                f"{body.get('description', resp.text[:200])}"
            )
        results.append(body)

    return results


def send_failure(context: str, error: Exception) -> None:
    """Report that the digest itself failed.

    Silence is ambiguous -- it could mean 'no moves needed'. This makes the
    difference explicit. Deliberately swallows its own errors; if Telegram is
    also down there is nothing left to try.
    """
    try:
        send(f"ffl digest FAILED during {context}\n\n{type(error).__name__}: {error}",
             markdown=False)
    except Exception:
        pass


def whoami() -> dict:
    """Verify the token works and report the bot identity."""
    token, _ = _credentials()
    resp = requests.get(API.format(token=token, method="getMe"), timeout=30)
    return resp.json()


if __name__ == "__main__":
    import sys

    if "--whoami" in sys.argv:
        print(whoami())
        raise SystemExit

    sample = (
        "*Week 3* — 2 issues\n\n"
        "*START* Doe (RB, 11.2) over Smith (RB, 6.1)\n"
        "Smith on bye. Doe rostered in 34% of leagues.\n\n"
        "*BYE HOLE* FLEX empty\n"
        "Best available: Jones (WR, 8.9) — on waivers until 11:59p PT tonight\n\n"
        "*WATCH* Brown (Q) — inactive would cost you 9 pts"
    )
    send(sample)
    print("sent")
