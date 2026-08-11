"use client";

import { useEffect, useRef } from "react";
import { CandlestickSeries, ColorType, createChart, LineSeries } from "lightweight-charts";
import { ChartPoint } from "@/types";

export function MarketChart({ data }: { data: ChartPoint[] }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, { height: 410, layout: { background: { type: ColorType.Solid, color: "#111c24" }, textColor: "#91a1aa" }, grid: { vertLines: { color: "#1d3039" }, horzLines: { color: "#1d3039" } }, rightPriceScale: { borderColor: "#263842" }, timeScale: { borderColor: "#263842" } });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#72c59a", downColor: "#d77875", borderVisible: false, wickUpColor: "#72c59a", wickDownColor: "#d77875" });
    candles.setData(data.map((d, index) => ({ time: `2026-08-${String(index + 5).padStart(2, "0")}` as const, open: d.open!, high: d.high!, low: d.low!, close: d.close! })));
    const fast = chart.addSeries(LineSeries, { color: "#5fb8b1", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    fast.setData(data.map((d, index) => ({ time: `2026-08-${String(index + 5).padStart(2, "0")}` as const, value: d.maShort! })));
    const slow = chart.addSeries(LineSeries, { color: "#d9a95f", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    slow.setData(data.map((d, index) => ({ time: `2026-08-${String(index + 5).padStart(2, "0")}` as const, value: d.maLong! })));
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: host.current?.clientWidth ?? 0 })); observer.observe(host.current);
    return () => { observer.disconnect(); chart.remove(); };
  }, [data]);
  return <div ref={host} className="h-[410px] w-full" aria-label="Mock candlestick chart" />;
}
