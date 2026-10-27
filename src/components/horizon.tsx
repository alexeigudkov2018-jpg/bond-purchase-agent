import { num, rub } from "@/lib/utils";

type Dict = Record<string, unknown>;

export function Horizon({ report }: { report: Dict | null }) {
  if (!report) return null;
  const broker = report.broker as Dict;
  const cash = report.cash as Dict;
  const weights = report.weights as Dict;
  const positions = (report.package as Dict[]) || [];

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="border-b border-[#d9d0c2] pb-8">
        <p className="text-xs uppercase tracking-[0.22em] text-[#8d4b32]">27 октября · к покупке</p>
        <h1 className="mt-2 font-serif text-4xl leading-tight sm:text-5xl">Пакет на 170 000 ₽</h1>
        <p className="mt-3 max-w-3xl text-[#5c564e]">{String(report.order_note)}</p>
      </header>

      <section className="mt-8 grid gap-4 md:grid-cols-4">
        <Stat label="Списание" value={rub(cash.total_debit as number, 2)} hint={`${String(broker.name)}, счёт ${String(broker.agreement)}`} />
        <Stat label="YTM до налога" value={`${num(weights.ytm as number)}%`} hint={`После налога ${num(weights.ytm_after_tax as number)}%`} tone="good" />
        <Stat label="Дюрация" value={`${num(weights.duration_years as number)} лет`} hint="Взвешена по сумме с НКД" />
        <Stat label="Остаток" value={rub(cash.remainder as number, 2)} hint="Меньше одной бумаги" tone="good" />
      </section>

      <section className="mt-10">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-serif text-3xl">К покупке</h2>
          <p className="text-sm text-[#5c564e]">Три позиции, срок до 2030–2032</p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {positions.map((item) => (
            <article key={String(item.isin)} className="rounded-3xl border border-[#e4dccb] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.16em] text-[#8d4b32]">{String(item.slot)}</p>
              <h3 className="mt-1 font-serif text-3xl">{String(item.shortname)}</h3>
              <p className="text-sm text-[#5c564e]">{String(item.isin)}</p>
              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <Field label="Количество" value={`${item.qty} шт.`} />
                <Field label="Списание" value={rub(item.debit as number, 2)} />
                <Field label="Грязная цена" value={rub(item.dirty as number, 2)} />
                <Field label="YTM" value={`${num(item.ytm as number)}%`} />
                <Field label="После налога" value={`${num(item.ytm_after_tax as number)}%`} />
                <Field label="Купон в год" value={rub(item.annual_coupon_position as number, 0)} />
                <Field label="До погашения" value={`${num(item.years as number)} лет`} />
                <Field label="Погашение" value={String(item.maturity)} />
              </dl>
              <p className="mt-4 text-xs leading-5 text-[#6d675e]">
                Цена {num(item.price as number, 3)}% в {String(item.price_asof).slice(11, 16)} МСК. НКД {rub(item.nkd as number, 2)}. Купон {num(item.coupon_percent as number)}%, {String(item.coupon_label)}.
                {item.note ? ` ${String(item.note)}` : ""}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-8 rounded-3xl bg-[#1a1814] px-5 py-5 text-[#f6f1e7]">
        <p className="text-xs uppercase tracking-[0.16em] text-[#e2b5a4]">Срок</p>
        <h2 className="mt-1 font-serif text-2xl">Деньги до 2032 года</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#ddd6cb]">{String(report.horizon)}</p>
        <p className="mt-3 text-sm leading-6 text-[#ddd6cb]">
          Купоны двух ОФЗ к 30 июня 2032 года: 26245 — {rub(44102.08, 0)}, 26252 — {rub(43194.69, 0)}. Банк до своего погашения платит {rub(21088.8, 0)} купонами и возвращает номинал 60 000 ₽.
        </p>
      </section>

      <footer className="mt-10 border-t border-[#d9d0c2] pt-6 text-sm leading-6 text-[#6d675e]">
        {String(report.disclaimer)} Лимит 5% на эмитента не проверен: оценки всего портфеля нет. На Минфин он не распространяется.
      </footer>
    </main>
  );
}

function Stat({ label, value, hint, tone = "ink" }: { label: string; value: string; hint: string; tone?: "ink" | "good" }) {
  const color = tone === "good" ? "text-[#1d6b45]" : "text-[#1a1814]";
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
