"""Сборка clean/ и derived/ только из raw и справочников. Пропуски не заполняются."""

from __future__ import annotations

import gzip
import json
from datetime import date

from scripts.common import CLEAN, DERIVED, RAW, REFERENCE, fetched_at_for, load_thresholds, read_csv, write_csv, write_json
from scripts.formulas import (
    BANKS_NO_PS,
    adj_factor_on,
    composite_mean,
    flow_share,
    instant_step,
    is_num,
    monetary_soft,
    monthly_return_pct,
    nsi_monthly,
    ofz_repricing,
    percentile_own,
    rate_change_pp,
    seasonality,
    solar_weight_sum,
    ssn_smooth_v1,
    stop_cap,
    top_abs_months,
    total_return_pct,
    valuation,
    weak_windows,
    weather_anomaly,
    yoy_change,
    zigzag_episodes,
    rolling_rai,
    global_drawdowns,
    weekday_stats,
    month_part_stats,
    beta_from_returns,
    pearson,
    rai_streak_above,
)
from scripts.parse_sources import (
    gfz_monthly,
    key_rate_events,
    parse_cbr_fx_xml,
    parse_cbr_keyrate_html,
    parse_cbr_metals,
    parse_fred_brent,
    parse_gfz_daily,
    parse_iss_history,
    parse_meteostat_daily,
    parse_noaa_solar,
    parse_silso_csv,
    parse_smartlab_html,
    weather_monthly,
)

SECTORS = [
    "Нефтегаз",
    "Металлургия и добыча",
    "Банки и финансы",
    "IT и телеком",
    "Энергетика",
    "Химия и удобрения",
    "Потребительский",
    "Транспорт и машиностроение",
    "Строительство и лес",
]
RAI_INDEXES = [
    "IMOEX",
    "IMOEX2",
    "MOEX10",
    "MOEXOG",
    "MOEXMM",
    "MOEXFN",
    "MOEXCN",
    "MOEXEU",
    "MOEXTL",
    "MOEXCH",
    "MOEXTN",
    "MOEXINN",
]
REGIMES = [
    ("R1", "2023-07", "2024-10", "7.5→21"),
    ("R2", "2024-11", "2025-05", "21"),
    ("R3a", "2022-10", "2023-06", "7.5"),
    ("R3b", "2026-08", "2026-11", "14, продолжается"),
    ("R4a", "2022-03", "2022-09", "20→7.5"),
    ("R4b", "2025-06", "2026-07", "20→14"),
]


def _latest_files(folder, pattern):
    return sorted(folder.glob(pattern))


def _load_keyrate():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "cbr", "keyrate_*.html"):
        parsed = parse_cbr_keyrate_html(path.read_text(encoding="utf-8", errors="replace"))
        rows.extend(parsed)
        stamps.append(fetched_at_for(path))
    dedup = {row["date"]: row for row in rows}
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _load_usd():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "cbr", "usdrub_*.xml"):
        rows.extend(parse_cbr_fx_xml(path.read_bytes()))
        stamps.append(fetched_at_for(path))
    dedup = {row["date"]: row for row in rows}
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _load_brent():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "fred", "brent_*.csv"):
        rows.extend(parse_fred_brent(path.read_text(encoding="utf-8", errors="replace")))
        stamps.append(fetched_at_for(path))
    dedup = {}
    for row in rows:
        if row["brent"] is None:
            continue
        dedup[row["date"]] = row
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _load_solar():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "solar", "noaa_*.json"):
        rows.extend(parse_noaa_solar(json.loads(path.read_text(encoding="utf-8"))))
        stamps.append(fetched_at_for(path))
    dedup = {row["month"]: row for row in rows}
    for path in _latest_files(RAW / "solar", "silso_m_*.csv"):
        for row in parse_silso_csv(path.read_text(encoding="utf-8", errors="replace"), "ssn"):
            if row["ssn"] is None:
                continue
            dedup.setdefault(row["month"], {"month": row["month"]})["ssn"] = row["ssn"]
        stamps.append(fetched_at_for(path))
    for path in _latest_files(RAW / "solar", "silso_ms_*.csv"):
        for row in parse_silso_csv(path.read_text(encoding="utf-8", errors="replace"), "ssn_smooth13"):
            if row["ssn_smooth13"] is None:
                continue
            dedup.setdefault(row["month"], {"month": row["month"]})["ssn_smooth13"] = row["ssn_smooth13"]
        stamps.append(fetched_at_for(path))
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _load_metals():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "cbr", "metals_*.xml"):
        rows.extend(parse_cbr_metals(path.read_bytes()))
        stamps.append(fetched_at_for(path))
    dedup = {}
    for row in rows:
        dedup.setdefault(row["date"], {}).update(row)
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _load_gfz():
    rows = []
    stamps = []
    for path in _latest_files(RAW / "solar", "gfz_*.txt"):
        rows.extend(gfz_monthly(parse_gfz_daily(path.read_text(encoding="utf-8", errors="replace"))))
        stamps.append(fetched_at_for(path))
    dedup = {row["month"]: row for row in rows}
    return [dedup[key] for key in sorted(dedup)], _latest(stamps)


def _latest(stamps):
    values = [item for item in stamps if item]
    return max(values) if values else ""


def _month_of(stamp: str) -> str:
    return stamp[:7]


