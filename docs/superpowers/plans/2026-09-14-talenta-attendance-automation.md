# Talenta Weekly Attendance Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A double-clickable Windows tool that, after the user logs in to Mekari Talenta by hand, submits one attendance request (08:30 in, 18:00 out, note `" "`) for each weekday from Monday through today of the current week.

**Architecture:** One Python module (`talenta_attendance.py`) drives a visible Chromium window through Playwright's sync API. Pure date logic and argument parsing are unit-tested; the browser flow is verified with a `--dry-run` mode that fills the form but never clicks Submit. All page selectors live in `talenta_selectors.py`; all user-editable values live in `config.json`. Success and failure are read from Talenta's own JSON reply to `/attendance/save-request`, not guessed from the screen.

**Tech Stack:** Python 3.13, Playwright 1.58 (already installed, Chromium bundle present), pytest, Windows `.bat` launchers.

**Spec:** `docs/superpowers/specs/2026-09-14-talenta-attendance-automation-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Pinned dependencies (`playwright`, `pytest`) |
| `pyproject.toml` | pytest configuration only (`pythonpath = ["."]`, `testpaths`), so bare `pytest` finds the module; not a packaging manifest |
| `config.json` | URLs, times, notes text, timeouts — the only file a non-programmer edits |
| `talenta_selectors.py` | Every CSS selector / URL fragment the page flow depends on; constants only. Named `talenta_selectors`, not `selectors`, because `selectors` is a Python standard-library module that asyncio/Playwright import — shadowing it would break the program |
| `talenta_attendance.py` | Program: `target_dates`, `parse_args`, config + logging, `DayResult`, browser steps, `submit_day`, `main` |
| `tests/test_dates.py` | Unit tests for `target_dates`, `parse_args`, `format_result` |
| `run_attendance.bat` | Double-click launcher (live) |
| `run_attendance_dryrun.bat` | Double-click launcher (`--dry-run`) |
| `logs/` | Runtime output, git-ignored (already in `.gitignore`) |

All commands below are run from `C:\Users\indiraa\Desktop\Talenta Automation` in PowerShell.

---

### Task 1: Project scaffolding — dependencies, config, selectors

**Files:**
- Create: `requirements.txt`
- Create: `config.json`
- Create: `talenta_selectors.py`

- [ ] **Step 1: Write `requirements.txt`**

```text
playwright>=1.58
pytest>=8
```

- [ ] **Step 2: Install pytest (Playwright is already present)**

Run: `pip install -r requirements.txt`
Expected: ends with `Successfully installed pytest-...` or `Requirement already satisfied` lines, no errors.

- [ ] **Step 3: Confirm Playwright can launch Chromium**

Run: `python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); print('chromium ok', b.version); b.close(); p.stop()"`
Expected: `chromium ok 1xx.x.xxxx.xx`. If it complains about a missing browser, run `python -m playwright install chromium` and retry.

- [ ] **Step 4: Write `config.json`**

```json
{
  "login_url": "https://account.mekari.com/users/sign_in?client_id=TAL-73645&return_to=L2F1dGg_Y2xpZW50X2lkPVRBTC03MzY0NSZyZXNwb25zZV90eXBlPWNvZGUmc2NvcGU9c3NvOnByb2ZpbGU%3D",
  "dashboard_url": "https://hr.talenta.co/employee/dashboard",
  "attendance_url": "https://hr.talenta.co/my-info/attendance?id=3345449",
  "check_in": "08:30",
  "check_out": "18:00",
  "notes": " ",
  "login_timeout_minutes": 10,
  "action_timeout_seconds": 15
}
```

- [ ] **Step 5: Write `talenta_selectors.py`**

