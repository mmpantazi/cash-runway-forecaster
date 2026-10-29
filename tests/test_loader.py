from datetime import date

import pytest

from runway.loader import DataError, Expense, load_expenses, load_invoices, occurrences, parse_amount, parse_date


@pytest.mark.parametrize("text,value", [
    ("1234.56", 1234.56), ("1,234.56", 1234.56), ("1.234,56", 1234.56), ("1 234,56", 1234.56),
    ("€1.234", 1234.0), ("1,5", 1.5), ("(200.00)", -200.0), ("1.234.567", 1234567.0), ("12 500 RON", 12500.0),
])
def test_parse_amount(text, value):
    assert parse_amount(text) == value


def test_parse_date_formats():
    assert parse_date("2026-03-04") == parse_date("04.03.2026") == parse_date("04/03/2026") == date(2026, 3, 4)
    with pytest.raises(ValueError):
        parse_date("March 4")


def test_semicolon_romanian_headers_and_bom(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("﻿Client;Factura;Data emitere;Scadenta;Valoare;Data plata\n"
                 "Alfa SRL;A1;01.02.2026;03.03.2026;1.200,50;10.03.2026\n"
                 "Beta SRL;B1;01.02.2026;;300;\n", encoding="utf-8")
    inv = load_invoices(f, default_terms=15)
    assert inv[0].amount == 1200.5 and inv[0].paid == date(2026, 3, 10)
    assert inv[1].due == date(2026, 2, 16) and inv[1].paid is None


def test_bad_rows_are_skipped_with_warning(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("client,amount,due\nA,100,2026-01-01\nB,abc,2026-01-01\n,5,2026-01-01\nC,7,nope\n")
    warnings = []
    inv = load_invoices(f, warnings=warnings)
    assert [i.client for i in inv] == ["A"]
    assert len(warnings) == 3 and "line 3" in warnings[0]


def test_missing_columns_and_files(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("who,what\nA,1\n")
    with pytest.raises(DataError, match="missing column"):
        load_invoices(f)
    with pytest.raises(DataError, match="not found"):
        load_invoices(tmp_path / "nope.csv")
    empty = tmp_path / "e.csv"
    empty.write_text("")
    with pytest.raises(DataError, match="empty"):
        load_expenses(empty)


def test_latin1_file(tmp_path):
    f = tmp_path / "f.csv"
    f.write_bytes("client,amount,due\nȘtefan SRL,10,2026-01-01\n".encode("utf-8").replace(b"\xc8\x98", b"\xd0"))
    assert load_invoices(f)[0].amount == 10


def test_monthly_occurrence_clamps_to_month_end():
    e = Expense("rent", 1, date(2026, 1, 31), "monthly")
    days = occurrences(e, date(2026, 1, 1), date(2026, 4, 30))
    assert days == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_recurring_from_the_past_and_end_date():
    e = Expense("x", 1, date(2025, 1, 6), "weekly", end=date(2026, 1, 20))
    days = occurrences(e, date(2026, 1, 1), date(2026, 6, 1))
    assert days[0] == date(2026, 1, 5) and days[-1] == date(2026, 1, 19)


def test_once_outside_window_ignored():
    e = Expense("x", 1, date(2026, 1, 1), "once")
    assert occurrences(e, date(2026, 2, 1), date(2026, 5, 1)) == []


def test_expense_frequency_aliases(tmp_path):
    f = tmp_path / "e.csv"
    f.write_text("descriere,suma,data,frecventa\nChirie,1000,2026-01-01,lunar\nX,5,2026-01-01,sometimes\n")
    w = []
    exp = load_expenses(f, w)
    assert len(exp) == 1 and exp[0].frequency == "monthly" and len(w) == 1
