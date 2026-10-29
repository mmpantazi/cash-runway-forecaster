from datetime import date, timedelta

from runway.loader import Expense, Invoice
from runway.model import HORIZON_DAYS, Settings, forecast, learn_profiles, project_billing

TODAY = date(2026, 6, 1)


def paid(client, due, delay, amount=100):
    return Invoice(client, "x", due - timedelta(days=30), due, amount, due + timedelta(days=delay))


def history(client, delays, amount=100):
    return [paid(client, TODAY - timedelta(days=60 + 30 * k), d, amount) for k, d in enumerate(delays)]


def open_inv(client, due_in, amount=1000):
    due = TODAY + timedelta(days=due_in)
    return Invoice(client, "open", due - timedelta(days=30), due, amount)


def settings(**kw):
    return Settings(cash=kw.pop("cash", 0.0), today=TODAY, runs=kw.pop("runs", 300), **kw)


def test_consistent_payer_arrives_on_predicted_day():
    inv = history("A", [10] * 6) + [open_inv("A", 5)]
    fc = forecast(inv, [], settings(bad_debt=0))
    day = (TODAY + timedelta(days=15) - TODAY).days
    assert fc.low[day - 1] == 0 and fc.low[day] == 1000
    assert fc.high[day - 1] == 0


def test_slow_client_is_later_than_fast_client():
    fast = forecast(history("F", [0] * 6) + [open_inv("F", 10)], [], settings(bad_debt=0))
    slow = forecast(history("S", [40] * 6) + [open_inv("S", 10)], [], settings(bad_debt=0))
    assert fast.mid[12] == 1000 and slow.mid[12] == 0 and slow.mid[50] == 1000


def test_overdue_invoice_cannot_be_paid_in_the_past():
    inv = history("A", [0, 5, 10, 30, 30, 30]) + [open_inv("A", -12)]
    fc = forecast(inv, [], settings(bad_debt=0))
    assert fc.low[0] == 0  # a 12-day-overdue invoice never lands "yesterday"
    assert fc.mid[-1] == 1000


def test_overdue_beyond_history_uses_tail_not_instant_payment():
    inv = history("A", [0, 1, 2]) + [open_inv("A", -40)]
    fc = forecast(inv, [], settings(bad_debt=0))
    assert fc.low[0] == 0 and fc.mid[-1] == 1000


def test_very_old_invoice_is_probably_never_paid():
    inv = history("A", [0] * 4) + [open_inv("A", -200)]
    fc = forecast(inv, [], settings())
    assert fc.mid[-1] == 0


def test_expenses_and_danger_date():
    exp = [Expense("rent", 400, TODAY + timedelta(days=3), "monthly")]
    fc = forecast(history("A", [0] * 3), exp, settings(cash=1000, buffer=0))
    assert fc.mid[2] == 1000 and fc.mid[3] == 600
    assert fc.danger_likely == date(2026, 8, 4)  # third rent payment: 1000 - 3 * 400
    assert fc.breach_probability == 1.0
    assert sum(fc.weekly_out) == 400 * len(fc.scheduled_out)


def test_no_danger_when_cash_is_ample():
    fc = forecast(history("A", [0] * 3), [Expense("r", 10, TODAY, "weekly")], settings(cash=10_000))
    assert fc.danger_likely is None and fc.danger_possible is None and fc.breach_probability == 0


def test_already_below_buffer_flags_today():
    fc = forecast(history("A", [0] * 3), [], settings(cash=-5))
    assert fc.danger_likely == TODAY


def test_new_client_borrows_from_pool():
    inv = history("Old", [20] * 8) + [open_inv("New", 0)]
    fc = forecast(inv, [], settings(bad_debt=0))
    assert fc.mid[10] == 0 and fc.mid[25] == 1000


def test_recent_behaviour_counts_more():
    p = learn_profiles(history("A", [0, 0, 0, 20, 20, 20, 20, 20]), TODAY)["A"]
    assert p.delays[0][1] > p.delays[-1][1]
    assert p.trend() == -20


def test_on_time_lever_moves_the_cash_earlier():
    inv = history("S", [40] * 6) + [open_inv("S", 5)]
    base = forecast(inv, [], settings(bad_debt=0))
    lever = forecast(inv, [], settings(bad_debt=0), on_time="S")
    assert base.mid[10] == 0 and lever.mid[10] == 1000


def test_same_seed_is_reproducible():
    inv = history("A", [0, 10, 25, 5]) + [open_inv("A", 3)]
    assert forecast(inv, [], settings()).low == forecast(inv, [], settings()).low


def test_no_history_at_all_still_works():
    fc = forecast([open_inv("N", 5)], [], settings(bad_debt=0))
    assert len(fc.mid) == HORIZON_DAYS and fc.mid[-1] == 1000


def test_projection_follows_rhythm():
    inv = [Invoice("A", str(k), TODAY - timedelta(days=30 * (6 - k)), TODAY - timedelta(days=30 * (6 - k)) + timedelta(days=14),
                   500, None) for k in range(1, 6)]
    proj = project_billing(inv, TODAY)
    assert proj and all(p.amount == 500 and (p.due - p.issued).days == 14 for p in proj)
    assert len({p.issued for p in proj}) == len(proj)


def test_projection_skips_irregular_or_inactive_clients():
    one_off = history("A", [0, 0])
    assert project_billing(one_off, TODAY) == []
    stale = [Invoice("B", "x", TODAY - timedelta(days=400 + 30 * k), TODAY - timedelta(days=370 + 30 * k), 5) for k in range(4)]
    assert project_billing(stale, TODAY) == []
