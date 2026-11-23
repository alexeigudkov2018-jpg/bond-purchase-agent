"""Сбор разрешённых источников и пересчёт таблиц."""

from __future__ import annotations

import json
from datetime import date, datetime

from scripts.build_tables import build_derived, build_macro, build_prices
from scripts.common import (
    CLEAN,
    DATA,
    DERIVED,
    DIGEST,
    LOGS,
    RAW,
    REFERENCE,
    ROOT,
    HttpClient,
    ensure_tree,
    iso_now,
    now_msk,
    read_csv,
    save_raw,
    sha256_file,
    write_csv,
    write_json,
)

GAPS_COLUMNS = ["date", "series", "source", "reason"]
ANOMALY_COLUMNS = ["date", "series", "kind", "detail", "value_a", "value_b"]


def collect_allowed(client: HttpClient, run_day: date) -> dict:
    """Качает только то, что не запрещено robots.txt. ISS при Disallow: / не трогаем."""
    added = {}
    errors = []
    gaps = []
    stamp = run_day.isoformat()

    iss_url = "https://iss.moex.com/iss/securities/SMLT.json"
    allowed, reason = client.check_robots(iss_url)
    if not allowed:
        gaps.append(
            {
                "date": stamp,
                "series": "moex_iss",
                "source": "S1",
                "reason": f"ISS не скачивался: {reason}. Цены, индексы, ОФЗ, дивиденды и мультипликаторы из ISS в этом запуске пустые.",
            }
        )
    else:
        errors.append({"source": "S1", "error": "robots разрешил ISS, но тестовый сбор свечей ещё не включён отдельным флагом"})

    key_url = (
        "https://www.cbr.ru/hd_base/keyrate/"
        "?UniDbQuery.Posted=True&UniDbQuery.From=01.01.2021&UniDbQuery.To="
        + run_day.strftime("%d.%m.%Y")
    )
    _fetch(client, key_url, RAW / "cbr" / f"keyrate_{stamp}.html", "S2", "key_rate", stamp, added, errors, gaps)

    usd_url = (
        "https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=04/01/2021&date_req2="
        + run_day.strftime("%d/%m/%Y")
        + "&VAL_NM_RQ=R01235"
    )
    _fetch(client, usd_url, RAW / "cbr" / f"usdrub_{stamp}.xml", "S2", "usdrub", stamp, added, errors, gaps)

    fred_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
    _fetch(client, fred_url, RAW / "fred" / f"brent_{stamp}.csv", "S3", "brent", stamp, added, errors, gaps)

    noaa_url = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
    _fetch(client, noaa_url, RAW / "solar" / f"noaa_{stamp}.json", "S5", "ssn", stamp, added, errors, gaps)

    for code, series, why in (
        ("S4", "metals", "долларовые металлы в тестовом запуске не качались: сначала нужен ответ stooq и его robots"),
        ("S5", "silso", "официальный SILSO в тестовом запуске не качался; SSN взят из NOAA, где ряд есть"),
        ("S5", "gfz", "файл GFZ Kp/Ap в тестовом запуске не качался"),
        ("S6", "weather", "Meteostat в тестовом запуске не качался"),
        ("S7", "fundamentals", "Smart-Lab в тестовом запуске не качался"),
        ("S8", "news", "ленты новостей в тестовом запуске не качались; тон без текста не ставится"),
    ):
        gaps.append({"date": stamp, "series": series, "source": code, "reason": why})
    return {"added": added, "errors": errors, "gaps": gaps}


def _fetch(client, url, path, source, series, stamp, added, errors, gaps):
    try:
        payload = client.get(url)
    except PermissionError as error:
        gaps.append({"date": stamp, "series": series, "source": source, "reason": str(error)})
        return
    except Exception as error:  # noqa: BLE001 — один источник не останавливает остальные
        errors.append({"source": source, "error": str(error)})
        return
    created = save_raw(path, payload, url)
    added[str(path.relative_to(ROOT))] = 1 if created else 0


