"""Предварительный пакет по выгрузке ДОХОДЪ, без биржевого принта.

Медиана оборота из файла не подменяет средний оборот за 10 сессий.
Дата доходности в этих книгах не заполнена, поэтому цены здесь не называются текущими.
Посленалоговая YTM не считается: в файле нет графика купонов, а YTM × 0,87 ответом не является.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
from openpyxl import load_workbook

from engine.cashflows import naive_haircut
from engine.corpbonds import rating_group
from engine.dohod import group_from_text
from engine.rules import (
    CONTRIBUTION_RUB,
    CORP_MIN_G_SPREAD_BP,
    CURVE_TURNOVER_RUB,
    MIN_POSITION_RUB,
    MIN_TURNOVER_RUB,
    OFZ_MAX_YEARS,
    OFZ_MIN_COUPON,
    OFZ_MIN_YEARS,
    SCORE_THRESHOLD,
    TARGET_YTM_PRETAX,
    TAX_RATE,
    UNSPENT_ALERT,
    broker_for_month,
    group_a_allowed,
)
from engine.scoring import score_corporate
from engine.select import _curve, _money, _position_dirty, _size, ban_reason

ROOT = Path(__file__).resolve().parents[1]
OFZ_BOOK = ROOT / "data" / "imports" / "2026-11-10-ofz-duration.xlsx"
CORP_BOOK = ROOT / "data" / "imports" / "2026-11-10-corp-duration.xlsx"
PRIOR_PATH = ROOT / "data" / "latest_package.json"
OUT_PATH = ROOT / "data" / "preview_package.json"

ANALYSIS_DATE = date(2026, 11, 10)
TUESDAY = date(2026, 11, 10)

_RU_MONTH = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _ru_day(value: date) -> str:
    return f"{value.day} {_RU_MONTH[value.month]}"

# Выпуски черновика 6 октября. Журнал исполнения пуст, повтор не доказан.
UNCONFIRMED_DRAFT = ("RU000A1038V6", "RU000A100EF5")


def _num(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and np.isnan(value):
            return None
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if text.lower() in {"", "-", "—", "n/a", "na", "none", "нет"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _rows(path: Path) -> list[dict]:
    book = load_workbook(path, data_only=True)
    sheet = book.active
    headers = [_text(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    found = []
    for raw in sheet.iter_rows(min_row=2, values_only=True):
        if not raw or not raw[0]:
            continue
        found.append({headers[index]: raw[index] for index in range(len(headers))})
    return found


def _lot(face: float, minimum: float | None) -> int:
    if face <= 0:
        return 1
    if minimum is None:
        return 1
    if abs(minimum - face) < 0.01:
        return 1
    if minimum > face and abs(minimum / face - round(minimum / face)) < 1e-6:
        return max(1, int(round(minimum / face)))
    if minimum < face and abs(minimum - round(minimum)) < 1e-6:
        return max(1, int(round(minimum)))
    return 1


def _period_days(per_year: float | None) -> int | None:
    if per_year is None:
        return None
    mapping = {12: 30, 4: 91, 2: 182, 1: 365}
    return mapping.get(int(round(per_year)))


def _coupon_label(per_year: float | None) -> str:
    labels = {12: "ежемесячный", 4: "квартальный", 2: "раз в полгода", 1: "раз в год"}
    if per_year is None:
        return "частота не указана"
    return labels.get(int(round(per_year)), f"{int(round(per_year))} раз в год")


def _load_prior(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            isin = node.get("isin")
            agency = node.get("rating_agency")
            if isinstance(isin, str) and agency and agency != "скринер ДОХОДЪ":
                found[isin.upper()] = {
                    "rating": node.get("rating"),
                    "agency": agency,
                    "date": node.get("rating_date"),
                    "outlook": node.get("rating_outlook"),
                    "source": node.get("rating_source"),
                    "asof": "2026-10-06",
                }
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def _related(issuer: str, borrower: str, name: str) -> str | None:
    haystack = f"{issuer} {borrower} {name}".lower().replace("ё", "е")
    tokens = {part for part in "".join(char if char.isalnum() else " " for char in haystack).split()}
    if "фпк" in tokens or "федеральная пассажирская" in haystack:
        return "ФПК — пассажирская дочка РЖД. Связку с РЖД и ПГК показываем, автоматически не покупаем."
    return None


def _normalize(row: dict, source: str) -> dict:
    face = _num(row.get("Текущий номинал")) or 0.0
    per_year = _num(row.get("Купон (раз/год)"))
    price = _num(row.get("Цена, % от номинала"))
    nkd = _num(row.get("НКД")) or 0.0
    coupon_pct = _num(row.get("Текущий купон, %"))
    coupon_value = _num(row.get("Размер купона"))
    clean = None if price is None else face * price / 100
    annual = None
    if coupon_value is not None and per_year is not None:
        annual = coupon_value * per_year
    elif coupon_pct is not None and face:
        annual = face * coupon_pct / 100
    current = _num(row.get("Текущая доходность, %"))
    if current is None and annual and clean:
        current = annual / clean * 100
    median_mln = _num(row.get("Медиана дневного оборота (млн в валюте торгов)"))
    frn_index = _text(row.get("Базовый индекс (для FRN)"))
    coupon_type = _text(row.get("Тип купона")).lower()
    # Новые выгрузки ДОХОДЪ иногда оставляют «Тип купона» пустым.
    # Если базового индекса FRN нет — считаем купон фиксированным; иначе плавающий.
    if not coupon_type:
        coupon_type = "плавающий" if frn_index else "фиксированный"
    return {
        "isin": _text(row.get("ISIN")).upper(),
        "shortname": _text(row.get("Название")),
        "issuer": _text(row.get("Эмитент")),
        "borrower": _text(row.get("Основной заемщик")),
        "currency": _text(row.get("Валюта номинала")).upper(),
        "event": _text(row.get("Событие в дату")).lower(),
        "years": _num(row.get("Лет до даты")),
        "duration": _num(row.get("Дюрация")),
        "ytm": _num(row.get("Эффективная доходность (YTM), %")),
        "simple_yield": _num(row.get("Простая доходность, %")),
        "current_yield": None if current is None else round(current, 2),
        "screener_rating": _text(row.get("Кредитное качество (рэнкинг)")).upper(),
        "credit_quality": _num(row.get("Кредитное качество (число, max=10)")),
        "issuer_quality": _num(row.get("Качество эмитента (max=10)")),
        "median_mln": median_mln,
        "median_rub": None if median_mln is None else median_mln * 1_000_000,
        "issue_date": _text(row.get("Дата выпуска")),
        "maturity": _text(row.get("Дата погашения")),
        "yield_asof": _text(row.get("Дата, к которой рассчитывается доходность")),
        "face": face,
        "min_lot_raw": _num(row.get("Минимальный лот")),
        "lot": _lot(face, _num(row.get("Минимальный лот"))),
        "price": price,
        "nkd": nkd,
        "coupon_value": coupon_value,
        "coupon_percent": coupon_pct,
        "per_year": per_year,
        "coupon_label": _coupon_label(per_year),
        "coupon_type": coupon_type,
        "subordinated": _text(row.get("Субординированная (да/нет)")).lower() == "да",
        "guaranteed": _text(row.get("С гарантией (да/нет)")).lower() == "да",
        "issuer_type": _text(row.get("Тип эмитента")).lower(),
        "frn_index": frn_index,
        "annual_coupon": None if annual is None else round(annual, 2),
        "source_file": source,
    }


def _hard_block(item: dict) -> str | None:
    if item["currency"] not in {"RUB", "SUR"}:
        return "номинал не в рублях"
    if item["coupon_type"] != "фиксированный" or item["frn_index"]:
        return "купон не фиксированный"
    if item["event"] != "погашение":
        return f"событие в дату: «{item['event'] or 'пусто'}», допускается только «погашение»"
    if item["subordinated"]:
        return "субординированный выпуск: рейтинг эмитента на выпуск не переносим"
    if item["issuer_type"] not in {"корпоративные", "государственные"}:
        return f"тип эмитента: {item['issuer_type'] or 'не указан'}"
    if item["ytm"] is None or item["duration"] is None or item["price"] is None or item["years"] is None:
        return "нет цены, доходности, дюрации или срока"
    if item["median_mln"] is None:
        return "в выгрузке нет оборота: отсутствие данных — отказ, медиану на среднее не подменяем"
    names = " ".join(part for part in (item["issuer"], item["borrower"], item["shortname"]) if part)
    ban = ban_reason(item["issuer"], None) or ban_reason(item["borrower"], None) or ban_reason(names, None)
    if ban:
        return ban
    return None


def _score(item: dict, curve: list[tuple[float, float]], confirmed: bool) -> dict:
    spread, clamped = (None, False)
    curve_ytm = None
    if curve and item["duration"] is not None and item["ytm"] is not None:
        curve_ytm, clamped = _curve(curve, item["duration"])
        spread = (item["ytm"] - curve_ytm) * 100
    scored = score_corporate(
        g_spread_bp=spread,
        net_debt_ebitda=None,
        ebitda_interest=None,
        credit_quality=item["credit_quality"],
        issuer_quality=item["issuer_quality"],
        coupon_period_days=_period_days(item["per_year"]),
        rating_confirmed=confirmed,
    )
    return {
        "g_spread_bp": None if spread is None else round(spread, 1),
        "curve_ytm": None if curve_ytm is None else round(curve_ytm, 4),
        "clamped": clamped,
        "score": scored,
    }


def _flags(group: str | None, spread: float | None, price: float | None, outlook: str | None) -> list[str]:
    flags = []
    if spread is not None and spread > 800 and group in {"a", "aa"}:
        flags.append(f"G-спред {spread:.0f} б.п. выше 800 при рейтинге A и выше")
    if group == "a" and price is not None and price < 95:
        flags.append(f"цена {price:.2f}% ниже 95% номинала в группе A")
    if outlook and "негат" in outlook.lower():
        flags.append(f"прогноз рейтинга: {outlook}")
    return flags


def _public(item: dict, extra: dict) -> dict:
    keep = (
        "isin", "shortname", "issuer", "borrower", "years", "duration", "ytm",
        "current_yield", "screener_rating", "credit_quality", "issuer_quality",
        "median_mln", "price", "nkd", "face", "lot", "coupon_percent", "coupon_label",
        "annual_coupon", "maturity", "guaranteed", "yield_asof",
    )
    payload = {key: item[key] for key in keep}
    payload.update(extra)
    return payload


def _allocate(picks: list[dict], cap: float, budget: float, rate: float) -> list[dict]:
    cash_left = budget
    package = []
    for pick in picks:
        dirty = _position_dirty(pick["face"], pick["price"], pick["nkd"])
        sized = _size(dirty, pick["lot"], cap * pick["slot_share"], cash_left, rate)
        if sized is None:
            continue
        annual = pick.get("annual_coupon")
        package.append({
            **{key: pick[key] for key in (
                "isin", "shortname", "issuer", "years", "duration", "ytm", "price",
                "nkd", "face", "lot", "coupon_percent", "coupon_label", "current_yield",
                "annual_coupon", "maturity", "median_mln", "slot_id", "slot_title",
            )},
            "verdict": "предварительно брать",
            "qty": sized["qty"],
            "dirty": _money(dirty),
            "position_sum": sized["position_sum"],
            "commission": sized["commission"],
            "debit": sized["debit"],
            "annual_coupon_position": None if annual is None else _money(annual * sized["qty"]),
            "naive_ytm_after_13": naive_haircut(pick["ytm"], TAX_RATE),
            "ytm_after_tax": None,
            "price_source": "выгрузка ДОХОДЪ, дата доходности в файле не заполнена",
        })
        cash_left -= sized["debit"]
    return package


def _weights(package: list[dict]) -> dict:
    spent = sum(item["position_sum"] for item in package)
    if spent <= 0:
        return {"ytm": None, "duration_years": None, "meets_target": False, "weight_base": "сумма позиций с НКД"}
    ytm = sum(item["ytm"] * item["position_sum"] for item in package) / spent
    duration = sum(item["duration"] * item["position_sum"] for item in package) / spent
    return {
        "ytm": round(ytm, 4),
        "duration_years": round(duration, 3),
        "meets_target": ytm + 1e-9 >= TARGET_YTM_PRETAX,
        "target": TARGET_YTM_PRETAX,
        "weight_base": "сумма позиций с НКД, без комиссии",
        "ytm_after_tax": None,
        "naive_ytm_after_13": round(sum(item["naive_ytm_after_13"] * item["position_sum"] for item in package) / spent, 4),
    }


def _cash(package: list[dict], budget: float) -> dict:
    spent = round(sum(item["position_sum"] for item in package) + 1e-9, 2)
    commission = round(sum(item["commission"] for item in package) + 1e-9, 2)
    debit = round(sum(item["debit"] for item in package) + 1e-9, 2)
    remainder = round(budget - debit, 2)
    return {
        "spent_dirty": spent,
        "commission": commission,
        "total_debit": debit,
        "remainder": remainder,
        "remainder_pct": round(remainder / budget, 4) if budget else None,
        "unspent_alert": remainder > budget * UNSPENT_ALERT + 0.01,
        "positions": len(package),
    }


def _tenor_curve(ofz: list[dict]) -> dict:
    points = [(item["years"], item["ytm"]) for item in ofz if item["years"] is not None and item["ytm"] is not None and (item["median_rub"] or 0) >= CURVE_TURNOVER_RUB]
    result = {}
    for tenor in (2, 5, 10, 15):
        if not points:
            result[str(tenor)] = None
            continue
        ytm, clamped = _curve(points, float(tenor))
        result[str(tenor)] = {"ytm": round(ytm, 4), "clamped": clamped}
    return result


def build_preview(
    ofz_path: Path = OFZ_BOOK,
    corp_path: Path = CORP_BOOK,
    prior_path: Path = PRIOR_PATH,
    budget: float = CONTRIBUTION_RUB,
    analysis_date: date = ANALYSIS_DATE,
    tuesday: date = TUESDAY,
) -> dict:
    file_day = _ru_day(analysis_date)
    broker = broker_for_month(tuesday.month)
    rate = broker["commission_rate"]
    cap = min(budget * (1 - 0.003), budget / (1 + rate))
    ofz_rows = [_normalize(row, ofz_path.name) for row in _rows(ofz_path)]
    corp_rows = [_normalize(row, corp_path.name) for row in _rows(corp_path)]
    prior = _load_prior(prior_path)

    curve_members = [
        item for item in ofz_rows
        if item["coupon_type"] == "фиксированный"
        and item["currency"] in {"RUB", "SUR"}
        and item["event"] == "погашение"
        and not item["subordinated"]
        and item["duration"] is not None
        and item["ytm"] is not None
        and item["median_rub"] is not None
        and item["median_rub"] >= CURVE_TURNOVER_RUB
    ]
    curve = [(item["duration"], item["ytm"]) for item in curve_members]
    durations = sorted(item[0] for item in curve)

    ofz_decisions = []
    eligible_ofz = []
    for item in ofz_rows:
        reason = _hard_block(item)
        if reason is None and (item["years"] or 0) < OFZ_MIN_YEARS:
            reason = "ОФЗ короче 5 лет: для продажи в 2030–2032 году доходность уже слабее большого купона"
        if reason is None and (item["years"] or 0) > OFZ_MAX_YEARS:
            reason = "ОФЗ длиннее 10 лет: к продаже в 2032 году бумага остаётся слишком длинной"
        if reason is None and (item["coupon_percent"] or 0) < OFZ_MIN_COUPON:
            reason = "купон ниже 11%: в этом окне берём большой купон"
        if reason is None and item["issuer_type"] != "государственные":
            reason = "в файле ОФЗ тип эмитента не государственный"
        status = "reject" if reason else "eligible"
        row = _public(item, {
            "status": status,
            "reason": reason or "большой купон, погашение в окне 5–10 лет под продажу в 2030–2032",
            "liquidity": f"медиана выгрузки, среднее за 10 сессий {file_day} не пересчитывалось",
        })
        ofz_decisions.append(row)
        if status == "eligible":
            eligible_ofz.append(item)
    eligible_ofz.sort(
        key=lambda item: (
            0 if (item["coupon_percent"] or 0) >= 12 else 1,
            item["years"] or 99,
            -(item["ytm"] or 0),
        )
    )

    counts: Counter[str] = Counter()
    exceptions = []
    waitlist = []
    review = []
    rejected = []
    for item in corp_rows:
        reason = _hard_block(item)
        if reason:
            counts[reason] += 1
            rejected.append(_public(item, {"status": "reject", "reason": reason}))
            continue
        if item["issuer_type"] != "корпоративные":
            counts["тип эмитента не корпоративный"] += 1
            rejected.append(_public(item, {"status": "reject", "reason": "тип эмитента не корпоративный"}))
            continue
        screener_group = group_from_text(item["screener_rating"])
        known = prior.get(item["isin"])
        agency_group = rating_group(known["rating"]) if known and known.get("rating") else None
        group = agency_group or screener_group
        notes = []
        if known and agency_group and screener_group and agency_group != screener_group:
            notes.append(
                f"скринер ДОХОДЪ показывает {item['screener_rating']}, карточка от 6 октября — {known['rating']}. Для окна срока взято агентство."
            )
        elif known and known.get("rating"):
            notes.append(f"рейтинг {known['rating']} взят из карточки прогона 6 октября, в этой выгрузке дата агентства не перепроверялась.")
        else:
            notes.append(f"буква рейтинга только из этой выгрузки ДОХОДЪ. Агентство {file_day} не сверялось, скринер агентство не заменяет.")
        if item["guaranteed"]:
            notes.append("в выгрузке стоит «с гарантией».")
        scored = _score(item, curve, confirmed=False)
        outlook = known.get("outlook") if known else None
        flags = _flags(group, scored["g_spread_bp"], item["price"], outlook)
        related = _related(item["issuer"], item["borrower"], item["shortname"])
        if related:
            flags.append(related)
        if known and known.get("date"):
            notes.append(
                f"6 октября дата карточки была {known['date']} ({known.get('agency')}). Балл за свежесть в этом прогоне не начислен: агентство заново не открывалось."
            )
        common = {
            "group": group,
            "rating": (known or {}).get("rating") or item["screener_rating"],
            "rating_agency": (known or {}).get("agency") or "скринер ДОХОДЪ",
            "rating_date": (known or {}).get("date"),
            "rating_outlook": outlook,
            "rating_source": (known or {}).get("source") or "https://www.dohod.ru/analytic/bonds",
            "rating_prior": bool(known),
            "g_spread_bp": scored["g_spread_bp"],
            "g_spread_clamped": scored["clamped"],
            "curve_ytm": scored["curve_ytm"],
            "score": scored["score"]["total"],
            "score_parts": scored["score"]["parts"],
            "score_passed": scored["score"]["passed"],
            "flags": flags,
            "notes": notes,
            "liquidity": "медиана выгрузки; среднее за 10 сессий этой датой не подтверждено",
        }
        if group is None or group == "below":
            reason = f"рейтинг {item['screener_rating'] or 'не указан'} ниже A− или не прочитан"
            counts[reason] += 1
            rejected.append(_public(item, {"status": "reject", "reason": reason, **common}))
            continue
        if group == "a" and not group_a_allowed(item.get("issuer") or ""):
            reason = "группа A без госучастия и не из списка крупных конгломератов"
            counts[reason] += 1
            rejected.append(_public(item, {"status": "reject", "reason": reason, **common}))
            continue
        spread = scored["g_spread_bp"]
        if spread is None or spread <= CORP_MIN_G_SPREAD_BP:
            reason = (
                f"не выгоднее ОФЗ: G-спред {spread} б.п."
                if spread is not None
                else "нет G-спреда к кривой ОФЗ: нельзя проверить выгоду против ОФЗ"
            )
            counts[reason] += 1
            rejected.append(_public(item, {"status": "reject", "reason": reason, **common}))
            continue
        years = item["years"]
        in_window = (group == "aa" and 4 <= years <= 7) or (group == "a" and 2 <= years <= 5)
        short_aa = group == "aa" and years < 4
        if short_aa:
            exceptions.append(_public(item, {
                **common,
                "status": "exception",
                "reason": "AAA/AA короче 4 лет: только согласованное исключение, не автоматическая покупка",
            }))
            continue
        if not in_window:
            reason = "срок до погашения вне окна рейтинга"
            counts[reason] += 1
            rejected.append(_public(item, {"status": "reject", "reason": reason, **common}))
            continue
        if not scored["score"]["passed"]:
            extra = ""
            if known and known.get("date"):
                extra = f" Даже если вернуть балл за карточку {known['date']}, выйдет {round(scored['score']['total'] + 1, 2)} — порог всё равно не пройден."
            waitlist.append(_public(item, {
                **common,
                "status": "wait",
                "reason": f"балл {scored['score']['total']} ниже порога {SCORE_THRESHOLD}.{extra}",
            }))
            continue
        if related:
            review.append(_public(item, {
                **common,
                "status": "flagged",
                "reason": related,
            }))
            continue
        review.append(_public(item, {
            **common,
            "status": "review",
            "reason": "порог баллов пройден, но среднее оборота не подтверждено и это не поручение",
        }))

    exceptions.sort(key=lambda item: (-(item["score"] or 0), -(item["ytm"] or 0), item["shortname"]))
    waitlist.sort(key=lambda item: (-(item["score"] or 0), -(item["ytm"] or 0)))
    review.sort(key=lambda item: (len(item["flags"]), -(item["score"] or 0), -(item["ytm"] or 0)))

    ofz_share = next(slot["share"] for slot in broker["slots"] if slot["bucket"] == "ofz")
    ofz_count = 2 if len(eligible_ofz) >= 2 and cap * ofz_share / 2 >= MIN_POSITION_RUB else 1
    picks = []
    for bond in eligible_ofz[:ofz_count]:
        picks.append({
            **bond,
            "slot_id": "ofz",
            "slot_title": "ОФЗ",
            "slot_share": ofz_share / ofz_count,
        })
    package = _allocate(picks, cap, budget, rate)
    weights = _weights(package)
    cash = _cash(package, budget)

    repeat = [item["isin"] for item in package if item["isin"] in UNCONFIRMED_DRAFT]
    next_ofz = eligible_ofz[ofz_count:ofz_count + 2]
    alternate_picks = [{
        **bond,
        "slot_id": "ofz",
        "slot_title": "ОФЗ",
        "slot_share": ofz_share / 2,
    } for bond in next_ofz]
    alternate = _allocate(alternate_picks, cap, budget, rate) if len(alternate_picks) == 2 else []

    third = None
    if len(eligible_ofz) > ofz_count:
        spare = eligible_ofz[ofz_count]
        third_rows = _allocate([{
            **spare,
            "slot_id": "ofz-extra",
            "slot_title": "Третья ОФЗ вместо корпоративного слота",
            "slot_share": 0.35,
        }], cap, budget, rate)
        third = third_rows[0] if third_rows else None

    clean_exceptions = [item for item in exceptions if item["score_passed"] and not item["flags"]]
    agreed = clean_exceptions[0] if clean_exceptions else None
    agreed_size = None
    if agreed:
        source = next(item for item in corp_rows if item["isin"] == agreed["isin"])
        sized = _allocate([{
            **source,
            "slot_id": "corp",
            "slot_title": "Корпорат, только как согласованное исключение",
            "slot_share": 0.35,
        }], cap, budget, rate)
        agreed_size = sized[0] if sized else None

    slots = [
        {"id": slot["id"], "title": slot["title"], "share": slot["share"], "target": _money(cap * slot["share"])}
        for slot in broker["slots"]
    ]

    return {
        "kind": "preview",
        "asof": analysis_date.isoformat(),
        "tuesday": tuesday.isoformat(),
        "preliminary": True,
        "title": "Предварительный пакет на 170 000 ₽",
        "broker": {
            "id": broker["id"],
            "name": broker["name"],
            "agreement": broker["agreement"],
            "commission_rate": rate,
            "parity": "нечётный" if tuesday.month % 2 else "чётный",
            "account": "обычный счёт. До конца 2026 поток не уходит на ИИС-3.",
        },
        "budget": {
            "contribution": budget,
            "extras": 0,
            "total": budget,
            "reserve_rate": 0.003,
            "securities_cap": _money(cap),
            "reserve_amount": _money(budget - cap),
            "slots": slots,
            "extras_note": "В preview купоны сверху взноса не добавляются; боевой пакет берёт их из data/inputs.json.",
        },
        "cash": cash,
        "weights": weights,
        "package": package,
        "limits": {
            "issuer": "Лимит 5% на эмитента не проверен: состава портфеля нет. На Минфин лимит не распространяется.",
            "schedule": f"График купонов, амортизация и оферта по bondization {file_day} не перечитывались. Событие «погашение» — ближайшее событие в выгрузке, оно не доказывает отсутствие амортизации дальше по графику.",
            "calendar": "Календарь купонов на 12 месяцев из этой выгрузки не строится. Из НКД он не восстанавливался.",
            "tax": "Посленалоговая YTM не посчитана. Для неё нужен IRR купонов и дисконта к номиналу. YTM × 0,87 показана только как наивное сравнение.",
        },
        "curve": {
            "method": "G-спред: numpy.interp доходности ОФЗ по дюрации. В кривую вошли фиксированные рублёвые ОФЗ из файла с медианой оборота от 20 млн ₽. Это медиана, не среднее.",
            "points": len(curve),
            "duration_min": None if not durations else round(durations[0], 3),
            "duration_max": None if not durations else round(durations[-1], 3),
            "tenor_ytm": _tenor_curve(ofz_rows),
            "tenor_note": "Утренние точки 2/5/10/15 лет интерполированы по сроку до погашения, отдельно от G-спреда.",
        },
        "ofz": ofz_decisions,
        "exceptions": exceptions,
        "waitlist": waitlist,
        "review": review,
        "rejected": rejected,
        "rejected_counts": dict(counts.most_common()),
        "repeat": {
            "isins": repeat,
            "note": "ОФЗ 26238 и 26230 совпадают с черновиками 6 и 13 октября. Журнал исполнения пуст, повтор не считается доказанным. Если они уже куплены, ниже запасная пара.",
        },
        "alternate_if_already_bought": {
            "package": alternate,
            "weights": _weights(alternate),
            "cash": _cash(alternate, budget),
        },
        "variants": [
            {
                "title": "Оставить корпоративный слот пустым",
                "detail": "Так и собран пакет. Деньги слота в ОФЗ молча не перенесены. Остаток больше 10% взноса.",
            },
            {
                "title": "Третья ОФЗ меняет норму 65/35",
                "detail": "Это вариант, не пакет.",
                "position": third,
            },
            {
                "title": "Короткий AAA/AA только отдельным согласием",
                "detail": "Все короткие AAA/AA с заполненной медианой лежат в одной таблице, включая ФосАгро. Первая строка варианта — максимальный балл без красных флагов. Срок сам по себе никого из этого списка не выкидывает.",
                "position": agreed_size,
                "name": None if agreed is None else agreed["shortname"],
            },
        ],
        "sources": [
            {"file": ofz_path.name, "rows": len(ofz_rows), "role": "ОФЗ"},
            {"file": corp_path.name, "rows": len(corp_rows), "role": "корпораты"},
        ],
        "caveats": [
            f"Дата, к которой считается доходность, в обеих книгах стоит прочерком. Котировка не называется биржевым принтом {file_day}.",
            "Колонка оборота — медиана. Порог 5 и 20 млн ₽ в правилах считается по среднему за 10 сессий. Медиана его не заменяет и не считается пройденным порогом.",
            f"Балл за свежесть рейтинга равен нулю: АКРА, Эксперт РА и НКР {file_day} не открывались. Даты карточек 6 октября упомянуты как прошлый прогон.",
            "NetDebt/Equity, Inside Q и Outside Q в баллы не входят. Вместо долга/EBITDA и покрытия процентов взяты число кредитного качества и качество эмитента, замена подписана.",
            (
                f"Кратчайшая дюрация ОФЗ в кривой файла — {durations[0]:.2f} года. "
                "numpy.interp за пределом диапазона берёт край кривой. Такой G-спред помечен и не считается точкой внутри кривой."
            ) if durations else "Кривая ОФЗ из файла не собралась.",
            "Лимит 5% и порог 15 млн не проверены: оценки портфеля нет. Акции не покупаются.",
            "Это не инвестиционная рекомендация и не поручение брокеру.",
        ],
        "disclaimer": "Предварительный расчёт по выгрузке. Это не индивидуальная инвестиционная рекомендация и не поручение на сделку.",
    }


def main() -> None:
    report = build_preview()
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    weights = report["weights"]
    cash = report["cash"]
    print(f"{report['tuesday']} {report['broker']['name']} {report['broker']['agreement']}")
    print(f"позиций {cash['positions']}, YTM {weights['ytm']}, дюрация {weights['duration_years']}, остаток {cash['remainder']}")
    for item in report["package"]:
        print(f"  {item['shortname']} {item['qty']} шт, {item['position_sum']} ₽, YTM {item['ytm']}")
    print(f"исключений {len(report['exceptions'])}, ожидание {len(report['waitlist'])}, к сверке {len(report['review'])}, отказ {len(report['rejected'])}")


if __name__ == "__main__":
    main()
