"""Submit Talenta attendance requests for Monday..today of the current week."""

from __future__ import annotations

import argparse
from datetime import date, timedelta


def target_dates(today: date) -> list[date]:
    """Monday of `today`'s week through `today`, capped at Friday."""
    monday = today - timedelta(days=today.weekday())
    last = today if today.weekday() <= 4 else monday + timedelta(days=4)
    return [monday + timedelta(days=i) for i in range((last - monday).days + 1)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit Talenta attendance requests for the current week."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fill the form for each date but never click Submit",
    )
    parser.add_argument(
        "--only",
        action="append",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="submit only this date (repeatable); replaces the current-week rule",
    )
    return parser.parse_args(argv)