def _last_full_month(today: date) -> str:
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def _calendar_months(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[5:7])
    last_y, last_m = int(end[:4]), int(end[5:7])
    out = []
    while (year, month) <= (last_y, last_m):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def build_macro(today: date):
    rates, rate_stamp = _load_keyrate()
    usd, usd_stamp = _load_usd()
    brent, brent_stamp = _load_brent()
    solar, solar_stamp = _load_solar()
    metals, metal_stamp = _load_metals()
    gfz, gfz_stamp = _load_gfz()
    by_month: dict[str, dict] = {}

    def bucket(month):
        return by_month.setdefault(month, {})

    for row in usd:
        bucket(_month_of(row["date"]))["usdrub"] = row["usdrub"]
    month_brent: dict[str, list[float]] = {}
    for row in brent:
        month_brent.setdefault(_month_of(row["date"]), []).append(row["brent"])
    for month, values in month_brent.items():
        cell = bucket(month)
        cell["brent_last"] = values[-1]
        cell["brent_avg"] = sum(values) / len(values)
    for row in rates:
        bucket(_month_of(row["date"]))["key_rate"] = row["rate"]
    for row in metals:
        cell = bucket(_month_of(row["date"]))
        for field in ("gold", "silver", "platinum", "palladium"):
            if row.get(field) is not None:
                cell[field] = row[field]
    for row in gfz:
        cell = bucket(row["month"])
        for field in ("ap", "kpmax", "sn_gfz"):
            if row.get(field) is not None:
                cell[field] = row[field]
        if cell.get("f107") is None and row.get("f107") is not None:
            cell["f107"] = row["f107"]
    ssn_series = [row for row in solar if row["month"] >= "2015-01"]
    smooth_input = [row["ssn"] for row in ssn_series]
    smoothed = ssn_smooth_v1(smooth_input)
    for row, smooth in zip(ssn_series, smoothed):
        cell = bucket(row["month"])
        cell["ssn"] = row["ssn"]
        cell["ssn_smooth13"] = row["ssn_smooth13"]
        cell["ssn_smooth_v1"] = smooth
        cell["f107"] = row["f107"]
    columns = [
        "month",
        "usdrub",
        "brent_last",
        "brent_avg",
        "key_rate",
        "gold",
        "silver",
        "platinum",
        "palladium",
        "ssn",
        "ssn_smooth13",
        "ssn_smooth_v1",
        "f107",
        "ap",
        "kpmax",
        "sn_gfz",
        "source",
        "fetched_at",
        "n_obs",
    ]
    rows = []
    for month in sorted(by_month):
        cell = by_month[month]
        sources = []
        if any(cell.get(key) is not None for key in ("usdrub", "key_rate", "gold", "silver", "platinum", "palladium")):
            sources.append("S2")
        if cell.get("brent_last") is not None:
            sources.append("S3")
        if any(cell.get(key) is not None for key in ("ssn", "f107", "ap", "kpmax", "sn_gfz")):
            sources.append("S5")
        filled = sum(1 for key in columns if key not in ("month", "source", "fetched_at", "n_obs") and cell.get(key) is not None)
        rows.append(
            {
                "month": month,
                **cell,
                "source": "+".join(sources),
                "fetched_at": _latest([rate_stamp, usd_stamp, brent_stamp, solar_stamp, metal_stamp, gfz_stamp]),
                "n_obs": filled,
            }
        )
    write_csv(CLEAN / "macro_monthly.csv", columns, rows)
    events = key_rate_events(rates)
    write_csv(
        CLEAN / "key_rate_events.csv",
        ["date", "rate_old", "rate_new", "decision", "source_url"],
        events,
    )
    return {"rates": rates, "macro": rows, "events": events, "solar_weight_sum": solar_weight_sum()}


def build_weather():
    rows = []
    for path in sorted((RAW / "weather").glob("meteostat_*.csv.gz")):
        station = path.name.split("_")[1]
        text = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
        fetched = fetched_at_for(path)
        for row in weather_monthly(parse_meteostat_daily(text)):
            rows.append(
                {
                    "month": row["month"],
                    "city_id": station,
                    "tmean": row["tmean"],
                    "anomaly_vs_1991_2020": "",
                    "source": "S6",
                    "fetched_at": fetched,
                    "n_obs": row["n_obs"],
                }
            )
    write_csv(
        CLEAN / "weather_monthly.csv",
        ["month", "city_id", "tmean", "anomaly_vs_1991_2020", "source", "fetched_at", "n_obs"],
        rows,
    )
    return rows


def build_fundamentals():
    parsed = []
    for path in sorted((RAW / "fundamentals").glob("smartlab_*.html")):
        if path.name.startswith("smartlab_table"):
            continue
        bits = path.name[:-5].split("_")
        if len(bits) < 5:
            continue
        ticker, label, kind = bits[1], bits[2], bits[3]
        for row in parse_smartlab_html(path.read_text(encoding="utf-8", errors="replace"), label):
            if row["period_end"] < "2019-01-01":
                continue
            filled = sum(1 for key in ("revenue", "ebitda", "net_income", "net_debt", "equity") if is_num(row.get(key)))
            parsed.append(
                {
                    "ticker": ticker,
                    "period_end": row["period_end"],
                    "report_type": row["report_type"],
                    "revenue": row["revenue"],
                    "net_income": row["net_income"],
                    "ebitda": row["ebitda"],
                    "net_debt": row["net_debt"],
                    "equity": row["equity"],
                    "shares_out": "",
                    "reported_at": row["reported_at"],
                    "source": "S7",
                    "fetched_at": fetched_at_for(path),
                    "ltm": "annual" if kind == "y" else "",
                    "_filled": filled,
                    "_kind": kind,
                }
            )
    best = {}
    for row in parsed:
        key = (row["ticker"], row["period_end"], row["report_type"])
        current = best.get(key)
        if current is None or (row["_kind"] == "q" and current["_kind"] != "q") or row["_filled"] > current["_filled"]:
            best[key] = row
    columns = [
        "ticker",
        "period_end",
        "report_type",
        "revenue",
        "ebitda",
        "net_income",
        "net_debt",
        "equity",
        "shares_out",
        "reported_at",
        "source",
        "fetched_at",
        "ltm",
    ]
    rows = [{key: row.get(key) for key in columns} for row in sorted(best.values(), key=lambda item: (item["ticker"], item["period_end"]))]
    write_csv(CLEAN / "fundamentals_quarterly.csv", columns, rows)
    return rows


