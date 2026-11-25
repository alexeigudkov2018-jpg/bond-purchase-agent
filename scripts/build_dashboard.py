"""Собирает dashboard.html — многовкладочный терминал на миллиметровке Ганна.

Числа только из data/ и reports/. При отсутствии снимков
data/bonds_tuesday_latest.csv, data/ps_screener_latest.csv,
data/macro_ofz_latest.md скрипт собирает их из уже лежащих источников.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"

OUT = ROOT / "dashboard.html"


def now_msk() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Moscow"))
    except Exception:  # noqa: BLE001
        return datetime.now()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in columns})
EVENTS = ROOT / "data" / "radar_events.csv"
PS_HISTORY = ROOT / "almanac_ps_history.md"
REPORTS = ROOT / "reports"
ALMANAC = ROOT / "almanac"
NARRATIVE = ROOT / "data" / "narrative"
FINRADAR = ROOT / "data" / "finradar"
BONDS_CSV = ROOT / "data" / "bonds_tuesday_latest.csv"
PS_CSV = ROOT / "data" / "ps_screener_latest.csv"
MACRO_MD = ROOT / "data" / "macro_ofz_latest.md"
CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
TICKER_ORDER = ("IMOEX", "SMLT", "KLVZ", "EUTR", "MGKL", "SELG", "TATN", "OZON", "GAZP")
SECTOR_INDICES = (
    ("MOEXOG", "Нефтегаз"),
    ("MOEXMM", "Металлы и добыча"),
    ("MOEXFN", "Финансы"),
    ("MOEXCN", "Потребительский"),
    ("MOEXCH", "Химия"),
    ("MOEXEU", "Энергетика"),
    ("MOEXTN", "Транспорт"),
    ("MOEX10", "MOEX10"),
)
FRACTIONS = (
    ("MOEXOG", "IMOEX", "Нефтегаз / IMOEX"),
    ("MOEXMM", "IMOEX", "Металлы / IMOEX"),
    ("MOEXFN", "IMOEX", "Финансы / IMOEX"),
    ("MOEXCN", "IMOEX", "Потреб / IMOEX"),
    ("MOEXCH", "IMOEX", "Химия / IMOEX"),
    ("MOEXEU", "IMOEX", "Энергетика / IMOEX"),
    ("MOEXTN", "IMOEX", "Транспорт / IMOEX"),
    ("IMOEX", "RGBITR", "IMOEX / RGBITR"),
    ("RGBITR", "RGBI", "RGBITR / RGBI"),
    ("MOEX10", "IMOEX", "MOEX10 / IMOEX"),
)


def _num(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt(value, digits=2):
    number = _num(value) if not isinstance(value, (int, float)) else value
    if number is None:
        return "нет"
    return f"{float(number):.{digits}f}"


def _pct(value, digits=2):
    number = _num(value) if not isinstance(value, (int, float)) else value
    if number is None:
        return "нет"
    sign = "+" if number > 0 else ""
    return f"{sign}{float(number):.{digits}f}%"


def _json_blob(payload) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def load_index_series() -> dict[str, dict[str, float]]:
    series: dict[str, dict[str, float]] = defaultdict(dict)
    for row in read_csv(CLEAN / "indices_daily.csv"):
        name = row.get("index") or ""
        stamp = row.get("date") or ""
        close = _num(row.get("close"))
        if name and stamp and close is not None:
            series[name][stamp] = close
    return series


def last_two(series: dict[str, float]) -> tuple[str | None, float | None, float | None, float | None]:
    dates = sorted(series)
    if not dates:
        return None, None, None, None
    last = dates[-1]
    prev = dates[-2] if len(dates) > 1 else None
    last_v = series[last]
    prev_v = series[prev] if prev else None
    day_pct = ((last_v / prev_v) - 1.0) * 100.0 if prev_v else None
    return last, last_v, prev_v, day_pct


def ret_n(series: dict[str, float], sessions: int) -> float | None:
    dates = sorted(series)
    if len(dates) <= sessions:
        return None
    a = series[dates[-(sessions + 1)]]
    b = series[dates[-1]]
    if not a:
        return None
    return ((b / a) - 1.0) * 100.0


def direction(value: float | None) -> str:
    if value is None:
        return "нет ряда"
    if value > 0.05:
        return "сильнее"
    if value < -0.05:
        return "слабее"
    return "плоско"


def parse_ps_history() -> list[dict]:
    rows = []
    if not PS_HISTORY.exists():
        return rows
    for line in PS_HISTORY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "Дата" in line or re.match(r"^\|\s*-+", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        stamp = cells[0]
        if not re.match(r"\d{2}\.\d{2}\.\d{4}", stamp):
            continue
        day, month, year = stamp.split(".")
        iso = f"{year}-{month}-{day}"
        rows.append(
            {
                "date": iso,
                "date_ru": stamp,
                "ps": _num(cells[1]),
                "cap_trn": _num(cells[2]),
                "sales_bn": _num(cells[3]) if len(cells) > 3 else None,
                "note": cells[5] if len(cells) > 5 else (cells[4] if len(cells) > 4 else ""),
            }
        )
    rows.sort(key=lambda item: item["date"])
    return rows


def latest_report() -> Path | None:
    files = sorted(REPORTS.glob("imoex_ps_*.md"))
    return files[-1] if files else None


def parse_ps_report_table(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    text = path.read_text(encoding="utf-8")
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Эмитент"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        tickers = re.findall(r"[A-Z0-9]+", cells[1].replace("+", " "))
        rows.append(
            {
                "issuer": cells[0],
                "tickers": cells[1],
                "ticker": tickers[0] if tickers else "",
                "weight_pct": _num(cells[2]),
                "mcap_bn": _num(cells[3]),
                "sales_bn": _num(cells[4]),
                "ps": _num(cells[5]),
                "report": cells[6] if len(cells) > 6 else "",
                "delta_ps": _num(cells[7]) if len(cells) > 7 else None,
                "window": cells[8] if len(cells) > 8 else "",
            }
        )
    return rows


def volume_spike_map(tickers: set[str]) -> dict[str, float | None]:
    if not tickers:
        return {}
    by_ticker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with (CLEAN / "prices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("ticker") or ""
            if ticker not in tickers:
                continue
            vol = _num(row.get("volume_rub"))
            stamp = row.get("date") or ""
            if stamp and vol is not None:
                by_ticker[ticker].append((stamp, vol))
    out: dict[str, float | None] = {}
    for ticker, points in by_ticker.items():
        points.sort()
        if len(points) < 6:
            out[ticker] = None
            continue
        last = points[-1][1]
        window = [v for _, v in points[-21:-1]]
        avg = sum(window) / len(window) if window else None
        out[ticker] = (last / avg) if avg else None
    return out


def rs_to_imoex(tickers: set[str], sessions: int = 20) -> dict[str, float | None]:
    series = load_index_series()
    imoex = series.get("IMOEX", {})
    imoex_ret = ret_n(imoex, sessions)
    closes: dict[str, dict[str, float]] = defaultdict(dict)
    with (CLEAN / "prices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("ticker") or ""
            if ticker not in tickers:
                continue
            close = _num(row.get("close"))
            stamp = row.get("date") or ""
            if stamp and close is not None:
                closes[ticker][stamp] = close
    out: dict[str, float | None] = {}
    for ticker in tickers:
        own = ret_n(closes.get(ticker, {}), sessions)
        if own is None or imoex_ret is None:
            out[ticker] = None
        else:
            out[ticker] = own - imoex_ret
    return out


def ensure_ps_screener() -> list[dict]:
    if PS_CSV.exists():
        return read_csv(PS_CSV)
    report = latest_report()
    rows = parse_ps_report_table(report) if report else []
    tickers = {row["ticker"] for row in rows if row.get("ticker")}
    spikes = volume_spike_map(tickers)
    rs_map = rs_to_imoex(tickers)
    as_of = report.stem.replace("imoex_ps_", "") if report else ""
    material = []
    for row in rows:
        ticker = row.get("ticker") or ""
        material.append(
            {
                "as_of": as_of,
                "issuer": row.get("issuer") or "",
                "tickers": row.get("tickers") or "",
                "ticker": ticker,
                "weight_pct": row.get("weight_pct") if row.get("weight_pct") is not None else "",
                "mcap_bn": row.get("mcap_bn") if row.get("mcap_bn") is not None else "",
                "sales_bn": row.get("sales_bn") if row.get("sales_bn") is not None else "",
                "ps": row.get("ps") if row.get("ps") is not None else "",
                "delta_ps": row.get("delta_ps") if row.get("delta_ps") is not None else "",
                "window": row.get("window") or "",
                "volume_spike": "" if spikes.get(ticker) is None else f"{spikes[ticker]:.4f}",
                "rs_imoex_20": "" if rs_map.get(ticker) is None else f"{rs_map[ticker]:.4f}",
                "report": row.get("report") or "",
            }
        )
    write_csv(
        PS_CSV,
        [
            "as_of",
            "issuer",
            "tickers",
            "ticker",
            "weight_pct",
            "mcap_bn",
            "sales_bn",
            "ps",
            "delta_ps",
            "window",
            "volume_spike",
            "rs_imoex_20",
            "report",
        ],
        material,
    )
    return material


def ensure_bonds_tuesday() -> list[dict]:
    if BONDS_CSV.exists():
        return read_csv(BONDS_CSV)
    package_path = ROOT / "data" / "latest_package.json"
    rows: list[dict] = []
    if package_path.exists():
        payload = json.loads(package_path.read_text(encoding="utf-8"))
        asof = payload.get("asof") or ""
        for item in payload.get("package") or []:
            rows.append(
                {
                    "as_of": asof,
                    "status": item.get("verdict") or "package",
                    "bucket": item.get("bucket") or "",
                    "secid": item.get("secid") or "",
                    "isin": item.get("isin") or "",
                    "shortname": item.get("shortname") or "",
                    "issuer": item.get("issuer") or "",
                    "rating": item.get("rating") or "",
                    "ytm": item.get("ytm") if item.get("ytm") is not None else "",
                    "duration_years": item.get("duration_years") if item.get("duration_years") is not None else "",
                    "g_spread_bp": item.get("g_spread_bp") if item.get("g_spread_bp") is not None else "",
                    "price_pct": item.get("price_pct") if item.get("price_pct") is not None else "",
                    "qty": item.get("qty") if item.get("qty") is not None else "",
                    "debit": item.get("debit") if item.get("debit") is not None else "",
                    "reason": item.get("slot_title") or "",
                    "anomaly": "",
                }
            )
        for item in payload.get("waitlist") or []:
            rows.append(
                {
                    "as_of": asof,
                    "status": "wait",
                    "bucket": "corp",
                    "secid": item.get("secid") or "",
                    "isin": item.get("isin") or "",
                    "shortname": item.get("shortname") or "",
                    "issuer": item.get("issuer") or "",
                    "rating": item.get("rating") or "",
                    "ytm": item.get("ytm") if item.get("ytm") is not None else "",
                    "duration_years": item.get("duration_years") if item.get("duration_years") is not None else "",
                    "g_spread_bp": item.get("g_spread_bp") if item.get("g_spread_bp") is not None else "",
                    "price_pct": item.get("price") if item.get("price") is not None else "",
                    "qty": "",
                    "debit": "",
                    "reason": item.get("reason") or "",
                    "anomaly": "waitlist",
                }
            )
        for item in (payload.get("exceptions") or [])[:12]:
            rows.append(
                {
                    "as_of": asof,
                    "status": "exception",
                    "bucket": "corp",
                    "secid": item.get("secid") or "",
                    "isin": item.get("isin") or "",
                    "shortname": item.get("shortname") or "",
                    "issuer": item.get("issuer") or "",
                    "rating": item.get("rating") or "",
                    "ytm": item.get("ytm") if item.get("ytm") is not None else "",
                    "duration_years": item.get("duration_years") if item.get("duration_years") is not None else "",
                    "g_spread_bp": item.get("g_spread_bp") if item.get("g_spread_bp") is not None else "",
                    "price_pct": item.get("price") if item.get("price") is not None else "",
                    "qty": "",
                    "debit": "",
                    "reason": item.get("reason") or "",
                    "anomaly": "short_aaa_aa",
                }
            )
        for item in (payload.get("rejected_examples") or [])[:8]:
            if "ОФЗ" in (item.get("shortname") or ""):
                continue
            rows.append(
                {
                    "as_of": asof,
                    "status": "reject",
                    "bucket": "corp",
                    "secid": item.get("secid") or "",
                    "isin": item.get("isin") or "",
                    "shortname": item.get("shortname") or "",
                    "issuer": item.get("issuer") or "",
                    "rating": item.get("rating") or "",
                    "ytm": item.get("ytm") if item.get("ytm") is not None else "",
                    "duration_years": item.get("duration_years") if item.get("duration_years") is not None else "",
                    "g_spread_bp": item.get("g_spread_bp") if item.get("g_spread_bp") is not None else "",
                    "price_pct": item.get("price") if item.get("price") is not None else "",
                    "qty": "",
                    "debit": "",
                    "reason": item.get("reason") or "",
                    "anomaly": "rejected",
                }
            )
    write_csv(
        BONDS_CSV,
        [
            "as_of",
            "status",
            "bucket",
            "secid",
            "isin",
            "shortname",
            "issuer",
            "rating",
            "ytm",
            "duration_years",
            "g_spread_bp",
            "price_pct",
            "qty",
            "debit",
            "reason",
            "anomaly",
        ],
        rows,
    )
    return rows


def ensure_macro_md(series: dict[str, dict[str, float]], curve: dict) -> str:
    if MACRO_MD.exists():
        return MACRO_MD.read_text(encoding="utf-8")
    imoex = series.get("IMOEX", {})
    imoex_dates = sorted(imoex)
    stamp = imoex_dates[-1] if imoex_dates else None
    prev = imoex_dates[-2] if len(imoex_dates) > 1 else None
    day = ((imoex[stamp] / imoex[prev]) - 1.0) * 100.0 if stamp and prev else None
    lines = [
        "# Макро / ОФЗ / дроби — снимок для dashboard",
        "",
        f"Сессия: {stamp or 'нет'}. Источник: `data/clean/indices_daily.csv`, `data/clean/ofz_curve_daily.csv`.",
        "",
        "## КБД",
        "",
        f"- 1Y: {_fmt(curve.get('t_1y'))}%",
        f"- 2Y: {_fmt(curve.get('t_2y'))}%",
        f"- 5Y: {_fmt(curve.get('t_5y'))}%",
        f"- 10Y: {_fmt(curve.get('t_10y'))}%",
        f"- 15Y: {_fmt(curve.get('t_15y'))}%",
        f"- Спред 10Y−2Y: {_fmt((lambda a, b: None if a is None or b is None else a - b)(_num(curve.get('t_10y')), _num(curve.get('t_2y'))))} п.п.",
        "",
        "## Отрасли: избыток к IMOEX за день",
        "",
        "| Индекс | День, % | Избыток к IMOEX, п.п. |",
        "| --- | ---: | ---: |",
    ]
    for code, title in SECTOR_INDICES:
        own = series.get(code, {})
        if not stamp or not prev or stamp not in own or prev not in own or not own[prev]:
            lines.append(f"| {title} ({code}) | нет | нет |")
            continue
        own_day = ((own[stamp] / own[prev]) - 1.0) * 100.0
        excess = None if day is None else own_day - day
        lines.append(f"| {title} ({code}) | {_fmt(own_day)} | {_fmt(excess)} |")
    lines.extend(["", "## Дроби 5с / 20с", "", "| Дробь | 5 сессий | 20 сессий |", "| --- | --- | --- |"])
    for num, den, label in FRACTIONS:
        ratio = {}
        left = series.get(num, {})
        right = series.get(den, {})
        for day_key in sorted(set(left) & set(right)):
            if right[day_key]:
                ratio[day_key] = left[day_key] / right[day_key]
        r5 = ret_n(ratio, 5)
        r20 = ret_n(ratio, 20)
        lines.append(f"| {label} | {direction(r5)} ({_fmt(r5)}) | {direction(r20)} ({_fmt(r20)}) |")
    text = "\n".join(lines) + "\n"
    MACRO_MD.write_text(text, encoding="utf-8")
    return text


def load_curve() -> dict:
    rows = read_csv(CLEAN / "ofz_curve_daily.csv")
    return rows[-1] if rows else {}


def load_finradar_extras() -> dict:
    files = sorted(FINRADAR.glob("*.md"))
    if not files:
        return {"rvi": None, "cnyrub": None, "source": "", "as_of": ""}
    path = files[-1]
    text = path.read_text(encoding="utf-8")
    rvi = None
    cny = None
    m_rvi = re.search(r"\|\s*RVI\s*\|\s*([0-9]+[.,][0-9]+)", text)
    if m_rvi:
        rvi = _num(m_rvi.group(1))
    m_cny = re.search(r"\|\s*CNYRUB_TOM[^\|]*\|\s*([0-9]+[.,][0-9]+)", text)
    if m_cny:
        cny = _num(m_cny.group(1))
    return {"rvi": rvi, "cnyrub": cny, "source": str(path.relative_to(ROOT)), "as_of": path.stem[:10]}


def load_bars(tickers: list[str]) -> dict[str, list[dict]]:
    wanted = set(tickers)
    bars: dict[str, dict[str, dict]] = {}
    with (CLEAN / "prices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("ticker") or ""
            if ticker not in wanted:
                continue
            stamp = row.get("date") or ""
            open_, high, low, close = (_num(row.get(name)) for name in ("open", "high", "low", "close"))
            if not stamp or close is None:
                continue
            bars.setdefault(ticker, {})[stamp] = {
                "time": stamp,
                "open": open_ if open_ is not None else close,
                "high": high if high is not None else close,
                "low": low if low is not None else close,
                "close": close,
            }
    # Индексы не подмешиваем к тикерам, уже взятым из prices_daily.
    share_tickers = set(bars)
    with (CLEAN / "indices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("index") or ""
            if ticker not in wanted or ticker in share_tickers:
                continue
            stamp = row.get("date") or ""
            close = _num(row.get("close"))
            if not stamp or close is None:
                continue
            bars.setdefault(ticker, {})[stamp] = {
                "time": stamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
            }
    return {
        ticker: [bars[ticker][stamp] for stamp in sorted(bars[ticker])]
        for ticker in tickers
        if ticker in bars
    }


def load_events() -> list[dict]:
    rows = []
    if not EVENTS.exists():
        return rows
    for row in read_csv(EVENTS):
        heat = _num(row.get("heat"))
        tone = _num(row.get("tone"))
        if not row.get("date") or not row.get("ticker") or heat is None or tone is None:
            continue
        rows.append(
            {
                "date": row["date"],
                "time_msk": row.get("time_msk") or "",
                "ticker": row["ticker"],
                "heat": heat,
                "tone": tone,
                "category": row.get("category") or "",
                "short_label": row.get("short_label") or "",
                "thesis": row.get("thesis") or "",
                "source_channel": row.get("source_channel") or "",
            }
        )
    rows.sort(key=lambda item: (item["date"], item["time_msk"], item["ticker"]))
    return rows


def ticker_list(events: list[dict]) -> list[str]:
    found = {row["ticker"] for row in events}
    ordered = [name for name in TICKER_ORDER if name in found]
    ordered.extend(sorted(found - set(ordered)))
    return ordered or ["IMOEX"]


def parse_soros_loops() -> list[dict]:
    files = sorted(NARRATIVE.glob("*.md"))
    if not files:
        return []
    path = files[-1]
    text = path.read_text(encoding="utf-8")
    loops = []
    section = re.search(
        r"## 3[^\n]*[Пп]етл[^\n]*\n(.*?)(?=\n## |\Z)",
        text,
        flags=re.S,
    )
    block = section.group(1) if section else text
    for match in re.finditer(
        r"(?:^\d+\.\s+\*\*|^\|\s*[A-Z]\s*\|\s*)([^\n|*]+?)(?:\*\*)?(?:\s*\||\s*$)",
        block,
        flags=re.M,
    ):
        title = match.group(1).strip(" |*")
        if len(title) < 8:
            continue
        loops.append({"title": title[:180], "source": path.name})
        if len(loops) >= 6:
            break
    finale = re.search(r"\*\*Главная петля[^*]*\*\*[:：]?\s*([^\n]+)", text)
    if finale:
        loops.insert(0, {"title": "Главная: " + finale.group(1).strip(" ."), "source": path.name})

    def _clean(title: str) -> str:
        return re.sub(r"\*+", "", title).strip(" .|")

    seen = set()
    unique = []
    for item in loops:
        title = _clean(item["title"])
        if len(title) < 8 or title in seen:
            continue
        seen.add(title)
        unique.append({"title": title, "source": item["source"]})
    return unique[:6]


def parse_almanac_diff() -> dict:
    files = sorted(ALMANAC.glob("DIFF_*.md"))
    if not files:
        return {"file": "", "rows": []}
    path = files[-1]
    text = path.read_text(encoding="utf-8")
    rows = []
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"metric": line[3:].strip(), "was": "", "became": "", "delta": ""}
            rows.append(current)
            continue
        if not current:
            continue
        if line.startswith("Было:"):
            current["was"] = line.split(":", 1)[1].strip()
        elif line.startswith("Стало:"):
            current["became"] = line.split(":", 1)[1].strip()
        elif line.startswith("Дельта:"):
            current["delta"] = line.split(":", 1)[1].strip()
    return {"file": str(path.relative_to(ROOT)), "rows": rows}


def build_fractions(series: dict[str, dict[str, float]]) -> list[dict]:
    out = []
    for num, den, label in FRACTIONS:
        ratio = {}
        left = series.get(num, {})
        right = series.get(den, {})
        for day in sorted(set(left) & set(right)):
            if right[day]:
                ratio[day] = left[day] / right[day]
        r5 = ret_n(ratio, 5)
        r20 = ret_n(ratio, 20)
        out.append(
            {
                "label": label,
                "num": num,
                "den": den,
                "ret5": r5,
                "ret20": r20,
                "dir5": direction(r5),
                "dir20": direction(r20),
            }
        )
    return out


def build_sectors(series: dict[str, dict[str, float]]) -> list[dict]:
    imoex = series.get("IMOEX", {})
    imoex_dates = sorted(imoex)
    if len(imoex_dates) < 2:
        return []
    stamp = imoex_dates[-1]
    prev = imoex_dates[-2]
    imoex_day = ((imoex[stamp] / imoex[prev]) - 1.0) * 100.0
    rows = []
    for code, title in SECTOR_INDICES:
        own = series.get(code, {})
        if stamp not in own or prev not in own or not own[prev]:
            rows.append(
                {
                    "code": code,
                    "title": title,
                    "date": stamp,
                    "close": own.get(stamp),
                    "day_pct": None,
                    "excess": None,
                }
            )
            continue
        day = ((own[stamp] / own[prev]) - 1.0) * 100.0
        rows.append(
            {
                "code": code,
                "title": title,
                "date": stamp,
                "close": own[stamp],
                "day_pct": day,
                "excess": day - imoex_day,
            }
        )
    rows.sort(key=lambda item: (item["excess"] is None, -(item["excess"] or 0)))
    return rows


def build_kpi(series, curve, ps_history, extras) -> dict:
    imoex_date, imoex, _, imoex_day = last_two(series.get("IMOEX", {}))
    rgbi_date, rgbitr, _, rgbitr_day = last_two(series.get("RGBITR", {}))
    y10 = _num(curve.get("t_10y"))
    y2 = _num(curve.get("t_2y"))
    spread = None if y10 is None or y2 is None else y10 - y2
    ps_vals = [row["ps"] for row in ps_history if row.get("ps") is not None]
    ps_last = ps_history[-1] if ps_history else {}
    return {
        "updated_at": now_msk().strftime("%Y-%m-%d %H:%M МСК"),
        "imoex": {"date": imoex_date, "value": imoex, "day_pct": imoex_day},
        "rgbitr": {"date": rgbi_date, "value": rgbitr, "day_pct": rgbitr_day},
        "ofz10": {"value": y10, "date": curve.get("date"), "spread_10_2": spread, "y2": y2},
        "ps": {
            "value": ps_last.get("ps"),
            "date": ps_last.get("date_ru") or ps_last.get("date"),
            "min": min(ps_vals) if ps_vals else None,
            "max": max(ps_vals) if ps_vals else None,
        },
        "rvi": {"value": extras.get("rvi"), "as_of": extras.get("as_of"), "source": extras.get("source")},
        "cnyrub": {"value": extras.get("cnyrub"), "as_of": extras.get("as_of"), "source": extras.get("source")},
    }


def build_payload() -> dict:
    series = load_index_series()
    curve = load_curve()
    extras = load_finradar_extras()
    ps_history = parse_ps_history()
    events = load_events()
    tickers = ticker_list(events)
    bars = load_bars(tickers)
    bonds = ensure_bonds_tuesday()
    ps_rows = ensure_ps_screener()
    ensure_macro_md(series, curve)
    return {
        "kpi": build_kpi(series, curve, ps_history, extras),
        "candles": {"tickers": tickers, "bars": bars, "events": events},
        "loops": parse_soros_loops(),
        "curve": {
            "date": curve.get("date"),
            "points": [
                {"tenor": "1Y", "years": 1, "ytm": _num(curve.get("t_1y"))},
                {"tenor": "2Y", "years": 2, "ytm": _num(curve.get("t_2y"))},
                {"tenor": "5Y", "years": 5, "ytm": _num(curve.get("t_5y"))},
                {"tenor": "10Y", "years": 10, "ytm": _num(curve.get("t_10y"))},
                {"tenor": "15Y", "years": 15, "ytm": _num(curve.get("t_15y"))},
            ],
        },
        "bonds": [
            {
                "status": row.get("status") or "",
                "bucket": row.get("bucket") or "",
                "secid": row.get("secid") or "",
                "shortname": row.get("shortname") or "",
                "issuer": row.get("issuer") or "",
                "rating": row.get("rating") or "",
                "ytm": _num(row.get("ytm")),
                "duration_years": _num(row.get("duration_years")),
                "g_spread_bp": _num(row.get("g_spread_bp")),
                "price_pct": _num(row.get("price_pct")),
                "qty": row.get("qty") or "",
                "debit": _num(row.get("debit")),
                "reason": row.get("reason") or "",
                "anomaly": row.get("anomaly") or "",
            }
            for row in bonds
        ],
        "ps_screener": [
            {
                "issuer": row.get("issuer") or "",
                "tickers": row.get("tickers") or "",
                "ticker": row.get("ticker") or "",
                "weight_pct": _num(row.get("weight_pct")),
                "mcap_bn": _num(row.get("mcap_bn")),
                "sales_bn": _num(row.get("sales_bn")),
                "ps": _num(row.get("ps")),
                "delta_ps": _num(row.get("delta_ps")),
                "window": row.get("window") or "",
                "volume_spike": _num(row.get("volume_spike")),
                "rs_imoex_20": _num(row.get("rs_imoex_20")),
            }
            for row in ps_rows
        ],
        "ps_history": ps_history,
        "fractions": build_fractions(series),
        "sectors": build_sectors(series),
        "almanac_diff": parse_almanac_diff(),
        "disclaimer": "Материал не является индивидуальной инвестиционной рекомендацией.",
    }


def build() -> None:
    payload = build_payload()
    html = HTML.replace("__DATA__", _json_blob(payload)).replace("__CDN__", CDN)
    OUT.write_text(html, encoding="utf-8")
    kpi = payload["kpi"]
    print(
        f"wrote {OUT.relative_to(ROOT)} "
        f"tickers={len(payload['candles']['tickers'])} "
        f"events={len(payload['candles']['events'])} "
        f"bonds={len(payload['bonds'])} "
        f"ps_rows={len(payload['ps_screener'])} "
        f"imoex={kpi['imoex']['value']} ps={kpi['ps']['value']}"
    )


HTML = r"""<!DOCTYPE html>
<html lang="ru" data-theme="gann">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TERMINAL · GANN / RADAR</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Libre+Baskerville:wght@400;700&display=swap" rel="stylesheet">
<script src="__CDN__"></script>
<style>
:root, [data-theme="gann"] {
  --paper: #F7F1D5;
  --card: #FCF8E3;
  --ink: #1C1915;
  --muted: #5C4F38;
  --rule: #B89856;
  --grid-minor: rgba(184, 152, 86, 0.22);
  --grid-major: rgba(160, 125, 58, 0.42);
  --up: #1B6B3A;
  --down: #A62626;
  --blue: #1D3E6E;
  --warn: #8A5A12;
  --chip: #F3E7B8;
  --shadow: rgba(92, 79, 56, 0.12);
  --chart-bg: #FCF8E3;
  --chart-text: #1C1915;
  --chart-grid: rgba(160, 125, 58, 0.35);
}
[data-theme="dark"] {
  --paper: #0b0f14;
  --card: #121820;
  --ink: #d7e0ea;
  --muted: #8b9aab;
  --rule: #3a4a5c;
  --grid-minor: rgba(80, 110, 140, 0.12);
  --grid-major: rgba(100, 140, 180, 0.22);
  --up: #3dd68c;
  --down: #f07178;
  --blue: #7eb6ff;
  --warn: #e6b84d;
  --chip: #1a2330;
  --shadow: rgba(0,0,0,0.35);
  --chart-bg: #121820;
  --chart-text: #d7e0ea;
  --chart-grid: rgba(100, 140, 180, 0.25);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  color: var(--ink);
  font-family: "Libre Baskerville", Georgia, serif;
  background-color: var(--paper);
  background-image:
    linear-gradient(var(--grid-minor) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-minor) 1px, transparent 1px),
    linear-gradient(var(--grid-major) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-major) 1px, transparent 1px);
  background-size: 10px 10px, 10px 10px, 50px 50px, 50px 50px;
  background-position: -1px -1px, -1px -1px, -1px -1px, -1px -1px;
  min-height: 100vh;
}
.mono { font-family: "JetBrains Mono", Consolas, monospace; }
header.app {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 18px 8px;
}
header.app h1 {
  margin: 0;
  font-size: 20px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
header.app .note { margin: 6px 0 0; font-size: 12px; color: var(--muted); max-width: 720px; }
#themeToggle {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  padding: 8px 10px;
  border: 1px solid var(--rule);
  background: var(--card);
  color: var(--ink);
  cursor: pointer;
  white-space: nowrap;
}
.kpi {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  padding: 8px 18px 12px;
}
.kpi .card {
  background: var(--card);
  border: 1px solid var(--rule);
  padding: 10px 12px;
  box-shadow: 0 1px 0 var(--shadow);
}
.kpi .label { font-family: "JetBrains Mono", Consolas, monospace; font-size: 10px; color: var(--muted); letter-spacing: 0.04em; text-transform: uppercase; }
.kpi .value { font-family: "JetBrains Mono", Consolas, monospace; font-size: 18px; margin-top: 4px; font-weight: 700; }
.kpi .sub { font-family: "JetBrains Mono", Consolas, monospace; font-size: 11px; color: var(--muted); margin-top: 2px; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--muted); }
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 0 18px 10px;
}
.tabs button {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
  padding: 7px 10px;
  border: 1px solid var(--rule);
  background: var(--chip);
  color: var(--ink);
  cursor: pointer;
}
.tabs button.active { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.panel { display: none; padding: 0 18px 28px; }
.panel.active { display: block; }
.board {
  background: var(--card);
  border: 1px solid var(--rule);
  padding: 12px;
  margin-bottom: 12px;
}
.board h2 { margin: 0 0 8px; font-size: 15px; letter-spacing: 0.04em; }
.board .hint { margin: 0 0 10px; font-size: 12px; color: var(--muted); }
.tickers { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.tickers button {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 10px;
  padding: 3px 6px;
  border: 1px solid var(--rule);
  background: var(--paper);
  color: var(--ink);
  cursor: pointer;
}
.tickers button.active { background: var(--ink); color: var(--paper); }
.wrap { position: relative; }
.chart { height: 420px; border: 1px solid var(--rule); background: var(--chart-bg); }
.chart.small { height: 260px; }
#lower { height: 150px; margin-top: 8px; border: 1px solid var(--rule); background: var(--chart-bg); }
#tip {
  display: none; position: absolute; z-index: 5; max-width: 340px;
  background: var(--card); border: 1px solid var(--rule); padding: 8px 10px;
  font-size: 13px; line-height: 1.35; pointer-events: none;
}
#tip .meta, .meta { font-family: "JetBrains Mono", Consolas, monospace; font-size: 11px; color: var(--muted); }
table.grid {
  width: 100%;
  border-collapse: collapse;
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 11px;
}
table.grid th, table.grid td {
  border-bottom: 1px solid var(--rule);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
table.grid th { color: var(--muted); font-weight: 600; }
table.grid td.num, table.grid th.num { text-align: right; }
tr.spike { background: rgba(166, 38, 38, 0.10); }
tr.rs-strong { box-shadow: inset 3px 0 0 var(--up); }
tr.anomaly { background: rgba(138, 90, 18, 0.12); }
.loops { display: grid; gap: 8px; }
.loop {
  border: 1px solid var(--rule);
  padding: 8px 10px;
  background: var(--paper);
}
.loop .meta { margin-bottom: 4px; }
.frac {
  display: inline-block;
  min-width: 72px;
  padding: 2px 6px;
  border: 1px solid var(--rule);
  text-align: center;
}
.scroll { overflow: auto; max-height: 520px; }
footer { padding: 0 18px 24px; font-size: 11px; color: var(--muted); }
@media (max-width: 720px) {
  .chart { height: 320px; }
  header.app { flex-direction: column; }
}
</style>
</head>
<body>
<header class="app">
  <div>
    <h1>Market Terminal · Millimeter Gann</h1>
    <p class="note">Единый срез из <span class="mono">data/</span> и <span class="mono">reports/</span>. Свечи, КБД, P/S, дроби и альманах на одной миллиметровке. Не совет.</p>
  </div>
  <button type="button" id="themeToggle" title="Переключить тему">Миллиметровка Ганна</button>
</header>

<section class="kpi" id="kpi"></section>
<nav class="tabs" id="tabs">
  <button type="button" data-tab="candles" class="active">1. Свечи и Нарративы</button>
  <button type="button" data-tab="ofz">2. ОФЗ и КБД</button>
  <button type="button" data-tab="ps">3. P/S Скринер</button>
  <button type="button" data-tab="fractions">4. Дроби и Сектора</button>
  <button type="button" data-tab="almanac">5. Сводка Альманаха</button>
</nav>

<section class="panel active" id="tab-candles">
  <div class="board">
    <h2>Свечи и события</h2>
    <p class="hint">TradingView Lightweight Charts. Флажки — строки <span class="mono">radar_events.csv</span>. У индекса без OHLC — линия по close.</p>
    <div class="tickers" id="tickers"></div>
    <div class="wrap">
      <div class="chart" id="price"></div>
      <div id="tip"></div>
    </div>
    <div id="lower"></div>
    <div id="eventList"></div>
  </div>
  <div class="board">
    <h2>Петли рефлексивности Сороса</h2>
    <p class="hint">Активные петли из последнего файла <span class="mono">data/narrative/</span>.</p>
    <div class="loops" id="loops"></div>
  </div>
</section>

<section class="panel" id="tab-ofz">
  <div class="board">
    <h2>Кривая бескупонной доходности (КБД)</h2>
    <p class="hint" id="curveHint">Точки 1 / 2 / 5 / 10 / 15 лет.</p>
    <div class="chart small" id="curveChart"></div>
  </div>
  <div class="board">
    <h2>Покупки вторника и аномалии корпоратов</h2>
    <p class="hint">Снимок <span class="mono">data/bonds_tuesday_latest.csv</span>.</p>
    <div class="scroll"><table class="grid" id="bondsTable"></table></div>
  </div>
</section>

<section class="panel" id="tab-ps">
  <div class="board">
    <h2>Накопленный P/S IMOEX</h2>
    <p class="hint">Ряд из <span class="mono">almanac_ps_history.md</span>.</p>
    <div class="chart small" id="psChart"></div>
  </div>
  <div class="board">
    <h2>P/S скринер и потоки</h2>
    <p class="hint">Таблица <span class="mono">data/ps_screener_latest.csv</span>. Подсветка: Volume Spike ≥ 1.8× и RS к IMOEX.</p>
    <div class="scroll"><table class="grid" id="psTable"></table></div>
  </div>
</section>

<section class="panel" id="tab-fractions">
  <div class="board">
    <h2>Межрыночные дроби · 5 и 20 сессий</h2>
    <p class="hint">Направление по закрытиям из <span class="mono">indices_daily</span> / снимок <span class="mono">macro_ofz_latest.md</span>.</p>
    <div class="scroll"><table class="grid" id="fracTable"></table></div>
  </div>
  <div class="board">
    <h2>Рейтинг отраслей по избытку к IMOEX</h2>
    <div class="scroll"><table class="grid" id="sectorTable"></table></div>
  </div>
</section>

<section class="panel" id="tab-almanac">
  <div class="board">
    <h2>Альманах · Было / Стало</h2>
    <p class="hint" id="diffHint">Сравнение из <span class="mono">almanac/DIFF_*.md</span>.</p>
    <div class="scroll"><table class="grid" id="diffTable"></table></div>
  </div>
</section>

<footer id="foot"></footer>

<script>
const DATA = __DATA__;
const themeBtn = document.getElementById("themeToggle");
const root = document.documentElement;

function themeLabel() {
  return root.getAttribute("data-theme") === "dark" ? "Тёмный терминал" : "Миллиметровка Ганна";
}
themeBtn.textContent = themeLabel();
themeBtn.addEventListener("click", () => {
  const next = root.getAttribute("data-theme") === "dark" ? "gann" : "dark";
  root.setAttribute("data-theme", next);
  themeBtn.textContent = themeLabel();
  applyChartTheme();
  if (currentTicker) showTicker(currentTicker);
  drawCurve();
  drawPs();
});

function clsPct(v) {
  if (v == null || Number.isNaN(v)) return "flat";
  if (v > 0) return "up";
  if (v < 0) return "down";
  return "flat";
}
function fmt(v, d=2) {
  if (v == null || Number.isNaN(v)) return "нет";
  return Number(v).toFixed(d);
}
function fmtPct(v, d=2) {
  if (v == null || Number.isNaN(v)) return "нет";
  const sign = v > 0 ? "+" : "";
  return sign + Number(v).toFixed(d) + "%";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function renderKpi() {
  const k = DATA.kpi;
  const cards = [
    ["IMOEX", fmt(k.imoex.value, 2), `${fmtPct(k.imoex.day_pct)} · ${k.imoex.date || "нет"}`, clsPct(k.imoex.day_pct)],
    ["RGBITR", fmt(k.rgbitr.value, 2), `${fmtPct(k.rgbitr.day_pct)} · ${k.rgbitr.date || "нет"}`, clsPct(k.rgbitr.day_pct)],
    ["КБД 10Y", fmt(k.ofz10.value, 2) + "%", `спред 10−2: ${fmt(k.ofz10.spread_10_2, 2)} п.п. · ${k.ofz10.date || "нет"}`, "flat"],
    ["P/S IMOEX", fmt(k.ps.value, 5), `коридор ${fmt(k.ps.min, 5)}–${fmt(k.ps.max, 5)} · ${k.ps.date || "нет"}`, "flat"],
    ["RVI", fmt(k.rvi.value, 2), `страх · ${k.rvi.as_of || "нет"}`, "flat"],
    ["CNY/RUB", fmt(k.cnyrub.value, 4), `${k.cnyrub.as_of || "нет"}`, "flat"],
    ["Обновлено", k.updated_at || "нет", "локальная сборка", "flat"],
  ];
  document.getElementById("kpi").innerHTML = cards.map(([label, value, sub, tone]) => (
    `<article class="card"><div class="label">${esc(label)}</div><div class="value ${tone}">${esc(value)}</div><div class="sub">${esc(sub)}</div></article>`
  )).join("");
}

document.getElementById("tabs").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-tab]");
  if (!btn) return;
  const id = btn.getAttribute("data-tab");
  document.querySelectorAll(".tabs button").forEach((el) => el.classList.toggle("active", el === btn));
  document.querySelectorAll(".panel").forEach((el) => el.classList.toggle("active", el.id === "tab-" + id));
  if (id === "ofz") drawCurve();
  if (id === "ps") drawPs();
  if (id === "candles" && currentTicker) {
    requestAnimationFrame(() => {
      priceChart.applyOptions({ width: priceEl.clientWidth });
      lowerChart.applyOptions({ width: lowerEl.clientWidth });
    });
  }
});