def quality(run_day: date, errors: list[dict]) -> dict:
    universe = [row for row in read_csv(REFERENCE / "universe.csv") if row.get("status") == "active"]
    prices = read_csv(CLEAN / "prices_daily.csv")
    last = {}
    for row in prices:
        ticker = row.get("ticker")
        if ticker and (ticker not in last or row["date"] > last[ticker]):
            last[ticker] = row["date"]
    gaps = []
    for row in universe:
        ticker = row["ticker"]
        seen = last.get(ticker, "")
        if not seen:
            gaps.append(
                {
                    "date": run_day.isoformat(),
                    "series": ticker,
                    "source": "S1",
                    "reason": "нет дневной цены: источник ISS в этом запуске не скачивался или не отдал бумагу",
                }
            )
    anomalies = []
    ordered: dict[str, list[dict]] = {}
    for row in prices:
        ordered.setdefault(row["ticker"], []).append(row)
    for ticker, bars in ordered.items():
        bars.sort(key=lambda item: item["date"])
        previous = None
        for bar in bars:
            try:
                close = float(bar["close"])
            except (TypeError, ValueError):
                continue
            volume = bar.get("volume")
            if volume not in ("", None):
                try:
                    if float(volume) == 0 and close != 0:
                        anomalies.append(
                            {
                                "date": bar["date"],
                                "series": ticker,
                                "kind": "zero_volume",
                                "detail": "объём 0 при ненулевой цене",
                                "value_a": close,
                                "value_b": 0,
                            }
                        )
                except ValueError:
                    pass
            if previous not in (None, 0):
                change = abs(close / previous - 1) * 100
                if change > 40:
                    anomalies.append(
                        {
                            "date": bar["date"],
                            "series": ticker,
                            "kind": "jump",
                            "detail": "дневное изменение больше 40%",
                            "value_a": change,
                            "value_b": "",
                        }
                    )
            previous = close
    legacy = REFERENCE / "legacy_vol1" / "Raw_Stocks.tsv"
    if not legacy.exists():
        gaps.append(
            {
                "date": run_day.isoformat(),
                "series": "legacy_vol1",
                "source": "SPEC",
                "reason": "нет data/reference/legacy_vol1/Raw_Stocks.tsv, регрессия к Тому 1 не выполнялась",
            }
        )
    return {"gaps": gaps, "anomalies": anomalies, "errors": errors}


def write_manifest(run_stamp: str) -> dict:
    previous = {}
    path = ROOT / "manifest.json"
    if path.exists():
        for item in json.loads(path.read_text(encoding="utf-8")).get("files", []):
            previous[item["file"]] = item
    files = []
    for folder in (CLEAN, DERIVED):
        for file in sorted(folder.rglob("*")):
            if not file.is_file() or file.name == ".gitkeep":
                continue
            rel = str(file.relative_to(ROOT))
            digest = sha256_file(file)
            rows = 0
            min_date = ""
            max_date = ""
            if file.suffix == ".csv":
                table = read_csv(file)
                rows = len(table)
                dates = []
                for row in table:
                    for key in ("date", "month", "year"):
                        if row.get(key):
                            dates.append(row[key])
                            break
                if dates:
                    min_date, max_date = min(dates), max(dates)
            updated = run_stamp
            old = previous.get(rel)
            if old and old.get("sha256") == digest:
                updated = old.get("updated_at", run_stamp)
            files.append(
                {"file": rel, "rows": rows, "min_date": min_date, "max_date": max_date, "sha256": digest, "updated_at": updated}
            )
    payload = {"files": files}
    write_json(path, payload)
    return payload