def _active_universe():
    return [row for row in read_csv(REFERENCE / "universe.csv") if row.get("status") == "active"]


def _actions_for(ticker):
    return [row for row in read_csv(REFERENCE / "corporate_actions.csv") if row.get("ticker") == ticker]


def load_share_bars():
    """Сырые свечи ISS, если они уже лежат в raw. Сеть здесь не вызывается."""
    bars = []
    for path in sorted((RAW / "moex_iss" / "shares").glob("*_*.json")):
        if "security" in path.name:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = fetched_at_for(path)
        for row in parse_iss_history(payload):
            close = row.get("CLOSE")
            if close in (None, ""):
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            bars.append(
                {
                    "date": row.get("TRADEDATE"),
                    "ticker": row.get("SECID"),
                    "open": row.get("OPEN"),
                    "high": row.get("HIGH"),
                    "low": row.get("LOW"),
                    "close": close_f,
                    "volume_rub": row.get("VALUE"),
                    "volume": row.get("VOLUME"),
                    "source": "S1",
                    "fetched_at": fetched,
                    "session": row.get("TRADINGSESSION") or 0,
                }
            )
    return bars


def build_prices(today: date):
    columns = [
        "date",
        "ticker",
        "open",
        "high",
        "low",
        "close",
        "volume_rub",
        "adj_factor",
        "close_adj",
        "source",
        "fetched_at",
    ]
    chosen = {}
    for bar in load_share_bars():
        key = (bar["ticker"], bar["date"])
        current = chosen.get(key)
        if current is None or (bar["session"] or 0) >= (current["session"] or 0):
            chosen[key] = bar
    rows = []
    for bar in sorted(chosen.values(), key=lambda item: (item["ticker"], item["date"])):
        factor = adj_factor_on(bar["date"], _actions_for(bar["ticker"]))
        close_adj = bar["close"] / factor if factor else None
        rows.append({**bar, "adj_factor": factor, "close_adj": close_adj})
    write_csv(CLEAN / "prices_daily.csv", columns, rows)
    monthly = []
    by_ticker_month: dict[tuple[str, str], dict] = {}
    for row in rows:
        by_ticker_month[(row["ticker"], row["date"][:7])] = row
    current = today.strftime("%Y-%m")
    for (ticker, month), row in sorted(by_ticker_month.items()):
        monthly.append(
            {
                "month": month,
                "ticker": ticker,
                "close_adj": row["close_adj"],
                "source": row["source"],
                "mtd": 1 if month == current else 0,
            }
        )
    write_csv(CLEAN / "prices_monthly.csv", ["month", "ticker", "close_adj", "source", "mtd"], monthly)
    _write_indices(today)
    _write_ofz()
    _write_curve()
    _write_dividends()
    _empty(
        CLEAN / "fundamentals_quarterly.csv",
        ["ticker", "period_end", "report_type", "revenue", "ebitda", "net_income", "net_debt", "equity", "shares_out", "reported_at", "source", "fetched_at", "ltm"],
    )
    _empty(CLEAN / "weather_monthly.csv", ["month", "city_id", "tmean", "anomaly_vs_1991_2020", "source", "fetched_at", "n_obs"])
    _empty(CLEAN / "news_events.csv", ["date", "category", "event", "source", "url", "tone", "status"])
    return rows, monthly