function chartBase(height) {
  return {
    height,
    layout: { background: { color: getComputedStyle(root).getPropertyValue("--chart-bg").trim() || "#FCF8E3" }, textColor: getComputedStyle(root).getPropertyValue("--chart-text").trim() || "#1C1915", fontSize: 11, fontFamily: "JetBrains Mono, Consolas, monospace" },
    grid: {
      vertLines: { color: getComputedStyle(root).getPropertyValue("--chart-grid").trim() || "rgba(160,125,58,0.35)" },
      horzLines: { color: getComputedStyle(root).getPropertyValue("--chart-grid").trim() || "rgba(160,125,58,0.35)" },
    },
    rightPriceScale: { borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856" },
    timeScale: { borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856" },
    crosshair: { mode: 0 },
  };
}

const priceEl = document.getElementById("price");
const lowerEl = document.getElementById("lower");
const tipEl = document.getElementById("tip");
const listEl = document.getElementById("eventList");
const buttonRow = document.getElementById("tickers");
let priceChart = LightweightCharts.createChart(priceEl, chartBase(420));
let lowerChart = LightweightCharts.createChart(lowerEl, Object.assign(chartBase(150), { height: 150 }));
const candleOptions = () => ({
  upColor: getComputedStyle(root).getPropertyValue("--up").trim(),
  downColor: getComputedStyle(root).getPropertyValue("--down").trim(),
  borderUpColor: getComputedStyle(root).getPropertyValue("--up").trim(),
  borderDownColor: getComputedStyle(root).getPropertyValue("--down").trim(),
  wickUpColor: getComputedStyle(root).getPropertyValue("--up").trim(),
  wickDownColor: getComputedStyle(root).getPropertyValue("--down").trim(),
});
let priceSeries = priceChart.addCandlestickSeries(candleOptions());
let priceKind = "candle";
const heat = lowerChart.addHistogramSeries({
  priceScaleId: "heat",
  priceFormat: { type: "price", precision: 0, minMove: 1 },
  base: 0,
  autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 5 } }),
});
const tone = lowerChart.addLineSeries({
  priceScaleId: "left",
  color: getComputedStyle(root).getPropertyValue("--blue").trim(),
  lineWidth: 2,
  priceFormat: { type: "price", precision: 0, minMove: 1 },
  autoscaleInfoProvider: () => ({ priceRange: { minValue: -5, maxValue: 5 } }),
});
const axis = lowerChart.addLineSeries({
  priceScaleId: "axis",
  color: "rgba(0,0,0,0)",
  lineWidth: 1,
  lastValueVisible: false,
  priceLineVisible: false,
  crosshairMarkerVisible: false,
});
lowerChart.priceScale("heat").applyOptions({ scaleMargins: { top: 0.12, bottom: 0.12 } });
lowerChart.priceScale("left").applyOptions({ visible: true, scaleMargins: { top: 0.12, bottom: 0.12 } });
lowerChart.priceScale("axis").applyOptions({ visible: false, autoScale: false });

