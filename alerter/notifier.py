"""
Notifiers are the "how do we tell the user" part of the app. Each one knows how
to deliver a text message somewhere (Telegram, the console, ...).

They all share the same tiny interface — a single ``send(text)`` method — so
the rest of the code can send an alert without caring where it ends up. To add
a new destination (Discord, Slack, email, ntfy.sh, push, ...), subclass
``Notifier`` and implement ``send()``.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import requests

log = logging.getLogger("alerter.notifier")


class Notifier(ABC):
    """Base class: anything that can deliver an alert message.

    ABC = "Abstract Base Class" — you can't use it directly; it just defines
    the contract that every real notifier must follow."""

    @abstractmethod
    def send(self, text: str) -> None:
        """Deliver one message. Subclasses fill in the actual delivery."""
        ...


class TelegramNotifier(Notifier):
    """
    Sends to one or more Telegram chats.

    TELEGRAM_CHAT_ID can be a single ID ("123456") or several comma-separated
    IDs ("123456,789012"). Each recipient must have started a chat with the
    bot first (sent any message), otherwise Telegram will refuse delivery.
    """

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self.token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        raw = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.chat_ids = [c.strip() for c in raw.split(",") if c.strip()]

    def send(self, text: str) -> None:
        if not self.token or not self.chat_ids:
            log.warning("Telegram not configured — would have sent:\n%s", text)
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        for chat_id in self.chat_ids:
            try:
                r = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=10,
                )
                r.raise_for_status()
            except Exception as e:
                log.error("Telegram send to %s failed: %s", chat_id, e)


class ConsoleNotifier(Notifier):
    """Prints to stdout — useful for local testing without spamming Telegram."""

    def send(self, text: str) -> None:
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60 + "\n")


class MultiNotifier(Notifier):
    """Fan-out: send to several notifiers at once."""

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def send(self, text: str) -> None:
        for n in self.notifiers:
            n.send(text)
