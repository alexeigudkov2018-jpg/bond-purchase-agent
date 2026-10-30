/** Регрессивная наценка: дешёвые — высокая, дорогие — низкая. */

export const COST_MIN = 1;
export const COST_MAX = 180_000;
export const TARGET_MARGIN_MIN = 23;
export const TARGET_MARGIN_MAX = 27;

/** Верхняя граница ступени → наценка %. */
export const TIERS: ReadonlyArray<readonly [number, number]> = [
  [5, 1000],
  [15, 700],
  [30, 500],
  [50, 400],
  [75, 350],
  [100, 280],
  [200, 200],
  [350, 160],
  [500, 120],
  [800, 100],
  [1_200, 85],
  [2_000, 70],
  [3_500, 58],
  [5_000, 50],
  [8_000, 42],
  [12_000, 38],
  [20_000, 35],
  [35_000, 32],
  [50_000, 30],
  [70_000, 28],
  [100_000, 27],
  [140_000, 26],
  [180_000, 25],
] as const;

export const DEFAULT_REVENUE_MIX: ReadonlyArray<readonly [number, number]> = [
  [3, 0.01],
  [75, 0.02],
  [300, 0.03],
  [2_000, 0.06],
  [15_000, 0.15],
  [50_000, 0.23],
  [100_000, 0.25],
  [160_000, 0.25],
] as const;

export type PriceQuote = {
  cost: number;
  markupPct: number;
  marginPct: number;
  price: number;
  bandLow: number;
  bandHigh: number;
};

export type ScheduleRow = {
  costFrom: number;
  costTo: number;
  markupPct: number;
  marginPct: number;
};

export function markupPct(cost: number): number {
  if (cost < COST_MIN) throw new Error(`закупка ниже ${COST_MIN}`);
  for (const [high, rate] of TIERS) {
    if (cost <= high) return rate;
  }
  return TIERS[TIERS.length - 1][1];
}

export function marginFromMarkup(markupPercent: number): number {
  return markupPercent / (100 + markupPercent);
}

export function sellPrice(cost: number, rate = markupPct(cost)): number {
  return Math.round(cost * (1 + rate / 100) * 100) / 100;
}

export function bandFor(cost: number): [number, number] {
  let low = COST_MIN;
  for (const [high] of TIERS) {
    if (cost <= high) return [low, high];
    low = high;
  }
  return [TIERS[TIERS.length - 2][0], COST_MAX];
}

export function quote(cost: number): PriceQuote {
  const rate = markupPct(cost);
  const [bandLow, bandHigh] = bandFor(cost);
  return {
    cost,
    markupPct: rate,
    marginPct: Math.round(marginFromMarkup(rate) * 10000) / 100,
    price: sellPrice(cost, rate),
    bandLow,
    bandHigh,
  };
}

export function schedule(): ScheduleRow[] {
  const rows: ScheduleRow[] = [];
  let low = COST_MIN;
  for (const [high, rate] of TIERS) {
    rows.push({
      costFrom: low,
      costTo: high,
      markupPct: rate,
      marginPct: Math.round(marginFromMarkup(rate) * 10000) / 100,
    });
    low = high + 0.01;
  }
  return rows;
}

export function moneyMargin(rows: ReadonlyArray<readonly [number, number]>): number {
  const total = rows.reduce((sum, [, weight]) => sum + weight, 0);
  if (total <= 0) throw new Error("сумма весов выручки должна быть > 0");
  const gross = rows.reduce(
    (sum, [cost, weight]) => sum + marginFromMarkup(markupPct(cost)) * weight,
    0,
  );
  return gross / total;
}

export function rub(value: number, digits = 0): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}
