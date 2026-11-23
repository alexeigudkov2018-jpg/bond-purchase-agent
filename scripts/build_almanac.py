"""Сборка текстового выпуска Альманаха, том 2, только из уже посчитанных таблиц."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.common import CLEAN, DERIVED, LOGS, ROOT, now_msk, read_csv  # noqa: E402

OUT = ROOT / "almanac"
LATEST = OUT / "Almanac_Vol2_latest.md"
ARCHIVE = OUT / "archive"


def _last(rows, field="month"):
    usable = [row for row in rows if row.get(field)]
    return usable[-1] if usable else {}


def _count(path: Path) -> int:
    if not path.exists():
        return 0
    return max(0, sum(1 for _ in path.open(encoding="utf-8")) - 1)


def _span(path: Path, field: str) -> tuple[str, str]:
    rows = read_csv(path) if path.exists() else []
    values = sorted(row[field] for row in rows if row.get(field))
    if not values:
        return "нет", "нет"
    return values[0], values[-1]


def _num(text):
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _show(value) -> str:
    if value in (None, ""):
        return "нет"
    return str(value)


def build(today: date) -> tuple[str, list[tuple[str, str]]]:
    metrics: list[tuple[str, str]] = []

    def metric(name: str, value) -> str:
        shown = _show(value)
        metrics.append((name, shown))
        return shown

    prices_min, prices_max = _span(CLEAN / "prices_daily.csv", "date")
    index_min, index_max = _span(CLEAN / "indices_daily.csv", "date")
    ofz_min, ofz_max = _span(CLEAN / "ofz_daily.csv", "date")
    macro = read_csv(CLEAN / "macro_monthly.csv")
    full = [row for row in macro if row.get("month") and row["month"] < today.strftime("%Y-%m")]
    month = _last(full)
    indices = [row for row in read_csv(CLEAN / "indices_daily.csv") if row.get("index") == "IMOEX"]
    imoex_last = indices[-1] if indices else {}
    returns = [row for row in read_csv(DERIVED / "returns_monthly.csv") if row.get("ticker") == "IMOEX" and row.get("month", "") < today.strftime("%Y-%m")]
    imoex_ret = _last(returns)
    sectors = [row for row in read_csv(DERIVED / "sector_returns.csv") if row.get("month") == imoex_ret.get("month")]
    weekdays = read_csv(DERIVED / "weekday_stats.csv")
    rai = [row for row in read_csv(DERIVED / "rai_monthly.csv") if row.get("month", "") < today.strftime("%Y-%m")]
    rai_row = _last(rai)
    curve = _last(read_csv(CLEAN / "ofz_curve_daily.csv"), "date")
    dashboard = {}
    board = DERIVED / "plan_dashboard.json"
    if board.exists():
        dashboard = json.loads(board.read_text(encoding="utf-8"))
    gaps = _count(LOGS / "gaps.csv")

    metric("prices_rows", _count(CLEAN / "prices_daily.csv"))
    metric("prices_min", prices_min)
    metric("prices_max", prices_max)
    metric("indices_rows", _count(CLEAN / "indices_daily.csv"))
    metric("indices_min", index_min)
    metric("indices_max", index_max)
    metric("ofz_rows", _count(CLEAN / "ofz_daily.csv"))
    metric("ofz_min", ofz_min)
    metric("ofz_max", ofz_max)
    metric("macro_month", month.get("month"))
    metric("key_rate", month.get("key_rate"))
    metric("usdrub", month.get("usdrub"))
    metric("brent_last", month.get("brent_last"))
    metric("ssn", month.get("ssn"))
    metric("imoex_date", imoex_last.get("date"))
    metric("imoex_close", imoex_last.get("close"))
    metric("imoex_month", imoex_ret.get("month"))
    metric("imoex_ret_pct", imoex_ret.get("ret_pct"))
    metric("rai_month", rai_row.get("month"))
    metric("rai_imoex", rai_row.get("IMOEX"))
    metric("ofz_2y", curve.get("t_2y"))
    metric("ofz_10y", curve.get("t_10y"))
    metric("step", dashboard.get("step"))
    metric("gaps", gaps)

    lines = [
        "# Альманах. Том 2. Российский фондовый рынок",
        "",
        f"Выпуск: {today.isoformat()}. Числа взяты из `data/clean` и `data/derived` на эту дату. Пустая ячейка источника здесь записана как «нет».",
        "",
        "Материал не является индивидуальной инвестиционной рекомендацией.",
        "",
        "## Метрики",
        "",
    ]
    for name, value in metrics:
        lines.append(f"- {name}: {value}")
    lines.extend(["", "## Покрытие", ""])
    lines.append(f"Дневные акции: {_count(CLEAN / 'prices_daily.csv')} строк, {prices_min} — {prices_max}.")
    lines.append(f"Дневные индексы: {_count(CLEAN / 'indices_daily.csv')} строк, {index_min} — {index_max}.")
    lines.append(f"ОФЗ: {_count(CLEAN / 'ofz_daily.csv')} строк, {ofz_min} — {ofz_max}.")
    lines.extend(["", "## Макро", ""])
    lines.append(
        f"Последний полный месяц { _show(month.get('month')) }: ставка {_show(month.get('key_rate'))}%, "
        f"USD/RUB {_show(month.get('usdrub'))}, Brent {_show(month.get('brent_last'))}, SSN {_show(month.get('ssn'))}."
    )
    lines.append("Золото, серебро, платина и палладий в месячной таблице — учётные цены ЦБ, рубли за грамм.")
    lines.extend(["", "## IMOEX", ""])
    lines.append(f"Последнее закрытие {_show(imoex_last.get('date'))}: {_show(imoex_last.get('close'))}.")
    lines.append(
        f"Доходность полного месяца {_show(imoex_ret.get('month'))}: {_show(imoex_ret.get('ret_pct'))}% без дивидендов."
    )
    lines.append(f"RAI на последний полный месяц {_show(rai_row.get('month'))}: {_show(rai_row.get('IMOEX'))}.")
    if weekdays:
        lines.append("")
        lines.append("Дни недели по дневным закрытиям IMOEX:")
        lines.append("")
        lines.append("| день | n | среднее, % | медиана, % | доля плюс |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in weekdays:
            lines.append(
                f"| {row.get('weekday','')} | {row.get('n_days','')} | {row.get('mean_pct','')} | {row.get('median_pct','')} | {row.get('pct_up','')} |"
            )
    lines.extend(["", "## Секторы", ""])
    if sectors:
        lines.append(f"Равновзвешенная доходность за {_show(imoex_ret.get('month'))}.")
        lines.append("")
        for row in sectors:
            lines.append(f"- {row.get('sector')}: {_show(row.get('ret_pct_eq'))}% (бумаг {row.get('n_tickers')})")
    else:
        lines.append("Секторных доходностей нет.")
    lines.extend(["", "## Кривая ОФЗ", ""])
    lines.append(
        f"Срез {_show(curve.get('date'))}: 2 года {_show(curve.get('t_2y'))}, 10 лет {_show(curve.get('t_10y'))}."
    )
    lines.append("Это текущий снимок zcyc, не история с 2021-01-04.")
    lines.extend(["", "## Табло плана", ""])
    lines.append(f"Ступень: {_show(dashboard.get('step'))}. Направление ставки: {_show(dashboard.get('key_rate_trend'))}.")
    lines.append(f"Пропусков в `logs/gaps.csv`: {gaps}.")
    lines.append("")
    return "\n".join(lines) + "\n", metrics


def _previous_metrics(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        if not line.startswith("- ") or ": " not in line:
            continue
        name, value = line[2:].split(": ", 1)
        if name.replace("_", "").isalnum():
            found[name] = value
    return found


def render_diff(today: date, previous: dict[str, str], current: list[tuple[str, str]]) -> str:
    lines = [f"# Сравнение выпуска {today.isoformat()}", ""]
    if not previous:
        lines.append("Предыдущего выпуска не было.")
        lines.append("")
    for name, new in current:
        old = previous.get(name, "нет")
        old_n, new_n = _num(old), _num(new)
        if old_n is not None and new_n is not None:
            delta = f"{new_n - old_n:.6g}"
        elif old == "нет" and new != "нет":
            delta = "появилось значение"
        elif old == new:
            delta = "0"
        else:
            delta = "текст изменился"
        lines.extend([f"## {name}", "", f"Было: {old}", f"Стало: {new}", f"Дельта: {delta}", ""])
    return "\n".join(lines)


def main() -> None:
    today = now_msk().date()
    previous_text = LATEST.read_text(encoding="utf-8") if LATEST.exists() else ""
    body, metrics = build(today)
    OUT.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    diff = render_diff(today, _previous_metrics(previous_text), metrics)
    (OUT / f"DIFF_{today.isoformat()}.md").write_text(diff, encoding="utf-8")
    LATEST.write_text(body, encoding="utf-8")
    (ARCHIVE / f"Almanac_Vol2_{today.isoformat()}.md").write_text(body, encoding="utf-8")
    print(f"latest={LATEST.relative_to(ROOT)} diff=almanac/DIFF_{today.isoformat()}.md")


if __name__ == "__main__":
    main()
