"""Trouve tout seul le chat_id Telegram, pour ne pas avoir à le chercher à la main."""
from __future__ import annotations

import re
from pathlib import Path

from .http import Session


def find_chat_id(token: str, session: Session | None = None,
                 wait: int = 0) -> tuple[str, str] | None:
    """Renvoie (chat_id, nom) de la dernière personne qui a écrit au bot.

    `wait` > 0 : si aucun message n'est en attente, Telegram garde la requête
    ouverte jusqu'à `wait` secondes et répond dès qu'un message arrive.
    """
    session = session or Session(min_delay=0, timeout=wait + 15)
    params = {"timeout": wait} if wait else None
    data = session.get_json(f"https://api.telegram.org/bot{token}/getUpdates", params=params)
    for update in reversed(data.get("result", [])):
        for key in ("message", "edited_message", "my_chat_member", "channel_post"):
            chat = (update.get(key) or {}).get("chat")
            if chat and "id" in chat:
                name = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
                return str(chat["id"]), name
    return None


def save_chat_id(config_path: str | Path, chat_id: str) -> bool:
    """Écrit chat_id dans la section [telegram] de config.toml."""
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r'(\[telegram\][^\[]*?^chat_id\s*=\s*)"[^"\n]*"', re.M | re.S)
    new, n = pattern.subn(lambda m: f'{m.group(1)}"{chat_id}"', text, count=1)
    if n:
        path.write_text(new, encoding="utf-8")
    return bool(n)
