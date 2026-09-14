"""Submit Talenta attendance requests for Monday..today of the current week."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

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


REQUIRED_CONFIG_KEYS = (
    "login_url",
    "dashboard_url",
    "attendance_url",
    "check_in",
    "check_out",
    "notes",
    "login_timeout_minutes",
    "action_timeout_seconds",
)


def setup_logger() -> logging.Logger:
    """INFO to the console, DEBUG (including tracebacks) to logs/run_*.log."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"run_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    logger = logging.getLogger("talenta")
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
        handler.close()
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


def first_line(text: str) -> str:
    text = text.strip()
    return text.splitlines()[0] if text else ""


# ---- Browser steps (verified against the live page by the dry run) ----


class LoginTimeout(Exception):
    """The user did not reach the dashboard in time. Aborts the whole run."""


class DayFailure(Exception):
    """One date could not be submitted. The run continues with the next date."""


def wait_for_login(
    page: Page,
    config: dict,
    log: logging.Logger,
    ready: Callable[[str], bool] | None = None,
) -> None:
    """Block until the user has logged in; `ready` decides which URL counts as logged in."""
    minutes = config["login_timeout_minutes"]
    dashboard = config["dashboard_url"]
    if ready is None:
        def ready(url: str) -> bool:
            return url.startswith(dashboard)
    log.info("Please log in in the browser window (waiting up to %s minutes)...", minutes)
    try:
        page.wait_for_url(ready, timeout=minutes * 60_000)
    except PlaywrightTimeout as exc:
        raise LoginTimeout(f"Login not completed within {minutes} minutes") from exc
    log.info("Logged in.")


def goto_attendance(page: Page, config: dict, log: logging.Logger, timeout_ms: int) -> None:
    talenta_host = urlsplit(config["attendance_url"]).netloc
    for attempt in (1, 2):
        page.goto(config["attendance_url"], timeout=timeout_ms, wait_until="domcontentloaded")
        if sel.LOGIN_HOST not in page.url:
            try:
                page.wait_for_selector(sel.REQUEST_BUTTON, state="visible", timeout=timeout_ms)
                return
            except PlaywrightTimeout as exc:
                if sel.LOGIN_HOST not in page.url:
                    raise DayFailure("The attendance page did not load (no Request button)") from exc
        if attempt == 2:
            break
        log.warning("Session expired - please log in again.")
        wait_for_login(page, config, log, ready=lambda url: urlsplit(url).netloc == talenta_host)
    raise DayFailure("Still on the login page after logging in again")


def open_request_modal(page: Page, timeout_ms: int) -> None:
    page.click(sel.REQUEST_BUTTON, timeout=timeout_ms)
    page.wait_for_selector(sel.MODAL, state="visible", timeout=timeout_ms)
    page.click(sel.ATTENDANCE_RADIO_LABEL, timeout=timeout_ms)
    try:
        expect(page.locator(sel.ATTENDANCE_RADIO)).to_be_checked(timeout=timeout_ms)
    except AssertionError as exc:
        raise DayFailure("Could not select the 'Attendance' request type") from exc


SET_DATE_JS = """([selector, year, month, day]) => {
    $(selector).pickadate('picker').set('select', new Date(year, month - 1, day));
}"""


def set_effective_date(page: Page, day: date, timeout_ms: int) -> None:
    """Select the date via pickadate's API.

    This fills the visible field and the hidden *_submit field and fires the
    page's change handler, which POSTs get-current-shift and then fills the
    Shift and Check In/Out date dropdowns itself.
    """
    try:
        with page.expect_response(lambda r: sel.SHIFT_LOOKUP_PATH in r.url, timeout=timeout_ms):
            page.evaluate(SET_DATE_JS, [sel.EFFECTIVE_DATE, day.year, day.month, day.day])
    except PlaywrightTimeout as exc:
        raise DayFailure(f"Talenta did not look up a shift for {day.isoformat()}") from exc


