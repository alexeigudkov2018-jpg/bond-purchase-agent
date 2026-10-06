"""Баллы корпоратов. Жёсткие отсечки применяются раньше этих баллов.

Границы интервалов не перекрываются: нижняя граница следующего интервала
не попадает в предыдущий.
"""

from __future__ import annotations

from engine.rules import SCORE_THRESHOLD


def g_spread_points(spread_bp: float | None) -> tuple[float, str]:
    if spread_bp is None:
        return 0.0, "G-спред не посчитан, балл 0"
    if spread_bp < 80:
        return 0.0, "G-спред менее 80 б.п."
    if spread_bp < 130:
        return 1.0, "G-спред от 80 до менее 130 б.п."
    if spread_bp < 200:
        return 2.0, "G-спред от 130 до менее 200 б.п."
    if spread_bp <= 600:
        return 3.0, "G-спред от 200 до 600 б.п. включительно"
    return 0.0, "G-спред выше 600 б.п."


def leverage_points(net_debt_ebitda: float | None) -> tuple[float | None, str]:
    if net_debt_ebitda is None:
        return None, "чистый долг/EBITDA нет в источниках прогона"
    if net_debt_ebitda < 2:
        return 3.0, "чистый долг/EBITDA менее 2"
    if net_debt_ebitda < 3:
        return 2.0, "чистый долг/EBITDA от 2 до менее 3"
    if net_debt_ebitda <= 4:
        return 1.0, "чистый долг/EBITDA от 3 до 4 включительно"
    return 0.0, "чистый долг/EBITDA выше 4"


def coverage_points(ebitda_interest: float | None) -> tuple[float | None, str]:
    if ebitda_interest is None:
        return None, "EBITDA/проценты нет в источниках прогона"
    if ebitda_interest > 5:
        return 2.0, "EBITDA/проценты выше 5"
    if ebitda_interest >= 3:
        return 1.0, "EBITDA/проценты от 3 до 5 включительно"
    return 0.0, "EBITDA/проценты ниже 3"


def credit_quality_points(score: float | None) -> tuple[float | None, str]:
    """Замена чистого долга/EBITDA. NetDebt/Equity не используется."""
    if score is None:
        return None, "кредитное качество не передано"
    if score >= 7:
        return 3.0, "кредитное качество от 7 до 10 → 3 вместо долга/EBITDA"
    if score >= 5.5:
        return 2.0, "кредитное качество от 5,5 до менее 7 → 2"
    if score >= 4:
        return 1.0, "кредитное качество от 4 до менее 5,5 → 1"
    return 0.0, "кредитное качество ниже 4 → 0"


def issuer_quality_points(score: float | None) -> tuple[float | None, str]:
    """Замена покрытия процентов."""
    if score is None:
        return None, "качество эмитента не передано"
    if score >= 7:
        return 2.0, "качество эмитента от 7 → 2 вместо покрытия процентов"
    if score >= 5:
        return 1.0, "качество эмитента от 5 до менее 7 → 1"
    return 0.0, "качество эмитента ниже 5 → 0"


def coupon_points(period_days: int | None) -> tuple[float, str]:
    if period_days is None:
        return 0.0, "период купона неизвестен"
    if period_days <= 35:
        return 1.0, "ежемесячный купон"
    if 80 <= period_days <= 100:
        return 0.5, "квартальный купон"
    return 0.0, "купон реже квартала, балл за частоту 0"


def rating_fresh_points(confirmed: bool) -> tuple[float, str]:
    if confirmed:
        return 1.0, "рейтинг подтверждён или повышен за последние 12 месяцев"
    return 0.0, "балл за рейтинг не начислен: нет подтверждения агентства за 12 месяцев"


def score_corporate(
    *,
    g_spread_bp: float | None,
    net_debt_ebitda: float | None,
    ebitda_interest: float | None,
    credit_quality: float | None,
    issuer_quality: float | None,
    coupon_period_days: int | None,
    rating_confirmed: bool,
) -> dict:
    parts: list[dict] = []

    g_pts, g_note = g_spread_points(g_spread_bp)
    parts.append({"criterion": "G-спред", "points": g_pts, "note": g_note, "substituted": False})

    lev_pts, lev_note = leverage_points(net_debt_ebitda)
    if lev_pts is None:
        lev_pts, lev_note = credit_quality_points(credit_quality)
        substituted = lev_pts is not None
        if lev_pts is None:
            lev_pts = 0.0
            substituted = False
            lev_note = "нет ни долга/EBITDA, ни показателя «кредитное качество» — балл 0, замена обозначена как отсутствующая"
        parts.append({
            "criterion": "Долг / кредитное качество",
            "points": lev_pts,
            "note": lev_note,
            "substituted": substituted,
        })
    else:
        parts.append({
            "criterion": "Чистый долг/EBITDA",
            "points": lev_pts,
            "note": lev_note,
            "substituted": False,
        })

    cov_pts, cov_note = coverage_points(ebitda_interest)
    if cov_pts is None:
        cov_pts, cov_note = issuer_quality_points(issuer_quality)
        substituted = cov_pts is not None
        if cov_pts is None:
            cov_pts = 0.0
            substituted = False
            cov_note = "нет ни покрытия процентов, ни показателя «качество эмитента» — балл 0"
        parts.append({
            "criterion": "Покрытие / качество эмитента",
            "points": cov_pts,
            "note": cov_note,
            "substituted": substituted,
        })
    else:
        parts.append({
            "criterion": "EBITDA/проценты",
            "points": cov_pts,
            "note": cov_note,
            "substituted": False,
        })

    c_pts, c_note = coupon_points(coupon_period_days)
    parts.append({"criterion": "Частота купона", "points": c_pts, "note": c_note, "substituted": False})

    r_pts, r_note = rating_fresh_points(rating_confirmed)
    parts.append({"criterion": "Свежесть рейтинга", "points": r_pts, "note": r_note, "substituted": False})

    total = round(sum(p["points"] for p in parts), 2)
    return {
        "total": total,
        "threshold": SCORE_THRESHOLD,
        "passed": total >= SCORE_THRESHOLD,
        "parts": parts,
    }
