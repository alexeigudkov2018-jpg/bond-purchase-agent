"""Точка входа сборщика. Режимы — раздел 4.2 docs/COLLECTOR_SPEC.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.pipeline import run  # noqa: E402

MODES = ("test", "daily", "weekly", "monthly", "quarterly", "backfill")


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборщик Альманаха, том 2")
    parser.add_argument(
        "--mode",
        default="daily",
        choices=MODES,
        help="daily: прошлый торговый день; weekly: солнце, погода, дивиденды, статусы; "
        "monthly: заморозка прошлого месяца; quarterly: отчётность; backfill: история с 2021-01-04",
    )
    args = parser.parse_args()
    result = run(args.mode)
    print(
        f"mode={result['mode']} gaps={result['gaps']} anomalies={result['anomalies']} "
        f"step={result['dashboard'].get('step')}"
    )


if __name__ == "__main__":
    main()