def _expect_value(page: Page, selector: str, expected: str, what: str, timeout_ms: int) -> None:
    try:
        expect(page.locator(selector)).to_have_value(expected, timeout=timeout_ms)
    except AssertionError as exc:
        try:
            actual = page.locator(selector).input_value(timeout=1_000)
        except Exception:
            actual = "(field not found)"
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
        try:
            expect(page.locator(selector)).to_be_checked(timeout=timeout_ms)
        except AssertionError as exc:
            raise DayFailure(f"{what} box is not ticked") from exc


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


CAPTURE_TOAST_JS = """(selector) => {
    window.__talentaToast = null;
    new MutationObserver(() => {
        const toasts = document.querySelectorAll(selector);
        if (toasts.length) window.__talentaToast = toasts[toasts.length - 1].innerText.trim();
    }).observe(document.body, {childList: true, subtree: true});
}"""

MARK_DOCUMENT_JS = "() => { window.__talentaSubmitted = true; }"

UNKNOWN_RESULT = "Submit result unknown - check Talenta's request history before rerunning this date"


def click_submit(page: Page, timeout_ms: int) -> dict:
    """Click Submit and return Talenta's JSON reply ({"result": "OK", "errorMsg": ...}).

    The reply body is captured on its way to the page: Talenta reloads the page
    the instant it gets an OK, which can discard the body before we could read
    it afterwards. The toast observer is armed first because validation toasts
    vanish after ~3 s, and the document marker lets wait_for_reload tell the
    old document from the reloaded one. Once captured["sent"] is set the POST
    has left the browser, so any failure after that must not be reported as
    "not submitted"; a reply that arrives after our wait is still used.
    """
    captured: dict = {}

    def capture(route) -> None:
        captured["sent"] = True
        try:
            response = route.fetch(timeout=timeout_ms * 2)
        except Exception:
            route.abort()
            return
        try:
            captured["status"] = response.status
            captured["body"] = response.text()
        finally:
            route.fulfill(response=response)

    def is_save_request(url: str) -> bool:
        return sel.SAVE_REQUEST_PATH in url

    page.evaluate(CAPTURE_TOAST_JS, sel.TOAST)
    page.evaluate(MARK_DOCUMENT_JS)
    page.route(is_save_request, capture)
    timed_out: PlaywrightTimeout | None = None
    try:
        with page.expect_response(lambda r: is_save_request(r.url), timeout=timeout_ms):
            page.click(sel.SUBMIT_BUTTON, timeout=timeout_ms)
    except PlaywrightTimeout as exc:
        timed_out = exc
    finally:
        # Removing the route while route.fetch() is still pending lets Chromium
        # release the original request as well, i.e. the POST would go out twice.
        # This is the page's only route, so unroute_all is safe.
        try:
            page.unroute_all(behavior="wait")
        except Exception as exc:
            if captured.get("sent"):
                raise DayFailure(f"{UNKNOWN_RESULT} (browser error while waiting for the reply)") from exc
            raise
    if "body" not in captured:
        toast = page.evaluate("() => window.__talentaToast")
        if not captured.get("sent"):
            raise DayFailure(f"Submit did not go through: {toast or 'no message shown'}") from timed_out
        detail = f"the page showed: {toast}" if toast else "no reply within the time limit"
        raise DayFailure(f"{UNKNOWN_RESULT} ({detail})") from timed_out
    try:
        reply = json.loads(captured["body"])
    except json.JSONDecodeError as exc:
        status = captured.get("status", "?")
        raise DayFailure(f"{UNKNOWN_RESULT} (HTTP {status} without a readable result)") from exc
    if not isinstance(reply, dict):
        raise DayFailure(f"{UNKNOWN_RESULT} (unexpected reply {first_line(str(reply))[:100]})")
    return reply


def wait_for_reload(page: Page, timeout_ms: int, log: logging.Logger) -> None:
    """On success Talenta calls location.reload(); wait until the fresh page is up.

    Relies on the marker set by click_submit; without it this returns at once.
    """
    try:
        page.wait_for_function("() => !window.__talentaSubmitted", timeout=timeout_ms)
        page.wait_for_load_state("load", timeout=timeout_ms)
    except Exception:
        log.warning("Talenta accepted the request but the page did not refresh; continuing.")


