/** Бумажный журнал. Вес фигуры растёт, если её сделки в плюсе, и падает, если они доходят до стопа. */

export const COST_R = 0.1;

export function emptyMemory() {
  return { version: 1, weights: {}, open: [], history: [] };
}

export function cloneMemory(seed) {
  const base = seed && typeof seed === "object" ? seed : emptyMemory();
  return {
    version: 1,
    weights: JSON.parse(JSON.stringify(base.weights || {})),
    open: JSON.parse(JSON.stringify(base.open || [])),
    history: JSON.parse(JSON.stringify(base.history || [])).slice(-80),
  };
}

export function weightOf(memory, patternId) {
  const w = memory?.weights?.[patternId];
  if (!w || !w.samples) return 1;
  const shrunk = (w.ewma * w.samples) / (w.samples + 8);
  let weight = 1 + shrunk * 0.65;
  const mean = w.sumR / w.samples;
  if (w.samples >= 12 && mean < -0.25) weight = Math.min(weight, 0.3);
  if (w.samples >= 4 && w.wins === 0) weight = Math.min(weight, 0.35);
  if (weight < 0.25) return 0.25;
  if (weight > 1.6) return 1.6;
  return weight;
}

export function recordResult(memory, row) {
  const id = row.patternId;
  const r = row.r;
  const w = memory.weights[id] || { ewma: 0, samples: 0, wins: 0, losses: 0, sumR: 0 };
  w.samples += 1;
  w.sumR += r;
  w.ewma = w.samples === 1 ? r : w.ewma * 0.9 + r * 0.1;
  if (r > 0) w.wins += 1;
  else w.losses += 1;
  memory.weights[id] = w;
  memory.history.push({
    symbol: row.symbol,
    interval: row.interval,
    patternId: id,
    name: row.name,
    direction: row.direction,
    r,
    outcome: row.outcome,
    at: row.at,
  });
  if (memory.history.length > 80) memory.history.splice(0, memory.history.length - 80);
}

/**
 * Проверяет открытые бумажные сделки этой пары.
 * Если в одной свече задеты и стоп, и цель, считается стоп.
 */
export function resolveOpen(memory, symbol, interval, candles) {
  const closed = [];
  const still = [];
  for (const trade of memory.open || []) {
    if (trade.symbol !== symbol || trade.interval !== interval) {
      still.push(trade);
      continue;
    }
    let done = null;
    for (const bar of candles) {
      if (bar.t <= trade.openedAt) continue;
      const hitStop = trade.direction === "long" ? bar.l <= trade.stop : bar.h >= trade.stop;
      const hitTarget = trade.direction === "long" ? bar.h >= trade.target : bar.l <= trade.target;
      if (hitStop || hitTarget) {
        const outcome = hitStop ? "stop" : "target";
        const exit = hitStop ? trade.stop : trade.target;
        const risk = Math.abs(trade.entry - trade.stop);
        const raw = risk > 0 ? (trade.direction === "long" ? exit - trade.entry : trade.entry - exit) / risk : 0;
        const r = raw - COST_R;
        done = { ...trade, outcome, r, at: bar.t };
        break;
      }
    }
    if (done) {
      recordResult(memory, done);
      closed.push(done);
    } else still.push(trade);
  }
  memory.open = still;
  return closed;
}

export function maybeOpen(memory, trade) {
  if (!trade) return false;
  const exists = (memory.open || []).some(
    (t) => t.symbol === trade.symbol && t.interval === trade.interval,
  );
  if (exists) return false;
  const sameBar = (memory.history || []).some(
    (h) => h.symbol === trade.symbol && h.at === trade.openedAt && h.patternId === trade.patternId,
  );
  if (sameBar) return false;
  const dup = (memory.open || []).some((t) => t.symbol === trade.symbol && t.openedAt === trade.openedAt);
  if (dup) return false;
  memory.open.push(trade);
  return true;
}

export function memorySummary(memory) {
  const rows = Object.entries(memory?.weights || {}).map(([id, w]) => ({
    id,
    samples: w.samples,
    wins: w.wins,
    losses: w.losses,
    meanR: w.samples ? w.sumR / w.samples : 0,
    weight: weightOf(memory, id),
  }));
  rows.sort((a, b) => b.samples - a.samples || a.meanR - b.meanR);
  return {
    rows,
    open: (memory.open || []).length,
    last: (memory.history || []).slice(-6).reverse(),
  };
}
