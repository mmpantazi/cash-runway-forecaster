"""Learn each client's payment delay and simulate the cash balance."""
from __future__ import annotations

import bisect
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import accumulate

from .loader import Expense, Invoice, occurrences

HORIZON_DAYS = 91
DECAY = 0.85
SHRINK = 3
PRIOR_DELAYS = [-2, 0, 3, 7, 14, 21, 30]
TAIL_MEAN_DAYS = 14


@dataclass
class Settings:
    cash: float
    today: date
    buffer: float = 0.0
    runs: int = 2000
    seed: int = 1
    bad_debt: float = 0.02


@dataclass
class ClientProfile:
    name: str
    delays: list[tuple[int, float]]  # (days after due date, recency weight), newest first
    open_amount: float = 0.0

    @property
    def n(self) -> int:
        return len(self.delays)

    def values(self) -> list[int]:
        return [d for d, _ in self.delays]

    def median(self) -> float | None:
        return statistics.median(self.values()) if self.delays else None

    def p80(self) -> float | None:
        v = sorted(self.values())
        return v[min(len(v) - 1, int(0.8 * len(v)))] if v else None

    def late_share(self, grace: int = 7) -> float | None:
        return sum(d > grace for d in self.values()) / self.n if self.n else None

    def trend(self) -> float | None:
        """Mean of the latest 3 delays minus the mean of all earlier ones."""
        v = self.values()
        if len(v) < 5:
            return None
        return statistics.mean(v[:3]) - statistics.mean(v[3:])


def is_open(inv: Invoice, today: date) -> bool:
    return inv.paid is None or inv.paid > today


def learn_profiles(invoices: list[Invoice], today: date) -> dict[str, ClientProfile]:
    by_client: dict[str, list[Invoice]] = {}
    for inv in invoices:
        by_client.setdefault(inv.client, []).append(inv)
    profiles = {}
    for name, items in by_client.items():
        paid = sorted((i for i in items if not is_open(i, today)), key=lambda i: i.paid, reverse=True)
        delays = [((i.paid - i.due).days, DECAY ** rank) for rank, i in enumerate(paid)]
        open_amount = sum(i.amount for i in items if is_open(i, today))
        profiles[name] = ClientProfile(name, delays, open_amount)
    return profiles


class _Pool:
    """Weighted empirical sample, conditioned on delay >= floor."""

    def __init__(self, delays: list[tuple[int, float]], floor: int):
        kept = [(d, w) for d, w in delays if d >= floor]
        self.values = [d for d, _ in kept]
        self.cum = list(accumulate(w for _, w in kept))

    def __bool__(self) -> bool:
        return bool(self.values)

    def draw(self, rng: random.Random) -> int:
        return self.values[bisect.bisect(self.cum, rng.random() * self.cum[-1])]


@dataclass
class _OpenInvoice:
    invoice: Invoice
    overdue: int
    own: _Pool
    pooled: _Pool
    p_own: float
    p_bad: float


def non_payment_probability(overdue: int, base: float) -> float:
    if overdue > 180:
        return max(base, 0.9)
    if overdue > 90:
        return max(base, 0.5)
    return base


def prepare_open(invoices, profiles, settings) -> list[_OpenInvoice]:
    pooled_all = [x for p in profiles.values() for x in p.delays] or [(d, 1.0) for d in PRIOR_DELAYS]
    prepared = []
    for inv in invoices:
        if not is_open(inv, settings.today):
            continue
        overdue = max(0, (settings.today - inv.due).days)
        prof = profiles[inv.client]
        prepared.append(_OpenInvoice(
            inv, overdue, _Pool(prof.delays, overdue), _Pool(pooled_all, overdue),
            prof.n / (prof.n + SHRINK), non_payment_probability(overdue, settings.bad_debt)))
    return prepared


def draw_delay(item: _OpenInvoice, rng: random.Random) -> int:
    if item.own and rng.random() < item.p_own:
        return item.own.draw(rng)
    if item.pooled:
        return item.pooled.draw(rng)
    return item.overdue + int(rng.expovariate(1 / TAIL_MEAN_DAYS))


@dataclass
class Forecast:
    days: list[date]
    low: list[float]
    mid: list[float]
    high: list[float]
    weekly_in: list[float]
    weekly_out: list[float]
    breach_probability: float
    danger_likely: date | None
    danger_possible: date | None
    opening: float
    buffer: float
    profiles: dict[str, ClientProfile] = field(default_factory=dict)
    scheduled_out: list[tuple[date, str, float]] = field(default_factory=list)


def percentile(sorted_values: list[float], q: float) -> float:
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def first_below(days, series, limit) -> date | None:
    return next((d for d, v in zip(days, series) if v < limit), None)


def forecast(invoices: list[Invoice], expenses: list[Expense], settings: Settings,
             on_time: str | None = None) -> Forecast:
    """Monte Carlo forecast. `on_time` names a client assumed to pay exactly on the due date."""
    today = settings.today
    profiles = learn_profiles(invoices, today)
    open_items = prepare_open(invoices, profiles, settings)
    if on_time:
        for item in open_items:
            if item.invoice.client == on_time:
                item.p_bad = 0.0
                item.own = item.pooled = _Pool([(item.overdue, 1.0)], item.overdue)
                item.p_own = 1.0

    last_day = today + timedelta(days=HORIZON_DAYS - 1)
    out_by_day = [0.0] * HORIZON_DAYS
    scheduled = []
    for exp in expenses:
        for d in occurrences(exp, today, last_day):
            out_by_day[(d - today).days] += exp.amount
            scheduled.append((d, exp.name, exp.amount))
    scheduled.sort()

    rng = random.Random(settings.seed)
    paths = []
    inflow_by_week = [0.0] * (HORIZON_DAYS // 7)
    for _ in range(settings.runs):
        incoming = [0.0] * HORIZON_DAYS
        for item in open_items:
            if rng.random() < item.p_bad:
                continue
            idx = max(0, (item.invoice.due - today).days + draw_delay(item, rng))
            if idx < HORIZON_DAYS:
                incoming[idx] += item.invoice.amount
        balance = settings.cash
        path = []
        for i in range(HORIZON_DAYS):
            balance += incoming[i] - out_by_day[i]
            path.append(balance)
            inflow_by_week[i // 7] += incoming[i]
        paths.append(path)

    low, mid, high = [], [], []
    for i in range(HORIZON_DAYS):
        col = sorted(p[i] for p in paths)
        low.append(percentile(col, 0.10))
        mid.append(percentile(col, 0.50))
        high.append(percentile(col, 0.90))
    days = [today + timedelta(days=i) for i in range(HORIZON_DAYS)]
    weekly_out = [sum(out_by_day[w * 7:(w + 1) * 7]) for w in range(HORIZON_DAYS // 7)]
    breaches = sum(min(p) < settings.buffer for p in paths)
    return Forecast(
        days, low, mid, high,
        [x / settings.runs for x in inflow_by_week], weekly_out,
        breaches / settings.runs,
        first_below(days, mid, settings.buffer), first_below(days, low, settings.buffer),
        settings.cash, settings.buffer, profiles, scheduled)
