"""Check the forecast against history: replay past dates and see where the money really landed."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .loader import Invoice
from .model import Settings, forecast

HORIZONS = (28, 56, 91)
MIN_PAID_HISTORY = 5


@dataclass
class HorizonResult:
    days: int
    cases: int
    inside: float
    below: float
    above: float
    mean_abs_error: float
    mean_open: float


def as_known_on(invoices: list[Invoice], cutoff: date) -> list[tuple[Invoice, Invoice]]:
    """(as known on `cutoff`, what really happened) pairs: later invoices unknown, later payments not yet made."""
    return [(replace(i, paid=None) if i.paid and i.paid > cutoff else i, i)
            for i in invoices if i.issued <= cutoff]


def backtest(invoices: list[Invoice], today: date, step: int = 14, runs: int = 500,
             seed: int = 1, horizons: tuple[int, ...] = HORIZONS) -> list[HorizonResult]:
    """Does the 10th-90th percentile band of collected cash contain what was really collected?"""
    paid_dates = sorted(i.paid for i in invoices if i.paid and i.paid <= today)
    if len(paid_dates) <= MIN_PAID_HISTORY:
        return []
    start = paid_dates[MIN_PAID_HISTORY]
    outcomes: dict[int, list[tuple[float, float, float, float, float]]] = {h: [] for h in horizons}
    cutoff = start
    while cutoff + timedelta(days=min(horizons)) <= today:
        pairs = as_known_on(invoices, cutoff)
        known = [k for k, _ in pairs]
        waiting = [(k, real) for k, real in pairs if k.paid is None]
        open_total = sum(k.amount for k, _ in waiting)
        if waiting and open_total > 0:
            fc = forecast(known, [], Settings(cash=0.0, today=cutoff, runs=runs, seed=seed))
            for h in horizons:
                end = cutoff + timedelta(days=h)
                if end > today:
                    continue
                actual = sum(k.amount for k, real in waiting if real.paid and real.paid <= end)
                outcomes[h].append((actual, fc.low[h - 1], fc.mid[h - 1], fc.high[h - 1], open_total))
        cutoff += timedelta(days=step)
    results = []
    for h, rows in outcomes.items():
        if not rows:
            continue
        n = len(rows)
        results.append(HorizonResult(
            h, n,
            sum(lo <= a <= hi for a, lo, _, hi, _ in rows) / n,
            sum(a < lo for a, lo, _, _, _ in rows) / n,
            sum(a > hi for a, _, _, hi, _ in rows) / n,
            sum(abs(a - mid) for a, _, mid, _, _ in rows) / n,
            sum(o for *_, o in rows) / n))
    return results
