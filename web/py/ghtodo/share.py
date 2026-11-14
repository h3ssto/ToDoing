"""Share key: lets a second device sign in without repeating the GitHub setup. It carries the access token (there is no server
to hold it), so treat it like a password. Format: `todoing1.` + urlsafe-base64(json). A full share link (`...#join=<key>`)
or a bare token is accepted too."""
from __future__ import annotations

import base64
import json

PREFIX = "todoing1."


def encode(token: str) -> str:
    raw = json.dumps({"t": token}, separators=(",", ":")).encode()
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(text: str) -> str:
    """-> token. Accepts a share key, a share link, or a plain token. Raises ValueError for a damaged key."""
    s = (text or "").strip()
    if "#join=" in s:
        s = s.split("#join=", 1)[1]
    if not s.startswith(PREFIX):
        return s
    body = s[len(PREFIX):]
    try:
        tok = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["t"]
    except Exception as e:
        raise ValueError("share key is damaged") from e
    if not isinstance(tok, str) or not tok:
        raise ValueError("share key is damaged")
    return tok