def render_log(run_day: date, started: datetime, added: dict, errors: list, gaps: list, anomalies: list) -> str:
    elapsed = (now_msk() - started).total_seconds()
    lines = [
        f"# Сбор {run_day.isoformat()}",
        "",
        f"Длительность, с: {elapsed:.1f}",
        "",
        "## Сырые файлы",
    ]
    if added:
        for name, flag in sorted(added.items()):
            lines.append(f"- {name}: {'создан' if flag else 'уже был, не перезаписан'}")
    else:
        lines.append("- новых файлов нет")
    lines.append("")
    lines.append("## Ошибки источников")
    if errors:
        for error in errors:
            lines.append(f"- {error['source']}: {error['error']}")
    else:
        lines.append("- нет")
    lines.append("")
    lines.append(f"## Пропуски: {len(gaps)}")
    for gap in gaps[:12]:
        lines.append(f"- {gap['series']}: {gap['reason']}")
    if len(gaps) > 12:
        lines.append(f"- ещё {len(gaps) - 12} строк в logs/gaps.csv")
    lines.append("")
    lines.append(f"## Аномалии: {len(anomalies)}")
    lines.append("")
    lines.append("Повторный запуск в тот же день не перезаписывает data/raw.")
    return "\n".join(lines) + "\n"


def render_weekly(run_day: date, dashboard: dict, gaps: list, anomalies: list) -> str:
    iso = run_day.isocalendar()
    rate = dashboard.get("key_rate")
    rate_text = "нет" if rate is None else f"{rate:.2f}%"

    def shown(value):
        return "нет" if value is None else value
    lines = [
        f"# Неделя {iso.year}-W{iso.week:02d}",
        "",
        f"Срез: {run_day.isoformat()}.",
        "IMOEX за неделю: нет дневного ряда. ISS закрыт robots.txt (Disallow: /), свечи не скачивались.",
        "IMOEX с начала года: нет дневного ряда.",
        f"Ключевая ставка на последнюю дату таблицы ЦБ: {rate_text}. Направление к предыдущему наблюдению: {dashboard.get('key_rate_trend')}.",
        f"Последняя дата изменения ставки в таблице ЦБ: {dashboard.get('last_cb_meeting') or 'нет'}. Календарь заседаний отдельно не разбирался.",
        f"RAI IMOEX, месяц: {shown(dashboard.get('rai_imoex_monthly'))}. Месяцев подряд выше 1: {shown(dashboard.get('rai_imoex_months_above_1_in_row'))}.",
        f"NSI последнего полного месяца (только confirmed): {shown(dashboard.get('nsi_last_month'))}.",
        f"Новые аномалии цен: {len(anomalies)}.",
        "Новые корпоративные действия: в реестр ничего не добавлено.",
        "Новые события-кандидаты: лента не собиралась, строк draft нет.",
        f"Табло плана: ступень {dashboard.get('step')}. Подтверждение двумя заседаниями не применялось: календаря заседаний нет, ступень мгновенная.",
        f"Стоп-кран: active={dashboard.get('stop_cap', {}).get('active')}, reason={dashboard.get('stop_cap', {}).get('reason')}, месяцев до порога RAI: {dashboard.get('stop_cap', {}).get('months_to_trigger')}.",
        f"Слабые окна этой даты: {', '.join(dashboard.get('weak_windows_today') or []) or 'нет'}.",
        f"Пропусков в журнале: {len(gaps)}. Требует решения автора: допуск к ISS, список 1-го эшелона, 22 акции матрицы, 13 погодных событий, дни сплитов.",
        "Кривая ОФЗ: нет ряда, признак инверсии пуст.",
        "",
        "Материал не является индивидуальной инвестиционной рекомендацией.",
        "",
    ]
    return "\n".join(lines)


