#!/usr/bin/env python3
"""Local manual entrypoint for the Bitcoin Smart DCA engine."""

from __future__ import annotations

import sys
from pathlib import Path


if sys.version_info < (3, 11):
    print(
        "Bitcoin Smart DCA requires Python 3.11 or newer; "
        f"found {sys.version_info.major}.{sys.version_info.minor}.",
        file=sys.stderr,
    )
    raise SystemExit(3)


MODULE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = MODULE_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
