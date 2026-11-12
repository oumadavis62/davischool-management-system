import unittest
from datetime import datetime, timedelta

from app.timetable.time_utils import EAT, format_eat, now_eat


class TimetableTimeUtilsTests(unittest.TestCase):
    def test_now_eat_returns_explicit_utc_plus_three_offset(self):
        value = datetime.fromisoformat(now_eat())
        self.assertEqual(value.utcoffset(), timedelta(hours=3))
        self.assertEqual(EAT.key, "Africa/Nairobi")

    def test_format_eat_converts_legacy_utc_timestamp(self):
        self.assertEqual(format_eat("2026-11-12T12:00:00Z"), "12 Nov 2026 15:00 EAT")

    def test_format_eat_treats_legacy_naive_database_timestamp_as_utc(self):
        self.assertEqual(format_eat("2026-11-12 12:00:00"), "12 Nov 2026 15:00 EAT")

    def test_format_eat_preserves_eat_wall_clock_time(self):
        self.assertEqual(format_eat("2026-11-12T15:00:00+03:00"), "12 Nov 2026 15:00 EAT")

    def test_format_eat_handles_postgres_naive_timestamp_as_eat(self):
        self.assertEqual(format_eat(datetime(2026, 11, 12, 15, 0, 0)), "12 Nov 2026 15:00 EAT")


if __name__ == "__main__":
    unittest.main()
