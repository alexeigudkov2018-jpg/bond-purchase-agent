"""Загрузка сырья по режимам раздела 4.2. Существующий raw не перезаписывается."""

from __future__ import annotations

import json
from datetime import date, timedelta

from scripts.common import RAW, REFERENCE, ROOT, HttpClient, read_csv, save_raw

HISTORY_START = date(2021, 1, 4)
SUN_START = date(2015, 1, 1)
WEATHER_START = date(1991, 1, 1)
NEWS_START = date(2021, 12, 1)
FUNDAMENTALS_FROM = 2019
ISS = "https://iss.moex.com"
STATIONS = (
    ("27612", "Москва"),
    ("26063", "Санкт-Петербург"),
    ("29430", "Новосибирск"),
    ("30710", "Иркутск"),
    ("31960", "Хабаровск"),
    ("34731", "Ростов-на-Дону"),
)
RAI_AND_EXTRA = (
    "IMOEX",
    "IMOEX2",
    "MOEX10",
    "MOEXOG",
    "MOEXMM",
    "MOEXFN",
    "MOEXCN",
    "MOEXEU",
    "MOEXTL",
    "MOEXCH",
    "MOEXTN",
    "MOEXINN",
    "RGBI",
    "RGBITR",
    "MCFTR",
)


def previous_trading_day(today: date) -> date:
    """Прошлый будний день. Биржевой календарь праздников в задании не задан."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def jobs_for(mode: str, today: date) -> dict:
    """Какие куски раздела 4.2 выполняет явный запуск режима."""
    prev = previous_trading_day(today)
    jobs = {
        "mode": mode,
        "iss_market": False,
        "iss_reference": False,
        "cbr_macro": False,
        "brent": False,
        "metals": False,
        "solar": False,
        "weather": False,
        "fundamentals": False,
        "news": False,
        "weekly_digest": False,
        "monthly_digest": False,
        "market_from": None,
        "market_to": None,
        "note": "",
    }
    if mode == "daily":
        jobs.update(
            iss_market=True,
            cbr_macro=True,
            brent=True,
            metals=True,
            market_from=prev,
            market_to=prev,
        )
    elif mode == "weekly":
        jobs.update(solar=True, weather=True, iss_reference=True, news=False, weekly_digest=True)
        if today.weekday() != 0:
            jobs["note"] = "weekly запущен не в понедельник; задание выполнено по флагу"
    elif mode == "monthly":
        jobs.update(monthly_digest=True, weekly_digest=False)
        if today.day != 1:
            jobs["note"] = "monthly запущен не 1-го числа; заморозка предыдущего месяца выполнена по флагу"
    elif mode == "quarterly":
        jobs.update(fundamentals=True)
        if not (today.day == 15 and today.month in (1, 4, 7, 10)):
            jobs["note"] = "quarterly запущен не 15-го января, апреля, июля или октября; отчётность снята по флагу"
    elif mode == "backfill":
        jobs.update(
            iss_market=True,
            iss_reference=True,
            cbr_macro=True,
            brent=True,
            metals=True,
            solar=True,
            weather=True,
            fundamentals=True,
            news=True,
            weekly_digest=True,
            monthly_digest=True,
            market_from=HISTORY_START,
            market_to=today,
            note="первичная загрузка: рынок с 2021-01-04, солнце с 2015-01, погода с 1991-01, отчётность с 2019",
        )
    else:
        raise ValueError(f"неизвестный режим {mode}")
    return jobs


def collect_jobs(client: HttpClient, jobs: dict, run_day: date) -> dict:
    added: dict[str, int] = {}
    errors = []
    gaps = []
    stamp = run_day.isoformat()
    iss_open = _iss_allowed(client, gaps, stamp) if jobs["iss_market"] or jobs["iss_reference"] else False
    if jobs["iss_market"]:
        if iss_open:
            _fetch_iss_market(client, jobs["market_from"], jobs["market_to"], run_day, added, errors, gaps)
        else:
            gaps.append(
                {
                    "date": stamp,
                    "series": "moex_iss",
                    "source": "S1",
                    "reason": "ISS не скачивался: robots.txt запрещает URL. Цены, индексы, ОФЗ, дивиденды и статусы в этом запуске пустые.",
                }
            )
    elif jobs["iss_reference"] and not iss_open:
        gaps.append(
            {
                "date": stamp,
                "series": "moex_iss_reference",
                "source": "S1",
                "reason": "дивиденды и статусы бумаг не сняты: robots.txt ISS запрещает URL",
            }
        )
    if jobs["iss_reference"] and iss_open:
        _fetch_iss_reference(client, run_day, added, errors, gaps)
    if jobs["cbr_macro"]:
        _fetch_cbr_macro(client, jobs["market_from"] or HISTORY_START, jobs["market_to"] or run_day, run_day, added, errors, gaps)
    if jobs["brent"]:
        _fetch(
            client,
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU",
            RAW / "fred" / f"brent_{stamp}.csv",
            "S3",
            "brent",
            stamp,
            added,
            errors,
            gaps,
        )
    if jobs["metals"]:
        _fetch_metals(client, jobs["market_from"] or HISTORY_START, jobs["market_to"] or run_day, run_day, added, errors, gaps)
    if jobs["solar"]:
        _fetch_solar(client, run_day, added, errors, gaps)
    if jobs["weather"]:
        _fetch_weather(client, run_day, added, errors, gaps)
    if jobs["news"]:
        _fetch_news(client, run_day, added, errors, gaps)
    if jobs["fundamentals"]:
        _fetch_fundamentals(client, run_day, added, errors, gaps)
    return {"added": added, "errors": errors, "gaps": gaps, "jobs": jobs}


def _iss_allowed(client, gaps, stamp) -> bool:
    allowed, reason = client.check_robots(f"{ISS}/iss/securities/SMLT.json")
    if allowed:
        return True
    return False


def _active_tickers():
    return [row["ticker"] for row in read_csv(REFERENCE / "universe.csv") if row.get("status") == "active" and row.get("ticker")]


def _fetch(client, url, path, source, series, stamp, added, errors, gaps, pause=None):
    if path.exists():
        added[str(path.relative_to(ROOT))] = 0
        return True
    try:
        payload = client.get(url, pause=pause)
    except PermissionError as error:
        gaps.append({"date": stamp, "series": series, "source": source, "reason": str(error)})
        return False
    except Exception as error:  # noqa: BLE001 — один источник не останавливает остальные
        errors.append({"source": source, "error": f"{series}: {error}"})
        return False
    created = save_raw(path, payload, url)
    added[str(path.relative_to(ROOT))] = 1 if created else 0
    return True


def _fetch_iss_market(client, start: date, end: date, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    window = f"from={start.isoformat()}&till={end.isoformat()}&iss.meta=off"
    tickers = _active_tickers()
    for index, ticker in enumerate(tickers, start=1):
        print(f"iss shares {index}/{len(tickers)} {ticker}", flush=True)
        url = f"{ISS}/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?{window}"
        _fetch_iss_paged(client, url, RAW / "moex_iss" / "shares" / f"{ticker}_{stamp}.json", "S1", ticker, stamp, added, errors, gaps)
    for index, code in enumerate(RAI_AND_EXTRA, start=1):
        print(f"iss index {index}/{len(RAI_AND_EXTRA)} {code}", flush=True)
        path = RAW / "moex_iss" / "indices" / f"{code}_{stamp}.json"
        url = f"{ISS}/iss/history/engines/stock/markets/index/boards/SNDX/securities/{code}.json?{window}"
        _fetch_iss_paged(client, url, path, "S1", code, stamp, added, errors, gaps)
        if _history_rows(path) == 0:
            alt = RAW / "moex_iss" / "indices" / f"{code}_all_{stamp}.json"
            alt_url = f"{ISS}/iss/history/engines/stock/markets/index/securities/{code}.json?{window}"
            _fetch_iss_paged(client, alt_url, alt, "S1", f"{code}_all", stamp, added, errors, gaps)
            if _history_rows(alt) == 0:
                gaps.append(
                    {
                        "date": stamp,
                        "series": code,
                        "source": "S1",
                        "reason": "история индекса пуста и на доске SNDX, и без доски",
                    }
                )
    _fetch_ofz_by_day(client, start, end, run_day, added, errors, gaps)
    curve_url = f"{ISS}/iss/engines/stock/zcyc.json?iss.meta=off"
    _fetch(client, curve_url, RAW / "moex_iss" / "bonds" / f"zcyc_{stamp}.json", "S1", "zcyc", stamp, added, errors, gaps)
    gaps.append(
        {
            "date": stamp,
            "series": "zcyc_history",
            "source": "S1",
            "reason": "эндпоинт zcyc отдаёт текущую кривую; отдельной истории с 2021-01-04 в задании нет",
        }
    )


def _fetch_ofz_by_day(client, start: date, end: date, run_day: date, added, errors, gaps):
    """История всей доски TQOB по from/till не отдаётся: берём date= на каждый будний день."""
    stamp = run_day.isoformat()
    day = start
    while day <= end:
        if day.weekday() < 5:
            month = day.strftime("%Y-%m")
            path = RAW / "moex_iss" / "bonds" / f"ofz_{stamp}_{month}.json"
            if not path.exists():
                print(f"iss ofz {month}", flush=True)
                failed = _fetch_ofz_month(client, day.replace(day=1), start, end, path, errors)
                if path.exists():
                    added[str(path.relative_to(ROOT))] = 1
                for failed_day in failed:
                    gaps.append(
                        {
                            "date": stamp,
                            "series": f"ofz_{failed_day}",
                            "source": "S1",
                            "reason": "день ОФЗ не скачан, месяц сохранён без этой даты",
                        }
                    )
        day += timedelta(days=1)


def _fetch_ofz_month(client, month_start: date, series_start: date, series_end: date, path, errors) -> list[str]:
    columns = None
    data = []
    failed = []
    day = month_start
    while day.month == month_start.month and day <= series_end:
        if day >= series_start and day.weekday() < 5:
            url = (
                f"{ISS}/iss/history/engines/stock/markets/bonds/boards/TQOB/securities.json"
                f"?date={day.isoformat()}&iss.meta=off"
            )
            try:
                payload = json.loads(client.get(url))
            except Exception as error:  # noqa: BLE001
                errors.append({"source": "S1", "error": f"ofz {day.isoformat()}: {error}"})
                failed.append(day.isoformat())
            else:
                block = payload.get("history") or {}
                columns = block.get("columns") or columns
                data.extend(block.get("data") or [])
        day += timedelta(days=1)
    body = json.dumps({"history": {"columns": columns or [], "data": data}}, ensure_ascii=False).encode("utf-8")
    save_raw(
        path,
        body,
        f"{ISS}/iss/history/engines/stock/markets/bonds/boards/TQOB/securities.json?month={month_start.strftime('%Y-%m')}",
    )
    return failed


def _fetch_iss_reference(client, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    dividend_gap = False
    for ticker in _active_tickers():
        _fetch(
            client,
            f"{ISS}/iss/securities/{ticker}.json?iss.meta=off",
            RAW / "moex_iss" / "shares" / f"security_{ticker}_{stamp}.json",
            "S1",
            f"{ticker}_security",
            stamp,
            added,
            errors,
            gaps,
        )
        if dividend_gap:
            continue
        path = RAW / "moex_iss" / "dividends" / f"{ticker}_{stamp}.json"
        url = f"{ISS}/iss/securities/{ticker}/dividends.json?iss.meta=off"
        if path.exists():
            added[str(path.relative_to(ROOT))] = 0
            continue
        try:
            payload = json.loads(client.get(url))
        except Exception as error:  # noqa: BLE001
            errors.append({"source": "S1", "error": f"{ticker}_dividends: {error}"})
            continue
        if "dividends" not in payload:
            dividend_gap = True
            gaps.append(
                {
                    "date": stamp,
                    "series": "dividends",
                    "source": "S1",
                    "reason": "ISS /securities/{ticker}/dividends.json не содержит блок dividends",
                }
            )
            continue
        created = save_raw(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), url)
        added[str(path.relative_to(ROOT))] = 1 if created else 0


def _history_rows(path) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    return len((payload.get("history") or {}).get("data") or [])


def _fetch_iss_paged(client, url, path, source, series, stamp, added, errors, gaps):
    if path.exists():
        added[str(path.relative_to(ROOT))] = 0
        return
    columns = None
    data = []
    start = 0
    try:
        while True:
            page_url = f"{url}{'&' if '?' in url else '?'}start={start}&iss.meta=off"
            payload = json.loads(client.get(page_url))
            block = None
            for key in ("history", "dividends"):
                if key in payload:
                    block = payload[key]
                    cursor = payload.get(f"{key}.cursor") or {}
                    break
            if block is None:
                errors.append({"source": source, "error": f"{series}: в ответе ISS нет history/dividends"})
                return
            columns = block.get("columns") or columns
            data.extend(block.get("data") or [])
            cursor_row = (cursor.get("data") or [[0, 0, 100]])[0]
            total = cursor_row[1] if len(cursor_row) > 1 else 0
            pagesize = cursor_row[2] if len(cursor_row) > 2 else 100
            start += pagesize or 100
            if not block.get("data") or start >= total:
                break
    except Exception as error:  # noqa: BLE001
        errors.append({"source": source, "error": f"{series}: {error}"})
        return
    body = json.dumps({"history": {"columns": columns, "data": data}}, ensure_ascii=False).encode("utf-8")
    created = save_raw(path, body, url)
    added[str(path.relative_to(ROOT))] = 1 if created else 0


def _fetch_cbr_macro(client, start: date, end: date, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    key_url = (
        "https://www.cbr.ru/hd_base/keyrate/?UniDbQuery.Posted=True&UniDbQuery.From="
        + start.strftime("%d.%m.%Y")
        + "&UniDbQuery.To="
        + end.strftime("%d.%m.%Y")
    )
    _fetch(client, key_url, RAW / "cbr" / f"keyrate_{stamp}.html", "S2", "key_rate", stamp, added, errors, gaps)
    usd_url = (
        "https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1="
        + start.strftime("%d/%m/%Y")
        + "&date_req2="
        + end.strftime("%d/%m/%Y")
        + "&VAL_NM_RQ=R01235"
    )
    _fetch(client, usd_url, RAW / "cbr" / f"usdrub_{stamp}.xml", "S2", "usdrub", stamp, added, errors, gaps)


def _fetch_metals(client, start: date, end: date, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    allowed, reason = client.check_robots("https://stooq.com/q/d/l/?s=gc.f&i=d")
    if not allowed:
        gaps.append(
            {
                "date": stamp,
                "series": "metals_usd",
                "source": "S4",
                "reason": f"долларовые металлы не скачивались: {reason}. Взяты учётные цены ЦБ в рублях за грамм.",
            }
        )
    else:
        for symbol, name in (("gc.f", "gold"), ("si.f", "silver"), ("pl.f", "platinum"), ("pa.f", "palladium")):
            _fetch(
                client,
                f"https://stooq.com/q/d/l/?s={symbol}&i=d",
                RAW / "stooq" / f"{name}_{stamp}.csv",
                "S4",
                name,
                stamp,
                added,
                errors,
                gaps,
            )
        gaps.append(
            {
                "date": stamp,
                "series": "metals_usd_units",
                "source": "S4",
                "reason": "файлы Stooq сохранены отдельно: колонки gold/silver/platinum/palladium остаются учётными ценами ЦБ в рублях за грамм, чтобы не смешивать единицы",
            }
        )
    url = (
        "https://www.cbr.ru/scripts/xml_metall.asp?date_req1="
        + start.strftime("%d/%m/%Y")
        + "&date_req2="
        + end.strftime("%d/%m/%Y")
    )
    _fetch(client, url, RAW / "cbr" / f"metals_{stamp}.xml", "S2", "metals_rub", stamp, added, errors, gaps)


def _fetch_solar(client, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    _fetch(
        client,
        "https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv",
        RAW / "solar" / f"silso_m_{stamp}.csv",
        "S5",
        "silso_ssn",
        stamp,
        added,
        errors,
        gaps,
    )
    _fetch(
        client,
        "https://www.sidc.be/SILSO/DATA/SN_ms_tot_V2.0.csv",
        RAW / "solar" / f"silso_ms_{stamp}.csv",
        "S5",
        "silso_smooth",
        stamp,
        added,
        errors,
        gaps,
    )
    _fetch(
        client,
        "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json",
        RAW / "solar" / f"noaa_{stamp}.json",
        "S5",
        "noaa",
        stamp,
        added,
        errors,
        gaps,
    )
    _fetch(
        client,
        "https://kp.gfz-potsdam.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt",
        RAW / "solar" / f"gfz_{stamp}.txt",
        "S5",
        "gfz",
        stamp,
        added,
        errors,
        gaps,
    )


def _fetch_weather(client, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    for station, _name in STATIONS:
        _fetch(
            client,
            f"https://bulk.meteostat.net/v2/daily/{station}.csv.gz",
            RAW / "weather" / f"meteostat_{station}_{stamp}.csv.gz",
            "S6",
            station,
            stamp,
            added,
            errors,
            gaps,
        )


def _fetch_news(client, run_day: date, added, errors, gaps):
    stamp = run_day.isoformat()
    _fetch(client, "https://www.cbr.ru/press/keypr/", RAW / "news" / f"{stamp}_cbr_keypr.html", "S8", "cbr_keypr", stamp, added, errors, gaps)
    _fetch(client, "https://www.cbr.ru/dkp/cal_mp/", RAW / "news" / f"{stamp}_cbr_cal_mp.html", "S8", "cbr_calendar", stamp, added, errors, gaps)
    gaps.append(
        {
            "date": stamp,
            "series": "news_archive",
            "source": "S8",
            "reason": f"ленты МосБиржи, РБК, Интерфакса, ТАСС, Forbes и «Эксперта» с {NEWS_START.isoformat()} в этот запуск не снимались: нет одного датированного архива, тон без текста не ставится",
        }
    )


def _fetch_fundamentals(client, run_day: date, added, errors, gaps):
    from scripts.parse_sources import parse_smartlab_html

    stamp = run_day.isoformat()
    tickers = _active_tickers()
    for index, ticker in enumerate(tickers, start=1):
        print(f"fundamentals {index}/{len(tickers)} {ticker}", flush=True)
        for kind in ("y", "q"):
            saved = False
            for report, label in (("MSFO", "IFRS"), ("RSBU", "RAS")):
                path = RAW / "fundamentals" / f"smartlab_{ticker}_{label}_{kind}_{stamp}.html"
                url = f"https://smart-lab.ru/q/{ticker}/f/{kind}/{report}/"
                if path.exists():
                    added[str(path.relative_to(ROOT))] = 0
                    saved = True
                    break
                try:
                    payload = client.get(url, pause=3)
                except Exception as error:  # noqa: BLE001
                    errors.append({"source": "S7", "error": f"{ticker} {label} {kind}: {error}"})
                    continue
                save_raw(path, payload, url)
                added[str(path.relative_to(ROOT))] = 1
                rows = parse_smartlab_html(payload.decode("utf-8", "replace"), label)
                saved = bool(rows)
                if saved:
                    break
            if not saved:
                gaps.append(
                    {
                        "date": stamp,
                        "series": f"{ticker}_{kind}",
                        "source": "S7",
                        "reason": f"отчётность {kind} с {FUNDAMENTALS_FROM} не разобрана или страница недоступна",
                    }
                )
    _fetch(
        client,
        "https://smart-lab.ru/q/shares_fundamental/",
        RAW / "fundamentals" / f"smartlab_table_{stamp}.html",
        "S7",
        "smartlab_table",
        stamp,
        added,
        errors,
        gaps,
        pause=3,
    )
