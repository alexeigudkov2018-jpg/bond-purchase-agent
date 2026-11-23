# Сборщик Альманаха, том 2

Задание: `docs/COLLECTOR_SPEC.md`. Формулы: `docs/METHODS.md`. Открытые вопросы: `docs/QUESTIONS.md`.

Сырьё лежит в `data/raw/` и не перезаписывается. Нормализованные таблицы — `data/clean/`, пересчёт — `data/derived/`. Справочники — `data/reference/`.

Запуск из корня репозитория:

```bash
python scripts/run_collector.py --mode daily
python scripts/run_collector.py --mode weekly
python scripts/run_collector.py --mode monthly
python scripts/run_collector.py --mode quarterly
python scripts/run_collector.py --mode backfill
python -m unittest tests.test_collector_formulas
```

`daily` берёт прошлый будний день. `weekly` обновляет солнце, погоду, дивиденды и статусы. `monthly` замораживает предыдущий месяц. `quarterly` снимает отчётность. `backfill` грузит историю: рынок с 2021-01-04, солнце с 2015-01, погоду с 1991-01.

Тестовый режим не качает историю ISS. Режимы `daily` и `backfill` ходят в публичный JSON `https://iss.moex.com/iss/` и в дневные CSV Stooq без автоматической блокировки по `robots.txt`: пауза не меньше секунды, свой User-Agent. Остальные сайты по-прежнему сверяются с `robots.txt`.
