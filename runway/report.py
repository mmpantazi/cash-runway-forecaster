"""Render a Forecast as terminal text or a self-contained HTML page."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, timedelta

from .i18n import STRINGS
from .model import HORIZON_DAYS, Forecast

LEVER_CLIENTS = 3


@dataclass
class Lever:
    client: str
    breach_before: float
    breach_after: float
    danger_before: date | None
    danger_after: date | None


def money(x: float) -> str:
    return f"{round(x) + 0:,}".replace("-", "−")


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def weekly_balances(fc: Forecast, series: list[float]) -> list[float]:
    return [series[w * 7 + 6] for w in range(HORIZON_DAYS // 7)]


def notes(fc: Forecast, lang: str) -> list[str]:
    s = STRINGS[lang]
    out = []
    if not any(p.n for p in fc.profiles.values()):
        out.append(s["no_history"])
    for p in fc.profiles.values():
        if 0 < p.n < 3:
            out.append(s["few"].format(client=p.name, n=p.n))
    return out


def stale_notes(stale: dict[str, int], lang: str) -> list[str]:
    return [STRINGS[lang]["stale"].format(client=c, n=n) for c, n in sorted(stale.items())]


def _date_or(d: date | None, s: dict, today: date) -> str:
    if d is None:
        return s["none"]
    return s["today"] if d == today else d.isoformat()


def trend_label(p, s) -> str:
    t = p.trend()
    if t is None:
        return ""
    if t >= 5:
        return f"{s['worse']} (+{t:.0f}{s['days']})"
    if t <= -5:
        return f"{s['better']} ({t:.0f}{s['days']})"
    return ""


def client_rows(fc: Forecast, lang: str) -> list[list[str]]:
    s = STRINGS[lang]
    rows = []
    for p in sorted(fc.profiles.values(), key=lambda p: (-p.open_amount, p.name)):
        d = s["days"]
        if p.n:
            rows.append([p.name, str(p.n), f"{p.median():.0f}{d}", f"{p.p80():.0f}{d}",
                         pct(p.late_share()), money(p.open_amount), trend_label(p, s)])
        else:
            rows.append([p.name, "0", "-", "-", "-", money(p.open_amount), s["new"]])
    return rows


def _table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    def line(r):
        return "  ".join(str(c).ljust(widths[0]) if i == 0 else str(c).rjust(widths[i])
                          for i, c in enumerate(r))
    return "\n".join([line(header), "  ".join("-" * w for w in widths)] + [line(r) for r in rows])


def week_rows(fc: Forecast) -> list[list[str]]:
    low, mid, high = (weekly_balances(fc, x) for x in (fc.low, fc.mid, fc.high))
    rows = []
    for w in range(HORIZON_DAYS // 7):
        rows.append([fc.days[w * 7 + 6].isoformat(), money(fc.weekly_in[w]), money(fc.weekly_out[w]),
                     money(low[w]), money(mid[w]), money(high[w])])
    return rows


def payments_before(fc: Forecast, limit: date, lang: str) -> str | None:
    """Biggest scheduled payments in the 7 days up to `limit`."""
    items = sorted(((a, n, d) for d, n, a in fc.scheduled
                    if a > 0 and limit - timedelta(days=7) <= d <= limit), reverse=True)[:3]
    if not items:
        return None
    text = ", ".join(f"{n} {money(a)} ({d.strftime('%d %b')})" for a, n, d in items)
    return STRINGS[lang]["before"].format(items=text)


def headline(fc: Forecast, lang: str, today: date) -> list[str]:
    s = STRINGS[lang]
    lines = [
        f"{s['danger']}",
        f"  {s['likely']}: {_date_or(fc.danger_likely, s, today)}",
        f"  {s['possible']}: {_date_or(fc.danger_possible, s, today)}",
        f"  {s['chance']}: {pct(fc.breach_probability)}",
        "  " + s["low_point"].format(low=money(min(fc.low)), mid=money(min(fc.mid))),
    ]
    first = fc.danger_possible
    if first and first > today and (hit := payments_before(fc, first, lang)):
        lines.append("  " + hit)
    return lines


def render_backtest(results, lang: str) -> str:
    s = STRINGS[lang]
    if not results:
        return s["bt_none"]
    rows = [[s["bt_weeks"].format(n=r.days // 7), str(r.cases), pct(r.inside), pct(r.below), pct(r.above),
             money(r.mean_abs_error), money(r.mean_open)] for r in results]
    cases = sum(r.cases for r in results)
    inside = sum(r.inside * r.cases for r in results) / cases
    if cases < 10:
        verdict = s["bt_few"]
    elif inside < 0.7:
        verdict = s["bt_narrow"]
    elif inside > 0.95:
        verdict = s["bt_wide"]
    else:
        verdict = s["bt_ok"]
    return "\n".join([s["bt_title"], "", _table(s["bt_head"], rows), "", s["bt_note"], verdict])


def lever_lines(levers: list[Lever], lang: str, today: date) -> list[str]:
    s = STRINGS[lang]
    out = []
    for lv in levers:
        line = s["lever"].format(client=lv.client, a=pct(lv.breach_before), b=pct(lv.breach_after))
        if lv.danger_before != lv.danger_after:
            line += "; " + s["lever_date"].format(a=_date_or(lv.danger_before, s, today),
                                                  b=_date_or(lv.danger_after, s, today))
        out.append(line)
    return out


def render_text(fc: Forecast, levers: list[Lever], warnings: list[str], lang: str, today: date,
                runs: int) -> str:
    s = STRINGS[lang]
    parts = [s["title"].upper(),
             s["from"].format(today=today.isoformat(), cash=money(fc.opening), buffer=money(fc.buffer)),
             ""]
    parts += headline(fc, lang, today) + [""]
    parts.append(_table([s["week"], s["inflow"], s["outflow"], s["worst"], s["likelyc"], s["best"]],
                        week_rows(fc)))
    parts += ["", s["clients"],
              _table([s["client"], s["paid"], s["median"], s["p80"], s["late"], s["open"], s["trend"]],
                     client_rows(fc, lang))]
    if levers:
        parts += ["", s["levers"]] + ["  " + line for line in lever_lines(levers, lang, today)]
    if warnings:
        parts += ["", s["warnings"]] + ["  - " + w for w in warnings]
    parts += ["", s["method"].format(runs=runs)]
    return "\n".join(parts)


INK, MUTED, GRID = "#1f2933", "#52606d", "#e4e7eb"
BLUE, BAND, RED = "#1f6fb2", "#cfe3f5", "#b42318"
W, H, ML, MR, MT, MB = 860, 360, 70, 20, 20, 40


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    raw = (hi - lo) / target
    magnitude = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw)
    first = -(-lo // step) * step
    ticks = []
    while first <= hi:
        ticks.append(first)
        first += step
    return ticks


def _chart(fc: Forecast, lang: str, today: date) -> str:
    s = STRINGS[lang]
    n = len(fc.days)
    lo = min(min(fc.low), fc.buffer, 0)
    hi = max(max(fc.high), fc.buffer, 0)
    span = (hi - lo) or 1
    lo, hi = lo - span * 0.05, hi + span * 0.05

    def x(i):
        return ML + (W - ML - MR) * i / (n - 1)

    def y(v):
        return MT + (H - MT - MB) * (hi - v) / (hi - lo)

    def poly(series):
        return " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series))

    band = poly(fc.high) + " " + " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in reversed(list(enumerate(fc.low))))
    svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(s["title"])}" id="chart">']
    for v in nice_ticks(lo, hi):
        svg.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"/>')
        svg.append(f'<text x="{ML - 8}" y="{y(v) + 4:.1f}" text-anchor="end" fill="{MUTED}" font-size="11">{money(v)}</text>')
    for w in range(0, HORIZON_DAYS // 7 + 1, 2):
        i = min(w * 7, n - 1)
        svg.append(f'<text x="{x(i):.1f}" y="{H - 16}" text-anchor="middle" fill="{MUTED}" font-size="11">{fc.days[i].strftime("%d %b")}</text>')
    svg.append(f'<polygon points="{band}" fill="{BAND}"/>')
    svg.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y(fc.buffer):.1f}" y2="{y(fc.buffer):.1f}" stroke="{MUTED}" stroke-dasharray="5 4"/>')
    svg.append(f'<text x="{W - MR}" y="{y(fc.buffer) - 5:.1f}" text-anchor="end" fill="{MUTED}" font-size="11">{html.escape(s["chart_buffer"])}</text>')
    svg.append(f'<polyline points="{poly(fc.mid)}" fill="none" stroke="{BLUE}" stroke-width="2.5" stroke-linejoin="round"/>')
    for d, label in ((fc.danger_possible, s["possible"]), (fc.danger_likely, s["likely"])):
        if d is not None:
            i = (d - fc.days[0]).days
            svg.append(f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{MT}" y2="{H - MB}" stroke="{RED}" stroke-width="1.5" stroke-dasharray="2 3"/>')
    if fc.danger_possible is not None:
        i = (fc.danger_possible - fc.days[0]).days
        anchor = "end" if i > n * 0.6 else "start"
        dx = -6 if anchor == "end" else 6
        svg.append(f'<text x="{x(i) + dx:.1f}" y="{MT + 12}" text-anchor="{anchor}" fill="{RED}" font-size="12" font-weight="600">{html.escape(s["chart_danger"])} {fc.danger_possible.isoformat()}</text>')
    svg.append(f'<line id="cross" x1="0" x2="0" y1="{MT}" y2="{H - MB}" stroke="{INK}" opacity="0" />')
    svg.append("</svg>")
    return "\n".join(svg)


def _html_table(header: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(fc: Forecast, levers: list[Lever], warnings: list[str], lang: str, today: date,
                runs: int) -> str:
    s = STRINGS[lang]
    data = [[d.isoformat(), round(a), round(b), round(c)] for d, a, b, c in zip(fc.days, fc.low, fc.mid, fc.high)]
    n = len(fc.days)
    plot_w = W - ML - MR
    heads = "".join(f"<p>{html.escape(l.strip())}</p>" if i else f"<h2>{html.escape(l)}</h2>"
                    for i, l in enumerate(headline(fc, lang, today)))
    lever_html = ""
    if levers:
        items = "".join(f"<li>{html.escape(l)}</li>" for l in lever_lines(levers, lang, today))
        lever_html = f"<h2>{html.escape(s['levers'])}</h2><ul>{items}</ul>"
    note_html = ""
    if warnings:
        note_html = f"<h2>{html.escape(s['warnings'])}</h2><ul>" + "".join(
            f"<li>{html.escape(w)}</li>" for w in warnings) + "</ul>"
    legend = (f'<p class="legend"><span class="sw" style="background:{BAND}"></span>{html.escape(s["chart_band"])}'
              f' &nbsp; <span class="sw" style="background:{BLUE}"></span>{html.escape(s["chart_mid"])}'
              f' &nbsp; <span class="sw" style="background:{RED}"></span>{html.escape(s["chart_danger"])}</p>')
    script = f"""
