import logging
from contextlib import contextmanager
from datetime import date

import pytest

import talenta_attendance as ta

MON, TUE = date(2026, 9, 14), date(2026, 9, 15)


class StubPage:
    def __init__(self):
        self.closed = False

    def set_default_timeout(self, timeout):
        pass

    def goto(self, url, **kwargs):
        pass

    def is_closed(self):
        return self.closed


class StubBrowser:
    def __init__(self):
        self.page = StubPage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class StubPlaywright:
    def __init__(self, browser):
        self.chromium = self
        self.browser = browser

    def launch(self, **kwargs):
        return self.browser


@pytest.fixture(autouse=True)
def release_log_file():
    yield
    talenta_log = logging.getLogger("talenta")
    for handler in talenta_log.handlers:
        handler.close()
    talenta_log.handlers.clear()


@pytest.fixture
def browser(monkeypatch, tmp_path):
    stub_browser = StubBrowser()
    playwright = StubPlaywright(stub_browser)

    @contextmanager
    def fake_sync_playwright():
        yield playwright

    config = {key: 1 for key in ta.REQUIRED_CONFIG_KEYS} | {"login_url": "https://login.test/"}
    monkeypatch.setattr(ta, "sync_playwright", fake_sync_playwright)
    monkeypatch.setattr(ta, "load_config", lambda: config)
    monkeypatch.setattr(ta, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ta, "wait_for_login", lambda *args, **kwargs: None)
    return stub_browser


def log_text(tmp_path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("run_*.log"))


def test_abort_after_a_submitted_day_still_prints_the_summary(monkeypatch, tmp_path, browser):
    def submit(page, day, config, dry_run, log):
        if day == MON:
            return ta.DayResult(day, "SUBMITTED")
        raise ta.LoginTimeout("Login not completed within 10 minutes")

    monkeypatch.setattr(ta, "submit_day", submit)
    code = ta.main(["--only", "2026-09-14", "--only", "2026-09-15"])
    text = log_text(tmp_path)
    assert code == 1
    assert "see the summary for what was already submitted" in text
    assert "2026-09-14  SUBMITTED" in text
    assert browser.closed


def test_abort_before_any_day_says_nothing_was_submitted(monkeypatch, tmp_path, browser):
    def submit(page, day, config, dry_run, log):
        raise ta.LoginTimeout("Login not completed within 10 minutes")

    monkeypatch.setattr(ta, "submit_day", submit)
    assert ta.main(["--only", "2026-09-14"]) == 1
    text = log_text(tmp_path)
    assert "Nothing was submitted" in text
    assert "Summary" not in text


def test_closed_window_stops_the_run_with_exit_2(monkeypatch, tmp_path, browser):
    def submit(page, day, config, dry_run, log):
        browser.page.closed = True
        return ta.DayResult(day, "SUBMITTED")

    monkeypatch.setattr(ta, "submit_day", submit)
    assert ta.main(["--only", "2026-09-14", "--only", "2026-09-15"]) == 2
    assert "browser window was closed" in log_text(tmp_path)


def test_all_submitted_returns_0_and_closes_the_browser(monkeypatch, tmp_path, browser):
    monkeypatch.setattr(
        ta, "submit_day", lambda page, day, config, dry_run, log: ta.DayResult(day, "SUBMITTED")
    )
    assert ta.main(["--only", "2026-09-14", "--only", "2026-09-15"]) == 0
    assert browser.closed


def test_any_failed_day_returns_2(monkeypatch, tmp_path, browser):
    monkeypatch.setattr(
        ta,
        "submit_day",
        lambda page, day, config, dry_run, log: ta.DayResult(day, "FAILED" if day == TUE else "SUBMITTED", "nope"),
    )
    assert ta.main(["--only", "2026-09-14", "--only", "2026-09-15"]) == 2


def test_summary_survives_a_failing_browser_close(monkeypatch, tmp_path, browser):
    def broken_close():
        raise RuntimeError("driver gone")

    browser.close = broken_close
    monkeypatch.setattr(
        ta, "submit_day", lambda page, day, config, dry_run, log: ta.DayResult(day, "SUBMITTED")
    )
    assert ta.main(["--only", "2026-09-14"]) == 0
    assert "2026-09-14  SUBMITTED" in log_text(tmp_path)
