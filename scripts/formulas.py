"""Формулы раздела 6. Чистые функции, без сети и без подстановки пропусков."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime

import numpy as np


SOLAR_V1_WEIGHTS = (1, 2, 3, 4, 5, 6, 24, 6, 5, 4, 3, 2, 1)
SOLAR_V1_DIVISOR = 64  # так записано в Томе 1; сумма весов равна 66
FLOW_BASE = 0.10
BANKS_NO_PS = frozenset({"SBER", "T", "VTBR", "BSPB", "MOEX", "RENI", "AFKS"})
WEEKDAY_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTH_PARTS = (("1-7", 1, 7), ("8-14", 8, 14), ("15-21", 15, 21), ("22-31", 22, 31))


def is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def monthly_return_pct(price_prev, price):
    if not is_num(price_prev) or not is_num(price) or price_prev == 0:
        return None
    return (price / price_prev - 1.0) * 100.0


def total_return_pct(price_prev, price, dividends):
    """5.5, в процентах, чтобы колонка называлась ret_tr_pct."""
    if not is_num(price_prev) or not is_num(price) or price_prev == 0:
        return None
    div = dividends if is_num(dividends) else 0.0
    return ((price + div) / price_prev - 1.0) * 100.0


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if is_num(x) and is_num(y)]
    n = len(pairs)
    if n < 3:
        return None, n
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    dy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    if dx == 0 or dy == 0:
        return None, n
    return num / (dx * dy), n


def sample_stdev(values):
    nums = [v for v in values if is_num(v)]
    if len(nums) < 2:
        return None
    return float(np.std(np.asarray(nums, dtype=float), ddof=1))


def beta_from_returns(asset, index):
    corr, n = pearson(asset, index)
    if corr is None:
        return None, n
    pairs = [(a, b) for a, b in zip(asset, index) if is_num(a) and is_num(b)]
    sa = sample_stdev([a for a, _ in pairs])
    sb = sample_stdev([b for _, b in pairs])
    if sa is None or sb in (None, 0):
        return None, n
    return corr * sa / sb, n


def parse_month(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def seasonality(monthly_returns):
    """monthly_returns: list of (YYYY-MM, ret_pct)."""
    by_month: dict[int, list[tuple[int, float]]] = {m: [] for m in range(1, 13)}
    years = set()
    for stamp, ret in monthly_returns:
        if not is_num(ret):
            continue
        year, month = parse_month(stamp)
        years.add(year)
        by_month[month].append((year, ret))
    averages = []
    hits = []
    ex2022 = []
    for month in range(1, 13):
        rows = by_month[month]
        if not rows:
            averages.append(None)
            hits.append(None)
            ex2022.append(None)
            continue
        averages.append(sum(r for _, r in rows) / len(rows))
        hits.append(sum(1 for _, r in rows if r > 0) / len(rows))
        kept = [r for year, r in rows if year != 2022]
        ex2022.append(sum(kept) / len(kept) if kept else None)
    n_years = len(years)
    return {
        "avg": averages,
        "hit": hits,
        "ex2022": ex2022,
        "n_years": n_years,
        "sample_lt_6": 1 if n_years < 6 else 0,
    }


def daily_returns(dates, closes):
    out = []
    for i in range(1, len(closes)):
        ret = monthly_return_pct(closes[i - 1], closes[i])
        if ret is None:
            continue
        stamp = dates[i]
        if isinstance(stamp, str):
            stamp = date.fromisoformat(stamp)
        out.append((stamp, ret))
    return out


def weekday_stats(dates, closes):
    rows = daily_returns(dates, closes)
    grouped: dict[int, list[float]] = {i: [] for i in range(7)}
    for stamp, ret in rows:
        grouped[stamp.weekday()].append(ret)
    result = []
    for idx, name in enumerate(WEEKDAY_RU):
        vals = grouped[idx]
        if not vals:
            continue
        result.append(
            {
                "weekday": name,
                "n_days": len(vals),
                "mean_pct": sum(vals) / len(vals),
                "median_pct": statistics.median(vals),
                "pct_up": 100.0 * sum(1 for v in vals if v > 0) / len(vals),
            }
        )
    return result


def month_part_stats(dates, closes):
    rows = daily_returns(dates, closes)
    months = {f"{stamp.year:04d}-{stamp.month:02d}" for stamp, _ in rows}
    n_months = len(months)
    result = []
    for label, start, end in MONTH_PARTS:
        vals = [ret for stamp, ret in rows if start <= stamp.day <= end]
        result.append(
            {
                "part": label,
                "n_days": len(vals),
                "mean_daily_pct": (sum(vals) / len(vals)) if vals else None,
                "pct_up": (100.0 * sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
                "contribution_pp": (sum(vals) / n_months) if vals and n_months else None,
                "n_obs": n_months,
            }
        )
    return result


def _episode(dates, prices, peak, trough, recovered, fall_confirmed, rise_confirmed):
    peak_px = prices[peak]
    trough_px = prices[trough]
    depth = (peak_px - trough_px) / peak_px * 100.0 if peak_px else None
    fall_days = trough - peak
    fall_speed = (abs(depth) / fall_days) if depth is not None and fall_days > 0 else None
    rec_days = None
    rebound = None
    rec_speed = None
    asym = None
    recovered_date = None
    if rise_confirmed and recovered is not None:
        rec_px = prices[recovered]
        rebound = (rec_px / trough_px - 1.0) * 100.0 if trough_px else None
        rec_days = recovered - trough
        rec_speed = (abs(rebound) / rec_days) if rebound is not None and rec_days > 0 else None
        asym = (rec_days / fall_days) if fall_days else None
        recovered_date = _as_iso(dates[recovered])
    return {
        "peak_date": _as_iso(dates[peak]),
        "trough_date": _as_iso(dates[trough]),
        "recovered_date": recovered_date,
        "peak_pts": peak_px,
        "trough_pts": trough_px,
        "depth_pct": depth,
        "rebound_pct": rebound,
        "fall_days": fall_days if fall_days > 0 else None,
        "rec_days": rec_days,
        "fall_speed": fall_speed,
        "rec_speed": rec_speed,
        "asym": asym,
        "completed": "да" if rise_confirmed else "нет",
        "fall_end": trough if fall_confirmed else None,
        "rise_end": recovered if rise_confirmed else None,
        "fall_complete": fall_confirmed and fall_speed is not None,
    }


def _as_iso(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def zigzag_episodes(dates, prices, threshold_pct=5.0):
    thr = threshold_pct / 100.0
    n = len(prices)
    if n == 0:
        return []
    pivots: list[tuple[int, str]] = []
    mode = None
    ext = 0
    for i in range(1, n):
        if prices[ext] == 0 or prices[0] == 0:
            continue
        if mode is None:
            change = prices[i] / prices[0] - 1.0
            if change <= -thr:
                pivots.append((0, "peak"))
                mode = "down"
                ext = i
            elif change >= thr:
                pivots.append((0, "trough"))
                mode = "up"
                ext = i
            continue
        if mode == "down":
            if prices[i] < prices[ext]:
                ext = i
            elif prices[ext] and prices[i] / prices[ext] - 1.0 >= thr:
                pivots.append((ext, "trough"))
                mode = "up"
                ext = i
        else:
            if prices[i] > prices[ext]:
                ext = i
            elif prices[ext] and (prices[ext] - prices[i]) / prices[ext] >= thr:
                pivots.append((ext, "peak"))
                mode = "down"
                ext = i
    episodes = []
    for pos, (idx, kind) in enumerate(pivots):
        if kind != "peak":
            continue
        trough = None
        recovered = None
        for later, later_kind in pivots[pos + 1 :]:
            if later_kind == "trough" and trough is None:
                trough = later
            elif later_kind == "peak" and trough is not None:
                recovered = later
                break
        if trough is not None:
            episodes.append(_episode(dates, prices, idx, trough, recovered, True, recovered is not None))
            continue
        if mode == "down" and prices[idx] and (prices[idx] - prices[ext]) / prices[idx] >= thr:
            episodes.append(_episode(dates, prices, idx, ext, None, False, False))
    return episodes


def rolling_rai(n_dates, episodes, window=126):
    values = [None] * n_dates
    for i in range(n_dates):
        if i + 1 < window:
            continue
        start = i - window + 1
        rises = [
            ep["rec_speed"]
            for ep in episodes
            if ep["completed"] == "да" and ep["rise_end"] is not None and start <= ep["rise_end"] <= i and is_num(ep["rec_speed"])
        ]
        falls = [
            ep["fall_speed"]
            for ep in episodes
            if ep["fall_complete"] and ep["fall_end"] is not None and start <= ep["fall_end"] <= i and is_num(ep["fall_speed"])
        ]
        if not rises or not falls:
            continue
        den = statistics.median(falls)
        if den == 0:
            continue
        values[i] = statistics.median(rises) / den
    return values


def global_drawdowns(dates, prices, threshold_pct=10.0):
    if not prices:
        return []
    episodes = []
    peak_i = 0
    trough_i = 0
    armed = False
    for i in range(1, len(prices)):
        if prices[i] >= prices[peak_i]:
            if armed:
                depth = (prices[peak_i] - prices[trough_i]) / prices[peak_i] * 100.0
                if depth >= threshold_pct:
                    episodes.append(
                        {
                            "peak_date": _as_iso(dates[peak_i]),
                            "trough_date": _as_iso(dates[trough_i]),
                            "depth_pct": depth,
                            "recovery_date": _as_iso(dates[i]),
                            "days_down": trough_i - peak_i,
                            "days_up": i - trough_i,
                        }
                    )
            peak_i = i
            trough_i = i
            armed = False
            continue
        if prices[i] < prices[trough_i]:
            trough_i = i
        depth = (prices[peak_i] - prices[i]) / prices[peak_i] * 100.0 if prices[peak_i] else 0
        if depth >= threshold_pct:
            armed = True
    if armed and prices[peak_i]:
        depth = (prices[peak_i] - prices[trough_i]) / prices[peak_i] * 100.0
        if depth >= threshold_pct:
            episodes.append(
                {
                    "peak_date": _as_iso(dates[peak_i]),
                    "trough_date": _as_iso(dates[trough_i]),
                    "depth_pct": depth,
                    "recovery_date": None,
                    "days_down": trough_i - peak_i,
                    "days_up": None,
                }
            )
    return episodes


def nsi_monthly(events):
    """events: list of {month, tone, status}. Только confirmed входят в NSI."""
    confirmed: dict[str, float] = {}
    draft: dict[str, float] = {}
    for event in events:
        tone = event.get("tone")
        if not is_num(tone):
            continue
        bucket = confirmed if event.get("status") == "confirmed" else draft
        month = event["month"]
        bucket[month] = bucket.get(month, 0.0) + float(tone)
    months = sorted(set(confirmed) | set(draft))
    rows = []
    running = 0.0
    for month in months:
        value = confirmed.get(month, 0.0)
        running += value
        rows.append(
            {
                "month": month,
                "nsi": value,
                "nsi_cum": running,
                "nsi_with_draft": value + draft.get(month, 0.0),
                "n_obs": sum(1 for event in events if event.get("month") == month and event.get("status") == "confirmed" and is_num(event.get("tone"))),
            }
        )
    return rows


def flow_share(years, equity_flow_share, contribution_over_capital, base=FLOW_BASE):
    if not all(is_num(v) for v in (years, equity_flow_share, contribution_over_capital)):
        return None
    denom = 1.0 + years * contribution_over_capital
    if denom == 0:
        return None
    return (base + years * equity_flow_share * contribution_over_capital) / denom


def ofz_repricing(duration_mod, delta_yield):
    """ΔP/P ≈ −D_mod·Δy. D_mod в годах, Δy в долях (0.01 = 1 п.п.)."""
    if not is_num(duration_mod) or not is_num(delta_yield):
        return None
    return -duration_mod * delta_yield


def valuation(close, shares_out, revenue_ltm, net_income_ltm, equity, net_debt, ebitda_ltm, dividends_12m, ticker):
    mcap = close * shares_out if is_num(close) and is_num(shares_out) else None
    applicable = 0 if ticker in BANKS_NO_PS else 1
    ps = (mcap / revenue_ltm) if mcap is not None and is_num(revenue_ltm) and revenue_ltm not in (0, None) and applicable else None
    pe = (mcap / net_income_ltm) if mcap is not None and is_num(net_income_ltm) and net_income_ltm not in (0, None) else None
    pb = (mcap / equity) if mcap is not None and is_num(equity) and equity not in (0, None) else None
    ev = (mcap + net_debt) if mcap is not None and is_num(net_debt) else None
    ev_ebitda = (ev / ebitda_ltm) if ev is not None and is_num(ebitda_ltm) and ebitda_ltm not in (0, None) else None
    div_yield = (dividends_12m / close * 100.0) if is_num(dividends_12m) and is_num(close) and close not in (0, None) else None
    nd_ebitda = (net_debt / ebitda_ltm) if is_num(net_debt) and is_num(ebitda_ltm) and ebitda_ltm not in (0, None) else None
    return {
        "mcap": mcap,
        "ps": ps,
        "pe": pe,
        "pb": pb,
        "ev": ev,
        "ev_ebitda": ev_ebitda,
        "div_yield_pct": div_yield,
        "nd_ebitda": nd_ebitda,
        "applicable_ps": applicable,
    }


def percentile_own(history, current):
    vals = [v for v in history if is_num(v)]
    if not is_num(current) or len(vals) < 2:
        return None
    return 100.0 * sum(1 for v in vals if v <= current) / len(vals)


def instant_step(rate, trend, rai, rate_step0=13.5, rate_step1=12.0, rate_step2=9.5, rai_below=1.0):
    if not is_num(rate):
        return None
    if rate > rate_step0 or trend == "up":
        return 0
    if not is_num(rai) or not rai < rai_below:
        return None
    if rate > rate_step1:
        return 1
    if rate > rate_step2:
        return 2
    return 3


def rai_streak_above(monthly_rai, limit=1.0):
    streak = 0
    for value in monthly_rai:
        if is_num(value) and value > limit:
            streak += 1
        else:
            streak = 0
    return streak


def stop_cap(trend, monthly_rai, months_limit=2):
    streak = rai_streak_above(monthly_rai, 1.0)
    need = months_limit + 1
    if trend == "up":
        return {"active": True, "reason": "hike", "months_to_trigger": 0, "streak": streak}
    if streak > months_limit:
        return {"active": True, "reason": "rai_gt1_over_2m", "months_to_trigger": 0, "streak": streak}
    return {"active": False, "reason": "none", "months_to_trigger": max(0, need - streak), "streak": streak}


def weak_windows(day: date):
    labels = []
    if day.weekday() == 3:
        labels.append("thursday")
    if 15 <= day.day <= 21:
        labels.append("week3")
    if day.month == 2:
        labels.append("feb")
    if day.month == 9:
        labels.append("sep")
    return labels


def monetary_soft(rate, trend, rate_step0=13.5):
    if not is_num(rate):
        return None
    return rate <= rate_step0 and trend != "up"


def solar_weight_sum():
    return sum(SOLAR_V1_WEIGHTS)


def ssn_smooth_v1(values):
    half = len(SOLAR_V1_WEIGHTS) // 2
    out = [None] * len(values)
    for i in range(half, len(values) - half):
        window = values[i - half : i + half + 1]
        if any(not is_num(v) for v in window):
            continue
        out[i] = sum(weight * value for weight, value in zip(SOLAR_V1_WEIGHTS, window)) / SOLAR_V1_DIVISOR
    return out


def weather_anomaly(tmean, normal):
    if not is_num(tmean) or not is_num(normal):
        return None
    return tmean - normal


def composite_mean(values):
    nums = [v for v in values if is_num(v)]
    if not nums:
        return None
    return sum(nums) / len(nums)


def top_abs_months(rows, limit=12):
    ranked = [row for row in rows if is_num(row.get("anomaly"))]
    ranked.sort(key=lambda row: abs(row["anomaly"]), reverse=True)
    return ranked[:limit]


def yoy_change(level_then, level_now):
    return monthly_return_pct(level_then, level_now)


def rate_change_pp(rate_then, rate_now):
    if not is_num(rate_then) or not is_num(rate_now):
        return None
    return rate_now - rate_then


def adj_multiplier(action_type, ratio):
    """Сколько накопить в adj_factor за одно событие после даты цены.

    split X:1 — историческую цену делим на X.
    consolidation X:1 — историческую цену умножаем на X, значит множитель фактора 1/X.
    """
    if not ratio or ":" not in ratio:
        return None
    left, right = ratio.split(":", 1)
    try:
        a = float(left)
        b = float(right)
    except ValueError:
        return None
    if a == 0 or b == 0:
        return None
    if action_type == "split":
        return a / b
    if action_type == "consolidation":
        return b / a
    return None


def adj_factor_on(price_date, actions):
    factor = 1.0
    stamp = price_date if isinstance(price_date, date) else date.fromisoformat(str(price_date)[:10])
    for action in actions:
        raw = action.get("date") or ""
        if not raw:
            continue
        try:
            event = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        if event <= stamp:
            continue
        mult = adj_multiplier(action.get("type"), action.get("ratio"))
        if mult is None:
            continue
        factor *= mult
    return factor


def propose_tone(text: str):
    """Только явные формулировки из шкалы 4.3. Иначе тон пустой, не ноль."""
    lowered = text.casefold()
    if "снятие ограничений" in lowered or "снизил ключевую ставку" in lowered or "снижение ключевой ставки" in lowered:
        return 2
    if "мобилизац" in lowered or "санкции против мосбиржи" in lowered or "санкции против московской биржи" in lowered:
        return -2
    if "повыс" in lowered and "ставк" in lowered:
        if ">2" in lowered or "на 3" in lowered or "на 4" in lowered or "более чем на 2" in lowered:
            return -2
        return -1
    if "рост инфляции" in lowered or "инфляция выросла" in lowered:
        return -1
    return None


def notable(corr, threshold=0.24):
    if not is_num(corr):
        return None
    return 1 if abs(corr) > threshold else 0
