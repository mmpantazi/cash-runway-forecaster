"""Command line entry point: `python -m runway`."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .demo import write_demo
from .i18n import STRINGS
from .loader import DataError, load_expenses, load_invoices, parse_amount, parse_date
from .model import Settings, forecast, is_open, learn_profiles, project_billing
from .report import LEVER_CLIENTS, Lever, money, notes, render_html, render_text, stale_notes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runway", description="13-week cash forecast from each client's real payment habits.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("forecast", help="forecast cash from invoice and expense CSVs")
    f.add_argument("--invoices", required=True, type=Path, help="CSV: client, amount, due/issued, paid")
    f.add_argument("--expenses", type=Path, help="CSV: description, amount, date, frequency")
    f.add_argument("--cash", required=True, help="cash in the bank today")
    f.add_argument("--buffer", default="0", help="minimum balance you want to keep (default 0)")
    f.add_argument("--today", help="forecast start date, YYYY-MM-DD (default: today)")
    f.add_argument("--terms", type=int, default=30, help="payment terms in days when a due date is missing")
    f.add_argument("--bad-debt", type=float, default=0.02, help="chance an open invoice is never paid")
    f.add_argument("--no-projection", action="store_true",
                   help="do not assume regular clients keep sending invoices at their usual rhythm")
    f.add_argument("--runs", type=int, default=2000, help="simulated futures (default 2000)")
    f.add_argument("--seed", type=int, default=1)
    f.add_argument("--lang", choices=sorted(STRINGS), default="en")
    f.add_argument("--html", type=Path, help="also write a self-contained HTML report here")

    d = sub.add_parser("demo", help="write sample CSVs and show their forecast")
    d.add_argument("folder", type=Path, nargs="?", default=Path("runway-demo"))
    d.add_argument("--lang", choices=sorted(STRINGS), default="en")
    return p


def stale_counts(invoices, today) -> dict[str, int]:
    counts: dict[str, int] = {}
    for inv in invoices:
        if is_open(inv, today) and (today - inv.due).days > 90:
            counts[inv.client] = counts.get(inv.client, 0) + 1
    return counts


def run_forecast(args) -> int:
    today = parse_date(args.today) if args.today else date.today()
    warnings: list[str] = []
    invoices = load_invoices(args.invoices, args.terms, warnings)
    expenses = load_expenses(args.expenses, warnings) if args.expenses else []
    if not args.no_projection:
        projected = project_billing(invoices, today)
        invoices = invoices + projected
        if projected:
            warnings.append(STRINGS[args.lang]["projected"].format(
                n=len(projected), total=money(sum(i.amount for i in projected))))
    settings = Settings(cash=parse_amount(args.cash), today=today, buffer=parse_amount(args.buffer),
                        runs=args.runs, seed=args.seed, bad_debt=args.bad_debt)
    fc = forecast(invoices, expenses, settings)

    levers = []
    profiles = learn_profiles(invoices, today)
    ranked = sorted(profiles.values(), key=lambda p: -(p.open_amount + p.projected_amount))
    for prof in ranked[:LEVER_CLIENTS]:
        if prof.open_amount + prof.projected_amount <= 0:
            continue
        alt = forecast(invoices, expenses, settings, on_time=prof.name)
        if alt.breach_probability != fc.breach_probability or alt.danger_possible != fc.danger_possible:
            levers.append(Lever(prof.name, fc.breach_probability, alt.breach_probability,
                                fc.danger_possible, alt.danger_possible))
    levers.sort(key=lambda l: l.breach_after - l.breach_before)

    all_notes = warnings + notes(fc, args.lang) + stale_notes(stale_counts(invoices, today), args.lang)
    print(render_text(fc, levers, all_notes, args.lang, today, args.runs))
    if args.html:
        args.html.write_text(render_html(fc, levers, all_notes, args.lang, today, args.runs), encoding="utf-8")
        print(f"\nHTML report: {args.html}")
    return 0


def run_demo(args) -> int:
    today = date.today()
    inv, exp = write_demo(args.folder, today)
    print(f"Sample files written to {args.folder}/ ({inv.name}, {exp.name})\n")
    ns = argparse.Namespace(invoices=inv, expenses=exp, cash="14000", buffer="2000", today=None, terms=30,
                            bad_debt=0.02, no_projection=False, runs=2000, seed=1, lang=args.lang, html=args.folder / "report.html")
    return run_forecast(ns)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_demo(args) if args.command == "demo" else run_forecast(args)
    except (DataError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
