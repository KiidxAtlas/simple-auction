"""Numbers for the Output page, worked out from the completion history and the
current catalogue. Pure functions: nothing here reads or writes files."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from statistics import median

from simple_auction.models import Lot
from simple_auction.services import dossier
from simple_auction.services.output import Completion

TREND_DAYS = 30
RECENT_LIMIT = 15
# Gaps longer than this between two lots on the same day are breaks, not pace.
PACE_BREAK = timedelta(hours=2)


@dataclass(frozen=True)
class Day:
    day: date
    count: int
    first: datetime
    last: datetime
    auctions: tuple[int, ...]


@dataclass(frozen=True)
class Report:
    total: int
    today: int
    yesterday: int
    week: int  # since Monday
    month: int  # since the 1st
    last_7: int
    last_30: int
    active_days: int
    first_day: date | None
    average_per_active_day: float
    average_last_30: float  # per calendar day, idle days included
    best: Day | None
    streak: int  # consecutive days with output, still running today or yesterday
    longest_streak: int
    median_minutes_between: float | None
    days: list[Day]  # newest first
    trend: list[tuple[date, int]]  # the last TREND_DAYS days, oldest first
    by_weekday: list[int]  # Monday..Sunday
    by_hour: list[int]  # 0..23
    by_auction: list[tuple[int, int]]  # (auction, completions), most first
    by_type: list[tuple[str, int]]  # (gun type, completions), most first
    recent: list[Completion]  # newest first


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days with output."""
    longest = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    # Not having finished anything yet today does not break yesterday's streak.
    end = today if today in days else today - timedelta(days=1)
    current = 0
    while end - timedelta(days=current) in days:
        current += 1
    return current, longest


def _median_gap(completions: list[Completion]) -> float | None:
    gaps = []
    by_day: dict[date, list[datetime]] = {}
    for c in completions:
        by_day.setdefault(c.day, []).append(c.at)
    for times in by_day.values():
        times.sort()
        gaps += [b - a for a, b in pairwise(times) if b - a <= PACE_BREAK]
    if not gaps:
        return None
    return median(g.total_seconds() for g in gaps) / 60


def report(completions: list[Completion], today: date) -> Report:
    grouped: dict[date, list[Completion]] = {}
    for c in sorted(completions, key=lambda c: c.at):
        grouped.setdefault(c.day, []).append(c)
    days = [
        Day(
            day,
            len(items),
            items[0].at,
            items[-1].at,
            tuple(sorted({c.auction for c in items})),
        )
        for day, items in grouped.items()
    ]
    counts = {d.day: d.count for d in days}

    def since(start: date) -> int:
        return sum(n for day, n in counts.items() if start <= day <= today)

    trend_start = today - timedelta(days=TREND_DAYS - 1)
    trend = [
        (
            trend_start + timedelta(days=i),
            counts.get(trend_start + timedelta(days=i), 0),
        )
        for i in range(TREND_DAYS)
    ]
    streak, longest = _streaks(set(counts), today)
    by_weekday, by_hour = [0] * 7, [0] * 24
    for c in completions:
        by_weekday[c.day.weekday()] += 1
        by_hour[c.at.hour] += 1
    return Report(
        total=len(completions),
        today=counts.get(today, 0),
        yesterday=counts.get(today - timedelta(days=1), 0),
        week=since(today - timedelta(days=today.weekday())),
        month=since(today.replace(day=1)),
        last_7=since(today - timedelta(days=6)),
        last_30=since(trend_start),
        active_days=len(days),
        first_day=min(counts, default=None),
        average_per_active_day=len(completions) / len(days) if days else 0.0,
        average_last_30=since(trend_start) / TREND_DAYS,
        best=max(days, key=lambda d: (d.count, d.day), default=None),
        streak=streak,
        longest_streak=longest,
        median_minutes_between=_median_gap(completions),
        days=sorted(days, key=lambda d: d.day, reverse=True),
        trend=trend,
        by_weekday=by_weekday,
        by_hour=by_hour,
        by_auction=sorted(
            Counter(c.auction for c in completions).items(),
            key=lambda item: (-item[1], item[0]),
        ),
        by_type=sorted(
            Counter(c.gun_type or "Unspecified" for c in completions).items(),
            key=lambda item: (-item[1], item[0]),
        ),
        recent=sorted(completions, key=lambda c: c.at, reverse=True)[:RECENT_LIMIT],
    )


@dataclass(frozen=True)
class AuctionProgress:
    auction: int
    total: int
    ready: int


@dataclass(frozen=True)
class Pipeline:
    """Where the catalogue stands right now."""

    total: int
    ready: int
    auctions: list[AuctionProgress]
    blockers: list[tuple[str, int]]  # (what is missing, lots affected), most first


def pipeline(auctions: dict[int, list[Lot]]) -> Pipeline:
    progress, blockers = [], Counter()
    for number, lots in sorted(auctions.items()):
        ready = 0
        for lot in lots:
            duplicate = bool(dossier.duplicates(lot, number, auctions))
            try:
                found = {label for label, _target in dossier.issues(lot, duplicate)}
            except ValueError, TypeError:
                found = {"Damaged research packet"}
            if found:
                blockers.update(found)
            else:
                ready += 1
        progress.append(AuctionProgress(number, len(lots), ready))
    return Pipeline(
        total=sum(p.total for p in progress),
        ready=sum(p.ready for p in progress),
        auctions=progress,
        blockers=sorted(blockers.items(), key=lambda item: (-item[1], item[0])),
    )


@dataclass(frozen=True)
class Funnel:
    """Lots started against lots with their information filled in."""

    started_total: int
    started_today: int
    filled_total: int
    filled_today: int
    in_progress_total: int  # started but not yet information filled


def funnel(filled: Report, started: Report) -> Funnel:
    """`started` covers every lot begun, so it includes the information-filled
    ones. Anything not yet filled is still in progress."""
    return Funnel(
        started_total=started.total,
        started_today=started.today,
        filled_total=filled.total,
        filled_today=filled.today,
        in_progress_total=max(0, started.total - filled.total),
    )
