"""Weekly delivery schedules: parsing tool input, naming Reddit's blocks, describing them."""

from __future__ import annotations

from adloop.reddit.schedule import describe_schedule, named_blocks, parse_schedule


# The EN ad group on the AdLoop account as Reddit returns it (Mon–Fri
# 13:00–23:59 in Ads Manager): days 0–4, so 0 is Monday, not Sunday.
_MON_FRI = [
    {"start_day": d, "start_hour": 13, "end_day": d, "end_hour": 23} for d in range(5)
]


class TestParse:
    def test_days_shorthand_expands_to_one_block_per_day(self):
        errors: list[str] = []
        blocks = parse_schedule([{"days": "MON-FRI", "start_hour": 13, "end_hour": 23}], errors)
        assert errors == []
        assert blocks == _MON_FRI

    def test_day_list_and_single_day(self):
        errors: list[str] = []
        blocks = parse_schedule(
            [{"days": ["Sat", "sunday"], "start_hour": 9, "end_hour": 17}, {"days": "WED", "start_hour": 0, "end_hour": 23}],
            errors,
        )
        assert errors == []
        assert [b["start_day"] for b in blocks] == [5, 6, 2]

    def test_range_wrapping_the_weekend(self):
        errors: list[str] = []
        blocks = parse_schedule([{"days": "SAT-MON", "start_hour": 8, "end_hour": 20}], errors)
        assert [b["start_day"] for b in blocks] == [5, 6, 0]

    def test_native_shape_with_names_and_overnight_window(self):
        errors: list[str] = []
        blocks = parse_schedule(
            [{"start_day": "FRI", "start_hour": 22, "end_day": "SAT", "end_hour": 3}], errors
        )
        assert errors == []
        assert blocks == [{"start_day": 4, "start_hour": 22, "end_day": 5, "end_hour": 3}]

    def test_empty_list_clears_and_none_means_untouched(self):
        errors: list[str] = []
        assert parse_schedule([], errors) == []
        assert parse_schedule(None, errors) is None
        assert errors == []

    def test_numeric_days_are_refused_as_ambiguous(self):
        errors: list[str] = []
        parse_schedule([{"start_day": 0, "start_hour": 1, "end_day": 0, "end_hour": 2}], errors)
        assert any("day name" in e and "ambiguous" in e for e in errors)

    def test_hours_and_order_are_validated(self):
        errors: list[str] = []
        parse_schedule(
            [
                {"days": "MON", "start_hour": 24, "end_hour": 5},
                {"days": "TUE", "start_hour": 20, "end_hour": 8},
                {"days": "XYZ", "start_hour": 1, "end_hour": 2},
                "not a block",
            ],
            errors,
        )
        joined = " ".join(errors)
        assert "between 0 and 23" in joined
        assert "before start_hour" in joined
        assert "unknown day" in joined
        assert "must be an object" in joined

    def test_non_list_is_an_error(self):
        errors: list[str] = []
        assert parse_schedule("MON-FRI", errors) is None
        assert errors and "list of time blocks" in errors[0]


class TestDescribe:
    def test_names_and_collapses_consecutive_days(self):
        assert named_blocks(_MON_FRI)[0] == {"start_day": "MON", "start_hour": 13, "end_day": "MON", "end_hour": 23}
        assert describe_schedule(_MON_FRI) == "Mon–Fri 13:00–23:59"

    def test_empty_is_any_time(self):
        assert describe_schedule([]) == "any time"
        assert describe_schedule(None) == "any time"

    def test_mixed_hours_and_overnight_blocks_are_listed(self):
        blocks = [
            {"start_day": 0, "start_hour": 9, "end_day": 0, "end_hour": 17},
            {"start_day": 1, "start_hour": 9, "end_day": 1, "end_hour": 17},
            {"start_day": 2, "start_hour": 13, "end_day": 2, "end_hour": 23},
            {"start_day": 4, "start_hour": 22, "end_day": 5, "end_hour": 3},
        ]
        assert describe_schedule(blocks) == "Mon–Tue 09:00–17:59; Wed 13:00–23:59; Fri 22:00 to Sat 03:59"

    def test_gap_in_days_breaks_the_range(self):
        blocks = [
            {"start_day": 0, "start_hour": 9, "end_day": 0, "end_hour": 17},
            {"start_day": 2, "start_hour": 9, "end_day": 2, "end_hour": 17},
        ]
        assert describe_schedule(blocks) == "Mon 09:00–17:59; Wed 09:00–17:59"

    def test_garbage_blocks_are_skipped(self):
        assert named_blocks(["x", {"start_day": "a"}]) == []
