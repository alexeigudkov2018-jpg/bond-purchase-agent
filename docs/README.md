# Сборщик Альманаха, том 2

Задание: `docs/COLLECTOR_SPEC.md`. Формулы: `docs/METHODS.md`. Открытые вопросы: `docs/QUESTIONS.md`.

Сырьё лежит в `data/raw/` и не перезаписывается. Нормализованные таблицы — `data/clean/`, пересчёт — `data/derived/`. Справочники — `data/reference/`.

Тестовый запуск из корня репозитория:

```bash
python scripts/run_collector.py --mode test
python -m unittest tests.test_collector_formulas
```

Тестовый режим качает только источники, которые не запрещены их `robots.txt`. На 2026-11-23 ISS закрыт `Disallow: /`, поэтому ценовые таблицы остаются пустыми, а пропуск пишется в `logs/gaps.csv`.
