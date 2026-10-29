import re
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from runway.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def files(tmp_path):
    inv = tmp_path / "inv.csv"
    inv.write_text("client,invoice,issued,due,amount,paid\n"
                   "Slow Co,1,2026-01-01,2026-01-31,1000,2026-03-15\n"
                   "Slow Co,2,2026-02-01,2026-03-03,1000,2026-04-20\n"
                   "Slow Co,3,2026-03-01,2026-03-31,1000,2026-05-20\n"
                   "Slow Co,4,2026-05-01,2026-05-31,1000,\n"
                   "Fast Co,1,2026-05-10,2026-05-24,500,2026-05-24\n")
    exp = tmp_path / "exp.csv"
    exp.write_text("description,amount,date,frequency\nRent,900,2026-06-05,monthly\n")
    return inv, exp, tmp_path


def test_forecast_text_and_html(capsys, files):
    inv, exp, tmp = files
    html_path = tmp / "r.html"
    code, out, err = run(capsys, "forecast", "--invoices", str(inv), "--expenses", str(exp), "--cash", "1500",
                         "--today", "2026-06-01", "--html", str(html_path), "--no-projection")
    assert code == 0, err
    assert "Danger date" in out and "Slow Co" in out and "Week ending" in out
    page = html_path.read_text(encoding="utf-8")
    svg = re.search(r"<svg.*?</svg>", page, re.S).group(0)
    ET.fromstring(svg)
    assert "Danger date" in page and "<script>" in page


def test_romanian_output(capsys, files):
    inv, exp, _ = files
    code, out, _ = run(capsys, "forecast", "--invoices", str(inv), "--expenses", str(exp), "--cash", "1.500,00",
                       "--today", "2026-06-01", "--lang", "ro")
    assert code == 0 and "Data de pericol" in out and "Săptămâna până la" in out


def test_errors_exit_2_without_traceback(capsys, tmp_path):
    code, out, err = run(capsys, "forecast", "--invoices", str(tmp_path / "missing.csv"), "--cash", "10")
    assert code == 2 and "error: file not found" in err
    code, _, err = run(capsys, "forecast", "--invoices", str(tmp_path), "--cash", "10")
    assert code == 2 and "cannot read" in err
    good = tmp_path / "i.csv"
    good.write_text("client,amount,due\nA,5,2026-01-01\n")
    code, _, err = run(capsys, "forecast", "--invoices", str(good), "--cash", "abc")
    assert code == 2 and "amount" in err


def test_demo_writes_files_and_report(capsys, tmp_path):
    code, out, _ = run(capsys, "demo", str(tmp_path / "d"))
    assert code == 0
    assert (tmp_path / "d" / "invoices.csv").exists() and (tmp_path / "d" / "report.html").exists()
    assert "What each client really does" in out


def test_projection_note_and_toggle(capsys, tmp_path):
    from runway.demo import write_demo
    inv, exp = write_demo(tmp_path, date(2026, 6, 1))
    base = ["forecast", "--invoices", str(inv), "--expenses", str(exp), "--cash", "5000", "--today", "2026-06-01"]
    _, with_p, _ = run(capsys, *base)
    _, without, _ = run(capsys, *base, "--no-projection")
    assert "projected from each regular client" in with_p
    assert "projected from each regular client" not in without


def test_nice_ticks_are_round():
    from runway.report import nice_ticks
    assert nice_ticks(-6705, 14000) == [-5000, 0, 5000, 10000]
    assert all(t % 100 == 0 for t in nice_ticks(0, 900))
