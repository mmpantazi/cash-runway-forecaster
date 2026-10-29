# Cash Runway Forecaster

Reads your invoice and expense CSVs, learns how long **each client really takes to pay**, and shows
what your bank balance is likely to do over the next 13 weeks: best case, worst case, and the
**danger date** when you first drop below the minimum you want to keep.

No dependencies (Python 3.10+ standard library), nothing leaves your machine. English and Romanian.

## Try it

```bash
python -m runway demo            # writes ./runway-demo/ with sample CSVs, prints the forecast, writes report.html
python -m runway demo --lang ro
```

## Use it on your own data

```bash
python -m runway forecast --invoices invoices.csv --expenses expenses.csv \
    --cash 14000 --buffer 3000 --html report.html
```

| option | meaning |
|---|---|
| `--cash` | money in the bank today (`14000`, `14,000.50` and `14.000,50` all work) |
| `--buffer` | the lowest balance you are comfortable with (default 0) |
| `--today` | start date, default today |
| `--terms` | payment terms in days when an invoice has no due date (default 30) |
| `--bad-debt` | chance that a normal open invoice is never paid (default 0.02) |
| `--no-projection` | do not assume regular clients keep invoicing at their usual rhythm |
| `--html FILE` | also write a self-contained report with a chart (hover for values) |
| `--lang en\|ro` | output language |
| `--runs`, `--seed` | simulations (default 2000) and random seed (same inputs, same output) |

Install as a command with `pip install .`, then run `runway forecast ...`.

### invoices.csv

One row per invoice, paid or not. Comma, semicolon or tab separated; accents and spacing in headers are ignored (`Dată încasare` = `data_incasare`); dates `2026-03-31`, `31.03.2026` or `31/03/2026`.

| column (aliases) | required | |
|---|---|---|
| `client` (customer, name, client) | yes | |
| `amount` (total, value, suma, valoare) | yes | |
| `due` (due_date, scadenta) | one of due / issued | |
| `issued` (issue_date, invoice_date, date) | | used with `--terms` if no due date |
| `paid` (paid_date, payment_date, data_plata) | | empty = still open |
| `invoice` (number, id) | | label only |

Invoices with a future date are treated as planned invoices.

### expenses.csv

| column | |
|---|---|
| `description` | label |
| `amount` | money out (sign ignored) |
| `date` | first (or only) date; past dates of recurring items are rolled forward |
| `frequency` | `once` (default), `weekly`, `biweekly`, `monthly`, `quarterly`, `yearly` (or RO: unic, saptamanal, lunar, trimestrial, anual) |
| `end` | optional last date |
| `type` | optional; `income` (or `in`, `incasare`, `venit`) marks money coming in, such as a retainer or grant |

Rows that cannot be read are skipped and listed under "Notes" in the report.

## Can I trust the band? Backtest it

```bash
python -m runway backtest --invoices invoices.csv
```

Replays past dates every 14 days using only what was known then, and checks whether the cash really collected from the invoices
already open fell inside the best-to-worst band (it should, about 80% of the time). Needs more than 5 paid invoices and, for a verdict, 10 or more replayed cases.

## How the forecast works

1. **Delay per client**: for every paid invoice, delay = paid date − due date. Recent invoices weigh more (×0.85 per step back), so a client that has recently become slower is noticed.
2. **Few invoices?** A client with `n` paid invoices uses its own history with probability `n / (n + 3)`, otherwise the pooled delays of all clients. A brand-new client therefore behaves like your average client.
3. **Open invoices** draw a payment day from the client's delays, but only from delays at least as long as the invoice is already overdue (an invoice 20 days late cannot have been paid yesterday). Invoices over 90 days late are treated as 50% never paid, over 180 days 90%.
4. **Regular billing** is projected: clients with 3+ invoices on a steady rhythm (every 7–120 days) get future invoices at their median amount, so the forecast is not only money you have already billed.
5. **Simulation**: 2000 possible futures are played day by day. *Worst* = 10th percentile of the balance, *best* = 90th, *likely* = median. The danger date is the first day the likely (or worst-case) line is below your buffer, next to the chance that any future dips below it.
6. **"What moves the danger date"** reruns the forecast with your biggest clients paying exactly on the due date.

Limits: the backtest judges payment timing only, not your expenses. The forecast only knows invoices and expenses you give it (no new-client sales, no tax guesses), and percentile lines per day are not single paths. Treat it as a risk radar, not a promise.

## Development

```bash
pip install pytest
python -m pytest
```
