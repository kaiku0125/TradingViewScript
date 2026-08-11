"""Read-only market provider adapters for the local manual MVP."""

from __future__ import annotations

import hashlib
import json
import socket
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from email.message import Message
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from .config import RuntimeConfig
from .indicators import MarketInputs


UTC = timezone.utc


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True)
class HttpJsonResult:
    payload: object
    fetched_at: datetime
    descriptor: dict


class ProviderRequestError(Exception):
    def __init__(self, code: str, descriptor: dict):
        self.code = code
        self.descriptor = descriptor
        super().__init__(code)


Transport = Callable[[str, int], HttpResponse]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def _default_transport(url: str, timeout: int) -> HttpResponse:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "bitcoin-dca/0.3"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        headers: Message = exc.headers
        return HttpResponse(
            status=exc.code,
            body=exc.read(),
            headers=dict(headers.items()) if headers is not None else {},
        )


class HttpClient:
    """Small retrying JSON client whose descriptors never contain secrets."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        transport: Transport | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ):
        self.config = config
        self.transport = transport or _default_transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper or time_module.sleep

    def get_json(
        self,
        *,
        provider: str,
        endpoint: str,
        base_url: str,
        params: Mapping[str, object],
        secret_keys: frozenset[str] = frozenset(),
    ) -> HttpJsonResult:
        public_params = {
            key: str(value) for key, value in params.items() if key not in secret_keys
        }
        query = urllib.parse.urlencode(
            [(key, str(value)) for key, value in params.items()]
        )
        url = f"{base_url}?{query}" if query else base_url
        descriptor = {
            "provider": provider,
            "endpoint": endpoint,
            "query": public_params,
            "http_status": None,
            "response_sha256": None,
            "attempts": 0,
        }
        last_code = "HTTP_FAILED"
        for attempt in range(1, self.config.http_max_attempts + 1):
            descriptor["attempts"] = attempt
            response = None
            try:
                response = self.transport(url, self.config.http_timeout_seconds)
                descriptor["http_status"] = response.status
                descriptor["response_sha256"] = hashlib.sha256(
                    response.body
                ).hexdigest()
                retryable = response.status == 429 or response.status >= 500
                if 200 <= response.status < 300:
                    try:
                        payload = json.loads(
                            response.body.decode("utf-8"),
                            parse_float=Decimal,
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise ProviderRequestError("INVALID_JSON", dict(descriptor))
                    return HttpJsonResult(
                        payload=payload,
                        fetched_at=self.clock().astimezone(UTC),
                        descriptor=dict(descriptor),
                    )
                last_code = f"HTTP_{response.status}"
                if not retryable:
                    raise ProviderRequestError(last_code, dict(descriptor))
            except ProviderRequestError:
                raise
            except (TimeoutError, socket.timeout):
                last_code = "TIMEOUT"
            except (urllib.error.URLError, ConnectionError, OSError):
                last_code = "CONNECTION_ERROR"

            if attempt >= self.config.http_max_attempts:
                break
            delay = self.config.http_retry_delays_seconds[attempt - 1]
            if response is not None and response.status == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        delay = min(30, max(0, int(retry_after)))
                    except ValueError:
                        pass
            self.sleeper(delay)
        raise ProviderRequestError(last_code, dict(descriptor))


@dataclass(frozen=True)
class NormalizedValue:
    value: Decimal | None
    record: dict
    quality_status: str
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class CoinbaseDailyResult:
    recent_high: Decimal | None
    atr: Decimal | None
    record: dict
    quality_status: str
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class MarketDataBundle:
    market_inputs: MarketInputs
    btc_reference: dict
    btc_previous_reference: dict
    btc_daily_candles: dict
    fear_greed: dict
    bviv: dict
    quality_status: str
    reason_codes: tuple[str, ...]


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise InvalidOperation
    parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _missing_point(
    *,
    source: str,
    symbol: str,
    interval: str,
    cutoff: datetime,
    stale_after: str,
    status: str,
    fallback_used: bool,
    descriptor: dict,
) -> dict:
    return {
        "source": source,
        "symbol": symbol,
        "value": None,
        "interval": interval,
        "observed_at": None,
        "available_at": None,
        "fetched_at": None,
        "timezone": "UTC",
        "cutoff_at": _iso(cutoff),
        "stale_after": stale_after,
        "quality_status": status,
        "fallback_used": fallback_used,
        "request_descriptor": descriptor,
    }


class CoinbaseAdapter:
    BASE_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"

    def __init__(self, config: RuntimeConfig, client: HttpClient):
        self.config = config
        self.client = client

    def _request(self, *, start: datetime, end: datetime, granularity: int):
        return self.client.get_json(
            provider="coinbase_exchange",
            endpoint="product_candles",
            base_url=self.BASE_URL,
            params={
                "start": start.astimezone(UTC).isoformat(timespec="seconds"),
                "end": end.astimezone(UTC).isoformat(timespec="seconds"),
                "granularity": granularity,
            },
        )

    @staticmethod
    def _rows(payload: object) -> dict[int, list]:
        if not isinstance(payload, list):
            raise ValueError("candles payload must be a list")
        rows: dict[int, list] = {}
        for row in payload:
            if not isinstance(row, list) or len(row) != 6:
                raise ValueError("candle row must contain six values")
            timestamp = row[0]
            if isinstance(timestamp, bool) or not isinstance(timestamp, int):
                raise ValueError("candle timestamp must be an integer")
            if timestamp in rows:
                raise ValueError("duplicate candle bucket")
            rows[timestamp] = row
        return rows

    def reference(self, cutoff: datetime, *, previous: bool = False) -> NormalizedValue:
        target_end = cutoff.astimezone(UTC) - (timedelta(days=1) if previous else timedelta())
        target_start = target_end - timedelta(minutes=5)
        stale_after = (
            "EXACT_HISTORICAL_BUCKET"
            if previous
            else f"PT{self.config.btc_reference_max_age_minutes}M"
        )
        descriptor: dict = {"provider": "coinbase_exchange", "endpoint": "product_candles"}
        try:
            response = self._request(
                start=target_start,
                end=target_end,
                granularity=300,
            )
            descriptor = response.descriptor
            rows = self._rows(response.payload)
            row = rows.get(int(target_start.timestamp()))
            if row is None:
                raise LookupError("exact reference bucket missing")
            close = _decimal(row[4])
            if close <= 0:
                raise ValueError("reference close must be positive")
            status = "valid"
            if not previous and response.fetched_at - target_end > timedelta(
                minutes=self.config.btc_reference_max_age_minutes
            ):
                status = "stale"
            record = {
                "source": "coinbase_exchange",
                "symbol": "BTC-USD",
                "value": format(close, "f"),
                "interval": "5m",
                "provider_timestamp": row[0],
                "bucket_start": _iso(target_start),
                "bucket_end": _iso(target_end),
                "observed_at": _iso(target_end),
                "available_at": _iso(target_end),
                "fetched_at": _iso(response.fetched_at),
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "stale_after": stale_after,
                "quality_status": status,
                "fallback_used": False,
                "request_descriptor": descriptor,
            }
            errors = () if status == "valid" else ("BTC_REFERENCE_STALE",)
            return NormalizedValue(
                close if status == "valid" else None, record, status, errors
            )
        except ProviderRequestError as exc:
            descriptor = exc.descriptor
            code = f"BTC_REFERENCE_{exc.code}"
        except LookupError:
            code = "BTC_REFERENCE_MISSING_BUCKET"
        except (ValueError, InvalidOperation):
            code = "BTC_REFERENCE_INVALID"
        record = _missing_point(
            source="coinbase_exchange",
            symbol="BTC-USD",
            interval="5m",
            cutoff=cutoff,
            stale_after=stale_after,
            status="missing" if "MISSING" in code else "invalid",
            fallback_used=False,
            descriptor=descriptor,
        )
        return NormalizedValue(None, record, record["quality_status"], (code,))

    def daily(self, cutoff: datetime) -> CoinbaseDailyResult:
        cutoff_utc = cutoff.astimezone(UTC)
        current_midnight = datetime.combine(cutoff_utc.date(), datetime.min.time(), UTC)
        last_start = current_midnight - timedelta(days=1)
        first_start = last_start - timedelta(days=self.config.location_lookback_days)
        request_end = last_start + timedelta(days=1)
        descriptor: dict = {"provider": "coinbase_exchange", "endpoint": "product_candles"}
        try:
            response = self._request(
                start=first_start,
                end=request_end,
                granularity=86400,
            )
            descriptor = response.descriptor
            rows = self._rows(response.payload)
            expected = [
                int((first_start + timedelta(days=index)).timestamp())
                for index in range(self.config.location_lookback_days + 1)
            ]
            if any(timestamp not in rows for timestamp in expected):
                raise LookupError("daily candle gap")
            normalized: list[dict] = []
            numeric: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
            for timestamp in expected:
                row = rows[timestamp]
                low, high, opened, close = (
                    _decimal(row[1]),
                    _decimal(row[2]),
                    _decimal(row[3]),
                    _decimal(row[4]),
                )
                if min(low, high, opened, close) <= 0 or low > high:
                    raise ValueError("invalid daily OHLC")
                start = datetime.fromtimestamp(timestamp, UTC)
                end = start + timedelta(days=1)
                if end > cutoff_utc:
                    raise ValueError("incomplete daily candle")
                numeric.append((low, high, opened, close))
                normalized.append(
                    {
                        "provider_timestamp": timestamp,
                        "bucket_start": _iso(start),
                        "bucket_end": _iso(end),
                        "low": format(low, "f"),
                        "high": format(high, "f"),
                        "open": format(opened, "f"),
                        "close": format(close, "f"),
                    }
                )
            lookback = numeric[-self.config.location_lookback_days :]
            recent_high = max(row[1] for row in lookback)
            true_ranges: list[Decimal] = []
            for index in range(1, len(numeric)):
                low, high, _, _ = numeric[index]
                previous_close = numeric[index - 1][3]
                true_ranges.append(
                    max(
                        high - low,
                        abs(high - previous_close),
                        abs(low - previous_close),
                    )
                )
            period = self.config.atr_period
            if len(true_ranges) < period:
                raise ValueError("insufficient ATR inputs")
            with localcontext() as context:
                context.prec = 28
                atr = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
                for value in true_ranges[period:]:
                    atr = (atr * Decimal(period - 1) + value) / Decimal(period)
            encoded = json.dumps(
                normalized, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            record = {
                "source": "coinbase_exchange",
                "symbol": "BTC-USD",
                "interval": "1d",
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "fetched_at": _iso(response.fetched_at),
                "quality_status": "valid",
                "fallback_used": False,
                "candle_count": len(normalized),
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "recent_high": format(recent_high, "f"),
                "atr": format(atr, "f"),
                "candles": normalized,
                "request_descriptor": descriptor,
            }
            return CoinbaseDailyResult(recent_high, atr, record, "valid", ())
        except ProviderRequestError as exc:
            descriptor = exc.descriptor
            code = f"BTC_DAILY_{exc.code}"
        except LookupError:
            code = "BTC_DAILY_GAP"
        except (ValueError, InvalidOperation):
            code = "BTC_DAILY_INVALID"
        return CoinbaseDailyResult(
            None,
            None,
            {
                "source": "coinbase_exchange",
                "symbol": "BTC-USD",
                "interval": "1d",
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "quality_status": "missing" if "GAP" in code else "invalid",
                "fallback_used": False,
                "candles": [],
                "request_descriptor": descriptor,
            },
            "missing" if "GAP" in code else "invalid",
            (code,),
        )


class FearGreedAdapter:
    BASE_URL = "https://api.alternative.me/fng/"

    def __init__(self, config: RuntimeConfig, client: HttpClient):
        self.config = config
        self.client = client

    def fetch(self, cutoff: datetime) -> NormalizedValue:
        stale_after = f"PT{self.config.fear_greed_max_age_hours}H"
        descriptor: dict = {"provider": "alternative_me", "endpoint": "fear_greed"}
        try:
            response = self.client.get_json(
                provider="alternative_me",
                endpoint="fear_greed",
                base_url=self.BASE_URL,
                params={"limit": 2, "format": "json"},
            )
            descriptor = response.descriptor
            payload = response.payload
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("invalid fear and greed payload")
            metadata = payload.get("metadata")
            if isinstance(metadata, dict) and metadata.get("error") not in (None, ""):
                raise ValueError("provider metadata error")
            candidates: list[tuple[datetime, Decimal]] = []
            for item in payload["data"]:
                if not isinstance(item, dict):
                    continue
                timestamp = int(item["timestamp"])
                observed = datetime.fromtimestamp(timestamp, UTC)
                value = _decimal(item["value"])
                if value == value.to_integral_value() and 0 <= value <= 100 and observed <= cutoff.astimezone(UTC):
                    candidates.append((observed, value))
            if not candidates:
                raise LookupError("no value before cutoff")
            observed, value = max(candidates, key=lambda item: item[0])
            status = "valid"
            if cutoff.astimezone(UTC) - observed > timedelta(
                hours=self.config.fear_greed_max_age_hours
            ):
                status = "stale"
            record = {
                "source": "alternative_me",
                "symbol": "CRYPTO_FEAR_GREED",
                "value": format(value, "f"),
                "interval": "1d",
                "observed_at": _iso(observed),
                "available_at": _iso(response.fetched_at),
                "fetched_at": _iso(response.fetched_at),
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "stale_after": stale_after,
                "quality_status": status,
                "fallback_used": False,
                "request_descriptor": descriptor,
                "attribution": "Alternative.me",
            }
            errors = () if status == "valid" else ("FEAR_GREED_STALE",)
            return NormalizedValue(value if status == "valid" else None, record, status, errors)
        except ProviderRequestError as exc:
            descriptor = exc.descriptor
            code = f"FEAR_GREED_{exc.code}"
        except LookupError:
            code = "FEAR_GREED_MISSING"
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
            code = "FEAR_GREED_INVALID"
        record = _missing_point(
            source="alternative_me",
            symbol="CRYPTO_FEAR_GREED",
            interval="1d",
            cutoff=cutoff,
            stale_after=stale_after,
            status="missing" if "MISSING" in code else "invalid",
            fallback_used=False,
            descriptor=descriptor,
        )
        record["attribution"] = "Alternative.me"
        return NormalizedValue(None, record, record["quality_status"], (code,))


class VolmexAdapter:
    BASE_URL = "https://rest-v1.volmex.finance/v2/history"

    def __init__(self, config: RuntimeConfig, client: HttpClient, api_key: str | None):
        self.config = config
        self.client = client
        self.api_key = api_key or None

    def _history(
        self, *, symbol: str, resolution: str, start: datetime, end: datetime
    ) -> HttpJsonResult:
        params: dict[str, object] = {
            "symbol": symbol,
            "resolution": resolution,
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
        }
        secret_keys = frozenset()
        if self.api_key:
            params["apikey"] = self.api_key
            secret_keys = frozenset({"apikey"})
        return self.client.get_json(
            provider="volmex",
            endpoint="history",
            base_url=self.BASE_URL,
            params=params,
            secret_keys=secret_keys,
        )

    @staticmethod
    def _history_points(payload: object) -> list[tuple[datetime, Decimal]]:
        if not isinstance(payload, dict) or payload.get("s") != "ok":
            raise ValueError("Volmex history status is not ok")
        timestamps = payload.get("t")
        closes = payload.get("c")
        if not isinstance(timestamps, list) or not isinstance(closes, list):
            raise ValueError("Volmex t/c arrays are missing")
        if len(timestamps) != len(closes):
            raise ValueError("Volmex t/c arrays differ in length")
        points: dict[int, Decimal] = {}
        for raw_timestamp, raw_close in zip(timestamps, closes):
            if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, int):
                raise ValueError("Volmex timestamp must be an integer")
            if raw_timestamp in points:
                raise ValueError("duplicate Volmex bucket")
            close = _decimal(raw_close)
            if close <= 0:
                raise ValueError("Volmex close must be positive")
            points[raw_timestamp] = close
        return [
            (datetime.fromtimestamp(timestamp, UTC), value)
            for timestamp, value in sorted(points.items())
        ]

    @staticmethod
    def _fixing_observed_at(provider_timestamp: datetime) -> datetime:
        """Normalize daily UDF bucket dates to the 16:00 New York fixing time."""
        if provider_timestamp.time() != datetime.min.time():
            return provider_timestamp
        new_york = ZoneInfo("America/New_York")
        fixing_local = datetime.combine(
            provider_timestamp.date(),
            datetime.min.time().replace(hour=16),
            tzinfo=new_york,
        )
        return fixing_local.astimezone(UTC)

    def _primary(self, cutoff: datetime) -> NormalizedValue:
        descriptor: dict = {"provider": "volmex", "endpoint": "history"}
        try:
            response = self._history(
                symbol="BVIV",
                resolution="60",
                start=cutoff.astimezone(UTC) - timedelta(hours=8),
                end=cutoff.astimezone(UTC),
            )
            descriptor = response.descriptor
            candidates = [
                (start, value)
                for start, value in self._history_points(response.payload)
                if start + timedelta(hours=1) <= cutoff.astimezone(UTC)
            ]
            if not candidates:
                raise LookupError("no completed primary bucket")
            start, value = max(candidates, key=lambda item: item[0])
            observed = start + timedelta(hours=1)
            if cutoff.astimezone(UTC) - observed > timedelta(
                hours=self.config.bviv_primary_max_age_hours
            ):
                raise TimeoutError("stale primary")
            record = {
                "source": "volmex",
                "symbol": "BVIV",
                "value": format(value, "f"),
                "interval": "60m",
                "provider_timestamp": int(start.timestamp()),
                "bucket_start": _iso(start),
                "bucket_end": _iso(observed),
                "observed_at": _iso(observed),
                "available_at": _iso(observed),
                "fetched_at": _iso(response.fetched_at),
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "stale_after": f"PT{self.config.bviv_primary_max_age_hours}H",
                "quality_status": "valid",
                "fallback_used": False,
                "request_descriptor": descriptor,
            }
            return NormalizedValue(value, record, "valid", ())
        except ProviderRequestError as exc:
            descriptor = exc.descriptor
            code = f"BVIV_PRIMARY_{exc.code}"
        except LookupError:
            code = "BVIV_PRIMARY_MISSING"
        except TimeoutError:
            code = "BVIV_PRIMARY_STALE"
        except (ValueError, InvalidOperation, OverflowError):
            code = "BVIV_PRIMARY_INVALID"
        record = _missing_point(
            source="volmex",
            symbol="BVIV",
            interval="60m",
            cutoff=cutoff,
            stale_after=f"PT{self.config.bviv_primary_max_age_hours}H",
            status="stale" if "STALE" in code else "missing" if "MISSING" in code else "invalid",
            fallback_used=False,
            descriptor=descriptor,
        )
        return NormalizedValue(None, record, record["quality_status"], (code,))

    def _fallback(self, cutoff: datetime) -> NormalizedValue:
        descriptor: dict = {"provider": "volmex", "endpoint": "history"}
        try:
            response = self._history(
                symbol="BVIVF",
                resolution="D",
                start=cutoff.astimezone(UTC) - timedelta(days=4),
                end=cutoff.astimezone(UTC),
            )
            descriptor = response.descriptor
            candidates = []
            for provider_timestamp, value in self._history_points(response.payload):
                observed = self._fixing_observed_at(provider_timestamp)
                if observed <= cutoff.astimezone(UTC):
                    candidates.append((provider_timestamp, observed, value))
            if not candidates:
                raise LookupError("no completed fixing")
            provider_timestamp, observed, value = max(
                candidates, key=lambda item: item[1]
            )
            if cutoff.astimezone(UTC) - observed > timedelta(
                hours=self.config.bviv_fallback_max_age_hours
            ):
                raise TimeoutError("stale fixing")
            record = {
                "source": "volmex",
                "symbol": "BVIVF",
                "value": format(value, "f"),
                "interval": "1d",
                "provider_timestamp": int(provider_timestamp.timestamp()),
                "observed_at": _iso(observed),
                "available_at": _iso(observed),
                "fetched_at": _iso(response.fetched_at),
                "timezone": "UTC",
                "cutoff_at": _iso(cutoff),
                "stale_after": f"PT{self.config.bviv_fallback_max_age_hours}H",
                "quality_status": "valid",
                "fallback_used": True,
                "request_descriptor": descriptor,
            }
            return NormalizedValue(value, record, "valid", ())
        except ProviderRequestError as exc:
            descriptor = exc.descriptor
            code = f"BVIV_FALLBACK_{exc.code}"
        except LookupError:
            code = "BVIV_FALLBACK_MISSING"
        except TimeoutError:
            code = "BVIV_FALLBACK_STALE"
        except (ValueError, InvalidOperation, OverflowError):
            code = "BVIV_FALLBACK_INVALID"
        record = _missing_point(
            source="volmex",
            symbol="BVIVF",
            interval="1d",
            cutoff=cutoff,
            stale_after=f"PT{self.config.bviv_fallback_max_age_hours}H",
            status="stale" if "STALE" in code else "missing" if "MISSING" in code else "invalid",
            fallback_used=True,
            descriptor=descriptor,
        )
        return NormalizedValue(None, record, record["quality_status"], (code,))

    def fetch(self, cutoff: datetime) -> NormalizedValue:
        primary = self._primary(cutoff)
        if primary.value is not None:
            return primary
        fallback = self._fallback(cutoff)
        if fallback.value is not None:
            record = dict(fallback.record)
            record["primary_error_codes"] = list(primary.error_codes)
            return NormalizedValue(
                fallback.value,
                record,
                "valid",
                primary.error_codes + ("BVIV_FALLBACK_USED",),
            )
        record = dict(fallback.record)
        record["symbol"] = "BVIV/BVIVF"
        record["fallback_used"] = True
        record["primary_error_codes"] = list(primary.error_codes)
        errors = primary.error_codes + fallback.error_codes + ("BVIV_NEUTRAL_MISSING",)
        return NormalizedValue(None, record, record["quality_status"], errors)


class MarketDataService:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        client: HttpClient | None = None,
        api_key: str | None = None,
    ):
        self.config = config
        self.client = client or HttpClient(config)
        self.coinbase = CoinbaseAdapter(config, self.client)
        self.fear_greed = FearGreedAdapter(config, self.client)
        self.volmex = VolmexAdapter(config, self.client, api_key)

    def collect(self, cutoff: datetime) -> MarketDataBundle:
        reference = self.coinbase.reference(cutoff)
        previous = self.coinbase.reference(cutoff, previous=True)
        daily = self.coinbase.daily(cutoff)
        fear_greed = self.fear_greed.fetch(cutoff)
        bviv = self.volmex.fetch(cutoff)
        btc_valid = (
            reference.value is not None
            and previous.value is not None
            and daily.quality_status == "valid"
        )
        errors = (
            reference.error_codes
            + previous.error_codes
            + daily.error_codes
            + fear_greed.error_codes
            + bviv.error_codes
        )
        if not btc_valid:
            quality = "blocked"
        elif fear_greed.value is None or bviv.value is None or bviv.record.get("fallback_used"):
            quality = "degraded"
        else:
            quality = "valid"
        return MarketDataBundle(
            market_inputs=MarketInputs(
                reference_price=reference.value if btc_valid else None,
                previous_reference_price=previous.value if btc_valid else None,
                recent_high=daily.recent_high if btc_valid else None,
                atr=daily.atr if btc_valid else None,
                fear_greed=fear_greed.value,
                bviv=bviv.value,
                bviv_fallback_used=bool(bviv.record.get("fallback_used")),
            ),
            btc_reference=reference.record,
            btc_previous_reference=previous.record,
            btc_daily_candles=daily.record,
            fear_greed=fear_greed.record,
            bviv=bviv.record,
            quality_status=quality,
            reason_codes=errors,
        )
