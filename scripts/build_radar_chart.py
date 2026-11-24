"""Собирает radar/radar_chart.html из чистых свечей и таблицы событий.

График — TradingView Lightweight Charts с CDN. Числа только из CSV.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.common import CLEAN, ROOT  # noqa: E402

EVENTS = ROOT / "data" / "radar_events.csv"
OUT = ROOT / "radar" / "radar_chart.html"
CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
TICKER_ORDER = ("IMOEX", "SMLT", "KLVZ", "EUTR", "MGKL", "SELG", "TATN", "OZON", "GAZP")


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_bars() -> dict[str, list[dict]]:
    bars: dict[str, dict[str, dict]] = {}
    with (CLEAN / "prices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("ticker") or ""
            stamp = row.get("date") or ""
            open_, high, low, close = (_num(row.get(name)) for name in ("open", "high", "low", "close"))
            if not ticker or not stamp or close is None:
                continue
            bars.setdefault(ticker, {})[stamp] = {
                "time": stamp,
                "open": open_ if open_ is not None else close,
                "high": high if high is not None else close,
                "low": low if low is not None else close,
                "close": close,
            }
    share_tickers = set(bars)
    with (CLEAN / "indices_daily.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = row.get("index") or ""
            stamp = row.get("date") or ""
            close = _num(row.get("close"))
            if not ticker or not stamp or close is None or ticker in share_tickers:
                continue
            # В indices_daily нет OHLC: свеча без выдуманного диапазона.
            bars.setdefault(ticker, {})[stamp] = {
                "time": stamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
            }
    return {ticker: [bars[ticker][stamp] for stamp in sorted(bars[ticker])] for ticker in bars}


def load_events() -> list[dict]:
    rows = []
    with EVENTS.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            heat = _num(row.get("heat"))
            tone = _num(row.get("tone"))
            if not row.get("date") or not row.get("ticker") or heat is None or tone is None:
                continue
            rows.append(
                {
                    "date": row["date"],
                    "time_msk": row.get("time_msk") or "",
                    "ticker": row["ticker"],
                    "heat": heat,
                    "tone": tone,
                    "category": row.get("category") or "",
                    "short_label": row.get("short_label") or "",
                    "thesis": row.get("thesis") or "",
                    "source_channel": row.get("source_channel") or "",
                }
            )
    rows.sort(key=lambda item: (item["date"], item["time_msk"], item["ticker"]))
    return rows


def ticker_list(bars: dict, events: list[dict]) -> list[str]:
    """Кнопки — тикеры из таблицы событий. Свечи подтягиваются только для них."""
    found = {row["ticker"] for row in events}
    ordered = [name for name in TICKER_ORDER if name in found]
    ordered.extend(sorted(found - set(ordered)))
    return ordered


def build() -> None:
    bars = load_bars()
    events = load_events()
    payload = {
        "tickers": ticker_list(bars, events),
        "bars": {ticker: bars.get(ticker, []) for ticker in ticker_list(bars, events)},
        "events": events,
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", blob).replace("__CDN__", CDN), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} tickers={len(payload['tickers'])} events={len(events)}")


HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NARRATIVE RADAR</title>
<script src="__CDN__"></script>
<style>
  body { margin: 0; background: #f3efe6; color: #1c1915; font-family: Georgia, "Times New Roman", serif; }
  header { padding: 14px 16px 0; }
  h1 { margin: 0; font-size: 18px; letter-spacing: 0.08em; }
  .note { margin: 4px 0 0; font-size: 12px; color: #5e584e; }
  .tickers { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 16px; }
  .tickers button {
    font-size: 10px;
    font-family: "Segoe UI", sans-serif;
    line-height: 1.2;
    padding: 3px 6px;
    border: 1px solid #1c1915;
    background: #fffdf8;
    color: #1c1915;
    cursor: pointer;
  }
  .tickers button.active { background: #1c1915; color: #f3efe6; }
  .wrap { position: relative; margin: 0 12px; }
  #price { height: 440px; }
  #lower { height: 170px; margin-top: 8px; }
  .scale-label { font-family: "Segoe UI", sans-serif; font-size: 10px; color: #5e584e; margin: 8px 16px 0; }
  #tip {
    display: none;
    position: absolute;
    z-index: 5;
    max-width: 340px;
    background: #fffdf8;
    border: 1px solid #1c1915;
    padding: 8px 10px;
    font-size: 13px;
    line-height: 1.35;
    pointer-events: none;
  }
  #tip .meta { font-family: "Segoe UI", sans-serif; font-size: 11px; color: #5e584e; }
  #empty { display: none; padding: 24px 16px; font-size: 14px; }
  #list { padding: 8px 16px 28px; }
  #list h2 { font-size: 14px; margin: 12px 0 6px; }
  #list article { border-top: 1px solid #d9d1c3; padding: 6px 0; }
  #list .meta { font-family: "Segoe UI", sans-serif; font-size: 11px; color: #5e584e; }
</style>
</head>
<body>
<header>
  <h1>NARRATIVE RADAR</h1>
  <p class="note">Свечи из clean, события из radar_events.csv. Всплывающий текст — тезис строки, не совет. У индекса в файле только close, поэтому IMOEX — линия по закрытию, без выдуманного диапазона.</p>
</header>
<div class="tickers" id="tickers"></div>
<div class="wrap">
  <div id="price"></div>
  <div id="tip"></div>
  <div id="empty"></div>
</div>
<p class="scale-label">Нижняя панель: гистограмма Жара 1–5 и линия Тона от −5 до +5. Если в день несколько событий, столбец берёт максимальный жар, линия — тон этой же строки.</p>
<div class="wrap"><div id="lower"></div></div>
<div id="list"></div>
<script>
const DATA = __DATA__;
const priceEl = document.getElementById("price");
const lowerEl = document.getElementById("lower");
const tipEl = document.getElementById("tip");
const emptyEl = document.getElementById("empty");
const listEl = document.getElementById("list");
const buttonRow = document.getElementById("tickers");

const base = {
  layout: { background: { color: "#f3efe6" }, textColor: "#1c1915", fontSize: 11 },
  grid: { vertLines: { color: "#e4dccf" }, horzLines: { color: "#e4dccf" } },
  rightPriceScale: { borderColor: "#1c1915" },
  timeScale: { borderColor: "#1c1915" },
  crosshair: { mode: 0 },
};
const priceChart = LightweightCharts.createChart(priceEl, Object.assign({ height: 440 }, base));
const lowerChart = LightweightCharts.createChart(lowerEl, Object.assign({ height: 170 }, base));
const candleOptions = {
  upColor: "#2f6f4e",
  downColor: "#9c3b3b",
  borderUpColor: "#2f6f4e",
  borderDownColor: "#9c3b3b",
  wickUpColor: "#2f6f4e",
  wickDownColor: "#9c3b3b",
};
let priceSeries = priceChart.addCandlestickSeries(candleOptions);
let priceKind = "candle";
const heat = lowerChart.addHistogramSeries({
  priceScaleId: "heat",
  priceFormat: { type: "price", precision: 0, minMove: 1 },
  base: 0,
  autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 5 } }),
});
const tone = lowerChart.addLineSeries({
  priceScaleId: "left",
  color: "#1f4b99",
  lineWidth: 2,
  priceFormat: { type: "price", precision: 0, minMove: 1 },
  autoscaleInfoProvider: () => ({ priceRange: { minValue: -5, maxValue: 5 } }),
});
const axis = lowerChart.addLineSeries({
  priceScaleId: "axis",
  color: "rgba(0,0,0,0)",
  lineWidth: 1,
  lastValueVisible: false,
  priceLineVisible: false,
  crosshairMarkerVisible: false,
});
lowerChart.priceScale("heat").applyOptions({ scaleMargins: { top: 0.12, bottom: 0.12 } });
lowerChart.priceScale("left").applyOptions({ visible: true, scaleMargins: { top: 0.12, bottom: 0.12 } });
lowerChart.priceScale("axis").applyOptions({ visible: false, autoScale: false });

let syncing = false;
priceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
  if (syncing || !range) return;
  syncing = true;
  try {
    lowerChart.timeScale().setVisibleRange(range);
  } catch (error) {
    // Нижняя шкала ещё без своих дат: прокрутка цены не должна рвать отрисовку.
  }
  syncing = false;
});

const requested = decodeURIComponent((location.hash || "").replace("#", ""));
let current = DATA.tickers.includes(requested) ? requested : (DATA.tickers[0] || "");
const buttons = {};
DATA.tickers.forEach((ticker) => {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = ticker;
  button.addEventListener("click", () => show(ticker));
  buttonRow.appendChild(button);
  buttons[ticker] = button;
});

function eventsOf(ticker) {
  return DATA.events.filter((row) => row.ticker === ticker);
}

function dayPanel(rows) {
  const byDay = new Map();
  rows.forEach((row) => {
    const prev = byDay.get(row.date);
    if (!prev || row.heat > prev.heat) byDay.set(row.date, row);
  });
  return Array.from(byDay.values()).sort((a, b) => a.date.localeCompare(b.date));
}

function markerColor(toneValue) {
  if (toneValue > 0) return "#2f6f4e";
  if (toneValue < 0) return "#9c3b3b";
  return "#6b6256";
}

function weekdays(from, to) {
  const days = [];
  const cursor = new Date(from + "T00:00:00Z");
  const end = new Date(to + "T00:00:00Z");
  while (cursor <= end) {
    const day = cursor.getUTCDay();
    if (day !== 0 && day !== 6) days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

function show(ticker) {
  current = ticker;
  Object.entries(buttons).forEach(([name, button]) => {
    button.classList.toggle("active", name === ticker);
  });
  const bars = DATA.bars[ticker] || [];
  const rows = eventsOf(ticker);
  const barDays = new Set(bars.map((bar) => bar.time));
  const markers = rows.filter((row) => barDays.has(row.date)).map((row) => ({
    time: row.date,
    position: row.tone < 0 ? "aboveBar" : "belowBar",
    color: markerColor(row.tone),
    shape: row.tone < 0 ? "arrowDown" : "circle",
    text: row.short_label,
  }));
  const ranged = bars.some((bar) => bar.high !== bar.low || bar.open !== bar.close);
  const kind = ranged ? "candle" : "line";
  if (kind !== priceKind) {
    priceChart.removeSeries(priceSeries);
    priceSeries = kind === "candle"
      ? priceChart.addCandlestickSeries(candleOptions)
      : priceChart.addLineSeries({ color: "#1c1915", lineWidth: 2 });
    priceKind = kind;
  }
  priceSeries.setData(kind === "candle"
    ? bars
    : bars.map((bar) => ({ time: bar.time, value: bar.close })));
  priceSeries.setMarkers(markers);
  const panel = dayPanel(rows);
  heat.setData(panel.map((row) => ({
    time: row.date,
    value: row.heat,
    color: row.heat >= 4 ? "#9c3b3b" : "#c47b2b",
  })));
  tone.setData(panel.map((row) => ({ time: row.date, value: row.tone })));
  const axisTimes = bars.length ? bars.map((bar) => bar.time) : weekdays("2026-11-02", "2026-11-25");
  axis.setData(axisTimes.map((time) => ({ time, value: 0 })));
  emptyEl.style.display = bars.length ? "none" : "block";
  emptyEl.textContent = bars.length ? "" : ticker + ": в clean нет дневных свечей. События остаются в списке и на нижней панели.";
  const focus = () => {
    syncing = true;
    if (bars.length) {
      const i0 = bars.findIndex((item) => item.time >= "2026-10-01");
      const logical = { from: i0 < 0 ? 0 : i0, to: bars.length + 5 };
      priceChart.timeScale().applyOptions({ barSpacing: 22, rightOffset: 6 });
      lowerChart.timeScale().applyOptions({ barSpacing: 22, rightOffset: 6 });
      priceChart.timeScale().setVisibleLogicalRange(logical);
      lowerChart.timeScale().setVisibleLogicalRange(logical);
    } else {
      lowerChart.timeScale().fitContent();
    }
    syncing = false;
    if (bar) priceChart.setCrosshairPosition(bar.close, marked.time, priceSeries);
  };
  const marked = markers[markers.length - 1];
  const bar = marked && bars.find((item) => item.time === marked.time);
  if (!bar) tipEl.style.display = "none";
  focus();
  requestAnimationFrame(focus);
  listEl.innerHTML = "<h2>" + ticker + "</h2>" + rows.map((row) => (
    '<article><div class="meta">' + row.date + " " + row.time_msk + " МСК · жар " + row.heat
    + " · тон " + row.tone + " · " + row.category + " · " + row.source_channel + "</div><div>"
    + row.thesis + "</div></article>"
  )).join("");
}

function placeTip(event) {
  const host = priceEl.getBoundingClientRect();
  let x = event.point.x + 12;
  let y = event.point.y + 12;
  if (x > host.width - 360) x = Math.max(8, event.point.x - 348);
  if (y > host.height - 80) y = Math.max(8, event.point.y - 72);
  tipEl.style.left = x + "px";
  tipEl.style.top = y + "px";
}

priceChart.subscribeCrosshairMove((event) => {
  if (!event.time || !event.point) {
    tipEl.style.display = "none";
    return;
  }
  const day = typeof event.time === "string" ? event.time : "";
  const rows = eventsOf(current).filter((row) => row.date === day);
  if (!rows.length) {
    tipEl.style.display = "none";
    return;
  }
  tipEl.innerHTML = rows.map((row) => (
    '<div class="meta">' + row.time_msk + " МСК · " + row.short_label
    + " · жар " + row.heat + " · тон " + row.tone + "</div><div>" + row.thesis + "</div>"
  )).join("<hr>");
  tipEl.style.display = "block";
  placeTip(event);
});

window.addEventListener("resize", () => {
  priceChart.applyOptions({ width: priceEl.clientWidth });
  lowerChart.applyOptions({ width: lowerEl.clientWidth });
});
priceChart.applyOptions({ width: priceEl.clientWidth });
lowerChart.applyOptions({ width: lowerEl.clientWidth });
if (current) show(current);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
