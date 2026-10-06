"""Скринер облигаций УК «ДОХОДЪ».

Страница: https://www.dohod.ru/analytic/bonds
Выгрузка всех строк: POST connectorweb.php?action=info.

Колонка vol_median — медиана дневного оборота в млн ₽. Правило портфеля
считает средний оборот, поэтому медиана здесь только справочная.
Кредитное качество (число 0–10) и качество эмитента (0–10) — те самые
замены для баллов, когда нет долга/EBITDA и покрытия процентов.
NetDebt/Equity из этой выгрузки в баллы не берём.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INFO_URL = "https://www.dohod.ru/assets/components/dohodbonds/connectorweb.php?action=info"
PAGE_URL = "https://www.dohod.ru/analytic/bonds"
UA = {"User-Agent": "tuesday-bond-agent/1.0"}

BAD_FLAGS = {"AMO", "PUT", "CALL", "FLT", "SUB", "PERP", "DEFAULT", "TECH_DEFAULT"}

TEXT_GROUP = {
    "AAA": "aa",
    "AA+": "aa",
    "AA": "aa",
    "AA-": "aa",
    "A+": "a",
    "A": "a",
    "A-": "a",
}


def fetch_rows() -> list[dict]:
    request = urllib.request.Request(INFO_URL, data=b"", headers=UA, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise RuntimeError("скринер ДОХОДЪ вернул не список выпусков")
    return payload


def load_index(cache_path: Path, refresh: bool = False) -> tuple[dict[str, dict], str]:
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached["by_isin"], cached["fetched_at"]
    rows = fetch_rows()
    by_isin = {}
    for row in rows:
        isin = (row.get("xml_isin") or "").upper()
        if isin:
            by_isin[isin] = row
    fetched_at = datetime.now(timezone.utc).isoformat()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"fetched_at": fetched_at, "by_isin": by_isin}, ensure_ascii=False),
        encoding="utf-8",
    )
    return by_isin, fetched_at


BELOW = {
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
    "CCC", "CC", "C", "D", "SD",
}


def group_from_text(text: str | None) -> str | None:
    if not text:
        return None
    token = text.strip().upper().replace(" ", "")
    if token in TEXT_GROUP:
        return TEXT_GROUP[token]
    if token in BELOW:
        return "below"
    return None


def blocker(row: dict | None) -> str | None:
    if not row:
        return "выпуска нет в скринере ДОХОДЪ"
    if (row.get("currency") or "").upper() not in ("RUB", "SUR"):
        return "в скринере валюта выпуска не рубль"
    if str(row.get("coupon_type")) != "1":
        return "в скринере купон не фиксированный"
    event = (row.get("event") or "").strip()
    if event != "погашение":
        return f"событие в дату: «{event or 'пусто'}», допускается только «погашение»"
    flags = {flag for flag in (row.get("eventFlag") or "").split(",") if flag}
    bad = sorted(flags & BAD_FLAGS)
    if bad:
        return "скринер помечает выпуск: " + ", ".join(bad)
    kind = row.get("emitent_type")
    if kind not in ("корпоративные", "государственные"):
        return f"тип эмитента в скринере: {kind or 'не указан'}"
    return None


def number(row: dict | None, key: str) -> float | None:
    if not row:
        return None
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