def render_quality(manifest: dict, errors: list, gaps: list, anomalies: list) -> str:
    files = manifest.get("files", [])
    total_rows = sum(item["rows"] for item in files)
    filled = sum(1 for item in files if item["rows"] > 0)
    share = (filled / len(files)) if files else 0
    lines = [
        "# Качество",
        "",
        f"Файлов в manifest: {len(files)}",
        f"Строк суммарно: {total_rows}",
        f"Файлов с ненулевым числом строк: {filled}",
        f"Доля таких файлов: {share:.2f}",
        f"Аномалий: {len(anomalies)}",
        f"Пропусков: {len(gaps)}",
        "",
        "## Источники с ошибкой",
    ]
    if errors:
        for error in errors:
            lines.append(f"- {error['source']}: {error['error']}")
    else:
        lines.append("- нет")
    lines.append("")
    return "\n".join(lines)


def touch_sources(run_stamp: str, added: dict) -> None:
    rows = read_csv(REFERENCE / "sources.csv")
    ok = set()
    for name, flag in added.items():
        if not flag:
            continue
        if "/cbr/" in name:
            ok.add("S2")
        elif "/fred/" in name:
            ok.add("S3")
        elif "/solar/" in name:
            ok.add("S5")
        elif "/moex_iss/" in name:
            ok.add("S1")
    for row in rows:
        if row["code"] in ok:
            row["last_ok_at"] = run_stamp
    write_csv(REFERENCE / "sources.csv", ["code", "name", "url", "what", "license_note", "last_ok_at"], rows)


def run(mode: str = "test") -> dict:
    ensure_tree()
    started = now_msk()
    run_day = started.date()
    client = HttpClient()
    if mode != "test":
        raise SystemExit("полный режим не запускался: сначала тестовый сбор разрешённых источников")
    collected = collect_allowed(client, run_day)
    macro = build_macro(run_day)
    build_prices(run_day)
    dashboard = build_derived(run_day, macro["macro"], macro["events"])
    report = quality(run_day, collected["errors"])
    gaps = collected["gaps"] + report["gaps"]
    anomalies = report["anomalies"]
    write_csv(LOGS / "gaps.csv", GAPS_COLUMNS, [])
    write_csv(LOGS / "anomalies.csv", ANOMALY_COLUMNS, [])
    from scripts.common import append_unique

    append_unique(LOGS / "gaps.csv", GAPS_COLUMNS, gaps, ["date", "series", "source", "reason"])
    append_unique(LOGS / "anomalies.csv", ANOMALY_COLUMNS, anomalies, ["date", "series", "kind", "detail"])
    # Повторный запуск не должен копить те же пропуски: append_unique это держит.
    # Но пустая предварительная запись выше стирает файл. Для идемпотентности пишем сразу итог без дублей.
    dedup_gaps = []
    seen = set()
    for row in gaps:
        key = (row["date"], row["series"], row["source"], row["reason"])
        if key in seen:
            continue
        seen.add(key)
        dedup_gaps.append(row)
    write_csv(LOGS / "gaps.csv", GAPS_COLUMNS, dedup_gaps)
    write_json(DERIVED / "plan_dashboard.json", dashboard)
    run_stamp = iso_now()
    added = {key: value for key, value in collected["added"].items() if not key.startswith("/")}
    # added keys were stored twice; keep repo-relative ones
    added = {key: value for key, value in collected["added"].items() if key.startswith("data/")}
    touch_sources(run_stamp, added)
    manifest = write_manifest(run_stamp)
    log = render_log(run_day, started, added, collected["errors"], dedup_gaps, anomalies)
    (LOGS / f"{run_day.isoformat()}.md").write_text(log, encoding="utf-8")
    iso = run_day.isocalendar()
    weekly = DIGEST / "weekly" / f"{iso.year}-W{iso.week:02d}.md"
    weekly.write_text(render_weekly(run_day, dashboard, dedup_gaps, anomalies), encoding="utf-8")
    (DIGEST / "quality.md").write_text(render_quality(manifest, collected["errors"], dedup_gaps, anomalies), encoding="utf-8")
    return {"dashboard": dashboard, "gaps": len(dedup_gaps), "anomalies": len(anomalies), "added": added}
