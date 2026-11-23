"""Точка входа: python scripts/run_collector.py --mode test"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.pipeline import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборщик Альманаха, том 2")
    parser.add_argument("--mode", default="test", choices=["test"])
    args = parser.parse_args()
    result = run(args.mode)
    print(f"gaps={result['gaps']} anomalies={result['anomalies']} step={result['dashboard'].get('step')}")


if __name__ == "__main__":
    main()