let syncing = false;
priceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
  if (syncing || !range) return;
  syncing = true;
  try { lowerChart.timeScale().setVisibleRange(range); } catch (e) {}
  syncing = false;
});

const candleData = DATA.candles || { tickers: [], bars: {}, events: [] };
let currentTicker = candleData.tickers[0] || "";
const buttons = {};
candleData.tickers.forEach((ticker) => {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = ticker;
  button.addEventListener("click", () => showTicker(ticker));
  buttonRow.appendChild(button);
  buttons[ticker] = button;
});

function eventsOf(ticker) {
  return (candleData.events || []).filter((row) => row.ticker === ticker);
}
function dayPanel(rows) {
  const byDay = new Map();
  rows.forEach((row) => {
    const prev = byDay.get(row.date);
    if (!prev || row.heat > prev.heat) byDay.set(row.date, row);
  });
  return Array.from(byDay.values()).sort((a, b) => a.date.localeCompare(b.date));
}
function markerColor(toneValue) {
  if (toneValue > 0) return getComputedStyle(root).getPropertyValue("--up").trim();
  if (toneValue < 0) return getComputedStyle(root).getPropertyValue("--down").trim();
  return getComputedStyle(root).getPropertyValue("--muted").trim();
}

function showTicker(ticker) {
  currentTicker = ticker;
  Object.entries(buttons).forEach(([name, button]) => button.classList.toggle("active", name === ticker));
  const bars = candleData.bars[ticker] || [];
  const rows = eventsOf(ticker);
  const barDays = new Set(bars.map((bar) => bar.time));
  const markers = rows.filter((row) => barDays.has(row.date)).map((row) => ({
    time: row.date,
    position: row.tone < 0 ? "aboveBar" : "belowBar",
    color: markerColor(row.tone),
    shape: row.tone < 0 ? "arrowDown" : "circle",
    text: row.short_label,
  }));
  const ranged = bars.some((bar) => bar.high !== bar.low || bar.open !== bar.close);
  const kind = ranged ? "candle" : "line";
  if (kind !== priceKind) {
    priceChart.removeSeries(priceSeries);
    priceSeries = kind === "candle"
      ? priceChart.addCandlestickSeries(candleOptions())
      : priceChart.addLineSeries({ color: getComputedStyle(root).getPropertyValue("--ink").trim(), lineWidth: 2 });
    priceKind = kind;
  } else if (kind === "candle") {
    priceSeries.applyOptions(candleOptions());
  }
  priceSeries.setData(kind === "candle" ? bars : bars.map((bar) => ({ time: bar.time, value: bar.close })));
  priceSeries.setMarkers(markers);
  const panel = dayPanel(rows);
  heat.setData(panel.map((row) => ({
    time: row.date,
    value: row.heat,
    color: row.heat >= 4 ? getComputedStyle(root).getPropertyValue("--down").trim() : getComputedStyle(root).getPropertyValue("--warn").trim(),
  })));
  tone.applyOptions({ color: getComputedStyle(root).getPropertyValue("--blue").trim() });
  tone.setData(panel.map((row) => ({ time: row.date, value: row.tone })));
  axis.setData((bars.length ? bars.map((bar) => bar.time) : ["2026-11-01","2026-11-25"]).map((time) => ({ time, value: 0 })));
  const focus = () => {
    syncing = true;
    if (bars.length) {
      const i0 = bars.findIndex((item) => item.time >= "2026-10-01");
      const logical = { from: i0 < 0 ? 0 : i0, to: bars.length + 5 };
      priceChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
      lowerChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
      priceChart.timeScale().setVisibleLogicalRange(logical);
      lowerChart.timeScale().setVisibleLogicalRange(logical);
    } else {
      lowerChart.timeScale().fitContent();
    }
    syncing = false;
  };
  focus();
  requestAnimationFrame(focus);
  listEl.innerHTML = `<h2 style="font-size:14px;margin:12px 0 6px">${esc(ticker)}</h2>` + rows.map((row) => (
    `<article style="border-top:1px solid var(--rule);padding:6px 0"><div class="meta">${esc(row.date)} ${esc(row.time_msk)} МСК · жар ${esc(row.heat)} · тон ${esc(row.tone)} · ${esc(row.category)} · ${esc(row.source_channel)}</div><div>${esc(row.thesis)}</div></article>`
  )).join("") || `<p class="hint">Событий нет.</p>`;
}

