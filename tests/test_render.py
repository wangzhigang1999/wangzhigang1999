"""Check calendar arithmetic and failure behavior without network requests."""

import unittest
from datetime import UTC, date, datetime, timedelta
from xml.etree import ElementTree

from scripts.render import Breakdown, Day, Week, normalize, render, stats


class CardTests(unittest.TestCase):
    def test_streak_resets_and_counts_contributions_not_commits(self) -> None:
        days = [
            Day(date(2026, 1, 1) + timedelta(days=i), count, 1 if count else 0)
            for i, count in enumerate([0, 5, 3, 0, 1, 1, 1])
        ]
        self.assertEqual(stats(days), (11, 5, 3))

    def test_exact_window_across_year_boundary(self) -> None:
        today = date(2026, 1, 2)
        weeks: list[Week] = [
            {
                "contributionDays": [
                    {
                        "date": (today - timedelta(days=i)).isoformat(),
                        "contributionCount": i,
                        "contributionLevel": "FIRST_QUARTILE",
                    }
                    for i in range(90)
                ]
            }
        ]
        days = normalize(weeks, today)
        self.assertEqual(len(days), 84)
        self.assertEqual(days[0].date, date(2025, 10, 11))
        self.assertEqual(days[-1].date, today)
        with self.assertRaises(ValueError):
            normalize([], today)
        image = render("a&b", days, datetime(2026, 1, 2, tzinfo=UTC), Breakdown(12, 3, 2, 4))
        root = ElementTree.fromstring(image)
        self.assertIn("a&b", root.find("{http://www.w3.org/2000/svg}title").text or "")  # type: ignore[union-attr]
        self.assertNotIn("<script", image)


if __name__ == "__main__":
    unittest.main()
