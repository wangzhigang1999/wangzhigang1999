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


LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
COLORS = ["#d9dfcf", "#bac9a9", "#8da780", "#5e7b59", "#344b38"]


def normalize(weeks: list[Week], today: date) -> list[Day]:
    """Require all 28 dates; a broken response must not silently replace history with zeros."""
    found: dict[date, Day] = {}
    for week in weeks:
        for item in week["contributionDays"]:
            day = date.fromisoformat(item["date"])
            count = item["contributionCount"]
            if type(count) is not int or count < 0:
                raise ValueError("Invalid contribution count")
            found[day] = Day(day, count, LEVELS.index(item["contributionLevel"]))
    expected = [today - timedelta(days=27 - i) for i in range(28)]
    if any(day not in found for day in expected):
        raise ValueError("Incomplete contribution calendar; keeping the existing card")
    return [found[day] for day in expected]


def fetch_days(login: str, now: datetime) -> list[Day]:
    """Use the repository-scoped Actions token; never read device credentials or notifications."""
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){contributionsCollection(from:$from,to:$to){
        contributionCalendar{weeks{contributionDays{date contributionCount contributionLevel}}}
      }}
    }"""
    start = datetime.combine(now.date() - timedelta(days=27), datetime.min.time(), UTC)
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
    return normalize(user["contributionsCollection"]["contributionCalendar"]["weeks"], now.date())


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


def render(login: str, days: list[Day], now: datetime) -> str:
    """One small card for desktop and mobile; retain the complete public calendar."""
    total, active, best = stats(days)
    title = f"{login}: {total} contributions, {active} active days in the last 28 days"
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="132" '
        'viewBox="0 0 640 132" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">Updated {now:%Y-%m-%d} UTC. Contributions are not commits. '
        "Best streak is limited to this 28-day window.</desc>",
        '<rect x=".5" y=".5" width="639" height="131" rx="12" fill="#fff" stroke="#dfe5df"/>',
        text("GitHub activity", 20, 25, 13, "#34473a", 600),
        text("Last 28 days", 529, 25),
        '<path d="M181 46v42 M357 46v42" stroke="#e8ece7"/>',
    ]
    for x, value, label in [
        (20, total, "contributions"),
        (203, active, "active days"),
        (379, best, "best streak · days"),
    ]:
        svg.append(text(str(value), x, 69, 30, "#365744", 600))
        svg.append(text(label, x, 88))
    for i, day in enumerate(days):
        x, y = 529 + (i % 7) * 13, 41 + (i // 7) * 13
        svg.append(
            f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" '
            f'fill="{COLORS[day.level]}"><title>{day.date}: '
            f"{day.count} contributions</title></rect>"
        )
    svg.extend(
        [
            text(f"{days[0].date:%m/%d} – {days[-1].date:%m/%d}", 20, 115, 10),
            text("Daily update", 529, 115, 10),
            "</svg>",
        ]
    )
    return "\n".join(svg) + "\n"


def main() -> None:
    login = os.environ.get("PROFILE_LOGIN", "wangzhigang1999")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise ValueError("Invalid profile login")
    now = datetime.now(UTC)
    days = fetch_days(login, now)
    for name, renderer in [("github.svg", render)]:
        path = Path("assets") / name
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(renderer(login, days, now), encoding="utf-8")
        temporary.replace(path)


if __name__ == "__main__":
    main()
