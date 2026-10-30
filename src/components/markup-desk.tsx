"use client";

import { useMemo, useState } from "react";
import {
  COST_MAX,
  COST_MIN,
  DEFAULT_REVENUE_MIX,
  TARGET_MARGIN_MAX,
  TARGET_MARGIN_MIN,
  moneyMargin,
  quote,
  rub,
  schedule,
} from "@/lib/markup";

function pct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

export function MarkupDesk() {
  const [costText, setCostText] = useState("100");
  const cost = Number(String(costText).replace(",", "."));
  const valid = Number.isFinite(cost) && cost >= COST_MIN;
  const priced = useMemo(() => (valid ? quote(cost) : null), [cost, valid]);
  const tiers = useMemo(() => schedule(), []);
  const modelMargin = useMemo(() => moneyMargin(DEFAULT_REVENUE_MIX) * 100, []);

  const curve = useMemo(() => {
    const points = [1, 3, 5, 15, 30, 50, 75, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 180_000];
    return points.map((c) => quote(c));
  }, []);

  const maxMarkup = 1000;
  const chartH = 160;

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <p className="text-sm tracking-[0.18em] text-[#8d4b32] uppercase">Прайс</p>
      <h1 className="mt-2 font-serif text-4xl leading-tight sm:text-5xl">Регрессивная наценка</h1>
      <p className="mt-4 max-w-2xl text-base leading-7 text-[#5c564e]">
        Дешёвые SKU — высокая наценка, дорогие — низкая. Диапазон закупки {rub(COST_MIN)}–{rub(COST_MAX)}.
        Цель по деньгам: валовая маржа {TARGET_MARGIN_MIN}–{TARGET_MARGIN_MAX}% при выручке, смещённой к дорогому краю.
        Ориентир на ≈100&nbsp;000 SKU.
      </p>

      <section className="mt-10 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <label className="block text-sm text-[#5c564e]" htmlFor="cost">
            Закупочная цена, ₽
          </label>
          <input
            id="cost"
            inputMode="decimal"
            value={costText}
            onChange={(event) => setCostText(event.target.value)}
            className="mt-2 w-full border border-[#d7d0c4] bg-[#faf7f1] px-4 py-3 font-serif text-3xl outline-none focus:border-[#8d4b32]"
          />
          {priced ? (
            <div className="mt-6 grid gap-4 sm:grid-cols-3">
              <Metric label="Наценка" value={pct(priced.markupPct, 0)} />
              <Metric label="Маржа в цене" value={pct(priced.marginPct)} />
              <Metric label="Цена продажи" value={rub(priced.price, 2)} />
            </div>
          ) : (
            <p className="mt-4 text-sm text-[#8d4b32]">Введите закупку от {rub(COST_MIN)}.</p>
          )}
          {priced ? (
            <p className="mt-4 text-sm text-[#5c564e]">
              Ступень {rub(priced.bandLow)}–{rub(priced.bandHigh)}: наценка фиксирована внутри полосы.
            </p>
          ) : null}
        </div>

        <div className="border border-[#d7d0c4] bg-[#faf7f1] p-5">
          <h2 className="font-serif text-2xl">Цель по деньгам</h2>
          <p className="mt-2 text-sm leading-6 text-[#5c564e]">
            Модельный микс (дорого доминирует в выручке) даёт{" "}
            <span className="text-[#1a1814]">{pct(modelMargin)}</span> валовой маржи — внутри коридора{" "}
            {TARGET_MARGIN_MIN}–{TARGET_MARGIN_MAX}%. Средняя наценка по SKU для этого не используется.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-[#5c564e]">
            <li>1–5 ₽ — до 1000% наценки</li>
            <li>50–100 ₽ — 280–350%</li>
            <li>180 000 ₽ — 25% наценки = 20% маржи</li>
            <li>500–100 000 ₽ — мягкий спуск, {tiers.filter((t) => t.costFrom >= 500 && t.costTo <= 100_000).length} ступеней</li>
          </ul>
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-serif text-3xl">Кривая наценки</h2>
        <p className="mt-2 max-w-2xl text-sm text-[#5c564e]">Высота столбика — наценка в % от закупки. Логарифм по оси цены сжатый.</p>
        <div className="mt-6 flex items-end gap-1 overflow-x-auto border-b border-[#d7d0c4] pb-2" style={{ height: chartH + 48 }}>
          {curve.map((point) => {
            const h = Math.max(4, (point.markupPct / maxMarkup) * chartH);
            return (
              <div key={point.cost} className="flex w-10 shrink-0 flex-col items-center justify-end sm:w-12" style={{ height: chartH + 40 }}>
                <span className="mb-1 text-[10px] text-[#5c564e]">{point.markupPct}</span>
                <div className="w-full bg-[#8d4b32]" style={{ height: h }} title={`${rub(point.cost)} → +${point.markupPct}%`} />
                <span className="mt-2 text-[10px] text-[#5c564e]">{point.cost >= 1000 ? `${point.cost / 1000}k` : point.cost}</span>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-serif text-3xl">Ступени</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead>
              <tr className="border-b border-[#d7d0c4] text-[#5c564e]">
                <th className="py-2 pr-3 font-medium">Закупка от</th>
                <th className="py-2 pr-3 font-medium">до</th>
                <th className="py-2 pr-3 font-medium">Наценка</th>
                <th className="py-2 font-medium">Маржа</th>
              </tr>
            </thead>
            <tbody>
              {tiers.map((row) => (
                <tr key={`${row.costFrom}-${row.costTo}`} className="border-b border-[#ece6da]">
                  <td className="py-2 pr-3">{rub(row.costFrom, row.costFrom % 1 ? 2 : 0)}</td>
                  <td className="py-2 pr-3">{rub(row.costTo, row.costTo % 1 ? 2 : 0)}</td>
                  <td className="py-2 pr-3">{pct(row.markupPct, 0)}</td>
                  <td className="py-2">{pct(row.marginPct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="mt-12 max-w-3xl text-sm leading-6 text-[#5c564e]">
        CLI: <code className="text-[#1a1814]">python3 -m engine.markup 100</code>, шкала{" "}
        <code className="text-[#1a1814]">--schedule</code>, прайс CSV{" "}
        <code className="text-[#1a1814]">--csv catalog.csv</code>. При миксе с доминированием дешёвых позиций
        маржа по деньгам будет выше целевого коридора — это ожидаемо при регрессивной шкале.
      </p>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs tracking-wide text-[#5c564e] uppercase">{label}</div>
      <div className="mt-1 font-serif text-2xl">{value}</div>
    </div>
  );
}
