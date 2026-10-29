from datetime import date, timedelta

from runway.backtest import as_known_on, backtest
from runway.cli import main
from runway.demo import write_demo
from runway.loader import Invoice, load_invoices

TODAY = date(2026, 6, 1)


def test_no_future_knowledge_leaks():
    early = Invoice("A", "1", date(2026, 1, 1), date(2026, 1, 31), 100, date(2026, 3, 1))
    later = Invoice("A", "2", date(2026, 4, 1), date(2026, 5, 1), 100, date(2026, 5, 5))
    pairs = as_known_on([early, later], date(2026, 2, 1))
    assert len(pairs) == 1
    known, real = pairs[0]
    assert known.paid is None and real.paid == date(2026, 3, 1)


def test_too_little_history_gives_no_result():
    inv = [Invoice("A", str(k), TODAY - timedelta(days=90 + k), TODAY - timedelta(days=60 + k), 10,
                   TODAY - timedelta(days=50)) for k in range(4)]
    assert backtest(inv, TODAY) == []


def test_demo_data_is_roughly_calibrated(tmp_path):
    inv_path, _ = write_demo(tmp_path, TODAY)
    results = backtest(load_invoices(inv_path), TODAY)
    assert results and all(r.cases >= 5 for r in results)
    cases = sum(r.cases for r in results)
    assert sum(r.inside * r.cases for r in results) / cases > 0.6
    for r in results:
        assert abs(r.inside + r.below + r.above - 1) < 1e-9


def test_backtest_cli(capsys, tmp_path):
    inv_path, _ = write_demo(tmp_path, TODAY)
    assert main(["backtest", "--invoices", str(inv_path), "--today", "2026-06-01"]) == 0
    out = capsys.readouterr().out
    assert "Inside band" in out and "Verdict" in out
