"""Render a dependency-free, compact SVG using the public profile calendar."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import TypedDict, cast


class Contribution(TypedDict):
    date: str
    contributionCount: int
    contributionLevel: str


class Week(TypedDict):
    contributionDays: list[Contribution]


class Calendar(TypedDict):
    weeks: list[Week]


class Collection(TypedDict):
    contributionCalendar: Calendar
    totalCommitContributions: int
    totalPullRequestContributions: int
    totalIssueContributions: int
    totalPullRequestReviewContributions: int


class User(TypedDict):
    contributionsCollection: Collection


class Data(TypedDict):
    user: User | None


class Response(TypedDict):
    data: Data
    errors: list[object]


@dataclass(frozen=True)
class Day:
    date: date
    count: int
    level: int


@dataclass(frozen=True)
class Breakdown:
    commits: int
    pull_requests: int
    issues: int
    reviews: int


WINDOW_DAYS = 84


LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
COLORS = ["#d9dfcf", "#bac9a9", "#8da780", "#5e7b59", "#344b38"]


def normalize(weeks: list[Week], today: date) -> list[Day]:
    """Require all 84 dates; a broken response must not silently replace history with zeros."""
    found: dict[date, Day] = {}
    for week in weeks:
        for item in week["contributionDays"]:
            day = date.fromisoformat(item["date"])
            count = item["contributionCount"]
            if type(count) is not int or count < 0:
                raise ValueError("Invalid contribution count")
            found[day] = Day(day, count, LEVELS.index(item["contributionLevel"]))
    expected = [today - timedelta(days=WINDOW_DAYS - 1 - i) for i in range(WINDOW_DAYS)]
    if any(day not in found for day in expected):
        raise ValueError("Incomplete contribution calendar; keeping the existing card")
    return [found[day] for day in expected]


def fetch_activity(login: str, now: datetime) -> tuple[list[Day], Breakdown]:
    """Use the repository-scoped Actions token; never read device credentials or notifications."""
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){contributionsCollection(from:$from,to:$to){
        totalCommitContributions totalPullRequestContributions
        totalIssueContributions totalPullRequestReviewContributions
        contributionCalendar{weeks{contributionDays{date contributionCount contributionLevel}}}
      }}
    }"""
    start = datetime.combine(now.date() - timedelta(days=WINDOW_DAYS - 1), datetime.min.time(), UTC)
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(
            {
                "query": query,
                "variables": {
                    "login": login,
                    "from": start.isoformat(),
                    "to": now.isoformat(),
                },
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "glance-profile-card",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = cast(Response, json.load(response))
    if payload.get("errors") or not payload.get("data", {}).get("user"):
        raise ValueError("GitHub did not return a contribution calendar")
    user = payload["data"]["user"]
    assert user is not None
    collection = user["contributionsCollection"]
    breakdown = Breakdown(
        collection["totalCommitContributions"],
        collection["totalPullRequestContributions"],
        collection["totalIssueContributions"],
        collection["totalPullRequestReviewContributions"],
    )
    if any(type(v) is not int or v < 0 for v in vars(breakdown).values()):
        raise ValueError("Invalid contribution breakdown")
    return normalize(collection["contributionCalendar"]["weeks"], now.date()), breakdown


def stats(days: list[Day]) -> tuple[int, int, int]:
    streak = best = 0
    for day in days:
        streak = streak + 1 if day.count else 0
        best = max(best, streak)
    return sum(day.count for day in days), sum(day.count > 0 for day in days), best


def text(
    value: str, x: int, y: int, size: int = 11, color: str = "#68776e", weight: int = 400
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'font-weight="{weight}" font-family="Segoe UI,Arial,sans-serif">'
        f"{escape(value)}</text>"
    )


def render(
    login: str, days: list[Day], now: datetime, breakdown: Breakdown, *, mobile: bool = False
) -> str:
    """Reflow the same 84-day data; calendar columns follow real Sunday-based weeks."""
    total, active, best = stats(days)
    width, height = (400, 376) if mobile else (800, 228)
    title = f"{login}: {total} contributions, {active} active days in the last 12 weeks"
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">Updated {now:%Y-%m-%d} UTC. GitHub contribution counts, '
        "not all Git commits. Best streak is limited to this 84-day window. "
        "The four categories do not include repository creation or restricted activity.</desc>",
        f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" '
        'rx="12" fill="#fff" stroke="#dfe5df"/>',
        text("GitHub activity", 24, 28, 14, "#34473a", 600),
        text("Last 12 weeks", width - 108, 28),
    ]
    for x, value, label in [
        (24, total, "contributions"),
        (151 if mobile else 180, active, "active days"),
        (266 if mobile else 328, best, "best streak · days"),
    ]:
        svg.append(text(str(value), x, 81, 32, "#365744", 600))
        svg.append(text(label, x, 102))
    svg.append(f'<path d="M24 122H{376 if mobile else 462}" stroke="#e8ece7"/>')
    for i, (value, label) in enumerate(
        [
            (breakdown.commits, "Commits"),
            (breakdown.pull_requests, "PRs opened"),
            (breakdown.issues, "Issues opened"),
            (breakdown.reviews, "PR reviews"),
        ]
    ):
        x = 24 + i * (92 if mobile else 114)
        svg.append(text(str(value), x, 153, 22, "#365744", 600))
        svg.append(text(label, x, 174, 10))
    # An 84-day window can span 13 calendar columns; blank edge cells stay absent.
    chart_x, chart_y = (110, 208) if mobile else (548, 60)
    offset = (days[0].date.weekday() + 1) % 7
    for row, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        svg.append(text(label, chart_x - 34, chart_y + row * 17 + 10, 10))
    for i, day in enumerate(days):
        column, row = divmod(offset + i, 7)
        x, y = chart_x + column * 17, chart_y + row * 17
        svg.append(
            f'<rect x="{x}" y="{y}" width="13" height="13" rx="3" '
            f'fill="{COLORS[day.level]}"><title>{day.date}: '
            f"{day.count} contributions</title></rect>"
        )
    svg.extend(
        [
            text(f"{days[0].date:%b %d} – {days[-1].date:%b %d, %Y}", 24, height - 18, 10),
            text("Daily update", width - 92, height - 18, 10),
            "</svg>",
        ]
    )
    return "\n".join(svg) + "\n"


def main() -> None:
    login = os.environ.get("PROFILE_LOGIN", "wangzhigang1999")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise ValueError("Invalid profile login")
    now = datetime.now(UTC)
    days, breakdown = fetch_activity(login, now)
    for name, mobile in [("github.svg", False), ("github-mobile.svg", True)]:
        path = Path("assets") / name
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(render(login, days, now, breakdown, mobile=mobile), encoding="utf-8")
        temporary.replace(path)


if __name__ == "__main__":
    main()
