# DERIVATIVES / FUTURES RADAR · утро 07:30 + вечер 19:00 МСК

**Готовые тексты для копирования:**

| Слот | Москва | Cron (UTC) | Файл промпта |
|---|---|---|---|
| Утро | **07:30** | `30 4 * * *` | [`derivatives-radar-morning-ru.md`](derivatives-radar-morning-ru.md) |
| Вечер | **19:00** | `0 16 * * *` | [`derivatives-radar-evening-ru.md`](derivatives-radar-evening-ru.md) |

Две автоматизации, в каждой один cron.

## Журнал

- `data/derivatives-journal.md` — OPEN/PLAN ядра
- `data/derivatives-account.json` — только `max_core_pairs` (по умолчанию 5)

**ГО агент не считает** и из-за маржи сделки не режет: полный список проверенных пар + блок ЯДРО. Маржу считаете вы.

**Утро → вечер:** все сделки/ЯДРО утра вечером обязательно пересчитываются (ДЕРЖАТЬ/ВЫХОДИТЬ/СОКРАТИТЬ). Утро пишет их в `data/derivatives-journal.md`; вечер не подменяет утро новым сканом.
