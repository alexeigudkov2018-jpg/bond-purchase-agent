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
