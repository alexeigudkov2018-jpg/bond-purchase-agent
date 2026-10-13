"""Сверка выгрузки ДОХОДЪ с Московской биржей и пакет на сегодняшних цифрах.

Источник котировок, НКД, доходности, дюрации, оборота и графика — ISS.
Буквы рейтинга и баллы качества по-прежнему из выгрузки: на бирже их нет.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from engine.cashflows import after_tax_ytm, coupon_calendar, naive_haircut, parse_iso, pretax_ytm_from_schedule
from engine.corpbonds import rating_group
from engine.dohod import group_from_text
from engine.moex import (
    ISS,
    bondization,
    description,
    duration_days,
    effective_yield,
    fetch_json,
    is_fixed_coupon,
    is_rub,
    last_trading_sessions,
    listed_offer,
    load_universe,
    map_turnover,
    moex_g_spread,
    quote,
    turnover_on_calendar,
    years_to,
)
from engine.preview import (
    ANALYSIS_DATE,
    CORP_BOOK,
    OFZ_BOOK,
    PRIOR_PATH,
    TUESDAY,
    _coupon_label,
    _flags,
    _load_prior,
    _normalize,
    _period_days,
    _related,
    _rows,
)
from engine.rules import (
    CONTRIBUTION_RUB,
    CURVE_TURNOVER_RUB,
    MIN_POSITION_RUB,
    MIN_TURNOVER_RUB,
    SCORE_THRESHOLD,
    TARGET_YTM_PRETAX,
    TAX_RATE,
    UNSPENT_ALERT,
    broker_for_month,
)
from engine.scoring import score_corporate
from engine.select import _curve, _money, _position_dirty, _size, ban_reason, fold

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "moex_package.json"


def _issuer_priors(path: Path) -> dict[str, dict]:
    by_isin = _load_prior(path)
    by_name: dict[str, dict] = {}
    if not path.exists():
        return by_name
    payload = json.loads(path.read_text(encoding="utf-8"))

    def walk(node) -> None:
        if isinstance(node, dict):
            agency = node.get("rating_agency")
            issuer = node.get("issuer")
            if agency and agency != "скринер ДОХОДЪ" and issuer and node.get("rating"):
                key = fold(issuer)
                current = by_name.get(key)
                rank = {"aa": 2, "a": 1, "below": 0, None: -1}
                group = rating_group(node.get("rating"))
                if current is None or rank.get(group, -1) < rank.get(current.get("group"), -1):
                    by_name[key] = {
                        "rating": node.get("rating"),
                        "agency": agency,
                        "date": node.get("rating_date"),
                        "outlook": node.get("rating_outlook"),
                        "source": node.get("rating_source"),
                        "group": group,
                        "via": "карточка эмитента от 6 октября",
                    }
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    by_name["_by_isin"] = by_isin
    return by_name


def _lookup_missing(isin: str) -> dict | None:
    url = f"{ISS}/securities.json?q={isin}&iss.meta=off&limit=30"
    payload = fetch_json(url, timeout=40)
    rows = payload.get("securities", {}).get("data") or []
    columns = payload.get("securities", {}).get("columns") or []
    for raw in rows:
        row = dict(zip(columns, raw))
        if (row.get("isin") or row.get("ISIN") or "").upper() != isin:
            continue
        secid = row.get("secid") or row.get("SECID")
        if not secid:
            continue
        info = description(secid)
        board = (info.get("PRIMARY_BOARDID") or "TQCB").upper()
        if board not in {"TQOB", "TQCB", "TQOD", "TQIR", "TQOE"}:
            board = "TQCB"
        quote_url = (
            f"{ISS}/engines/stock/markets/bonds/boards/{board}/securities/{secid}.json"
            f"?iss.meta=off&iss.only=securities,marketdata,marketdata_yields"
        )
        card = fetch_json(quote_url, timeout=40)
        if not card.get("securities", {}).get("data"):
            continue
        sec_cols = card["securities"]["columns"]
        security = dict(zip(sec_cols, card["securities"]["data"][0]))
        market = {}
        if card.get("marketdata", {}).get("data"):
            market = dict(zip(card["marketdata"]["columns"], card["marketdata"]["data"][0]))
        yields = {}
        if card.get("marketdata_yields", {}).get("data"):
            yields = dict(zip(card["marketdata_yields"]["columns"], card["marketdata_yields"]["data"][0]))
        security["board"] = board
        security["market"] = market
        security["yields"] = yields
        return security
    return None


def _schedule(secid: str) -> dict:
    try:
        data = bondization(secid)
        info = description(secid)
    except Exception as error:
        return {"ok": False, "reason": f"график выпуска не загрузился: {error}", "coupons": [], "note": "", "initial_face": None}
    maturity = parse_iso(info.get("MATDATE"))
    amort = data["amortizations"]
    extra = []
    for row in amort:
        if row.get("data_source") == "maturity":
            continue
        amort_date = parse_iso(row.get("amortdate"))
        if amort_date and maturity and amort_date < maturity:
            extra.append(row)
    initial = _float(info.get("INITIALFACEVALUE"))
    current = _float(info.get("FACEVALUE"))
    coupons = []
    future_rates = set()
    for row in data["coupons"]:
        day = parse_iso(row.get("coupondate"))
        amount = row.get("value_rub")
        if amount is None:
            amount = row.get("value")
        if day is None or amount is None:
            continue
        coupons.append({"date": day.isoformat(), "amount": float(amount)})
        if day > date.today() and row.get("valueprc") is not None and (maturity is None or day <= maturity):
            future_rates.add(round(float(row["valueprc"]), 4))
    if len(amort) > 1 or extra:
        return {"ok": False, "reason": "в графике MOEX есть амортизация", "coupons": coupons, "note": "", "initial_face": initial}
    if data["offers"]:
        return {"ok": False, "reason": "в условиях выпуска на бирже есть оферта", "coupons": coupons, "note": "", "initial_face": initial}
    if initial and current and current < initial * 0.999:
        return {"ok": False, "reason": "текущий номинал ниже начального", "coupons": coupons, "note": "", "initial_face": initial}
    if len(future_rates) > 1:
        return {"ok": False, "reason": "будущие купоны в графике не постоянны", "coupons": coupons, "note": "", "initial_face": initial}
    note = "график MOEX проверен: амортизации и оферты нет"
    if initial and current and abs(initial - current) < 0.01:
        note = "график MOEX проверен: номинал равен начальному, амортизации и оферты нет"
    return {"ok": True, "reason": "", "coupons": coupons, "note": note, "initial_face": initial}


def _float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _moex_view(bond: dict, asof: date) -> dict:
    quoted = quote(bond)
    face = float(bond.get("FACEVALUE") or 0)
    price = quoted["price"]
    nkd = float(bond.get("ACCRUEDINT") or 0)
    ytm = effective_yield(bond)
    duration = duration_days(bond)
    years = years_to(bond, asof)
    per_year = None
    period = bond.get("COUPONPERIOD")
    if period:
        days = int(period)
        if days <= 35:
            per_year = 12
        elif 80 <= days <= 100:
            per_year = 4
        elif 160 <= days <= 200:
            per_year = 2
        elif days >= 300:
            per_year = 1
    coupon_pct = None if bond.get("COUPONPERCENT") is None else float(bond["COUPONPERCENT"])
    annual = None
    if coupon_pct is not None and face:
        annual = face * coupon_pct / 100
    clean = None if price is None else face * price / 100
    current = None
    if annual and clean:
        current = annual / clean * 100
    offer = listed_offer(bond)
    return {
        "secid": bond.get("SECID"),
        "board": bond.get("board"),
        "shortname": bond.get("SHORTNAME"),
        "secname": bond.get("SECNAME"),
        "face": face,
        "lot": int(bond.get("LOTSIZE") or 1),
        "price": None if price is None else round(price, 4),
        "price_source": quoted["source"],
        "price_asof": quoted["asof"],
        "price_stale": quoted["stale"],
        "nkd": round(nkd, 4),
        "ytm": None if ytm is None else round(ytm, 4),
        "yield_date": (bond.get("yields") or {}).get("YIELDDATE"),
        "duration_days": duration,
        "duration": None if duration is None else round(duration / 365.0, 3),
        "years": None if years is None else round(years, 2),
        "maturity": bond.get("MATDATE"),
        "coupon_percent": coupon_pct,
        "coupon_period": period,
        "coupon_label": _coupon_label(per_year),
        "per_year": per_year,
        "annual_coupon": None if annual is None else round(annual, 2),
        "current_yield": None if current is None else round(current, 2),
        "fixed": is_fixed_coupon(bond),
        "rub": is_rub(bond),
        "offer": None if offer is None else offer.isoformat(),
        "subtype": bond.get("BONDSUBTYPE"),
        "bond_type": bond.get("BONDTYPE"),
        "g_spread_moex": moex_g_spread(bond),
        "turnover": bond.get("turnover") or {},
        "moex_url": f"https://www.moex.com/ru/issue.aspx?board={bond.get('board')}&code={bond.get('SECID')}",
    }


def _delta(excel: dict, moex: dict | None) -> dict:
    if moex is None:
        return {}

    def diff(left, right):
        if left is None or right is None:
            return None
        return round(right - left, 4)

    return {
        "price_pp": diff(excel.get("price"), moex.get("price")),
        "ytm_pp": diff(excel.get("ytm"), moex.get("ytm")),
        "nkd": diff(excel.get("nkd"), moex.get("nkd")),
        "duration_years": diff(excel.get("duration"), moex.get("duration")),
        "years": diff(excel.get("years"), moex.get("years")),
    }


def _curve_from(ofz: list[dict]) -> list[tuple[float, float]]:
    points = []
    for item in ofz:
        view = item["moex"]
        turnover = (view.get("turnover") or {}).get("mean")
        if turnover is None or turnover < CURVE_TURNOVER_RUB:
            continue
        if not view.get("fixed") or not view.get("rub"):
            continue
        if view.get("duration") is None or view.get("ytm") is None:
            continue
        points.append((view["duration"], view["ytm"]))
    return points


def _score_row(excel: dict, moex: dict, curve: list[tuple[float, float]], confirmed: bool) -> dict:
    spread, clamped, curve_ytm = None, False, None
    if curve and moex.get("duration") is not None and moex.get("ytm") is not None:
        curve_ytm, clamped = _curve(curve, moex["duration"])
        spread = (moex["ytm"] - curve_ytm) * 100
    scored = score_corporate(
        g_spread_bp=spread,
        net_debt_ebitda=None,
        ebitda_interest=None,
        credit_quality=excel.get("credit_quality"),
        issuer_quality=excel.get("issuer_quality"),
        coupon_period_days=moex.get("coupon_period") or _period_days(excel.get("per_year")),
        rating_confirmed=confirmed,
    )
    return {
        "g_spread_bp": None if spread is None else round(spread, 1),
        "curve_ytm": None if curve_ytm is None else round(curve_ytm, 4),
        "clamped": clamped,
        "moex_g_spread_bp": moex.get("g_spread_moex"),
        "score": scored,
    }


def _known_rating(excel: dict, priors: dict) -> dict | None:
    by_isin = priors.get("_by_isin") or {}
    if excel["isin"] in by_isin:
        known = dict(by_isin[excel["isin"]])
        known["via"] = "карточка этого выпуска от 6 октября"
        return known
    for name in (excel.get("issuer"), excel.get("borrower")):
        found = priors.get(fold(name or ""))
        if found:
            return found
    return None


def _allocate(picks: list[dict], cap: float, budget: float, rate: float, asof: date) -> list[dict]:
    cash_left = budget
    package = []
    for pick in picks:
        moex = pick["moex"]
        dirty = _position_dirty(moex["face"], moex["price"], moex["nkd"])
        sized = _size(dirty, moex["lot"], cap * pick["slot_share"], cash_left, rate)
        if sized is None:
            continue
        clean = moex["face"] * moex["price"] / 100
        maturity = parse_iso(moex.get("maturity"))
        schedule = pick.get("coupon_schedule") or []
        tax = after_tax_ytm(
            asof=asof,
            clean_price=clean,
            nkd=moex["nkd"],
            face=moex["face"],
            coupons=schedule,
            tax_rate=TAX_RATE,
            maturity=maturity,
        )
        own = pretax_ytm_from_schedule(
            asof=asof,
            dirty_price=dirty,
            face=moex["face"],
            coupons=schedule,
            maturity=maturity,
        )
        mean = (moex.get("turnover") or {}).get("mean")
        median = (moex.get("turnover") or {}).get("median")
        package.append({
            "isin": pick["isin"],
            "secid": moex["secid"],
            "shortname": moex["shortname"] or pick["excel"]["shortname"],
            "issuer": pick["excel"]["issuer"],
            "slot_id": pick["slot_id"],
            "slot_title": pick["slot_title"],
            "verdict": "брать по сверке с биржей",
            "qty": sized["qty"],
            "lot": moex["lot"],
            "face": moex["face"],
            "price": moex["price"],
            "price_source": moex["price_source"],
            "price_asof": moex["price_asof"],
            "nkd": _money(moex["nkd"]),
            "dirty": _money(dirty),
            "position_sum": sized["position_sum"],
            "commission": sized["commission"],
            "debit": sized["debit"],
            "ytm": moex["ytm"],
            "ytm_cashflow": None if own is None else round(own, 4),
            "ytm_after_tax": tax["ytm"],
            "ytm_after_tax_method": tax["method"],
            "naive_ytm_after_13": naive_haircut(moex["ytm"], TAX_RATE),
            "duration": moex["duration"],
            "years": moex["years"],
            "maturity": moex["maturity"],
            "coupon_percent": moex["coupon_percent"],
            "coupon_label": moex["coupon_label"],
            "current_yield": moex["current_yield"],
            "annual_coupon": moex["annual_coupon"],
            "annual_coupon_position": None if moex["annual_coupon"] is None else _money(moex["annual_coupon"] * sized["qty"]),
            "mean_turnover": None if mean is None else round(mean, 2),
            "median_turnover": None if median is None else round(median, 2),
            "excel_median_mln": pick["excel"].get("median_mln"),
            "excel_price": pick["excel"].get("price"),
            "excel_ytm": pick["excel"].get("ytm"),
            "excel_duration": pick["excel"].get("duration"),
            "bondization_note": pick.get("bondization_note"),
            "moex_url": moex["moex_url"],
            "coupon_schedule": schedule,
            "bucket": "ofz" if pick["slot_id"] == "ofz" else "corporate",
        })
        cash_left -= sized["debit"]
    return package


def _weights(package: list[dict]) -> dict:
    spent = sum(item["position_sum"] for item in package)
    if spent <= 0:
        return {"ytm": None, "ytm_after_tax": None, "duration_years": None, "meets_target": False}
    ytm = sum((item["ytm"] or 0) * item["position_sum"] for item in package) / spent
    tax_rows = [item for item in package if item["ytm_after_tax"] is not None]
    tax_base = sum(item["position_sum"] for item in tax_rows)
    tax = None if tax_base <= 0 else sum(item["ytm_after_tax"] * item["position_sum"] for item in tax_rows) / tax_base
    duration = sum((item["duration"] or 0) * item["position_sum"] for item in package) / spent
    return {
        "ytm": round(ytm, 4),
        "ytm_after_tax": None if tax is None else round(tax, 4),
        "duration_years": round(duration, 3),
        "meets_target": ytm + 1e-9 >= TARGET_YTM_PRETAX,
        "target": TARGET_YTM_PRETAX,
        "weight_base": "сумма позиций с НКД, без комиссии",
        "naive_ytm_after_13": round(sum((item["naive_ytm_after_13"] or 0) * item["position_sum"] for item in package) / spent, 4),
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


def build_verified(budget: float = CONTRIBUTION_RUB) -> dict:
    asof = date.today()
    broker = broker_for_month(TUESDAY.month if asof.month == TUESDAY.month else asof.month)
    rate = broker["commission_rate"]
    cap = min(budget * (1 - 0.003), budget / (1 + rate))
    sessions = last_trading_sessions()
    universe = load_universe()
    by_isin: dict[str, dict] = {}
    for rows in universe.values():
        for bond in rows:
            isin = (bond.get("ISIN") or "").upper()
            if isin:
                by_isin[isin] = bond

    excel_ofz = [_normalize(row, OFZ_BOOK.name) for row in _rows(OFZ_BOOK)]
    excel_corp = [_normalize(row, CORP_BOOK.name) for row in _rows(CORP_BOOK)]
    excel = excel_ofz + excel_corp
    missing = []
    for item in excel:
        if item["isin"] not in by_isin:
            found = _lookup_missing(item["isin"])
            if found:
                by_isin[item["isin"]] = found
            else:
                missing.append(item["isin"])

    wanted = [by_isin[item["isin"]] for item in excel if item["isin"] in by_isin]
    ofz_board = [
        bond for bond in universe["TQOB"]
        if is_rub(bond) and is_fixed_coupon(bond) and (bond.get("FACEVALUE") or 0)
    ]
    pool = {bond["SECID"]: bond for bond in wanted}
    for bond in ofz_board:
        pool.setdefault(bond["SECID"], bond)
    map_turnover(list(pool.values()), sessions)
    for bond in pool.values():
        stats = bond.get("turnover") or {}
        if stats.get("mean") is None:
            bond["turnover"] = turnover_on_calendar(bond["SECID"], bond["board"], sessions)

    priors = _issuer_priors(PRIOR_PATH)
    ofz_curve_source = []
    for bond in ofz_board:
        view = _moex_view(bond, asof)
        ofz_curve_source.append({"moex": view, "isin": (bond.get("ISIN") or "").upper(), "excel_name": bond.get("SHORTNAME")})
    curve = _curve_from(ofz_curve_source)

    def attach(item: dict) -> dict:
        bond = by_isin.get(item["isin"])
        moex = None if bond is None else _moex_view(bond, asof)
        return {"excel": item, "moex": moex, "isin": item["isin"], "delta": _delta(item, moex), "bond": bond}

    ofz_rows = [attach(item) for item in excel_ofz]
    corp_rows = [attach(item) for item in excel_corp]

    eligible_ofz = []
    ofz_public = []
    for row in ofz_rows:
        excel, moex = row["excel"], row["moex"]
        reason = None if moex else "выпуска нет на TQOB, TQCB и в поиске ISS"
        if reason is None and not moex["rub"]:
            reason = "биржа: номинал не в рублях"
        if reason is None and not moex["fixed"]:
            reason = "биржа: купон не фиксированный"
        if reason is None and moex["offer"]:
            reason = f"биржа: есть дата оферты {moex['offer']}"
        mean = None if moex is None else (moex["turnover"] or {}).get("mean")
        if reason is None and mean is None:
            reason = "биржа не отдала оборот"
        if reason is None and mean < MIN_TURNOVER_RUB:
            reason = "средний оборот за 10 сессий ниже 5 млн ₽"
        if reason is None and (moex["years"] or 0) < 8:
            reason = "ОФЗ короче 8 лет до погашения"
        if reason is None and (moex["ytm"] is None or moex["duration"] is None or moex["price"] is None):
            reason = "биржа не отдала цену, доходность или дюрацию"
        status = "reject" if reason else "eligible"
        ofz_public.append({
            "isin": excel["isin"],
            "shortname": (moex or {}).get("shortname") or excel["shortname"],
            "status": status,
            "reason": reason or "длинная фиксированная ОФЗ, приоритет по дюрации биржи",
            "excel_duration": excel["duration"],
            "duration": None if moex is None else moex["duration"],
            "years": None if moex is None else moex["years"],
            "ytm": None if moex is None else moex["ytm"],
            "mean_turnover": mean,
            "excel_median_mln": excel["median_mln"],
            "delta": row["delta"],
        })
        if status == "eligible":
            eligible_ofz.append(row)
    eligible_ofz.sort(key=lambda row: (-(row["moex"]["duration"] or 0), -(row["moex"]["years"] or 0), -(row["moex"]["ytm"] or 0)))

    longer_outside = []
    file_isins = {item["isin"] for item in excel_ofz}
    for item in ofz_curve_source:
        view = item["moex"]
        mean = (view["turnover"] or {}).get("mean")
        if item["isin"] in file_isins:
            continue
        if mean is None or mean < MIN_TURNOVER_RUB:
            continue
        if (view["years"] or 0) < 8 or view["duration"] is None:
            continue
        if eligible_ofz and view["duration"] > (eligible_ofz[0]["moex"]["duration"] or 0) + 0.05:
            longer_outside.append({
                "isin": item["isin"],
                "shortname": view["shortname"],
                "duration": view["duration"],
                "years": view["years"],
                "ytm": view["ytm"],
                "mean_turnover": round(mean, 2),
            })
    longer_outside.sort(key=lambda item: -item["duration"])

    counts: Counter[str] = Counter()
    exceptions, waitlist, review, rejected = [], [], [], []
    classified = []
    for row in corp_rows:
        excel, moex = row["excel"], row["moex"]
        if moex is None:
            counts["нет на бирже"] += 1
            rejected.append({"isin": excel["isin"], "shortname": excel["shortname"], "status": "reject", "reason": "выпуска нет в ISS", "excel": _brief(excel)})
            continue
        reason = None
        ban = ban_reason(excel["issuer"], None) or ban_reason(excel["borrower"], None)
        if excel["currency"] not in {"RUB", "SUR"}:
            reason = "номинал не в рублях"
        elif excel["subordinated"]:
            reason = "субординированный выпуск: рейтинг эмитента на выпуск не переносим"
        elif excel["issuer_type"] not in {"корпоративные", "государственные"}:
            reason = f"тип эмитента: {excel['issuer_type'] or 'не указан'}"
        elif ban:
            reason = ban
        elif excel["event"] != "погашение":
            reason = f"событие в дату: «{excel['event'] or 'пусто'}», допускается только «погашение»"
        if not moex["rub"]:
            reason = "биржа: номинал не в рублях"
        elif not moex["fixed"]:
            reason = "биржа: купон не фиксированный"
        elif moex["offer"]:
            reason = f"биржа: есть дата оферты {moex['offer']}"
        mean = (moex["turnover"] or {}).get("mean")
        if reason is None and mean is None:
            reason = "биржа не отдала оборот"
        if reason is None and mean < MIN_TURNOVER_RUB:
            reason = "средний оборот за 10 сессий ниже 5 млн ₽"
        related = _related(excel["issuer"], excel["borrower"], excel["shortname"])
        if reason:
            counts[reason] += 1
            rejected.append({
                "isin": excel["isin"],
                "shortname": moex["shortname"] or excel["shortname"],
                "status": "reject",
                "reason": reason,
                "mean_turnover": mean,
                "excel_median_mln": excel["median_mln"],
                "ytm": moex["ytm"],
                "years": moex["years"],
                "price": moex["price"],
            })
            continue
        known = _known_rating(excel, priors)
        agency_group = rating_group(known["rating"]) if known and known.get("rating") else None
        screener_group = group_from_text(excel["screener_rating"])
        group = agency_group or screener_group
        notes = []
        if known and agency_group and screener_group and agency_group != screener_group:
            notes.append(f"скринер показывает {excel['screener_rating']}, {known['via']} — {known['rating']}. Окно срока по агентству.")
        elif known:
            notes.append(f"{known['via']}: {known.get('rating')}. Дату 13 октября заново не открывали, балл свежести не начислен.")
        else:
            notes.append("буква только из выгрузки ДОХОДЪ. Карточки агентства на этот выпуск нет.")
        if excel["guaranteed"]:
            notes.append("в выгрузке стоит гарантия.")
        scored = _score_row(excel, moex, curve, confirmed=False)
        outlook = known.get("outlook") if known else None
        flags = _flags(group, scored["g_spread_bp"], moex["price"], outlook)
        if related:
            flags.append(related)
        common = {
            "isin": excel["isin"],
            "shortname": moex["shortname"] or excel["shortname"],
            "issuer": excel["issuer"],
            "group": group,
            "rating": (known or {}).get("rating") or excel["screener_rating"],
            "rating_agency": (known or {}).get("agency") or "скринер ДОХОДЪ",
            "screener_rating": excel["screener_rating"],
            "years": moex["years"],
            "duration": moex["duration"],
            "ytm": moex["ytm"],
            "price": moex["price"],
            "mean_turnover": None if mean is None else round(mean, 2),
            "median_turnover": None if (moex["turnover"] or {}).get("median") is None else round(moex["turnover"]["median"], 2),
            "excel_median_mln": excel["median_mln"],
            "g_spread_bp": scored["g_spread_bp"],
            "g_spread_clamped": scored["clamped"],
            "moex_g_spread_bp": scored["moex_g_spread_bp"],
            "score": scored["score"]["total"],
            "score_passed": scored["score"]["passed"],
            "score_parts": scored["score"]["parts"],
            "flags": flags,
            "notes": notes,
            "moex_url": moex["moex_url"],
        }
        row["common"] = common
        row["group"] = group
        row["flags"] = flags
        row["related"] = related
        row["scored"] = scored
        if group in (None, "below"):
            reason = f"рейтинг {excel['screener_rating'] or 'не указан'} ниже A− или не прочитан"
            counts[reason] += 1
            rejected.append({**common, "status": "reject", "reason": reason})
            continue
        years = moex["years"] or 0
        in_window = (group == "aa" and 4 <= years <= 7) or (group == "a" and 2 <= years <= 5)
        short_aa = group == "aa" and years < 4
        if short_aa:
            exceptions.append({**common, "status": "exception", "reason": "AAA/AA короче 4 лет: только отдельное согласие"})
            continue
        if not in_window:
            counts["срок вне окна рейтинга"] += 1
            rejected.append({**common, "status": "reject", "reason": "срок до погашения вне окна рейтинга"})
            continue
        if not scored["score"]["passed"]:
            extra = ""
            if known and known.get("date"):
                extra = f" С баллом за карточку {known['date']} было бы {round(scored['score']['total'] + 1, 2)}."
            waitlist.append({**common, "status": "wait", "reason": f"балл {scored['score']['total']} ниже порога {SCORE_THRESHOLD}.{extra}"})
            continue
        if related or flags:
            review.append({**common, "status": "flagged", "reason": related or "красный флаг, в автоматическую покупку не берём"})
            continue
        classified.append(row)

    exceptions.sort(key=lambda item: (-(item["score"] or 0), -(item["ytm"] or 0), item["shortname"]))
    waitlist.sort(key=lambda item: (-(item["score"] or 0), -(item["ytm"] or 0)))
    classified.sort(key=lambda row: (0 if row["common"]["rating_agency"] != "скринер ДОХОДЪ" else 1, len(row["flags"]), -row["common"]["score"], -(row["moex"]["ytm"] or 0)))

    ofz_share = next(slot["share"] for slot in broker["slots"] if slot["bucket"] == "ofz")
    ofz_count = 2 if len(eligible_ofz) >= 2 and cap * ofz_share / 2 >= MIN_POSITION_RUB else 1
    picks = []
    for bond in eligible_ofz[:ofz_count]:
        check = _schedule(bond["moex"]["secid"])
        if not check["ok"]:
            counts[check["reason"]] += 1
            continue
        picks.append({
            **bond,
            "slot_id": "ofz",
            "slot_title": "ОФЗ",
            "slot_share": ofz_share / max(ofz_count, 1),
            "coupon_schedule": check["coupons"],
            "bondization_note": check["note"],
        })
    corp_slot = next(slot for slot in broker["slots"] if slot["bucket"] == "corp")
    for row in classified:
        if any(item["isin"] == row["isin"] for item in picks):
            continue
        check = _schedule(row["moex"]["secid"])
        if not check["ok"]:
            counts[check["reason"]] += 1
            rejected.append({**row["common"], "status": "reject", "reason": check["reason"]})
            continue
        picks.append({
            **row,
            "slot_id": corp_slot["id"],
            "slot_title": corp_slot["title"],
            "slot_share": corp_slot["share"],
            "coupon_schedule": check["coupons"],
            "bondization_note": check["note"],
        })
        break

    package = _allocate(picks, cap, budget, rate, asof)
    weights = _weights(package)
    cash = _cash(package, budget)
    calendar = coupon_calendar(package, asof=asof)

    checks = []
    for row in ofz_rows + corp_rows:
        excel, moex = row["excel"], row["moex"]
        checks.append({
            "isin": excel["isin"],
            "file": "ОФЗ" if excel["issuer_type"] == "государственные" else "корпорат",
            "shortname": (moex or {}).get("shortname") or excel["shortname"],
            "found": moex is not None,
            "excel_price": excel["price"],
            "moex_price": None if moex is None else moex["price"],
            "excel_ytm": excel["ytm"],
            "moex_ytm": None if moex is None else moex["ytm"],
            "excel_nkd": excel["nkd"],
            "moex_nkd": None if moex is None else moex["nkd"],
            "excel_duration": excel["duration"],
            "moex_duration": None if moex is None else moex["duration"],
            "excel_years": excel["years"],
            "moex_years": None if moex is None else moex["years"],
            "mean_turnover": None if moex is None or (moex["turnover"] or {}).get("mean") is None else round(moex["turnover"]["mean"], 2),
            "median_turnover": None if moex is None or (moex["turnover"] or {}).get("median") is None else round(moex["turnover"]["median"], 2),
            "excel_median_mln": excel["median_mln"],
            "price_asof": None if moex is None else moex["price_asof"],
            "price_source": None if moex is None else moex["price_source"],
            "delta": row["delta"],
            "moex_url": None if moex is None else moex["moex_url"],
        })

    found = [row for row in checks if row["found"]]
    price_diffs = [abs(row["delta"]["price_pp"]) for row in found if row["delta"].get("price_pp") is not None]
    ytm_diffs = [abs(row["delta"]["ytm_pp"]) for row in found if row["delta"].get("ytm_pp") is not None]

    tenor = {}
    tenor_points = [(item["moex"]["years"], item["moex"]["ytm"]) for item in ofz_curve_source if item["moex"]["years"] and item["moex"]["ytm"] and ((item["moex"]["turnover"] or {}).get("mean") or 0) >= CURVE_TURNOVER_RUB]
    for tenor_year in (2, 5, 10, 15):
        if not tenor_points:
            continue
        ytm, clamped = _curve(tenor_points, float(tenor_year))
        tenor[str(tenor_year)] = {"ytm": round(ytm, 4), "clamped": clamped}

    slots = [
        {"id": slot["id"], "title": slot["title"], "share": slot["share"], "target": _money(cap * slot["share"])}
        for slot in broker["slots"]
    ]
    quote_times = sorted({row["price_asof"] for row in checks if row.get("price_asof")})
    return {
        "kind": "moex",
        "asof": asof.isoformat(),
        "tuesday": TUESDAY.isoformat() if asof <= TUESDAY else asof.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "file_asof": ANALYSIS_DATE.isoformat(),
        "sessions": sessions,
        "quote_times": quote_times[:8],
        "broker": {
            "id": broker["id"],
            "name": broker["name"],
            "agreement": broker["agreement"],
            "commission_rate": rate,
            "account": "обычный счёт Альфы. До конца 2026 поток на ИИС-3 не уходит. Порог 15 млн не проверен.",
        },
        "budget": {
            "contribution": budget,
            "total": budget,
            "securities_cap": _money(cap),
            "reserve_amount": _money(budget - cap),
            "slots": slots,
        },
        "cash": cash,
        "weights": weights,
        "package": package,
        "calendar": [row for row in calendar if row["total"] > 0],
        "checks": checks,
        "match": {
            "rows": len(checks),
            "found": len(found),
            "missing": missing,
            "max_abs_price_pp": None if not price_diffs else round(max(price_diffs), 4),
            "max_abs_ytm_pp": None if not ytm_diffs else round(max(ytm_diffs), 4),
            "median_abs_price_pp": None if not price_diffs else round(sorted(price_diffs)[len(price_diffs) // 2], 4),
            "median_abs_ytm_pp": None if not ytm_diffs else round(sorted(ytm_diffs)[len(ytm_diffs) // 2], 4),
        },
        "ofz": ofz_public,
        "exceptions": exceptions,
        "waitlist": waitlist,
        "review": review,
        "rejected": rejected,
        "rejected_counts": dict(counts.most_common()),
        "longer_ofz_outside_file": longer_outside[:5],
        "curve": {
            "points": len(curve),
            "method": "G-спред: numpy.interp YTM фиксированных ОФЗ по дюрации биржи. В кривой средний оборот за 10 сессий от 20 млн ₽, пропуск дня равен нулю.",
            "tenor_ytm": tenor,
        },
        "turnover": {
            "metric": "средний VALUE",
            "sessions": sessions,
            "session_count": len(sessions),
            "missing_day": "ноль",
        },
        "caveats": [
            "Цены, НКД, YTM, дюрация и оборот взяты с ISS Московской биржи. Буквы скринера и числа кредитного качества остались из выгрузки: биржа их не публикует.",
            "Балл за свежесть рейтинга равен нулю: сайты АКРА, Эксперт РА и НКР 13 октября не открывались.",
            "Средний оборот считается по 10 торговым дням якоря ОФЗ 26238. Медиана выгрузки показана рядом и порог не закрывает.",
            "Лимит 5% и порог 15 млн не проверены: состава портфеля нет.",
            "Это не инвестиционная рекомендация и не поручение брокеру.",
        ],
        "disclaimer": "Сверка с Московской биржей. Это не индивидуальная инвестиционная рекомендация.",
    }


def _brief(excel: dict) -> dict:
    return {"price": excel.get("price"), "ytm": excel.get("ytm"), "duration": excel.get("duration")}


def main() -> None:
    report = build_verified()
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    match = report["match"]
    cash = report["cash"]
    weights = report["weights"]
    print(f"найдено {match['found']} из {match['rows']}, нет на бирже: {match['missing']}")
    print(f"макс |цена| {match['max_abs_price_pp']} п.п., макс |YTM| {match['max_abs_ytm_pp']} п.п.")
    print(f"сессии {report['sessions']}")
    print(f"позиций {cash['positions']}, YTM {weights['ytm']}, после налога {weights['ytm_after_tax']}, остаток {cash['remainder']}")
    for item in report["package"]:
        print(f"  {item['shortname']} {item['qty']} шт {item['position_sum']} YTM {item['ytm']} после {item['ytm_after_tax']} оборот {item['mean_turnover']}")
    print(f"ожидание {len(report['waitlist'])}, исключения {len(report['exceptions'])}, отказ {len(report['rejected'])}")
    if report["longer_ofz_outside_file"]:
        print("длиннее файла:", report["longer_ofz_outside_file"][0])


if __name__ == "__main__":
    main()
