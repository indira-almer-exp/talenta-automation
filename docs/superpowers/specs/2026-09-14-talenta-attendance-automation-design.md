# Talenta Weekly Attendance Automation — Design

**Date:** 2026-09-14
**Status:** Approved for planning

## 1. Goal

A double-clickable Windows tool that submits Mekari Talenta attendance requests
for Monday through the current day of the current week (capped at Friday), each
with check-in 08:30 and check-out 18:00 and a single-space note. The user logs
in by hand; the tool never sees or stores credentials.

## 2. Decisions already made

| Topic | Decision |
|---|---|
| Times | Fixed 08:30 check-in, 18:00 check-out, stored in `config.json` |
| Notes | One space character `" "` (Talenta rejects an empty note) |
| Days already recorded, on leave, or holidays | Submit anyway; Talenta's rejection is logged as a failure |
| Week rule | Monday of the current ISO week through `min(today, Friday)`. Saturday/Sunday runs cover Mon–Fri of the week just ended |
| Packaging | Python 3.13 + Playwright (already installed, Chromium 1208 present) + `.bat` launcher |
| Approach | Visible-browser UI automation with Playwright. No API reverse-engineering, no remembered login |

## 3. Files

All inside `C:\Users\indiraa\Desktop\Talenta Automation\`.

| File | Purpose |
|---|---|
| `run_attendance.bat` | Double-click entry point. Runs `python talenta_attendance.py`, then `pause` so the log stays readable |
| `run_attendance_dryrun.bat` | Same, with `--dry-run` |
| `talenta_attendance.py` | The program: argument parsing, date logic, browser control, per-day form flow, summary |
| `talenta_selectors.py` | Every CSS selector and URL fragment the page flow depends on, as module constants |
| `config.json` | `login_url`, `attendance_url`, `dashboard_url`, `check_in`, `check_out`, `notes`, `login_timeout_minutes` (10), `action_timeout_seconds` (15) |
| `requirements.txt` | `playwright>=1.58`, `pytest` |
| `pyproject.toml` | pytest configuration only (`pythonpath = ["."]`, `testpaths = ["tests"]`) so bare `pytest` works; not a packaging manifest |
| `tests/test_dates.py` | Unit tests for the date-range function |
| `logs/` | Created on demand; git-ignored. `run_YYYY-MM-DD_HHMMSS.log` plus `fail_YYYY-MM-DD.png` per failed day |
| `.gitignore` | `logs/`, `__pycache__/`, `.pytest_cache/` |

## 4. Program flow

```
main()
 ├─ parse args: --dry-run, --only YYYY-MM-DD (repeatable)
 ├─ load config.json
 ├─ dates = target_dates(today) or the --only list
 ├─ open logger (console + logs/run_*.log)
 ├─ launch Chromium (headless=False), new page, default timeout = action_timeout
 ├─ goto login_url
 ├─ wait_for_login(page): wait until URL starts with dashboard_url, up to login_timeout
 ├─ for date in dates:
 │     result = submit_day(page, date, config, dry_run)   # never raises
 │     results.append(result)
 ├─ print summary table (date, status, reason)
 └─ close browser (in dry-run: leave open until Enter pressed)
