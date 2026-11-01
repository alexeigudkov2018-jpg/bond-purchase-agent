"""Собрать вторничный пакет и записать data/latest_package.json.

Запуск из корня репозитория: python -m engine
Повторный запуск в тот же торговый день берёт кэш биржи, если не передан --refresh.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.corpbonds import CorpBonds
from engine.dohod import blocker as dohod_blocker
from engine.dohod import group_from_text, load_index
from engine.moex import (
    effective_yield,
    is_fixed_coupon,
    is_rub,
    last_trading_sessions,
    listed_offer,
    load_universe,
    map_turnover,
    rgbi_history,
    to_maturity,
    years_to,
)
from engine.rules import CONTRIBUTION_RUB, TURNOVER_SESSIONS
from engine.select import _corp_structural, _ofz_hard, build_package, load_screener

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"
MSK = ZoneInfo("Europe/Moscow")


def moscow_now() -> datetime:
    return datetime.now(MSK)


def load_inputs() -> dict:
    path = DATA / "inputs.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def extras_for(broker_id: str, inputs: dict) -> tuple[float, str]:
    if inputs.get("coupons_already_in_cash"):
        return 0.0, "Поступления не добавлены: они уже входят в названный свободный остаток."
    key = "available_coupons_alfa" if broker_id == "alfa" else "available_coupons_sber"
    amount = float(inputs.get(key) or 0)
    if amount <= 0:
        return 0.0, "Купоны, дивиденды и погашения к взносу не добавлены: по этому счёту они не переданы."
    other = "Сбера" if broker_id == "alfa" else "Альфы"
    return amount, f"К взносу добавлены {amount:,.2f} ₽ поступлений этого счёта. Деньги {other} не использовались."


def losing_isins(positions: list[dict]) -> set[str]:
    found = set()
    for row in positions:
        isin = (row.get("isin") or "").upper()
        bought = row.get("avg_price")
        current = row.get("current_price")
        if isin and bought not in (None, "") and current not in (None, "") and float(current) < float(bought):
            found.add(isin)
    return found


def attach_dohod(bonds: list[dict], index: dict[str, dict]) -> None:
    for bond in bonds:
        isin = (bond.get("ISIN") or "").upper()
        bond["dohod"] = index.get(isin)


def prepare_universe(refresh: bool, asof: date, dohod_index: dict[str, dict]) -> tuple[dict, list[str], str]:
    cache_path = CACHE / f"universe-{asof.isoformat()}.json"
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        attach_dohod(cached["universe"]["TQOB"] + cached["universe"]["TQCB"], dohod_index)
        return cached["universe"], cached["sessions"], cached["fetched_at"]

    print("Загружаю доски TQOB и TQCB…", file=sys.stderr)
    raw = load_universe()
    sessions = last_trading_sessions(count=TURNOVER_SESSIONS)
    ofz = [row for row in raw["TQOB"] if _ofz_hard(row)]
    corp = []
    for row in raw["TQCB"]:
        if not _corp_structural(row, asof):
            continue
        if effective_yield(row) is None and not (row.get("market") or {}).get("VALTODAY"):
            continue
        corp.append(row)
    attach_dohod(ofz + corp, dohod_index)
    print(f"Считаю средний оборот: ОФЗ {len(ofz)}, корпораты {len(corp)}, сессий {len(sessions)}", file=sys.stderr)
    map_turnover(ofz + corp, sessions)
    liquid = []
    for row in corp:
        mean = (row.get("turnover") or {}).get("mean")
        if not mean or mean < 5_000_000:
            continue
        if dohod_blocker(row.get("dohod")):
            continue
        if group_from_text((row.get("dohod") or {}).get("credit_rating_text")) == "below":
            continue
        liquid.append(row)
    print(f"Карточки рейтинга для {len(liquid)} ликвидных корпоратов…", file=sys.stderr)
    CorpBonds(CACHE / "corpbonds").enrich(liquid)
    universe = {"TQOB": ofz, "TQCB": corp}
    fetched_at = datetime.now(timezone.utc).isoformat()
    CACHE.mkdir(parents=True, exist_ok=True)
    stored = {
        "TQOB": [{key: value for key, value in bond.items() if key != "dohod"} for bond in ofz],
        "TQCB": [{key: value for key, value in bond.items() if key != "dohod"} for bond in corp],
    }
    cache_path.write_text(
        json.dumps({"universe": stored, "sessions": sessions, "fetched_at": fetched_at}, ensure_ascii=False),
        encoding="utf-8",
    )
    return universe, sessions, fetched_at


def market_block(asof: date) -> dict:
    start = asof - timedelta(days=21)
    try:
        rows = rgbi_history(start, asof)
    except Exception as error:
        return {"rgbi": {"status": "не загружен", "error": str(error)}, "cbr": _cbr_note()}
    if len(rows) < 2:
        return {"rgbi": {"status": "мало точек"}, "cbr": _cbr_note()}
    last = rows[-1]
    week = rows[-6] if len(rows) >= 6 else rows[0]
    change = (last["close"] - week["close"]) / week["close"] * 100
    return {
        "rgbi": {
            "status": "загружен",
            "last": last["close"],
            "last_date": last["date"],
            "week_ago": week["close"],
            "week_ago_date": week["date"],
            "change_pct": round(change, 2),
            "source": "MOEX ISS индекс RGBI, режим SNDX",
        },
        "cbr": _cbr_note(),
        "defaults": {
            "status": "в этом прогоне лента дефолтов и реструктуризаций не загружалась",
            "url": "https://www.moex.com/a1791",
        },
        "rating_actions": {
            "status": "отдельная лента рейтинговых действий не загружалась; даты рейтингов есть только у бумаг, дошедших до карточки",
            "url": "https://www.acra-ratings.ru/ratings/issuers/",
        },
        "primary": {
            "status": "календарь первичных размещений в прогон не входил",
            "url": "https://www.moex.com/s14",
        },
    }


def _cbr_note() -> dict:
    return {
        "status": "решение и дата заседания в этом прогоне не подтверждались запросом к сайту ЦБ",
        "url": "https://www.cbr.ru/hd_base/keyrate/",
        "calendar_url": "https://www.cbr.ru/dkp/mp_dec/",
    }


def stocks_block(asof: date, portfolio_value: float | None, inputs: dict | None = None) -> dict:
    first_tuesday = _is_first_tuesday(asof)
    inputs = inputs or {}
    target = float(inputs.get("stocks_target_max") or 0.10)
    pause = bool(inputs.get("stocks_pause", True))
    share = inputs.get("stocks_share")
    stocks_value = inputs.get("stocks_value")
    share_known = share is not None
    if share_known:
        share = float(share)
        stocks_value = None if stocks_value is None else float(stocks_value)
        pct = round(share * 100, 1)
        target_pct = round(target * 100, 1)
        if pause or share > target:
            reason = (
                f"Покупки акций на паузе. Доля акций в объединённом портфеле {pct}% "
                f"при потолке {target_pct}%. 1 ноября пользователь зафиксировал текущие позиции: "
                "новые акции не докупаем, снижение доли идёт пополнениями в облигации."
            )
            pause = True
        else:
            reason = (
                f"Доля акций {pct}% не выше потолка {target_pct}%. "
                "Вторничный пакет по-прежнему собирается только из облигаций."
            )
    else:
        reason = (
            "Покупки акций на паузе. Фактическая доля акций в объединённом портфеле не передана, "
            "поэтому пауза не снимается. Долгосрочная цель по акциям — до 10%, снижение доли идёт "
            "пополнениями в облигации."
        )
        pause = True
    return {
        "first_tuesday": first_tuesday,
        "pause": pause,
        "share_known": share_known,
        "share": share,
        "stocks_value": stocks_value,
        "target_max": target,
        "reason": reason,
        "included_in_package": False,
        "portfolio_value": portfolio_value,
        "dividend_block": "Выгрузка акций и дивидендов не приложена." if first_tuesday else None,
    }


def _is_first_tuesday(day: date) -> bool:
    if day.weekday() != 1:
        return False
    return day.day <= 7


def screener_note() -> dict:
    uploads = sorted(path.name for path in (ROOT / "uploads").glob("*") if path.is_file())
    screener = sorted(path.name for path in (DATA / "screener").glob("*.csv"))
    return {
        "uploads": uploads,
        "screener_files": screener,
        "note": (
            "Проверены папка data/screener, вложения uploads и живой скринер ДОХОДЪ. "
            + ("Локального CSV нет. " if not screener else "Локальный CSV прочитан и перекрывает одноимённые коэффициенты. ")
            + "Чистый долг/EBITDA и покрытие процентов в скринере не публикуются, NetDebt/Equity в баллы не берётся."
        ),
    }


def tuesday_label(now: datetime) -> dict:
    today = now.date()
    if today.weekday() == 1:
        return {"date": today.isoformat(), "kind": "текущий вторник", "preliminary": False}
    days_ahead = (1 - today.weekday()) % 7
    nxt = today + timedelta(days=days_ahead or 7)
    return {"date": nxt.isoformat(), "kind": "предварительный пакет к следующему вторнику", "preliminary": True}


def render_text(report: dict) -> str:
    broker = report["broker"]
    cash = report["cash"]
    weights = report["weights"]
    lines = [
        f"{report['tuesday']['kind']}: {report['tuesday']['date']}",
        f"Брокер: {broker['name']}, договор {broker['agreement']}, комиссия {broker['commission_rate'] * 100:.3f}%",
        f"Бюджет {report['budget']['total']:.2f} ₽, потолок бумаг {report['budget']['securities_cap']:.2f} ₽",
        f"Позиций: {cash['positions']}. Списание {cash['total_debit']:.2f} ₽, остаток {cash['remainder']:.2f} ₽",
        f"Средневзвешенная YTM {weights.get('ytm')}% при цели {report['target_ytm']}%. Посленалоговая {weights.get('ytm_after_tax')}%",
        "",
    ]
    for item in report["package"]:
        lines.append(
            f"[{item['verdict']}] {item['slot_title']}: {item['shortname']} {item['secid']} "
            f"{item['qty']} шт. × {item['dirty']:.2f} = {item['position_sum']:.2f} ₽, "
            f"комиссия {item['commission']:.2f}, YTM {item['ytm']}%"
        )
    if report["cash"]["unspent_alert"]:
        lines.append("Остаток больше 10% бюджета.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Вторничный пакет ОФЗ и корпоративных облигаций")
    parser.add_argument("--refresh", action="store_true", help="заново запросить биржу и карточки")
    parser.add_argument("--date", help="дата расчёта YYYY-MM-DD, по умолчанию сегодня по Москве")
    args = parser.parse_args()
    now = moscow_now()
    asof = date.fromisoformat(args.date) if args.date else now.date()
    inputs = load_inputs()
    print("Загружаю скринер ДОХОДЪ…", file=sys.stderr)
    dohod_index, dohod_at = load_index(CACHE / "dohod.json", refresh=args.refresh)
    universe, sessions, fetched_at = prepare_universe(args.refresh, asof, dohod_index)
    # Брокер нужен до бюджета, чтобы взять поступления нужного счёта.
    from engine.rules import broker_for_month

    broker = broker_for_month(asof.month)
    extras, extras_note = extras_for(broker["id"], inputs)
    contribution = float(inputs.get("contribution") or CONTRIBUTION_RUB)
    budget = contribution + extras
    positions = list(inputs.get("positions") or [])
    portfolio_value = inputs.get("portfolio_value")
    if portfolio_value is not None:
        portfolio_value = float(portfolio_value)
    last_week = {isin.upper() for isin in inputs.get("last_week_isins") or []}
    report = build_package(
        universe=universe,
        sessions=sessions,
        asof=asof,
        budget=budget,
        extras=extras,
        extras_note=extras_note,
        screener=load_screener(DATA / "screener"),
        positions=positions,
        portfolio_value=portfolio_value,
        last_week_isins=last_week,
        losing_isins=losing_isins(positions),
    )
    report["generated_at"] = now.isoformat()
    report["quotes_fetched_at"] = fetched_at
    report["dohod"] = {
        "url": "https://www.dohod.ru/analytic/bonds",
        "fetched_at": dohod_at,
        "rows": len(dohod_index),
        "turnover_metric": "vol_median — медиана дневного оборота, млн ₽; в порог 5 млн не подставляется",
        "scores": "кредитное качество и качество эмитента из скринера заменяют долг/EBITDA и покрытие процентов",
    }
    report["tuesday"] = tuesday_label(now) if not args.date else {
        "date": asof.isoformat(),
        "kind": "расчёт на указанную дату",
        "preliminary": asof.weekday() != 1,
    }
    report["schedule"] = "каждый вторник в 09:00 МСК"
    report["market"] = market_block(asof)
    report["stocks"] = stocks_block(asof, portfolio_value, inputs)
    report["sources"] = screener_note()
    report["execution_log"] = (
        "Журнал исполненных пакетов пуст. Запрет повтора выпусков прошлой недели нечем подтвердить."
        if not last_week else "Повтор выпусков из переданного списка прошлой недели запрещён."
    )
    report["disclaimer"] = (
        "Это не индивидуальная инвестиционная рекомендация. "
        "Цены, количества, НКД и комиссии предварительные и не заменяют брокерский отчёт. "
        "Цель 16% — ориентир отбора, не гарантия доходности."
    )
    # Внутренний объект бумаги в JSON не кладём.
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "latest_package.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    runs = DATA / "runs"
    runs.mkdir(exist_ok=True)
    (runs / f"{asof.isoformat()}.json").write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print(render_text(report))
    print(f"\nЗаписано {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
