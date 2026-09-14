"""Submit Talenta attendance requests for Monday..today of the current week."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect, sync_playwright

import talenta_selectors as sel

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
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
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


class LoginTimeout(Exception):
    """The user did not reach the dashboard in time. Aborts the whole run."""


class DayFailure(Exception):
    """One date could not be submitted. The run continues with the next date."""


def wait_for_login(page: Page, config: dict, log: logging.Logger) -> None:
    minutes = config["login_timeout_minutes"]
    dashboard = config["dashboard_url"]
    log.info("Please log in in the browser window (waiting up to %s minutes)...", minutes)
    try:
        page.wait_for_url(lambda url: url.startswith(dashboard), timeout=minutes * 60_000)
    except PlaywrightTimeout as exc:
        raise LoginTimeout(f"Login not completed within {minutes} minutes") from exc
    log.info("Logged in.")


def goto_attendance(page: Page, config: dict, log: logging.Logger) -> None:
    page.goto(config["attendance_url"])
    if sel.LOGIN_HOST in page.url:
        log.warning("Session expired - please log in again.")
        wait_for_login(page, config, log)
        page.goto(config["attendance_url"])
    page.wait_for_selector(sel.REQUEST_BUTTON, state="visible")


def open_request_modal(page: Page) -> None:
    page.click(sel.REQUEST_BUTTON)
    page.wait_for_selector(sel.MODAL, state="visible")
    page.click(sel.ATTENDANCE_RADIO_LABEL)
    if not page.locator(sel.ATTENDANCE_RADIO).is_checked():
        raise DayFailure("Could not select the 'Attendance' request type")


SET_DATE_JS = """([selector, year, month, day]) => {
    $(selector).pickadate('picker').set('select', new Date(year, month - 1, day));
}"""


def set_effective_date(page: Page, day: date, timeout_ms: int) -> None:
    """Select the date via pickadate's API.

    This fills the visible field and the hidden *_submit field and fires the
    page's change handler, which POSTs get-current-shift and then fills the
    Shift and Check In/Out date dropdowns itself.
    """
    with page.expect_response(lambda r: sel.SHIFT_LOOKUP_PATH in r.url, timeout=timeout_ms):
        page.evaluate(SET_DATE_JS, [sel.EFFECTIVE_DATE, day.year, day.month, day.day])


def _expect_value(page: Page, selector: str, expected: str, what: str, timeout_ms: int) -> None:
    try:
        expect(page.locator(selector)).to_have_value(expected, timeout=timeout_ms)
    except AssertionError as exc:
        actual = page.locator(selector).input_value()
        raise DayFailure(f"{what} is '{actual}', expected '{expected}'") from exc


def verify_prefilled(page: Page, day: date, timeout_ms: int) -> None:
    iso = day.isoformat()
    _expect_value(page, sel.EFFECTIVE_DATE_HIDDEN, iso, "Effective date", timeout_ms)
    try:
        expect(page.locator(sel.SHIFT_SELECT)).not_to_have_value("", timeout=timeout_ms)
    except AssertionError as exc:
        raise DayFailure("Shift dropdown stayed empty - probably a day off or no schedule") from exc
    _expect_value(page, sel.CHECKIN_DATE_SELECT, iso, "Check In date", timeout_ms)
    _expect_value(page, sel.CHECKOUT_DATE_SELECT, iso, "Check Out date", timeout_ms)
    for selector, what in ((sel.CHECKIN_BOX, "Check In"), (sel.CHECKOUT_BOX, "Check Out")):
        if not page.locator(selector).is_checked():
            raise DayFailure(f"{what} box is not ticked")


def fill_times_and_notes(page: Page, config: dict) -> None:
    for selector, value, what in (
        (sel.CHECKIN_TIME, config["check_in"], "Check In time"),
        (sel.CHECKOUT_TIME, config["check_out"], "Check Out time"),
    ):
        page.fill(selector, value)
        actual = page.input_value(selector)
        if actual != value:
            raise DayFailure(f"{what} shows '{actual}' after typing '{value}'")
    page.fill(sel.NOTES, config["notes"])


def click_submit(page: Page, timeout_ms: int) -> dict:
    """Click Submit and return Talenta's JSON reply ({"result": "OK", "errorMsg": ...})."""
    try:
        with page.expect_response(lambda r: sel.SAVE_REQUEST_PATH in r.url, timeout=timeout_ms) as info:
            page.click(sel.SUBMIT_BUTTON)
    except PlaywrightTimeout as exc:
        toast = page.locator(sel.TOAST).first
        message = toast.inner_text().strip() if toast.count() else "no reply from Talenta"
        raise DayFailure(f"Submit did not go through: {message}") from exc
    return info.value.json()


def wait_for_reload(page: Page, timeout_ms: int) -> None:
    """On success Talenta calls location.reload(); wait until the fresh page is up."""
    page.wait_for_selector(sel.MODAL, state="hidden", timeout=timeout_ms)
    page.wait_for_load_state("load")
