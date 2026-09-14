from datetime import date
from pathlib import Path

from talenta_attendance import DayResult, format_result, parse_args, target_dates

# 2026-09-14 is a Monday, so 14..18 are Mon..Fri and 19/20 are the weekend.
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


def test_format_result_success_has_no_trailing_noise():
    assert format_result(DayResult(MON, "SUBMITTED")) == "2026-09-14  SUBMITTED"


def test_format_result_failure_includes_reason_and_screenshot():
    result = DayResult(TUE, "FAILED", "Shift dropdown stayed empty", Path("logs/fail_2026-09-15.png"))
    assert format_result(result) == (
        "2026-09-15  FAILED      Shift dropdown stayed empty  logs\\fail_2026-09-15.png"
    )