const D={data},ML={ML},PW={plot_w},N={n};
const svg=document.getElementById('chart'),cross=document.getElementById('cross'),tip=document.getElementById('tip');
svg.addEventListener('mousemove',e=>{{
  const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)/r.width*{W};
  const i=Math.max(0,Math.min(N-1,Math.round((px-ML)/PW*(N-1))));
  const x=ML+PW*i/(N-1);cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.setAttribute('opacity',.5);
  const d=D[i];tip.hidden=false;tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';
  tip.textContent=d[0]+'  {s["worst"]} '+d[1].toLocaleString()+'  {s["likelyc"]} '+d[2].toLocaleString()+'  {s["best"]} '+d[3].toLocaleString();
}});
svg.addEventListener('mouseleave',()=>{{cross.setAttribute('opacity',0);tip.hidden=true;}});
"""
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(s['title'])}</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;color:{INK};max-width:900px;margin:2rem auto;padding:0 1rem;background:#fff}}
h1{{font-size:1.5rem;margin:0}} h2{{font-size:1.1rem;margin:1.6rem 0 .4rem}} p{{margin:.2rem 0}}
.sub{{color:{MUTED}}} table{{border-collapse:collapse;width:100%;font-size:13px;margin:.4rem 0}}
th,td{{text-align:right;padding:4px 8px;border-bottom:1px solid {GRID}}} th:first-child,td:first-child{{text-align:left}}
th{{color:{MUTED};font-weight:600}} svg{{width:100%;height:auto}} .legend{{font-size:13px;color:{MUTED}}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:-1px;margin-right:4px}}
#tip{{position:fixed;background:{INK};color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;pointer-events:none}}
details{{margin-top:1rem}}
</style></head><body>
<h1>{html.escape(s['title'])}</h1>
<p class="sub">{html.escape(s['from'].format(today=today.isoformat(), cash=money(fc.opening), buffer=money(fc.buffer)))}</p>
{heads}
{_chart(fc, lang, today)}
{legend}
<div id="tip" hidden></div>
<details open><summary>{html.escape(s['table_view'])}</summary>
{_html_table([s['week'], s['inflow'], s['outflow'], s['worst'], s['likelyc'], s['best']], week_rows(fc))}</details>
<h2>{html.escape(s['clients'])}</h2>
{_html_table([s['client'], s['paid'], s['median'], s['p80'], s['late'], s['open'], s['trend']], client_rows(fc, lang))}
{lever_html}{note_html}
<p class="sub" style="margin-top:1.5rem">{html.escape(s['method'].format(runs=runs))}</p>
<script>{script}</script>
</body></html>
"""
