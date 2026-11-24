"""Send messages and videos to Rishabh's Telegram chat through a bot.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (GitHub secrets). Errors are
re-raised without the web address, because the address contains the token.
"""
import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4096
MAX_CAPTION = 1024
MAX_VIDEO_BYTES = 50 * 1000 * 1000  # bot upload limit


def _settings():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat


def configured():
    return all(_settings())


def _post(method, data, files=None):
    token, chat = _settings()
    data = dict(data, chat_id=chat)
    try:
        resp = requests.post(API.format(token=token, method=method),
                             data=data, files=files, timeout=300)
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        # "from None" drops the original error, whose text holds the token.
        raise RuntimeError(
            f"Telegram {method} failed ({type(exc).__name__})") from None
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} refused: "
                           f"{body.get('description', 'unknown error')}")
    return body


def split_text(text, limit=MAX_TEXT):
    """Split long text on line breaks so each piece fits one message."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    if current.strip():
        parts.append(current)
    return parts


def send_message(text):
    if not configured():
        print("[telegram] not configured, message was:\n" + text)
        return
    for part in split_text(text):
        _post("sendMessage", {"text": part, "disable_web_page_preview": "true"})


def send_video(path, caption=""):
    """Send a video file. Returns False (sends nothing) if it is too big."""
    if not configured():
        print(f"[telegram] not configured, would send {path}")
        return True
    if os.path.getsize(path) > MAX_VIDEO_BYTES:
        return False
    with open(path, "rb") as fh:
        _post("sendVideo",
              {"caption": caption[:MAX_CAPTION], "supports_streaming": "true",
               "width": "1080", "height": "1920"},
              files={"video": (os.path.basename(path), fh, "video/mp4")})
    return True
