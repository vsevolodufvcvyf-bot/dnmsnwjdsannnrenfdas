import { writeFileSync } from "node:fs";
import { decide } from "../lib/decide.js";
import { resampleFromEnd } from "../lib/indicators.js";
import { cloneMemory, emptyMemory, recordResult } from "../lib/learn.js";
import { parseBinanceKlines } from "../lib/market.js";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"];
const BARS = 2800;
const WINDOW = 220;
const INTERVAL = "15m";

async function history(symbol) {
  const all = new Map();
  let end = Date.now();
  while (all.size < BARS) {
    const url = `https://data-api.binance.vision/api/v3/klines?symbol=${symbol}&interval=${INTERVAL}&limit=1000&endTime=${end}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${symbol} ${res.status}`);
    const rows = await res.json();
    if (!Array.isArray(rows) || !rows.length) break;
    for (const candle of parseBinanceKlines(rows)) all.set(candle.t, candle);
    const first = rows[0][0];
    if (first >= end) break;
    end = first - 1;
    if (rows.length < 1000) break;
  }
  return [...all.values()].sort((a, b) => a.t - b.t).slice(-BARS);
}

function walk(candles, memory, learn) {
  const stats = { trades: 0, sumR: 0, wins: 0 };
  let open = null;
  for (let i = WINDOW; i < candles.length; i++) {
    const window = candles.slice(i - WINDOW, i + 1);
    const bar = window[window.length - 1];
    if (open && bar.t > open.openedAt) {
      const hitStop = open.direction === "long" ? bar.l <= open.stop : bar.h >= open.stop;
      const hitTarget = open.direction === "long" ? bar.h >= open.target : bar.l <= open.target;
      if (hitStop || hitTarget) {
        const exit = hitStop ? open.stop : open.target;
        const risk = Math.abs(open.entry - open.stop) || 1;
        const raw = open.direction === "long" ? (exit - open.entry) / risk : (open.entry - exit) / risk;
        const r = raw - 0.1;
        stats.trades += 1;
        stats.sumR += r;
        if (r > 0) stats.wins += 1;
        if (learn) {
          recordResult(memory, {
            patternId: open.patternId,
            name: open.name,
            direction: open.direction,
            r,
            outcome: hitStop ? "stop" : "target",
            symbol: open.symbol,
            interval: INTERVAL,
            at: bar.t,
          });
        }
        open = null;
      }
    }
    if (!open) {
      const analysis = decide(window, resampleFromEnd(window, 4), null, memory);
      if (analysis.verdict !== "wait" && analysis.pattern) {
        open = {
          symbol: "train",
          patternId: analysis.pattern.id,
          name: analysis.pattern.name,
          direction: analysis.verdict,
          entry: analysis.pattern.entry,
          stop: analysis.pattern.stop,
          target: analysis.pattern.target,
          openedAt: bar.t,
        };
      }
    }
  }
  return stats;
}

const memory = emptyMemory();
const train = { trades: 0, sumR: 0, wins: 0 };
const test = { trades: 0, sumR: 0, wins: 0 };
const perSymbol = [];

for (const symbol of SYMBOLS) {
  const started = Date.now();
  const candles = await history(symbol);
  const split = Math.floor(candles.length * 0.7);
  const trainPart = walk(candles.slice(0, split), memory, true);
  const frozen = cloneMemory(memory);
  const testPart = walk(candles.slice(split - WINDOW), frozen, false);
  train.trades += trainPart.trades;
  train.sumR += trainPart.sumR;
  train.wins += trainPart.wins;
  test.trades += testPart.trades;
  test.sumR += testPart.sumR;
  test.wins += testPart.wins;
  perSymbol.push({
    symbol,
    bars: candles.length,
    train: trainPart,
    test: testPart,
    seconds: Math.round((Date.now() - started) / 1000),
  });
  console.log(symbol, "bars", candles.length, "train", trainPart.trades, "test", testPart.trades, "sec", perSymbol.at(-1).seconds);
}

const mean = (bag) => (bag.trades ? bag.sumR / bag.trades : 0);
const seed = {
  version: 1,
  note: `Веса сняты с 15-минуток ${SYMBOLS.join(", ")}. На контрольном куске средний результат ${mean(test).toFixed(2)}R за ${test.trades} сделок.`,
  trainedOn: SYMBOLS,
  test: {
    symbols: SYMBOLS,
    interval: INTERVAL,
    trades: test.trades,
    wins: test.wins,
    meanR: Number(mean(test).toFixed(3)),
    trainTrades: train.trades,
    trainMeanR: Number(mean(train).toFixed(3)),
  },
  weights: memory.weights,
  open: [],
  history: [],
};

writeFileSync(new URL("../lib/seed.js", import.meta.url), `/** Сгенерировано scripts/seed.mjs. */\nexport const SEED = ${JSON.stringify(seed, null, 2)};\n`);

const lines = [
  "# Прогон истории",
  "",
  `Интервал ${INTERVAL}, окно ${WINDOW} свечей, монеты ${SYMBOLS.join(", ")}.`,
  "Первые 70% баров учат веса. Последние 30% идут контролем и веса уже не двигают.",
  "Из каждого результата вычтено 0.1R на комиссию и проскальзывание.",
  "",
  `Обучение: ${train.trades} сделок, средний ${mean(train).toFixed(3)}R, в плюс ${train.wins}.`,
  `Контроль: ${test.trades} сделок, средний ${mean(test).toFixed(3)}R, в плюс ${test.wins}.`,
  "",
  "| Монета | Баров | Обучение, сделок | Обучение, R | Контроль, сделок | Контроль, R |",
  "| --- | --- | --- | --- | --- | --- |",
];
for (const row of perSymbol) {
  const tm = row.train.trades ? row.train.sumR / row.train.trades : 0;
  const em = row.test.trades ? row.test.sumR / row.test.trades : 0;
  lines.push(`| ${row.symbol} | ${row.bars} | ${row.train.trades} | ${tm.toFixed(3)} | ${row.test.trades} | ${em.toFixed(3)} |`);
}
lines.push("", "Веса с обучения записаны в `lib/seed.js`. Отрицательное число значит, что на этом куске схемы в сумме не обогнали комиссию.");
writeFileSync(new URL("../SEED_REPORT.md", import.meta.url), lines.join("\n") + "\n");
console.log("control meanR", mean(test).toFixed(3), "trades", test.trades);
