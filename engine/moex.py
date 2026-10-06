"""Загрузка облигаций и оборотов с Московской биржи (ISS, без ключа)."""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

from engine.cashflows import parse_iso

ISS = "https://iss.moex.com/iss"
UA = {"User-Agent": "tuesday-bond-agent/1.0"}

SEC_COLUMNS = ",".join([
    "SECID", "SHORTNAME", "ISIN", "SECNAME", "FACEVALUE", "FACEUNIT", "MATDATE",
    "COUPONPERCENT", "COUPONVALUE", "COUPONPERIOD", "NEXTCOUPON", "ACCRUEDINT",
    "PREVPRICE", "PREVDATE", "LOTSIZE", "LISTLEVEL", "STATUS", "BONDTYPE",
    "BONDSUBTYPE", "COUPON_DETAILS", "FACEVALUE_TYPE", "OFFERDATE",
    "CALLOPTIONDATE", "PUTOPTIONDATE", "BUYBACKDATE", "CURRENCYID",
])
MD_COLUMNS = "SECID,LAST,YIELD,DURATION,VALTODAY,UPDATETIME,SYSTIME,LCURRENTPRICE"
Y_COLUMNS = "SECID,EFFECTIVEYIELD,DURATION,GSPREADBP,PRICE,YIELDDATE,YIELDDATETYPE"


def fetch_json(url: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _rows(block: dict) -> list[dict]:
    columns = block["columns"]
    return [dict(zip(columns, row)) for row in block["data"]]


def load_board(board: str) -> list[dict]:
    url = (
        f"{ISS}/engines/stock/markets/bonds/boards/{board}/securities.json"
        f"?iss.meta=off&iss.only=securities,marketdata,marketdata_yields"
        f"&securities.columns={SEC_COLUMNS}"
        f"&marketdata.columns={MD_COLUMNS}"
        f"&marketdata_yields.columns={Y_COLUMNS}"
    )
    payload = fetch_json(url)
    securities = _rows(payload["securities"])
    market = {row["SECID"]: row for row in _rows(payload["marketdata"])}
    yields = {row["SECID"]: row for row in _rows(payload["marketdata_yields"])}
    for row in securities:
        row["board"] = board
        row["market"] = market.get(row["SECID"], {})
        row["yields"] = yields.get(row["SECID"], {})
    return securities


def load_universe() -> dict:
    return {"TQOB": load_board("TQOB"), "TQCB": load_board("TQCB")}


def history_values(secid: str, board: str, start: date, end: date) -> list[tuple[str, float]]:
    url = (
        f"{ISS}/history/engines/stock/markets/bonds/boards/{board}/securities/{secid}.json"
        f"?from={start.isoformat()}&till={end.isoformat()}"
        f"&iss.meta=off&history.columns=TRADEDATE,VALUE"
    )
    payload = fetch_json(url, timeout=40)
    return [(row[0], float(row[1] or 0)) for row in payload["history"]["data"]]


def turnover_on_calendar(
    secid: str,
    board: str,
    sessions: list[str],
) -> dict:
    if not sessions:
        return {"mean": None, "median": None, "sessions": 0, "traded_days": 0, "values": []}
    start = date.fromisoformat(sessions[0])
    end = date.fromisoformat(sessions[-1])
    try:
        rows = history_values(secid, board, start, end)
    except Exception as error:  # сеть биржи не должна ронять весь пакет
        return {
            "mean": None,
            "median": None,
            "sessions": len(sessions),
            "traded_days": 0,
            "values": [],
            "error": str(error),
        }
    by_day = {day: value for day, value in rows}
    aligned = [by_day.get(day, 0.0) for day in sessions]
    if secid not in {day for day, _ in rows} and not rows:
        return {
            "mean": None,
            "median": None,
            "sessions": len(sessions),
            "traded_days": 0,
            "values": aligned,
        }
    ordered = sorted(aligned)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "mean": sum(aligned) / len(aligned),
        "median": median,
        "sessions": len(sessions),
        "traded_days": sum(1 for value in aligned if value > 0),
        "values": aligned,
    }


def last_trading_sessions(anchor: str = "SU26238RMFS4", count: int = 10) -> list[str]:
    end = date.today()
    start = end - timedelta(days=40)
    rows = history_values(anchor, "TQOB", start, end)
    days = sorted({day for day, value in rows if value and value > 0})
    return days[-count:]


