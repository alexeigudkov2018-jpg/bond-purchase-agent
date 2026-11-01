"""Сборка вторничного пакета: фильтры, баллы, лоты, комиссия."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np

from engine.cashflows import (
    after_tax_ytm,
    coupon_calendar,
    naive_haircut,
    parse_iso,
    pretax_ytm_from_schedule,
)
from engine.corpbonds import confirmed_within_year, rating_group
from engine.dohod import blocker as dohod_blocker
from engine.dohod import group_from_text, number as dohod_number
from engine.moex import (
    description,
    duration_days,
    effective_yield,
    is_fixed_coupon,
    is_rub,
    listed_offer,
    moex_g_spread,
    quote,
    to_maturity,
    years_to,
    bondization,
)
from engine.rules import (
    ISSUER_BANS,
    ISSUER_LIMIT,
    MAX_POSITIONS,
    MIN_POSITION_RUB,
    MIN_TURNOVER_RUB,
    SCORE_THRESHOLD,
    SECTOR_BANS,
    OFZ_MAX_YEARS,
    OFZ_MIN_COUPON,
    OFZ_MIN_YEARS,
    TARGET_YTM_PRETAX,
    TAX_RATE,
    UNSPENT_ALERT,
    broker_for_month,
)
from engine.scoring import score_corporate

RATING_RANK = {
    "AAA": 21, "AA+": 20, "AA": 19, "AA-": 18,
    "A+": 17, "A": 16, "A-": 15,
    "BBB+": 14, "BBB": 13, "BBB-": 12,
    "BB+": 11, "BB": 10, "BB-": 9,
    "B+": 8, "B": 7, "B-": 6,
}


def fold(value: str | None) -> str:
    text = (value or "").lower().replace("ё", "е")
    for char in ("«", "»", "\"", "'", "“", "”"):
        text = text.replace(char, "")
    return " ".join(text.split())


def tokens(value: str) -> set[str]:
    cleaned = "".join(char if char.isalnum() else " " for char in fold(value))
    return set(cleaned.split())


def sector_exception(issuer: str) -> bool:
    name = fold(issuer)
    if "трансконтейнер" in name:
        return True
    if "контейнерн" in name and ("первая" in name or "пкт" in tokens(name)):
        return True
    if "пкт" in tokens(name):
        return True
    return False


def ban_reason(issuer: str, sector: str | None) -> str | None:
    name = fold(issuer)
    if not name:
        return None
    for pattern, reason in ISSUER_BANS:
        if pattern in name:
            return reason
    for word, reason in (("ржд", "РЖД: запрет из-за связки с ПГК"), ("мтс", "МТС: полный стоп до 2029 года"), ("пгк", "ПГК: полный стоп до 2029 года"), ("камаз", "КАМАЗ: старый стоп не отменён")):
        if word in tokens(name):
            return reason
    if sector_exception(issuer):
        return None
    haystack = f"{name} {fold(sector)}"
    for pattern, reason in SECTOR_BANS:
        if pattern in haystack:
            return f"секторный запрет: {reason}"
    return None


def load_screener(directory: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                isin = (row.get("isin") or row.get("ISIN") or "").strip().upper()
                if not isin:
                    continue
                found[isin] = {key.strip().lower(): (value or "").strip() for key, value in row.items()}
                found[isin]["_file"] = path.name
    return found


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").replace("%", ""))
    except ValueError:
        return None


def _worst_rating(card: dict) -> dict | None:
    org = (card or {}).get("org") or {}
    actions = list(org.get("actions") or [])
    if actions:
        return min(actions, key=lambda item: RATING_RANK.get(item["rating"], 0))
    page = [item for item in (card or {}).get("ratings") or [] if item.get("rating")]
    if not page:
        return None
    worst = min(page, key=lambda item: RATING_RANK.get(item["rating"], 0))
    return worst


def _curve(points: list[tuple[float, float]], x: float) -> tuple[float, bool]:
    ordered = sorted(points)
    xs = [item[0] for item in ordered]
    ys = [item[1] for item in ordered]
    clamped = x < xs[0] or x > xs[-1]
    return float(np.interp(x, xs, ys)), clamped


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _position_dirty(face: float, price_pct: float, nkd: float) -> float:
    return face * price_pct / 100 + nkd


def _size(dirty: float, lot: int, slot_target: float, cash_left: float, rate: float) -> dict | None:
    if dirty <= 0 or lot < 1:
        return None
    raw = int(slot_target // dirty)
    qty = raw - (raw % lot)
    if qty < lot and dirty <= slot_target:
        qty = lot if dirty <= slot_target else 0
    if qty < lot:
        return None

    def debit(quantity: int) -> tuple[float, float, float]:
        position = quantity * dirty
        commission = position * rate
        return position, commission, position + commission

    position, commission, total = debit(qty)
    if position < MIN_POSITION_RUB:
        needed = qty
        while needed * dirty < MIN_POSITION_RUB:
            needed += lot
        if needed * dirty <= max(slot_target, MIN_POSITION_RUB) and debit(needed)[2] <= cash_left:
            qty = needed
            position, commission, total = debit(qty)
    while qty >= lot and total > cash_left + 0.01:
        qty -= lot
        if qty < lot:
            return None
        position, commission, total = debit(qty)
    if position + 0.01 < MIN_POSITION_RUB:
        return None
    return {
        "qty": qty,
        "position_sum": _money(position),
        "commission": _money(commission),
        "debit": _money(total),
    }


def _red_flags(group: str | None, g_spread: float | None, price: float | None, outlook: str | None) -> list[str]:
    flags = []
    if g_spread is not None and g_spread > 800 and group in ("a", "aa"):
        flags.append(f"G-спред {g_spread:.0f} б.п. выше 800 при рейтинге A и выше")
    if group == "a" and price is not None and price < 95:
        flags.append(f"цена {price:.2f}% ниже 95% номинала при рейтинге группы A")
    if outlook and "негат" in outlook.lower():
        flags.append(f"прогноз рейтинга: {outlook}")
    if outlook and "пересмотр" in outlook.lower():
        flags.append(f"рейтинг на пересмотре: {outlook}")
    return flags


def _coupon_label(period: int | None) -> str:
    if period is None:
        return "неизвестная частота"
    if period <= 35:
        return "ежемесячный"
    if 80 <= period <= 100:
        return "квартальный"
    if 160 <= period <= 200:
        return "полугодовой"
    return f"каждые {period} дн."


def build_package(
    *,
    universe: dict,
    sessions: list[str],
    asof: date,
    budget: float,
    extras: float,
    extras_note: str,
    screener: dict[str, dict],
    positions: list[dict],
    portfolio_value: float | None,
    last_week_isins: set[str],
    losing_isins: set[str],
) -> dict:
    broker = broker_for_month(asof.month)
    rate = broker["commission_rate"]
    securities_cap = min(budget * (1 - 0.003), budget / (1 + rate))
    reserve_amount = _money(budget - securities_cap)

    ofz_rows = [row for row in universe["TQOB"] if _ofz_hard(row)]
    corp_rows = [row for row in universe["TQCB"] if _corp_structural(row, asof)]

    curve_points = []
    for bond in ofz_rows:
        turnover = (bond.get("turnover") or {}).get("mean")
        ytm = effective_yield(bond)
        duration = duration_days(bond)
        if turnover is None or turnover < 20_000_000 or ytm is None or duration is None:
            continue
        curve_points.append((duration / 365.0, ytm, years_to(bond, asof) or 0))
    curve_duration = [(item[0], item[1]) for item in curve_points]
    curve_maturity = [(item[2], item[1]) for item in curve_points if item[2] > 0]

    rejected: list[dict] = []
    waitlist: list[dict] = []
    exceptions: list[dict] = []
    eligible: dict[str, list[dict]] = {"ofz": [], "aa": [], "a": [], "corp": []}

    for bond in ofz_rows:
        verdict = _assess_ofz(bond, asof, sessions, last_week_isins)
        if verdict["status"] == "reject":
            rejected.append(verdict)
            continue
        if verdict["status"] == "wait":
            waitlist.append(verdict)
            continue
        eligible["ofz"].append(verdict)

    for bond in corp_rows:
        verdict = _assess_corp(
            bond,
            asof=asof,
            sessions=sessions,
            curve=curve_duration,
            screener=screener,
            last_week_isins=last_week_isins,
            losing_isins=losing_isins,
        )
        status = verdict["status"]
        if status == "reject":
            rejected.append(verdict)
        elif status == "exception":
            exceptions.append(verdict)
        elif status == "wait":
            waitlist.append(verdict)
        elif status == "eligible":
            bucket = verdict["bucket"]
            eligible[bucket].append(verdict)
            # Слот corp оставлен для старых отчётов; в него идут только AAA/AA.
            if bucket == "aa":
                eligible["corp"].append(verdict)

    for bucket in eligible.values():
        bucket.sort(key=lambda item: item["sort_key"])
    exceptions.sort(key=lambda item: item["sort_key"])

    chosen = _pick_slots(broker, eligible, securities_cap)
    chosen, bondization_rejections = _confirm_bondization(chosen, eligible)
    package = _allocate(chosen, broker, securities_cap, budget, rate)

    weights = _weights(package)
    calendar = coupon_calendar(package, asof=asof)
    spent = sum(item["position_sum"] for item in package)
    commission = sum(item["commission"] for item in package)
    debit = _money(spent + commission)
    remainder = _money(budget - debit)
    remainder_pct = remainder / budget if budget else 0

    limits = _limits(package, positions, portfolio_value, asof)
    market = _market_curve(curve_duration, curve_maturity)
    variants = _variants(
        broker=broker,
        package=package,
        eligible=eligible,
        exceptions=exceptions,
        securities_cap=securities_cap,
        remainder_pct=remainder_pct,
        rate=rate,
    )

    reason_counts: dict[str, int] = {}
    for item in rejected:
        reason_counts[item["reason"]] = reason_counts.get(item["reason"], 0) + 1

    return {
        "asof": asof.isoformat(),
        "broker": {
            "id": broker["id"],
            "name": broker["name"],
            "agreement": broker["agreement"],
            "commission_rate": rate,
            "month": asof.month,
            "parity": "чётный" if asof.month % 2 == 0 else "нечётный",
        },
        "budget": {
            "contribution": _money(budget - extras),
            "extras": _money(extras),
            "extras_note": extras_note,
            "total": _money(budget),
            "reserve_rate": 0.003,
            "reserve_amount": reserve_amount,
            "broker_rate": rate,
            "securities_cap": _money(securities_cap),
            "slots": [
                {"id": slot["id"], "title": slot["title"], "share": slot["share"], "target": _money(securities_cap * slot["share"])}
                for slot in broker["slots"]
            ],
        },
        "turnover": {
            "metric": "среднее дневного оборота VALUE",
            "sessions": sessions,
            "session_count": len(sessions),
            "missing_day": "0 ₽, день входит в среднее",
            "median_note": "медиана посчитана отдельно и в порог 5 млн ₽ не подставляется",
            "threshold": MIN_TURNOVER_RUB,
            "curve_threshold": 20_000_000,
        },
        "package": package,
        "weights": weights,
        "target_ytm": TARGET_YTM_PRETAX,
        "cash": {
            "spent_dirty": _money(spent),
            "commission": _money(commission),
            "total_debit": debit,
            "remainder": remainder,
            "remainder_pct": round(remainder_pct, 4),
            "unspent_alert": remainder_pct > UNSPENT_ALERT + 1e-9,
            "positions": len(package),
            "positions_short": len(package) < 2,
        },
        "calendar": calendar,
        "exceptions": [_public_candidate(item) for item in exceptions],
        "waitlist": [_public_candidate(item) for item in waitlist[:25]],
        "rejected_counts": dict(sorted(reason_counts.items(), key=lambda item: -item[1])[:12]),
        "rejected_examples": [_public_candidate(item) for item in rejected[:15]],
        "limits": limits,
        "market_curve": market,
        "variants": variants,
        "bondization_rejections": bondization_rejections,
        "curve_bonds": len(curve_duration),
        "score_threshold": SCORE_THRESHOLD,
        "max_positions": MAX_POSITIONS,
    }


def _ofz_hard(bond: dict) -> bool:
    if bond.get("STATUS") != "A":
        return False
    if not is_rub(bond) or not is_fixed_coupon(bond) or not to_maturity(bond):
        return False
    if listed_offer(bond):
        return False
    return True


def _corp_structural(bond: dict, asof: date) -> bool:
    if bond.get("STATUS") != "A":
        return False
    if not is_rub(bond) or not is_fixed_coupon(bond) or not to_maturity(bond):
        return False
    if listed_offer(bond):
        return False
    years = years_to(bond, asof)
    if years is None or years < 1 or years > 7.05:
        return False
    coupon = bond.get("COUPONPERCENT")
    period = bond.get("COUPONPERIOD") or 0
    if coupon is not None and float(coupon) < 0.5 and int(period) > 360:
        return False
    return True


def _assess_ofz(bond: dict, asof: date, sessions: list[str], last_week_isins: set[str] | None = None) -> dict:
    years = years_to(bond, asof) or 0
    screen = bond.get("dohod") or {}
    base = _base_fields(bond, asof, (screen.get("emitent") if screen else None) or "Минфин России")
    base["dohod_median_turnover"] = _dohod_median(screen)
    blocked = dohod_blocker(screen or None)
    if blocked:
        return {**base, "status": "reject", "reason": blocked}
    if (bond.get("ISIN") or "").upper() in (last_week_isins or set()):
        return {**base, "status": "reject", "reason": "выпуск куплен на прошлой неделе"}
    if years < OFZ_MIN_YEARS:
        return {**base, "status": "reject", "reason": "ОФЗ короче 6,5 лет: для продажи в 2030–2032 году доходность уже слабее большого купона"}
    if years > OFZ_MAX_YEARS:
        return {**base, "status": "reject", "reason": "ОФЗ длиннее 9,5 лет: к продаже в 2032 году бумага остаётся слишком длинной"}
    coupon = float(bond.get("COUPONPERCENT") or 0)
    if coupon < OFZ_MIN_COUPON:
        return {**base, "status": "reject", "reason": "купон ниже 11%: в этом окне берём большой купон"}
    turnover = bond.get("turnover") or {}
    if turnover.get("mean") is None:
        return {**base, "status": "reject", "reason": "нет данных об обороте"}
    if turnover["mean"] < MIN_TURNOVER_RUB:
        return {**base, "status": "reject", "reason": "средний оборот ниже 5 млн ₽"}
    if base["ytm"] is None or base["duration_days"] is None or base["price"] is None:
        return {**base, "status": "reject", "reason": "нет цены, доходности или дюрации"}
    base.update({
        "status": "eligible",
        "bucket": "ofz",
        "reason": "большой купон, погашение в 2033–2036, под продажу в 2030–2032",
        "sort_key": (0 if coupon >= 12 else 1, years, -(base["ytm"] or 0)),
        "score": None,
        "flags": [],
    })
    return base


def _assess_corp(
    bond: dict,
    *,
    asof: date,
    sessions: list[str],
    curve: list[tuple[float, float]],
    screener: dict[str, dict],
    last_week_isins: set[str],
    losing_isins: set[str],
) -> dict:
    card = bond.get("corpbonds") or {}
    screen = bond.get("dohod") or {}
    issuer = screen.get("emitent") or card.get("issuer") or bond.get("SHORTNAME") or ""
    org = card.get("org") or {}
    sector = screen.get("sector_text") or org.get("sector")
    rating = _worst_rating(card)
    agency_group = rating_group(rating["rating"]) if rating else None
    screener_group = group_from_text(screen.get("credit_rating_text"))
    group = agency_group or screener_group
    base = _base_fields(bond, asof, issuer)
    base["dohod_median_turnover"] = _dohod_median(screen)
    blocked = dohod_blocker(screen or None)
    if blocked:
        return {**base, "status": "reject", "reason": blocked}
    base["sector"] = sector
    base["rating"] = None if rating is None else rating.get("rating")
    base["rating_agency"] = None if rating is None else rating.get("agency")
    base["rating_date"] = None if rating is None else rating.get("date")
    base["rating_outlook"] = None if rating is None else rating.get("outlook")
    base["rating_action"] = None if rating is None else rating.get("action")
    base["rating_source"] = (org.get("source_url") or card.get("source_url"))
    base["instrument_type"] = card.get("instrument_type")
    letter = (screen.get("credit_rating_text") or "").strip()
    base["screener_rating"] = letter or None
    base["screener_quality"] = dohod_number(screen, "quality")
    base["screener_credit_quality"] = dohod_number(screen, "credit_rating")
    isin = (bond.get("ISIN") or "").upper()

    if card.get("instrument_type") and card["instrument_type"] not in ("Корпоративный", None):
        return {**base, "status": "reject", "reason": f"тип инструмента «{card['instrument_type']}», в пакет идут только корпоративные"}
    ban = ban_reason(issuer, sector)
    if ban:
        return {**base, "status": "reject", "reason": ban}
    name = fold(f"{bond.get('SHORTNAME')} {bond.get('SECNAME')} {issuer}")
    if "суб" in tokens(bond.get("SHORTNAME") or "") or "суборд" in name:
        return {**base, "status": "reject", "reason": "субординированный выпуск: рейтинг эмитента на выпуск не переносим"}
    if isin in last_week_isins:
        return {**base, "status": "reject", "reason": "выпуск куплен на прошлой неделе"}
    if isin in losing_isins:
        return {**base, "status": "reject", "reason": "убыточная позиция того же выпуска, усреднение запрещено"}
    turnover = bond.get("turnover") or {}
    if turnover.get("mean") is None:
        return {**base, "status": "reject", "reason": "нет данных об обороте"}
    if turnover["mean"] < MIN_TURNOVER_RUB:
        return {**base, "status": "reject", "reason": "средний оборот ниже 5 млн ₽"}
    if group is None:
        return {**base, "status": "wait", "reason": "нет буквы рейтинга ни в карточке агентства, ни в скринере ДОХОДЪ", "sort_key": (0, 0)}
    if group == "below":
        shown = (rating or {}).get("rating") or letter or "ниже A−"
        return {**base, "status": "reject", "reason": f"рейтинг {shown} ниже A−"}
    if base["ytm"] is None or base["duration_days"] is None or base["price"] is None:
        return {**base, "status": "reject", "reason": "нет цены, доходности или дюрации"}

    g_spread, clamped = (None, False)
    if curve and base["duration_years"] is not None:
        curve_ytm, clamped = _curve(curve, base["duration_years"])
        g_spread = (base["ytm"] - curve_ytm) * 100
    csv_row = screener.get(isin, {})
    confirmed = confirmed_within_year(rating, asof) if rating and rating.get("date") else False
    credit_quality = _float(csv_row.get("credit_quality"))
    if credit_quality is None:
        credit_quality = dohod_number(screen, "credit_rating")
    issuer_quality = _float(csv_row.get("issuer_quality"))
    if issuer_quality is None:
        issuer_quality = dohod_number(screen, "quality")
    scored = score_corporate(
        g_spread_bp=g_spread,
        net_debt_ebitda=_float(csv_row.get("net_debt_ebitda")),
        ebitda_interest=_float(csv_row.get("ebitda_interest")),
        credit_quality=credit_quality,
        issuer_quality=issuer_quality,
        coupon_period_days=bond.get("COUPONPERIOD"),
        rating_confirmed=confirmed,
    )
    flags = _red_flags(group, g_spread, base["price"], rating.get("outlook") if rating else None)
    notes: list[str] = []
    if rating and (rating.get("action") or "").startswith("Пониж"):
        flags.append("рейтинг понижен")
    if agency_group and screener_group and agency_group != screener_group:
        notes.append(f"скринер ДОХОДЪ показывает {letter}, карточка агентства — {rating.get('rating')}. Для окна срока взято агентство.")
    if agency_group is None:
        notes.append("буква рейтинга взята из скринера ДОХОДЪ, карточка агентства не сопоставлена")
        base["rating"] = letter or None
        base["rating_agency"] = "скринер ДОХОДЪ"
        base["rating_source"] = "https://www.dohod.ru/analytic/bonds"
    years = base["years"]
    in_window = (group == "aa" and 4 <= years <= 7) or (group == "a" and 2 <= years <= 5)
    short_aa = group == "aa" and years < 4
    base.update({
        "g_spread_bp": None if g_spread is None else round(g_spread, 1),
        "g_spread_clamped": clamped,
        "moex_g_spread_bp": moex_g_spread(bond),
        "score": scored,
        "flags": flags,
        "notes": notes,
        "rating_confirmed": confirmed,
        "sort_key": (int(agency_group is None), len(flags), -scored["total"], -(base["ytm"] or 0)),
    })
    if group == "a":
        base.update({
            "status": "reject",
            "bucket": "a",
            "reason": "группа A с 01.11.2026 вне автоматического пакета: только ОФЗ и AAA/AA",
        })
        return base
    if short_aa:
        base.update({
            "status": "exception",
            "bucket": "aa-short",
            "reason": "AAA/AA короче 4 лет: кандидат на согласованное исключение, не автоматическая покупка",
        })
        return base
    if not in_window:
        return {**base, "status": "reject", "reason": "срок до погашения вне окна рейтинга"}
    if not scored["passed"]:
        return {
            **base,
            "status": "wait",
            "bucket": group,
            "reason": f"балл {scored['total']} ниже порога {SCORE_THRESHOLD}",
        }
    base.update({"status": "eligible", "bucket": group, "reason": "прошёл жёсткие фильтры и порог баллов"})
    return base


def _dohod_median(row: dict | None) -> float | None:
    value = dohod_number(row, "vol_median")
    if value is None:
        return None
    return round(value * 1_000_000, 2)


def _base_fields(bond: dict, asof: date, issuer: str | None) -> dict:
    quoted = quote(bond)
    face = float(bond.get("FACEVALUE") or 0)
    ytm = effective_yield(bond)
    duration = duration_days(bond)
    years = years_to(bond, asof)
    price = quoted["price"]
    nkd = float(bond.get("ACCRUEDINT") or 0)
    clean = None if price is None else face * price / 100
    annual = None
    if bond.get("COUPONPERCENT") is not None and face:
        annual = face * float(bond["COUPONPERCENT"]) / 100
    current_yield = None
    if annual and clean:
        current_yield = annual / clean * 100
    turnover = bond.get("turnover") or {}
    return {
        "secid": bond["SECID"],
        "isin": bond.get("ISIN"),
        "shortname": bond.get("SHORTNAME"),
        "secname": bond.get("SECNAME"),
        "issuer": issuer or "Минфин России",
        "board": bond.get("board"),
        "maturity": bond.get("MATDATE"),
        "years": round(years, 2) if years is not None else None,
        "face": face,
        "lot": int(bond.get("LOTSIZE") or 1),
        "price": price,
        "price_source": quoted["source"],
        "price_asof": quoted["asof"],
        "price_stale": quoted["stale"],
        "nkd": nkd,
        "coupon_percent": bond.get("COUPONPERCENT"),
        "coupon_value": bond.get("COUPONVALUE"),
        "coupon_period": bond.get("COUPONPERIOD"),
        "coupon_label": _coupon_label(bond.get("COUPONPERIOD")),
        "annual_coupon": None if annual is None else round(annual, 2),
        "current_yield": None if current_yield is None else round(current_yield, 2),
        "ytm": ytm,
        "ytm_source": "MOEX ISS marketdata_yields.EFFECTIVEYIELD",
        "duration_days": duration,
        "duration_years": None if duration is None else round(duration / 365.0, 3),
        "avg_turnover": turnover.get("mean"),
        "median_turnover": turnover.get("median"),
        "traded_days": turnover.get("traded_days"),
        "turnover_sessions": turnover.get("sessions"),
        "listlevel": bond.get("LISTLEVEL"),
        "bond": bond,
    }


def _pick_slots(broker: dict, eligible: dict, cap: float) -> list[dict]:
    picks: list[dict] = []
    ofz = list(eligible["ofz"])
    ofz_slot = next(slot for slot in broker["slots"] if slot["bucket"] == "ofz")
    ofz_count = 1
    if broker["id"] == "alfa" and len(ofz) >= 2 and cap * ofz_slot["share"] / 2 >= MIN_POSITION_RUB:
        ofz_count = 2
    for bond in ofz[:ofz_count]:
        picks.append({**bond, "slot_id": "ofz", "slot_title": ofz_slot["title"], "slot_share": ofz_slot["share"] / ofz_count})

    for slot in broker["slots"]:
        if slot["bucket"] == "ofz":
            continue
        pool = eligible["corp"] if slot["bucket"] == "corp" else eligible[slot["bucket"]]
        used = {item["isin"] for item in picks}
        candidate = next((item for item in pool if item["isin"] not in used), None)
        if candidate:
            picks.append({**candidate, "slot_id": slot["id"], "slot_title": slot["title"], "slot_share": slot["share"]})
    return picks


def _confirm_bondization(picks: list[dict], eligible: dict) -> tuple[list[dict], list[dict]]:
    confirmed: list[dict] = []
    rejections: list[dict] = []
    for pick in picks:
        if pick["slot_id"] == "corp":
            pool = [pick] + [item for item in eligible["corp"] if item["isin"] != pick["isin"]]
        elif pick["bucket"] == "ofz":
            pool = [pick] + [item for item in eligible["ofz"] if item["isin"] != pick["isin"]]
        else:
            pool = [pick] + [item for item in eligible.get(pick["bucket"], []) if item["isin"] != pick["isin"]]
        placed = False
        for candidate in pool:
            if any(item["isin"] == candidate["isin"] for item in confirmed):
                continue
            check = _bondization_check(candidate["bond"])
            if not check["ok"]:
                rejections.append({
                    "secid": candidate["secid"],
                    "isin": candidate["isin"],
                    "shortname": candidate["shortname"],
                    "reason": check["reason"],
                })
                continue
            placed_candidate = {
                **candidate,
                "slot_id": pick["slot_id"],
                "slot_title": pick["slot_title"],
                "slot_share": pick["slot_share"],
                "coupon_schedule": check["coupons"],
                "bondization_note": check["note"],
                "initial_face": check["initial_face"],
            }
            confirmed.append(placed_candidate)
            placed = True
            break
        if not placed:
            rejections.append({
                "secid": pick["secid"],
                "isin": pick["isin"],
                "shortname": pick["shortname"],
                "reason": "слот не заполнен: график выпуска не прошёл проверку",
            })
    return confirmed, rejections


def _bondization_check(bond: dict) -> dict:
    try:
        data = bondization(bond["SECID"])
        info = description(bond["SECID"])
    except Exception as error:
        return {"ok": False, "reason": f"график выпуска не загрузился: {error}", "coupons": [], "note": "", "initial_face": None}
    maturity = parse_iso(bond.get("MATDATE"))
    amort = data["amortizations"]
    extra = []
    for row in amort:
        if row.get("data_source") == "maturity":
            continue
        amort_date = parse_iso(row.get("amortdate"))
        if amort_date and maturity and amort_date < maturity:
            extra.append(row)
    if len(amort) > 1 or extra:
        return {"ok": False, "reason": "в графике есть амортизация", "coupons": [], "note": "", "initial_face": None}
    if data["offers"]:
        return {"ok": False, "reason": "в условиях выпуска есть оферта", "coupons": [], "note": "", "initial_face": None}
    initial = _float(str(info.get("INITIALFACEVALUE") or "")) if info.get("INITIALFACEVALUE") is not None else None
    current = _float(str(info.get("FACEVALUE") or "")) if info.get("FACEVALUE") is not None else None
    if initial and current and current < initial * 0.999:
        return {"ok": False, "reason": "текущий номинал ниже начального", "coupons": [], "note": "", "initial_face": initial}
    coupons = []
    rates = set()
    for row in data["coupons"]:
        day = parse_iso(row.get("coupondate"))
        amount = row.get("value_rub")
        if amount is None:
            amount = row.get("value")
        if day is None or amount is None:
            continue
        coupons.append({"date": day.isoformat(), "amount": float(amount)})
        if row.get("valueprc") is not None and (maturity is None or day <= maturity):
            rates.add(round(float(row["valueprc"]), 4))
    future_rates = set()
    for row in data["coupons"]:
        day = parse_iso(row.get("coupondate"))
        if day and maturity and day > date.today() and row.get("valueprc") is not None:
            future_rates.add(round(float(row["valueprc"]), 4))
    if len(future_rates) > 1:
        return {"ok": False, "reason": "будущие купоны в графике не постоянны", "coupons": coupons, "note": "", "initial_face": initial}
    return {
        "ok": True,
        "reason": "",
        "coupons": coupons,
        "note": "амортизация и оферта в графике MOEX bondization не найдены, номинал равен начальному" if initial and current and abs(initial - current) < 0.01 else "график MOEX bondization проверен",
        "initial_face": initial,
    }


def _allocate(picks: list[dict], broker: dict, cap: float, budget: float, rate: float) -> list[dict]:
    cash_left = budget
    package = []
    for pick in picks:
        dirty = _position_dirty(pick["face"], pick["price"], pick["nkd"])
        slot_target = cap * pick["slot_share"]
        sized = _size(dirty, pick["lot"], slot_target, cash_left, rate)
        if sized is None:
            continue
        clean = pick["face"] * pick["price"] / 100
        maturity = parse_iso(pick["maturity"])
        tax = after_tax_ytm(
            asof=date.today(),
            clean_price=clean,
            nkd=pick["nkd"],
            face=pick["face"],
            coupons=pick.get("coupon_schedule") or [],
            tax_rate=TAX_RATE,
            maturity=maturity,
        )
        own_ytm = pretax_ytm_from_schedule(
            asof=date.today(),
            dirty_price=dirty,
            face=pick["face"],
            coupons=pick.get("coupon_schedule") or [],
            maturity=maturity,
        )
        naive = naive_haircut(pick["ytm"], TAX_RATE)
        flags = list(pick.get("flags") or [])
        verdict = "брать"
        if flags:
            verdict = "брать, красный флаг раскрыт"
        if pick.get("price_stale"):
            flags.append("цена не из текущей сделки")
        item = {
            "slot_id": pick["slot_id"],
            "slot_title": pick["slot_title"],
            "bucket": "ofz" if pick["slot_id"] == "ofz" else pick.get("bucket"),
            "verdict": verdict,
            "secid": pick["secid"],
            "isin": pick["isin"],
            "shortname": pick["shortname"],
            "issuer": pick["issuer"],
            "rating": pick.get("rating"),
            "rating_agency": pick.get("rating_agency"),
            "rating_date": pick.get("rating_date"),
            "rating_outlook": pick.get("rating_outlook"),
            "rating_source": pick.get("rating_source"),
            "rating_confirmed": pick.get("rating_confirmed", False),
            "sector": pick.get("sector"),
            "qty": sized["qty"],
            "lot": pick["lot"],
            "face": pick["face"],
            "initial_face": pick.get("initial_face"),
            "price_pct": pick["price"],
            "price_source": pick["price_source"],
            "price_asof": pick["price_asof"],
            "nkd": _money(pick["nkd"]),
            "dirty": _money(dirty),
            "position_sum": sized["position_sum"],
            "commission": sized["commission"],
            "debit": sized["debit"],
            "ytm": pick["ytm"],
            "ytm_source": pick["ytm_source"],
            "ytm_cashflow": None if own_ytm is None else round(own_ytm, 4),
            "ytm_after_tax": tax["ytm"],
            "ytm_after_tax_method": tax["method"],
            "naive_ytm_after_13": naive,
            "duration_days": pick["duration_days"],
            "duration_years": pick["duration_years"],
            "years": pick["years"],
            "maturity": pick["maturity"],
            "g_spread_bp": pick.get("g_spread_bp"),
            "moex_g_spread_bp": pick.get("moex_g_spread_bp"),
            "score": pick.get("score"),
            "coupon_percent": pick["coupon_percent"],
            "coupon_label": pick["coupon_label"],
            "annual_coupon": pick["annual_coupon"],
            "current_yield": pick["current_yield"],
            "annual_coupon_position": None if pick["annual_coupon"] is None else _money(pick["annual_coupon"] * sized["qty"]),
            "avg_turnover": None if pick["avg_turnover"] is None else round(pick["avg_turnover"], 2),
            "median_turnover": None if pick["median_turnover"] is None else round(pick["median_turnover"], 2),
            "dohod_median_turnover": pick.get("dohod_median_turnover"),
            "screener_rating": pick.get("screener_rating"),
            "screener_quality": pick.get("screener_quality"),
            "screener_credit_quality": pick.get("screener_credit_quality"),
            "traded_days": pick["traded_days"],
            "turnover_sessions": pick["turnover_sessions"],
            "flags": flags,
            "notes": pick.get("notes") or [],
            "reason": pick["reason"],
            "bondization_note": pick.get("bondization_note"),
            "coupon_schedule": pick.get("coupon_schedule") or [],
            "moex_url": f"https://www.moex.com/ru/issue.aspx?board={pick['board']}&code={pick['secid']}",
            "card_url": None if pick["slot_id"] == "ofz" else f"https://corpbonds.ru/bond/{pick['isin']}",
        }
        package.append(item)
        cash_left -= sized["debit"]
    return package


def _weights(package: list[dict]) -> dict:
    spent = sum(item["position_sum"] for item in package)
    if spent <= 0:
        return {"ytm": None, "ytm_after_tax": None, "duration_years": None, "meets_target": False, "by_position": []}
    ytm = sum((item["ytm"] or 0) * item["position_sum"] for item in package) / spent
    tax_values = [item for item in package if item["ytm_after_tax"] is not None]
    tax_base = sum(item["position_sum"] for item in tax_values)
    ytm_tax = None if tax_base <= 0 else sum(item["ytm_after_tax"] * item["position_sum"] for item in tax_values) / tax_base
    duration = sum((item["duration_years"] or 0) * item["position_sum"] for item in package) / spent
    return {
        "ytm": round(ytm, 4),
        "ytm_after_tax": None if ytm_tax is None else round(ytm_tax, 4),
        "duration_years": round(duration, 3),
        "meets_target": ytm + 1e-9 >= TARGET_YTM_PRETAX,
        "target": TARGET_YTM_PRETAX,
        "weight_base": "сумма позиций с НКД, без комиссии",
    }


def _limits(package: list[dict], positions: list[dict], portfolio_value: float | None, asof: date) -> dict:
    account = "обычный"
    threshold = "порог 15 млн ₽ не проверен: нет свежей оценки портфеля, по умолчанию обычный счёт"
    if portfolio_value is not None:
        if portfolio_value >= 15_000_000 and asof.year <= 2026:
            threshold = (
                f"оценка {portfolio_value:,.0f} ₽ не ниже 15 млн, но до конца 2026 регулярные покупки "
                "остаются на обычном счёте. На ИИС-3 этот взнос не отправляем."
            )
        elif portfolio_value >= 15_000_000:
            account = "ИИС-3"
            threshold = "порог 15 млн ₽ достигнут, поток на ИИС-3 того же брокера"
        else:
            threshold = f"оценка {portfolio_value:,.0f} ₽ ниже 15 млн, обычный счёт"
    issuer_notes = []
    if portfolio_value is None:
        issuer_notes.append("лимит 5% на эмитента не проверен: нет текущей стоимости объединённого портфеля")
    else:
        base = portfolio_value
        incoming = sum(item["position_sum"] for item in package)
        for item in package:
            if item["bucket"] == "ofz":
                issuer_notes.append(f"{item['shortname']}: лимит 5% на Минфин не применяется")
                continue
            already = sum(float(row.get("value") or 0) for row in positions if fold(row.get("issuer")) == fold(item["issuer"]))
            share = (already + item["position_sum"]) / (base + incoming) if base + incoming else 1
            issuer_notes.append(
                f"{item['issuer']}: {share:.1%} объединённого портфеля после покупки при переданных позициях"
                + (" — выше 5%, в живой пакет такую бумагу лучше не подтверждать" if share > ISSUER_LIMIT else " — в пределах 5%")
            )
    return {
        "account": account,
        "threshold": threshold,
        "issuer_limit": ISSUER_LIMIT,
        "issuer_notes": issuer_notes,
        "portfolio_value": portfolio_value,
        "positions_received": len(positions),
    }


def _market_curve(duration_points: list[tuple[float, float]], maturity_points: list[tuple[float, float]]) -> dict:
    tenors = {}
    for tenor in (2, 5, 10, 15):
        if len(maturity_points) < 2:
            tenors[str(tenor)] = None
            continue
        value, clamped = _curve(maturity_points, tenor)
        tenors[str(tenor)] = {"ytm": round(value, 3), "clamped": clamped, "axis": "срок до погашения, лет"}
    return {
        "g_spread_axis": "дюрация, лет",
        "g_spread_points": len(duration_points),
        "tenor_ytm": tenors,
    }


def _variants(broker, package, eligible, exceptions, securities_cap, remainder_pct, rate) -> list[dict]:
    notes = []
    filled = {item["slot_id"] for item in package}
    for slot in broker["slots"]:
        if slot["id"] in filled or slot["bucket"] == "ofz" and any(item["slot_id"] == "ofz" for item in package):
            continue
        notes.append({
            "title": f"Слот «{slot['title']}» не заполнен",
            "detail": "Фильтр не ослаблялся. Деньги слота остаются в остатке, а не переносятся в другой класс.",
        })
    if remainder_pct > UNSPENT_ALERT:
        notes.append({
            "title": "Остаток больше 10% взноса",
            "detail": "Норма распределения не сдвигалась. Ниже вариант, который нужно согласовать отдельно.",
        })
        used = {item["isin"] for item in package}
        nxt = next((item for item in eligible["ofz"] if item["isin"] not in used), None)
        if nxt and broker["id"] == "alfa":
            notes.append({
                "title": "Вариант на согласование: третья ОФЗ вместо пустого корпоративного слота",
                "detail": (
                    f"{nxt['shortname']} ({nxt['secid']}), дюрация {nxt['duration_years']} лет, "
                    f"YTM {nxt['ytm']}%. Это меняет норму 65/35 и в пакет само не входит."
                ),
            })
    if exceptions:
        head = exceptions[0]
        notes.append({
            "title": "Кандидаты на согласованное исключение по сроку AAA/AA",
            "detail": (
                f"Ближайший по сортировке: {head['shortname']} ({head['isin']}), "
                f"рейтинг {head.get('rating')}, срок {head.get('years')} лет, "
                f"YTM {head.get('ytm')}, G-спред {head.get('g_spread_bp')} б.п., "
                f"балл {(head.get('score') or {}).get('total')}. "
                "Короткий AAA/AA не покупается автоматически. ФосАгро и прочие короткие AAA/AA сравниваются в одном списке."
            ),
        })
    if len(package) < 3:
        notes.append({
            "title": f"В пакете {len(package)} из 3 позиций",
            "detail": "Две позиции допустимы, когда третьей подходящей нет. Одной позиции правила не просят.",
        })
    return notes


def _public_candidate(item: dict) -> dict:
    score = item.get("score") or {}
    return {
        "secid": item.get("secid"),
        "isin": item.get("isin"),
        "shortname": item.get("shortname"),
        "issuer": item.get("issuer"),
        "rating": item.get("rating"),
        "rating_agency": item.get("rating_agency"),
        "rating_date": item.get("rating_date"),
        "rating_outlook": item.get("rating_outlook"),
        "rating_source": item.get("rating_source"),
        "sector": item.get("sector"),
        "years": item.get("years"),
        "maturity": item.get("maturity"),
        "ytm": item.get("ytm"),
        "duration_years": item.get("duration_years"),
        "g_spread_bp": item.get("g_spread_bp"),
        "moex_g_spread_bp": item.get("moex_g_spread_bp"),
        "score": score.get("total"),
        "score_parts": score.get("parts"),
        "coupon_percent": item.get("coupon_percent"),
        "coupon_label": item.get("coupon_label"),
        "avg_turnover": None if item.get("avg_turnover") is None else round(item["avg_turnover"], 2),
        "median_turnover": None if item.get("median_turnover") is None else round(item["median_turnover"], 2),
        "dohod_median_turnover": item.get("dohod_median_turnover"),
        "screener_rating": item.get("screener_rating"),
        "screener_quality": item.get("screener_quality"),
        "price": item.get("price"),
        "flags": item.get("flags") or [],
        "notes": item.get("notes") or [],
        "reason": item.get("reason"),
        "status": item.get("status"),
        "moex_url": f"https://www.moex.com/ru/issue.aspx?board={item.get('board')}&code={item.get('secid')}",
        "card_url": None if not item.get("isin") or item.get("bucket") == "ofz" else f"https://corpbonds.ru/bond/{item.get('isin')}",
    }