priceChart.subscribeCrosshairMove((event) => {
  if (!event.time || !event.point) { tipEl.style.display = "none"; return; }
  const day = typeof event.time === "string" ? event.time : "";
  const rows = eventsOf(currentTicker).filter((row) => row.date === day);
  if (!rows.length) { tipEl.style.display = "none"; return; }
  tipEl.innerHTML = rows.map((row) => (
    `<div class="meta">${esc(row.time_msk)} МСК · ${esc(row.short_label)} · жар ${esc(row.heat)} · тон ${esc(row.tone)}</div><div>${esc(row.thesis)}</div>`
  )).join("<hr>");
  tipEl.style.display = "block";
  const host = priceEl.getBoundingClientRect();
  let x = event.point.x + 12;
  let y = event.point.y + 12;
  if (x > host.width - 360) x = Math.max(8, event.point.x - 348);
  if (y > host.height - 80) y = Math.max(8, event.point.y - 72);
  tipEl.style.left = x + "px";
  tipEl.style.top = y + "px";
});

document.getElementById("loops").innerHTML = (DATA.loops || []).map((loop) => (
  `<article class="loop"><div class="meta">${esc(loop.source)}</div><div>${esc(loop.title)}</div></article>`
)).join("") || `<p class="hint">Петель в последнем narrative-файле не найдено.</p>`;

