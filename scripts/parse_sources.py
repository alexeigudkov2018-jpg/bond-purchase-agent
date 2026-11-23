"""Разбор ответов источников. Пропуски остаются пустыми."""

from __future__ import annotations

import csv
import io
import json
import re
from xml.etree import ElementTree

from scripts.formulas import is_num


def _num(text):
    if text is None:
        return None
    raw = str(text).strip().replace(" ", "").replace(",", ".")
    if raw in ("", ".", "-", "null"):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not is_num(value):
        return None
    return value


def parse_cbr_keyrate_html(html: str) -> list[dict]:
    rows = re.findall(r"<td>(\d{2}\.\d{2}\.\d{4})</td>\s*<td>([0-9]+,[0-9]+|[0-9]+)</td>", html)
    parsed = []
    for raw_date, raw_rate in rows:
        day, month, year = raw_date.split(".")
        parsed.append({"date": f"{year}-{month}-{day}", "rate": _num(raw_rate)})
    parsed.sort(key=lambda row: row["date"])
    return [row for row in parsed if row["rate"] is not None]


def key_rate_events(observations: list[dict]) -> list[dict]:
    events = []
    previous = None
    for row in observations:
        if previous is None:
            previous = row
            continue
        if row["rate"] == previous["rate"]:
            previous = row
            continue
        decision = "hike" if row["rate"] > previous["rate"] else "cut"
        events.append(
            {
                "date": row["date"],
                "rate_old": previous["rate"],
                "rate_new": row["rate"],
                "decision": decision,
                "source_url": "https://www.cbr.ru/hd_base/keyrate/",
            }
        )
        previous = row
    return events


def parse_cbr_fx_xml(xml_bytes: bytes) -> list[dict]:
    root = ElementTree.fromstring(xml_bytes)
    rows = []
    for record in root.findall("Record"):
        raw_date = record.attrib.get("Date", "")
        if not raw_date:
            continue
        day, month, year = raw_date.split(".")
        nominal = _num(record.findtext("Nominal")) or 1.0
        value = _num(record.findtext("Value"))
        if value is None or nominal == 0:
            continue
        rows.append({"date": f"{year}-{month}-{day}", "usdrub": value / nominal})
    rows.sort(key=lambda row: row["date"])
    return rows


def parse_fred_brent(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        price = _num(row.get("DCOILBRENTEU") or row.get("VALUE"))
        stamp = (row.get("DATE") or row.get("observation_date") or "")[:10]
        if not stamp:
            continue
        rows.append({"date": stamp, "brent": price})
    return rows


def parse_noaa_solar(payload) -> list[dict]:
    rows = []
    for item in payload:
        stamp = str(item.get("time-tag") or "")
        if len(stamp) < 7:
            continue
        ssn = _num(item.get("ssn"))
        smooth = _num(item.get("smoothed_ssn"))
        f107 = _num(item.get("f10.7"))
        rows.append(
            {
                "month": stamp[:7],
                "ssn": None if ssn is not None and ssn < 0 else ssn,
                "ssn_smooth13": None if smooth is not None and smooth < 0 else smooth,
                "f107": None if f107 is not None and f107 < 0 else f107,
            }
        )
    return rows


def parse_iss_history(payload: dict) -> list[dict]:
    history = payload.get("history") or {}
    columns = history.get("columns") or []
    table = []
    for raw in history.get("data") or []:
        row = dict(zip(columns, raw))
        table.append(row)
    return table


def parse_iss_description(payload: dict) -> dict:
    description = payload.get("description") or {}
    columns = description.get("columns") or []
    found = {}
    for raw in description.get("data") or []:
        row = dict(zip(columns, raw))
        found[row.get("name")] = row.get("value")
    tqbr = None
    boards = payload.get("boards") or {}
    bcols = boards.get("columns") or []
    for raw in boards.get("data") or []:
        row = dict(zip(bcols, raw))
        if row.get("boardid") == "TQBR":
            tqbr = row
            break
    return {"fields": found, "tqbr": tqbr}


METAL_FIELDS = {"1": "gold", "2": "silver", "3": "platinum", "4": "palladium"}
QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}


def parse_cbr_metals(xml_bytes: bytes) -> list[dict]:
    """Учётные цены ЦБ, рубли за грамм. Коды: 1 золото, 2 серебро, 3 платина, 4 палладий."""
    root = ElementTree.fromstring(xml_bytes)
    by_date: dict[str, dict] = {}
    for record in root.findall("Record"):
        raw_date = record.attrib.get("Date", "")
        if not raw_date or len(raw_date) != 10:
            continue
        day, month, year = raw_date.split(".")
        stamp = f"{year}-{month}-{day}"
        field = METAL_FIELDS.get(record.attrib.get("Code", ""))
        if not field:
            continue
        price = _num(record.findtext("Sell"))
        if price is None:
            continue
        by_date.setdefault(stamp, {"date": stamp})[field] = price
    return [by_date[key] for key in sorted(by_date)]


