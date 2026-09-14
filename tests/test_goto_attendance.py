import logging

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

import talenta_attendance as ta

CONFIG = {"attendance_url": "https://hr.talenta.co/my-info/attendance?id=1"}
LOGIN = "https://account.mekari.com/users/sign_in?client_id=TAL"
LOG = logging.getLogger("test")


class FakePage:
    """Scripts the URL the browser lands on after each goto."""

    def __init__(self, landing_urls, button_visible=True):
        self.landing_urls = list(landing_urls)
        self.button_visible = button_visible
        self.url = ""
        self.goto_calls = 0
        self.selector_waits = 0

    def goto(self, url, **kwargs):
        self.goto_calls += 1
        self.url = self.landing_urls.pop(0)

    def wait_for_selector(self, selector, **kwargs):
        self.selector_waits += 1
        if not self.button_visible:
            raise PlaywrightTimeout("no Request button")


def test_normal_load_needs_one_goto_and_one_wait():
    page = FakePage([CONFIG["attendance_url"]])
    ta.goto_attendance(page, CONFIG, LOG, 1_000)
    assert (page.goto_calls, page.selector_waits) == (1, 1)


def test_bounce_to_login_waits_for_relogin_then_retries(monkeypatch):
    page = FakePage([LOGIN, CONFIG["attendance_url"]])
    predicates = []
    monkeypatch.setattr(ta, "wait_for_login", lambda p, c, l, ready=None: predicates.append(ready))
    ta.goto_attendance(page, CONFIG, LOG, 1_000)
    assert page.goto_calls == 2
    assert page.selector_waits == 1  # no selector wait while sitting on the login page
    ready = predicates[0]
    assert ready("https://hr.talenta.co/employee/dashboard")
    assert not ready(LOGIN)


def test_still_on_login_after_relogin_fails_the_day(monkeypatch):
    page = FakePage([LOGIN, LOGIN])
    monkeypatch.setattr(ta, "wait_for_login", lambda *args, **kwargs: None)
    with pytest.raises(ta.DayFailure, match="Still on the login page"):
        ta.goto_attendance(page, CONFIG, LOG, 1_000)


def test_missing_request_button_fails_the_day():
    page = FakePage([CONFIG["attendance_url"]], button_visible=False)
    with pytest.raises(ta.DayFailure, match="did not load"):
        ta.goto_attendance(page, CONFIG, LOG, 1_000)
