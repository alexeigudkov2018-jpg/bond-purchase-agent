"""Собирает dashboard.html — многовкладочный терминал на миллиметровке Ганна.

Числа только из data/ и reports/. При отсутствии снимков
data/bonds_tuesday_latest.csv, data/ps_screener_latest.csv,
data/macro_ofz_latest.md скрипт собирает их из уже лежащих источников.

Итог — один self-contained HTML: DATA и Lightweight Charts встроены
в файл, страница открывается по file:// без сервера и без сети.
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
LWC_VENDOR = Path(__file__).resolve().parent / "vendor" / "lightweight-charts.standalone.production.js"
CANDLES_EXTRA = CLEAN / "candles_extra_daily.csv"
# Полный рабочий список: индексы, акции, вечные фьючерсы металлов/FX, нефть BR.
TICKER_ORDER = (
    "IMOEX",
    "RGBI",
    "SMLT",
    "KLVZ",
    "EUTR",
    "MGKL",
    "SELG",
    "TATN",
    "OZON",
    "GAZP",
    "GLDRUBF",
    "SLVRUBF",
    "PLTRUBF",
    "PLDRUBF",
    "USDRUBF",
    "CNYRUBF",
    "BR",
)
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
# 9 активных отраслей Стовалла (MOEXTL застыл 19.03.2026 — не используем).
STOVALL_SECTORS = (
    ("MOEXOG", "Нефтегаз"),
    ("MOEXFN", "Финансы"),
    ("MOEXMM", "Металлы и добыча"),
    ("MOEXIT", "ИТ и телеком"),
    ("MOEXTN", "Транспорт"),
    ("MOEXRE", "Недвижимость"),
    ("MOEXCN", "Потребительский"),
    ("MOEXEU", "Электроэнергетика"),
    ("MOEXCH", "Химия и нефтехимия"),
)
STOVALL_HORIZONS = {
    "tactical": {"label": "Тактика 20/10", "rs": 20, "mom": 10},
    "cycle": {"label": "Цикл 60/30", "rs": 60, "mom": 30},
    "long": {"label": "Долгосрок 120/60", "rs": 120, "mom": 60},
}
# Макро-бонус фазы: кто обычно лидирует у Стовалла / на рублевой ставке.
STOVALL_PHASE_BONUS = {
    "ПИК СТАВКИ": {"MOEXEU": 1.0, "MOEXCN": 0.8, "MOEXFN": 0.4},
    "РАННЯЯ ЭКСПАНСИЯ": {"MOEXFN": 1.0, "MOEXRE": 1.0, "MOEXIT": 0.8, "MOEXCN": 0.6, "MOEXTN": 0.4},
    "СРЕДНЯЯ ЭКСПАНСИЯ": {"MOEXTN": 1.0, "MOEXMM": 0.9, "MOEXCH": 0.8, "MOEXIT": 0.5, "MOEXOG": 0.4},
    "ПОЗДНЯЯ ЭКСПАНСИЯ": {"MOEXOG": 1.0, "MOEXCH": 0.8, "MOEXEU": 0.7, "MOEXMM": 0.5},
    "РАННЯЯ КОНТРАКЦИЯ": {"MOEXEU": 1.0, "MOEXCN": 0.9, "MOEXIT": 0.4},
    "СРЕДНЯЯ КОНТРАКЦИЯ": {"MOEXEU": 1.0, "MOEXCN": 0.9, "MOEXIT": 0.5, "MOEXCH": 0.3},
    "ПОЗДНЯЯ КОНТРАКЦИЯ": {"MOEXFN": 0.9, "MOEXRE": 0.8, "MOEXIT": 0.6, "MOEXCN": 0.5},
}
# Бонус направления RUSFAR: выигрывают от снижения / повышения ставки.
STOVALL_RATE_BONUS = {
    "СНИЖЕНИЕ": {"MOEXRE": 0.8, "MOEXFN": 0.7, "MOEXIT": 0.5, "MOEXCN": 0.3, "MOEXTN": 0.2},
    "ПОВЫШЕНИЕ": {"MOEXOG": 0.6, "MOEXMM": 0.5, "MOEXCH": 0.4, "MOEXEU": 0.3, "MOEXFN": 0.2},
    "ПЛАТО": {},
}
ROTATION_CSV = CLEAN / "indices_rotation_daily.csv"
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
    for path in (CLEAN / "indices_daily.csv", ROTATION_CSV):
        for row in read_csv(path):
            name = row.get("index") or ""
            stamp = row.get("date") or ""
            close = _num(row.get("close"))
            if name and stamp and close is not None:
                series[name][stamp] = close
    return series


def _zscores(values: list[float | None]) -> list[float | None]:
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return [0.0 if v is not None else None for v in values]
    mean = sum(present) / len(present)
    var = sum((v - mean) ** 2 for v in present) / len(present)
    std = var ** 0.5
    if std < 1e-12:
        return [0.0 if v is not None else None for v in values]
    return [None if v is None else (v - mean) / std for v in values]


def _session_return(series: dict[str, float], sessions: int) -> float | None:
    return ret_n(series, sessions)


def classify_rusfar_cycle(rusfar: dict[str, float]) -> dict:
    dates = sorted(rusfar)
    if len(dates) < 60:
        return {
            "asof": dates[-1] if dates else None,
            "rate": rusfar.get(dates[-1]) if dates else None,
            "cycle_pos": None,
            "delta_60": None,
            "delta_dir": "нет ряда",
            "phase": "нет ряда",
            "corridor_low": None,
            "corridor_high": None,
            "window_days": 0,
            "favored": [],
        }
    asof = dates[-1]
    rate = rusfar[asof]
    # ~2 календарных года ≈ 504 торговых сессии, иначе вся доступная история.
    window = dates[-min(len(dates), 504) :]
    lows = [rusfar[d] for d in window]
    lo, hi = min(lows), max(lows)
    cycle_pos = 0.5 if hi <= lo else (rate - lo) / (hi - lo)
    # 60 торговых сессий назад
    prev_idx = max(0, len(dates) - 1 - 60)
    prev_rate = rusfar[dates[prev_idx]]
    delta_60 = rate - prev_rate
    if abs(delta_60) < 0.15:
        delta_dir = "ПЛАТО"
    elif delta_60 < 0:
        delta_dir = "СНИЖЕНИЕ"
    else:
        delta_dir = "ПОВЫШЕНИЕ"
    if cycle_pos >= 0.85 and delta_dir in ("ПЛАТО", "СНИЖЕНИЕ"):
        phase = "ПИК СТАВКИ"
    elif delta_dir == "ПОВЫШЕНИЕ":
        if cycle_pos < 0.35:
            phase = "РАННЯЯ КОНТРАКЦИЯ"
        elif cycle_pos < 0.70:
            phase = "СРЕДНЯЯ КОНТРАКЦИЯ"
        else:
            phase = "ПОЗДНЯЯ КОНТРАКЦИЯ"
    elif delta_dir == "СНИЖЕНИЕ":
        if cycle_pos >= 0.70:
            phase = "РАННЯЯ ЭКСПАНСИЯ"
        elif cycle_pos >= 0.35:
            phase = "СРЕДНЯЯ ЭКСПАНСИЯ"
        else:
            phase = "ПОЗДНЯЯ ЭКСПАНСИЯ"
    else:  # ПЛАТО
        if cycle_pos >= 0.70:
            phase = "ПОЗДНЯЯ КОНТРАКЦИЯ"
        elif cycle_pos <= 0.30:
            phase = "ПОЗДНЯЯ ЭКСПАНСИЯ"
        else:
            phase = "СРЕДНЯЯ ЭКСПАНСИЯ"
    favored_map = STOVALL_PHASE_BONUS.get(phase, {})
    favored = [code for code, _ in sorted(favored_map.items(), key=lambda item: -item[1])]
    return {
        "asof": asof,
        "rate": rate,
        "cycle_pos": cycle_pos,
        "delta_60": delta_60,
        "delta_dir": delta_dir,
        "phase": phase,
        "corridor_low": lo,
        "corridor_high": hi,
        "window_days": len(window),
        "favored": favored,
    }


def build_stovall_rotation(series: dict[str, dict[str, float]]) -> dict:
    cycle = classify_rusfar_cycle(series.get("RUSFAR", {}))
    imoex = series.get("IMOEX", {})
    phase = cycle.get("phase") or ""
    delta_dir = cycle.get("delta_dir") or ""
    phase_bonus_map = STOVALL_PHASE_BONUS.get(phase, {})
    rate_bonus_map = STOVALL_RATE_BONUS.get(delta_dir, {})
    horizons_out: dict[str, list[dict]] = {}
    for key, cfg in STOVALL_HORIZONS.items():
        rs_n = cfg["rs"]
        mom_n = cfg["mom"]
        raw_rows = []
        for code, title in STOVALL_SECTORS:
            own = series.get(code, {})
            sec_ret = _session_return(own, rs_n)
            imx_ret = _session_return(imoex, rs_n)
            rs = None if sec_ret is None or imx_ret is None else sec_ret - imx_ret
            mom = _session_return(own, mom_n)
            mom_prev = None
            dates = sorted(own)
            if len(dates) > mom_n * 2:
                truncated = {d: own[d] for d in dates[: -(mom_n)]}
                mom_prev = _session_return(truncated, mom_n)
            accel = None if mom is None or mom_prev is None else mom - mom_prev
            raw_rows.append(
                {
                    "code": code,
                    "title": title,
                    "rs": rs,
                    "momentum": mom,
                    "acceleration": accel,
                    "close": own.get(dates[-1]) if dates else None,
                    "asof": dates[-1] if dates else None,
                    "rate_bonus": float(rate_bonus_map.get(code, 0.0)),
                    "phase_bonus": float(phase_bonus_map.get(code, 0.0)),
                }
            )
        z_rs = _zscores([row["rs"] for row in raw_rows])
        z_mom = _zscores([row["momentum"] for row in raw_rows])
        z_acc = _zscores([row["acceleration"] for row in raw_rows])
        scored = []
        for i, row in enumerate(raw_rows):
            if z_rs[i] is None or z_mom[i] is None:
                score = None
            else:
                acc = z_acc[i] if z_acc[i] is not None else 0.0
                score = z_rs[i] + z_mom[i] + 0.5 * acc + row["rate_bonus"] + row["phase_bonus"]
            scored.append(
                {
                    **row,
                    "z_rs": z_rs[i],
                    "z_momentum": z_mom[i],
                    "z_acceleration": z_acc[i],
                    "score": score,
                    "macro_boost": bool(row["rate_bonus"] or row["phase_bonus"]),
                    "boost_note": (
                        (
                            (f"фаза +{row['phase_bonus']:.1f}" if row["phase_bonus"] else "")
                            + (" · " if row["phase_bonus"] and row["rate_bonus"] else "")
                            + (f"ставка +{row['rate_bonus']:.1f}" if row["rate_bonus"] else "")
                        )
                        or "без макро-бонуса"
                    ),
                }
            )
        scored.sort(key=lambda item: (item["score"] is None, -(item["score"] or 0.0)))
        for rank, row in enumerate(scored, start=1):
            row["rank"] = rank
        horizons_out[key] = scored
    return {
        "model": "Sector Rotation MOEX · Стовалл + RUSFAR",
        "cycle": cycle,
        "horizons": {
            key: {"label": STOVALL_HORIZONS[key]["label"], "rs": STOVALL_HORIZONS[key]["rs"], "mom": STOVALL_HORIZONS[key]["mom"], "rows": rows}
            for key, rows in horizons_out.items()
        },
        "default_horizon": "cycle",
        "note": "Score = Z(RS) + Z(Momentum) + 0.5·Z(Acceleration) + бонус RUSFAR + бонус фазы. MOEXTL исключён.",
    }


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


def _ingest_bar_row(
    store: dict[str, dict[str, dict]],
    ticker: str,
    stamp: str,
    open_: float | None,
    high: float | None,
    low: float | None,
    close: float | None,
    volume: float | None = None,
) -> None:
    if not ticker or not stamp or close is None:
        return
    prev = store.get(ticker, {}).get(stamp)
    # Полный OHLC из ISS/prices имеет приоритет над close-only индексом.
    if prev and prev.get("_full") and not (open_ is not None and high is not None and low is not None):
        return
    full = open_ is not None and high is not None and low is not None and open_ != 0
    store.setdefault(ticker, {})[stamp] = {
        "time": stamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "_full": full,
    }


def synthesize_candles(raw_rows: list[dict]) -> list[dict]:
    """Гарантирует валидные свечи: open=prev close при отсутствии OPEN."""
    out: list[dict] = []
    prev_close: float | None = None
    for row in raw_rows:
        close = row.get("close")
        if close is None:
            continue
        open_ = row.get("open")
        high = row.get("high")
        low = row.get("low")
        if open_ is None or open_ == 0:
            open_ = prev_close if prev_close is not None else close
        if high is None or high == 0:
            high = max(float(open_), float(close))
        if low is None or low == 0:
            low = min(float(open_), float(close))
        high = max(float(high), float(open_), float(close))
        low = min(float(low), float(open_), float(close))
        item = {
            "time": row["time"],
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
        }
        if row.get("volume") is not None:
            item["volume"] = float(row["volume"])
        out.append(item)
        prev_close = float(close)
    # Окно ~1 год для терминала (если ряд длиннее).
    if len(out) > 270:
        out = out[-270:]
    return out


def load_bars(tickers: list[str]) -> dict[str, list[dict]]:
    wanted = set(tickers) | set(TICKER_ORDER)
    bars: dict[str, dict[str, dict]] = {}

    def read_ohlc_csv(path: Path, ticker_field: str) -> None:
        if not path.exists():
            return
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                ticker = row.get(ticker_field) or ""
                if ticker not in wanted:
                    continue
                stamp = row.get("date") or ""
                open_, high, low, close = (_num(row.get(name)) for name in ("open", "high", "low", "close"))
                volume = _num(row.get("volume_rub") or row.get("volume"))
                _ingest_bar_row(bars, ticker, stamp, open_, high, low, close, volume)

    read_ohlc_csv(CLEAN / "prices_daily.csv", "ticker")
    read_ohlc_csv(CANDLES_EXTRA, "ticker")

    with (CLEAN / "indices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("index") or ""
            if ticker not in wanted:
                continue
            stamp = row.get("date") or ""
            close = _num(row.get("close"))
            open_ = _num(row.get("open"))
            high = _num(row.get("high"))
            low = _num(row.get("low"))
            _ingest_bar_row(bars, ticker, stamp, open_, high, low, close, None)

    result: dict[str, list[dict]] = {}
    for ticker in sorted(bars):
        raw = [bars[ticker][stamp] for stamp in sorted(bars[ticker])]
        candles = synthesize_candles(raw)
        if candles:
            result[ticker] = candles
    # Стабильный порядок по TICKER_ORDER + хвост.
    ordered: dict[str, list[dict]] = {}
    for ticker in TICKER_ORDER:
        if ticker in result:
            ordered[ticker] = result[ticker]
    for ticker in sorted(result):
        if ticker not in ordered:
            ordered[ticker] = result[ticker]
    return ordered


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


def ticker_list(events: list[dict], bars: dict[str, list[dict]]) -> list[str]:
    available = set(bars)
    ordered = [name for name in TICKER_ORDER if name in available]
    extras = sorted(available - set(ordered))
    # Событийные тикеры без бара не показываем — иначе пустой график.
    return ordered + extras or ["IMOEX"]


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
    bars = load_bars(list(TICKER_ORDER))
    tickers = ticker_list(events, bars)
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
        "stovall": build_stovall_rotation(series),
        "almanac_diff": parse_almanac_diff(),
        "disclaimer": "Материал не является индивидуальной инвестиционной рекомендацией.",
    }


def _inline_lwc_script() -> str:
    """Встраивает standalone Lightweight Charts для file:// без сети."""
    if not LWC_VENDOR.exists():
        raise FileNotFoundError(
            f"нет {LWC_VENDOR.relative_to(ROOT)} — положите lightweight-charts.standalone.production.js в scripts/vendor/"
        )
    source = LWC_VENDOR.read_text(encoding="utf-8")
    # Не дать закрыть HTML-тег script изнутри бандла.
    source = source.replace("</script>", "<\\/script>").replace("</Script>", "<\\/Script>")
    return f"<script>\n{source}\n</script>"


