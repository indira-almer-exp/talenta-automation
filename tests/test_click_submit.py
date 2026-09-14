from contextlib import contextmanager

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

import talenta_attendance as ta


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def text(self):
        return self._body


class FakeRoute:
    def __init__(self, response=None, fetch_error=None):
        self.response = response
        self.fetch_error = fetch_error
        self.calls = []

    def fetch(self, **kwargs):
        self.calls.append("fetch")
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.response

    def fulfill(self, **kwargs):
        self.calls.append("fulfill")

    def abort(self):
        self.calls.append("abort")

    def continue_(self):
        self.calls.append("continue")


class FakePage:
    """Drives click_submit's route handler the way Playwright would.

    `sent_route` is the FakeRoute handed to the handler when the click sends the
    request (None means the POST never leaves the browser). `response_seen` says
    whether expect_response is satisfied before it times out.
    """

    def __init__(self, sent_route=None, response_seen=True, toast=None):
        self.sent_route = sent_route
        self.response_seen = response_seen
        self.toast = toast
        self.handler = None
        self.unroute_calls = []

    def evaluate(self, js, arg=None):
        return self.toast if "__talentaToast" in js else None

    def route(self, matcher, handler):
        self.handler = handler

    def click(self, selector, **kwargs):
        if self.sent_route is not None:
            self.handler(self.sent_route)

    @contextmanager
    def expect_response(self, predicate, timeout):
        yield
        if not self.response_seen:
            raise PlaywrightTimeout("no response")

    def unroute_all(self, behavior=None):
        self.unroute_calls.append(behavior)


def ok_route(body='{"result": "OK", "errorMsg": "ok"}'):
    return FakeRoute(FakeResponse(200, body))


def test_normal_reply_is_returned_and_the_route_is_waited_out():
    route = ok_route()
    page = FakePage(route)
    assert ta.click_submit(page, 1_000) == {"result": "OK", "errorMsg": "ok"}
    assert route.calls == ["fetch", "fulfill"]
    # Dropping the route while its fetch is pending makes Chromium re-send the POST.
    assert page.unroute_calls == ["wait"]


def test_late_reply_is_still_used():
    page = FakePage(ok_route('{"result": "OK"}'), response_seen=False)
    assert ta.click_submit(page, 1_000) == {"result": "OK"}


def test_sent_without_answer_reports_unknown_result_and_never_resends():
    route = FakeRoute(fetch_error=RuntimeError("socket hang up"))
    page = FakePage(route, response_seen=False)
    with pytest.raises(ta.DayFailure) as info:
        ta.click_submit(page, 1_000)
    assert str(info.value).startswith(ta.UNKNOWN_RESULT)
    assert route.calls == ["fetch", "abort"]


def test_never_sent_reports_did_not_go_through_with_the_toast():
    page = FakePage(sent_route=None, response_seen=False, toast="Shift cannot be blank")
    with pytest.raises(ta.DayFailure, match="Submit did not go through: Shift cannot be blank"):
        ta.click_submit(page, 1_000)


def test_unreadable_reply_reports_unknown_result():
    page = FakePage(FakeRoute(FakeResponse(200, "<html>oops</html>")))
    with pytest.raises(ta.DayFailure, match="HTTP 200 without a readable result"):
        ta.click_submit(page, 1_000)


def test_non_object_reply_reports_unknown_result():
    page = FakePage(ok_route('["nope"]'))
    with pytest.raises(ta.DayFailure, match="unexpected reply"):
        ta.click_submit(page, 1_000)


def test_browser_error_after_sending_is_reported_as_unknown_result():
    class BrokenUnroutePage(FakePage):
        def unroute_all(self, behavior=None):
            raise RuntimeError("target closed")

    page = BrokenUnroutePage(ok_route(), response_seen=False)
    with pytest.raises(ta.DayFailure, match="browser error while waiting for the reply"):
        ta.click_submit(page, 1_000)
