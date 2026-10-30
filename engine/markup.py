"""Регрессивная наценка ассортимента.

Дешёвые позиции — высокая наценка, дорогие — низкая.
Цель по деньгам: валовая маржа 23–27% при выручке, смещённой к дорогому краю.
Это не инвестиционная рекомендация и не готовый прайс конкретного каталога.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

COST_MIN = 1.0
COST_MAX = 180_000.0
TARGET_MARGIN_MIN = 0.23
TARGET_MARGIN_MAX = 0.27

# Верхняя граница ступени (включительно) → наценка в процентах.
# 1–5 ₽ до 1000%; 50–100 ₽ усилены до 280–350%; 180 000 ₽ → 25% (= 20% маржи).
# 500–100 000 ₽ — мягкий спуск многими ступенями к дорогому краю.
TIERS: tuple[tuple[float, float], ...] = (
    (5, 1000),
    (15, 700),
    (30, 500),
    (50, 400),
    (75, 350),
    (100, 280),
    (200, 200),
    (350, 160),
    (500, 120),
    (800, 100),
    (1_200, 85),
    (2_000, 70),
    (3_500, 58),
    (5_000, 50),
    (8_000, 42),
    (12_000, 38),
    (20_000, 35),
    (35_000, 32),
    (50_000, 30),
    (70_000, 28),
    (100_000, 27),
    (140_000, 26),
    (180_000, 25),
)

# Ориентир микса выручки, при котором шкала даёт ~26% маржи по деньгам.
DEFAULT_REVENUE_MIX: tuple[tuple[float, float], ...] = (
    (3, 0.01),
    (75, 0.02),
    (300, 0.03),
    (2_000, 0.06),
    (15_000, 0.15),
    (50_000, 0.23),
    (100_000, 0.25),
    (160_000, 0.25),
)


@dataclass(frozen=True)
class PriceQuote:
    cost: float
    markup_pct: float
    margin_pct: float
    price: float
    band_low: float
    band_high: float


def markup_pct(cost: float) -> float:
    """Наценка в процентах для закупочной цены."""
    if cost < COST_MIN:
        raise ValueError(f"закупка ниже {COST_MIN}: {cost}")
    for high, rate in TIERS:
        if cost <= high:
            return float(rate)
    return float(TIERS[-1][1])


def margin_from_markup(markup_percent: float) -> float:
    """Доля валовой маржи в цене: m / (100 + m)."""
    if markup_percent < 0:
        raise ValueError(f"отрицательная наценка: {markup_percent}")
    return markup_percent / (100.0 + markup_percent)


def sell_price(cost: float, markup_percent: float | None = None) -> float:
    rate = markup_pct(cost) if markup_percent is None else markup_percent
    return round(cost * (1.0 + rate / 100.0), 2)


def band_for(cost: float) -> tuple[float, float]:
    low = COST_MIN
    for high, _ in TIERS:
        if cost <= high:
            return low, high
        low = high
    return TIERS[-2][0], COST_MAX


def quote(cost: float) -> PriceQuote:
    rate = markup_pct(cost)
    low, high = band_for(cost)
    return PriceQuote(
        cost=round(cost, 4),
        markup_pct=rate,
        margin_pct=round(margin_from_markup(rate) * 100.0, 2),
        price=sell_price(cost, rate),
        band_low=low,
        band_high=high,
    )


def schedule() -> list[dict]:
    rows: list[dict] = []
    low = COST_MIN
    for high, rate in TIERS:
        rows.append(
            {
                "cost_from": low,
                "cost_to": high,
                "markup_pct": rate,
                "margin_pct": round(margin_from_markup(rate) * 100.0, 2),
            }
        )
        low = high + 0.01
    return rows


def money_margin(rows: list[tuple[float, float]]) -> float:
    """Валовая маржа по деньгам: Σ(margin × выручка) / Σ(выручка).

    Каждый элемент — (закупка, вес выручки). Веса нормализуются.
    """
    total_w = sum(weight for _, weight in rows)
    if total_w <= 0:
        raise ValueError("сумма весов выручки должна быть > 0")
    gross = 0.0
    for cost, weight in rows:
        gross += margin_from_markup(markup_pct(cost)) * weight
    return gross / total_w


def price_rows(costs: list[float]) -> list[dict]:
    return [asdict(quote(cost)) for cost in costs]


def price_csv(path: Path, cost_column: str = "cost", out: Path | None = None) -> Path:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or cost_column not in reader.fieldnames:
            raise ValueError(f"нет колонки {cost_column!r} в {path}")
        fieldnames = list(reader.fieldnames) + [
            "markup_pct",
            "margin_pct",
            "sell_price",
            "band_low",
            "band_high",
        ]
        rows_out: list[dict] = []
        for row in reader:
            cost = float(str(row[cost_column]).replace(" ", "").replace(",", "."))
            priced = quote(cost)
            enriched = dict(row)
            enriched.update(
                {
                    "markup_pct": priced.markup_pct,
                    "margin_pct": priced.margin_pct,
                    "sell_price": priced.price,
                    "band_low": priced.band_low,
                    "band_high": priced.band_high,
                }
            )
            rows_out.append(enriched)

    target = out or path.with_name(f"{path.stem}_priced.csv")
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)
    return target


def build_report(sample_costs: list[float] | None = None) -> dict:
    samples = sample_costs or [1, 5, 50, 75, 100, 500, 2_000, 20_000, 100_000, 180_000]
    target_margin = money_margin(list(DEFAULT_REVENUE_MIX))
    return {
        "title": "Регрессивная наценка бизнеса",
        "sku_capacity": 100_000,
        "cost_range": {"min": COST_MIN, "max": COST_MAX},
        "target_money_margin": {
            "min_pct": TARGET_MARGIN_MIN * 100,
            "max_pct": TARGET_MARGIN_MAX * 100,
            "model_pct": round(target_margin * 100, 2),
            "note": (
                "Цель 23–27% — по деньгам (валовая прибыль / выручка), не среднее наценки. "
                "Модельный микс смещён к дорогому краю; при доминировании дешёвых SKU маржа выше."
            ),
        },
        "anchors": {
            "cheap_1_5": "до 1000% наценки",
            "mid_50_100": "280–350% наценки",
            "expensive_180000": "25% наценки = 20% маржи",
            "middle_500_100000": "мягкий спуск, много ступеней",
        },
        "schedule": schedule(),
        "samples": price_rows(samples),
        "default_revenue_mix": [
            {"cost": cost, "revenue_share": share, **asdict(quote(cost))}
            for cost, share in DEFAULT_REVENUE_MIX
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Регрессивная наценка по закупочной цене")
    parser.add_argument("cost", nargs="?", type=float, help="закупочная цена, ₽")
    parser.add_argument("--schedule", action="store_true", help="напечатать ступени JSON")
    parser.add_argument("--report", action="store_true", help="полный отчёт JSON")
    parser.add_argument("--csv", type=Path, help="CSV с колонкой cost")
    parser.add_argument("--cost-column", default="cost")
    parser.add_argument("--out", type=Path, help="куда писать priced CSV")
    args = parser.parse_args(argv)

    if args.schedule:
        json.dump(schedule(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.report:
        json.dump(build_report(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.csv:
        target = price_csv(args.csv, cost_column=args.cost_column, out=args.out)
        print(target)
        return 0
    if args.cost is None:
        parser.print_help()
        return 2

    priced = quote(args.cost)
    print(
        f"закупка {priced.cost:.2f} ₽ → наценка {priced.markup_pct:.0f}% "
        f"(маржа {priced.margin_pct:.1f}%) → цена {priced.price:.2f} ₽ "
        f"[{priced.band_low:.0f}–{priced.band_high:.0f}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
