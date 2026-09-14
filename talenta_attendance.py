"""Submit Talenta attendance requests for Monday..today of the current week."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"


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


def load_config(path: Path = ROOT / "config.json") -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def setup_logger() -> logging.Logger:
    """INFO to the console, DEBUG (including tracebacks) to logs/run_*.log."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"run_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    logger = logging.getLogger("talenta")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logfile = logging.FileHandler(log_path, encoding="utf-8")
    logfile.setLevel(logging.DEBUG)
    logfile.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(logfile)
    logger.info("Log file: %s", log_path)
    return logger


@dataclass
class DayResult:
    date: date
    status: str  # SUBMITTED | DRY_RUN | FAILED
    reason: str = ""
    screenshot: Path | None = None


def format_result(result: DayResult) -> str:
    line = f"{result.date.isoformat()}  {result.status:<10}  {result.reason}"
    if result.screenshot is not None:
        line += f"  {result.screenshot}"
    return line.rstrip()


def print_summary(results: list[DayResult], log: logging.Logger) -> None:
    log.info("---- Summary ----")
    for result in results:
        log.info(format_result(result))
