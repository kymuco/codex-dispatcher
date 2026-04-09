from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


MAX_TELEGRAM_TEXT = 4096


class TelegramApiError(RuntimeError):
    pass


@dataclass
class TelegramClient:
    token: str

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def _post(self, method: str, payload: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            url=f"{self.base_url}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="replace")
            raise TelegramApiError(f"Telegram API HTTP error: {exc.code} {error_text}") from exc
        except urllib.error.URLError as exc:
            raise TelegramApiError(f"Telegram API connection error: {exc}") from exc

        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramApiError(f"Telegram API returned an error payload: {body}")
        return body["result"]

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout_seconds}
        if offset is not None:
            payload["offset"] = offset
        result = self._post("getUpdates", payload)
        return result if isinstance(result, list) else []

    def set_my_commands(self, *, commands: list[dict[str, str]]) -> None:
        self._post("setMyCommands", {"commands": commands})

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        chunks = self._chunk_text(text)
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }
            if reply_to_message_id is not None and index == 0:
                payload["reply_to_message_id"] = reply_to_message_id
            if reply_markup is not None and index == 0:
                payload["reply_markup"] = reply_markup
            self._post("sendMessage", payload)

    def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        self._post("answerCallbackQuery", payload)

    def clear_inline_keyboard(self, *, chat_id: int, message_id: int) -> None:
        self._post(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            },
        )

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        text = text or ""
        if len(text) <= MAX_TELEGRAM_TEXT:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            piece = remaining[:MAX_TELEGRAM_TEXT]
            split_at = piece.rfind("\n")
            if split_at < MAX_TELEGRAM_TEXT // 2:
                split_at = MAX_TELEGRAM_TEXT
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        return chunks