def _num_cell(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not is_num(number):
        return None
    return number


def _write_indices(today: date):
    chosen = {}
    for path in sorted((RAW / "moex_iss" / "indices").glob("*_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = fetched_at_for(path)
        for row in parse_iss_history(payload):
            close = _num_cell(row.get("CLOSE"))
            stamp = row.get("TRADEDATE") or ""
            code = row.get("SECID") or ""
            if not stamp or not code or close is None or stamp < "2021-01-04":
                continue
            key = (code, stamp)
            current = chosen.get(key)
            session = row.get("TRADINGSESSION") or 0
            try:
                session = int(session)
            except (TypeError, ValueError):
                session = 0
            if current is None or session >= current["session"]:
                chosen[key] = {"date": stamp, "index": code, "close": close, "source": "S1", "fetched_at": fetched, "session": session}
    rows = [{key: value[key] for key in ("date", "index", "close", "source", "fetched_at")} for value in sorted(chosen.values(), key=lambda item: (item["index"], item["date"]))]
    write_csv(CLEAN / "indices_daily.csv", ["date", "index", "close", "source", "fetched_at"], rows)
    current = today.strftime("%Y-%m")
    monthly = []
    last = {}
    for row in rows:
        last[(row["index"], row["date"][:7])] = row
    for (code, month), row in sorted(last.items()):
        monthly.append({"month": month, "index": code, "close": row["close"], "mtd": 1 if month == current else 0, "source": "S1", "fetched_at": row["fetched_at"]})
    write_csv(CLEAN / "indices_monthly.csv", ["month", "index", "close", "mtd", "source", "fetched_at"], monthly)


def _write_ofz():
    chosen = {}
    for path in sorted((RAW / "moex_iss" / "bonds").glob("ofz_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = fetched_at_for(path)
        for row in parse_iss_history(payload):
            stamp = row.get("TRADEDATE") or ""
            secid = row.get("SECID") or ""
            if not stamp or not secid or stamp < "2021-01-04":
                continue
            key = (secid, stamp)
            session = row.get("TRADINGSESSION") or 0
            try:
                session = int(session)
            except (TypeError, ValueError):
                session = 0
            current = chosen.get(key)
            if current is not None and session < current["_session"]:
                continue
            chosen[key] = {
                "date": stamp,
                "secid": secid,
                "isin": row.get("ISIN") or "",
                "price_pct": _num_cell(row.get("CLOSE")),
                "ytm": _num_cell(row.get("YIELDCLOSE")),
                "duration_days": _num_cell(row.get("DURATION")),
                "coupon_rate": _num_cell(row.get("COUPONPERCENT")),
                "maturity": row.get("MATDATE") or "",
                "source": "S1",
                "fetched_at": fetched,
                "_session": session,
            }
    columns = ["date", "secid", "isin", "price_pct", "ytm", "duration_days", "coupon_rate", "maturity", "source", "fetched_at"]
    rows = [{key: value.get(key) for key in columns} for value in sorted(chosen.values(), key=lambda item: (item["date"], item["secid"]))]
    write_csv(CLEAN / "ofz_daily.csv", columns, rows)


def _write_curve():
    tenors = {0.25: None, 1.0: "t_1y", 2.0: "t_2y", 3.0: "t_3y", 5.0: "t_5y", 7.0: "t_7y", 10.0: "t_10y", 15.0: "t_15y", 20.0: "t_20y"}
    columns = ["date", "t_1y", "t_2y", "t_3y", "t_5y", "t_7y", "t_10y", "t_15y", "t_20y", "source", "fetched_at"]
    rows = []
    for path in sorted((RAW / "moex_iss" / "bonds").glob("zcyc_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        block = payload.get("yearyields") or {}
        cols = block.get("columns") or []
        record = {name: None for name in columns}
        record["source"] = "S1"
        record["fetched_at"] = fetched_at_for(path)
        for raw in block.get("data") or []:
            row = dict(zip(cols, raw))
            period = _num_cell(row.get("period"))
            value = _num_cell(row.get("value"))
            field = tenors.get(period)
            if field:
                record[field] = value
            if row.get("tradedate"):
                record["date"] = row["tradedate"]
        if record.get("date"):
            rows.append(record)
    write_csv(CLEAN / "ofz_curve_daily.csv", columns, rows)


def _write_dividends():
    rows = []
    for path in sorted((RAW / "moex_iss" / "dividends").glob("*_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = fetched_at_for(path)
        ticker = path.name.split("_")[0]
        for row in parse_iss_history(payload):
            record_date = row.get("registryclosedate") or row.get("REGISTRYCLOSEDATE") or ""
            amount = _num_cell(row.get("value") if row.get("value") is not None else row.get("VALUE"))
            if not record_date or amount is None:
                continue
            rows.append(
                {
                    "ticker": row.get("secid") or row.get("SECID") or ticker,
                    "record_date": record_date,
                    "amount_rub": amount,
                    "currency": row.get("currencyid") or row.get("CURRENCYID") or "",
                    "source": "S1",
                    "fetched_at": fetched,
                }
            )
    write_csv(CLEAN / "dividends.csv", ["ticker", "record_date", "amount_rub", "currency", "source", "fetched_at"], rows)


def _empty(path, columns):
    if not path.exists():
        write_csv(path, columns, [])


def _returns(monthly_rows):
    dividends = _dividend_amounts()
    by_ticker: dict[str, list[dict]] = {}
    for row in monthly_rows:
        if str(row.get("mtd")) == "1":
            continue
        by_ticker.setdefault(row["ticker"], []).append(row)
    out = []
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda item: item["month"])
        for prev, row in zip(rows, rows[1:]):
            try:
                previous = float(prev["close_adj"])
                current = float(row["close_adj"])
            except (TypeError, ValueError):
                continue
            ret = monthly_return_pct(previous, current)
            tr = total_return_pct(previous, current, dividends.get((ticker, row["month"]), 0.0))
            out.append({"month": row["month"], "ticker": ticker, "ret_pct": ret, "ret_tr_pct": tr, "n_obs": 2})
    return out


def build_derived(today: date, macro_rows, events):
    _, monthly = _read_prices()
    returns = _returns(monthly)
    write_csv(DERIVED / "returns_monthly.csv", ["month", "ticker", "ret_pct", "ret_tr_pct", "n_obs"], returns)
    universe = _active_universe()
    sectors = {row["ticker"]: row.get("sector", "") for row in universe}
    echelons = {row["ticker"]: row.get("echelon", "") for row in universe}
    _write_sector_returns(returns, sectors)
    _write_betas(returns, macro_rows, sectors, echelons, today)
    _write_seasonality(returns)
    _write_calendar()
    _write_rai()
    _write_nsi()
    _write_valuation()
    _write_regimes(returns)
    _write_solar(macro_rows)
    _write_weather()
    _write_echelons(returns, echelons)
    _write_extremes(returns)
    _write_yoy(macro_rows, today)
    _write_plan_flows()
    dashboard = _write_plan(today, macro_rows, events)
    return dashboard


def _read_prices():
    daily = read_csv(CLEAN / "prices_daily.csv")
    monthly = read_csv(CLEAN / "prices_monthly.csv")
    for row in read_csv(CLEAN / "indices_monthly.csv"):
        if row.get("index") == "IMOEX":
            monthly.append({"month": row["month"], "ticker": "IMOEX", "close_adj": row["close"], "source": row.get("source"), "mtd": row.get("mtd")})
    return daily, monthly


def _dividend_amounts():
    found: dict[tuple[str, str], float] = {}
    for row in read_csv(CLEAN / "dividends.csv"):
        currency = (row.get("currency") or "").upper()
        if currency not in ("", "RUB", "SUR"):
            continue
        try:
            amount = float(row["amount_rub"])
        except (TypeError, ValueError):
            continue
        stamp = row.get("record_date") or ""
        if len(stamp) < 7:
            continue
        factor = adj_factor_on(stamp, _actions_for(row.get("ticker") or ""))
        if factor:
            amount = amount / factor
        key = (row.get("ticker") or "", stamp[:7])
        found[key] = found.get(key, 0.0) + amount
    return found


def _write_sector_returns(returns, sectors):
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in returns:
        sector = sectors.get(row["ticker"])
        if not sector or not is_num(row["ret_pct"]):
            continue
        grouped.setdefault((row["month"], sector), []).append(row["ret_pct"])
    rows = []
    for (month, sector), values in sorted(grouped.items()):
        rows.append(
            {
                "month": month,
                "sector": sector,
                "ret_pct_eq": sum(values) / len(values),
                "n_tickers": len(values),
                "n_obs": len(values),
            }
        )
    write_csv(DERIVED / "sector_returns.csv", ["month", "sector", "ret_pct_eq", "n_tickers", "n_obs"], rows)


def _series_map(rows, key_field, value_field):
    found: dict[str, float] = {}
    for row in rows:
        value = row.get(value_field)
        try:
            found[row[key_field]] = float(value) if value not in ("", None) else None
        except (TypeError, ValueError):
            found[row[key_field]] = None
    return found


def _write_betas(returns, macro_rows, sectors, echelons, today):
    last_full = _last_full_month(today)
    window = [row for row in returns if "2021-01" <= row["month"] <= last_full]
    imoex = _series_map([row for row in window if row["ticker"] == "IMOEX"], "month", "ret_pct")
    months = sorted({row["month"] for row in window} | set(imoex))
    index_vals = [imoex.get(month) for month in months]
    rate = {}
    previous = None
    for row in macro_rows:
        current = row.get("key_rate")
        try:
            current_f = float(current) if current not in ("", None) else None
        except ValueError:
            current_f = None
        rate[row["month"]] = None if previous is None or current_f is None else current_f - previous
        if current_f is not None:
            previous = current_f
    rows = []
    tickers = sorted({row["ticker"] for row in window if row["ticker"] != "IMOEX"})
    for ticker in tickers:
        asset_map = _series_map([row for row in window if row["ticker"] == ticker], "month", "ret_pct")
        asset = [asset_map.get(month) for month in months]
        beta, n_obs = beta_from_returns(asset, index_vals)
        corr_imoex, _ = pearson(asset, index_vals)
        dkey = [rate.get(month) for month in months]
        corr_dkey, _ = pearson(asset, dkey)
        rows.append(
            {
                "ticker": ticker,
                "sector": sectors.get(ticker, ""),
                "echelon": echelons.get(ticker, ""),
                "beta": beta,
                "corr_imoex": corr_imoex,
                "corr_usdrub": None,
                "corr_brent": None,
                "corr_dkey": corr_dkey,
                "corr_ssn": None,
                "corr_ssn_yoy": None,
                "corr_temp": None,
                "n_obs": n_obs,
            }
        )
    write_csv(
        DERIVED / "betas_corr.csv",
        ["ticker", "sector", "echelon", "beta", "corr_imoex", "corr_usdrub", "corr_brent", "corr_dkey", "corr_ssn", "corr_ssn_yoy", "corr_temp", "n_obs"],
        rows,
    )
    _empty(DERIVED / "corr_matrix_22.csv", ["ticker", "n_obs"])
    _write_corr_sectors(months, imoex)


def _write_corr_sectors(months, imoex):
    sector_rows = read_csv(DERIVED / "sector_returns.csv")
    header = ["asset", *SECTORS, "n_obs"]
    assets = ["IMOEX", *SECTORS]
    maps = {"IMOEX": imoex}
    for asset in assets:
        if asset == "IMOEX":
            continue
        maps[asset] = _series_map([row for row in sector_rows if row["sector"] == asset], "month", "ret_pct_eq")
    rows = []
    for asset in assets:
        left = [maps[asset].get(month) for month in months]
        record = {"asset": asset}
        ns = []
        for other in SECTORS:
            corr, n_obs = pearson(left, [maps[other].get(month) for month in months])
            record[other] = corr
            ns.append(n_obs)
        record["n_obs"] = min(ns) if ns else 0
        rows.append(record)
    write_csv(DERIVED / "corr_sectors.csv", header, rows)


def _write_seasonality(returns):
    grouped: dict[str, list[tuple[str, float]]] = {}
    for row in returns:
        if is_num(row["ret_pct"]):
            grouped.setdefault(row["ticker"], []).append((row["month"], row["ret_pct"]))
    columns = (
        ["asset"]
        + [f"m{m:02d}" for m in range(1, 13)]
        + [f"hit_m{m:02d}" for m in range(1, 13)]
        + ["n_years", "sample_lt_6", "n_obs"]
        + [f"avg_ex2022_m{m:02d}" for m in range(1, 13)]
    )
    rows = []
    year_month = {}
    for asset, pairs in sorted(grouped.items()):
        stats = seasonality(pairs)
        record = {"asset": asset, "n_years": stats["n_years"], "sample_lt_6": stats["sample_lt_6"], "n_obs": stats["n_years"]}
        for index, month in enumerate(range(1, 13)):
            record[f"m{month:02d}"] = stats["avg"][index]
            record[f"hit_m{month:02d}"] = stats["hit"][index]
            record[f"avg_ex2022_m{month:02d}"] = stats["ex2022"][index]
        rows.append(record)
        if asset == "IMOEX":
            for stamp, ret in pairs:
                year_month.setdefault(stamp[:4], {})[int(stamp[5:7])] = ret
    write_csv(DERIVED / "seasonality.csv", columns, rows)
    grid = []
    for year in sorted(year_month):
        record = {"year": year, "n_obs": len(year_month[year])}
        for month in range(1, 13):
            record[f"m{month:02d}"] = year_month[year].get(month)
        grid.append(record)
    write_csv(DERIVED / "imoex_year_month.csv", ["year", *[f"m{m:02d}" for m in range(1, 13)], "n_obs"], grid)


def _write_calendar():
    daily = [row for row in read_csv(CLEAN / "indices_daily.csv") if row.get("index") == "IMOEX"]
    daily.sort(key=lambda row: row["date"])
    dates = [row["date"] for row in daily]
    closes = []
    for row in daily:
        try:
            closes.append(float(row.get("close_adj") or row.get("close")))
        except (TypeError, ValueError):
            closes.append(None)
    usable = [(d, c) for d, c in zip(dates, closes) if is_num(c)]
    write_csv(
        DERIVED / "weekday_stats.csv",
        ["weekday", "n_days", "mean_pct", "median_pct", "pct_up"],
        weekday_stats([d for d, _ in usable], [c for _, c in usable]),
    )
    write_csv(
        DERIVED / "month_parts_stats.csv",
        ["part", "n_days", "mean_daily_pct", "pct_up", "contribution_pp", "n_obs"],
        month_part_stats([d for d, _ in usable], [c for _, c in usable]),
    )


def _write_rai():
    by_index: dict[str, list[tuple[str, float]]] = {code: [] for code in RAI_INDEXES}
    for row in read_csv(CLEAN / "indices_daily.csv"):
        code = row.get("index")
        if code not in by_index:
            continue
        try:
            close = float(row["close"])
        except (TypeError, ValueError):
            continue
        by_index[code].append((row["date"], close))
    episodes = []
    daily_rows = []
    drawdowns = []
    monthly: dict[str, dict] = {}
    for code in RAI_INDEXES:
        series = sorted(by_index[code])
        if len(series) < 2:
            continue
        dates = [item[0] for item in series]
        prices = [item[1] for item in series]
        found, rai_rows, downs = rai_frame(code, dates, prices)
        episodes.extend(found)
        drawdowns.extend(downs)
        last_by_month = {}
        for stamp, value in rai_rows:
            daily_rows.append({"date": stamp, "index": code, "rai": value, "n_obs": len(prices)})
            if is_num(value):
                last_by_month[stamp[:7]] = value
        for month, value in last_by_month.items():
            monthly.setdefault(month, {"month": month, "n_obs": len(prices)})[code] = value
    episode_columns = ["index", "peak_date", "trough_date", "recovered_date", "peak_pts", "trough_pts", "depth_pct", "rebound_pct", "fall_days", "rec_days", "fall_speed", "rec_speed", "asym", "completed", "n_obs"]
    write_csv(DERIVED / "zigzag_episodes.csv", episode_columns, [{key: row.get(key) for key in episode_columns} for row in episodes])
    write_csv(DERIVED / "rai_daily.csv", ["date", "index", "rai", "n_obs"], daily_rows)
    columns = ["month", *RAI_INDEXES, "n_obs"]
    write_csv(DERIVED / "rai_monthly.csv", columns, [monthly[key] for key in sorted(monthly)])
    write_csv(
        DERIVED / "drawdowns_global.csv",
        ["index", "peak_date", "trough_date", "depth_pct", "recovery_date", "days_down", "days_up", "n_obs"],
        drawdowns,
    )


def rai_frame(index_name, dates, prices, window=126):
    episodes = zigzag_episodes(dates, prices)
    for episode in episodes:
        episode["index"] = index_name
        episode["n_obs"] = len(prices)
    rai = rolling_rai(len(prices), episodes, window=window)
    drawdowns = global_drawdowns(dates, prices)
    for row in drawdowns:
        row["index"] = index_name
        row["n_obs"] = len(prices)
    return episodes, list(zip(dates, rai)), drawdowns


def _write_nsi():
    events = []
    for row in read_csv(CLEAN / "news_events.csv"):
        try:
            tone = float(row["tone"]) if row.get("tone") not in ("", None) else None
        except ValueError:
            tone = None
        events.append({"month": (row.get("date") or "")[:7], "tone": tone, "status": row.get("status")})
    rows = nsi_monthly([event for event in events if event["month"]])
    imoex = {row["month"]: row for row in read_csv(DERIVED / "returns_monthly.csv") if row.get("ticker") == "IMOEX"}
    nsi_vals = []
    next_rets = []
    for row in rows:
        year, month = int(row["month"][:4]), int(row["month"][5:7])
        month = month + 1
        if month == 13:
            year, month = year + 1, 1
        nxt = f"{year:04d}-{month:02d}"
        ret = imoex.get(nxt, {}).get("ret_pct")
        try:
            ret_f = float(ret) if ret not in ("", None) else None
        except ValueError:
            ret_f = None
        nsi_vals.append(row["nsi"])
        next_rets.append(ret_f)
        row["imoex_close"] = None
        row["imoex_ret_pct"] = imoex.get(row["month"], {}).get("ret_pct")
    corr, n_corr = pearson(nsi_vals, next_rets)
    for row in rows:
        row["corr_next_imoex"] = corr
        row["corr_n_obs"] = n_corr
    write_csv(
        DERIVED / "nsi_monthly.csv",
        ["month", "nsi", "nsi_cum", "imoex_close", "imoex_ret_pct", "n_obs", "corr_next_imoex", "corr_n_obs"],
        rows,
    )


def _write_valuation():
    columns = [
        "date",
        "ticker",
        "price",
        "mcap_rub",
        "revenue_ltm",
        "ps",
        "pe",
        "pb",
        "ev_ebitda",
        "div_yield_pct",
        "nd_ebitda",
        "applicable_ps",
        "source_ps",
        "as_of_report",
        "ps_pctile_own_history",
        "ps_vs_sector_median",
        "n_obs",
    ]
    _empty(DERIVED / "valuation_snapshot.csv", columns)


def cross_check(ticker, own, external, kind, anomalies):
    if not is_num(own) or not is_num(external) or own == 0:
        return own
    if abs(external - own) / abs(own) > 0.15:
        anomalies.append(
            {
                "date": "",
                "series": ticker,
                "kind": kind,
                "detail": "расхождение со Smart-Lab больше 15%; в расчёте собственное значение",
                "value_a": own,
                "value_b": external,
            }
        )
    return own


def _write_regimes(returns):
    imoex = [row for row in returns if row.get("ticker") == "IMOEX"]
    rows = []
    for name, start, end, label in REGIMES:
        months = _calendar_months(start, end)
        sample = []
        for row in imoex:
            if start <= row["month"] <= end and is_num(row["ret_pct"]):
                sample.append(row["ret_pct"])
        growth = 1.0
        for value in sample:
            growth *= 1.0 + value / 100.0
        rows.append(
            {
                "window": name,
                "period": f"{start}…{end}",
                "rate": label,
                "n_months": len(months),
                "imoex_cum_pct": (growth - 1.0) * 100.0 if sample else None,
                "imoex_avg_pct": sum(sample) / len(sample) if sample else None,
                "hit_pct": 100.0 * sum(1 for value in sample if value > 0) / len(sample) if sample else None,
                "rai_avg": None,
                "nsi_sum": None,
                "n_obs": len(sample),
            }
        )
    write_csv(
        DERIVED / "regime_windows.csv",
        ["window", "period", "rate", "n_months", "imoex_cum_pct", "imoex_avg_pct", "hit_pct", "rai_avg", "nsi_sum", "n_obs"],
        rows,
    )


def _write_solar(macro_rows):
    sample = [row for row in macro_rows if row.get("ssn") not in ("", None)]
    values = []
    for row in sample:
        try:
            values.append(float(row["ssn"]))
        except (TypeError, ValueError):
            continue
    median = None
    if values:
        ordered = sorted(values)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    rows = []
    for row in sample:
        try:
            ssn = float(row["ssn"])
        except (TypeError, ValueError):
            continue
        if median is None or ssn == median:
            phase = ""
        elif ssn > median:
            phase = "above"
        else:
            phase = "below"
        rows.append(
            {
                "month": row["month"],
                "ssn": ssn,
                "ssn_smooth13": row.get("ssn_smooth13"),
                "ssn_smooth_v1": row.get("ssn_smooth_v1"),
                "phase": phase,
                "n_obs": len(values),
            }
        )
    write_csv(
        DERIVED / "solar_phases.csv",
        ["month", "ssn", "ssn_smooth13", "ssn_smooth_v1", "phase", "n_obs"],
        rows,
    )
    _empty(DERIVED / "solar_lags.csv", ["asset", "lag", "corr", "n_obs"])


def _write_weather():
    raw = read_csv(CLEAN / "weather_monthly.csv")
    normals = {}
    for row in raw:
        if not ("1991-01" <= row.get("month", "") <= "2020-12"):
            continue
        try:
            normals.setdefault((row["city_id"], row["month"][5:7]), []).append(float(row["tmean"]))
        except (TypeError, ValueError, KeyError):
            continue
    enriched = []
    for row in raw:
        try:
            tmean = float(row["tmean"])
        except (TypeError, ValueError):
            continue
        bucket = normals.get((row.get("city_id"), row["month"][5:7]), [])
        normal = sum(bucket) / len(bucket) if len(bucket) >= 1 else None
        # Норма только если в базовом месяце есть наблюдения; порог 25 дней проверяется при сборе.
        anomaly = weather_anomaly(tmean, normal)
        enriched.append({**row, "anomaly_vs_1991_2020": anomaly})
    if enriched:
        write_csv(
            CLEAN / "weather_monthly.csv",
            ["month", "city_id", "tmean", "anomaly_vs_1991_2020", "source", "fetched_at", "n_obs"],
            enriched,
        )
    by_month: dict[str, list[float]] = {}
    for row in enriched:
        if is_num(row.get("anomaly_vs_1991_2020")):
            by_month.setdefault(row["month"], []).append(row["anomaly_vs_1991_2020"])
    composite_rows = []
    for month, values in sorted(by_month.items()):
        composite_rows.append({"month": month, "anomaly": composite_mean(values), "n_obs": len(values)})
    flagged = {row["month"] for row in top_abs_months(composite_rows, 12)}
    write_csv(
        DERIVED / "weather_composite.csv",
        ["month", "anomaly_composite", "top12_flag", "n_obs"],
        [
            {
                "month": row["month"],
                "anomaly_composite": row["anomaly"],
                "top12_flag": 1 if row["month"] in flagged else 0,
                "n_obs": row["n_obs"],
            }
            for row in composite_rows
        ],
    )
    _empty(DERIVED / "weather_events.csv", ["month", "event", "affected_sectors", "imoex_ret", *SECTORS, "n_obs"])


def _write_echelons(returns, echelons):
    grouped: dict[str, list[dict]] = {}
    for row in returns:
        group = echelons.get(row["ticker"], "")
        if not group or not is_num(row["ret_pct"]):
            continue
        grouped.setdefault(group, []).append(row)
    rows = []
    for group, items in sorted(grouped.items()):
        values = [item["ret_pct"] for item in items]
        worst = min(items, key=lambda item: item["ret_pct"])
        best = max(items, key=lambda item: item["ret_pct"])
        mean = sum(values) / len(values)
        var = sum((value - mean) ** 2 for value in values) / (len(values) - 1) if len(values) > 1 else None
        rows.append(
            {
                "group": group,
                "n_tickers": len({item["ticker"] for item in items}),
                "avg_sigma": var**0.5 if var is not None else None,
                "avg_abs_ret": sum(abs(value) for value in values) / len(values),
                "worst_month": worst["month"],
                "best_month": best["month"],
                "n_obs": len(values),
            }
        )
    write_csv(
        DERIVED / "echelon_vol.csv",
        ["group", "n_tickers", "avg_sigma", "avg_abs_ret", "worst_month", "best_month", "n_obs"],
        rows,
    )


def _write_extremes(returns):
    ranked = [row for row in returns if is_num(row["ret_pct"])]
    ranked.sort(key=lambda row: row["ret_pct"])
    bottom = ranked[:12]
    top = list(reversed(ranked[-12:]))
    rows = []
    for kind, sample in (("bottom12", bottom), ("top12", top)):
        for row in sample:
            rows.append({"kind": kind, "month": row["month"], "ticker": row["ticker"], "ret_pct": row["ret_pct"], "n_obs": len(ranked)})
    write_csv(DERIVED / "extremes_monthly.csv", ["kind", "month", "ticker", "ret_pct", "n_obs"], rows)


def _write_yoy(macro_rows, today):
    # Без дневных цен IMOEX YTD акций не из чего считать. Ставка, USD и Brent — из macro, на конец того же месяца.
    rows = []
    by_month = {row["month"]: row for row in macro_rows}
    month_day = today.strftime("%m")
    for year in range(2021, today.year + 1):
        stamp = f"{year}-{month_day}"
        prev = f"{year - 1}-{month_day}"
        if stamp not in by_month or prev not in by_month:
            continue
        for metric, field, changer in (
            ("key_rate", "key_rate", rate_change_pp),
            ("usdrub", "usdrub", yoy_change),
            ("brent", "brent_last", yoy_change),
        ):
            try:
                now = float(by_month[stamp][field]) if by_month[stamp].get(field) not in ("", None) else None
                then = float(by_month[prev][field]) if by_month[prev].get(field) not in ("", None) else None
            except (TypeError, ValueError):
                now, then = None, None
            rows.append(
                {
                    "metric": metric,
                    "entity": field,
                    "year": year,
                    "ytd_to_date_pct": changer(then, now),
                    "full_year_pct": None,
                    "n_obs": 2 if now is not None and then is not None else 0,
                }
            )
    write_csv(DERIVED / "yoy_compare.csv", ["metric", "entity", "year", "ytd_to_date_pct", "full_year_pct", "n_obs"], rows)


def _write_plan_flows():
    _empty(DERIVED / "plan_flows.csv", ["n", "s", "c", "share", "n_obs"])


def plan_share_row(years, equity_flow, contribution):
    return {
        "n": years,
        "s": equity_flow,
        "c": contribution,
        "share": flow_share(years, equity_flow, contribution),
        "n_obs": 1,
    }


def _write_plan(today: date, macro_rows, events):
    thresholds = load_thresholds()
    rates = [row for row in macro_rows if row.get("key_rate") not in ("", None)]
    key_rate = None
    trend = "flat"
    if rates:
        try:
            key_rate = float(rates[-1]["key_rate"])
            if len(rates) >= 2:
                prev = float(rates[-2]["key_rate"])
                if key_rate > prev:
                    trend = "up"
                elif key_rate < prev:
                    trend = "down"
        except (TypeError, ValueError):
            key_rate = None
    daily, _stamp = _load_keyrate()
    if len(daily) >= 2 and is_num(daily[-1]["rate"]) and is_num(daily[-2]["rate"]):
        key_rate = daily[-1]["rate"]
        if daily[-1]["rate"] > daily[-2]["rate"]:
            trend = "up"
        elif daily[-1]["rate"] < daily[-2]["rate"]:
            trend = "down"
        else:
            trend = "flat"
    rai_series = []
    for row in read_csv(DERIVED / "rai_monthly.csv"):
        raw = row.get("IMOEX")
        try:
            rai_series.append(float(raw) if raw not in ("", None) else None)
        except (TypeError, ValueError):
            rai_series.append(None)
    rai_value = next((value for value in reversed(rai_series) if is_num(value)), None)
    curve_rows = read_csv(CLEAN / "ofz_curve_daily.csv")
    curve = curve_rows[-1] if curve_rows else {}

    def curve_num(name):
        raw = curve.get(name)
        try:
            return float(raw) if raw not in ("", None) else None
        except (TypeError, ValueError):
            return None

    y2, y10 = curve_num("t_2y"), curve_num("t_10y")
    inverted = None if y2 is None or y10 is None else int(y2 > y10)
    ofz_rows = read_csv(CLEAN / "ofz_daily.csv")
    ofz_note = "ΔP/P ≈ −D_mod·Δy; D_mod в годах, Δy в долях."
    if ofz_rows:
        ofz_note += " duration_days в ofz_daily — дни ISS, в годы сами не переводятся."
    else:
        ofz_note += " Ряд ОФЗ пуст."
    step = instant_step(
        key_rate,
        trend,
        rai_value,
        thresholds["step0_rate_above"],
        thresholds["step1_rate_above"],
        thresholds["step2_rate_above"],
        thresholds["rai_bull_below"],
    )
    stop = stop_cap(trend, rai_series, thresholds["stop_rai_months"])
    if stop["active"]:
        step = 0
    windows = weak_windows(today)
    nsi_value = 0
    payload = {
        "as_of": today.isoformat(),
        "key_rate": key_rate,
        "key_rate_trend": trend if key_rate is not None else None,
        "last_cb_meeting": events[-1]["date"] if events else None,
        "rai_imoex_monthly": rai_value,
        "rai_imoex_months_above_1_in_row": rai_streak_above(rai_series),
        "nsi_last_month": None,
        "nsi_last_month_including_draft": None,
        "nsi_confirmed_only": True,
        "ofz_ytm_2y": y2,
        "ofz_ytm_5y": curve_num("t_5y"),
        "ofz_ytm_10y": y10,
        "ofz_curve_inverted": inverted,
        "step": step,
        "step_confirmation": "instant_no_meeting_calendar",
        "soft_conditions": {
            "c1_monetary": monetary_soft(key_rate, trend, thresholds["step0_rate_above"]),
            "c2_rai_below_1": None if rai_value is None else rai_value < 1,
            "c3_nsi_ge_0_and_weak_window": (nsi_value >= 0) and bool(windows),
        },
        "stop_cap": {"active": stop["active"], "reason": stop["reason"], "months_to_trigger": stop["months_to_trigger"]},
        "weak_windows_today": windows,
        "ofz_repricing_note": ofz_note,
        "ofz_example_delta_p": ofz_repricing(None, None),
    }
    write_json(DERIVED / "plan_dashboard.json", payload)
    return payload


def price_history_for_tests(dates, prices):
    """Вспомогательная обёртка, чтобы тесты гоняли RAI на массиве, а не на пустом ISS."""
    return rai_frame("TEST", dates, prices, window=len(dates))