```python
"""Selectors and URL fragments for Talenta's attendance request modal.

Values come from the saved attendance page and Talenta's
scriptEmployeeAttendance.js. If Talenta changes its layout, fix it here.
"""

LOGIN_HOST = "account.mekari.com"

REQUEST_BUTTON = "#changeShiftRequestBtn"
MODAL = "#modalReqAttendance"

ATTENDANCE_RADIO = "#typeRequestCheckin"
ATTENDANCE_RADIO_LABEL = 'label[for="typeRequestCheckin"]'

EFFECTIVE_DATE = "#datepicker_request"
EFFECTIVE_DATE_HIDDEN = 'input[name="datepicker_request_submit"]'

SHIFT_SELECT = "#checkinrequest-shift_id"

CHECKIN_BOX = "#checkInBox"
CHECKOUT_BOX = "#checkOutBox"
CHECKIN_TIME = "#checkInAttendance"
CHECKOUT_TIME = "#checkOutAttendance"
CHECKIN_DATE_SELECT = "#checkInDateAttendance"
CHECKOUT_DATE_SELECT = "#checkOutDateAttendance"

NOTES = "#changeshiftrequest-reason"

SUBMIT_BUTTON = "#btnSaveRequest"
CANCEL_BUTTON = "#modalReqAttendance .custom-cancel-btn"

TOAST = "#toast-container .toast"

SHIFT_LOOKUP_PATH = "/attendance/get-current-shift"
SAVE_REQUEST_PATH = "/attendance/save-request"
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.json talenta_selectors.py
git commit -m "Add dependencies, config and page selectors"
```

---

### Task 2: Date logic and argument parsing (TDD)

**Files:**
- Create: `talenta_attendance.py`
- Create: `tests/test_dates.py`

Reference: 2026-09-14 is a Monday, so 2026-09-14..18 is Mon..Fri and 19/20 are Sat/Sun.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dates.py`:

```python
from datetime import date

from talenta_attendance import parse_args, target_dates

MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 9, d) for d in range(14, 21))


def test_friday_gives_monday_to_friday():
    assert target_dates(FRI) == [MON, TUE, WED, THU, FRI]


def test_wednesday_stops_at_wednesday():
    assert target_dates(WED) == [MON, TUE, WED]


def test_monday_gives_only_monday():
    assert target_dates(MON) == [MON]


def test_saturday_gives_full_week_just_ended():
    assert target_dates(SAT) == [MON, TUE, WED, THU, FRI]


def test_sunday_gives_full_week_just_ended():
    assert target_dates(SUN) == [MON, TUE, WED, THU, FRI]


def test_parse_args_defaults():
    args = parse_args([])
    assert args.dry_run is False
    assert args.only is None


def test_parse_args_only_is_repeatable_and_parsed_as_dates():
    args = parse_args(["--dry-run", "--only", "2026-09-14", "--only", "2026-09-16"])
    assert args.dry_run is True
    assert args.only == [MON, WED]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests -v`
Expected: `ERROR` collecting — `ModuleNotFoundError: No module named 'talenta_attendance'`.

- [ ] **Step 3: Write the minimal implementation**

Create `talenta_attendance.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add talenta_attendance.py tests/test_dates.py
git commit -m "Add week date logic and CLI argument parsing with tests"
```

---

### Task 3: Config loading, logging, result type and summary formatting

**Files:**
- Modify: `talenta_attendance.py`
- Modify: `tests/test_dates.py`

- [ ] **Step 1: Write the failing test for summary formatting**

Append to `tests/test_dates.py`:

```python
from pathlib import Path

from talenta_attendance import DayResult, format_result


def test_format_result_success_has_no_trailing_noise():
    assert format_result(DayResult(MON, "SUBMITTED")) == "2026-09-14  SUBMITTED"


