from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


BITCOIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BITCOIN_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.config import load_config
from bitcoin_dca.errors import UserInputError
from bitcoin_dca.providers import (
    CoinbaseAdapter,
    FearGreedAdapter,
    HttpClient,
    HttpResponse,
    MarketDataService,
    ProviderRequestError,
    VolmexAdapter,
)
from bitcoin_dca.recommendation import RecommendationService
from bitcoin_dca.storage import JournalStore
from bitcoin_dca.validation import journal_warnings, validate_journal


UTC = timezone.utc


def response(payload: object, status: int = 200, headers: dict | None = None):
    return HttpResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers or {},
    )


class FixtureTransport:
    def __init__(self, *, missing_reference: bool = False, daily_gap: bool = False):
        self.missing_reference = missing_reference
        self.daily_gap = daily_gap
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: int) -> HttpResponse:
        self.urls.append(url)
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.netloc == "api.exchange.coinbase.com":
            granularity = int(query["granularity"][0])
            start = datetime.fromisoformat(query["start"][0])
            end = datetime.fromisoformat(query["end"][0])
            if granularity == 300:
                timestamp = int(start.timestamp())
                if self.missing_reference and end.date().isoformat() == "2026-08-12":
                    return response([])
                close = "70000" if end.date().isoformat() == "2026-08-12" else "72000"
                return response([[timestamp, "69000", "73000", "71000", close, "10"]])
            rows = []
            cursor = start
            index = 0
            while cursor < end:
                close = 90000 + index * 10
                rows.append(
                    [
                        int(cursor.timestamp()),
                        str(close - 1000),
                        str(close + 1000),
                        str(close - 500),
                        str(close),
                        "100",
                    ]
                )
                cursor += timedelta(days=1)
                index += 1
            if self.daily_gap:
                rows.pop(20)
            return response(list(reversed(rows)))
        if parsed.netloc == "api.alternative.me":
            cutoff = datetime(2026, 8, 12, 13, 0, tzinfo=UTC)
            return response(
                {
                    "name": "Fear and Greed Index",
                    "data": [
                        {
                            "value": "20",
                            "timestamp": str(int((cutoff - timedelta(hours=13)).timestamp())),
                        },
                        {
                            "value": "80",
                            "timestamp": str(int((cutoff + timedelta(hours=11)).timestamp())),
                        },
                    ],
                    "metadata": {"error": None},
                }
            )
        if parsed.netloc == "rest-v1.volmex.finance":
            symbol = query["symbol"][0]
            cutoff = datetime.fromtimestamp(int(query["to"][0]), UTC)
            if symbol == "BVIV":
                return response(
                    {
                        "s": "ok",
                        "t": [int((cutoff - timedelta(hours=1)).timestamp())],
                        "c": ["75.5"],
                    }
                )
            return response(
                {
                    "s": "ok",
                    "t": [int((cutoff - timedelta(hours=20)).timestamp())],
                    "c": ["72.0"],
                }
            )
        raise AssertionError(f"unexpected URL: {url}")


class ProviderRecommendationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        source = json.loads(
            (BITCOIN_ROOT / "config" / "config.1.0-draft.2.json").read_text(
                encoding="utf-8"
            )
        )
        source["runtime"]["data_dir"] = str(self.workspace / "data")
        source["runtime"]["reports_dir"] = str(self.workspace / "reports")
        source["runtime"]["templates_dir"] = str(BITCOIN_ROOT / "templates")
        source["runtime"]["http_retry_delays_seconds"] = [0, 0]
        self.config_path = self.workspace / "config.json"
        self.config_path.write_text(json.dumps(source), encoding="utf-8")
        self.config = load_config(self.config_path)
        self.now = datetime.fromisoformat("2026-08-12T21:05:00+08:00")
        self.cutoff = datetime.fromisoformat("2026-08-12T21:00:00+08:00")
        self.transport = FixtureTransport()
        self.client = HttpClient(
            self.config,
            transport=self.transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def market_service(self, transport=None, *, api_key: str = "top-secret-key"):
        client = self.client
        if transport is not None:
            client = HttpClient(
                self.config,
                transport=transport,
                clock=lambda: self.now.astimezone(UTC),
                sleeper=lambda _: None,
            )
        return MarketDataService(self.config, client=client, api_key=api_key)

    def test_coinbase_exact_bucket_unsorted_daily_and_wilder_atr(self) -> None:
        adapter = CoinbaseAdapter(self.config, self.client)
        reference = adapter.reference(self.cutoff)
        daily = adapter.daily(self.cutoff)
        self.assertEqual(reference.quality_status, "valid")
        self.assertEqual(reference.record["bucket_end"], "2026-08-12T13:00:00+00:00")
        self.assertEqual(reference.record["observed_at"], reference.record["bucket_end"])
        self.assertEqual(daily.quality_status, "valid")
        self.assertEqual(daily.record["candle_count"], 91)
        self.assertEqual(len(daily.record["candles"]), 91)
        self.assertIsNotNone(daily.recent_high)
        self.assertGreater(daily.atr, 0)

    def test_coinbase_missing_bucket_and_daily_gap_are_not_filled(self) -> None:
        transport = FixtureTransport(missing_reference=True, daily_gap=True)
        client = HttpClient(
            self.config,
            transport=transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        adapter = CoinbaseAdapter(self.config, client)
        reference = adapter.reference(self.cutoff)
        daily = adapter.daily(self.cutoff)
        self.assertIsNone(reference.value)
        self.assertIn("BTC_REFERENCE_MISSING_BUCKET", reference.error_codes)
        self.assertIsNone(daily.atr)
        self.assertIn("BTC_DAILY_GAP", daily.error_codes)

    def test_coinbase_duplicate_bucket_is_invalid(self) -> None:
        def duplicate_transport(url: str, timeout: int) -> HttpResponse:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            start = datetime.fromisoformat(query["start"][0])
            row = [int(start.timestamp()), "1", "2", "1", "2", "3"]
            return response([row, row])

        client = HttpClient(
            self.config,
            transport=duplicate_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        result = CoinbaseAdapter(self.config, client).reference(self.cutoff)
        self.assertIsNone(result.value)
        self.assertIn("BTC_REFERENCE_INVALID", result.error_codes)

    def test_fear_greed_uses_latest_before_cutoff_and_marks_stale(self) -> None:
        adapter = FearGreedAdapter(self.config, self.client)
        current = adapter.fetch(self.cutoff)
        self.assertEqual(current.value, 20)
        self.assertEqual(current.record["attribution"], "Alternative.me")

        def stale_transport(url: str, timeout: int) -> HttpResponse:
            observed = self.cutoff.astimezone(UTC) - timedelta(hours=40)
            return response(
                {
                    "data": [{"value": "30", "timestamp": str(int(observed.timestamp()))}],
                    "metadata": {"error": None},
                }
            )

        stale_client = HttpClient(
            self.config,
            transport=stale_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        stale = FearGreedAdapter(self.config, stale_client).fetch(self.cutoff)
        self.assertIsNone(stale.value)
        self.assertEqual(stale.quality_status, "stale")

    def test_http_retries_429_but_not_other_4xx(self) -> None:
        attempts = 0
        delays: list[float] = []

        def retry_transport(url: str, timeout: int) -> HttpResponse:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return response({}, status=429, headers={"Retry-After": "0"})
            return response({"ok": True})

        client = HttpClient(
            self.config,
            transport=retry_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=delays.append,
        )
        result = client.get_json(
            provider="fixture",
            endpoint="retry",
            base_url="https://fixture.invalid/data",
            params={},
        )
        self.assertEqual(result.descriptor["attempts"], 2)
        self.assertEqual(delays, [0])

        bad_attempts = 0

        def bad_request(url: str, timeout: int) -> HttpResponse:
            nonlocal bad_attempts
            bad_attempts += 1
            return response({}, status=403)

        bad_client = HttpClient(
            self.config,
            transport=bad_request,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        with self.assertRaises(ProviderRequestError):
            bad_client.get_json(
                provider="fixture",
                endpoint="forbidden",
                base_url="https://fixture.invalid/data",
                params={},
            )
        self.assertEqual(bad_attempts, 1)

        server_attempts = 0

        def server_error(url: str, timeout: int) -> HttpResponse:
            nonlocal server_attempts
            server_attempts += 1
            return response({}, status=500 if server_attempts == 1 else 200)

        server_client = HttpClient(
            self.config,
            transport=server_error,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        server_client.get_json(
            provider="fixture",
            endpoint="server-error",
            base_url="https://fixture.invalid/data",
            params={},
        )
        self.assertEqual(server_attempts, 2)

    def test_timeout_retries_to_configured_attempt_limit(self) -> None:
        attempts = 0

        def timeout_transport(url: str, timeout: int) -> HttpResponse:
            nonlocal attempts
            attempts += 1
            raise TimeoutError("fixture timeout")

        client = HttpClient(
            self.config,
            transport=timeout_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        with self.assertRaises(ProviderRequestError) as caught:
            client.get_json(
                provider="fixture",
                endpoint="timeout",
                base_url="https://fixture.invalid/data",
                params={},
            )
        self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertEqual(attempts, 3)

    def test_volmex_primary_failure_uses_bvivf_and_redacts_key(self) -> None:
        urls: list[str] = []

        def fallback_transport(url: str, timeout: int) -> HttpResponse:
            urls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if query["symbol"][0] == "BVIV":
                return response({}, status=403)
            cutoff = datetime.fromtimestamp(int(query["to"][0]), UTC)
            return response(
                {
                    "s": "ok",
                    "t": [int((cutoff - timedelta(hours=20)).timestamp())],
                    "c": ["71.25"],
                }
            )

        client = HttpClient(
            self.config,
            transport=fallback_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        result = VolmexAdapter(
            self.config, client, "top-secret-key"
        ).fetch(self.cutoff)
        self.assertEqual(result.value, Decimal("71.25"))
        self.assertTrue(result.record["fallback_used"])
        serialized = json.dumps(result.record, sort_keys=True)
        self.assertNotIn("top-secret-key", serialized)
        self.assertNotIn("apikey", serialized)
        self.assertTrue(any("apikey=top-secret-key" in url for url in urls))

    def test_bvivf_daily_bucket_is_available_only_after_new_york_fixing(self) -> None:
        def fixing_transport(url: str, timeout: int) -> HttpResponse:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if query["symbol"][0] == "BVIV":
                return response({}, status=403)
            cutoff = datetime.fromtimestamp(int(query["to"][0]), UTC)
            same_day = datetime.combine(cutoff.date(), datetime.min.time(), UTC)
            previous_day = same_day - timedelta(days=1)
            return response(
                {
                    "s": "ok",
                    "t": [int(same_day.timestamp()), int(previous_day.timestamp())],
                    "c": ["99", "70"],
                }
            )

        client = HttpClient(
            self.config,
            transport=fixing_transport,
            clock=lambda: self.now.astimezone(UTC),
            sleeper=lambda _: None,
        )
        result = VolmexAdapter(self.config, client, None).fetch(self.cutoff)
        self.assertEqual(result.value, Decimal("70"))
        self.assertEqual(result.record["observed_at"], "2026-08-11T20:00:00+00:00")

    def test_volmex_all_missing_returns_neutral_input(self) -> None:
        def missing_transport(url: str, timeout: int) -> HttpResponse:
            return response({"s": "ok", "t": [], "c": []})

        bundle = self.market_service(missing_transport, api_key="").collect(self.cutoff)
        self.assertIsNone(bundle.market_inputs.bviv)
        self.assertIn("BVIV_NEUTRAL_MISSING", bundle.reason_codes)

    def test_recommend_writes_target_snapshot_then_decision_and_redacts_secret(self) -> None:
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(),
        )
        outcome = service.recommend(now=self.now)
        self.assertEqual(outcome.exit_code, 0)
        self.assertTrue(outcome.created_weekly_target)
        self.assertEqual(outcome.decision["revision"], 1)
        self.assertEqual(outcome.decision["snapshot_id"], outcome.snapshot["snapshot_id"])
        self.assertEqual(
            outcome.decision["weekly_target_id"],
            outcome.weekly_target["weekly_target_id"],
        )
        with store.lock(exclusive=False):
            datasets = store.read_all()
            validate_journal(datasets, self.config)
        self.assertEqual(
            {key: len(value) for key, value in datasets.items()},
            {
                "market_snapshots": 1,
                "decisions": 1,
                "executions": 0,
                "weekly_targets": 1,
            },
        )
        all_bytes = b"".join(
            path.read_bytes()
            for path in store.paths.datasets.values()
            if path.exists()
        )
        self.assertNotIn(b"top-secret-key", all_bytes)

    def test_same_day_recommend_appends_snapshot_and_decision_revision(self) -> None:
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(),
        )
        first = service.recommend(now=self.now)
        second = service.recommend(now=self.now)
        self.assertFalse(second.created_weekly_target)
        self.assertEqual(second.decision["decision_id"], first.decision["decision_id"])
        self.assertEqual(second.decision["revision"], 2)
        self.assertEqual(
            second.decision["supersedes_revision_id"], first.decision["revision_id"]
        )
        self.assertNotEqual(second.snapshot["snapshot_id"], first.snapshot["snapshot_id"])
        self.assertEqual(service.store.read_dataset("market_snapshots").__len__(), 2)

    def test_identical_orphan_snapshot_is_reused_after_crash(self) -> None:
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(),
        )
        first = service.recommend(now=self.now)
        orphan = copy.deepcopy(first.snapshot)
        orphan["snapshot_id"] = str(uuid4())
        orphan["operation_id"] = str(uuid4())
        orphan["created_at"] = self.now.isoformat(timespec="seconds")
        datasets = store.read_all()
        prospective = {name: list(records) for name, records in datasets.items()}
        prospective["market_snapshots"].append(orphan)
        validate_journal(prospective, self.config)
        store.append_records("market_snapshots", [orphan])
        self.assertEqual(
            journal_warnings(prospective),
            [f"orphan market snapshot: {orphan['snapshot_id']}"],
        )

        recovered = service.recommend(now=self.now)
        self.assertTrue(recovered.reused_orphan_snapshot)
        self.assertEqual(recovered.snapshot["snapshot_id"], orphan["snapshot_id"])
        self.assertEqual(len(store.read_dataset("market_snapshots")), 2)
        self.assertEqual(recovered.decision["revision"], 2)

    def test_btc_failure_saves_blocked_decision(self) -> None:
        transport = FixtureTransport(missing_reference=True)
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(transport),
        )
        outcome = service.recommend(now=self.now)
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(outcome.decision["decision_status"], "blocked")
        self.assertIsNone(outcome.decision["final_suggested_usd"])
        self.assertEqual(len(store.read_dataset("market_snapshots")), 1)
        self.assertEqual(len(store.read_dataset("decisions")), 1)

    def test_before_cutoff_writes_nothing(self) -> None:
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(),
        )
        with self.assertRaises(UserInputError):
            service.recommend(now=datetime.fromisoformat("2026-08-12T20:59:59+08:00"))
        self.assertFalse(any(path.exists() for path in store.paths.datasets.values()))

    def test_after_original_window_end_is_allowed(self) -> None:
        store = JournalStore(self.config)
        service = RecommendationService(
            self.config,
            store=store,
            market_data=self.market_service(),
        )
        outcome = service.recommend(now=datetime.fromisoformat("2026-08-12T21:10:01+08:00"))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.snapshot["cutoff_at"], "2026-08-12T21:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
