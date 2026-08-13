"""Command-line interface for the local manual Smart DCA MVP."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .config import DEFAULT_CONFIG_PATH, load_config
from .daily_workflow import (
    DEFAULT_ENV_FILE,
    DailyWorkflowService,
    TelegramNotifier,
    load_secret_env,
)
from .errors import (
    BitcoinDcaError,
    ConfigError,
    JournalValidationError,
    LockUnavailableError,
    OperationCancelled,
    UserInputError,
)
from .ledger import JournalService, PortfolioState
from .recommendation import RecommendationOutcome
from .rehearsal import run_first_day_rehearsal
from .reporting import ReporterService
from .storage import JournalStore


def _confirm(preview: dict, *, assume_yes: bool) -> bool:
    print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
    if assume_yes:
        return True
    answer = input("Append this event to the canonical Journal? Type yes: ")
    return answer.strip().lower() == "yes"


def _print_state(state: PortfolioState) -> None:
    payload = state.as_dict()
    print("PortfolioState")
    for key in (
        "actual_invested_usd",
        "remaining_funds_usd",
        "total_btc",
        "average_cost_usd",
        "actual_invested_today_usd",
        "actual_invested_this_week_usd",
        "effective_purchase_count",
        "data_status",
        "latest_execution_id",
        "latest_day_close_reason",
        "as_of",
    ):
        print(f"  {key}: {payload[key]}")


def _print_recommendation(outcome: RecommendationOutcome) -> None:
    decision = outcome.decision
    snapshot = outcome.snapshot
    print("Smart DCA recommendation (draft parameters; not a trade)")
    print(f"  plan_date: {decision['plan_date']}")
    print(f"  cutoff_at: {snapshot['cutoff_at']}")
    print(f"  config_version: {decision['config_version']}")
    print(f"  decision_status: {decision['decision_status']}")
    print(f"  final_suggested_usd: {decision['final_suggested_usd']}")
    print(
        "  remaining_to_execute_today_usd: "
        f"{decision['remaining_to_execute_today_usd']}"
    )
    print(f"  reason_codes: {', '.join(decision['reason_codes']) or 'none'}")
    print(f"  snapshot_id: {snapshot['snapshot_id']}")
    print(f"  decision_revision_id: {decision['revision_id']}")
    print(f"  weekly_target_id: {outcome.weekly_target['weekly_target_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dca.py",
        description="Bitcoin Smart DCA local manual MVP",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="versioned machine config path",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    purchase = subparsers.add_parser(
        "record-purchase", help="append a manually executed BTC purchase"
    )
    purchase.add_argument("--usd", required=True, help="total USD paid")
    purchase.add_argument("--btc", required=True, help="net BTC received")
    purchase.add_argument(
        "--plan-date",
        type=date.fromisoformat,
        help="DCA recommendation date (YYYY-MM-DD); defaults to execution date",
    )
    purchase.add_argument(
        "--executed-at",
        type=datetime.fromisoformat,
        help="actual execution timestamp with UTC offset; defaults to record time",
    )
    purchase.add_argument("--note")
    purchase.add_argument(
        "--yes", action="store_true", help="skip interactive confirmation"
    )

    correction = subparsers.add_parser(
        "correct-purchase", help="append reversal and replacement events"
    )
    correction.add_argument("--execution-id", required=True)
    correction.add_argument("--usd", required=True, help="correct total USD paid")
    correction.add_argument("--btc", required=True, help="correct net BTC received")
    correction.add_argument("--note")
    correction.add_argument(
        "--yes", action="store_true", help="skip interactive confirmation"
    )

    close_day = subparsers.add_parser(
        "close-day", help="explicitly skip or complete the current plan day"
    )
    close_day.add_argument(
        "--reason", choices=("skipped", "completed_for_day"), required=True
    )
    close_day.add_argument("--note")
    close_day.add_argument(
        "--yes", action="store_true", help="skip interactive confirmation"
    )

    subparsers.add_parser("status", help="show derived local portfolio state")
    subparsers.add_parser("validate", help="validate canonical JSONL datasets")
    recommend = subparsers.add_parser(
        "recommend", help="fetch cutoff-qualified data and save today's recommendation"
    )
    recommend.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="local secret env file containing Telegram credentials",
    )
    daily = subparsers.add_parser(
        "run-daily",
        help="save today's recommendation and deliver the same result to Telegram",
    )
    daily.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="local secret env file containing Telegram credentials",
    )
    telegram_test = subparsers.add_parser(
        "test-telegram",
        help="send one non-financial Telegram configuration test message",
    )
    telegram_test.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="local secret env file containing Telegram credentials",
    )
    report = subparsers.add_parser(
        "report", help="derive a deterministic Markdown report from the Journal"
    )
    report.add_argument("kind", choices=("daily", "weekly", "monthly"))
    report.add_argument("--date", help="reference plan date in YYYY-MM-DD form")
    report.add_argument(
        "--stdout", action="store_true", help="print without writing a report file"
    )
    subparsers.add_parser(
        "rehearse-first-day",
        help="run an isolated fixed-data first-day workflow without formal writes",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    service = JournalService(config)

    if args.command == "validate":
        counts = service.validate()
        print("Journal valid")
        for dataset, count in sorted(counts.items()):
            print(f"  {dataset}: {count}")
        warnings = service.validation_warnings()
        for warning in warnings:
            print(f"  warning: {warning}")
        return 0

    if args.command == "status":
        service.validate()
        _print_state(service.portfolio_state())
        store = JournalStore(config)
        with store.lock(exclusive=False):
            decisions = store.read_dataset("decisions")
        if decisions:
            latest = decisions[-1]
            print(f"  latest_decision_status: {latest['decision_status']}")
            print(f"  latest_final_suggested_usd: {latest['final_suggested_usd']}")
            print(f"  latest_decision_plan_date: {latest['plan_date']}")
        else:
            print("  latest_decision_status: none")
        return 0

    if args.command in {"recommend", "run-daily"}:
        load_secret_env(args.env_file)
        result = DailyWorkflowService(
            config,
            notifier=TelegramNotifier.from_environment(),
        ).run()
        _print_recommendation(result.recommendation)
        print("  telegram_notification: delivered")
        return result.recommendation.exit_code

    if args.command == "test-telegram":
        load_secret_env(args.env_file)
        notifier = TelegramNotifier.from_environment()
        tested_at = datetime.now(config.timezone).isoformat(timespec="seconds")
        notifier.send(
            "Bitcoin Smart DCA Telegram 測試成功\n"
            f"時間：{tested_at}\n"
            "這不是投資建議，也沒有執行 recommendation。"
        )
        print("Telegram test notification delivered")
        return 0

    if args.command == "report":
        try:
            reference_date = None if args.date is None else date.fromisoformat(args.date)
        except ValueError as exc:
            raise UserInputError("report --date must be YYYY-MM-DD") from exc
        result = ReporterService(config).generate(
            args.kind,
            reference_date=reference_date,
            write=not args.stdout,
        )
        if args.stdout:
            print(result.content, end="" if result.content.endswith("\n") else "\n")
        else:
            print(f"Generated {result.kind} report: {result.output_path}")
            print(f"  period: {result.period_start}..{result.period_end}")
            print(f"  watermark: {result.watermark}")
        return 0

    if args.command == "rehearse-first-day":
        outcome = run_first_day_rehearsal(config)
        print("Gate 4A-4 first-day rehearsal passed")
        print(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    callback = lambda preview: _confirm(preview, assume_yes=args.yes)
    if args.command == "record-purchase":
        record, state = service.record_purchase(
            usd=args.usd,
            btc=args.btc,
            plan_date=args.plan_date,
            executed_at=args.executed_at,
            note=args.note,
            confirm=callback,
        )
        print(f"Appended purchase {record['execution_id']}")
        _print_state(state)
        return 0

    if args.command == "correct-purchase":
        records, state = service.correct_purchase(
            execution_id=args.execution_id,
            usd=args.usd,
            btc=args.btc,
            note=args.note,
            confirm=callback,
        )
        print(
            "Appended correction "
            f"reversal={records[0]['execution_id']} "
            f"replacement={records[1]['execution_id']}"
        )
        _print_state(state)
        return 0
    if args.command == "close-day":
        record, state = service.close_day(
            reason=args.reason,
            note=args.note,
            confirm=callback,
        )
        print(f"Appended day_close {record['execution_id']}")
        _print_state(state)
        return 0
    raise UserInputError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except JournalValidationError as exc:
        print("Journal validation failed:", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 3
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 3
    except (UserInputError, OperationCancelled) as exc:
        message = str(exc) or "operation cancelled"
        print(f"Operation not written: {message}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print(
            "Operation interrupted; durable partial records may exist. Run validate.",
            file=sys.stderr,
        )
        return 6
    except LockUnavailableError as exc:
        print(f"Journal lock error: {exc}", file=sys.stderr)
        return 5
    except OSError as exc:
        print(f"Filesystem error: {exc}. Run validate.", file=sys.stderr)
        return 5
    except BitcoinDcaError as exc:
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 6
