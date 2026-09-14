import logging
from datetime import date

import pytest

import talenta_attendance as ta

MON = date(2026, 9, 14)
CONFIG = {"action_timeout_seconds": 1}
LOG = logging.getLogger("test")

STEP_NAMES = (
    "goto_attendance",
    "open_request_modal",
    "set_effective_date",
    "verify_prefilled",
    "fill_times_and_notes",
    "wait_for_reload",
)


class StubPage:
    """Stands in for a Playwright page whose browser is already gone."""

    def screenshot(self, **kwargs):
        raise RuntimeError("no browser")

    def click(self, *args, **kwargs):
        raise RuntimeError("no browser")


def stub_steps(monkeypatch, reply):
    for name in STEP_NAMES:
        monkeypatch.setattr(ta, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ta, "click_submit", lambda page, timeout_ms: reply)


def test_ok_reply_is_reported_as_submitted(monkeypatch):
    stub_steps(monkeypatch, {"result": "OK", "errorMsg": "Request submitted"})
    result = ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert (result.status, result.reason) == ("SUBMITTED", "")


def test_rejection_uses_talentas_message(monkeypatch):
    stub_steps(monkeypatch, {"result": "FAILED", "errorMsg": "Attendance already exists\nignored"})
    result = ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert result.status == "FAILED"
    assert result.reason == "Talenta rejected the request: Attendance already exists"
    assert result.screenshot is None


def test_rejection_without_message_shows_the_raw_reply(monkeypatch):
    stub_steps(monkeypatch, {"result": "FAILED"})
    result = ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert result.reason == "Talenta rejected the request: {'result': 'FAILED'}"


def test_dry_run_never_clicks_submit(monkeypatch):
    stub_steps(monkeypatch, None)

    def must_not_be_called(page, timeout_ms):
        raise AssertionError("Submit must not be clicked in a dry run")

    monkeypatch.setattr(ta, "click_submit", must_not_be_called)
    assert ta.submit_day(StubPage(), MON, CONFIG, True, LOG).status == "DRY_RUN"


def test_unexpected_error_without_message_has_no_dangling_colon(monkeypatch):
    stub_steps(monkeypatch, None)
    monkeypatch.setattr(ta, "verify_prefilled", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    result = ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert (result.status, result.reason) == ("FAILED", "RuntimeError")


def test_login_timeout_aborts_instead_of_being_recorded(monkeypatch):
    stub_steps(monkeypatch, None)

    def expired(*args, **kwargs):
        raise ta.LoginTimeout("Login not completed within 10 minutes")

    monkeypatch.setattr(ta, "goto_attendance", expired)
    with pytest.raises(ta.LoginTimeout):
        ta.submit_day(StubPage(), MON, CONFIG, False, LOG)


def test_ok_reply_without_message_logs_plain_submitted(monkeypatch, caplog):
    stub_steps(monkeypatch, {"result": "OK"})
    with caplog.at_level(logging.INFO, logger="test"):
        ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert "Submitted" in caplog.text
    assert "Submitted:" not in caplog.text


def test_long_rejection_is_truncated(monkeypatch):
    stub_steps(monkeypatch, {"result": "FAILED", "errorMsg": "x" * 500})
    result = ta.submit_day(StubPage(), MON, CONFIG, False, LOG)
    assert result.reason == "Talenta rejected the request: " + "x" * 200
