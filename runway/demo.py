"""Write a realistic sample dataset so the tool can be tried in one command."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

CLIENTS = {
    "Acme Retail": (30, 2, 2400),
    "Nordlicht GmbH": (30, 12, 3100),
    "Pixel Studio": (14, 25, 900),
    "City Council": (30, 45, 5200),
    "Bright Dental": (15, 1, 650),
}


def write_demo(folder: Path, today: date, seed: int = 7) -> tuple[Path, Path]:
    rng = random.Random(seed)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for client, (terms, typical_delay, size) in CLIENTS.items():
        for k in range(8, 0, -1):
            issued = today - timedelta(days=k * 38 + rng.randint(-5, 5))
            due = issued + timedelta(days=terms)
            delay = max(-3, int(rng.gauss(typical_delay, 4 + typical_delay // 4)))
            amount = round(size * rng.uniform(0.7, 1.3), -1)
            paid = due + timedelta(days=delay)
            rows.append([client, f"{client[:3].upper()}-{9 - k:03d}", issued, due, amount,
                         paid if paid <= today else ""])
    rows.sort(key=lambda r: r[2])
    inv_path = folder / "invoices.csv"
    with inv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["client", "invoice", "issued", "due", "amount", "paid"])
        w.writerows(rows)

    exp_path = folder / "expenses.csv"
    month_start = today.replace(day=1)
    with exp_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["description", "amount", "date", "frequency"])
        w.writerows([
            ["Office rent", 1800, month_start, "monthly"],
            ["Salaries", 7200, month_start.replace(day=25), "monthly"],
            ["Software subscriptions", 340, month_start.replace(day=5), "monthly"],
            ["Insurance", 1200, today + timedelta(days=40), "quarterly"],
            ["VAT payment", 3900, today + timedelta(days=20), "quarterly"],
            ["Contractor", 450, today + timedelta(days=2), "weekly"],
            ["New laptop", 2100, today + timedelta(days=33), "once"],
        ])
    return inv_path, exp_path
