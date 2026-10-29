"""Read invoice and expense CSV exports into plain dataclasses."""
from __future__ import annotations

import calendar
import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

FREQUENCIES = {
    "once": 0, "weekly": 7, "biweekly": 14, "monthly": "m", "quarterly": "q", "yearly": "y",
    "unic": 0, "saptamanal": 7, "lunar": "m", "trimestrial": "q", "anual": "y",
}

INVOICE_COLUMNS = {
    "client": ("client", "customer", "name", "clientul", "partener", "nume_client", "denumire"),
    "number": ("invoice", "invoice_id", "number", "id", "nr", "nr_factura", "factura", "numar"),
    "issued": ("issued", "issue_date", "invoice_date", "date", "data", "data_emitere", "data_emiterii", "data_factura"),
    "due": ("due", "due_date", "scadenta", "data_scadenta"),
    "amount": ("amount", "total", "value", "suma", "valoare", "total_cu_tva", "total_factura"),
    "paid": ("paid", "paid_date", "payment_date", "date_paid", "data_plata", "data_incasare", "data_incasarii", "incasat"),
}
EXPENSE_COLUMNS = {
    "name": ("description", "name", "expense", "category", "descriere", "denumire"),
    "amount": ("amount", "total", "value", "suma", "valoare", "total_cu_tva", "total_factura"),
    "date": ("date", "start", "next_date", "due_date", "data"),
    "frequency": ("frequency", "repeat", "recurrence", "frecventa"),
    "end": ("end", "end_date", "until", "pana_la"),
    "type": ("type", "direction", "kind", "tip"),
}
INCOME_WORDS = {"in", "income", "inflow", "incasare", "venit", "intrare"}


class DataError(ValueError):
    """Raised when a file cannot be used at all."""


@dataclass
class Invoice:
    client: str
    number: str
    issued: date
    due: date
    amount: float
    paid: date | None = None


@dataclass
class Expense:
    """A scheduled payment. Positive amount = money out, negative = money in (retainer, grant...)."""
    name: str
    amount: float
    start: date
    frequency: str = "once"
    end: date | None = None


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def parse_amount(text: str) -> float:
    """Accept 1234.56, 1,234.56, 1.234,56, 1 234,56 and currency symbols."""
    s = re.sub(r"[^\d,.\-()]", "", text.strip())
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()")
    if not s:
        raise ValueError(f"unrecognised amount {text!r}")
    decimal = None
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
    else:
        for sep in ",.":
            if s.count(sep) == 1 and len(s.rpartition(sep)[2]) != 3:
                decimal = sep
    if decimal:
        whole, _, frac = s.rpartition(decimal)
        s = re.sub(r"[.,]", "", whole) + "." + frac
    else:
        s = re.sub(r"[.,]", "", s)
    value = float(s)
    return -value if negative else value


def _plain(name: str) -> str:
    """Lower-case, accent-free, underscore-separated header: 'Dată încasare' -> 'data_incasare'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[\s.\-]+", "_", ascii_name.strip().lower()).strip("_")


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DataError(f"file not found: {path}") from None
    except OSError as exc:
        raise DataError(f"cannot read {path}: {exc.strerror}") from None
    except UnicodeDecodeError:
        text = Path(path).read_text(encoding="latin-1")
    if not text.strip():
        raise DataError(f"{path} is empty")
    first = text.splitlines()[0]
    delimiter = max(",;\t", key=first.count)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    header = [_plain(h) for h in (reader.fieldnames or [])]
    reader.fieldnames = header
    rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]
    return header, rows


def _map_columns(header: list[str], spec: dict[str, tuple[str, ...]], path, required) -> dict[str, str]:
    mapping = {}
    for field, aliases in spec.items():
        for alias in aliases:
            if alias in header:
                mapping[field] = alias
                break
    missing = [f for f in required if f not in mapping]
    if missing:
        raise DataError(f"{path}: missing column(s) {', '.join(missing)}; found {', '.join(header)}")
    return mapping


def load_invoices(path, default_terms: int = 30, warnings: list[str] | None = None) -> list[Invoice]:
    warnings = warnings if warnings is not None else []
    header, rows = _read_rows(path)
    col = _map_columns(header, INVOICE_COLUMNS, path, ("client", "amount"))
    if "due" not in col and "issued" not in col:
        raise DataError(f"{path}: need a due date or an issue date column")
    out = []
    names: dict[str, str] = {}
    for n, row in enumerate(rows, start=2):
        try:
            amount = parse_amount(row[col["amount"]])
            issued = parse_date(row[col["issued"]]) if row.get(col.get("issued", ""), "") else None
            due = parse_date(row[col["due"]]) if row.get(col.get("due", ""), "") else None
            if due is None and issued is None:
                raise ValueError("no issue or due date")
            if due is None:
                due = issued + timedelta(days=default_terms)
            if issued is None:
                issued = due - timedelta(days=default_terms)
            paid_text = row.get(col.get("paid", ""), "")
            paid = parse_date(paid_text) if paid_text else None
            client = row[col["client"]]
            if not client:
                raise ValueError("empty client")
        except (ValueError, KeyError) as exc:
            warnings.append(f"{Path(path).name} line {n}: skipped ({exc})")
            continue
        client = names.setdefault(" ".join(client.split()).casefold(), " ".join(client.split()))
        out.append(Invoice(client, row.get(col.get("number", ""), "") or f"row{n}", issued, due, amount, paid))
    if not out:
        raise DataError(f"{path}: no usable invoice rows")
    return out


def load_expenses(path, warnings: list[str] | None = None) -> list[Expense]:
    warnings = warnings if warnings is not None else []
    header, rows = _read_rows(path)
    col = _map_columns(header, EXPENSE_COLUMNS, path, ("amount", "date"))
    out = []
    for n, row in enumerate(rows, start=2):
        try:
            amount = abs(parse_amount(row[col["amount"]]))
            if row.get(col.get("type", ""), "").lower() in INCOME_WORDS:
                amount = -amount
            start = parse_date(row[col["date"]])
            freq = row.get(col.get("frequency", ""), "").lower() or "once"
            if freq not in FREQUENCIES:
                raise ValueError(f"unknown frequency {freq!r}")
            end_text = row.get(col.get("end", ""), "")
            end = parse_date(end_text) if end_text else None
        except (ValueError, KeyError) as exc:
            warnings.append(f"{Path(path).name} line {n}: skipped ({exc})")
            continue
        name = row.get(col.get("name", ""), "") or f"expense {n}"
        out.append(Expense(name, amount, start, _canonical(freq), end))
    return out


def _canonical(freq: str) -> str:
    step = FREQUENCIES[freq]
    return {0: "once", 7: "weekly", 14: "biweekly", "m": "monthly", "q": "quarterly", "y": "yearly"}[step]


def _add_months(anchor: date, months: int) -> date:
    y, m = divmod(anchor.month - 1 + months, 12)
    year, month = anchor.year + y, m + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def occurrences(exp: Expense, first: date, last: date) -> list[date]:
    """Dates in [first, last] on which the expense falls."""
    end = min(exp.end, last) if exp.end else last
    if exp.frequency == "once":
        return [exp.start] if first <= exp.start <= end else []
    days = []
    k = 0
    while True:
        if exp.frequency in ("weekly", "biweekly"):
            d = exp.start + timedelta(days=(7 if exp.frequency == "weekly" else 14) * k)
        else:
            d = _add_months(exp.start, k * {"monthly": 1, "quarterly": 3, "yearly": 12}[exp.frequency])
        if d > end:
            return days
        if d >= first:
            days.append(d)
        k += 1
