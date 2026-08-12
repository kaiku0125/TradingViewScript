from __future__ import annotations

import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path


BITCOIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BITCOIN_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.cli import build_parser
from bitcoin_dca.daily_workflow import (
    DailyWorkflowService,
    TelegramNotifier,
    format_recommendation_message,
    load_secret_env,
)
from bitcoin_dca.errors import NotificationError
from bitcoin_dca.recommendation import RecommendationOutcome


def outcome() -> RecommendationOutcome:
    return RecommendationOutcome(
        snapshot={"cutoff_at": "2026-08-12T21:00:00+08:00"},
        decision={
            "plan_date": "2026-08-12",
            "decision_status": "normal",
            "final_suggested_usd": "174.36",
            "remaining_to_execute_today_usd": "174.36",
            "reason_codes": ["BUDGET_GUARD_APPLIED"],
            "revision": 1,
        },
        weekly_target={"weekly_target_id": "target-1"},
        created_weekly_target=True,
        reused_orphan_snapshot=False,
    )


class _Recommendation:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error
        self.calls = 0

    def recommend(self, *, now=None):
        del now
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


class _Notifier:
    def __init__(self):
        self.messages: list[str] = []

    def send(self, message: str) -> None:
        self.messages.append(message)


class DailyTelegramTest(unittest.TestCase):
    def test_load_secret_env_accepts_only_approved_keys(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env.local"
            path.write_text(
                "TELEGRAM_BOT_TOKEN='bot-secret'\n"
                "TELEGRAM_CHAT_ID=123\n"
                "VOLMEX_API_KEY=volmex-secret\n"
                "UNRELATED_SECRET=must-not-load\n",
                encoding="utf-8",
            )
            environment = {"TELEGRAM_CHAT_ID": "existing"}
            load_secret_env(path, environ=environment)
        self.assertEqual(environment["TELEGRAM_BOT_TOKEN"], "bot-secret")
        self.assertEqual(environment["TELEGRAM_CHAT_ID"], "existing")
        self.assertEqual(environment["VOLMEX_API_KEY"], "volmex-secret")
        self.assertNotIn("UNRELATED_SECRET", environment)

    def test_notifier_posts_form_encoded_message(self) -> None:
        captured = {}

        def transport(url: str, payload: bytes, timeout: int) -> bytes:
            captured.update(url=url, payload=payload, timeout=timeout)
            return b'{"ok":true}'

        TelegramNotifier(
            bot_token="bot-secret",
            chat_id="chat-123",
            transport=transport,
        ).send("hello BTC")
        form = urllib.parse.parse_qs(captured["payload"].decode("utf-8"))
        self.assertEqual(form["chat_id"], ["chat-123"])
        self.assertEqual(form["text"], ["hello BTC"])
        self.assertIn("botbot-secret/sendMessage", captured["url"])

    def test_notifier_errors_never_expose_the_bot_token(self) -> None:
        def transport(url: str, payload: bytes, timeout: int) -> bytes:
            del url, payload, timeout
            raise RuntimeError("request contained bot-secret")

        notifier = TelegramNotifier(
            bot_token="bot-secret",
            chat_id="chat-123",
            transport=transport,
        )
        with self.assertRaises(NotificationError) as caught:
            notifier.send("hello")
        self.assertNotIn("bot-secret", str(caught.exception))

    def test_missing_telegram_credentials_fail_before_workflow(self) -> None:
        with self.assertRaises(NotificationError):
            TelegramNotifier.from_environment({})

    def test_daily_workflow_sends_the_saved_recommendation(self) -> None:
        recommendation = _Recommendation(outcome())
        notifier = _Notifier()
        result = DailyWorkflowService(
            object(),
            notifier=notifier,
            recommendation=recommendation,
        ).run()
        self.assertEqual(recommendation.calls, 1)
        self.assertEqual(result.recommendation, outcome())
        self.assertEqual(notifier.messages, [result.notification_message])
        self.assertIn("今日建議投入：174.36 USD", result.notification_message)
        self.assertIn("不是自動下單", result.notification_message)

    def test_recommendation_failure_sends_only_safe_error_type(self) -> None:
        notifier = _Notifier()
        service = DailyWorkflowService(
            object(),
            notifier=notifier,
            recommendation=_Recommendation(
                error=RuntimeError("provider URL contained bot-secret")
            ),
        )
        with self.assertRaises(RuntimeError):
            service.run()
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("RuntimeError", notifier.messages[0])
        self.assertNotIn("bot-secret", notifier.messages[0])

    def test_message_handles_blocked_decision_without_amount(self) -> None:
        blocked = outcome()
        blocked.decision["decision_status"] = "blocked"
        blocked.decision["final_suggested_usd"] = None
        self.assertIn("今日建議投入：不可執行", format_recommendation_message(blocked))

    def test_cli_exposes_shared_run_daily_command(self) -> None:
        args = build_parser().parse_args(["run-daily", "--env-file", ".env.local"])
        self.assertEqual(args.command, "run-daily")
        self.assertEqual(args.env_file, Path(".env.local"))
        recommend = build_parser().parse_args(["recommend"])
        self.assertEqual(recommend.command, "recommend")
        self.assertTrue(str(recommend.env_file).endswith(".env.local"))
        telegram = build_parser().parse_args(["test-telegram"])
        self.assertEqual(telegram.command, "test-telegram")


if __name__ == "__main__":
    unittest.main()
