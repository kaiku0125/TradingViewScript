"""Command-line interface for the implemented Gate 4A-1 Journal core."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import DEFAULT_CONFIG_PATH, load_config
from .errors import (
    BitcoinDcaError,
    ConfigError,
    JournalValidationError,
    LockUnavailableError,
    OperationCancelled,
    UserInputError,
)
from .ledger import JournalService, PortfolioState


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dca.py",
        description="Bitcoin Smart DCA local Journal core (Gate 4A-1)",
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
    return parser


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    service = JournalService(config)

    if args.command == "validate":
        counts = service.validate()
        print("Journal valid")
        for dataset, count in sorted(counts.items()):
            print(f"  {dataset}: {count}")
        return 0

    if args.command == "status":
        service.validate()
        _print_state(service.portfolio_state())
        print("  decision_runtime: not implemented (Gate 4A-2/4A-3)")
        return 0

    callback = lambda preview: _confirm(preview, assume_yes=args.yes)
    if args.command == "record-purchase":
        record, state = service.record_purchase(
            usd=args.usd,
            btc=args.btc,
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
    except (UserInputError, OperationCancelled, KeyboardInterrupt) as exc:
        message = str(exc) or "operation cancelled"
        print(f"Operation not written: {message}", file=sys.stderr)
        return 4
    except LockUnavailableError as exc:
        print(f"Journal lock error: {exc}", file=sys.stderr)
        return 5
    except OSError as exc:
        print(f"Filesystem error: {exc}", file=sys.stderr)
        return 5
    except BitcoinDcaError as exc:
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 6

