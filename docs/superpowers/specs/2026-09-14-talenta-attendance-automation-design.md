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
| `tests/` | `test_dates.py` (week logic, CLI parsing, summary formatting), `test_submit_day.py` (reply handling with the browser steps stubbed), `test_main.py` (exit codes and summary-on-abort with a stub Playwright), `test_goto_attendance.py` (session-expiry retry) |
| `logs/` | Created on demand; git-ignored. `run_YYYY-MM-DD_HHMMSS.log` plus `fail_YYYY-MM-DD.png` per failed day |
| `.gitignore` | `logs/`, `__pycache__/`, `.pytest_cache/`, `.claude/settings.local.json` |

## 4. Program flow

```
main()
 ├─ parse args: --dry-run, --only YYYY-MM-DD (repeatable)
 ├─ load config.json
 ├─ dates = target_dates(today), or the --only list with duplicates removed
 ├─ open logger (console + logs/run_*.log)
 ├─ launch Chromium (headless=False), new page, default timeout = action_timeout
 ├─ goto login_url
 ├─ wait_for_login(page, config, log): wait until URL starts with dashboard_url, up to login_timeout
 ├─ for date in dates:
 │     result = submit_day(page, date, config, dry_run, log)   # raises only LoginTimeout
 │     results.append(result)
 │     stop if the browser window was closed; in dry-run, pause for Enter after each date
 ├─ print summary table (date, status, reason) - on every exit path, before closing the browser
 └─ close browser
```

### 4.1 `target_dates(today: date) -> list[date]`

Pure function. `monday = today - timedelta(days=today.weekday())`. Last day is
`today` if `today.weekday() <= 4`, otherwise `monday + 4 days`. Returns the
inclusive list from `monday` to that last day.

### 4.2 `wait_for_login(page, config, log, ready=None)`

`page.wait_for_url(ready, timeout=login_timeout)` where `ready` defaults to
`url.startswith(dashboard_url)`. On timeout at startup: log "Login not completed
within N minutes. Nothing was submitted.", close browser, exit code 1. The
mid-run re-login (section 4.3 step 1) passes a `ready` that accepts any URL on
the Talenta host, because Mekari sends the user back to the attendance page,
not the dashboard.

### 4.3 `submit_day(page, date, config, dry_run) -> DayResult`

`DayResult` is a dataclass: `date`, `status` (`SUBMITTED` / `DRY_RUN` / `FAILED`),
`reason` (empty on success), `screenshot` (path or `None`).

Steps, using the selectors in section 5:

1. `page.goto(attendance_url)`; wait for `REQUEST_BUTTON` to be visible.
   If the URL lands on `account.mekari.com` instead (session expired) - either
   immediately or after the button wait times out - call `wait_for_login`
   again, then retry `goto` once. Still on the login page after that: failure.
2. Click `REQUEST_BUTTON`; wait for `MODAL` to be visible.
3. Click `ATTENDANCE_RADIO_LABEL`; poll until `ATTENDANCE_RADIO` is checked.
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
   - `CHECKIN_BOX` and `CHECKOUT_BOX` are checked (also polled)
   Any mismatch after the timeout is a failure with a descriptive reason
   (for example "Shift dropdown stayed empty — probably a day off").
6. `fill(CHECKIN_TIME, "08:30")`, `fill(CHECKOUT_TIME, "18:00")`; read back
   both values and confirm they match (the `99:99` input mask must not have
   mangled them).
7. `fill(NOTES, " ")`.
8. If `dry_run`: return `DRY_RUN`, leave the modal open, do not click Submit.
9. Otherwise submit, reading Talenta's own JSON answer rather than the screen:
   - Arm a `MutationObserver` that records the newest toast text (Talenta's
     validation toasts vanish after ~3 s), and set a `window.__talentaSubmitted`
     marker on the current document.
   - Register a `page.route` for `/attendance/save-request` whose handler does
     `route.fetch()` (bounded at twice the action timeout), records status and
     body, then `route.fulfill()`s the page.
     The body must be captured this way because Talenta calls
     `location.reload()` the instant it receives OK and Chromium may discard
     the response before it could be read afterwards. If `route.fetch()`
     itself fails the handler `abort()`s so the POST is never re-sent.
   - Click `SUBMIT_BUTTON` inside `page.expect_response(...)`. Afterwards the
     route is removed with `unroute_all(behavior="wait")`: dropping a route
     while its `route.fetch()` is still pending makes Chromium release the
     original request as well, which would send the POST twice. A reply that
     arrives after the wait is still used as the result.
   - `result == "OK"` → wait until the marker is gone (the reload happened) and
     the new document is loaded; if that never happens, log a warning and still
     return `SUBMITTED` (the OK reply already proved acceptance).
   - any other JSON → `FAILED` with the first line of `errorMsg` as the reason.
   - Timeout with the POST never sent (client-side validation) → `FAILED`,
     "Submit did not go through: <toast text>".
   - Timeout after the POST was sent, or a reply that is not a JSON object →
     `FAILED` with "Submit result unknown - check Talenta's request history
     before rerunning this date (...)". The tool never claims "not submitted"
     once the request has left the browser.
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

Exit code 0 if every date is `SUBMITTED`/`DRY_RUN`; 2 if any failed or the
run stopped early (browser window closed); 1 if the run aborted before the
loop finished for another reason (login timeout, unreadable `config.json`,
unexpected error). The summary is printed on every exit path that attempted
at least one date, so the user always sees what was already submitted.

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
| `config.json` missing, malformed, missing a key, or a timeout that is not a positive number | Friendly one-line message, exit 1, no browser opened |
| Login not completed in 10 min | Exit 1, nothing submitted |
| Session expires mid-run | Wait for re-login (10 min), retry the same date once |
| Any per-day failure (selector missing, verification mismatch, Talenta rejection, timeout) | Screenshot + log + cancel modal, continue to next date |
| Reply to Submit not received in time, or unreadable, after the POST was sent | `FAILED` with "Submit result unknown - check Talenta's request history before rerunning this date" |
| Browser window closed by the user mid-run | Stop, print summary, exit 2 |
| Every browser action | 15 s timeout, passed explicitly |
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
