"""Isolated first-day rehearsal for the local manual MVP."""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .config import RuntimeConfig
from .ledger import JournalService
from .providers import HttpClient, HttpResponse, MarketDataService
from .recommendation import RecommendationService
from .reporting import ReporterService
from .storage import JournalStore


UTC = timezone.utc
FIXED_NOW = datetime.fromisoformat("2026-08-12T21:05:00+08:00")


@dataclass(frozen=True)
class RehearsalOutcome:
    plan_date: str
    decision_status: str
    suggested_usd: str
    purchase_usd: str
    purchase_btc: str
    execution_status: str
    journal_counts: dict[str, int]
    report_watermarks: dict[str, str]
    report_sha256: dict[str, str]
    formal_journal_unchanged: bool

    def as_dict(self) -> dict:
        return {
            "plan_date": self.plan_date,
            "decision_status": self.decision_status,
            "suggested_usd": self.suggested_usd,
            "purchase_usd": self.purchase_usd,
            "purchase_btc": self.purchase_btc,
            "execution_status": self.execution_status,
            "journal_counts": self.journal_counts,
            "report_watermarks": self.report_watermarks,
            "report_sha256": self.report_sha256,
            "formal_journal_unchanged": self.formal_journal_unchanged,
        }


def _response(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={},
    )


class _FixtureTransport:
    """Deterministic in-process provider fixture; it performs no network I/O."""

    def __call__(self, url: str, timeout: int) -> HttpResponse:
        del timeout
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.netloc == "api.exchange.coinbase.com":
            granularity = int(query["granularity"][0])
            start = datetime.fromisoformat(query["start"][0])
            end = datetime.fromisoformat(query["end"][0])
            if granularity == 300:
                close = "70000" if end.date() == FIXED_NOW.astimezone(UTC).date() else "72000"
                return _response(
                    [[int(start.timestamp()), "69000", "73000", "71000", close, "10"]]
                )
            rows = []
            cursor = start
            index = 0
            while cursor < end:
                close = Decimal("90000") + Decimal(index * 10)
                rows.append(
                    [
                        int(cursor.timestamp()),
                        str(close - Decimal("1000")),
                        str(close + Decimal("1000")),
                        str(close - Decimal("500")),
                        str(close),
                        "100",
                    ]
                )
                cursor += timedelta(days=1)
                index += 1
            return _response(list(reversed(rows)))
        if parsed.netloc == "api.alternative.me":
            cutoff = FIXED_NOW.astimezone(UTC).replace(minute=0)
            return _response(
                {
                    "name": "Fear and Greed Index",
                    "data": [
                        {
                            "value": "20",
                            "timestamp": str(
                                int((cutoff - timedelta(hours=13)).timestamp())
                            ),
                        }
                    ],
                    "metadata": {"error": None},
                }
            )
        if parsed.netloc == "rest-v1.volmex.finance":
            cutoff = datetime.fromtimestamp(int(query["to"][0]), UTC)
            return _response(
                {
                    "s": "ok",
                    "t": [int((cutoff - timedelta(hours=1)).timestamp())],
                    "c": ["75.5"],
                }
            )
        raise AssertionError(f"unexpected rehearsal URL: {url}")


def _dataset_hashes(store: JournalStore) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name, path in store.paths.datasets.items():
        result[name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
    return result


def run_first_day_rehearsal(config: RuntimeConfig) -> RehearsalOutcome:
    """Exercise day one in a temporary store and prove the formal store is untouched."""

    formal_store = JournalStore(config)
    formal_before = _dataset_hashes(formal_store)
    with tempfile.TemporaryDirectory(prefix="bitcoin-dca-rehearsal-") as folder:
        root = Path(folder)
        rehearsal_config = replace(
            config,
            data_dir=root / "data",
            reports_dir=root / "reports",
        )
        client = HttpClient(
            rehearsal_config,
            transport=_FixtureTransport(),
            clock=lambda: FIXED_NOW.astimezone(UTC),
            sleeper=lambda _: None,
        )
        market = MarketDataService(rehearsal_config, client=client, api_key=None)
        recommendation = RecommendationService(
            rehearsal_config,
            market_data=market,
            environ={},
        ).recommend(now=FIXED_NOW)
        suggested = recommendation.decision["final_suggested_usd"]
        if suggested is None:
            raise RuntimeError("first-day rehearsal produced a blocked recommendation")

        purchase_btc = format(
            (Decimal(suggested) / Decimal("70000")).quantize(Decimal("0.00000001")),
            "f",
        )
        journal = JournalService(rehearsal_config)
        journal.record_purchase(
            usd=suggested,
            btc=purchase_btc,
            note="Gate 4A-4 isolated first-day rehearsal",
            confirm=lambda _: True,
            now=FIXED_NOW + timedelta(minutes=1),
        )
        journal.close_day(
            reason="completed_for_day",
            note="Gate 4A-4 isolated first-day rehearsal",
            confirm=lambda _: True,
            now=FIXED_NOW + timedelta(minutes=2),
        )
        state = journal.portfolio_state(now=FIXED_NOW + timedelta(minutes=2))
        counts = journal.validate()

        reporter = ReporterService(rehearsal_config)
        reports = {
            kind: reporter.generate(kind, reference_date=FIXED_NOW.date())
            for kind in ("daily", "weekly", "monthly")
        }
        for result in reports.values():
            if "{{" in result.content or result.output_path is None:
                raise RuntimeError("rehearsal report is incomplete")
        daily = reports["daily"].content
        execution_status = "executed" if "| 執行狀態 | `executed` |" in daily else "unknown"
        outcome = RehearsalOutcome(
            plan_date=FIXED_NOW.date().isoformat(),
            decision_status=recommendation.decision["decision_status"],
            suggested_usd=suggested,
            purchase_usd=format(state.actual_invested_today_usd, ".2f"),
            purchase_btc=purchase_btc,
            execution_status=execution_status,
            journal_counts=counts,
            report_watermarks={key: value.watermark for key, value in reports.items()},
            report_sha256={
                key: hashlib.sha256(value.content.encode("utf-8")).hexdigest()
                for key, value in reports.items()
            },
            formal_journal_unchanged=False,
        )

    formal_after = _dataset_hashes(formal_store)
    unchanged = formal_before == formal_after
    if not unchanged:
        raise RuntimeError("formal Journal changed during isolated rehearsal")
    return replace(outcome, formal_journal_unchanged=True)
