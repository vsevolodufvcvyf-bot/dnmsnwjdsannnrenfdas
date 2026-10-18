import { decide } from "./decide.js";
import { maybeOpen, memorySummary, resolveOpen } from "./learn.js";

export function step(memory, candles, higher, news, spec, interval) {
  const symbol = spec.compact;
  const closed = resolveOpen(memory, symbol, interval, candles);
  const analysis = decide(candles, higher, news, memory);
  let opened = false;
  if (analysis.verdict !== "wait" && analysis.pattern && candles.length) {
    const last = candles[candles.length - 1];
    opened = maybeOpen(memory, {
      symbol,
      interval,
      patternId: analysis.pattern.id,
      name: analysis.pattern.name,
      direction: analysis.verdict,
      entry: analysis.pattern.entry,
      stop: analysis.pattern.stop,
      target: analysis.pattern.target,
      openedAt: last.t,
    });
  }
  return { analysis, closed, opened, summary: memorySummary(memory) };
}
