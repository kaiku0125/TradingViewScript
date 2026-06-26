#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from holdings import update_holdings_pine as holdings_sync


DEFAULT_OUTPUT = Path("generated/trade_rows.json")
DEFAULT_MODE = "trade_history"


def fetch_trade_rows(base_url: str, token: str, mode: str) -> dict:
    query = urlencode({"token": token, "mode": mode})
    url = f"{base_url}?{query}"

    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def validate_payload(payload: dict) -> None:
    if payload.get("error"):
        raise ValueError(f"Web app error: {payload['error']}")
    if "fetched_at" not in payload:
        raise ValueError("Payload is missing fetched_at")
    if "tabs" not in payload or not isinstance(payload["tabs"], dict):
        raise ValueError("Payload is missing tabs object")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch live trade row snapshot from Apps Script.")
    parser.add_argument("--url", default=os.environ.get("TRADE_HISTORY_WEB_APP_URL", holdings_sync.DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("TRADE_HISTORY_WEB_APP_TOKEN") or os.environ.get("HOLDINGS_WEB_APP_TOKEN"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", default=DEFAULT_MODE)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Missing token. Pass --token or set TRADE_HISTORY_WEB_APP_TOKEN / HOLDINGS_WEB_APP_TOKEN.")

    payload = fetch_trade_rows(args.url, args.token, args.mode)
    validate_payload(payload)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Trade rows fetched successfully")
    print(f"fetched_at: {payload['fetched_at']}")
    print(f"tabs: {', '.join(payload['tabs'].keys())}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
