"""Awodele / Moore discrete harmonic analysis helper.

Recomputes Fourier a,b coefficients the way Awodele walks through
(Economic Cycles rainfall example), then optionally applies the same
pipeline to MOEX mid-price series with a linear detrend layer.

This is a research calculator, not a trading signal.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def coeffs(series: list[float], period: int) -> tuple[float, float, float]:
    """a, b, power=a²+b² for cycle length `period` (Awodele discrete form)."""
    n = len(series)
    a = b = 0.0
    for t, val in enumerate(series):
        ang = 2.0 * math.pi * t / period
        a += (2.0 / n) * val * math.cos(ang)
        b += (2.0 / n) * val * math.sin(ang)
    return a, b, a * a + b * b


def reconstruct(a0: float, components: list[tuple[int, float, float]], t: int) -> float:
    y = a0
    for period, a, b in components:
        y += a * math.cos(2.0 * math.pi * t / period) + b * math.sin(2.0 * math.pi * t / period)
    return y


def local_peaks(spec: list[dict[str, Any]], order: int = 2) -> list[dict[str, Any]]:
    peaks: list[dict[str, Any]] = []
    for i in range(order, len(spec) - order):
        p = spec[i]["power"]
        if all(p > spec[i - j]["power"] for j in range(1, order + 1)) and all(
            p >= spec[i + j]["power"] for j in range(1, order + 1)
        ):
            peaks.append(spec[i])
    return peaks


def lin_detrend(y: list[float]) -> tuple[list[float], float, float, list[float]]:
    n = len(y)
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n
    num = sum((t - x_mean) * (y[t] - y_mean) for t in range(n))
    den = sum((t - x_mean) ** 2 for t in range(n))
    slope = num / den if den else 0.0
    intercept = y_mean - slope * x_mean
    trend = [intercept + slope * t for t in range(n)]
    resid = [y[t] - trend[t] for t in range(n)]
    return resid, slope, intercept, trend


def ohio_valley_rainfall() -> list[float]:
    """72 annual inches 1839–1910 as printed in Awodele ch.3 (Moore table)."""
    return [
        29.92, 42.84, 43.94, 41.89, 48.20, 37.95, 40.11, 48.39, 55.26, 44.97, 46.37, 54.77,
        32.54, 46.73, 35.67, 40.30, 47.89, 28.98, 37.95, 55.48, 46.68, 36.00, 43.81, 40.26,
        37.95, 36.68, 48.93, 47.37, 40.72, 46.87, 41.29, 37.46, 29.91, 32.90, 45.18, 38.48,
        44.78, 47.34, 34.69, 36.35, 39.22, 49.94, 41.60, 56.10, 49.25, 40.05, 37.63, 39.61,
        38.00, 46.19, 37.06, 55.43, 40.68, 36.96, 40.80, 31.07, 29.06, 39.22, 44.80, 45.04,
        40.46, 33.60, 31.78, 39.53, 37.98, 28.24, 42.81, 41.95, 46.68, 33.29, 41.40, 36.20,
    ]


def verify_rainfall_example() -> dict[str, Any]:
    rain = ohio_valley_rainfall()
    assert len(rain) == 72
    a0 = sum(rain) / len(rain)
    a8, b8, p8 = coeffs(rain, 8)
    recon = [reconstruct(a0, [(8, a8, b8)], t) for t in range(4)]
    spec = []
    for t in range(3, 37):
        a, b, p = coeffs(rain, t)
        spec.append({"T": t, "a": a, "b": b, "power": p, "amp": math.sqrt(p)})
    peaks = sorted(local_peaks(spec), key=lambda r: -r["power"])
    return {
        "N": 72,
        "A0": a0,
        "book_A0_rounded": 41.19,
        "T8": {
            "a": a8,
            "b": b8,
            "power": p8,
            "book_a": -3.1339,
            "book_b": 2.6938,
            "book_power": 17.0745,
        },
        "recon_t0_3": recon,
        "book_recon_t0_3": [38.0531, 40.8756, 43.8803, 45.3069],
        "local_peaks_top": peaks[:10],
    }


def _mids_by_bucket(daily: list[dict[str, Any]], mode: str) -> tuple[list[float], list[dict[str, Any]]]:
    buckets: dict[Any, list[tuple[datetime, float]]] = {}
    for r in daily:
        td = r.get("TRADEDATE")
        if not td:
            continue
        close, high, low = r.get("CLOSE"), r.get("HIGH"), r.get("LOW")
        if close is None and (high is None or low is None):
            continue
        d = datetime.strptime(td, "%Y-%m-%d")
        key = d.isocalendar()[:2] if mode == "weekly" else (d.year, d.month)
        mid = (float(high) + float(low)) / 2.0 if high is not None and low is not None else float(close)
        buckets.setdefault(key, []).append((d, mid))
    series: list[float] = []
    meta: list[dict[str, Any]] = []
    for key in sorted(buckets):
        pts = buckets[key]
        mid = sum(p[1] for p in pts) / len(pts)
        series.append(mid)
        row: dict[str, Any] = {"date": pts[-1][0].date().isoformat(), "mid": mid}
        if mode == "weekly":
            row["iso"] = key
        else:
            row["ym"] = key
        meta.append(row)
    return series, meta


def analyze_series(
    name: str,
    daily: list[dict[str, Any]],
    *,
    mode: str = "weekly",
    t_max: int | None = None,
    top_k: int = 6,
    forecast_n: int = 26,
) -> dict[str, Any]:
    series, meta = _mids_by_bucket(daily, mode)
    n = len(series)
    resid, slope, intercept, trend = lin_detrend(series)
    a0 = sum(resid) / n
    tmax = t_max if t_max is not None else (180 if mode == "weekly" else max(3, n // 2))
    tmax = min(tmax, max(3, int(0.45 * n)))
    harm = {int(round(n / k)) for k in range(2, 8) if n / k >= 3}
    spec: list[dict[str, Any]] = []
    for period in range(3, tmax + 1):
        a, b, power = coeffs(resid, period)
        spec.append(
            {
                "T": period,
                "a": a,
                "b": b,
                "power": power,
                "amp": math.sqrt(power),
                "phase": math.atan2(b, a),
                "n_harmonic": period in harm,
            }
        )
    peaks = [p for p in local_peaks(spec) if not p["n_harmonic"]]
    peaks_sorted = sorted(peaks, key=lambda r: -r["power"])
    ranked = sorted(spec, key=lambda r: -r["power"])
    chosen = peaks_sorted[:top_k]
    if len(chosen) < 3:
        chosen = [r for r in ranked if not r["n_harmonic"] and r["T"] >= 8][:top_k]
    comps = [(c["T"], c["a"], c["b"]) for c in chosen]

    def recon_resid(t: int) -> float:
        return reconstruct(a0, comps, t)

    recon = [trend[t] + recon_resid(t) for t in range(n)]
    ss_res = sum((series[t] - recon[t]) ** 2 for t in range(n))
    ss_tot = sum((series[t] - sum(series) / n) ** 2 for t in range(n))
    r2_price = 1 - ss_res / ss_tot if ss_tot else 0.0
    ss_res2 = sum((resid[t] - recon_resid(t)) ** 2 for t in range(n))
    ss_tot2 = sum((resid[t] - a0) ** 2 for t in range(n))
    r2_resid = 1 - ss_res2 / ss_tot2 if ss_tot2 else 0.0

    last_date = datetime.strptime(meta[-1]["date"], "%Y-%m-%d").date()

    def t_to_date(t: float) -> str:
        ti = int(round(t))
        if 0 <= ti < n:
            return meta[ti]["date"]
        step = int(round(t - (n - 1)))
        if mode == "weekly":
            return (last_date + timedelta(weeks=step)).isoformat()
        y, m = meta[-1]["ym"]
        m2 = m + step
        y2 = y + (m2 - 1) // 12
        m2 = (m2 - 1) % 12 + 1
        return f"{y2:04d}-{m2:02d}-28"

    fut = []
    for i in range(1, forecast_n + 1):
        t = n - 1 + i
        tr = intercept + slope * t
        y = tr + recon_resid(t)
        fut.append(
            {
                "step": i,
                "t": t,
                "date": t_to_date(t),
                "y": y,
                "trend": tr,
                "cycle": y - tr,
            }
        )

    def pct(a: float, b: float) -> float | None:
        return None if a == 0 else 100.0 * (b - a) / a

    now = series[-1]
    fwd: dict[str, Any] = {}
    for step in (4, 13, 26):
        if len(fut) >= step:
            f = fut[step - 1]
            fwd[str(step)] = {"date": f["date"], "y": f["y"], "pct": pct(now, f["y"])}

    dom = chosen[0]
    phase, period = dom["phase"], dom["T"]
    peaks_t, troughs_t = [], []
    for k in range(-5, 40):
        tp = phase * period / (2 * math.pi) + k * period
        tt = phase * period / (2 * math.pi) + period / 2 + k * period
        if n - 2 <= tp < n + forecast_n:
            peaks_t.append(tp)
        if n - 2 <= tt < n + forecast_n:
            troughs_t.append(tt)

    return {
        "name": name,
        "mode": mode,
        "N": n,
        "from": meta[0]["date"],
        "to": meta[-1]["date"],
        "last_mid": now,
        "detrend": {
            "slope_per_bar": slope,
            "intercept": intercept,
            "note": "linear detrend before HA — working layer, not in Awodele text",
        },
        "t_max": tmax,
        "r2_price": r2_price,
        "r2_resid": r2_resid,
        "chosen": chosen,
        "top_local_peaks": peaks_sorted[:12],
        "top_raw_power": ranked[:10],
        "dom_T": dom["T"],
        "dom_amp": dom["amp"],
        "next_dom_peaks": [{"t": t, "date": t_to_date(t)} for t in peaks_t[:4]],
        "next_dom_troughs": [{"t": t, "date": t_to_date(t)} for t in troughs_t[:4]],
        "fwd": fwd,
        "forecast_head": fut[:12],
    }


def load_iss_history(path: str | Path) -> list[dict[str, Any]]:
    rows = json.loads(Path(path).read_text())
    for r in rows:
        for k in ("CLOSE", "HIGH", "LOW"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    return rows


if __name__ == "__main__":
    rain = verify_rainfall_example()
    print("rainfall A0", round(rain["A0"], 5), "T8 a", round(rain["T8"]["a"], 4), "b", round(rain["T8"]["b"], 4))
