import { mln, num, rub } from "@/lib/utils";

type Dict = Record<string, unknown>;

export function MoexCheck({ report }: { report: Dict | null }) {
  if (!report) return null;
  const broker = report.broker as Dict;
  const budget = report.budget as Dict;
  const cash = report.cash as Dict;
  const weights = report.weights as Dict;
  const positions = (report.package as Dict[]) || [];
  const slots = (budget.slots as Dict[]) || [];
  const checks = (report.checks as Dict[]) || [];
  const exceptions = (report.exceptions as Dict[]) || [];
  const waitlist = (report.waitlist as Dict[]) || [];
  const rejected = (report.rejected as Dict[]) || [];
  const calendar = (report.calendar as Dict[]) || [];
  const curve = (report.curve as Dict) || {};
  const tenor = (curve.tenor_ytm as Dict) || {};
  const match = (report.match as Dict) || {};
  const turnover = (report.turnover as Dict) || {};
  const caveats = (report.caveats as string[]) || [];
  const sessions = (turnover.sessions as string[]) || [];
  const meets = Boolean(weights.meets_target);
  const moved = checks
    .filter((row) => Math.abs(Number(row.delta && (row.delta as Dict).ytm_pp) || 0) >= 0.15 || Math.abs(Number(row.delta && (row.delta as Dict).price_pp) || 0) >= 0.3)
    .sort((a, b) => Math.abs(Number((b.delta as Dict)?.ytm_pp) || 0) - Math.abs(Number((a.delta as Dict)?.ytm_pp) || 0));

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="border-b border-[#d9d0c2] pb-8">
        <p className="text-xs uppercase tracking-[0.22em] text-[#8d4b32]">Московская биржа · {String(report.asof)}</p>
        <h1 className="mt-2 font-serif text-4xl leading-tight sm:text-5xl">Сверка 49 выпусков</h1>
        <p className="mt-3 max-w-3xl text-[#5c564e]">
          Все строки двух файлов нашлись в ISS: {String(match.found)} из {String(match.rows)}. Пакет на вторник {String(report.tuesday)} для {String(broker.name)}, соглашение {String(broker.agreement)}, пересчитан по цене, НКД, доходности и среднему обороту биржи.
          Медианный сдвиг цены {num(match.median_abs_price_pp as number)} п.п., доходности {num(match.median_abs_ytm_pp as number)} п.п.
        </p>
      </header>

      <section className="mt-8 grid gap-4 md:grid-cols-4">
        <Stat label="Взнос" value={rub(budget.total as number)} hint={`${String(broker.name)}, комиссия 0,291%`} />
        <Stat
          label="YTM до налога"
          value={`${num(weights.ytm as number)}%`}
          hint={meets ? "Ориентир 16% выполнен" : "Ниже ориентира 16%"}
          tone={meets ? "good" : "warn"}
        />
        <Stat
          label="После НДФЛ 13%"
          value={`${num(weights.ytm_after_tax as number)}%`}
          hint="IRR купонов и дисконта по графику биржи"
          tone="good"
        />
        <Stat
          label="Остаток"
          value={rub(cash.remainder as number)}
          hint={`${num((Number(cash.remainder_pct) || 0) * 100, 1)}% взноса. Корпоративный слот пуст`}
          tone="warn"
        />
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">К покупке по бирже</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {positions.map((item) => (
            <article key={String(item.isin)} className="rounded-3xl border border-[#e4dccb] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(item.slot_title)}</p>
              <h3 className="mt-1 font-serif text-3xl">{String(item.shortname)}</h3>
              <p className="text-sm text-[#5c564e]">{String(item.secid)} · {String(item.isin)}</p>
              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
                <Field label="Количество" value={`${item.qty} шт.`} />
                <Field label="Грязная цена" value={rub(item.dirty as number, 2)} />
                <Field label="Сумма с НКД" value={rub(item.position_sum as number, 2)} />
                <Field label="Комиссия" value={rub(item.commission as number, 2)} />
                <Field label="Списание" value={rub(item.debit as number, 2)} />
                <Field label="YTM биржи" value={`${num(item.ytm as number)}%`} />
                <Field label="YTM по графику" value={`${num(item.ytm_cashflow as number)}%`} />
                <Field label="После налога" value={`${num(item.ytm_after_tax as number)}%`} />
                <Field label="Дюрация биржи" value={`${num(item.duration as number)} лет`} />
                <Field label="До погашения" value={`${num(item.years as number)} лет`} />
                <Field label="Средний оборот" value={mln(item.mean_turnover as number)} />
                <Field label="Купон" value={`${num(item.coupon_percent as number)}%`} />
              </dl>
              <p className="mt-4 text-xs leading-5 text-[#6d675e]">
                Цена {num(item.price as number)}% в {String(item.price_asof)}, источник: {String(item.price_source)}.
                В файле было {num(item.excel_price as number)}% и YTM {num(item.excel_ytm as number)}%. Дюрация файла {num(item.excel_duration as number)} — это модифицированная дюрация скринера, в отбор взята дюрация биржи.
                Средний оборот {mln(item.mean_turnover as number)}, медиана биржи {mln(item.median_turnover as number)}, медиана файла {num(item.excel_median_mln as number, 0)} млн ₽.
              </p>
              <p className="mt-2 text-xs leading-5 text-[#6d675e]">
                {String(item.bondization_note)}. Наивное {num(item.naive_ytm_after_13 as number)}% — это YTM × 0,87, ответом служит IRR.
                <a className="ml-2 underline" href={String(item.moex_url)}>Биржа</a>
              </p>
            </article>
          ))}
          {slots.filter((slot) => slot.id !== "ofz").map((slot) => (
            <article key={String(slot.id)} className="rounded-3xl border border-dashed border-[#c8b49a] bg-[#fbf6ee] p-5 lg:col-span-2">
              <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(slot.title)}</p>
              <h3 className="mt-1 font-serif text-3xl">Не заполнен</h3>
              <p className="mt-3 text-sm leading-6 text-[#5c564e]">
                Цель слота {rub(slot.target as number, 0)}. После сверки оборота внутри окна 4–7 лет остаются выпуски с баллом ниже 5. Короткие AAA/AA с высоким баллом, включая ПКТ 2P2 и ФосАгро, в пакет не переносятся.
              </p>
              {waitlist.map((item) => (
                <p key={String(item.isin)} className="mt-3 text-sm leading-6">
                  <span className="font-medium">{String(item.shortname)}</span> — {String(item.reason)} YTM {num(item.ytm as number)}%, G-спред {num(item.g_spread_bp as number, 0)} б.п., средний оборот {mln(item.mean_turnover as number)}.
                </p>
              ))}
            </article>
          ))}
        </div>
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <h2 className="font-serif text-3xl">Деньги и купоны</h2>
          <table className="mt-4 w-full text-sm">
            <tbody>
              <Row label="Взнос" value={rub(budget.contribution as number, 2)} />
              <Row label="Резерв 0,3%" value={rub(budget.reserve_amount as number, 2)} />
              <Row label="Бумаги с НКД" value={rub(cash.spent_dirty as number, 2)} />
              <Row label="Комиссия" value={rub(cash.commission as number, 2)} />
              <Row label="Списание" value={rub(cash.total_debit as number, 2)} />
              <Row label="Остаток" value={rub(cash.remainder as number, 2)} strong />
            </tbody>
          </table>
          <p className="mt-4 text-sm text-[#5c564e]">Купоны на 12 месяцев только из графика выплат MOEX.</p>
          <table className="mt-2 w-full text-sm">
            <tbody>
              {calendar.map((row) => (
                <Row key={String(row.month)} label={String(row.month)} value={rub(row.total as number, 2)} />
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h2 className="font-serif text-3xl">Кривая</h2>
          <div className="mt-4 grid grid-cols-4 gap-2">
            {["2", "5", "10", "15"].map((key) => {
              const point = tenor[key] as Dict | undefined;
              return (
                <div key={key} className="rounded-2xl bg-white px-3 py-3 text-center">
                  <p className="text-[11px] uppercase tracking-wider text-[#8a8175]">{key} лет</p>
                  <p className="mt-1 font-serif text-xl">{point ? `${num(point.ytm as number)}%` : "—"}</p>
                  {point?.clamped ? <p className="text-[10px] text-[#8d4b32]">край кривой</p> : null}
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-sm leading-6 text-[#5c564e]">{String(curve.method)} Точек: {String(curve.points)}.</p>
          <p className="mt-2 text-sm leading-6 text-[#5c564e]">
            Среднее за {String(turnover.session_count)} сессий: {sessions[0]} — {sessions[sessions.length - 1]}. Пропуск дня равен нулю.
          </p>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Где файл и биржа разошлись заметнее</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#5c564e]">
          Порог таблицы: сдвиг YTM от 0,15 п.п. или цены от 0,30 п.п. Дюрация файла короче биржевой: у длинных ОФЗ разница около половины года, это модифицированная дюрация скринера против дюрации ISS.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
              <tr>
                <th className="py-2 pr-3 font-medium">Выпуск</th>
                <th className="py-2 pr-3 font-medium">Цена, файл</th>
                <th className="py-2 pr-3 font-medium">Цена, биржа</th>
                <th className="py-2 pr-3 font-medium">YTM, файл</th>
                <th className="py-2 pr-3 font-medium">YTM, биржа</th>
                <th className="py-2 font-medium">Дюрация, файл → биржа</th>
              </tr>
            </thead>
            <tbody>
              {moved.map((row) => (
                <tr key={String(row.isin)} className="border-t border-[#eadfce]">
                  <td className="py-2 pr-3 font-medium">{String(row.shortname)}</td>
                  <td className="py-2 pr-3">{num(row.excel_price as number)}</td>
                  <td className="py-2 pr-3">{num(row.moex_price as number)}</td>
                  <td className="py-2 pr-3">{num(row.excel_ytm as number)}%</td>
                  <td className="py-2 pr-3">{num(row.moex_ytm as number)}%</td>
                  <td className="py-2">{num(row.excel_duration as number)} → {num(row.moex_duration as number)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Короткие AAA/AA после сверки оборота</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#5c564e]">
          Средний оборот с биржи вернул в сравнение выпуски, у которых в файле медиана была пустой. Срок короче четырёх лет по-прежнему общее исключение. ФосАгро в этом списке наравне с остальными.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
              <tr>
                <th className="py-2 pr-3 font-medium">Выпуск</th>
                <th className="py-2 pr-3 font-medium">Рейтинг</th>
                <th className="py-2 pr-3 font-medium">Срок</th>
                <th className="py-2 pr-3 font-medium">YTM</th>
                <th className="py-2 pr-3 font-medium">G-спред</th>
                <th className="py-2 pr-3 font-medium">Балл</th>
                <th className="py-2 font-medium">Средний оборот</th>
              </tr>
            </thead>
            <tbody>
              {exceptions.map((item) => (
                <tr key={String(item.isin)} className="border-t border-[#eadfce] align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{String(item.shortname)}</div>
                    {(item.flags as string[] | undefined)?.length ? <div className="text-xs text-[#8d4b32]">{(item.flags as string[]).join(" ")}</div> : null}
                  </td>
                  <td className="py-2 pr-3">{String(item.rating)} <span className="text-xs text-[#6d675e]">/ {String(item.screener_rating)}</span></td>
                  <td className="py-2 pr-3">{num(item.years as number)} лет</td>
                  <td className="py-2 pr-3">{num(item.ytm as number)}%</td>
                  <td className="py-2 pr-3">{num(item.g_spread_bp as number, 0)} б.п.</td>
                  <td className="py-2 pr-3">{num(item.score as number, 1)}</td>
                  <td className="py-2">{mln(item.mean_turnover as number)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="font-serif text-3xl">Все строки файлов</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[#8a8175]">
              <tr>
                <th className="py-2 pr-3 font-medium">Выпуск</th>
                <th className="py-2 pr-3 font-medium">Файл</th>
                <th className="py-2 pr-3 font-medium">YTM биржа</th>
                <th className="py-2 pr-3 font-medium">Цена биржа</th>
                <th className="py-2 pr-3 font-medium">Среднее</th>
                <th className="py-2 font-medium">Медиана файла</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((row) => (
                <tr key={String(row.isin)} className="border-t border-[#eadfce]">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{String(row.shortname)}</div>
                    <div className="text-xs text-[#6d675e]">{String(row.file)}</div>
                  </td>
                  <td className="py-2 pr-3">{num(row.excel_ytm as number)}%</td>
                  <td className="py-2 pr-3">{num(row.moex_ytm as number)}%</td>
                  <td className="py-2 pr-3">{num(row.moex_price as number)}%</td>
                  <td className="py-2 pr-3">{mln(row.mean_turnover as number)}</td>
                  <td className="py-2">{row.excel_median_mln == null ? "нет" : `${num(row.excel_median_mln as number, 2)} млн`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {rejected.length > 0 && (
        <section className="mt-10">
          <h2 className="font-serif text-3xl">Отказы после сверки</h2>
          <ul className="mt-4 space-y-1 text-sm text-[#5c564e]">
            {rejected.map((item) => (
              <li key={String(item.isin)}><span className="font-medium text-[#1a1814]">{String(item.shortname)}</span> — {String(item.reason)}</li>
            ))}
          </ul>
        </section>
      )}

      <ul className="mt-10 space-y-2 text-sm leading-6 text-[#5c564e]">
        {caveats.map((item) => <li key={item}>{item}</li>)}
      </ul>
      <footer className="mt-8 border-t border-[#d9d0c2] pt-6 text-sm leading-6 text-[#6d675e]">{String(report.disclaimer)}</footer>
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
