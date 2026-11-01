"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { mln, num, rub } from "@/lib/utils";

type Dict = Record<string, unknown>;

export function Desk({ report, inputs }: { report: Dict | null; inputs: Dict }) {
  const [data, setData] = useState<Dict | null>(report);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    contribution: String(inputs.contribution ?? 170000),
    available_coupons_alfa: String(inputs.available_coupons_alfa ?? 0),
    available_coupons_sber: String(inputs.available_coupons_sber ?? 0),
    coupons_already_in_cash: Boolean(inputs.coupons_already_in_cash),
    portfolio_value: inputs.portfolio_value == null ? "" : String(inputs.portfolio_value),
    last_week_isins: Array.isArray(inputs.last_week_isins) ? (inputs.last_week_isins as string[]).join(", ") : "",
  });

  async function rebuild(refresh: boolean, withInputs = false) {
    setBusy(refresh ? "Котировки и скринер" : "Пересчёт пакета");
    setError(null);
    const payload: Dict = { refresh };
    if (withInputs) {
      payload.inputs = {
        contribution: Number(form.contribution) || 170000,
        available_coupons_alfa: Number(form.available_coupons_alfa) || 0,
        available_coupons_sber: Number(form.available_coupons_sber) || 0,
        coupons_already_in_cash: form.coupons_already_in_cash,
        portfolio_value: form.portfolio_value === "" ? null : Number(form.portfolio_value),
        positions: Array.isArray(inputs.positions) ? inputs.positions : [],
        last_week_isins: form.last_week_isins.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean),
      };
    }
    try {
      const response = await fetch("/api/package", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await response.json();
      if (!response.ok) throw new Error(json.error || "Сборка не удалась");
      setData(json);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Сборка не удалась");
    } finally {
      setBusy(null);
    }
  }

  if (!data) {
    return (
      <main className="mx-auto max-w-3xl px-5 py-16">
        <p className="text-sm uppercase tracking-[0.18em] text-[#8d4b32]">Вторничный сбор</p>
        <h1 className="mt-3 font-serif text-4xl">Пакет ещё не собран</h1>
        <p className="mt-4 max-w-xl text-[#5c564e]">
          Агент читает Московскую биржу и скринер ДОХОДЪ, затем оставляет только рублёвые фиксированные ОФЗ и корпораты по правилам портфеля.
        </p>
        <Button className="mt-6" onClick={() => rebuild(true)} disabled={Boolean(busy)}>
          {busy || "Собрать пакет"}
        </Button>
        {error && <p className="mt-4 text-sm text-[#8d4b32]">{error}</p>}
      </main>
    );
  }

  const broker = data.broker as Dict;
  const budget = data.budget as Dict;
  const cash = data.cash as Dict;
  const weights = data.weights as Dict;
  const positions = (data.package as Dict[]) || [];
  const calendar = (data.calendar as Dict[]) || [];
  const exceptions = (data.exceptions as Dict[]) || [];
  const waitlist = (data.waitlist as Dict[]) || [];
  const variants = (data.variants as Dict[]) || [];
  const market = (data.market as Dict) || {};
  const rgbi = (market.rgbi as Dict) || {};
  const curve = ((data.market_curve as Dict)?.tenor_ytm as Dict) || {};
  const stocks = (data.stocks as Dict) || {};
  const limits = (data.limits as Dict) || {};
  const tuesday = (data.tuesday as Dict) || {};
  const turnover = (data.turnover as Dict) || {};
  const rejected = (data.rejected_counts as Dict) || {};
  const meets = Boolean(weights.meets_target);
  const unspent = Boolean(cash.unspent_alert);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="flex flex-col gap-6 border-b border-[#d9d0c2] pb-8 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-[#8d4b32]">Каждый вторник, 09:00 МСК</p>
          <h1 className="mt-2 font-serif text-4xl leading-tight sm:text-5xl">Вторничный пакет</h1>
          <p className="mt-3 max-w-xl text-[#5c564e]">
            {String(tuesday.kind || "Расчёт")} {String(tuesday.date || data.asof)}. Брокер {String(broker.name)}, договор {String(broker.agreement)}. Месяц {String(broker.parity)}: ОФЗ, AAA/AA и группа A с госучастием или крупным конгломератом; корпорат только если выгоднее кривой ОФЗ.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => rebuild(false)} disabled={Boolean(busy)}>
            {busy && !busy.includes("Котировки") ? busy : "Пересчитать"}
          </Button>
          <Button variant="copper" onClick={() => rebuild(true)} disabled={Boolean(busy)}>
            {busy && busy.includes("Котировки") ? "Обновляю биржу…" : "Обновить котировки"}
          </Button>
        </div>
      </header>
      {error && <p className="mt-4 text-sm text-[#8d4b32]">{error}</p>}

      <section className="mt-8 grid gap-4 md:grid-cols-4">
        <Stat label="Взнос" value={rub(budget.total as number)} hint={String(budget.extras_note || "")} />
        <Stat
          label="YTM пакета до налога"
          value={`${num(weights.ytm as number)}%`}
          hint={meets ? "Ориентир 16% выполнен" : "Ниже ориентира 16%"}
          tone={meets ? "good" : "warn"}
        />
        <Stat
          label="После НДФЛ 13%"
          value={`${num(weights.ytm_after_tax as number)}%`}
          hint="IRR купонов и дисконта, не YTM минус 13%"
        />
        <Stat
          label="Остаток"
          value={rub(cash.remainder as number)}
          hint={unspent ? "Больше 10% взноса, фильтры не сдвигались" : "В пределах 10%"}
          tone={unspent ? "warn" : "good"}
        />
      </section>

      <section className="mt-10">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-serif text-3xl">К покупке</h2>
          <p className="text-sm text-[#5c564e]">{Number(cash.positions)} из 3 позиций</p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {positions.map((item) => (
            <article key={String(item.secid)} className="rounded-3xl border border-[#e4dccb] bg-white p-5 shadow-[0_1px_0_rgba(26,24,20,0.04)]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(item.slot_title)}</p>
                  <h3 className="mt-1 font-serif text-3xl">{String(item.shortname)}</h3>
                  <p className="text-sm text-[#5c564e]">{String(item.secid)} · {String(item.isin)}</p>
                </div>
                <span className="rounded-full bg-[#e7f3ec] px-3 py-1 text-xs font-medium text-[#1d6b45]">{String(item.verdict)}</span>
              </div>
              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
                <Field label="Количество" value={`${item.qty} шт.`} />
                <Field label="Грязная цена" value={rub(item.dirty as number, 2)} />
                <Field label="Сумма с НКД" value={rub(item.position_sum as number, 2)} />
                <Field label="Комиссия" value={rub(item.commission as number, 2)} />
                <Field label="YTM" value={`${num(item.ytm as number)}%`} />
                <Field label="Дюрация" value={`${num(item.duration_years as number)} лет`} />
                <Field label="До погашения" value={`${num(item.years as number)} лет`} />
                <Field label="Купон" value={`${num(item.coupon_percent as number)}%, ${item.coupon_label}`} />
                <Field label="Текущая доходность" value={`${num(item.current_yield as number)}%`} />
              </dl>
              <p className="mt-4 text-xs leading-5 text-[#6d675e]">
                Цена {num(item.price_pct as number)}% номинала, источник: {String(item.price_source)}
                {item.price_asof ? `, ${item.price_asof}` : ""}. Номинал {rub(item.face as number, 0)}, лот {String(item.lot)}.
                Средний оборот {mln(item.avg_turnover as number)} за {String(item.turnover_sessions)} сессий, медиана {mln(item.median_turnover as number)}.
              </p>
              <p className="mt-2 text-xs leading-5 text-[#6d675e]">
                Посленалоговая YTM {num(item.ytm_after_tax as number)}%. Простое {num(item.naive_ytm_after_13 as number)}% — это YTM × 0,87, его не используем как ответ.
                <a className="ml-2 underline" href={String(item.moex_url)}>Биржа</a>
              </p>
            </article>
          ))}
          {((budget.slots as Dict[]) || [])
            .filter((slot) => !positions.some((item) => item.slot_id === slot.id))
            .map((slot) => (
              <article key={String(slot.id)} className="rounded-3xl border border-dashed border-[#c8b49a] bg-[#fbf6ee] p-5">
                <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(slot.title)}</p>
                <h3 className="mt-1 font-serif text-3xl">Не заполнен</h3>
                <p className="mt-3 text-sm leading-6 text-[#5c564e]">
                  Цель слота {rub(slot.target as number, 0)}. Внутри окна срока и порога 5 баллов подходящей бумаги нет. Фильтр не ослаблялся, деньги слота не перенесены в ОФЗ.
                </p>
                {waitlist.slice(0, 2).map((item) => (
                  <p key={String(item.secid)} className="mt-3 text-sm">
                    <span className="font-medium">{String(item.shortname)}</span>
                    {" "}— {String(item.reason)}. Рейтинг {String(item.rating)}, срок {num(item.years as number)} лет, YTM {num(item.ytm as number)}%.
                  </p>
                ))}
              </article>
            ))}
        </div>
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <h2 className="font-serif text-3xl">Деньги</h2>
          <table className="mt-4 w-full text-sm">
            <tbody>
              <Row label="Взнос" value={rub(budget.contribution as number, 2)} />
              <Row label="Поступления на этот счёт" value={rub(budget.extras as number, 2)} />
              <Row label="Резерв комиссии 0,3%" value={rub(budget.reserve_amount as number, 2)} />
              <Row label={`Фактическая комиссия ${(Number(broker.commission_rate) * 100).toFixed(3)}%`} value={rub(cash.commission as number, 2)} />
              <Row label="Бумаги с НКД" value={rub(cash.spent_dirty as number, 2)} />
              <Row label="Полное списание" value={rub(cash.total_debit as number, 2)} />
              <Row label="Остаток" value={rub(cash.remainder as number, 2)} strong />
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-5 text-[#6d675e]">
            Доли взяты от бюджета после резерва. Бумаги вместе с комиссией помещаются в {rub(budget.total as number, 0)}. Лимит 5% на Минфин не применяется. {String(limits.threshold)}
          </p>
        </div>
        <div>
          <h2 className="font-serif text-3xl">Рынок</h2>
          <div className="mt-4 grid grid-cols-4 gap-2">
            {["2", "5", "10", "15"].map((tenor) => {
              const point = curve[tenor] as Dict | undefined;
              return (
                <div key={tenor} className="rounded-2xl bg-white px-3 py-3 text-center">
                  <p className="text-[11px] uppercase tracking-wider text-[#8a8175]">{tenor} лет</p>
                  <p className="mt-1 font-serif text-xl">{point ? `${num(point.ytm as number)}%` : "—"}</p>
                  {point?.clamped ? <p className="text-[10px] text-[#8d4b32]">край кривой</p> : null}
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-sm leading-6 text-[#5c564e]">
            Кривая — YTM фиксированных ОФЗ со средним оборотом от 20 млн ₽, интерполяция по сроку до погашения. G-спред корпоратов считается отдельно, по дюрации, через numpy.interp. Точек на кривой спреда: {String((data.market_curve as Dict)?.g_spread_points)}.
          </p>
          <p className="mt-2 text-sm leading-6 text-[#5c564e]">
            RGBI {rgbi.last ? `${num(rgbi.last as number)} на ${rgbi.last_date}` : "не загружен"}
            {rgbi.week_ago ? `, неделей ранее ${num(rgbi.week_ago as number)} (${rgbi.week_ago_date}), ${num(rgbi.change_pct as number)}%` : ""}.
            {" "}{String((market.cbr as Dict)?.status || "")}.
          </p>
        </div>
      </section>

      {Boolean(stocks.first_tuesday) && (
        <section className="mt-8 rounded-3xl bg-[#1a1814] px-5 py-5 text-[#f6f1e7]">
          <p className="text-xs uppercase tracking-[0.16em] text-[#e2b5a4]">Первый вторник месяца</p>
          <h2 className="mt-1 font-serif text-2xl">Акции остаются на паузе</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#ddd6cb]">{String(stocks.reason)} {String(stocks.dividend_block || "")}</p>
        </section>
      )}

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Купоны на 12 месяцев</h2>
        <p className="mt-2 text-sm text-[#5c564e]">Только будущие даты из графика MOEX. Из НКД календарь не восстанавливался.</p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
              <tr>
                <th className="py-2 font-medium">Месяц</th>
                <th className="py-2 font-medium">ОФЗ</th>
                <th className="py-2 font-medium">Корпораты</th>
                <th className="py-2 font-medium">Итого</th>
              </tr>
            </thead>
            <tbody>
              {calendar.filter((row) => Number(row.total) > 0).map((row) => (
                <tr key={String(row.month)} className="border-t border-[#eadfce]">
                  <td className="py-2">{String(row.month)}</td>
                  <td className="py-2">{rub(row.ofz as number, 2)}</td>
                  <td className="py-2">{rub(row.corporate as number, 2)}</td>
                  <td className="py-2 font-medium">{rub(row.total as number, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Исключение по сроку AAA/AA</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#5c564e]">
          Короткие AAA/AA не покупаются сами. Все сопоставимые выпуски лежат в одном списке: и ФосАгро, и остальные. Отклонить одну бумагу только из‑за срока и тут же сделать исключение другой нельзя.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
              <tr>
                <th className="py-2 pr-3 font-medium">Выпуск</th>
                <th className="py-2 pr-3 font-medium">Агентство</th>
                <th className="py-2 pr-3 font-medium">Скринер</th>
                <th className="py-2 pr-3 font-medium">Срок</th>
                <th className="py-2 pr-3 font-medium">Дюрация</th>
                <th className="py-2 pr-3 font-medium">YTM</th>
                <th className="py-2 pr-3 font-medium">G-спред</th>
                <th className="py-2 pr-3 font-medium">Балл</th>
                <th className="py-2 pr-3 font-medium">Оборот, среднее</th>
                <th className="py-2 font-medium">Медиана ДОХОДЪ</th>
              </tr>
            </thead>
            <tbody>
              {exceptions.map((item) => (
                <tr key={String(item.isin)} className="border-t border-[#eadfce] align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{String(item.shortname)}</div>
                    <div className="text-xs text-[#6d675e]">{String(item.issuer)}</div>
                  </td>
                  <td className="py-2 pr-3">{String(item.rating || "—")} {item.rating_date ? <span className="block text-xs text-[#6d675e]">{String(item.rating_date)}</span> : null}</td>
                  <td className="py-2 pr-3">{String(item.screener_rating || "—")}</td>
                  <td className="py-2 pr-3">{num(item.years as number)} лет</td>
                  <td className="py-2 pr-3">{num(item.duration_years as number)}</td>
                  <td className="py-2 pr-3">{num(item.ytm as number)}%</td>
                  <td className="py-2 pr-3">{item.g_spread_bp == null ? "—" : `${num(item.g_spread_bp as number, 0)} б.п.`}</td>
                  <td className="py-2 pr-3">{num(item.score as number, 1)}</td>
                  <td className="py-2 pr-3">{mln(item.avg_turnover as number)}</td>
                  <td className="py-2">{mln(item.dohod_median_turnover as number)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {variants.length > 0 && (
        <section className="mt-10">
          <h2 className="font-serif text-3xl">Что не вошло в пакет</h2>
          <ul className="mt-4 space-y-3">
            {variants.map((item) => (
              <li key={String(item.title)} className="rounded-2xl bg-white px-4 py-3">
                <p className="font-medium">{String(item.title)}</p>
                <p className="mt-1 text-sm leading-6 text-[#5c564e]">{String(item.detail)}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="font-serif text-3xl">Откуда цифры</h2>
          <ul className="mt-4 space-y-2 text-sm leading-6 text-[#5c564e]">
            <li>Порог ликвидности — {String(turnover.metric)} за {String(turnover.session_count)} торговых дней. Пропуск равен нулю. Медиана скринера ДОХОДЪ в порог не подставляется.</li>
            <li>Баллы корпоратов: G-спред к кривой ОФЗ, кредитное качество и качество эмитента из скринера вместо долга/EBITDA и покрытия процентов. NetDebt/Equity не используется.</li>
            <li>Свежесть рейтинга берётся из даты на карточке, которая ссылается на АКРА или Эксперт РА. Сайт агентства в этом прогоне отдельно не открывался, если дата уже есть в карточке.</li>
            <li>{String(data.execution_log)}</li>
            <li>{String((data.sources as Dict)?.note || "")}</li>
          </ul>
          <h3 className="mt-6 font-medium">Почему остальные выпуски отсеялись</h3>
          <ul className="mt-2 space-y-1 text-sm text-[#5c564e]">
            {Object.entries(rejected).map(([reason, count]) => (
              <li key={reason}>{count as number} — {reason}</li>
            ))}
          </ul>
        </div>
        <form
          className="rounded-3xl border border-[#e4dccb] bg-white p-5"
          onSubmit={(event) => {
            event.preventDefault();
            rebuild(false, true);
          }}
        >
          <h2 className="font-serif text-3xl">Уточнить вводные</h2>
          <p className="mt-2 text-sm text-[#5c564e]">Взнос сам не растёт. Купоны Альфы не считаются деньгами Сбера.</p>
          <label className="mt-4 block text-sm">Взнос, ₽
            <Input className="mt-1" value={form.contribution} onChange={(event) => setForm({ ...form, contribution: event.target.value })} />
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-sm">Купоны Альфы, ₽
              <Input className="mt-1" value={form.available_coupons_alfa} onChange={(event) => setForm({ ...form, available_coupons_alfa: event.target.value })} />
            </label>
            <label className="text-sm">Купоны Сбера, ₽
              <Input className="mt-1" value={form.available_coupons_sber} onChange={(event) => setForm({ ...form, available_coupons_sber: event.target.value })} />
            </label>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.coupons_already_in_cash} onChange={(event) => setForm({ ...form, coupons_already_in_cash: event.target.checked })} />
            Поступления уже сидят в названном остатке
          </label>
          <label className="mt-3 block text-sm">Стоимость обычных счетов, ₽
            <Input className="mt-1" placeholder="пусто — порог 15 млн не проверен" value={form.portfolio_value} onChange={(event) => setForm({ ...form, portfolio_value: event.target.value })} />
          </label>
          <label className="mt-3 block text-sm">ISIN покупок прошлой недели
            <Input className="mt-1" placeholder="RU000A… через запятую" value={form.last_week_isins} onChange={(event) => setForm({ ...form, last_week_isins: event.target.value })} />
          </label>
          <Button className="mt-4" type="submit" disabled={Boolean(busy)}>Пересчитать с этими вводными</Button>
        </form>
      </section>

      <footer className="mt-12 border-t border-[#d9d0c2] pt-6 text-sm leading-6 text-[#6d675e]">
        {String(data.disclaimer)} Цены, количества и комиссии предварительные. Это не поручение брокеру.
        Скринер: <a className="underline" href="https://www.dohod.ru/analytic/bonds">dohod.ru/analytic/bonds</a>.
      </footer>
    </main>
  );
}

function Stat({ label, value, hint, tone = "ink" }: { label: string; value: string; hint: string; tone?: "ink" | "good" | "warn" }) {
  const color = tone === "good" ? "text-[#1d6b45]" : tone === "warn" ? "text-[#8d4b32]" : "text-[#1a1814]";
  return (
    <div className="rounded-3xl bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-[0.14em] text-[#8a8175]">{label}</p>
      <p className={`mt-2 font-serif text-3xl ${color}`}>{value}</p>
      <p className="mt-2 text-xs leading-5 text-[#6d675e]">{hint}</p>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-[#8a8175]">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <tr className="border-t border-[#eadfce]">
      <td className={`py-2 ${strong ? "font-medium" : ""}`}>{label}</td>
      <td className={`py-2 text-right ${strong ? "font-medium" : ""}`}>{value}</td>
    </tr>
  );
}
