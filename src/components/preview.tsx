import { mln, num, rub } from "@/lib/utils";

type Dict = Record<string, unknown>;

export function Preview({ report }: { report: Dict | null }) {
  if (!report) return null;
  const broker = report.broker as Dict;
  const budget = report.budget as Dict;
  const cash = report.cash as Dict;
  const weights = report.weights as Dict;
  const positions = (report.package as Dict[]) || [];
  const slots = (budget.slots as Dict[]) || [];
  const waitlist = (report.waitlist as Dict[]) || [];
  const exceptions = (report.exceptions as Dict[]) || [];
  const rejected = (report.rejected as Dict[]) || [];
  const curve = (report.curve as Dict) || {};
  const tenor = (curve.tenor_ytm as Dict) || {};
  const repeat = (report.repeat as Dict) || {};
  const alternate = (report.alternate_if_already_bought as Dict) || {};
  const alternateRows = (alternate.package as Dict[]) || [];
  const alternateWeights = (alternate.weights as Dict) || {};
  const variants = (report.variants as Dict[]) || [];
  const caveats = (report.caveats as string[]) || [];
  const limits = (report.limits as Dict) || {};
  const counts = (report.rejected_counts as Dict) || {};
  const ofz = (report.ofz as Dict[]) || [];
  const focus = (report.focus as Dict) || null;
  const focusRows = ((focus?.rows as Dict[]) || []);
  const meets = Boolean(weights.meets_target);
  const unspent = Boolean(cash.unspent_alert);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="border-b border-[#d9d0c2] pb-8">
        <p className="text-xs uppercase tracking-[0.22em] text-[#8d4b32]">Выгрузка ДОХОДЪ · предварительно</p>
        <h1 className="mt-2 font-serif text-4xl leading-tight sm:text-5xl">Пакет на 170 000 ₽</h1>
        <p className="mt-3 max-w-3xl text-[#5c564e]">
          {report.full_ofz
            ? String(report.order_note)
            : `Расчёт на вторник ${String(report.tuesday)} для ${String(broker.name)}, соглашение ${String(broker.agreement)}. Октябрь чётный: ОФЗ 65% двумя выпусками, корпорат — одна позиция A и выше на 35%. Котировки взяты из двух книг скринера. Дата доходности в файлах стоит прочерком.`}
        </p>
      </header>

      <section className="mt-8 grid gap-4 md:grid-cols-4">
        <Stat label="Взнос" value={rub(budget.total as number)} hint="Купоны сверху не добавлялись" />
        <Stat
          label="YTM до налога"
          value={`${num(weights.ytm as number)}%`}
          hint={weights.ytm_after_tax != null ? `После налога ${num(weights.ytm_after_tax as number)}%. ${meets ? "Ориентир 16% выполнен" : "Ниже ориентира 16%"}` : meets ? "Ориентир 16% выполнен" : "Ниже ориентира 16%"}
          tone={meets ? "good" : "warn"}
        />
        <Stat
          label="Дюрация пакета"
          value={`${num(weights.duration_years as number)} лет`}
          hint="Взвешена по сумме с НКД"
        />
        <Stat
          label="Остаток"
          value={rub(cash.remainder as number, report.full_ofz ? 2 : 0)}
          hint={report.full_ofz ? "Весь взнос в двух ОФЗ, остаток меньше одной бумаги" : unspent ? `${num((cash.remainder_pct as number) * 100, 1)}% взноса. Фильтры не сдвигались` : "В пределах 10%"}
          tone={report.full_ofz || !unspent ? "good" : "warn"}
        />
      </section>

      <section className="mt-10">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-serif text-3xl">К покупке</h2>
          <p className="text-sm text-[#5c564e]">{report.full_ofz ? "Две позиции на весь взнос" : `${Number(cash.positions)} из 3 позиций`}</p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {positions.map((item) => (
            <article key={String(item.isin)} className="rounded-3xl border border-[#e4dccb] bg-white p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(item.slot_title)}</p>
                  <h3 className="mt-1 font-serif text-3xl">{String(item.shortname)}</h3>
                  <p className="text-sm text-[#5c564e]">{String(item.isin)}</p>
                </div>
                <span className="rounded-full bg-[#e7f3ec] px-3 py-1 text-xs font-medium text-[#1d6b45]">{report.full_ofz ? "к покупке" : "предварительно"}</span>
              </div>
              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
                <Field label="Количество" value={`${item.qty} шт.`} />
                <Field label="Грязная цена" value={rub(item.dirty as number, 2)} />
                <Field label="Сумма с НКД" value={rub(item.position_sum as number, 2)} />
                <Field label="Комиссия 0,291%" value={rub(item.commission as number, 2)} />
                <Field label="Списание" value={rub(item.debit as number, 2)} />
                <Field label="YTM" value={`${num(item.ytm as number)}%`} />
                <Field label="Дюрация" value={`${num(item.duration as number)} лет`} />
                <Field label="До погашения" value={`${num(item.years as number)} лет`} />
                <Field label="Купон" value={`${num(item.coupon_percent as number)}%, ${item.coupon_label}`} />
                <Field label="Текущая доходность" value={`${num(item.current_yield as number)}%`} />
                <Field label="Купон в год на позицию" value={rub(item.annual_coupon_position as number, 0)} />
                <Field label="Медиана оборота" value={`${num(item.median_mln as number, 0)} млн ₽`} />
              </dl>
              <p className="mt-4 text-xs leading-5 text-[#6d675e]">
                Цена {num(item.price as number, 3)}% номинала, НКД {rub(item.nkd as number, 2)}. Номинал {rub(item.face as number, 0)}, лот {String(item.lot)} бумага.
                Погашение {String(item.maturity)}. {item.price_asof ? `Цена биржи на ${String(item.price_asof)}.` : "Источник цены: выгрузка, без даты расчёта."}
                {item.ytm_after_tax != null ? ` После налога ${num(item.ytm_after_tax as number)}%.` : ""}
              </p>
            </article>
          ))}
          {report.full_ofz ? (
            <article className="rounded-3xl border border-[#e4dccb] bg-[#fbf6ee] p-5 lg:col-span-2">
              <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">Слот корпората на этот вторник</p>
              <h3 className="mt-1 font-serif text-3xl">Отдан двум ОФЗ</h3>
              <p className="mt-3 text-sm leading-6 text-[#5c564e]">
                ФосАгро и выпуски ПСБ в эту заявку не вошли: срок короче четырёх лет, доходность ниже ОФЗ. Деньги слота добавлены к 26238 и 26230. Это решение на 20 октября, норма 65/35 на следующие вторники не меняется.
              </p>
            </article>
          ) : null}
          {!report.full_ofz && slots.filter((slot) => !positions.some((item) => item.slot_id === slot.id)).map((slot) => (
            <article key={String(slot.id)} className="rounded-3xl border border-dashed border-[#c8b49a] bg-[#fbf6ee] p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(slot.title)}</p>
              <h3 className="mt-1 font-serif text-3xl">Не заполнен</h3>
              <p className="mt-3 text-sm leading-6 text-[#5c564e]">
                Цель слота {rub(slot.target as number, 0)}. Внутри окна срока балл ниже 5, эти выпуски ниже. Короткие AAA/AA в пакет не переносятся.
              </p>
              {waitlist.map((item) => (
                <p key={String(item.isin)} className="mt-3 text-sm leading-6">
                  <span className="font-medium">{String(item.shortname)}</span>
                  {" "}— {String(item.reason)} Срок {num(item.years as number)} лет, дюрация {num(item.duration as number)}, YTM {num(item.ytm as number)}%, G-спред {num(item.g_spread_bp as number, 0)} б.п.{item.g_spread_clamped ? " с края кривой" : ""}.
                </p>
              ))}
            </article>
          ))}
        </div>
      </section>

      {focus && (
        <section className="mt-10">
          <h2 className="font-serif text-3xl">{String(focus.title)}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#5c564e]">{String(focus.summary)} Сверка на {String(focus.checked_at)}. Рейтинг — с агрегатора, страница агентства сегодня не открывалась. G-спред посчитан по дюрации биржи и кривой ОФЗ со средним оборотом от 20 млн.</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
                <tr>
                  <th className="py-2 pr-3 font-medium">Выпуск</th>
                  <th className="py-2 pr-3 font-medium">Вердикт</th>
                  <th className="py-2 pr-3 font-medium">YTM биржи</th>
                  <th className="py-2 pr-3 font-medium">Срок</th>
                  <th className="py-2 pr-3 font-medium">Балл</th>
                  <th className="py-2 font-medium">Средний оборот</th>
                </tr>
              </thead>
              <tbody>
                {focusRows.map((item) => (
                  <tr key={String(item.isin)} className="border-t border-[#eadfce] align-top">
                    <td className="py-2 pr-3">
                      <div className="font-medium">{String(item.shortname)}</div>
                      <div className="text-xs text-[#6d675e]">{String(item.reason)}</div>
                    </td>
                    <td className="py-2 pr-3">{String(item.verdict)}</td>
                    <td className="py-2 pr-3">{num(item.ytm as number)}%</td>
                    <td className="py-2 pr-3">{num(item.years as number)} лет</td>
                    <td className="py-2 pr-3">{num(item.score as number, 1)}</td>
                    <td className="py-2">{mln(item.mean_turnover as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <h2 className="font-serif text-3xl">Деньги</h2>
          <table className="mt-4 w-full text-sm">
            <tbody>
              <Row label="Взнос" value={rub(budget.contribution as number, 2)} />
              <Row label="Резерв комиссии 0,3%" value={rub(budget.reserve_amount as number, 2)} />
              <Row label="Потолок бумаг" value={rub(budget.securities_cap as number, 2)} />
              <Row label="Бумаги с НКД" value={rub(cash.spent_dirty as number, 2)} />
              <Row label="Комиссия Альфы 0,291%" value={rub(cash.commission as number, 2)} />
              <Row label="Полное списание" value={rub(cash.total_debit as number, 2)} />
              <Row label="Остаток" value={rub(cash.remainder as number, 2)} strong />
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-5 text-[#6d675e]">
            Потолок бумаг — минимум из взноса после резерва 0,3% и взноса, делённого на 1 + 0,291%. {String(limits.issuer)} {String(broker.account)}
          </p>
        </div>
        <div>
          <h2 className="font-serif text-3xl">Кривая ОФЗ</h2>
          <div className="mt-4 grid grid-cols-4 gap-2">
            {["2", "5", "10", "15"].map((tenorKey) => {
              const point = tenor[tenorKey] as Dict | undefined;
              return (
                <div key={tenorKey} className="rounded-2xl bg-white px-3 py-3 text-center">
                  <p className="text-[11px] uppercase tracking-wider text-[#8a8175]">{tenorKey} лет</p>
                  <p className="mt-1 font-serif text-xl">{point ? `${num(point.ytm as number)}%` : "—"}</p>
                  {point?.clamped ? <p className="text-[10px] text-[#8d4b32]">край кривой</p> : null}
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-sm leading-6 text-[#5c564e]">{String(curve.tenor_note)}</p>
          <p className="mt-2 text-sm leading-6 text-[#5c564e]">
            {String(curve.method)} Точек: {String(curve.points)}, дюрация от {num(curve.duration_min as number)} до {num(curve.duration_max as number)} лет.
          </p>
        </div>
      </section>

      <section className="mt-8 rounded-3xl bg-[#1a1814] px-5 py-5 text-[#f6f1e7]">
        <p className="text-xs uppercase tracking-[0.16em] text-[#e2b5a4]">Совпадение с черновиком 6 октября</p>
        <h2 className="mt-1 font-serif text-2xl">26238 и 26230 уже могли быть куплены</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#ddd6cb]">{String(repeat.note)}</p>
        {alternateRows.length > 0 && (
          <p className="mt-3 text-sm leading-6 text-[#ddd6cb]">
            Запасная пара по той же дюрации: {alternateRows.map((item) => `${item.shortname} · ${item.qty} шт. · ${rub(item.position_sum as number, 0)}`).join("; ")}.
            Взвешенная YTM {num(alternateWeights.ytm as number)}%, дюрация {num(alternateWeights.duration_years as number)} лет.
            Ориентир 16% {alternateWeights.meets_target ? "выполнен" : "не выполнен"}.
          </p>
        )}
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Короткие AAA/AA</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#5c564e]">
          В пакет они не входят. Срок короче четырёх лет один и тот же для всей таблицы, включая ФосАгро. Буква агентства, где она есть, взята из карточек прогона 6 октября. Кратчайшая дюрация ОФЗ в кривой файла — {num(curve.duration_min as number)} года. Пометка «край» стоит только там, где спред упёрся в границу.
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
                <th className="py-2 pr-3 font-medium">Цена</th>
                <th className="py-2 font-medium">Медиана</th>
              </tr>
            </thead>
            <tbody>
              {exceptions.map((item) => (
                <tr key={String(item.isin)} className="border-t border-[#eadfce] align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{String(item.shortname)}</div>
                    <div className="text-xs text-[#6d675e]">{String(item.issuer)}</div>
                    {(item.flags as string[] | undefined)?.length ? (
                      <div className="mt-1 text-xs text-[#8d4b32]">{(item.flags as string[]).join(" ")}</div>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">{String(item.rating || "—")}</td>
                  <td className="py-2 pr-3">{String(item.screener_rating || "—")}</td>
                  <td className="py-2 pr-3">{num(item.years as number)} лет</td>
                  <td className="py-2 pr-3">{num(item.duration as number)}</td>
                  <td className="py-2 pr-3">{num(item.ytm as number)}%</td>
                  <td className="py-2 pr-3">{item.g_spread_bp == null ? "—" : `${num(item.g_spread_bp as number, 0)} б.п.`}{item.g_spread_clamped ? <div className="text-xs text-[#8d4b32]">край кривой</div> : null}</td>
                  <td className="py-2 pr-3">{num(item.score as number, 1)}</td>
                  <td className="py-2 pr-3">{num(item.price as number)}%</td>
                  <td className="py-2">{item.median_mln == null ? "—" : `${num(item.median_mln as number, 2)} млн`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Что можно сделать с остатком</h2>
        <ul className="mt-4 space-y-3">
          {variants.map((item) => {
            const position = item.position as Dict | undefined;
            return (
              <li key={String(item.title)} className="rounded-2xl bg-white px-4 py-3">
                <p className="font-medium">{String(item.title)}</p>
                <p className="mt-1 text-sm leading-6 text-[#5c564e]">{String(item.detail)}</p>
                {position && (
                  <p className="mt-2 text-sm leading-6">
                    {String(position.shortname)}: {String(position.qty)} шт., сумма {rub(position.position_sum as number, 2)}, комиссия {rub(position.commission as number, 2)}, списание {rub(position.debit as number, 2)}, YTM {num(position.ytm as number)}%, дюрация {num(position.duration as number)} лет.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="font-serif text-3xl">ОФЗ длиннее 8 лет</h2>
          <p className="mt-2 text-sm text-[#5c564e]">Порядок — по дюрации файла, затем по сроку. Доходность 16,9% у более короткой дюрации в пакет не берётся.</p>
          <ul className="mt-4 space-y-1 text-sm">
            {ofz.filter((item) => item.status === "eligible").sort((a, b) => Number(b.duration) - Number(a.duration)).map((item) => (
              <li key={String(item.isin)} className="flex justify-between gap-3 border-t border-[#eadfce] py-1.5">
                <span>{String(item.shortname)}</span>
                <span className="text-[#5c564e]">{num(item.duration as number)} лет · {num(item.ytm as number)}% · {num(item.years as number)} до погашения</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="font-serif text-3xl">Почему остальные не вошли</h2>
          <ul className="mt-4 space-y-1 text-sm text-[#5c564e]">
            {Object.entries(counts).map(([reason, count]) => (
              <li key={reason}>{count as number} — {reason}</li>
            ))}
          </ul>
          <ul className="mt-4 space-y-2 text-sm">
            {rejected.map((item) => (
              <li key={String(item.isin)}>
                <span className="font-medium">{String(item.shortname)}</span>
                <span className="text-[#5c564e]"> — {String(item.reason)}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Чего в файле нет</h2>
        <ul className="mt-4 space-y-2 text-sm leading-6 text-[#5c564e]">
          {caveats.map((item) => <li key={item}>{item}</li>)}
          <li>{String(limits.schedule)}</li>
          <li>{String(limits.calendar)}</li>
          <li>{String(limits.tax)} Наивное сравнение по пакету: {num(weights.naive_ytm_after_13 as number)}%.</li>
        </ul>
      </section>

      <footer className="mt-12 border-t border-[#d9d0c2] pt-6 text-sm leading-6 text-[#6d675e]">
        {String(report.disclaimer)} Скринер: <a className="underline" href="https://www.dohod.ru/analytic/bonds">dohod.ru/analytic/bonds</a>.
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
