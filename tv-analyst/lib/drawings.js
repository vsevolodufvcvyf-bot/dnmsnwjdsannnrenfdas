/** Время свечи в секундах, как его ждёт график TradingView. */
export function candleTime(candle) {
  if (!candle || !Number.isFinite(candle.t)) return null;
  return candle.t > 1e12 ? Math.floor(candle.t / 1000) : Math.floor(candle.t);
}

export function attachDrawingTimes(drawings, candles) {
  const timeAt = (index) => {
    if (!Number.isInteger(index) || index < 0 || index >= candles.length) return null;
    return candleTime(candles[index]);
  };
  const out = [];
  for (const drawing of drawings || []) {
    if (drawing.type === "dot") {
      const time = timeAt(drawing.i);
      if (!time) continue;
      out.push({ ...drawing, time, time1: time, time2: time });
      continue;
    }
    const time1 = timeAt(drawing.i1 ?? 0);
    const time2 = timeAt(drawing.i2 ?? candles.length - 1);
    const time = time2 || time1;
    if (!time) continue;
    out.push({ ...drawing, time, time1: time1 || time, time2: time2 || time });
  }
  return out;
}
