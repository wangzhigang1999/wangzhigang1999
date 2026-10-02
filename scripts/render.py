"""Render a dependency-free, board-inspired SVG using the public profile calendar."""

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
# Pixel numerals are paths, so the SVG never depends on fonts, scripts, or remote assets.
DIGITS = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}


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


def numeral(value: int, x: int, y: int, size: int) -> str:
    commands: list[str] = []
    for i, char in enumerate(str(value)):
        for row, cells in enumerate(DIGITS[char]):
            for col, cell in enumerate(cells):
                if cell == "1":
                    commands.append(
                        f"M{x + (i * 4 + col) * size} {y + row * size}h{size}v{size}h-{size}z"
                    )
    return f'<path d="{"".join(commands)}" fill="#344b38"/>'


def text(value: str, x: int, y: int, size: int = 14, color: str = "#65745d") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'font-family="monospace">{escape(value)}</text>'
    )


def render(login: str, days: list[Day], now: datetime) -> str:
    total, active, best = stats(days)
    title = f"{login}: {total} contributions, {active} active days in the last 28 days"
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 408" '
        f'role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title>',
        '<desc id="desc">GitHub profile activity, updated daily. '
        "Contributions are not commits. Streak is limited to this 28-day window.</desc>",
        '<rect x="1" y="1" width="858" height="406" rx="24" fill="#f0f2e9" stroke="#cbd3c1"/>',
        '<rect x="20" y="20" width="820" height="368" rx="9" fill="#e7ebdc" stroke="#72816a"/>',
        text(f"@{login}", 46, 65, 24, "#344b38"),
        text("GLANCE / GITHUB", 666, 63, 14),
        '<path d="M46 89H814 M324 115V302 M46 327H814" stroke="#a8b49d" fill="none"/>',
        text("LAST 28 DAYS", 364, 129, 14),
    ]
    start = days[0].date
    for col in range(7):
        label = (start + timedelta(days=col)).strftime("%a")[0]
        svg.append(text(label, 67 + col * 31, 128, 12))
    for i, day in enumerate(days):
        x, y = 62 + (i % 7) * 31, 143 + (i // 7) * 31
        svg.append(
            f'<rect x="{x}" y="{y}" width="23" height="23" rx="2" '
            f'fill="{COLORS[day.level]}" stroke="#a8b49d" stroke-width="0.6">'
            f"<title>{day.date}: {day.count} contributions</title></rect>"
        )
    svg.extend(
        [
            text(f"{start:%b %d} - {days[-1].date:%b %d}", 62, 297, 13),
            numeral(total, 364, 153, 9),
            text("CONTRIBUTIONS", 364, 223, 14),
            numeral(active, 364, 250, 6),
            text("ACTIVE DAYS", 364, 304, 12),
            numeral(best, 593, 250, 6),
            text("BEST STREAK / DAYS", 593, 304, 12),
            text("FROM MY DESK TO MY PROFILE", 46, 360, 12),
            text(f"UPDATED {now:%Y-%m-%d} UTC", 593, 360, 12),
            "</svg>",
        ]
    )
    return "\n".join(svg) + "\n"


def main() -> None:
    login = os.environ.get("PROFILE_LOGIN", "wangzhigang1999")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise ValueError("Invalid profile login")
    now = datetime.now(UTC)
    card = render(login, fetch_days(login, now), now)
    path = Path("assets/github.svg")
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(card, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    main()