let curveChart, curveSeries, psChartObj, psSeries;
function applyChartTheme() {
  const base = chartBase(420);
  priceChart.applyOptions(base);
  lowerChart.applyOptions(Object.assign(chartBase(150), { height: 150 }));
  if (curveChart) curveChart.applyOptions(chartBase(260));
  if (psChartObj) psChartObj.applyOptions(chartBase(260));
}
function drawCurve() {
  const el = document.getElementById("curveChart");
  const points = (DATA.curve.points || []).filter((p) => p.ytm != null);
  const tenorTimes = {
    "1Y": "2020-01-01",
    "2Y": "2020-02-01",
    "5Y": "2020-05-01",
    "10Y": "2020-10-01",
    "15Y": "2021-03-01",
  };
  const timeToTenor = Object.fromEntries(Object.entries(tenorTimes).map(([k, v]) => [v, k]));
  const base = Object.assign(chartBase(260), {
    timeScale: {
      borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856",
      tickMarkFormatter: (time) => {
        const key = typeof time === "string" ? time : "";
        return timeToTenor[key] || "";
      },
    },
    localization: {
      locale: "ru-RU",
      timeFormatter: (time) => timeToTenor[typeof time === "string" ? time : ""] || "",
    },
  });
  if (!curveChart) {
    curveChart = LightweightCharts.createChart(el, base);
    curveSeries = curveChart.addLineSeries({
      color: getComputedStyle(root).getPropertyValue("--blue").trim(),
      lineWidth: 3,
      pointMarkersVisible: true,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
  } else {
    curveChart.applyOptions(base);
    curveSeries.applyOptions({ color: getComputedStyle(root).getPropertyValue("--blue").trim() });
  }
  document.getElementById("curveHint").textContent = `Срез ${DATA.curve.date || "нет"} · точки 1/2/5/10/15 лет.`;
  curveSeries.setData(points.map((p) => ({ time: tenorTimes[p.tenor] || p.tenor, value: p.ytm })));
  curveChart.timeScale().fitContent();
  let legend = document.getElementById("curveLegend");
  if (!legend) {
    legend = document.createElement("div");
    legend.id = "curveLegend";
    legend.className = "meta";
    legend.style.marginTop = "8px";
    el.parentElement.appendChild(legend);
  }
  legend.textContent = points.map((p) => `${p.tenor}: ${fmt(p.ytm, 2)}%`).join("   ·   ");
}
function drawPs() {
  const el = document.getElementById("psChart");
  if (!psChartObj) {
    psChartObj = LightweightCharts.createChart(el, chartBase(260));
    psSeries = psChartObj.addAreaSeries({
      lineColor: getComputedStyle(root).getPropertyValue("--blue").trim(),
      topColor: "rgba(29, 62, 110, 0.28)",
      bottomColor: "rgba(29, 62, 110, 0.02)",
      lineWidth: 2,
    });
  } else {
    psChartObj.applyOptions(chartBase(260));
    psSeries.applyOptions({ lineColor: getComputedStyle(root).getPropertyValue("--blue").trim() });
  }
  const rows = (DATA.ps_history || []).filter((r) => r.ps != null);
  psSeries.setData(rows.map((r) => ({ time: r.date, value: r.ps })));
  psChartObj.timeScale().fitContent();
}

function renderBonds() {
  const rows = DATA.bonds || [];
  const head = `<tr><th>Статус</th><th>Бумага</th><th>Эмитент</th><th>Рейтинг</th><th class="num">YTM</th><th class="num">Dur</th><th class="num">G, б.п.</th><th class="num">Цена</th><th>Причина / аномалия</th></tr>`;
  const body = rows.map((row) => {
    const cls = row.anomaly ? "anomaly" : "";
    return `<tr class="${cls}"><td>${esc(row.status)}</td><td>${esc(row.shortname || row.secid)}</td><td>${esc(row.issuer)}</td><td>${esc(row.rating)}</td><td class="num">${fmt(row.ytm, 2)}</td><td class="num">${fmt(row.duration_years, 2)}</td><td class="num">${fmt(row.g_spread_bp, 1)}</td><td class="num">${fmt(row.price_pct, 2)}</td><td>${esc(row.reason)}${row.anomaly ? " · " + esc(row.anomaly) : ""}</td></tr>`;
  }).join("");
  document.getElementById("bondsTable").innerHTML = head + (body || `<tr><td colspan="9">Нет строк в bonds_tuesday_latest.csv</td></tr>`);
}

function renderPsTable() {
  const rows = DATA.ps_screener || [];
  const head = `<tr><th>Эмитент</th><th>Тикер</th><th class="num">Вес %</th><th class="num">P/S</th><th class="num">ΔP/S</th><th class="num">Vol spike</th><th class="num">RS IMOEX 20с</th><th>Окно</th></tr>`;
  const body = rows.map((row) => {
    const spike = row.volume_spike != null && row.volume_spike >= 1.8;
    const strong = row.rs_imoex_20 != null && row.rs_imoex_20 > 0;
    const cls = [spike ? "spike" : "", strong ? "rs-strong" : ""].filter(Boolean).join(" ");
    return `<tr class="${cls}"><td>${esc(row.issuer)}</td><td>${esc(row.tickers || row.ticker)}</td><td class="num">${fmt(row.weight_pct, 2)}</td><td class="num">${fmt(row.ps, 3)}</td><td class="num ${clsPct(row.delta_ps)}">${fmt(row.delta_ps, 4)}</td><td class="num">${fmt(row.volume_spike, 2)}</td><td class="num ${clsPct(row.rs_imoex_20)}">${fmt(row.rs_imoex_20, 2)}</td><td>${esc(row.window)}</td></tr>`;
  }).join("");
  document.getElementById("psTable").innerHTML = head + (body || `<tr><td colspan="8">Нет строк скринера</td></tr>`);
}

function renderFractions() {
  const rows = DATA.fractions || [];
  const head = `<tr><th>Дробь</th><th>5 сессий</th><th>20 сессий</th><th class="num">5с %</th><th class="num">20с %</th></tr>`;
  const body = rows.map((row) => (
    `<tr><td>${esc(row.label)}</td><td><span class="frac ${clsPct(row.ret5)}">${esc(row.dir5)}</span></td><td><span class="frac ${clsPct(row.ret20)}">${esc(row.dir20)}</span></td><td class="num ${clsPct(row.ret5)}">${fmt(row.ret5, 2)}</td><td class="num ${clsPct(row.ret20)}">${fmt(row.ret20, 2)}</td></tr>`
  )).join("");
  document.getElementById("fracTable").innerHTML = head + body;
  const sectors = DATA.sectors || [];
  const shead = `<tr><th>#</th><th>Отрасль</th><th>Индекс</th><th class="num">Close</th><th class="num">День %</th><th class="num">Избыток к IMOEX</th></tr>`;
  const sbody = sectors.map((row, i) => (
    `<tr><td>${i + 1}</td><td>${esc(row.title)}</td><td>${esc(row.code)}</td><td class="num">${fmt(row.close, 2)}</td><td class="num ${clsPct(row.day_pct)}">${fmtPct(row.day_pct)}</td><td class="num ${clsPct(row.excess)}">${fmt(row.excess, 2)}</td></tr>`
  )).join("");
  document.getElementById("sectorTable").innerHTML = shead + sbody;
}

function renderDiff() {
  const diff = DATA.almanac_diff || { file: "", rows: [] };
  document.getElementById("diffHint").textContent = `Файл ${diff.file || "нет"}`;
  const head = `<tr><th>Метрика</th><th>Было</th><th>Стало</th><th>Дельта</th></tr>`;
  const body = (diff.rows || []).map((row) => (
    `<tr><td>${esc(row.metric)}</td><td>${esc(row.was)}</td><td>${esc(row.became)}</td><td>${esc(row.delta)}</td></tr>`
  )).join("");
  document.getElementById("diffTable").innerHTML = head + (body || `<tr><td colspan="4">DIFF не найден</td></tr>`);
}

renderKpi();
renderBonds();
renderPsTable();
renderFractions();
renderDiff();
document.getElementById("foot").textContent = DATA.disclaimer || "";
if (currentTicker) showTicker(currentTicker);
window.addEventListener("resize", () => {
  priceChart.applyOptions({ width: priceEl.clientWidth });
  lowerChart.applyOptions({ width: lowerEl.clientWidth });
  if (curveChart) curveChart.applyOptions({ width: document.getElementById("curveChart").clientWidth });
  if (psChartObj) psChartObj.applyOptions({ width: document.getElementById("psChart").clientWidth });
});
priceChart.applyOptions({ width: priceEl.clientWidth });
lowerChart.applyOptions({ width: lowerEl.clientWidth });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