def record_failure(page: Page, day: date, reason: str, log: logging.Logger) -> DayResult:
    log.error("FAILED %s: %s", day.isoformat(), reason)
    screenshot: Path | None = LOG_DIR / f"fail_{day.isoformat()}.png"
    try:
        page.screenshot(path=str(screenshot), full_page=True, timeout=5_000)
    except Exception:
        screenshot = None
    try:
        page.click(sel.CANCEL_BUTTON, timeout=2_000)
    except Exception:
        pass
    return DayResult(day, "FAILED", reason, screenshot)


def submit_day(page: Page, day: date, config: dict, dry_run: bool, log: logging.Logger) -> DayResult:
    """Submit one date. Never raises except LoginTimeout, which aborts the run."""
    log.info("=== %s ===", day.isoformat())
    timeout_ms = config["action_timeout_seconds"] * 1_000
    try:
        goto_attendance(page, config, log, timeout_ms)
        open_request_modal(page, timeout_ms)
        set_effective_date(page, day, timeout_ms)
        verify_prefilled(page, day, timeout_ms)
        fill_times_and_notes(page, config)
        if dry_run:
            log.info("Form filled; Submit NOT clicked (dry run).")
            return DayResult(day, "DRY_RUN")
        reply = click_submit(page, timeout_ms)
        if reply.get("result") == "OK":
            wait_for_reload(page, timeout_ms, log)
            note = first_line(str(reply.get("errorMsg", "")))
            log.info("Submitted%s", f": {note}" if note else "")
            return DayResult(day, "SUBMITTED")
        rejection = first_line(str(reply.get("errorMsg") or reply))[:200]
        raise DayFailure(f"Talenta rejected the request: {rejection}")
    except LoginTimeout:
        raise
    except DayFailure as exc:
        return record_failure(page, day, str(exc), log)
    except Exception as exc:
        log.debug("Traceback for %s", day.isoformat(), exc_info=True)
        detail = first_line(str(exc))
        reason = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
        return record_failure(page, day, reason, log)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read config.json: {exc}")
        return 1
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing:
        print(f"config.json is missing: {', '.join(missing)}")
        return 1
    for key in ("login_timeout_minutes", "action_timeout_seconds"):
        value = config[key]
        if not isinstance(value, (int, float)) or value <= 0:
            print(f"config.json: {key} must be a positive number, got {value!r}")
            return 1
    log = setup_logger()
    dates = list(dict.fromkeys(args.only)) if args.only else target_dates(date.today())
    log.info("Target dates: %s", ", ".join(d.isoformat() for d in dates))
    if args.dry_run:
        log.info("DRY RUN - Submit will not be clicked.")

    results: list[DayResult] = []
    with sync_playwright() as playwright:
        browser = None
        try:
            browser = playwright.chromium.launch(headless=False)
            page = browser.new_page()
            page.set_default_timeout(config["action_timeout_seconds"] * 1_000)
            page.goto(config["login_url"], wait_until="domcontentloaded")
            wait_for_login(page, config, log)
            for day in dates:
                results.append(submit_day(page, day, config, args.dry_run, log))
                if page.is_closed():
                    log.error("The browser window was closed - stopping.")
                    break
                if results[-1].status == "DRY_RUN" and sys.stdin is not None and sys.stdin.isatty():
                    input("  Inspect the filled form in the browser, then press Enter to continue... ")
        except LoginTimeout as exc:
            if results:
                log.error("%s. Stopping - see the summary for what was already submitted.", exc)
            else:
                log.error("%s. Nothing was submitted.", exc)
            return 1
        except Exception:
            log.exception("Unexpected error - stopping.")
            return 1
        finally:
            if results:
                print_summary(results, log)
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    log.debug("Closing the browser failed", exc_info=True)

    if len(results) < len(dates) or any(r.status == "FAILED" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
