"""Денежные потоки, посленалоговая доходность и календарь купонов.

Посленалоговая YTM — это IRR потоков при НДФЛ 13% на купон и на дисконт
к номиналу. Это не YTM × (1 − 0,13).
"""

from __future__ import annotations

from datetime import date, datetime


def years_between(start: date, end: date) -> float:
    return (end - start).days / 365.0


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Годовая эффективная ставка, actual/365. None, если корень не найден."""
    if len(cashflows) < 2:
        return None
    start = cashflows[0][0]
    if cashflows[0][1] >= 0:
        return None

    def npv(rate: float) -> float:
        total = 0.0
        for day, amount in cashflows:
            t = years_between(start, day)
            total += amount / ((1 + rate) ** t)
        return total

    lo, hi = -0.5, 3.0
    n_lo, n_hi = npv(lo), npv(hi)
    if n_lo == 0:
        return lo
    if n_lo * n_hi > 0:
        # Расширяем поиск один раз: очень высокая доходность дистресса.
        hi = 8.0
        n_hi = npv(hi)
        if n_lo * n_hi > 0:
            return None
    for _ in range(80):
        mid = (lo + hi) / 2
        n_mid = npv(mid)
        if abs(n_mid) < 1e-8:
            return mid
        if n_lo * n_mid <= 0:
            hi, n_hi = mid, n_mid
        else:
            lo, n_lo = mid, n_mid
    return (lo + hi) / 2


def parse_iso(value: str | None) -> date | None:
    if not value or str(value).startswith("0000"):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def pretax_ytm_from_schedule(
    *,
    asof: date,
    dirty_price: float,
    face: float,
    coupons: list[dict],
    maturity: date | None = None,
) -> float | None:
    """Купоны: {date: ISO, amount: рубли на одну бумагу}. Номинал добавляется в дату погашения."""
    by_day: dict[date, float] = {}
    for coupon in coupons:
        day = parse_iso(coupon.get("date"))
        if day is None or day <= asof:
            continue
        by_day[day] = by_day.get(day, 0.0) + float(coupon["amount"])
    if maturity is not None and maturity > asof:
        by_day[maturity] = by_day.get(maturity, 0.0) + face
    elif by_day:
        last = max(by_day)
        by_day[last] = by_day.get(last, 0.0) + face
    else:
        return None
    rate = xirr([(asof, -dirty_price)] + sorted(by_day.items()))
    if rate is None:
        return None
    return rate * 100


def after_tax_ytm(
    *,
    asof: date,
    clean_price: float,
    nkd: float,
    face: float,
    coupons: list[dict],
    tax_rate: float,
    maturity: date | None = None,
) -> dict:
    """Купон режется на налог целиком. Дисконт к номиналу облагается на погашении.

    НКД, уплаченный при покупке, в этой модели не уменьшает налоговую базу
    следующего купона. Налоговый вычет с премии к номиналу не начисляется.
    """
    dirty = clean_price + nkd
    by_day: dict[date, float] = {}
    for coupon in coupons:
        day = parse_iso(coupon.get("date"))
        if day is None or day <= asof:
            continue
        net = float(coupon["amount"]) * (1 - tax_rate)
        by_day[day] = by_day.get(day, 0.0) + net
    if maturity is not None and maturity > asof:
        pay_day = maturity
    elif by_day:
        pay_day = max(by_day)
    else:
        return {"ytm": None, "method": "нет будущих купонов в графике, из НКД не восстанавливали"}
    discount = max(face - clean_price, 0.0)
    tax_on_discount = discount * tax_rate
    by_day[pay_day] = by_day.get(pay_day, 0.0) + face - tax_on_discount
    merged = [(asof, -dirty)] + sorted(by_day.items())
    rate = xirr(merged)
    return {
        "ytm": None if rate is None else round(rate * 100, 4),
        "tax_on_discount": round(tax_on_discount, 2),
        "method": (
            "IRR фактических дат купонов, НДФЛ 13% с каждого купона и с дисконта "
            "к номиналу на погашении; премия к номиналу налогом не компенсируется"
        ),
    }


def coupon_calendar(
    positions: list[dict],
    *,
    asof: date,
    months: int = 12,
) -> list[dict]:
    """Помесячный календарь только из графика выплат, не из НКД."""
    buckets: dict[str, dict] = {}
    cursor = date(asof.year, asof.month, 1)
    for _ in range(months):
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        buckets[key] = {"month": key, "ofz": 0.0, "corporate": 0.0, "total": 0.0}
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    end = cursor
    missing: list[str] = []
    for position in positions:
        schedule = position.get("coupon_schedule") or []
        if not schedule:
            missing.append(position["secid"])
            continue
        kind = "ofz" if position.get("bucket") == "ofz" else "corporate"
        qty = int(position["qty"])
        for coupon in schedule:
            day = parse_iso(coupon.get("date"))
            if day is None or day <= asof or day >= end:
                continue
            key = f"{day.year:04d}-{day.month:02d}"
            if key not in buckets:
                continue
            amount = float(coupon["amount"]) * qty
            buckets[key][kind] += amount
            buckets[key]["total"] += amount
    rows = []
    for row in buckets.values():
        rows.append({
            "month": row["month"],
            "ofz": round(row["ofz"], 2),
            "corporate": round(row["corporate"], 2),
            "total": round(row["total"], 2),
        })
    return rows


def naive_haircut(ytm: float | None, tax_rate: float) -> float | None:
    if ytm is None:
        return None
    return round(ytm * (1 - tax_rate), 4)