```

### 4.1 `target_dates(today: date) -> list[date]`

Pure function. `monday = today - timedelta(days=today.weekday())`. Last day is
`today` if `today.weekday() <= 4`, otherwise `monday + 4 days`. Returns the
inclusive list from `monday` to that last day.

### 4.2 `wait_for_login(page)`

`page.wait_for_url(lambda url: url.startswith(dashboard_url), timeout=login_timeout)`.
On timeout: log "Login not completed within N minutes", close browser, exit code 1.
Nothing has been submitted at this point.

### 4.3 `submit_day(page, date, config, dry_run) -> DayResult`

`DayResult` is a dataclass: `date`, `status` (`SUBMITTED` / `DRY_RUN` / `FAILED`),
`reason` (empty on success), `screenshot` (path or `None`).

Steps, using the selectors in section 5:

1. `page.goto(attendance_url)`; wait for `REQUEST_BUTTON` to be visible.
   If the URL lands on the login page instead (session expired), call
   `wait_for_login` again, then retry `goto` once.
2. Click `REQUEST_BUTTON`; wait for `MODAL` to be visible.
3. Click `ATTENDANCE_RADIO_LABEL`.
4. Set the effective date by evaluating in the page:
   `$(SEL).pickadate('picker').set('select', new Date(y, m-1, d))`.
   This updates the visible field, the hidden `datepicker_request_submit`
   field, and fires the page's own `change` handler, which POSTs
   `/attendance/get-current-shift` and fills the shift and date dropdowns.
   Wrap the `evaluate` call in `page.expect_response(url contains
   "get-current-shift")` so the script waits for that round-trip.
5. Verify, polling up to `action_timeout`:
   - hidden `datepicker_request_submit` value == `YYYY-MM-DD`
   - `SHIFT_SELECT` value is non-empty
   - `CHECKIN_DATE_SELECT` and `CHECKOUT_DATE_SELECT` values == `YYYY-MM-DD`
   - `CHECKIN_BOX` and `CHECKOUT_BOX` are checked
   Any mismatch after the timeout is a failure with a descriptive reason
   (for example "Shift dropdown stayed empty — probably a day off").
6. `fill(CHECKIN_TIME, "08:30")`, `fill(CHECKOUT_TIME, "18:00")`; read back
   both values and confirm they match (the `99:99` input mask must not have
   mangled them).
7. `fill(NOTES, " ")`.
8. If `dry_run`: return `DRY_RUN`, leave the modal open, do not click Submit.
9. Otherwise, inside `page.expect_response(url contains "save-request")`,
   click `SUBMIT_BUTTON`. Parse the JSON body:
   - `result == "OK"` → the page reloads itself; `page.wait_for_load_state()`;
     return `SUBMITTED`.
   - anything else → return `FAILED` with `errorMsg` as the reason.
10. Any exception or failed verification: take a full-page screenshot to
    `logs/fail_YYYY-MM-DD.png`, log the traceback, try to click
    `CANCEL_BUTTON` (ignore errors), return `FAILED`. The loop continues with
    the next date.

### 4.4 Summary

Printed at the end and written to the log, one line per date:

```
2026-09-14  SUBMITTED
2026-09-15  FAILED     Attendance already exists   logs/fail_2026-09-15.png
```

Exit code 0 if every date is `SUBMITTED`/`DRY_RUN`, 2 if any failed.

## 5. Selectors (`talenta_selectors.py`)

Taken from the saved attendance page and Talenta's `scriptEmployeeAttendance.js`.

| Constant | Value |
|---|---|
| `REQUEST_BUTTON` | `#changeShiftRequestBtn` |
| `MODAL` | `#modalReqAttendance` |
| `ATTENDANCE_RADIO` | `#typeRequestCheckin` |
| `ATTENDANCE_RADIO_LABEL` | `label[for="typeRequestCheckin"]` |
| `EFFECTIVE_DATE` | `#datepicker_request` |
| `EFFECTIVE_DATE_HIDDEN` | `input[name="datepicker_request_submit"]` |
| `SHIFT_SELECT` | `#checkinrequest-shift_id` |
| `CHECKIN_BOX` / `CHECKOUT_BOX` | `#checkInBox` / `#checkOutBox` |
| `CHECKIN_TIME` / `CHECKOUT_TIME` | `#checkInAttendance` / `#checkOutAttendance` |
| `CHECKIN_DATE_SELECT` / `CHECKOUT_DATE_SELECT` | `#checkInDateAttendance` / `#checkOutDateAttendance` |
| `NOTES` | `#changeshiftrequest-reason` |
| `SUBMIT_BUTTON` | `#btnSaveRequest` |
| `CANCEL_BUTTON` | `#modalReqAttendance .custom-cancel-btn` |
| `SHIFT_LOOKUP_PATH` | `/attendance/get-current-shift` |
| `SAVE_REQUEST_PATH` | `/attendance/save-request` |
| `LOGIN_HOST` | `account.mekari.com` (URL substring meaning "bounced to login") |
| `TOAST` | `#toast-container .toast` (Materialize toast, read when Submit is blocked client-side) |

Materialize hides native `<select>`, radio and checkbox inputs, so the script
reads their values through `input_value()` / `is_checked()` / `evaluate`
rather than interacting with them visually, and clicks labels for radios.

## 6. Error handling summary

| Situation | Behaviour |
|---|---|
| Login not completed in 10 min | Exit 1, nothing submitted |
| Session expires mid-run | Wait for re-login (10 min), retry the same date once |
| Any per-day failure (selector missing, verification mismatch, Talenta rejection, timeout) | Screenshot + log + cancel modal, continue to next date |
| Every browser action | 15 s timeout via Playwright default timeout |
| Unexpected exception outside the per-day loop | Logged with traceback, browser closed, exit 1 |

## 7. Testing

1. **Unit tests** (`pytest tests/`): `target_dates` for a Monday, Wednesday,
   Friday, Saturday and Sunday input; fixed dates, no reliance on the clock.
2. **Dry run**: `run_attendance_dryrun.bat` or `--dry-run --only <date>`.
   Fills the form for one date and stops with the modal open for visual
   comparison against the reference screenshot. First real-browser test.
3. **Single live submission**: `--only <date>` for one past day; verify the
   request appears in Talenta's request history before running a full week.
4. **Full run** on a Friday.

## 8. Out of scope

Remembering the login, auto-scheduling on Fridays, skipping holidays or days
that already have records, randomized times, Windows notifications, handling
the Shift-change request type.