def bondization(secid: str) -> dict:
    """Полный график. Без limit биржа отдаёт только первую страницу купонов."""
    rows = {"amortizations": [], "coupons": [], "offers": []}
    start = 0
    while start <= 400:
        url = f"{ISS}/securities/{secid}/bondization.json?iss.meta=off&start={start}&limit=100"
        payload = fetch_json(url, timeout=40)
        page = {
            key: _rows(payload.get(key, {"columns": [], "data": []}))
            for key in rows
        }
        added = sum(len(chunk) for chunk in page.values())
        for key, chunk in page.items():
            rows[key].extend(chunk)
        if added < 100:
            break
        start += 100
    coupons = []
    seen = set()
    for row in rows["coupons"]:
        key = (row.get("coupondate"), row.get("value_rub"), row.get("value"))
        if key in seen:
            continue
        seen.add(key)
        coupons.append(row)
    rows["coupons"] = coupons
    return rows


def description(secid: str) -> dict:
    url = f"{ISS}/securities/{secid}.json?iss.meta=off&iss.only=description"
    payload = fetch_json(url, timeout=40)
    out = {}
    for row in payload["description"]["data"]:
        out[row[0]] = row[2]
    return out


def rgbi_history(start: date, end: date) -> list[dict]:
    url = (
        f"{ISS}/history/engines/stock/markets/index/boards/SNDX/securities/RGBI.json"
        f"?from={start.isoformat()}&till={end.isoformat()}"
        f"&iss.meta=off&history.columns=TRADEDATE,CLOSE"
    )
    payload = fetch_json(url)
    return [{"date": row[0], "close": row[1]} for row in payload["history"]["data"]]


def map_turnover(bonds: list[dict], sessions: list[str], workers: int = 12) -> None:
    def job(bond: dict) -> tuple[str, dict]:
        return bond["SECID"], turnover_on_calendar(bond["SECID"], bond["board"], sessions)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job, bond) for bond in bonds]
        done = {secid: stats for secid, stats in (item.result() for item in as_completed(futures))}
    for bond in bonds:
        bond["turnover"] = done.get(bond["SECID"], {})


def quote(bond: dict) -> dict:
    market = bond.get("market") or {}
    last = market.get("LAST")
    systime = market.get("SYSTIME") or market.get("UPDATETIME")
    if last not in (None, 0, "0"):
        return {
            "price": float(last),
            "source": "MOEX ISS последняя сделка LAST",
            "asof": systime,
            "stale": False,
        }
    prev = bond.get("PREVPRICE")
    return {
        "price": None if prev is None else float(prev),
        "source": "MOEX ISS предыдущая цена PREVPRICE, это не цена текущей сделки",
        "asof": bond.get("PREVDATE"),
        "stale": True,
    }


def effective_yield(bond: dict) -> float | None:
    value = (bond.get("yields") or {}).get("EFFECTIVEYIELD")
    if value is None:
        return None
    return float(value)


def duration_days(bond: dict) -> float | None:
    value = (bond.get("yields") or {}).get("DURATION")
    if value in (None, 0):
        value = (bond.get("market") or {}).get("DURATION")
    if value in (None, 0):
        return None
    return float(value)


def moex_g_spread(bond: dict) -> float | None:
    value = (bond.get("yields") or {}).get("GSPREADBP")
    if value is None:
        return None
    return float(value)


def is_rub(bond: dict) -> bool:
    return bond.get("FACEUNIT") in ("SUR", "RUB") and "валют" not in (bond.get("BONDTYPE") or "").lower()


def is_fixed_coupon(bond: dict) -> bool:
    bond_type = (bond.get("BONDTYPE") or "").lower()
    details = (bond.get("COUPON_DETAILS") or "").lower()
    name = f"{bond.get('SECNAME') or ''} {bond.get('SHORTNAME') or ''}".lower()
    secid = bond.get("SECID") or ""
    if "плава" in bond_type:
        return False
    if any(token in details for token in ("ключев", "ruonia", "инфляц", "плава")):
        return False
    if any(token in name for token in ("офз-пк", "офз-ин", "офз-ад")):
        return False
    if secid.startswith(("SU290", "SU520", "SU460")):
        return False
    return "фиксир" in bond_type or "фиксир" in details


def listed_offer(bond: dict) -> date | None:
    for key in ("OFFERDATE", "CALLOPTIONDATE", "PUTOPTIONDATE", "BUYBACKDATE"):
        found = parse_iso(bond.get(key))
        if found:
            return found
    return None


def to_maturity(bond: dict) -> bool:
    return (bond.get("BONDSUBTYPE") or "") == "До погашения"


def years_to(bond: dict, asof: date) -> float | None:
    maturity = parse_iso(bond.get("MATDATE"))
    if maturity is None:
        return None
    return (maturity - asof).days / 365.25
