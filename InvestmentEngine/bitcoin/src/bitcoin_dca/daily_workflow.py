"""Shared manual and scheduled recommendation plus Telegram workflow."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .config import RuntimeConfig
from .errors import NotificationError
from .recommendation import RecommendationOutcome, RecommendationService


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.local"
ALLOWED_SECRET_KEYS = frozenset(
    {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "VOLMEX_API_KEY"}
)


def load_secret_env(
    path: Path,
    *,
    environ: dict[str, str] | None = None,
) -> None:
    """Load only approved DCA secret names without overriding the process env."""

    target = os.environ if environ is None else environ
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_SECRET_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            target.setdefault(key, value)


TelegramTransport = Callable[[str, bytes, int], bytes]


def _default_transport(url: str, payload: bytes, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise NotificationError(
            f"Telegram sendMessage returned HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise NotificationError("Telegram sendMessage connection failed") from None


class TelegramNotifier:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        transport: TelegramTransport | None = None,
        timeout_seconds: int = 15,
    ):
        if not bot_token or not chat_id:
            raise NotificationError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured"
            )
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._transport = transport or _default_transport
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        transport: TelegramTransport | None = None,
    ) -> "TelegramNotifier":
        source = os.environ if environ is None else environ
        return cls(
            bot_token=source.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=source.get("TELEGRAM_CHAT_ID", ""),
            transport=transport,
        )

    def send(self, message: str) -> None:
        payload = urllib.parse.urlencode(
            {
                "chat_id": self._chat_id,
                "text": message,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            body = self._transport(url, payload, self._timeout_seconds)
        except NotificationError:
            raise
        except Exception:
            raise NotificationError("Telegram sendMessage failed") from None
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NotificationError("Telegram returned an invalid JSON response") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise NotificationError("Telegram rejected the notification")


def format_recommendation_message(outcome: RecommendationOutcome) -> str:
    decision = outcome.decision
    amount = decision.get("final_suggested_usd")
    amount_text = "不可執行" if amount is None else f"{amount} USD"
    remaining = decision.get("remaining_to_execute_today_usd")
    remaining_text = "N/A" if remaining is None else f"{remaining} USD"
    reason_codes = ", ".join(decision.get("reason_codes", [])) or "none"
    return "\n".join(
        (
            f"Bitcoin Smart DCA｜{decision['plan_date']}",
            f"狀態：{decision['decision_status']}",
            f"今日建議投入：{amount_text}",
            f"今日尚待執行：{remaining_text}",
            f"原因代碼：{reason_codes}",
            f"Decision revision：{decision['revision']}",
            "參數仍為 draft；這是決策建議，不是自動下單。",
            "成交後請回報：投入 USD＋實收 BTC。",
        )
    )


@dataclass(frozen=True)
class DailyWorkflowResult:
    recommendation: RecommendationOutcome
    notification_message: str


class DailyWorkflowService:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        notifier: TelegramNotifier,
        recommendation: RecommendationService | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.notifier = notifier
        self.recommendation = recommendation or RecommendationService(
            config,
            environ=environ,
        )

    def run(self, *, now: datetime | None = None) -> DailyWorkflowResult:
        try:
            outcome = self.recommendation.recommend(now=now)
        except Exception as exc:
            try:
                self.notifier.send(
                    "Bitcoin Smart DCA 執行失敗\n"
                    f"錯誤類型：{type(exc).__name__}\n"
                    "請開啟 Codex 檢查；未宣稱 recommendation 成功。"
                )
            except NotificationError:
                pass
            raise
        message = format_recommendation_message(outcome)
        self.notifier.send(message)
        return DailyWorkflowResult(
            recommendation=outcome,
            notification_message=message,
        )