def parse_silso_csv(text: str, field: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        value = _num(parts[3])
        if value is not None and value < 0:
            value = None
        rows.append({"month": f"{int(parts[0]):04d}-{int(parts[1]):02d}", field: value})
    return rows


def parse_gfz_daily(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 27 or not parts[0].isdigit():
            continue
        kps = []
        for raw in parts[7:15]:
            value = _num(raw)
            if value is not None and value >= 0:
                kps.append(value)
        ap = _num(parts[23])
        sn = _num(parts[24])
        f107 = _num(parts[25])
        rows.append(
            {
                "date": f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}",
                "kpmax": max(kps) if kps else None,
                "ap": None if ap is not None and ap < 0 else ap,
                "sn": None if sn is not None and sn < 0 else sn,
                "f107": None if f107 is not None and f107 < 0 else f107,
            }
        )
    return rows


def monthly_mean(values):
    nums = [value for value in values if is_num(value)]
    if not nums:
        return None
    return sum(nums) / len(nums)


def gfz_monthly(daily_rows, start_month="2015-01"):
    grouped: dict[str, list[dict]] = {}
    for row in daily_rows:
        month = row["date"][:7]
        if month < start_month:
            continue
        grouped.setdefault(month, []).append(row)
    out = []
    for month in sorted(grouped):
        bucket = grouped[month]
        kps = [row["kpmax"] for row in bucket if is_num(row["kpmax"])]
        out.append(
            {
                "month": month,
                "ap": monthly_mean([row["ap"] for row in bucket]),
                "kpmax": max(kps) if kps else None,
                "sn_gfz": monthly_mean([row["sn"] for row in bucket]),
                "f107": monthly_mean([row["f107"] for row in bucket]),
                "n_obs": len(bucket),
            }
        )
    return out


def parse_meteostat_daily(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) < 2 or len(parts[0]) != 10:
            continue
        rows.append({"date": parts[0], "tmean": _num(parts[1])})
    return rows


def weather_monthly(daily_rows, start="1991-01-01"):
    grouped: dict[str, list[float]] = {}
    for row in daily_rows:
        if row["date"] < start or not is_num(row["tmean"]):
            continue
        grouped.setdefault(row["date"][:7], []).append(row["tmean"])
    out = []
    for month in sorted(grouped):
        values = grouped[month]
        if len(values) < 25:
            continue
        out.append({"month": month, "tmean": sum(values) / len(values), "n_obs": len(values)})
    return out


def _plain_cell(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def _scale_number(label: str, raw: str):
    if raw in ("", "?", "-", "—"):
        return None
    value = _num(raw.replace(" ", ""))
    if value is None:
        return None
    lowered = label.casefold()
    if "млрд" in lowered:
        return value * 1_000_000_000
    if "млн" in lowered:
        return value * 1_000_000
    return value


def _aligned(row: list[str], header_index: int) -> str:
    """Год в шапке Smart-Lab часто стоит на столбец левее числа."""
    direct = row[header_index] if header_index < len(row) else ""
    if _num(direct.replace(" ", "")) is not None or re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", direct):
        return direct
    shifted = header_index + 1
    return row[shifted] if shifted < len(row) else ""


def _period_end(token: str):
    quarter = re.fullmatch(r"(20\d{2})Q([1-4])", token)
    if quarter:
        return f"{quarter.group(1)}-{QUARTER_END[quarter.group(2)]}"
    if re.fullmatch(r"20\d{2}", token):
        return f"{token}-12-31"
    return None


def parse_smartlab_html(html: str, report_type: str) -> list[dict]:
    """Разбор таблицы Smart-Lab по подписям строк, не по номерам колонок."""
    rows = []
    for raw_row in re.findall(r"<tr[\s\S]*?</tr>", html, flags=re.I):
        cells = [_plain_cell(cell) for cell in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", raw_row, flags=re.I)]
        if any(cells):
            rows.append(cells)
    header = None
    for cells in rows:
        if any(re.fullmatch(r"20\d{2}(?:Q[1-4])?", cell) for cell in cells):
            header = cells
            break
    if not header:
        return []
    periods = [(index, cell, _period_end(cell)) for index, cell in enumerate(header) if _period_end(cell)]
    wanted = {
        "revenue": ("выручка",),
        "ebitda": ("ebitda",),
        "net_income": ("чистая прибыль",),
        "net_debt": ("чистый долг",),
        "equity": ("собствен",),
    }
    picked = {}
    report_dates = {}
    for cells in rows:
        label = cells[0].casefold() if cells else ""
        if label.startswith("дата отчета"):
            for index, _token, period in periods:
                raw = _aligned(cells, index)
                if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", raw):
                    day, month, year = raw.split(".")
                    report_dates[period] = f"{year}-{month}-{day}"
            continue
        for key, needles in wanted.items():
            if key in picked:
                continue
            if "капитализац" in label or "рентаб" in label or "н/с" in label or "/" in label:
                continue
            if not all(needle in label for needle in needles):
                continue
            if key == "equity" and "капитал" not in label:
                continue
            if key != "equity" and not label.startswith(needles[0]):
                continue
            picked[key] = (cells, label)
    if not picked:
        return []
    out = []
    for _index, _token, period in periods:
        record = {
            "period_end": period,
            "report_type": report_type,
            "revenue": None,
            "ebitda": None,
            "net_income": None,
            "net_debt": None,
            "equity": None,
            "reported_at": report_dates.get(period, ""),
            "ltm": "",
        }
        for key, (cells, label) in picked.items():
            record[key] = _scale_number(label, _aligned(cells, _index))
        if any(is_num(record[key]) for key in ("revenue", "ebitda", "net_income", "net_debt", "equity")):
            out.append(record)
    return out