def test_format_result_failure_includes_reason_and_screenshot():
    result = DayResult(TUE, "FAILED", "Shift dropdown stayed empty", Path("logs/fail_2026-09-15.png"))
    assert format_result(result) == (
        "2026-09-15  FAILED      Shift dropdown stayed empty  logs\\fail_2026-09-15.png"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests -v`
Expected: `ImportError: cannot import name 'DayResult'`.

- [ ] **Step 3: Add config, logging, `DayResult`, `format_result`**

In `talenta_attendance.py`, replace the import block at the top with:

```python
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
```

Then append after `parse_args`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests -v`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add talenta_attendance.py tests/test_dates.py
git commit -m "Add config loading, logging, DayResult and summary formatting"
```

---

### Task 4: Browser steps for one day

These functions talk to the live page and are verified in Task 6's dry run rather than by unit tests. Each raises `DayFailure` with a human-readable reason when something is wrong.

**Files:**
- Modify: `talenta_attendance.py`

- [ ] **Step 1: Add Playwright imports and the selectors module**

In `talenta_attendance.py`, extend the import block (after `from pathlib import Path`):

```python
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect, sync_playwright

import talenta_selectors as sel
```

- [ ] **Step 2: Add the exception types and login wait**

Append to `talenta_attendance.py`:

```python
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
```

- [ ] **Step 3: Add navigation and modal opening**

Append:

```python
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
```

- [ ] **Step 4: Add effective-date setting through the page's own picker**

Append:

```python
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
```

- [ ] **Step 5: Add verification of the auto-filled fields**

Append:

```python
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
```

- [ ] **Step 6: Add time/notes filling, submit, and post-submit wait**

Append:

```python
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
```

- [ ] **Step 7: Sanity-check the module still imports and tests still pass**

Run: `python -m pytest tests -v`
Expected: `9 passed`.

- [ ] **Step 8: Commit**

```bash
git add talenta_attendance.py
git commit -m "Add browser steps for opening and filling the attendance request modal"
```

---

### Task 5: Per-day orchestration and `main`

**Files:**
- Modify: `talenta_attendance.py`

- [ ] **Step 1: Add failure handling and `submit_day`**

Append to `talenta_attendance.py`:

```python
def record_failure(page: Page, day: date, reason: str, log: logging.Logger) -> DayResult:
    log.error("FAILED %s: %s", day.isoformat(), reason)
    screenshot: Path | None = LOG_DIR / f"fail_{day.isoformat()}.png"
    try:
        page.screenshot(path=str(screenshot), full_page=True)
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
        goto_attendance(page, config, log)
        open_request_modal(page)
        set_effective_date(page, day, timeout_ms)
        verify_prefilled(page, day, timeout_ms)
        fill_times_and_notes(page, config)
        if dry_run:
            log.info("Form filled; Submit NOT clicked (dry run).")
            return DayResult(day, "DRY_RUN")
        reply = click_submit(page, timeout_ms)
        if reply.get("result") == "OK":
            wait_for_reload(page, timeout_ms)
            log.info("Submitted: %s", reply.get("errorMsg", ""))
            return DayResult(day, "SUBMITTED")
        raise DayFailure(f"Talenta rejected the request: {reply.get('errorMsg', reply)}")
    except LoginTimeout:
        raise
    except DayFailure as exc:
        return record_failure(page, day, str(exc), log)
    except Exception as exc:
        log.debug("Traceback for %s", day.isoformat(), exc_info=True)
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        return record_failure(page, day, f"{type(exc).__name__}: {first_line}", log)
```

- [ ] **Step 2: Add `main`**

Append:

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config()
    log = setup_logger()
    dates = args.only or target_dates(date.today())
    log.info("Target dates: %s", ", ".join(d.isoformat() for d in dates))
    if args.dry_run:
        log.info("DRY RUN - Submit will not be clicked.")

    results: list[DayResult] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(config["action_timeout_seconds"] * 1_000)
        try:
            page.goto(config["login_url"])
            wait_for_login(page, config, log)
            for day in dates:
                result = submit_day(page, day, config, args.dry_run, log)
                results.append(result)
                if result.status == "DRY_RUN":
                    input("  Inspect the filled form in the browser, then press Enter to continue... ")
        except LoginTimeout as exc:
            log.error("%s. Nothing was submitted.", exc)
            return 1
        except Exception:
            log.exception("Unexpected error - stopping.")
            return 1
        finally:
            browser.close()

    print_summary(results, log)
    return 0 if all(r.status != "FAILED" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Check the CLI help renders and tests still pass**

Run: `python talenta_attendance.py --help`
Expected: usage text listing `--dry-run` and `--only YYYY-MM-DD`.

Run: `python -m pytest tests -v`
Expected: `9 passed`.

- [ ] **Step 4: Commit**

```bash
git add talenta_attendance.py
git commit -m "Add per-day orchestration and main entry point"
```

---

### Task 6: Double-click launchers

**Files:**
- Create: `run_attendance.bat`
- Create: `run_attendance_dryrun.bat`

- [ ] **Step 1: Write `run_attendance.bat`**

```bat
@echo off
cd /d "%~dp0"
python talenta_attendance.py %*
echo.
echo Exit code %ERRORLEVEL% (0 = all submitted, 2 = some dates failed, 1 = run aborted)
pause
```

- [ ] **Step 2: Write `run_attendance_dryrun.bat`**

```bat
@echo off
cd /d "%~dp0"
python talenta_attendance.py --dry-run %*
echo.
echo Exit code %ERRORLEVEL%
pause
```

- [ ] **Step 3: Verify the launcher reaches the login page**

Run: `.\run_attendance_dryrun.bat --only 2026-09-14`
Expected: a Chromium window opens on the Mekari login page and the console prints `Please log in in the browser window (waiting up to 10 minutes)...`. Do **not** log in yet — close the browser window; the console should print `Unexpected error - stopping.` (the page was closed) and `Exit code 1`, then wait for a key press.

- [ ] **Step 4: Commit**

```bash
git add run_attendance.bat run_attendance_dryrun.bat
git commit -m "Add double-click launchers for live and dry runs"
```

---

### Task 7: Live verification (needs the user at the keyboard)

No new files. This task confirms the real page behaves as the saved HTML predicted. Each step's problems are fixed in `talenta_selectors.py` or the relevant function in `talenta_attendance.py`, then committed.

- [ ] **Step 1: Dry run on one past weekday**

Run: `.\run_attendance_dryrun.bat --only 2026-09-14` (use the most recent past weekday if different) and log in when the browser opens.
Expected console: `Logged in.`, `=== 2026-09-14 ===`, `Form filled; Submit NOT clicked (dry run).`, then the Enter prompt.
Expected browser: the Request modal open with Attendance selected, Effective Date `14 September, 2026`, a shift chosen, both boxes ticked, `08:30` / `18:00`, both date dropdowns `14 Sep, 2026`, Notes containing a space. Compare against the reference screenshot in the spec discussion. Press Enter; expected summary line `2026-09-14  DRY_RUN`.

If a step fails, the reason and `logs/fail_2026-09-14.png` say which field; adjust and rerun.

- [ ] **Step 2: Single live submission**

Run: `.\run_attendance.bat --only 2026-09-14` and log in.
Expected: `Submitted: ...` and summary `2026-09-14  SUBMITTED`, exit code 0. In Talenta, open the attendance page and confirm the new request appears in the request history table with the right date and times.

- [ ] **Step 3: Confirm the duplicate path is handled**

Run the same command again: `.\run_attendance.bat --only 2026-09-14`.
Expected: either `SUBMITTED` again (if Talenta allows a second pending request for the same day) or `FAILED 2026-09-14: Talenta rejected the request: <Talenta's message>` with a screenshot in `logs/` and exit code 2. Either way the browser must not hang and the summary must print.

- [ ] **Step 4: Full-week run**

On Friday, double-click `run_attendance.bat`. Expected: one `SUBMITTED` (or explained `FAILED`) line per weekday and the window waiting for a key press.

- [ ] **Step 5: Commit any selector or flow fixes**

```bash
git add -A
git commit -m "Adjust selectors/flow after live verification"
```

(Skip if nothing changed.)
