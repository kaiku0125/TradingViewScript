import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import refresh_trade_rows
from trade_history.update_trade_history import validate_snapshot_payload


VALID_SNAPSHOT = {
    "fetched_at": "2026-07-02T10:00:00+08:00",
    "tabs": {
        "BTC": [["Date", "Qty"], ["2026/07/01", "1"]],
        "ETH": [["Date", "Qty"]],
    },
}


class SnapshotValidationTest(unittest.TestCase):
    def test_refresh_validator_accepts_valid_snapshot_without_spreadsheet_url(self) -> None:
        refresh_trade_rows.validate_payload(VALID_SNAPSHOT)

    def test_refresh_validator_accepts_string_spreadsheet_url(self) -> None:
        payload = dict(VALID_SNAPSHOT, spreadsheet_url="https://docs.google.com/spreadsheets/d/demo")
        refresh_trade_rows.validate_payload(payload)

    def test_refresh_validator_rejects_missing_fetched_at(self) -> None:
        payload = dict(VALID_SNAPSHOT)
        payload.pop("fetched_at")
        with self.assertRaisesRegex(ValueError, "missing fetched_at"):
            refresh_trade_rows.validate_payload(payload)

    def test_refresh_validator_rejects_tabs_that_are_not_a_dict(self) -> None:
        payload = dict(VALID_SNAPSHOT, tabs=[])
        with self.assertRaisesRegex(ValueError, "tabs must be a non-empty object"):
            refresh_trade_rows.validate_payload(payload)

    def test_refresh_validator_rejects_empty_tabs(self) -> None:
        payload = dict(VALID_SNAPSHOT, tabs={})
        with self.assertRaisesRegex(ValueError, "tabs must be a non-empty object"):
            refresh_trade_rows.validate_payload(payload)

    def test_refresh_validator_rejects_tab_rows_that_are_not_lists(self) -> None:
        payload = dict(VALID_SNAPSHOT, tabs={"BTC": "bad"})
        with self.assertRaisesRegex(ValueError, "tab 'BTC' must contain a list of rows"):
            refresh_trade_rows.validate_payload(payload)

    def test_refresh_validator_rejects_non_list_row(self) -> None:
        payload = dict(VALID_SNAPSHOT, tabs={"ETH": [["Date"], "bad-row"]})
        with self.assertRaisesRegex(ValueError, "tab 'ETH' row 2 must be a list"):
            refresh_trade_rows.validate_payload(payload)

    def test_update_trade_history_validator_accepts_missing_spreadsheet_url(self) -> None:
        validate_snapshot_payload(VALID_SNAPSHOT)

    def test_update_trade_history_validator_rejects_missing_fetched_at(self) -> None:
        payload = dict(VALID_SNAPSHOT)
        payload.pop("fetched_at")
        with self.assertRaisesRegex(ValueError, "Invalid trade snapshot: missing fetched_at"):
            validate_snapshot_payload(payload)

    def test_update_trade_history_cli_stops_before_converter_for_invalid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = Path(tmp_dir) / "trade_rows.json"
            snapshot_path.write_text(json.dumps({"tabs": {"BTC": []}}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "trade_history/update_trade_history.py",
                    "--input",
                    str(snapshot_path),
                ],
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid trade snapshot: missing fetched_at", result.stderr)


if __name__ == "__main__":
    unittest.main()
