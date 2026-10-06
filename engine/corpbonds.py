"""Рейтинг и отрасль с публичной карточки CorpBonds.

Это агрегатор, не сайт АКРА, Эксперт РА или НКР. Уровень рейтинга для
жёсткого фильтра берём отсюда и прямо называем источник. Балл за свежесть
рейтинга начисляется только если в карточке эмитента есть дата действия
агентства за последние 12 месяцев: саму карточку агентства этот прогон
дополнительно не открывает, поэтому балл помечен как «по дате в агрегаторе,
не по странице агентства».
"""

from __future__ import annotations

import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

UA = {"User-Agent": "tuesday-bond-agent/1.0"}
AGENCIES = ("АКРА", "Эксперт РА", "НКР")


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8", "ignore")


def _text_lines(html: str) -> list[str]:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"&#x([0-9A-Fa-f]+);", lambda match: chr(int(match.group(1), 16)), html)
    html = html.replace("&nbsp;", " ").replace("&times;", " ")
    html = re.sub(r"<[^>]+>", "\n", html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in html.splitlines()]
    return [line for line in lines if line]


def _org_id(html: str) -> str | None:
    match = re.search(r'href="(/org/\d+)"', html)
    if not match:
        return None
    return match.group(1).rstrip("/").split("/")[-1]


def _normalize_rating(raw: str) -> str | None:
    text = raw.upper().replace(" ", "")
    text = text.replace("(RU)", "").replace("RU", "", 1) if text.startswith("RU") else text
    text = text.replace("(RU)", "")
    text = text.replace("А", "A").replace("В", "B").replace("С", "C")
    # Кириллическая А уже заменена. Остаётся шкала AAA..C.
    match = re.search(r"(AAA|AA\+|AA-|AA|A\+|A-|A|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|B)", text)
    if not match:
        return None
    return match.group(1)


def rating_group(rating: str | None) -> str | None:
    if rating is None:
        return None
    if rating.startswith("AAA") or rating.startswith("AA"):
        return "aa"
    if rating.startswith("A"):
        return "a"
    return "below"


def _parse_agency_date(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def parse_bond_page(html: str) -> dict:
    lines = _text_lines(html)
    issuer = None
    for index, line in enumerate(lines):
        if line.startswith("Эмитент"):
            issuer = lines[index + 1] if index + 1 < len(lines) else None
            break
    ratings: list[dict] = []
    # Короткий блок «Рейтинг / Эксперт РА AAA / АКРА AAA».
    for index, line in enumerate(lines):
        if line == "Рейтинг" and index + 1 < len(lines):
            for follow in lines[index + 1:index + 6]:
                if follow in ("Тип", "Доходность и цена", "Кредитный рейтинг"):
                    break
                for agency in AGENCIES:
                    if follow.startswith(agency):
                        ratings.append({
                            "agency": agency,
                            "rating": _normalize_rating(follow[len(agency):]),
                            "date": None,
                            "outlook": None,
                            "action": None,
                        })
            break
    kind = None
    for index, line in enumerate(lines):
        if line == "Тип" and index + 1 < len(lines):
            kind = lines[index + 1]
            break
    return {
        "issuer": issuer,
        "org_id": _org_id(html),
        "ratings": [item for item in ratings if item["rating"]],
        "instrument_type": kind,
    }


def parse_org_page(html: str) -> dict:
    lines = _text_lines(html)
    sector = None
    for index, line in enumerate(lines):
        if line == "Отрасль" and index + 1 < len(lines):
            sector = lines[index + 1]
            break
    actions: list[dict] = []
    agencies_seen = set()
    index = 0
    while index < len(lines) - 4:
        agency = lines[index]
        if agency in AGENCIES and lines[index] not in agencies_seen:
            rating = _normalize_rating(lines[index + 1])
            rated_on = _parse_agency_date(lines[index + 2])
            outlook = lines[index + 3]
            action = lines[index + 4]
            if rating and rated_on and outlook in ("Стабильный", "Позитивный", "Негативный", "Развивающийся", "На пересмотре"):
                actions.append({
                    "agency": agency,
                    "rating": rating,
                    "date": rated_on,
                    "outlook": outlook,
                    "action": action,
                })
                agencies_seen.add(agency)
                index += 5
                continue
        index += 1
    best = _best_rating(actions)
    return {"sector": sector, "actions": actions, "best": best}


def _best_rating(actions: list[dict]) -> dict | None:
    if not actions:
        return None
    rank = {
        "AAA": 21, "AA+": 20, "AA": 19, "AA-": 18,
        "A+": 17, "A": 16, "A-": 15,
        "BBB+": 14, "BBB": 13, "BBB-": 12,
    }
    return max(actions, key=lambda item: (rank.get(item["rating"], 0), item["date"]))


def confirmed_within_year(action: dict | None, asof: date) -> bool:
    if not action or not action.get("date"):
        return False
    rated = date.fromisoformat(action["date"])
    action_name = action.get("action") or ""
    fresh_action = action_name.startswith(("Подтверж", "Повыш", "Присво"))
    return (asof - rated).days <= 366 and fresh_action


class CorpBonds:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cached(self, kind: str, key: str, url: str) -> str:
        path = self.cache_dir / f"{kind}-{key}.html"
        if path.exists() and path.stat().st_size > 1000:
            return path.read_text(encoding="utf-8", errors="ignore")
        html = _fetch(url)
        path.write_text(html, encoding="utf-8")
        return html

    def bond(self, isin: str) -> dict:
        html = self._cached("bond", isin, f"https://corpbonds.ru/bond/{isin}")
        parsed = parse_bond_page(html)
        parsed["source_url"] = f"https://corpbonds.ru/bond/{isin}"
        return parsed

    def org(self, org_id: str) -> dict:
        html = self._cached("org", org_id, f"https://corpbonds.ru/org/{org_id}")
        parsed = parse_org_page(html)
        parsed["source_url"] = f"https://corpbonds.ru/org/{org_id}"
        return parsed

    def enrich(self, bonds: list[dict], workers: int = 8) -> None:
        def job(bond: dict) -> tuple[str, dict]:
            isin = bond.get("ISIN") or bond["SECID"]
            try:
                card = self.bond(isin)
                if card.get("org_id"):
                    card["org"] = self.org(card["org_id"])
                return bond["SECID"], card
            except Exception as error:
                return bond["SECID"], {"error": str(error), "ratings": [], "issuer": None}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(job, bond) for bond in bonds]
            found = {secid: card for secid, card in (item.result() for item in as_completed(futures))}
        for bond in bonds:
            bond["corpbonds"] = found.get(bond["SECID"], {})