def build() -> None:
    payload = build_payload()
    html = (
        HTML.replace("__DATA__", _json_blob(payload))
        .replace("__LWC_SCRIPT__", _inline_lwc_script())
    )
    OUT.write_text(html, encoding="utf-8")
    kpi = payload["kpi"]
    print(
        f"wrote {OUT.relative_to(ROOT)} "
        f"tickers={len(payload['candles']['tickers'])} "
        f"events={len(payload['candles']['events'])} "
        f"bonds={len(payload['bonds'])} "
        f"ps_rows={len(payload['ps_screener'])} "
        f"imoex={kpi['imoex']['value']} ps={kpi['ps']['value']} "
        f"lwc_inline={LWC_VENDOR.stat().st_size}"
    )


HTML = r"""<!DOCTYPE html>
<html lang="ru" data-theme="gann">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TERMINAL · GANN / RADAR</title>
__LWC_SCRIPT__
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
.chart-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; justify-content: space-between; margin-bottom: 6px; }
.chart-head h2 { margin: 0 0 4px; }
.fs-btn {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  padding: 8px 14px;
  border: 2px solid var(--ink);
  background: #F2C94C;
  color: var(--ink);
  cursor: pointer;
  letter-spacing: 0.02em;
  box-shadow: 2px 2px 0 rgba(28, 25, 21, 0.18);
  white-space: nowrap;
}
.fs-btn:hover { filter: brightness(0.97); }
.fs-btn.active { background: var(--ink); color: #F2C94C; }
.mode-block { margin: 8px 0 4px; }
.mode-label {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 4px;
}
.active-badges { display: flex; flex-wrap: wrap; gap: 4px; min-height: 0; margin: 2px 0 6px; }
.active-badges .badge {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 10px;
  padding: 2px 7px;
  border: 1px solid var(--rule);
  background: rgba(242, 201, 76, 0.35);
  color: var(--ink);
}
.chart-workspace { position: relative; }
.chart-workspace.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  overflow: auto;
  padding: 12px 14px 18px;
  background:
    linear-gradient(rgba(184, 152, 86, 0.22) 1px, transparent 1px),
    linear-gradient(90deg, rgba(184, 152, 86, 0.22) 1px, transparent 1px),
    #FCF8E3;
  background-size: 8px 8px, 8px 8px, auto;
}
.chart-workspace.is-fullscreen .chart { height: min(52vh, 560px); }
.chart-workspace.is-fullscreen #haChart { height: 240px; }
.chart-workspace.is-fullscreen #pctRChart,
.chart-workspace.is-fullscreen #rsiStochChart,
.chart-workspace.is-fullscreen #rsxChart,
.chart-workspace.is-fullscreen #optChart { height: 170px; }
.explain-compact { border-style: dashed; }
.wrap { position: relative; }
.chart { height: 420px; border: 1px solid var(--rule); background: var(--chart-bg); }
.chart.small { height: 260px; }
#lower { height: 150px; margin-top: 8px; border: 1px solid var(--rule); background: var(--chart-bg); }
#optBox, #pctRBox, #rsiStochBox, #haBox, #rsxBox { display: none; margin-top: 8px; border: 1px solid var(--rule); background: var(--card); padding: 8px; }
#optBox .pct-head, #pctRBox .pct-head, #rsiStochBox .pct-head, #haBox .pct-head, #rsxBox .pct-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 6px; }
#optBox .pct-head h3, #pctRBox .pct-head h3, #rsiStochBox .pct-head h3, #haBox .pct-head h3, #rsxBox .pct-head h3 { margin: 0; font-size: 13px; }
#pctRSpeed, #rsiStochMode { display: flex; gap: 4px; }
#fairMode { display: none; gap: 4px; flex-wrap: wrap; align-items: center; margin: 6px 0 0; }
#pctRSpeed button, #rsiStochMode button, #fairMode button { font-family: "JetBrains Mono", Consolas, monospace; font-size: 10px; padding: 4px 8px; border: 1px solid var(--rule); background: var(--paper); color: var(--ink); cursor: pointer; }
#pctRSpeed button.active, #rsiStochMode button.active, #fairMode button.active { background: var(--ink); color: var(--paper); }
#pctRChart, #rsiStochChart, #rsxChart, #optChart { height: 160px; border: 1px solid var(--rule); background: var(--chart-bg); }
#haChart { height: 220px; border: 1px solid var(--rule); background: var(--chart-bg); }
#haBox.ha-bull { box-shadow: inset 0 0 0 9999px rgba(27, 107, 58, 0.06); }
#haBox.ha-bear { box-shadow: inset 0 0 0 9999px rgba(166, 38, 38, 0.06); }
.stovall-cycle {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
  margin: 8px 0 4px;
}
.stovall-cycle .cell {
  border: 1px solid var(--rule);
  background: var(--paper);
  padding: 8px 10px;
}
.stovall-cycle .cell .k { display: block; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.stovall-cycle .cell .v { display: block; margin-top: 4px; font-family: "JetBrains Mono", Consolas, monospace; font-size: 13px; }
.stovall-cycle .phase .v { font-family: "Libre Baskerville", Georgia, serif; font-size: 15px; font-weight: 700; }
tr.macro-boost td:first-child { box-shadow: inset 3px 0 0 var(--blue); }
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
.modes { display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 6px; }
.modes button {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 10px;
  padding: 5px 9px;
  border: 1px solid var(--rule);
  background:
    linear-gradient(rgba(184, 152, 86, 0.12) 1px, transparent 1px),
    linear-gradient(90deg, rgba(184, 152, 86, 0.12) 1px, transparent 1px),
    var(--paper);
  background-size: 6px 6px, 6px 6px, auto;
  color: var(--ink);
  cursor: pointer;
}
.modes button.active { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.modes button[data-mode="clear"] { border-style: dashed; }
#explainBoard { margin-top: 10px; }
#explainBoard table.grid td:first-child { color: var(--muted); width: 38%; }
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
    <div class="chart-head">
      <div>
        <h2>Свечи, уровни и индикаторы</h2>
        <p class="hint">Полные дневные свечи (~1 год). Все панели синхронизированы по времени. Флажки — <span class="mono">radar_events.csv</span>.</p>
      </div>
      <button type="button" id="btnFullscreen" class="fs-btn" title="Развернуть график">⛶ На весь экран</button>
    </div>
    <div class="tickers" id="tickers"></div>
    <div class="mode-block">
      <div class="mode-label">Строка 1 · Уровни, Циклы и Волны (наложения)</div>
      <div class="modes" id="modeRowLevels">
        <button type="button" data-mode="gann9" id="btnGann9">Квадрат 9 Ганна (Углы)</button>
        <button type="button" data-mode="gann18" id="btnGann18">Сетка Ганна 1/8 (50%)</button>
        <button type="button" data-mode="boroden" id="btnBoroden">Кластеры и Время Кэролайн Бороден</button>
        <button type="button" data-mode="elliott" id="btnElliott">Волны Эллиотта (1-2-3-4-5)</button>
        <button type="button" data-mode="plummer" id="btnPlummer">Канал Вибрации Пламмера</button>
      </div>
    </div>
    <div class="mode-block">
      <div class="mode-label">Строка 2 · Трендовые наложения и Нижние подвалы</div>
      <div class="modes" id="modeRowTrend">
        <button type="button" data-mode="kennedy" id="btnKennedy">Kennedy Trend (MA+HA)</button>
        <button type="button" data-mode="donch" id="btnDonch">Donchian 20 + Поглощения</button>
        <button type="button" data-mode="hill" id="btnHill">5 vs 200 (Arthur Hill)</button>
        <button type="button" data-mode="fair" id="btnFair">Средний High/Low</button>
        <button type="button" data-mode="opt" id="btnOpt">Подвал: Опционы Put/Call</button>
        <button type="button" data-mode="pctr" id="btnPctR">Подвал: %R (5/20)</button>
        <button type="button" data-mode="rsistoch" id="btnRsiStoch">Подвал: RSI + Stoch</button>
        <button type="button" data-mode="rsx" id="btnRsx">Подвал: Jurik RSX</button>
        <button type="button" data-mode="ha" id="btnHa">Подвал: Heikin-Ashi</button>
        <button type="button" data-mode="clear" id="btnClearModes">Очистить всё</button>
      </div>
    </div>
    <div id="activeBadges" class="active-badges"></div>
    <div id="fairMode">
      <span class="meta" style="margin-right:4px">Режим коридора:</span>
      <button type="button" data-fair="cum" class="active">Накопленное среднее (вся история)</button>
      <button type="button" data-fair="sma20">Скользящий конверт SMA(20)</button>
    </div>
    <div id="chartWorkspace" class="chart-workspace">
      <div class="wrap">
        <div class="chart" id="price"></div>
        <div id="tip"></div>
      </div>
      <div id="lower"></div>
      <div id="optBox">
        <div class="pct-head">
          <h3 id="optTitle">Подвал · Опционы Put/Call (прокси потока)</h3>
          <span class="meta" id="optHint">PCR по объёму дня</span>
        </div>
        <div id="optChart"></div>
      </div>
      <div id="pctRBox">
        <div class="pct-head">
          <h3 id="pctRTitle">Панель %R · быстрый (5)</h3>
          <div id="pctRSpeed">
            <button type="button" data-speed="5" class="active">Быстрый %R(5)</button>
            <button type="button" data-speed="20">Медленный %R(20)</button>
          </div>
        </div>
        <div id="pctRChart"></div>
      </div>
      <div id="rsiStochBox">
        <div class="pct-head">
          <h3 id="rsiStochTitle">Панель RSI (14 / SMA9 / EMA45)</h3>
          <div id="rsiStochMode">
            <button type="button" data-pane="rsi" class="active">RSI (14 / SMA9 / EMA45)</button>
            <button type="button" data-pane="stoch">Stochastic (8, 5, 3)</button>
          </div>
        </div>
        <div id="rsiStochChart"></div>
      </div>
      <div id="rsxBox">
        <div class="pct-head">
          <h3 id="rsxTitle">Панель Jurik RSX (14) · Ход / Сила / Слом</h3>
          <span class="meta" id="rsxHint">ось 50 · слом наклона</span>
        </div>
        <div id="rsxChart"></div>
      </div>
      <div id="haBox">
        <div class="pct-head">
          <h3 id="haTitle">Панель Heikin-Ashi + EMA9</h3>
          <span class="meta" id="haRibbonHint">лента EMA9</span>
        </div>
        <div id="haChart"></div>
      </div>
      <div class="board explain-compact" id="explainBoard" style="display:none;margin-top:10px;padding:10px;">
        <h2 id="explainTitle">Пояснения · индикаторы</h2>
        <div id="kennedySummary"></div>
        <div id="gannStatus"></div>
        <div id="borodenStatus"></div>
        <div id="elliottStatus"></div>
        <div id="kennedyStatus"></div>
        <div id="donchStatus"></div>
        <div id="optStatus"></div>
        <div id="pctRStatus"></div>
        <div id="rsiStochStatus"></div>
        <div id="rsxStatus"></div>
        <div id="haStatus"></div>
        <div id="hillStatus"></div>
        <div id="fairStatus"></div>
        <div id="plummerStatus"></div>
      </div>
    </div>
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
    <h2>Sector Rotation MOEX · Стовалл + RUSFAR</h2>
    <p class="hint">Фаза денежного цикла по RUSFAR (2-летний коридор ISS) и Score Стовалла по 9 отраслям. Горизонт: Тактика 20/10 · Цикл 60/30 · Долгосрок 120/60.</p>
    <div id="stovallCycle" class="stovall-cycle"></div>
    <div id="stovallHorizon" class="modes" style="margin:10px 0 8px">
      <button type="button" data-horizon="tactical">Тактика 20/10</button>
      <button type="button" data-horizon="cycle" class="active">Цикл 60/30</button>
      <button type="button" data-horizon="long">Долгосрок 120/60</button>
    </div>
    <div class="scroll"><table class="grid" id="stovallTable"></table></div>
    <p class="hint" id="stovallNote"></p>
  </div>
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
  const rule = getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856";
  return {
    height,
    layout: { background: { color: getComputedStyle(root).getPropertyValue("--chart-bg").trim() || "#FCF8E3" }, textColor: getComputedStyle(root).getPropertyValue("--chart-text").trim() || "#1C1915", fontSize: 11, fontFamily: "JetBrains Mono, Consolas, monospace" },
    grid: {
      vertLines: { color: getComputedStyle(root).getPropertyValue("--chart-grid").trim() || "rgba(160,125,58,0.35)" },
      horzLines: { color: getComputedStyle(root).getPropertyValue("--chart-grid").trim() || "rgba(160,125,58,0.35)" },
    },
    rightPriceScale: { borderColor: rule, minimumWidth: 75 },
    timeScale: { borderColor: rule },
    crosshair: { mode: 0 },
  };
}

const priceEl = document.getElementById("price");
const lowerEl = document.getElementById("lower");
const tipEl = document.getElementById("tip");
const listEl = document.getElementById("eventList");
const buttonRow = document.getElementById("tickers");
const chartWorkspace = document.getElementById("chartWorkspace");
const activeBadgesEl = document.getElementById("activeBadges");
const btnFullscreen = document.getElementById("btnFullscreen");
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

let syncingRange = false;
let syncingCrosshair = false;
function paneCharts() {
  return [priceChart, lowerChart, optChart, pctRChart, rsiStochChart, rsxChart, haChart].filter(Boolean);
}
function paneSeriesOf(chart) {
  if (chart === priceChart) return priceSeries;
  if (chart === lowerChart) return heat;
  if (chart === optChart) return optPcrLine || optCallHist;
  if (chart === pctRChart) return pctRHist || pctRSmaLine;
  if (chart === rsiStochChart) return rsiStochMain;
  if (chart === rsxChart) return rsxLine;
  if (chart === haChart) return haCandleSeries;
  return null;
}
function syncLogicalRange(source, range) {
  if (syncingRange || !range) return;
  syncingRange = true;
  paneCharts().forEach((chart) => {
    if (chart === source) return;
    try { chart.timeScale().setVisibleLogicalRange(range); } catch (e) {}
  });
  syncingRange = false;
}
function bindRangeSync(chart) {
  if (!chart || chart.__rangeBound) return;
  chart.__rangeBound = true;
  chart.timeScale().subscribeVisibleLogicalRangeChange((range) => syncLogicalRange(chart, range));
}
function syncCrosshair(source, param) {
  if (syncingCrosshair) return;
  syncingCrosshair = true;
  paneCharts().forEach((chart) => {
    if (chart === source) return;
    try {
      if (!param || param.time == null) {
        chart.clearCrosshairPosition();
        return;
      }
      const series = paneSeriesOf(chart);
      if (!series) return;
      chart.setCrosshairPosition(0, param.time, series);
    } catch (e) {
      try { if (!param || param.time == null) chart.clearCrosshairPosition(); } catch (e2) {}
    }
  });
  syncingCrosshair = false;
}
function bindCrosshairSync(chart) {
  if (!chart || chart.__xhBound) return;
  chart.__xhBound = true;
  chart.subscribeCrosshairMove((param) => syncCrosshair(chart, param));
}
bindRangeSync(priceChart);
bindRangeSync(lowerChart);
bindCrosshairSync(priceChart);
bindCrosshairSync(lowerChart);

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

let kennedyOn = false;
let donchOn = false;
let pctROn = false;
let pctRPeriod = 5;
let rsiStochOn = false;
let rsiStochMode = "rsi";
let rsxOn = false;
let haOn = false;
let hillOn = false;
let fairOn = false;
let fairMode = "cum";
let plummerOn = false;
let gann9On = false;
let gann18On = false;
let borodenOn = false;
let elliottOn = false;
let optOn = false;
let fullscreenOn = false;
const kennedySeries = { ema5: null, sma10: null, sma30: null, haOpen: null, haClose: null };
const donchSeries = { hh: null, mid: null, ll: null };
const fairSeries = { hi: null, lo: null };
const hillSeries = { sma5: null, sma200: null, clouds: [] };
const plummerSeries = {
  basis: null, upperIn: null, lowerIn: null, upperEx: null, lowerEx: null,
  fillInnerHi: null, fillInnerLo: null, fillUpHi: null, fillUpLo: null, fillDnHi: null, fillDnLo: null,
};
const gann9Series = { lines: [] };
const gann18Series = { lines: [] };
const borodenSeries = { clusters: [], swings: [], timeMarks: [] };
const elliottSeries = { lines: [], labels: [] };
const explainBoard = document.getElementById("explainBoard");
const explainTitle = document.getElementById("explainTitle");
const gannStatusEl = document.getElementById("gannStatus");
const borodenStatusEl = document.getElementById("borodenStatus");
const elliottStatusEl = document.getElementById("elliottStatus");
const optStatusEl = document.getElementById("optStatus");
const optBox = document.getElementById("optBox");
const optChartEl = document.getElementById("optChart");
let optChart = null;
let optPcrLine = null;
let optCallHist = null;
let optPutHist = null;
let optLevel1 = null;
const MODE_BADGES = [
  ["gann9", () => gann9On, "Gann Sq9"],
  ["gann18", () => gann18On, "Gann 1/8"],
  ["boroden", () => borodenOn, "Boroden"],
  ["elliott", () => elliottOn, "Elliott"],
  ["plummer", () => plummerOn, "Пламмер"],
  ["kennedy", () => kennedyOn, "Kennedy"],
  ["donch", () => donchOn, "Donchian"],
  ["hill", () => hillOn, "5 vs 200"],
  ["fair", () => fairOn, "Fair Range"],
  ["opt", () => optOn, "Put/Call"],
  ["pctr", () => pctROn, "%R"],
  ["rsistoch", () => rsiStochOn, "RSI/Stoch"],
  ["rsx", () => rsxOn, "RSX"],
  ["ha", () => haOn, "Heikin-Ashi"],
];
function refreshActiveBadges() {
  if (!activeBadgesEl) return;
  activeBadgesEl.innerHTML = MODE_BADGES.filter((row) => row[1]()).map((row) =>
    `<span class="badge">${esc(row[2])}</span>`
  ).join("");
}
function anyIndicatorOn() {
  return kennedyOn || donchOn || pctROn || rsiStochOn || rsxOn || haOn || hillOn || fairOn || plummerOn
    || gann9On || gann18On || borodenOn || elliottOn || optOn;
}
function toggleFullscreen(force) {
  fullscreenOn = typeof force === "boolean" ? force : !fullscreenOn;
  if (chartWorkspace) chartWorkspace.classList.toggle("is-fullscreen", fullscreenOn);
  if (btnFullscreen) {
    btnFullscreen.classList.toggle("active", fullscreenOn);
    btnFullscreen.textContent = fullscreenOn ? "⛶ Свернуть" : "⛶ На весь экран";
  }
  requestAnimationFrame(() => {
    resizeAllCharts();
    window.dispatchEvent(new Event("resize"));
  });
}
if (btnFullscreen) btnFullscreen.addEventListener("click", () => toggleFullscreen());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && fullscreenOn) toggleFullscreen(false);
});
const kennedySummaryEl = document.getElementById("kennedySummary");
const kennedyStatusEl = document.getElementById("kennedyStatus");
const donchStatusEl = document.getElementById("donchStatus");
const pctRStatusEl = document.getElementById("pctRStatus");
const rsiStochStatusEl = document.getElementById("rsiStochStatus");
const rsxStatusEl = document.getElementById("rsxStatus");
const haStatusEl = document.getElementById("haStatus");
const hillStatusEl = document.getElementById("hillStatus");
const fairStatusEl = document.getElementById("fairStatus");
const plummerStatusEl = document.getElementById("plummerStatus");
const fairModeEl = document.getElementById("fairMode");
const pctRBox = document.getElementById("pctRBox");
const pctRChartEl = document.getElementById("pctRChart");
const rsiStochBox = document.getElementById("rsiStochBox");
const rsiStochChartEl = document.getElementById("rsiStochChart");
const rsxBox = document.getElementById("rsxBox");
const rsxChartEl = document.getElementById("rsxChart");
const haBox = document.getElementById("haBox");
const haChartEl = document.getElementById("haChart");
let haChart = null;
let haCandleSeries = null;
let haEmaCloseLine = null;
let haEmaOpenLine = null;
let rsxChart = null;
let rsxLine = null;
let rsxBreakHist = null;
let rsxLevel50 = null;
let pctRChart = null;
let pctRHist = null;
let pctRSmaLine = null;
let pctRLevel80 = null;
let pctRLevel50 = null;
let pctRLevel20 = null;
let rsiStochChart = null;
let rsiStochMain = null;
let rsiStochSec = null;
let rsiStochThird = null;
let rsiStochLvlA = null;
let rsiStochLvlB = null;
let rsiStochLvlC = null;
let rsiZoneBullHi = null;
let rsiZoneBullLo = null;
let rsiZoneBearHi = null;
let rsiZoneBearLo = null;
document.getElementById("btnKennedy").addEventListener("click", () => {
  kennedyOn = !kennedyOn;
  document.getElementById("btnKennedy").classList.toggle("active", kennedyOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnDonch").addEventListener("click", () => {
  donchOn = !donchOn;
  document.getElementById("btnDonch").classList.toggle("active", donchOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnPctR").addEventListener("click", () => {
  pctROn = !pctROn;
  document.getElementById("btnPctR").classList.toggle("active", pctROn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnRsiStoch").addEventListener("click", () => {
  rsiStochOn = !rsiStochOn;
  document.getElementById("btnRsiStoch").classList.toggle("active", rsiStochOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnRsx").addEventListener("click", () => {
  rsxOn = !rsxOn;
  document.getElementById("btnRsx").classList.toggle("active", rsxOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnHa").addEventListener("click", () => {
  haOn = !haOn;
  document.getElementById("btnHa").classList.toggle("active", haOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnHill").addEventListener("click", () => {
  hillOn = !hillOn;
  document.getElementById("btnHill").classList.toggle("active", hillOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnFair").addEventListener("click", () => {
  fairOn = !fairOn;
  document.getElementById("btnFair").classList.toggle("active", fairOn);
  fairModeEl.style.display = fairOn ? "flex" : "none";
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnPlummer").addEventListener("click", () => {
  plummerOn = !plummerOn;
  document.getElementById("btnPlummer").classList.toggle("active", plummerOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnGann9").addEventListener("click", () => {
  gann9On = !gann9On;
  document.getElementById("btnGann9").classList.toggle("active", gann9On);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnGann18").addEventListener("click", () => {
  gann18On = !gann18On;
  document.getElementById("btnGann18").classList.toggle("active", gann18On);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnBoroden").addEventListener("click", () => {
  borodenOn = !borodenOn;
  document.getElementById("btnBoroden").classList.toggle("active", borodenOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnElliott").addEventListener("click", () => {
  elliottOn = !elliottOn;
  document.getElementById("btnElliott").classList.toggle("active", elliottOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("btnOpt").addEventListener("click", () => {
  optOn = !optOn;
  document.getElementById("btnOpt").classList.toggle("active", optOn);
  if (currentTicker) showTicker(currentTicker);
});
document.getElementById("fairMode").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-fair]");
  if (!btn) return;
  fairMode = btn.getAttribute("data-fair") === "sma20" ? "sma20" : "cum";
  document.querySelectorAll("#fairMode button").forEach((el) => el.classList.toggle("active", el === btn));
  if (fairOn && currentTicker) showTicker(currentTicker);
});
document.getElementById("pctRSpeed").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-speed]");
  if (!btn) return;
  pctRPeriod = Number(btn.getAttribute("data-speed")) || 5;
  document.querySelectorAll("#pctRSpeed button").forEach((el) => el.classList.toggle("active", el === btn));
  document.getElementById("pctRTitle").textContent = pctRPeriod === 5
    ? "Панель %R · быстрый (5)"
    : "Панель %R · медленный (20)";
  if (pctROn && currentTicker) applyPctRPanel(candleData.bars[currentTicker] || []);
});
document.getElementById("rsiStochMode").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-pane]");
  if (!btn) return;
  rsiStochMode = btn.getAttribute("data-pane") === "stoch" ? "stoch" : "rsi";
  document.querySelectorAll("#rsiStochMode button").forEach((el) => el.classList.toggle("active", el === btn));
  document.getElementById("rsiStochTitle").textContent = rsiStochMode === "rsi"
    ? "Панель RSI (14 / SMA9 / EMA45)"
    : "Панель Stochastic (8, 5, 3)";
  if (rsiStochOn && currentTicker) applyRsiStochPanel(candleData.bars[currentTicker] || []);
});
document.getElementById("btnClearModes").addEventListener("click", () => {
  kennedyOn = false;
  donchOn = false;
  pctROn = false;
  rsiStochOn = false;
  rsxOn = false;
  haOn = false;
  hillOn = false;
  fairOn = false;
  plummerOn = false;
  gann9On = false;
  gann18On = false;
  borodenOn = false;
  elliottOn = false;
  optOn = false;
  ["btnKennedy","btnDonch","btnPctR","btnRsiStoch","btnRsx","btnHa","btnHill","btnFair","btnPlummer","btnGann9","btnGann18","btnBoroden","btnElliott","btnOpt"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.remove("active");
  });
  fairModeEl.style.display = "none";
  if (currentTicker) showTicker(currentTicker);
});

function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) { sum = 0; continue; }
    sum += v;
    if (i >= period) {
      const old = values[i - period];
      if (old != null) sum -= old;
    }
    if (i >= period - 1) {
      let ok = true;
      for (let j = i - period + 1; j <= i; j++) if (values[j] == null) { ok = false; break; }
      out[i] = ok ? sum / period : null;
    }
  }
  return out;
}

function ema(values, period) {
  const out = new Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    if (prev == null) {
      if (i < period - 1) continue;
      let sum = 0;
      let ok = true;
      for (let j = i - period + 1; j <= i; j++) {
        if (values[j] == null) { ok = false; break; }
        sum += values[j];
      }
      if (!ok) continue;
      prev = sum / period;
      out[i] = prev;
      continue;
    }
    prev = v * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function heikinAshi(bars) {
  const ha = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const haClose = (b.open + b.high + b.low + b.close) / 4;
    const haOpen = i === 0 ? (b.open + b.close) / 2 : (ha[i - 1].open + ha[i - 1].close) / 2;
    ha.push({
      time: b.time,
      open: haOpen,
      close: haClose,
      high: Math.max(b.high, haOpen, haClose),
      low: Math.min(b.low, haOpen, haClose),
    });
  }
  return ha;
}

function jurikRsx(closes, length = 14) {
  const n = closes.length;
  const out = new Array(n).fill(null);
  if (n < 2) return out;
  const f18 = 3 / (length + 2);
  const f20 = 1 - f18;
  let f28 = 0, f30 = 0, f38 = 0, f40 = 0, f48 = 0, f50 = 0;
  let f58 = 0, f60 = 0, f68 = 0, f70 = 0, f78 = 0, f80 = 0;
  let f88 = 0;
  let prev = closes[0];
  for (let i = 1; i < n; i++) {
    const src = closes[i];
    if (src == null || Number.isNaN(src) || prev == null || Number.isNaN(prev)) {
      prev = src;
      continue;
    }
    const v8 = 100 * src - 100 * prev;
    f28 = f20 * f28 + f18 * v8;
    f30 = f18 * f28 + f20 * f30;
    const vC = f28 * 1.5 - f30 * 0.5;
    f38 = f20 * f38 + f18 * vC;
    f40 = f18 * f38 + f20 * f40;
    const v10 = f38 * 1.5 - f40 * 0.5;
    f48 = f20 * f48 + f18 * v10;
    f50 = f18 * f48 + f20 * f50;
    const v14 = f48 * 1.5 - f50 * 0.5;
    f58 = f20 * f58 + f18 * Math.abs(v8);
    f60 = f18 * f58 + f20 * f60;
    const v18 = f58 * 1.5 - f60 * 0.5;
    f68 = f20 * f68 + f18 * v18;
    f70 = f18 * f68 + f20 * f70;
    const v1C = f68 * 1.5 - f70 * 0.5;
    f78 = f20 * f78 + f18 * v1C;
    f80 = f18 * f78 + f20 * f80;
    const v20 = f78 * 1.5 - f80 * 0.5;
    if (v20 > 0) f88 = v14 / v20;
    const raw = v20 <= 0 ? 50 : 50 * (f88 + 1);
    out[i] = Math.max(0, Math.min(100, raw));
    prev = src;
  }
  const warm = Math.min(length, n);
  for (let i = 0; i < warm; i++) out[i] = null;
  return out;
}

function rsiWilder(closes, period = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const ch = closes[i] - closes[i - 1];
    if (ch >= 0) avgGain += ch; else avgLoss -= ch;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));
  for (let i = period + 1; i < closes.length; i++) {
    const ch = closes[i] - closes[i - 1];
    const gain = ch > 0 ? ch : 0;
    const loss = ch < 0 ? -ch : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - (100 / (1 + avgGain / avgLoss));
  }
  return out;
}

function stochastic(bars, kPeriod = 8, kSmooth = 5, dPeriod = 3) {
  const rawK = bars.map((_, i) => {
    if (i < kPeriod - 1) return null;
    let hi = -Infinity, lo = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      hi = Math.max(hi, bars[j].high);
      lo = Math.min(lo, bars[j].low);
    }
    if (hi === lo) return 50;
    return 100 * ((bars[i].close - lo) / (hi - lo));
  });
  const k = sma(rawK, kSmooth);
  const d = sma(k, dPeriod);
  return { k, d };
}

function linePoints(bars, values) {
  const out = [];
  for (let i = 0; i < bars.length; i++) {
    if (values[i] == null || Number.isNaN(values[i])) continue;
    out.push({ time: bars[i].time, value: values[i] });
  }
  return out;
}

function trueRange(bars) {
  const out = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    const hi = bars[i].high;
    const lo = bars[i].low;
    if (i === 0) {
      out[i] = hi - lo;
      continue;
    }
    const prevClose = bars[i - 1].close;
    out[i] = Math.max(hi - lo, Math.abs(hi - prevClose), Math.abs(lo - prevClose));
  }
  return out;
}

function rma(values, period) {
  const out = new Array(values.length).fill(null);
  let prev = null;
  let seed = 0;
  let count = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    if (prev == null) {
      seed += v;
      count += 1;
      if (count < period) continue;
      prev = seed / period;
      out[i] = prev;
      continue;
    }
    prev = (prev * (period - 1) + v) / period;
    out[i] = prev;
  }
  return out;
}

function computePlummer(bars, len = 34, multIn = 1.618, multEx = 2.618) {
  const hlc3 = bars.map((b) => (b.high + b.low + b.close) / 3);
  const basis = ema(hlc3, len);
  const vibUnit = rma(trueRange(bars), len);
  const upperIn = basis.map((v, i) => (v == null || vibUnit[i] == null ? null : v + vibUnit[i] * multIn));
  const lowerIn = basis.map((v, i) => (v == null || vibUnit[i] == null ? null : v - vibUnit[i] * multIn));
  const upperEx = basis.map((v, i) => (v == null || vibUnit[i] == null ? null : v + vibUnit[i] * multEx));
  const lowerEx = basis.map((v, i) => (v == null || vibUnit[i] == null ? null : v - vibUnit[i] * multEx));
  const signals = [];
  for (let i = 0; i < bars.length; i++) {
    if (lowerEx[i] == null || upperEx[i] == null) continue;
    const b = bars[i];
    if (b.low <= lowerEx[i] && b.close > lowerEx[i] && b.close > b.open) {
      signals.push({ time: b.time, side: "P+", index: i });
    }
    if (b.high >= upperEx[i] && b.close < upperEx[i] && b.close < b.open) {
      signals.push({ time: b.time, side: "P-", index: i });
    }
  }
  let last = bars.length - 1;
  while (last >= 0 && (basis[last] == null || vibUnit[last] == null)) last -= 1;
  let pulsePhase = "нет данных";
  if (last >= 0) {
    const b = bars[last];
    const slopeUp = last > 0 && basis[last - 1] != null ? basis[last] > basis[last - 1] : false;
    if (b.close >= upperEx[last]) pulsePhase = "Пик пульса (+2.618): истощение роста";
    else if (b.close >= upperIn[last] && slopeUp) pulsePhase = "Фаза расширения вверх (+1.618)";
    else if (b.close <= lowerEx[last]) pulsePhase = "Дно пульса (−2.618): истощение падения";
    else if (b.close <= lowerIn[last] && !slopeUp) pulsePhase = "Фаза сжатия вниз (−1.618)";
    else if (slopeUp) pulsePhase = "Восходящий ритм к верхней стенке";
    else pulsePhase = "Нисходящий ритм к нижней стенке";
  }
  return {
    basis, vibUnit, upperIn, lowerIn, upperEx, lowerEx, signals,
    status: {
      len,
      vibUnit: last >= 0 ? vibUnit[last] : null,
      basis: last >= 0 ? basis[last] : null,
      upperIn: last >= 0 ? upperIn[last] : null,
      lowerIn: last >= 0 ? lowerIn[last] : null,
      upperEx: last >= 0 ? upperEx[last] : null,
      lowerEx: last >= 0 ? lowerEx[last] : null,
      pulsePhase,
      close: last >= 0 ? bars[last].close : null,
      time: last >= 0 ? bars[last].time : null,
    },
  };
}

function applyPlummer(bars, eventMarkers) {
  plummerStatusEl.innerHTML = "";
  if (!plummerOn || !bars.length) return eventMarkers;
  const pack = computePlummer(bars, 34, 1.618, 2.618);
  const chartBg = getComputedStyle(root).getPropertyValue("--chart-bg").trim() || "#FCF8E3";
  const navy = getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E";
  const blue = "#2F6FED";
  const red = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";
  const green = getComputedStyle(root).getPropertyValue("--up").trim() || "#1B6B3A";
  const band = (hiKey, loKey, fill) => {
    plummerSeries[hiKey] = priceChart.addAreaSeries({
      lineColor: "rgba(0,0,0,0)",
      topColor: fill,
      bottomColor: fill,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    plummerSeries[loKey] = priceChart.addAreaSeries({
      lineColor: "rgba(0,0,0,0)",
      topColor: chartBg,
      bottomColor: chartBg,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
  };
  // Сначала внешние зоны, затем внутренняя, затем линии поверх.
  band("fillUpHi", "fillUpLo", "rgba(166, 38, 38, 0.12)");
  band("fillDnHi", "fillDnLo", "rgba(27, 107, 58, 0.12)");
  band("fillInnerHi", "fillInnerLo", "rgba(47, 111, 237, 0.10)");
  plummerSeries.fillUpHi.setData(linePoints(bars, pack.upperEx));
  plummerSeries.fillUpLo.setData(linePoints(bars, pack.upperIn));
  plummerSeries.fillDnHi.setData(linePoints(bars, pack.lowerIn));
  plummerSeries.fillDnLo.setData(linePoints(bars, pack.lowerEx));
  plummerSeries.fillInnerHi.setData(linePoints(bars, pack.upperIn));
  plummerSeries.fillInnerLo.setData(linePoints(bars, pack.lowerIn));
  plummerSeries.basis = priceChart.addLineSeries({ color: navy, lineWidth: 2, title: "Ось 0" });
  plummerSeries.upperIn = priceChart.addLineSeries({ color: blue, lineWidth: 1, title: "+1.618" });
  plummerSeries.lowerIn = priceChart.addLineSeries({ color: blue, lineWidth: 1, title: "-1.618" });
  plummerSeries.upperEx = priceChart.addLineSeries({ color: red, lineWidth: 2, title: "+2.618" });
  plummerSeries.lowerEx = priceChart.addLineSeries({ color: green, lineWidth: 2, title: "-2.618" });
  plummerSeries.basis.setData(linePoints(bars, pack.basis));
  plummerSeries.upperIn.setData(linePoints(bars, pack.upperIn));
  plummerSeries.lowerIn.setData(linePoints(bars, pack.lowerIn));
  plummerSeries.upperEx.setData(linePoints(bars, pack.upperEx));
  plummerSeries.lowerEx.setData(linePoints(bars, pack.lowerEx));
  const markers = pack.signals.map((sig) => ({
    time: sig.time,
    position: sig.side === "P+" ? "belowBar" : "aboveBar",
    color: sig.side === "P+" ? green : red,
    shape: sig.side === "P+" ? "arrowUp" : "arrowDown",
    text: sig.side,
  }));
  const st = pack.status;
  plummerStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Канал Пламмера · Пульс Жизни v3</h3>
    <p class="hint">Ритм ${st.len}: <span class="mono">basis = EMA(hlc3, ${st.len})</span>, <span class="mono">vibUnit = RMA(TR, ${st.len})</span>. Внутренний коридор ±1.618, внешний ±2.618. Сигналы P+/P− — отбой от экстремумов.</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>Единица вибрации</td><td class="mono">${fmt(st.vibUnit, 4)}</td></tr>
      <tr><td>Ось равновесия</td><td class="mono">${fmt(st.basis, 4)}</td></tr>
      <tr><td>Коридор +1.618 / −1.618</td><td class="mono">${fmt(st.upperIn, 4)} / ${fmt(st.lowerIn, 4)}</td></tr>
      <tr><td>Пределы +2.618 / −2.618</td><td class="mono">${fmt(st.upperEx, 4)} / ${fmt(st.lowerEx, 4)}</td></tr>
      <tr><td>Фаза Пульса Жизни</td><td><strong>${esc(st.pulsePhase)}</strong></td></tr>
      <tr><td>Сигналов P+ / P−</td><td class="mono">${pack.signals.filter((s) => s.side === "P+").length} / ${pack.signals.filter((s) => s.side === "P-").length}</td></tr>
    </table></div>`;
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function clearIndicatorOverlays() {
  Object.keys(kennedySeries).forEach((key) => {
    if (kennedySeries[key]) {
      try { priceChart.removeSeries(kennedySeries[key]); } catch (e) {}
      kennedySeries[key] = null;
    }
  });
  Object.keys(donchSeries).forEach((key) => {
    if (donchSeries[key]) {
      try { priceChart.removeSeries(donchSeries[key]); } catch (e) {}
      donchSeries[key] = null;
    }
  });
  Object.keys(fairSeries).forEach((key) => {
    if (fairSeries[key]) {
      try { priceChart.removeSeries(fairSeries[key]); } catch (e) {}
      fairSeries[key] = null;
    }
  });
  if (hillSeries.sma5) {
    try { priceChart.removeSeries(hillSeries.sma5); } catch (e) {}
    hillSeries.sma5 = null;
  }
  if (hillSeries.sma200) {
    try { priceChart.removeSeries(hillSeries.sma200); } catch (e) {}
    hillSeries.sma200 = null;
  }
  (hillSeries.clouds || []).forEach((series) => {
    try { priceChart.removeSeries(series); } catch (e) {}
  });
  hillSeries.clouds = [];
  Object.keys(plummerSeries).forEach((key) => {
    if (plummerSeries[key]) {
      try { priceChart.removeSeries(plummerSeries[key]); } catch (e) {}
      plummerSeries[key] = null;
    }
  });
  (gann9Series.lines || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  gann9Series.lines = [];
  (gann18Series.lines || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  gann18Series.lines = [];
  (borodenSeries.clusters || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  (borodenSeries.swings || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  (borodenSeries.timeMarks || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  borodenSeries.clusters = [];
  borodenSeries.swings = [];
  borodenSeries.timeMarks = [];
  (elliottSeries.lines || []).forEach((series) => { try { priceChart.removeSeries(series); } catch (e) {} });
  elliottSeries.lines = [];
  elliottSeries.labels = [];
  explainBoard.style.display = "none";
  kennedySummaryEl.innerHTML = "";
  kennedyStatusEl.innerHTML = "";
  donchStatusEl.innerHTML = "";
  pctRStatusEl.innerHTML = "";
  rsiStochStatusEl.innerHTML = "";
  rsxStatusEl.innerHTML = "";
  haStatusEl.innerHTML = "";
  hillStatusEl.innerHTML = "";
  fairStatusEl.innerHTML = "";
  plummerStatusEl.innerHTML = "";
  if (gannStatusEl) gannStatusEl.innerHTML = "";
  if (borodenStatusEl) borodenStatusEl.innerHTML = "";
  if (elliottStatusEl) elliottStatusEl.innerHTML = "";
  if (optStatusEl) optStatusEl.innerHTML = "";
  pctRBox.style.display = "none";
  rsiStochBox.style.display = "none";
  rsxBox.style.display = "none";
  haBox.style.display = "none";
  if (optBox) optBox.style.display = "none";
  haBox.classList.remove("ha-bull", "ha-bear");
  fairModeEl.style.display = fairOn ? "flex" : "none";
}

function refreshExplainVisibility() {
  const any = anyIndicatorOn();
  explainBoard.style.display = any ? "block" : "none";
  const titles = MODE_BADGES.filter((row) => row[1]()).map((row) => row[2]);
  explainTitle.textContent = titles.length ? ("Пояснения · " + titles.join(" · ")) : "Пояснения · индикаторы";
  refreshActiveBadges();
}

function renderKennedySummary(bars) {
  kennedySummaryEl.innerHTML = "";
  if (!bars.length || !anyIndicatorOn()) return;
  const trend = computeKennedy(bars);
  const donch = computeDonch(bars);
  const pr5 = percentR(bars, 5);
  const pr20 = percentR(bars, 20);
  const last = bars.length - 1;
  let active = "нет";
  if (trend && trend.status && trend.status.signal && trend.status.signal !== "Ожидание") active = "Trend: " + trend.status.signal;
  if (donch && donch.signals.length) {
    const lastSig = donch.signals[donch.signals.length - 1];
    if (lastSig.index >= last - 3) active = lastSig.side;
  }
  const maTrend = trend ? trend.status.maTrend : "нет";
  const posPct = donch ? donch.status.posPct : null;
  const zone = donch ? donch.status.zone : "нет";
  kennedySummaryEl.innerHTML = `
    <h3 style="font-size:13px;margin:0 0 6px">Сводка статуса · ${esc(currentTicker)}</h3>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Значение</th></tr>
      <tr><td>Тренд МА</td><td class="${maTrend === "Бычий" ? "up" : (maTrend === "Медвежий" ? "down" : "flat")}">${esc(maTrend)}</td></tr>
      <tr><td>Позиция в Donchian %</td><td class="mono">${fmt(posPct, 1)}% · ${esc(zone)}</td></tr>
      <tr><td>%R(5)</td><td class="mono">${fmt(pr5[last], 2)}</td></tr>
      <tr><td>%R(20)</td><td class="mono">${fmt(pr20[last], 2)}</td></tr>
      <tr><td>Активный сигнал</td><td><strong>${esc(active)}</strong></td></tr>
    </table></div>`;
}

function ensureRsiStochChart() {
  if (rsiStochChart) return;
  rsiStochChart = LightweightCharts.createChart(rsiStochChartEl, Object.assign(chartBase(160), {
    height: 160,
    rightPriceScale: {
      borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856",
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
  }));
  const zoneArea = (top, bottom) => rsiStochChart.addAreaSeries({
    lineColor: "rgba(0,0,0,0)",
    topColor: top,
    bottomColor: bottom,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  // Сначала медвежий коридор 20–60, затем бычий 40–80, маски снизу отсекают заливку.
  rsiZoneBearHi = zoneArea("rgba(166, 38, 38, 0.16)", "rgba(166, 38, 38, 0.16)");
  rsiZoneBearLo = zoneArea("rgba(252, 248, 227, 1)", "rgba(252, 248, 227, 1)");
  rsiZoneBullHi = zoneArea("rgba(29, 62, 110, 0.16)", "rgba(29, 62, 110, 0.16)");
  rsiZoneBullLo = zoneArea("rgba(252, 248, 227, 1)", "rgba(252, 248, 227, 1)");
  rsiStochMain = rsiStochChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E",
    lineWidth: 2,
    priceLineVisible: false,
  });
  rsiStochSec = rsiStochChart.addLineSeries({
    color: "#1C1915",
    lineWidth: 1,
    priceLineVisible: false,
  });
  rsiStochThird = rsiStochChart.addLineSeries({
    color: "#1C1915",
    lineWidth: 3,
    priceLineVisible: false,
  });
  const dash = () => rsiStochChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38",
    lineWidth: 1,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  });
  rsiStochLvlA = dash();
  rsiStochLvlB = dash();
  rsiStochLvlC = dash();
  bindRangeSync(rsiStochChart); bindCrosshairSync(rsiStochChart);
}

function applyRsiStochPanel(bars) {
  rsiStochStatusEl.innerHTML = "";
  if (!rsiStochOn || !bars.length) {
    rsiStochBox.style.display = "none";
    return;
  }
  rsiStochBox.style.display = "block";
  ensureRsiStochChart();
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E";
  const ink = getComputedStyle(root).getPropertyValue("--ink").trim() || "#1C1915";
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38";
  const paper = getComputedStyle(root).getPropertyValue("--chart-bg").trim() || getComputedStyle(root).getPropertyValue("--card").trim() || "#FCF8E3";
  rsiStochChart.applyOptions(Object.assign(chartBase(160), { height: 160 }));
  rsiStochMain.applyOptions({ color: blue, lineWidth: 2 });
  rsiStochSec.applyOptions({ color: ink, lineWidth: 1 });
  rsiStochThird.applyOptions({ color: ink, lineWidth: 3 });
  [rsiStochLvlA, rsiStochLvlB, rsiStochLvlC].forEach((series) => series.applyOptions({ color: muted, lineStyle: 2 }));
  rsiZoneBearHi.applyOptions({ topColor: "rgba(166, 38, 38, 0.16)", bottomColor: "rgba(166, 38, 38, 0.16)", lineColor: "rgba(0,0,0,0)" });
  rsiZoneBullHi.applyOptions({ topColor: "rgba(29, 62, 110, 0.16)", bottomColor: "rgba(29, 62, 110, 0.16)", lineColor: "rgba(0,0,0,0)" });
  rsiZoneBearLo.applyOptions({ topColor: paper, bottomColor: paper, lineColor: "rgba(0,0,0,0)" });
  rsiZoneBullLo.applyOptions({ topColor: paper, bottomColor: paper, lineColor: "rgba(0,0,0,0)" });
  const closes = bars.map((b) => b.close);
  const rsi = rsiWilder(closes, 14);
  const rsiSma9 = sma(rsi, 9);
  const rsiEma45 = ema(rsi, 45);
  const stoch = stochastic(bars, 8, 5, 3);
  const lvl = (seriesArr, level) => bars.map((b, i) => (seriesArr[i] == null ? null : { time: b.time, value: level })).filter(Boolean);
  let note = "";
  let lastIdx = bars.length - 1;
  if (rsiStochMode === "rsi") {
    rsiZoneBearHi.setData(lvl(rsi, 60));
    rsiZoneBearLo.setData(lvl(rsi, 20));
    rsiZoneBullHi.setData(lvl(rsi, 80));
    rsiZoneBullLo.setData(lvl(rsi, 40));
    rsiStochMain.setData(linePoints(bars, rsi));
    rsiStochSec.setData(linePoints(bars, rsiSma9));
    rsiStochThird.setData(linePoints(bars, rsiEma45));
    rsiStochLvlA.setData(lvl(rsi, 70));
    rsiStochLvlB.setData(lvl(rsi, 50));
    rsiStochLvlC.setData(lvl(rsi, 25));
    while (lastIdx >= 0 && rsi[lastIdx] == null) lastIdx -= 1;
    const r = lastIdx >= 0 ? rsi[lastIdx] : null;
    const s9 = lastIdx >= 0 ? rsiSma9[lastIdx] : null;
    const e45 = lastIdx >= 0 ? rsiEma45[lastIdx] : null;
    const fan = r != null && s9 != null && e45 != null && r > s9 && s9 > e45;
    if (r == null) note = "RSI ещё не посчитан";
    else if (r > 70) note = `перегрев RSI > 70 (сейчас ${fmt(r, 1)})`;
    else if (r < 25) note = `перепроданность RSI < 25 (сейчас ${fmt(r, 1)})`;
    else note = `RSI в рабочей зоне (${fmt(r, 1)})`;
    if (fan) note += " · бычий веер RSI > SMA9 > EMA45";
    else if (r != null && s9 != null && e45 != null && r < s9 && s9 < e45) note += " · медвежий веер RSI < SMA9 < EMA45";
    else if (r != null && s9 != null) note += r > s9 ? " · RSI выше SMA9" : " · RSI ниже SMA9";
    let zoneMode = "нет RSI";
    if (r != null && r >= 50) zoneMode = "БЫЧИЙ 40–80";
    else if (r != null && r < 50) zoneMode = "МЕДВЕЖИЙ 20–60";
    rsiStochStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Панель RSI + Stoch · RSI</h3>
      <p class="hint">Kennedy RSI/Stoch pane: RSI(14), SMA9 и EMA45, уровни 70 / 50 / 25; заливка зон 40–80 (бычья) и 20–60 (медвежья).</p>
      <div class="scroll"><table class="grid">
        <tr><th>Параметр</th><th>Статус</th></tr>
        <tr><td>RSI / SMA9 / EMA45</td><td class="mono">${fmt(r, 2)} / ${fmt(s9, 2)} / ${fmt(e45, 2)}</td></tr>
        <tr><td>Диагностика</td><td>${esc(note)}</td></tr>
        <tr><td>Режим зон RSI</td><td>${esc(zoneMode)}</td></tr>
      </table></div>`;
  } else {
    rsiZoneBearHi.setData([]);
    rsiZoneBearLo.setData([]);
    rsiZoneBullHi.setData([]);
    rsiZoneBullLo.setData([]);
    rsiStochMain.setData(linePoints(bars, stoch.k));
    rsiStochSec.setData(linePoints(bars, stoch.d));
    rsiStochThird.setData([]);
    rsiStochLvlA.setData(lvl(stoch.k, 80));
    rsiStochLvlB.setData(lvl(stoch.k, 20));
    rsiStochLvlC.setData([]);
    while (lastIdx >= 0 && stoch.k[lastIdx] == null) lastIdx -= 1;
    const k = lastIdx >= 0 ? stoch.k[lastIdx] : null;
    const d = lastIdx >= 0 ? stoch.d[lastIdx] : null;
    const prevK = lastIdx > 0 ? stoch.k[lastIdx - 1] : null;
    const prevD = lastIdx > 0 ? stoch.d[lastIdx - 1] : null;
    if (k == null || d == null) note = "Stochastic ещё не посчитан";
    else if (prevK != null && prevD != null && prevK <= prevD && k > d) note = `%K пересёк %D снизу вверх (${fmt(k, 1)} > ${fmt(d, 1)})`;
    else if (prevK != null && prevD != null && prevK >= prevD && k < d) note = `%K пересёк %D сверху вниз (${fmt(k, 1)} < ${fmt(d, 1)})`;
    else if (k > d) note = `%K выше %D (${fmt(k, 1)} / ${fmt(d, 1)}) — бычий уклон`;
    else if (k < d) note = `%K ниже %D (${fmt(k, 1)} / ${fmt(d, 1)}) — медвежий уклон`;
    else note = `%K и %D совпали (${fmt(k, 1)})`;
    if (k != null && k > 80) note += " · зона перекупленности > 80";
    if (k != null && k < 20) note += " · зона перепроданности < 20";
    rsiStochStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Панель RSI + Stoch · Stochastic</h3>
      <p class="hint">Kennedy RSI/Stoch pane: Stochastic(8,5,3), %K синий, %D чёрный, уровни 80 / 20.</p>
      <div class="scroll"><table class="grid">
        <tr><th>Параметр</th><th>Статус</th></tr>
        <tr><td>%K / %D</td><td class="mono">${fmt(k, 2)} / ${fmt(d, 2)}</td></tr>
        <tr><td>Диагностика</td><td>${esc(note)}</td></tr>
      </table></div>`;
  }
  rsiStochChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
  try {
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) rsiStochChart.timeScale().setVisibleLogicalRange(range);
  } catch (e) {}
}

function ensureHaChart() {
  if (haChart) return;
  haChart = LightweightCharts.createChart(haChartEl, Object.assign(chartBase(220), { height: 220 }));
  haCandleSeries = haChart.addCandlestickSeries(candleOptions());
  haEmaCloseLine = haChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E",
    lineWidth: 2,
    title: "EMA9 HA_Close",
  });
  haEmaOpenLine = haChart.addLineSeries({
    color: "#1C1915",
    lineWidth: 2,
    title: "EMA9 HA_Open",
  });
  bindRangeSync(haChart); bindCrosshairSync(haChart);
}

function applyHaPanel(bars) {
  haStatusEl.innerHTML = "";
  haBox.classList.remove("ha-bull", "ha-bear");
  if (!haOn || !bars.length) {
    haBox.style.display = "none";
    return;
  }
  haBox.style.display = "block";
  ensureHaChart();
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E";
  const ink = getComputedStyle(root).getPropertyValue("--ink").trim() || "#1C1915";
  haChart.applyOptions(Object.assign(chartBase(220), { height: 220 }));
  haCandleSeries.applyOptions(candleOptions());
  haEmaCloseLine.applyOptions({ color: blue, lineWidth: 2 });
  haEmaOpenLine.applyOptions({ color: ink, lineWidth: 2 });
  const ha = heikinAshi(bars);
  const haOpen = ha.map((b) => b.open);
  const haClose = ha.map((b) => b.close);
  const emaClose = ema(haClose, 9);
  const emaOpen = ema(haOpen, 9);
  haCandleSeries.setData(ha.map((b) => ({
    time: b.time,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  })));
  haEmaCloseLine.setData(linePoints(ha, emaClose));
  haEmaOpenLine.setData(linePoints(ha, emaOpen));
  haChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
  try {
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) haChart.timeScale().setVisibleLogicalRange(range);
  } catch (e) {}
  const last = ha.length - 1;
  let i = last;
  while (i >= 0 && (emaClose[i] == null || emaOpen[i] == null)) i -= 1;
  const ribbonBull = i >= 0 && emaClose[i] > emaOpen[i];
  const ribbonBear = i >= 0 && emaClose[i] < emaOpen[i];
  if (ribbonBull) haBox.classList.add("ha-bull");
  if (ribbonBear) haBox.classList.add("ha-bear");
  const ribbonText = ribbonBull
    ? "бычья лента: EMA9(HA_Close) > EMA9(HA_Open)"
    : (ribbonBear ? "медвежья лента: EMA9(HA_Close) < EMA9(HA_Open)" : "лента плоская / мало данных");
  document.getElementById("haRibbonHint").textContent = ribbonText;
  haStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Heikin-Ashi + EMA9</h3>
    <p class="hint">Усреднённые свечи HA_Open/High/Low/Close и лента EMA(9) от HA_Close (синяя) и HA_Open (чёрная).</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>HA close</td><td class="mono">${fmt(i >= 0 ? ha[i].close : null, 4)}</td></tr>
      <tr><td>EMA9 HA_Close / HA_Open</td><td class="mono">${fmt(i >= 0 ? emaClose[i] : null, 4)} / ${fmt(i >= 0 ? emaOpen[i] : null, 4)}</td></tr>
      <tr><td>Режим ленты</td><td class="${ribbonBull ? "up" : (ribbonBear ? "down" : "flat")}">${esc(ribbonText)}</td></tr>
    </table></div>`;
}

function ensureRsxChart() {
  if (rsxChart) return;
  rsxChart = LightweightCharts.createChart(rsxChartEl, Object.assign(chartBase(160), {
    height: 160,
    rightPriceScale: {
      borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856",
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
  }));
  rsxBreakHist = rsxChart.addHistogramSeries({
    priceFormat: { type: "price", precision: 1, minMove: 0.1 },
    base: 50,
    autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
  });
  rsxLine = rsxChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E",
    lineWidth: 2,
    priceLineVisible: false,
  });
  rsxLevel50 = rsxChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38",
    lineWidth: 1,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  });
  bindRangeSync(rsxChart); bindCrosshairSync(rsxChart);
}

function computeRsxPack(bars) {
  const closes = bars.map((b) => b.close);
  const rsx = jurikRsx(closes, 14);
  const breaks = [];
  const tint = new Array(bars.length).fill(null);
  for (let i = 2; i < bars.length; i++) {
    const r = rsx[i], r1 = rsx[i - 1], r2 = rsx[i - 2];
    if (r == null || r1 == null || r2 == null) continue;
    if (r > r1 && r1 <= r2) {
      breaks.push({ time: bars[i].time, side: "up", index: i });
      for (let k = 0; k < 5 && i + k < bars.length; k++) {
        if (rsx[i + k] != null) tint[i + k] = "up";
      }
    } else if (r < r1 && r1 >= r2) {
      breaks.push({ time: bars[i].time, side: "down", index: i });
      for (let k = 0; k < 5 && i + k < bars.length; k++) {
        if (rsx[i + k] != null) tint[i + k] = "down";
      }
    }
  }
  let last = bars.length - 1;
  while (last >= 0 && rsx[last] == null) last -= 1;
  const r = last >= 0 ? rsx[last] : null;
  const r1 = last >= 1 ? rsx[last - 1] : null;
  const r2 = last >= 2 ? rsx[last - 2] : null;
  let hod = "нет данных";
  let konets = "—";
  if (r != null && r1 != null && r2 != null) {
    const d1 = r - r1;
    const d2 = r1 - r2;
    if (d1 > 0 && d2 > 0) hod = "рост";
    else if (d1 > 0 && d2 <= 0) { hod = "падение слабеет"; konets = "падение может кончаться"; }
    else if (d1 < 0 && d2 < 0) hod = "падение";
    else if (d1 < 0 && d2 >= 0) { hod = "рост слабеет"; konets = "рост может кончаться"; }
    else hod = "плоский";
  } else if (r != null && r1 != null) {
    hod = r > r1 ? "рост" : (r < r1 ? "падение" : "плоский");
  }
  const sila = r != null && Math.abs(r - 50) >= 15 ? "сильный" : "обычный";
  return { rsx, breaks, tint, status: { value: r, hod, sila, konets, time: last >= 0 ? bars[last].time : null } };
}

function applyRsxPanel(bars, eventMarkers) {
  rsxStatusEl.innerHTML = "";
  if (!rsxOn || !bars.length) {
    rsxBox.style.display = "none";
    return eventMarkers;
  }
  rsxBox.style.display = "block";
  ensureRsxChart();
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E";
  const up = getComputedStyle(root).getPropertyValue("--up").trim() || "#1B6B3A";
  const down = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38";
  rsxChart.applyOptions(Object.assign(chartBase(160), { height: 160 }));
  rsxLine.applyOptions({ color: blue, lineWidth: 2 });
  rsxLevel50.applyOptions({ color: muted, lineStyle: 2 });
  const pack = computeRsxPack(bars);
  rsxLine.setData(linePoints(bars, pack.rsx));
  rsxLevel50.setData(bars.map((b, i) => (pack.rsx[i] == null ? null : { time: b.time, value: 50 })).filter(Boolean));
  const hist = [];
  for (let i = 0; i < bars.length; i++) {
    if (pack.rsx[i] == null || !pack.tint[i]) continue;
    hist.push({
      time: bars[i].time,
      value: pack.rsx[i],
      color: pack.tint[i] === "up" ? "rgba(27, 107, 58, 0.35)" : "rgba(166, 38, 38, 0.35)",
    });
  }
  rsxBreakHist.setData(hist);
  rsxChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
  try {
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) rsxChart.timeScale().setVisibleLogicalRange(range);
  } catch (e) {}
  const st = pack.status;
  const hodCls = st.hod.indexOf("рост") >= 0 ? "up" : (st.hod.indexOf("падение") >= 0 ? "down" : "flat");
  document.getElementById("rsxHint").textContent = `RSX ${fmt(st.value, 1)} · ${st.hod} · ${st.sila}`;
  rsxStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Jurik RSX (14) · Ход / Сила / Слом</h3>
    <p class="hint">Тройное сглаживание Jurik RSX(14), ось 50. Зелёный/красный сегмент — слом наклона на 5 баров. Памятка: <strong>слом без свечи не вход</strong>.</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>RSX</td><td class="mono">${fmt(st.value, 2)}</td></tr>
      <tr><td>Ход</td><td class="${hodCls}">${esc(st.hod)}</td></tr>
      <tr><td>Сила</td><td>${esc(st.sila)}</td></tr>
      <tr><td>Конец</td><td>${esc(st.konets)}</td></tr>
      <tr><td>Сломов ↑ / ↓</td><td class="mono">${pack.breaks.filter((b) => b.side === "up").length} / ${pack.breaks.filter((b) => b.side === "down").length}</td></tr>
      <tr><td>Памятка</td><td>слом без свечи не вход</td></tr>
    </table></div>`;
  const markers = pack.breaks.map((sig) => ({
    time: sig.time,
    position: sig.side === "up" ? "belowBar" : "aboveBar",
    color: sig.side === "up" ? up : down,
    shape: sig.side === "up" ? "arrowUp" : "arrowDown",
    text: sig.side === "up" ? "RSX↑" : "RSX↓",
  }));
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function findPivotsHill(bars, left = 10, right = 5) {
  const out = [];
  for (let i = left; i < bars.length - right; i++) {
    let isHigh = true;
    let isLow = true;
    for (let j = i - left; j <= i + right; j++) {
      if (j === i) continue;
      if (bars[j].high > bars[i].high) isHigh = false;
      if (bars[j].low < bars[i].low) isLow = false;
      if (!isHigh && !isLow) break;
    }
    if (isHigh) out.push({ time: bars[i].time, price: bars[i].high, side: "H", index: i });
    if (isLow) out.push({ time: bars[i].time, price: bars[i].low, side: "L", index: i });
  }
  return out;
}

function applyHillCloud(bars, eventMarkers) {
  hillStatusEl.innerHTML = "";
  if (!hillOn || !bars.length) return eventMarkers;
  const closes = bars.map((b) => b.close);
  const sma5 = sma(closes, 5);
  const sma200 = sma(closes, 200);
  const paper = getComputedStyle(root).getPropertyValue("--chart-bg").trim()
    || getComputedStyle(root).getPropertyValue("--card").trim()
    || "#FCF8E3";
  const purple = "rgba(92, 55, 140, 0.28)";
  const red = "rgba(166, 38, 38, 0.28)";
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38";
  const up = getComputedStyle(root).getPropertyValue("--up").trim() || "#1B6B3A";
  const down = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";

  const addCloud = (from, to, bull) => {
    if (to < from) return;
    const fill = bull ? purple : red;
    const hiSer = priceChart.addAreaSeries({
      lineColor: "rgba(0,0,0,0)",
      topColor: fill,
      bottomColor: fill,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const loSer = priceChart.addAreaSeries({
      lineColor: "rgba(0,0,0,0)",
      topColor: paper,
      bottomColor: paper,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const hiData = [];
    const loData = [];
    for (let i = from; i <= to; i++) {
      if (sma5[i] == null || sma200[i] == null) continue;
      hiData.push({ time: bars[i].time, value: Math.max(sma5[i], sma200[i]) });
      loData.push({ time: bars[i].time, value: Math.min(sma5[i], sma200[i]) });
    }
    if (hiData.length) {
      hiSer.setData(hiData);
      loSer.setData(loData);
      hillSeries.clouds.push(hiSer, loSer);
    } else {
      try { priceChart.removeSeries(hiSer); } catch (e) {}
      try { priceChart.removeSeries(loSer); } catch (e) {}
    }
  };

  let segStart = -1;
  let segBull = null;
  for (let i = 0; i < bars.length; i++) {
    if (sma5[i] == null || sma200[i] == null) {
      if (segStart >= 0) {
        addCloud(segStart, i - 1, segBull);
        segStart = -1;
        segBull = null;
      }
      continue;
    }
    const bull = sma5[i] > sma200[i];
    if (segStart < 0) {
      segStart = i;
      segBull = bull;
    } else if (bull !== segBull) {
      addCloud(segStart, i - 1, segBull);
      segStart = i;
      segBull = bull;
    }
  }
  if (segStart >= 0) addCloud(segStart, bars.length - 1, segBull);

  hillSeries.sma5 = priceChart.addLineSeries({ color: "#5C378C", lineWidth: 2, title: "SMA5" });
  hillSeries.sma200 = priceChart.addLineSeries({ color: muted, lineWidth: 2, title: "SMA200" });
  hillSeries.sma5.setData(linePoints(bars, sma5));
  hillSeries.sma200.setData(linePoints(bars, sma200));

  const pctAbove = bars.map((_, i) => {
    if (sma5[i] == null || sma200[i] == null || sma200[i] === 0) return null;
    return ((sma5[i] - sma200[i]) / sma200[i]) * 100;
  });
  const markers = [];
  for (let i = 1; i < bars.length; i++) {
    if (pctAbove[i] == null) continue;
    const prev = pctAbove[i - 1];
    if (pctAbove[i] >= 1.0 && (prev == null || prev < 1.0)) {
      markers.push({
        time: bars[i].time,
        position: "belowBar",
        color: up,
        shape: "arrowUp",
        text: "ЛОНГ",
      });
    }
    if (pctAbove[i] <= -1.0 && (prev == null || prev > -1.0)) {
      markers.push({
        time: bars[i].time,
        position: "aboveBar",
        color: down,
        shape: "arrowDown",
        text: "ВЫХОД",
      });
    }
  }
  findPivotsHill(bars, 10, 5).forEach((pv) => {
    markers.push({
      time: pv.time,
      position: pv.side === "H" ? "aboveBar" : "belowBar",
      color: pv.side === "H" ? down : up,
      shape: "circle",
      text: fmt(pv.price, 2),
    });
  });

  let last = bars.length - 1;
  while (last >= 0 && (sma5[last] == null || sma200[last] == null)) last -= 1;
  const s5 = last >= 0 ? sma5[last] : null;
  const s200 = last >= 0 ? sma200[last] : null;
  const gap = last >= 0 ? pctAbove[last] : null;
  let mode = "нет SMA200";
  let modeCls = "flat";
  if (gap != null) {
    if (gap >= 1.0) {
      mode = "БЫЧИЙ тренд: держать по тренду";
      modeCls = "up";
    } else if (gap <= -1.0) {
      mode = "МЕДВЕЖИЙ тренд: вне рынка";
      modeCls = "down";
    } else {
      mode = "НЕЙТРАЛЬНО ±1%: ждать ясности";
      modeCls = "flat";
    }
  }
  hillStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Облако 5 vs 200 · Arthur Hill</h3>
    <p class="hint">SMA(5) / SMA(200), облако фиолетовое при SMA5&gt;SMA200 и красное при SMA5&lt;SMA200. ЛОНГ при разрыве ≥ +1%, ВЫХОД при ≤ −1%. Пивоты: 10 баров влево / 5 вправо.</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>SMA5 / SMA200</td><td class="mono">${fmt(s5, 4)} / ${fmt(s200, 4)}</td></tr>
      <tr><td>Разрыв pctAbove</td><td class="mono">${fmt(gap, 2)}%</td></tr>
      <tr><td>Режим 5 vs 200</td><td class="${modeCls}"><strong>${esc(mode)}</strong></td></tr>
      <tr><td>Сигналов ЛОНГ / ВЫХОД</td><td class="mono">${markers.filter((m) => m.text === "ЛОНГ").length} / ${markers.filter((m) => m.text === "ВЫХОД").length}</td></tr>
    </table></div>`;
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function applyFairRange(bars) {
  fairStatusEl.innerHTML = "";
  if (!fairOn || !bars.length) return;
  const down = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim() || "#1D3E6E";
  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  let avgHi;
  let avgLo;
  let modeLabel;
  if (fairMode === "sma20") {
    avgHi = sma(highs, 20);
    avgLo = sma(lows, 20);
    modeLabel = "SMA(20) High / Low";
  } else {
    avgHi = new Array(bars.length).fill(null);
    avgLo = new Array(bars.length).fill(null);
    let sumH = 0, sumL = 0;
    for (let i = 0; i < bars.length; i++) {
      sumH += highs[i];
      sumL += lows[i];
      avgHi[i] = sumH / (i + 1);
      avgLo[i] = sumL / (i + 1);
    }
    modeLabel = "накопленное среднее cum(High)/N · cum(Low)/N";
  }
  fairSeries.hi = priceChart.addLineSeries({ color: down, lineWidth: 2, title: "Avg High" });
  fairSeries.lo = priceChart.addLineSeries({ color: blue, lineWidth: 2, title: "Avg Low" });
  fairSeries.hi.setData(linePoints(bars, avgHi));
  fairSeries.lo.setData(linePoints(bars, avgLo));
  let i = bars.length - 1;
  while (i >= 0 && (avgHi[i] == null || avgLo[i] == null)) i -= 1;
  const close = i >= 0 ? bars[i].close : null;
  const hi = i >= 0 ? avgHi[i] : null;
  const lo = i >= 0 ? avgLo[i] : null;
  let where = "нет данных";
  let whereCls = "flat";
  if (close != null && hi != null && lo != null) {
    if (close > hi) { where = "выше среднего High"; whereCls = "down"; }
    else if (close < lo) { where = "ниже среднего Low"; whereCls = "up"; }
    else { where = "внутри коридора"; whereCls = "flat"; }
  }
  fairStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Диапазон справедливости · Avg High / Low</h3>
    <p class="hint">Красная — средний High, синяя — средний Low. Режим: ${esc(modeLabel)}.</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>Режим</td><td>${esc(modeLabel)}</td></tr>
      <tr><td>Avg High / Avg Low</td><td class="mono">${fmt(hi, 4)} / ${fmt(lo, 4)}</td></tr>
      <tr><td>Close</td><td class="mono">${fmt(close, 4)}</td></tr>
      <tr><td>Положение цены</td><td class="${whereCls}"><strong>${esc(where)}</strong></td></tr>
    </table></div>`;
}

function ensurePctRChart() {
  if (pctRChart) return;
  pctRChart = LightweightCharts.createChart(pctRChartEl, Object.assign(chartBase(160), {
    height: 160,
    rightPriceScale: {
      borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856",
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
  }));
  pctRHist = pctRChart.addHistogramSeries({
    priceFormat: { type: "price", precision: 1, minMove: 0.1 },
    base: 50,
    autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
  });
  pctRSmaLine = pctRChart.addLineSeries({
    color: "#1C1915",
    lineWidth: 2,
    priceLineVisible: false,
  });
  const dash = (value) => pctRChart.addLineSeries({
    color: getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38",
    lineWidth: 1,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  });
  pctRLevel80 = dash(80);
  pctRLevel50 = dash(50);
  pctRLevel20 = dash(20);
  bindRangeSync(pctRChart); bindCrosshairSync(pctRChart);
}

function applyPctRPanel(bars) {
  pctRStatusEl.innerHTML = "";
  if (!pctROn || !bars.length) {
    pctRBox.style.display = "none";
    return;
  }
  pctRBox.style.display = "block";
  ensurePctRChart();
  const up = getComputedStyle(root).getPropertyValue("--up").trim() || "#1B6B3A";
  const down = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";
  const ink = getComputedStyle(root).getPropertyValue("--ink").trim() || "#1C1915";
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38";
  pctRChart.applyOptions(Object.assign(chartBase(160), { height: 160 }));
  pctRSmaLine.applyOptions({ color: ink });
  [pctRLevel80, pctRLevel50, pctRLevel20].forEach((series) => series.applyOptions({ color: muted, lineStyle: 2 }));
  const values = percentR(bars, pctRPeriod);
  const avg = sma(values, 10);
  const hist = [];
  const smaPts = [];
  const lvl = (level) => bars.map((b, i) => (values[i] == null ? null : { time: b.time, value: level })).filter(Boolean);
  for (let i = 0; i < bars.length; i++) {
    if (values[i] == null) continue;
    hist.push({ time: bars[i].time, value: values[i], color: values[i] >= 50 ? up : down });
    if (avg[i] != null) smaPts.push({ time: bars[i].time, value: avg[i] });
  }
  pctRHist.setData(hist);
  pctRSmaLine.setData(smaPts);
  pctRLevel80.setData(lvl(80));
  pctRLevel50.setData(lvl(50));
  pctRLevel20.setData(lvl(20));
  pctRChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
  try {
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) pctRChart.timeScale().setVisibleLogicalRange(range);
  } catch (e) {}
  const last = bars.length - 1;
  let i = last;
  while (i >= 0 && values[i] == null) i -= 1;
  const v = i >= 0 ? values[i] : null;
  const s = i >= 0 ? avg[i] : null;
  const prevV = i > 0 ? values[i - 1] : null;
  const prevS = i > 0 ? avg[i - 1] : null;
  let note = "данных %R пока мало";
  if (v != null) {
    if (v > 80) note = `зона силы (> 80): %R(${pctRPeriod}) = ${fmt(v, 1)}`;
    else if (v < 20) note = `зона слабости (< 20): %R(${pctRPeriod}) = ${fmt(v, 1)}`;
    else if (v >= 50) note = `выше середины (50–80): %R(${pctRPeriod}) = ${fmt(v, 1)}`;
    else note = `ниже середины (20–50): %R(${pctRPeriod}) = ${fmt(v, 1)}`;
    if (prevV != null && prevS != null && s != null) {
      if (prevV <= prevS && v > s) note += ` · пересечение SMA10 снизу вверх`;
      else if (prevV >= prevS && v < s) note += ` · пересечение SMA10 сверху вниз`;
      else if (v > s) note += ` · %R выше своей SMA10`;
      else if (v < s) note += ` · %R ниже своей SMA10`;
    }
  }
  pctRStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Панель %R (${pctRPeriod})</h3>
    <p class="hint">Формула Kennedy PercentR: <span class="mono">100 * (Close − LL(N)) / (HH(N) − LL(N))</span>, линия — SMA(10).</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>Режим</td><td>${pctRPeriod === 5 ? "Быстрый %R(5)" : "Медленный %R(20)"}</td></tr>
      <tr><td>%R / SMA10</td><td class="mono">${fmt(v, 2)} / ${fmt(s, 2)}</td></tr>
      <tr><td>Интерпретация</td><td>${esc(note)}</td></tr>
    </table></div>`;
}

function computeKennedy(bars) {
  if (!bars.length) return null;
  const closes = bars.map((b) => b.close);
  const ha = heikinAshi(bars);
  const haOpen = ha.map((b) => b.open);
  const haClose = ha.map((b) => b.close);
  const ema5 = ema(closes, 5);
  const sma10 = sma(closes, 10);
  const sma30 = sma(closes, 30);
  const haEmaOpen = ema(haOpen, 9);
  const haEmaClose = ema(haClose, 9);
  const rsi = rsiWilder(closes, 14);
  const rsiSma9 = sma(rsi, 9);
  const rsiEma45 = ema(rsi, 45);
  const stoch = stochastic(bars, 8, 5, 3);
  const signals = [];
  for (let i = 1; i < bars.length; i++) {
    const k0 = stoch.k[i - 1], d0 = stoch.d[i - 1], k1 = stoch.k[i], d1 = stoch.d[i];
    if ([k0, d0, k1, d1, sma10[i], haEmaOpen[i], haEmaClose[i], rsi[i]].some((v) => v == null)) continue;
    const crossUp = k0 <= d0 && k1 > d1;
    const crossDown = k0 >= d0 && k1 < d1;
    if (bars[i].close > sma10[i] && haEmaClose[i] > haEmaOpen[i] && rsi[i] < 70 && crossUp) {
      signals.push({ time: bars[i].time, side: "L", index: i });
    }
    if (bars[i].close < sma10[i] && haEmaClose[i] < haEmaOpen[i] && rsi[i] > 25 && crossDown) {
      signals.push({ time: bars[i].time, side: "S", index: i });
    }
  }
  const last = bars.length - 1;
  let maTrend = "Боковик";
  if (ema5[last] != null && sma10[last] != null && sma30[last] != null) {
    if (ema5[last] > sma10[last] && sma10[last] > sma30[last]) maTrend = "Бычий";
    else if (ema5[last] < sma10[last] && sma10[last] < sma30[last]) maTrend = "Медвежий";
  }
  let priceVsSma10 = "нет";
  if (sma10[last] != null) priceVsSma10 = bars[last].close > sma10[last] ? "выше SMA10" : (bars[last].close < sma10[last] ? "ниже SMA10" : "на SMA10");
  let haBand = "нет";
  if (haEmaClose[last] != null && haEmaOpen[last] != null) {
    haBand = haEmaClose[last] > haEmaOpen[last] ? "HA_EMA_Close > HA_EMA_Open (бычья лента)" : (haEmaClose[last] < haEmaOpen[last] ? "HA_EMA_Close < HA_EMA_Open (медвежья лента)" : "HA лента плоская");
  }
  let signal = "Ожидание";
  const lastSig = signals.length ? signals[signals.length - 1] : null;
  if (lastSig && lastSig.index >= last - 3) signal = lastSig.side === "L" ? "LONG" : "SHORT";
  else if (
    sma10[last] != null && haEmaClose[last] != null && haEmaOpen[last] != null && rsi[last] != null &&
    stoch.k[last] != null && stoch.d[last] != null
  ) {
    if (bars[last].close > sma10[last] && haEmaClose[last] > haEmaOpen[last] && rsi[last] < 70 && stoch.k[last] > stoch.d[last]) signal = "LONG";
    else if (bars[last].close < sma10[last] && haEmaClose[last] < haEmaOpen[last] && rsi[last] > 25 && stoch.k[last] < stoch.d[last]) signal = "SHORT";
  }
  return {
    ema5, sma10, sma30, haEmaOpen, haEmaClose, rsi, rsiSma9, rsiEma45, stoch, signals,
    status: {
      maTrend, priceVsSma10, haBand,
      rsi: rsi[last], rsiSma9: rsiSma9[last], rsiEma45: rsiEma45[last],
      stochK: stoch.k[last], stochD: stoch.d[last],
      signal, close: bars[last].close, time: bars[last].time,
    },
  };
}

function applyKennedy(bars, eventMarkers) {
  if (!kennedyOn || !bars.length) {
    return eventMarkers;
  }
  const pack = computeKennedy(bars);
  if (!pack) return eventMarkers;
  const up = getComputedStyle(root).getPropertyValue("--up").trim();
  const down = getComputedStyle(root).getPropertyValue("--down").trim();
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim();
  const warn = getComputedStyle(root).getPropertyValue("--warn").trim();
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim();
  kennedySeries.ema5 = priceChart.addLineSeries({ color: blue, lineWidth: 2, title: "EMA5" });
  kennedySeries.sma10 = priceChart.addLineSeries({ color: warn, lineWidth: 2, title: "SMA10" });
  kennedySeries.sma30 = priceChart.addLineSeries({ color: muted, lineWidth: 2, title: "SMA30" });
  kennedySeries.haOpen = priceChart.addLineSeries({ color: down, lineWidth: 1, lineStyle: 2, title: "HA EMA9 Open" });
  kennedySeries.haClose = priceChart.addLineSeries({ color: up, lineWidth: 1, lineStyle: 2, title: "HA EMA9 Close" });
  kennedySeries.ema5.setData(linePoints(bars, pack.ema5));
  kennedySeries.sma10.setData(linePoints(bars, pack.sma10));
  kennedySeries.sma30.setData(linePoints(bars, pack.sma30));
  kennedySeries.haOpen.setData(linePoints(bars, pack.haEmaOpen));
  kennedySeries.haClose.setData(linePoints(bars, pack.haEmaClose));
  const sigMarkers = pack.signals.map((sig) => ({
    time: sig.time,
    position: sig.side === "L" ? "belowBar" : "aboveBar",
    color: sig.side === "L" ? up : down,
    shape: sig.side === "L" ? "arrowUp" : "arrowDown",
    text: sig.side,
  }));
  const st = pack.status;
  const toneCls = st.signal === "LONG" ? "up" : (st.signal === "SHORT" ? "down" : "flat");
  kennedyStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:0 0 6px">Kennedy Trend</h3>
    <p class="hint">Тикер <span class="mono">${esc(currentTicker)}</span> · бар ${esc(st.time)} · close ${fmt(st.close, 4)}. EMA5 / SMA10 / SMA30 + лента EMA(9) Heikin-Ashi, RSI(14)+SMA9/EMA45, Stochastic(8,5,3).</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>Тренд МА</td><td class="${st.maTrend === "Бычий" ? "up" : (st.maTrend === "Медвежий" ? "down" : "flat")}">${esc(st.maTrend)}</td></tr>
      <tr><td>Цена vs SMA10</td><td>${esc(st.priceVsSma10)}</td></tr>
      <tr><td>HA лента EMA9</td><td>${esc(st.haBand)}</td></tr>
      <tr><td>RSI(14)</td><td class="mono">${fmt(st.rsi, 2)}</td></tr>
      <tr><td>RSI SMA9 / EMA45</td><td class="mono">${fmt(st.rsiSma9, 2)} / ${fmt(st.rsiEma45, 2)}</td></tr>
      <tr><td>Stoch %K / %D</td><td class="mono">${fmt(st.stochK, 2)} / ${fmt(st.stochD, 2)}</td></tr>
      <tr><td>Текущий сигнал</td><td class="${toneCls}"><strong>${esc(st.signal)}</strong></td></tr>
      <tr><td>Сигналов L/S на ряде</td><td class="mono">${pack.signals.filter((s) => s.side === "L").length} / ${pack.signals.filter((s) => s.side === "S").length}</td></tr>
    </table></div>`;
  return eventMarkers.concat(sigMarkers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function highestLowest(bars, i, period) {
  const from = Math.max(0, i - period + 1);
  let hi = -Infinity, lo = Infinity;
  for (let j = from; j <= i; j++) {
    hi = Math.max(hi, bars[j].high);
    lo = Math.min(lo, bars[j].low);
  }
  return { hi, lo };
}

function percentR(bars, period) {
  return bars.map((_, i) => {
    if (i < period - 1) return null;
    const { hi, lo } = highestLowest(bars, i, period);
    if (hi === lo) return 50;
    return 100 * ((bars[i].close - lo) / (hi - lo));
  });
}

function bodyEngulfing(prev, curr) {
  if (!prev || !curr) return null;
  const prevBear = prev.close < prev.open;
  const prevBull = prev.close > prev.open;
  const currBull = curr.close > curr.open;
  const currBear = curr.close < curr.open;
  const prevTop = Math.max(prev.open, prev.close);
  const prevBot = Math.min(prev.open, prev.close);
  const currTop = Math.max(curr.open, curr.close);
  const currBot = Math.min(curr.open, curr.close);
  if (prevBear && currBull && currBot <= prevBot && currTop >= prevTop) return "EB";
  if (prevBull && currBear && currBot <= prevBot && currTop >= prevTop) return "ES";
  return null;
}

function computeDonch(bars) {
  if (!bars.length) return null;
  const period = 20;
  const hh = new Array(bars.length).fill(null);
  const ll = new Array(bars.length).fill(null);
  const mid = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) continue;
    const range = highestLowest(bars, i, period);
    hh[i] = range.hi;
    ll[i] = range.lo;
    mid[i] = (range.hi + range.lo) / 2;
  }
  const pr5 = percentR(bars, 5);
  const pr20 = percentR(bars, 20);
  const pr5Sma = sma(pr5, 10);
  const pr20Sma = sma(pr20, 10);
  const signals = [];
  const engulf = [];
  for (let i = 1; i < bars.length; i++) {
    const kind = bodyEngulfing(bars[i - 1], bars[i]);
    if (kind) engulf.push({ time: bars[i].time, side: kind, index: i });
    if (hh[i] == null || ll[i] == null) continue;
    const touchLow = bars[i].low <= ll[i] * 1.002;
    const touchHigh = bars[i].high >= hh[i] * 0.998;
    const crossUp = pr5[i - 1] != null && pr5Sma[i - 1] != null && pr5[i] != null && pr5Sma[i] != null
      && pr5[i - 1] <= pr5Sma[i - 1] && pr5[i] > pr5Sma[i];
    const crossDown = pr5[i - 1] != null && pr5Sma[i - 1] != null && pr5[i] != null && pr5Sma[i] != null
      && pr5[i - 1] >= pr5Sma[i - 1] && pr5[i] < pr5Sma[i];
    if (touchLow && (kind === "EB" || (crossUp && pr20[i] != null && pr20[i] < 50))) {
      signals.push({ time: bars[i].time, side: "DC+", index: i });
    }
    if (touchHigh && (kind === "ES" || (crossDown && pr20[i] != null && pr20[i] > 50))) {
      signals.push({ time: bars[i].time, side: "DC-", index: i });
    }
  }
  const last = bars.length - 1;
  const width = hh[last] != null && ll[last] != null ? (hh[last] - ll[last]) : null;
  const posPct = width && width > 0 ? 100 * ((bars[last].close - ll[last]) / width) : null;
  let zone = "середина канала";
  if (posPct != null) {
    if (posPct >= 80) zone = "верх канала / зона силы";
    else if (posPct <= 20) zone = "низ канала / зона слабости";
    else if (posPct >= 50) zone = "выше середины";
    else zone = "ниже середины";
  }
  return {
    hh, mid, ll, pr5, pr20, pr5Sma, pr20Sma, signals, engulf,
    status: {
      hh: hh[last], mid: mid[last], ll: ll[last], posPct, zone,
      pr5: pr5[last], pr5Sma: pr5Sma[last], pr20: pr20[last], pr20Sma: pr20Sma[last],
      close: bars[last].close, time: bars[last].time,
    },
  };
}

function applyDonch(bars, eventMarkers) {
  if (!donchOn || !bars.length) return eventMarkers;
  const pack = computeDonch(bars);
  if (!pack) return eventMarkers;
  const up = getComputedStyle(root).getPropertyValue("--up").trim();
  const down = getComputedStyle(root).getPropertyValue("--down").trim();
  const blue = getComputedStyle(root).getPropertyValue("--blue").trim();
  const muted = getComputedStyle(root).getPropertyValue("--muted").trim();
  donchSeries.hh = priceChart.addLineSeries({ color: down, lineWidth: 2, title: "Donch HH" });
  donchSeries.mid = priceChart.addLineSeries({ color: blue, lineWidth: 1, lineStyle: 2, title: "Donch Mid" });
  donchSeries.ll = priceChart.addLineSeries({ color: up, lineWidth: 2, title: "Donch LL" });
  donchSeries.hh.setData(linePoints(bars, pack.hh));
  donchSeries.mid.setData(linePoints(bars, pack.mid));
  donchSeries.ll.setData(linePoints(bars, pack.ll));
  const markers = [];
  pack.engulf.forEach((sig) => {
    markers.push({
      time: sig.time,
      position: sig.side === "EB" ? "belowBar" : "aboveBar",
      color: sig.side === "EB" ? up : down,
      shape: "circle",
      text: sig.side,
    });
  });
  pack.signals.forEach((sig) => {
    markers.push({
      time: sig.time,
      position: sig.side === "DC+" ? "belowBar" : "aboveBar",
      color: sig.side === "DC+" ? up : down,
      shape: sig.side === "DC+" ? "arrowUp" : "arrowDown",
      text: sig.side,
    });
  });
  const st = pack.status;
  donchStatusEl.innerHTML = `
    <h3 style="font-size:13px;margin:12px 0 6px">Donchian + %R</h3>
    <p class="hint">Тикер <span class="mono">${esc(currentTicker)}</span> · бар ${esc(st.time)}. Канал 20 + поглощения EB/ES и сигналы DC± у границ.</p>
    <div class="scroll"><table class="grid">
      <tr><th>Параметр</th><th>Статус</th></tr>
      <tr><td>HH / Mid / LL</td><td class="mono">${fmt(st.hh, 4)} / ${fmt(st.mid, 4)} / ${fmt(st.ll, 4)}</td></tr>
      <tr><td>Позиция в канале</td><td class="mono">${fmt(st.posPct, 1)}% · ${esc(st.zone)}</td></tr>
      <tr><td>%R(5) / SMA10</td><td class="mono">${fmt(st.pr5, 2)} / ${fmt(st.pr5Sma, 2)}</td></tr>
      <tr><td>%R(20) / SMA10</td><td class="mono">${fmt(st.pr20, 2)} / ${fmt(st.pr20Sma, 2)}</td></tr>
      <tr><td>Сигналов DC+ / DC−</td><td class="mono">${pack.signals.filter((s) => s.side === "DC+").length} / ${pack.signals.filter((s) => s.side === "DC-").length}</td></tr>
      <tr><td>Поглощений EB / ES</td><td class="mono">${pack.engulf.filter((s) => s.side === "EB").length} / ${pack.engulf.filter((s) => s.side === "ES").length}</td></tr>
    </table></div>`;
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}


function levelLine(times, value, color, width, style) {
  const series = priceChart.addLineSeries({
    color,
    lineWidth: width || 1,
    lineStyle: style == null ? 2 : style,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  });
  series.setData(times.map((time) => ({ time, value })));
  return series;
}

function findPivotSwings(bars, left, right) {
  const swings = [];
  for (let i = left; i < bars.length - right; i++) {
    let isHigh = true, isLow = true;
    for (let j = i - left; j <= i + right; j++) {
      if (j === i) continue;
      if (bars[j].high >= bars[i].high) isHigh = false;
      if (bars[j].low <= bars[i].low) isLow = false;
    }
    if (isHigh) swings.push({ index: i, time: bars[i].time, price: bars[i].high, kind: "H" });
    if (isLow) swings.push({ index: i, time: bars[i].time, price: bars[i].low, kind: "L" });
  }
  return swings;
}

function pickMajorSwings(bars, count) {
  const raw = findPivotSwings(bars, 3, 3);
  if (!raw.length) return [];
  const span = Math.max(...bars.map((b) => b.high)) - Math.min(...bars.map((b) => b.low)) || 1;
  const scored = raw.map((s) => {
    const neighbors = raw.filter((o) => o !== s).slice(-6);
    let prominence = 0;
    neighbors.forEach((o) => { prominence = Math.max(prominence, Math.abs(s.price - o.price)); });
    return Object.assign({}, s, { score: prominence / span });
  }).sort((a, b) => b.score - a.score);
  const chosen = scored.slice(0, Math.max(count * 2, count)).sort((a, b) => a.index - b.index);
  // keep alternating kinds, take last `count`
  const alt = [];
  chosen.forEach((s) => {
    if (!alt.length || alt[alt.length - 1].kind !== s.kind) alt.push(s);
    else if (Math.abs(s.price - alt[alt.length - 1].price) > Math.abs(alt[alt.length - 1].price) * 0.002) alt[alt.length - 1] = s;
  });
  return alt.slice(-count);
}

function applyGannSquare9(bars) {
  if (gannStatusEl) gannStatusEl.innerHTML = "";
  if (!gann9On || !bars.length) return;
  const pivot = pickMajorSwings(bars, 1)[0] || { price: bars[bars.length - 1].close, time: bars[bars.length - 1].time, kind: "C" };
  const root = Math.sqrt(Math.max(pivot.price, 1e-9));
  const times = bars.map((b) => b.time);
  const angles = [
    { deg: 45, step: 0.125, color: "#8A5A12" },
    { deg: 90, step: 0.25, color: "#1D3E6E" },
    { deg: 180, step: 0.5, color: "#A62626" },
    { deg: 360, step: 1.0, color: "#1C1915" },
  ];
  const levels = [];
  angles.forEach((ang) => {
    for (let k = -4; k <= 4; k++) {
      if (k === 0) continue;
      const lvl = Math.pow(root + k * ang.step, 2);
      if (lvl <= 0) continue;
      gann9Series.lines.push(levelLine(times, lvl, ang.color, k === 1 || k === -1 ? 2 : 1, 2));
      levels.push({ deg: ang.deg, k, value: lvl });
    }
  });
  // cardinal pivot
  gann9Series.lines.push(levelLine(times, pivot.price, "#F2C94C", 2, 0));
  if (gannStatusEl) {
    gannStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Квадрат 9 Ганна (Углы)</h3>
      <p class="hint">Пивот ${esc(pivot.kind)} @ <span class="mono">${fmt(pivot.price, 4)}</span> (${esc(pivot.time)}). Уровни (√P ± n·δ)², δ=0.125/0.25/0.5/1.</p>
      <div class="scroll"><table class="grid"><tr><th>Угол</th><th>n</th><th>Уровень</th></tr>
      ${levels.filter((l) => Math.abs(l.k) <= 2).slice(0, 16).map((l) => `<tr><td>${l.deg}°</td><td class="mono">${l.k > 0 ? "+" : ""}${l.k}</td><td class="mono">${fmt(l.value, 4)}</td></tr>`).join("")}
      </table></div>`;
  }
}

function applyGannGrid18(bars) {
  if (!gann18On || !bars.length) {
    if (!gann9On && gannStatusEl && !gannStatusEl.innerHTML) gannStatusEl.innerHTML = "";
    return;
  }
  const windowBars = bars.slice(-120);
  let hi = -Infinity, lo = Infinity, hiT = "", loT = "";
  windowBars.forEach((b) => {
    if (b.high >= hi) { hi = b.high; hiT = b.time; }
    if (b.low <= lo) { lo = b.low; loT = b.time; }
  });
  const times = bars.map((b) => b.time);
  const span = hi - lo || 1;
  const fracs = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1];
  fracs.forEach((f) => {
    const v = lo + span * f;
    const isMid = Math.abs(f - 0.5) < 1e-9;
    const isEdge = f === 0 || f === 1;
    gann18Series.lines.push(levelLine(times, v, isMid ? "#A62626" : (isEdge ? "#1C1915" : "#8A5A12"), isMid ? 2 : 1, isMid ? 0 : 2));
  });
  const extra = `
    <h3 style="font-size:13px;margin:12px 0 6px">Сетка Ганна 1/8 (50%)</h3>
    <p class="hint">Диапазон ${esc(loT)}→${esc(hiT)}: Low <span class="mono">${fmt(lo, 4)}</span> … High <span class="mono">${fmt(hi, 4)}</span>. Красная — 4/8 (50%).</p>`;
  if (gannStatusEl) gannStatusEl.innerHTML = (gannStatusEl.innerHTML || "") + extra;
}

function applyBoroden(bars, eventMarkers) {
  if (borodenStatusEl) borodenStatusEl.innerHTML = "";
  if (!borodenOn || bars.length < 30) return eventMarkers;
  const swings = pickMajorSwings(bars, 3);
  if (swings.length < 2) return eventMarkers;
  const times = bars.map((b) => b.time);
  const fibs = [0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618];
  const allLevels = [];
  for (let i = 1; i < swings.length; i++) {
    const a = swings[i - 1], b = swings[i];
    const series = priceChart.addLineSeries({
      color: "#1D3E6E", lineWidth: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    });
    series.setData([{ time: a.time, value: a.price }, { time: b.time, value: b.price }]);
    borodenSeries.swings.push(series);
    fibs.forEach((f) => {
      const value = a.price + (b.price - a.price) * f;
      allLevels.push({ value, fib: f, from: a.index, to: b.index });
    });
  }
  // price clusters: 3+ fib levels within 0.35% of mid
  const tol = (Math.max(...bars.map((b) => b.high)) - Math.min(...bars.map((b) => b.low))) * 0.0035;
  const used = new Array(allLevels.length).fill(false);
  const clusters = [];
  for (let i = 0; i < allLevels.length; i++) {
    if (used[i]) continue;
    const group = [allLevels[i]];
    used[i] = true;
    for (let j = i + 1; j < allLevels.length; j++) {
      if (used[j]) continue;
      if (Math.abs(allLevels[j].value - allLevels[i].value) <= tol) {
        group.push(allLevels[j]);
        used[j] = true;
      }
    }
    if (group.length >= 3) {
      const mid = group.reduce((s, g) => s + g.value, 0) / group.length;
      clusters.push({ mid, count: group.length, fibs: group.map((g) => g.fib) });
      borodenSeries.clusters.push(levelLine(times, mid, "#A62626", 2, 0));
    }
  }
  // time clusters from swing durations
  const markers = [];
  if (swings.length >= 3) {
    const d1 = swings[1].index - swings[0].index;
    const d2 = swings[2].index - swings[1].index;
    const base = swings[2].index;
    [0.382, 0.5, 0.618, 1.0, 1.618].forEach((f) => {
      const idx = Math.round(base + (d1 + d2) * 0.5 * f);
      if (idx >= 0 && idx < bars.length) {
        markers.push({
          time: bars[idx].time,
          position: "aboveBar",
          color: "#8A5A12",
          shape: "square",
          text: "T" + f,
        });
        const mark = priceChart.addLineSeries({
          color: "rgba(138,90,18,0.55)", lineWidth: 1, lineStyle: 3,
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        });
        // vertical proxy: tiny segment at mid price — LWC has no vline; use markers primarily
        mark.setData([
          { time: bars[idx].time, value: bars[idx].low },
          { time: bars[idx].time, value: bars[idx].high },
        ]);
        borodenSeries.timeMarks.push(mark);
      }
    });
  }
  if (borodenStatusEl) {
    borodenStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Кластеры и Время · Кэролайн Бороден</h3>
      <p class="hint">3 свинга → Fib 0.382…1.618. Кластер = ≥3 уровней в узком коридоре. T* — временные проекции.</p>
      <div class="scroll"><table class="grid">
        <tr><th>Свинг</th><th>Дата</th><th>Цена</th></tr>
        ${swings.map((s, i) => `<tr><td>${i + 1} · ${s.kind}</td><td class="mono">${esc(s.time)}</td><td class="mono">${fmt(s.price, 4)}</td></tr>`).join("")}
        <tr><td colspan="3">Кластеров цены: <span class="mono">${clusters.length}</span>${clusters.length ? " · " + clusters.map((c) => fmt(c.mid, 2) + "×" + c.count).join(", ") : ""}</td></tr>
      </table></div>`;
  }
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function applyElliott(bars, eventMarkers) {
  if (elliottStatusEl) elliottStatusEl.innerHTML = "";
  if (!elliottOn || bars.length < 40) return eventMarkers;
  // zigzag with ATR-like threshold
  const ranges = bars.map((b) => b.high - b.low);
  const avg = ranges.slice(-40).reduce((s, v) => s + v, 0) / Math.min(40, ranges.length) || 1;
  const thr = avg * 1.8;
  const pivots = [];
  let mode = null; // H seeking high, L seeking low
  let extreme = bars[0];
  let extremeIdx = 0;
  for (let i = 1; i < bars.length; i++) {
    const b = bars[i];
    if (mode == null) {
      if (b.high - extreme.low >= thr) { mode = "H"; extreme = b; extremeIdx = i; }
      else if (extreme.high - b.low >= thr) { mode = "L"; extreme = b; extremeIdx = i; }
      continue;
    }
    if (mode === "H") {
      if (b.high >= extreme.high) { extreme = b; extremeIdx = i; }
      else if (extreme.high - b.low >= thr) {
        pivots.push({ index: extremeIdx, time: extreme.time, price: extreme.high, kind: "H" });
        mode = "L"; extreme = b; extremeIdx = i;
      }
    } else {
      if (b.low <= extreme.low) { extreme = b; extremeIdx = i; }
      else if (b.high - extreme.low >= thr) {
        pivots.push({ index: extremeIdx, time: extreme.time, price: extreme.low, kind: "L" });
        mode = "H"; extreme = b; extremeIdx = i;
      }
    }
  }
  const wave = pivots.slice(-6);
  if (wave.length < 5) {
    if (elliottStatusEl) elliottStatusEl.innerHTML = `<h3 style="font-size:13px;margin:12px 0 6px">Волны Эллиотта</h3><p class="hint">Недостаточно свингов для 1-2-3-4-5 (найдено ${wave.length}).</p>`;
    return eventMarkers;
  }
  const five = wave.slice(-5);
  const labels = ["1", "2", "3", "4", "5"];
  const markers = [];
  for (let i = 0; i < five.length; i++) {
    markers.push({
      time: five[i].time,
      position: five[i].kind === "H" ? "aboveBar" : "belowBar",
      color: "#1D3E6E",
      shape: "circle",
      text: labels[i],
    });
    if (i > 0) {
      const series = priceChart.addLineSeries({
        color: i === 3 ? "#A62626" : "#1D3E6E",
        lineWidth: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData([
        { time: five[i - 1].time, value: five[i - 1].price },
        { time: five[i].time, value: five[i].price },
      ]);
      elliottSeries.lines.push(series);
    }
  }
  elliottSeries.labels = labels;
  if (elliottStatusEl) {
    elliottStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Волны Эллиотта (1-2-3-4-5)</h3>
      <p class="hint">Импульс по зигзагу (порог ~1.8×ATR окна). Точки 1…5 на последних свингах.</p>
      <div class="scroll"><table class="grid"><tr><th>Волна</th><th>Дата</th><th>Цена</th></tr>
      ${five.map((p, i) => `<tr><td>${labels[i]} · ${p.kind}</td><td class="mono">${esc(p.time)}</td><td class="mono">${fmt(p.price, 4)}</td></tr>`).join("")}
      </table></div>`;
  }
  return eventMarkers.concat(markers).sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

function ensureOptChart() {
  if (optChart) return;
  optChart = LightweightCharts.createChart(optChartEl, Object.assign(chartBase(160), {
    height: 160,
    rightPriceScale: {
      borderColor: getComputedStyle(root).getPropertyValue("--rule").trim() || "#B89856",
      minimumWidth: 75,
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
  }));
  optCallHist = optChart.addHistogramSeries({
    priceScaleId: "vol",
    priceFormat: { type: "volume" },
    base: 0,
  });
  optPutHist = optChart.addHistogramSeries({
    priceScaleId: "vol",
    priceFormat: { type: "volume" },
    base: 0,
  });
  optPcrLine = optChart.addLineSeries({
    priceScaleId: "right",
    color: getComputedStyle(root).getPropertyValue("--ink").trim() || "#1C1915",
    lineWidth: 2,
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  });
  optLevel1 = optChart.addLineSeries({
    priceScaleId: "right",
    color: getComputedStyle(root).getPropertyValue("--muted").trim() || "#5C4F38",
    lineWidth: 1,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  });
  optChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.55, bottom: 0.05 } });
  bindRangeSync(optChart);
  bindCrosshairSync(optChart);
}

function applyOptPanel(bars) {
  if (optStatusEl) optStatusEl.innerHTML = "";
  if (!optOn || !bars.length) {
    if (optBox) optBox.style.display = "none";
    return;
  }
  optBox.style.display = "block";
  ensureOptChart();
  const up = getComputedStyle(root).getPropertyValue("--up").trim() || "#1B6B3A";
  const down = getComputedStyle(root).getPropertyValue("--down").trim() || "#A62626";
  const ink = getComputedStyle(root).getPropertyValue("--ink").trim() || "#1C1915";
  optChart.applyOptions(Object.assign(chartBase(160), { height: 160 }));
  optPcrLine.applyOptions({ color: ink });
  // proxy: up-day volume = Call, down-day = Put; PCR = SMA(Put)/SMA(Call)
  const call = [];
  const put = [];
  const pcr = [];
  let sumC = 0, sumP = 0;
  const win = 10;
  const qC = [], qP = [];
  for (let i = 0; i < bars.length; i++) {
    const vol = bars[i].volume != null ? bars[i].volume : Math.abs(bars[i].close - bars[i].open) * 1000;
    const isUp = bars[i].close >= bars[i].open;
    const c = isUp ? vol : 0;
    const p = isUp ? 0 : vol;
    call.push({ time: bars[i].time, value: c, color: "rgba(27,107,58,0.35)" });
    put.push({ time: bars[i].time, value: -p, color: "rgba(166,38,38,0.35)" });
    qC.push(c); qP.push(p); sumC += c; sumP += p;
    if (qC.length > win) { sumC -= qC.shift(); sumP -= qP.shift(); }
    const ratio = sumC > 0 ? sumP / sumC : (sumP > 0 ? 2 : 1);
    pcr.push({ time: bars[i].time, value: ratio });
  }
  optCallHist.setData(call);
  optPutHist.setData(put);
  optPcrLine.setData(pcr);
  optLevel1.setData(bars.map((b) => ({ time: b.time, value: 1 })));
  optChart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
  try {
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (range) optChart.timeScale().setVisibleLogicalRange(range);
  } catch (e) {}
  const last = pcr[pcr.length - 1];
  let note = "нейтрально";
  if (last) {
    if (last.value > 1.2) note = "Put-перевес (PCR > 1.2) — давление продавцов";
    else if (last.value < 0.8) note = "Call-перевес (PCR < 0.8) — спрос покупателей";
    else note = "баланс Put/Call около 1";
  }
  document.getElementById("optHint").textContent = note;
  if (optStatusEl) {
    optStatusEl.innerHTML = `
      <h3 style="font-size:13px;margin:12px 0 6px">Подвал · Опционы Put/Call</h3>
      <p class="hint">Прокси потока: объём растущих дней = Call, падающих = Put. Линия — SMA(10) PCR.</p>
      <div class="scroll"><table class="grid">
        <tr><th>Параметр</th><th>Значение</th></tr>
        <tr><td>PCR (10)</td><td class="mono">${fmt(last ? last.value : null, 2)}</td></tr>
        <tr><td>Интерпретация</td><td>${esc(note)}</td></tr>
      </table></div>`;
  }
}

function resizeAllCharts() {
  const mainH = fullscreenOn ? Math.min(window.innerHeight * 0.52, 560) : 420;
  const paneH = fullscreenOn ? 170 : 160;
  const haH = fullscreenOn ? 240 : 220;
  if (priceEl) priceChart.applyOptions(Object.assign(chartBase(mainH), { width: priceEl.clientWidth, height: priceEl.clientHeight || mainH }));
  if (lowerEl) lowerChart.applyOptions(Object.assign(chartBase(150), { width: lowerEl.clientWidth, height: lowerEl.clientHeight || 150 }));
  if (optChart && optChartEl) optChart.applyOptions(Object.assign(chartBase(paneH), { width: optChartEl.clientWidth, height: optChartEl.clientHeight || paneH }));
  if (pctRChart && pctRChartEl) pctRChart.applyOptions(Object.assign(chartBase(paneH), { width: pctRChartEl.clientWidth, height: pctRChartEl.clientHeight || paneH }));
  if (rsiStochChart && rsiStochChartEl) rsiStochChart.applyOptions(Object.assign(chartBase(paneH), { width: rsiStochChartEl.clientWidth, height: rsiStochChartEl.clientHeight || paneH }));
  if (rsxChart && rsxChartEl) rsxChart.applyOptions(Object.assign(chartBase(paneH), { width: rsxChartEl.clientWidth, height: rsxChartEl.clientHeight || paneH }));
  if (haChart && haChartEl) haChart.applyOptions(Object.assign(chartBase(haH), { width: haChartEl.clientWidth, height: haChartEl.clientHeight || haH }));
}

function showTicker(ticker) {
  currentTicker = ticker;
  Object.entries(buttons).forEach(([name, button]) => button.classList.toggle("active", name === ticker));
  clearIndicatorOverlays();
  const bars = candleData.bars[ticker] || [];
  const rows = eventsOf(ticker);
  const barDays = new Set(bars.map((bar) => bar.time));
  let markers = rows.filter((row) => barDays.has(row.date)).map((row) => ({
    time: row.date,
    position: row.tone < 0 ? "aboveBar" : "belowBar",
    color: markerColor(row.tone),
    shape: row.tone < 0 ? "arrowDown" : "circle",
    text: row.short_label,
  }));
  // Всегда свечи: синтез OHLC уже в DATA.
  if (priceKind !== "candle") {
    priceChart.removeSeries(priceSeries);
    priceSeries = priceChart.addCandlestickSeries(candleOptions());
    priceKind = "candle";
  } else {
    priceSeries.applyOptions(candleOptions());
  }
  priceSeries.setData(bars);
  applyGannSquare9(bars);
  applyGannGrid18(bars);
  markers = applyBoroden(bars, markers);
  markers = applyElliott(bars, markers);
  markers = applyKennedy(bars, markers);
  markers = applyDonch(bars, markers);
  markers = applyHillCloud(bars, markers);
  applyFairRange(bars);
  markers = applyPlummer(bars, markers);
  applyOptPanel(bars);
  applyPctRPanel(bars);
  applyRsiStochPanel(bars);
  markers = applyRsxPanel(bars, markers);
  applyHaPanel(bars);
  renderKennedySummary(bars);
  refreshExplainVisibility();
  if (typeof priceSeries.setMarkers === "function") priceSeries.setMarkers(markers);
  const panel = dayPanel(rows);
  heat.setData(panel.map((row) => ({
    time: row.date,
    value: row.heat,
    color: row.heat >= 4 ? getComputedStyle(root).getPropertyValue("--down").trim() : getComputedStyle(root).getPropertyValue("--warn").trim(),
  })));
  tone.applyOptions({ color: getComputedStyle(root).getPropertyValue("--blue").trim() });
  tone.setData(panel.map((row) => ({ time: row.date, value: row.tone })));
  // Общая временная ось на всех панелях — полный массив time свечей.
  const axisTimes = bars.length ? bars.map((bar) => bar.time) : ["2026-11-01","2026-11-25"];
  axis.setData(axisTimes.map((time) => ({ time, value: 0 })));
  const focus = () => {
    syncingRange = true;
    if (bars.length) {
      const i0 = bars.findIndex((item) => item.time >= "2026-10-01");
      const logical = { from: i0 < 0 ? 0 : i0, to: bars.length + 5 };
      paneCharts().forEach((chart) => {
        try {
          chart.timeScale().applyOptions({ barSpacing: 18, rightOffset: 6 });
          chart.timeScale().setVisibleLogicalRange(logical);
        } catch (e) {}
      });
    } else {
      lowerChart.timeScale().fitContent();
    }
    syncingRange = false;
    resizeAllCharts();
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
  resizeAllCharts();
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

let stovallHorizon = (DATA.stovall && DATA.stovall.default_horizon) || "cycle";

function renderStovall() {
  const pack = DATA.stovall || null;
  const cycleEl = document.getElementById("stovallCycle");
  const tableEl = document.getElementById("stovallTable");
  const noteEl = document.getElementById("stovallNote");
  if (!pack || !pack.cycle) {
    cycleEl.innerHTML = `<p class="hint">Нет данных RUSFAR / отраслей для модели Стовалла.</p>`;
    tableEl.innerHTML = "";
    noteEl.textContent = "";
    return;
  }
  const c = pack.cycle;
  const favored = (c.favored || []).join(", ") || "—";
  const posPct = c.cycle_pos == null ? "нет" : (100 * c.cycle_pos).toFixed(0) + "%";
  const dirCls = c.delta_dir === "СНИЖЕНИЕ" ? "up" : (c.delta_dir === "ПОВЫШЕНИЕ" ? "down" : "flat");
  cycleEl.innerHTML = `
    <div class="cell phase"><span class="k">Фаза цикла</span><span class="v">${esc(c.phase || "нет")}</span></div>
    <div class="cell"><span class="k">RUSFAR</span><span class="v mono">${fmt(c.rate, 2)}% · ${esc(c.asof || "")}</span></div>
    <div class="cell"><span class="k">cycle_pos (2г)</span><span class="v mono">${esc(posPct)} · [${fmt(c.corridor_low, 2)}; ${fmt(c.corridor_high, 2)}]</span></div>
    <div class="cell"><span class="k">Δ 60 сессий</span><span class="v mono ${dirCls}">${fmt(c.delta_60, 2)} п.п. · ${esc(c.delta_dir || "")}</span></div>
    <div class="cell"><span class="k">Макро-бонус фазы</span><span class="v">${esc(favored)}</span></div>`;
  const horizon = pack.horizons[stovallHorizon] || pack.horizons.cycle || { rows: [], label: "" };
  document.querySelectorAll("#stovallHorizon button").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-horizon") === stovallHorizon);
  });
  const head = `<tr><th>#</th><th>Сектор</th><th>Код</th><th class="num">Score</th><th class="num">Z(RS)</th><th class="num">Z(Mom)</th><th class="num">Z(Acc)</th><th class="num">RS %</th><th class="num">Mom %</th><th>Макро-бонус</th></tr>`;
  const body = (horizon.rows || []).map((row) => {
    const boost = row.macro_boost ? "macro-boost" : "";
    const scoreCls = row.score == null ? "flat" : (row.score >= 0 ? "up" : "down");
    return `<tr class="${boost}"><td>${esc(row.rank)}</td><td>${esc(row.title)}</td><td>${esc(row.code)}</td><td class="num ${scoreCls}"><strong>${fmt(row.score, 2)}</strong></td><td class="num">${fmt(row.z_rs, 2)}</td><td class="num">${fmt(row.z_momentum, 2)}</td><td class="num">${fmt(row.z_acceleration, 2)}</td><td class="num ${clsPct(row.rs)}">${fmt(row.rs, 2)}</td><td class="num ${clsPct(row.momentum)}">${fmt(row.momentum, 2)}</td><td>${esc(row.boost_note)}</td></tr>`;
  }).join("");
  tableEl.innerHTML = head + (body || `<tr><td colspan="10">Нет строк рейтинга</td></tr>`);
  noteEl.textContent = `${pack.model || ""} · горизонт ${horizon.label || stovallHorizon}. ${pack.note || ""} Сектора с макро-бонусом отмечены синей полосой.`;
}

document.getElementById("stovallHorizon").addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-horizon]");
  if (!btn) return;
  stovallHorizon = btn.getAttribute("data-horizon") || "cycle";
  renderStovall();
});

function renderFractions() {
  renderStovall();
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
window.addEventListener("resize", () => {
  resizeAllCharts();
  if (curveChart) curveChart.applyOptions({ width: document.getElementById("curveChart").clientWidth });
  if (psChartObj) psChartObj.applyOptions({ width: document.getElementById("psChart").clientWidth });
});
resizeAllCharts();
if (currentTicker) {
  showTicker(currentTicker);
  // Повтор после layout: LWC иногда стартует с нулевой шириной контейнера.
  requestAnimationFrame(() => {
    resizeAllCharts();
    showTicker(currentTicker);
  });
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
