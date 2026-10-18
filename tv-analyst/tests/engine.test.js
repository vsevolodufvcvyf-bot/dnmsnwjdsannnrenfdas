import test from "node:test";
import assert from "node:assert/strict";
import { decide } from "../lib/decide.js";
import { step } from "../lib/engine.js";
import { emptyMemory, recordResult, weightOf } from "../lib/learn.js";
import { dropForming, mapInterval, parseBinanceKlines, parseKucoinCandles, parseOkxCandles, parseTvSymbol } from "../lib/market.js";
import { scoreNews } from "../lib/news.js";
import { classifyHarmonic, detectPatterns } from "../lib/patterns.js";
import { resampleFromEnd } from "../lib/indicators.js";

function shape(keys, n = null) {
  const last = n ?? keys[keys.length - 1][0] + 1;
  const priceAt = (i) => {
    if (i <= keys[0][0]) return keys[0][1];
    for (let k = 0; k < keys.length - 1; k++) {
      const [i0, p0] = keys[k];
      const [i1, p1] = keys[k + 1];
      if (i >= i0 && i <= i1) return p0 + ((p1 - p0) * (i - i0)) / (i1 - i0);
    }
    return keys[keys.length - 1][1];
  };
  const keySet = new Set(keys.map(([i]) => i));
  const candles = [];
  for (let i = 0; i < last; i++) {
    const price = priceAt(i);
    const peak = keySet.has(i);
    const high = peak ? price : price + 0.2;
    const low = peak ? price - 0.12 : price - 0.28;
    candles.push({
      t: 1_700_000_000_000 + i * 900_000,
      o: price,
      h: Math.max(high, price),
      l: Math.min(low, price),
      c: price,
      v: 100,
    });
  }
  return candles;
}

function forceBreak(candles, down) {
  const n = candles.length;
  const prev = candles[n - 2];
  const last = candles[n - 1];
  if (down) {
    prev.o = prev.c + 0.4;
    prev.c = prev.c;
    prev.h = prev.c + 0.5;
    prev.l = prev.c - 0.1;
    last.o = prev.c;
    last.c = prev.c - 2.2;
    last.h = prev.c + 0.05;
    last.l = last.c - 0.2;
  } else {
    prev.o = prev.c - 0.4;
    prev.h = prev.c + 0.1;
    prev.l = prev.c - 0.5;
    last.o = prev.c;
    last.c = prev.c + 2.2;
    last.l = prev.c - 0.05;
    last.h = last.c + 0.2;
  }
}

test("тикер TradingView разбирается для любой монеты", () => {
  assert.equal(parseTvSymbol("BINANCE:ETHUSDT").compact, "ETHUSDT");
  assert.equal(parseTvSymbol("BYBIT:SOLUSDT.P").base, "SOL");
  assert.equal(parseTvSymbol("OKX:BTC-USDT").binance, "BTCUSDT");
  assert.equal(parseTvSymbol("PEPEUSDT").base, "PEPE");
  assert.equal(parseTvSymbol("BINANCE:1000BONKUSDT").base, "1000BONK");
  assert.equal(mapInterval("15"), "15m");
  assert.equal(mapInterval("4ч"), "4h");
  assert.equal(mapInterval("1Д"), "1d");
});

test("свечи бирж приводятся к одному виду", () => {
  const binance = parseBinanceKlines([[1000, "10", "12", "9", "11", "5"]]);
  assert.equal(binance[0].h, 12);
  const okx = parseOkxCandles({ data: [["2000", "1", "3", "0.5", "2", "8"], ["1000", "1", "2", "0.4", "1.5", "4"]] });
  assert.deepEqual(okx.map((c) => c.t), [1000, 2000]);
  const kucoin = parseKucoinCandles({ data: [["2", "10", "11", "12", "9", "3"]] });
  assert.equal(kucoin[0].h, 12);
  assert.equal(kucoin[0].l, 9);
  assert.equal(kucoin[0].c, 11);
  const forming = dropForming([{ t: 0, o: 1, h: 1, l: 1, c: 1, v: 1 }, { t: 1_000_000, o: 1, h: 1, l: 1, c: 1, v: 1 }], "15m", 1_000_000);
  assert.equal(forming.length, 1);
});

test("ровный рынок не даёт фигуру", () => {
  const candles = Array.from({ length: 80 }, (_, i) => ({
    t: i * 900000,
    o: 100,
    h: 100,
    l: 100,
    c: 100,
    v: 10,
  }));
  assert.equal(detectPatterns(candles).length, 0);
  const view = decide(candles, null, null, emptyMemory());
  assert.equal(view.verdict, "wait");
  assert.equal(view.title, "ЖДАТЬ");
});

test("двойная вершина даёт один шорт и линию шеи", () => {
  const candles = shape([
    [0, 100],
    [12, 100],
    [30, 112],
    [46, 100],
    [62, 112],
    [78, 100.4],
    [79, 100.4],
  ]);
  forceBreak(candles, true);
  const found = detectPatterns(candles);
  const top = found.find((p) => p.id === "double_top");
  assert.ok(top, found.map((p) => p.id).join(","));
  assert.equal(top.direction, "short");
  assert.ok(top.stop > top.entry);
  assert.ok(top.target < top.entry);
  assert.ok(top.drawings.some((d) => d.role === "neck"));
  const view = decide(candles, null, { tone: "neutral", headlines: [] }, emptyMemory());
  assert.equal(view.verdict, "short");
  assert.equal(view.title, "ВНИЗ");
  assert.equal(view.pattern.id, "double_top");
});

test("двойное дно даёт лонг", () => {
  const candles = shape([
    [0, 110],
    [12, 110],
    [30, 98],
    [46, 110],
    [62, 98],
    [78, 109.6],
    [79, 109.6],
  ]);
  forceBreak(candles, false);
  const found = detectPatterns(candles);
  const bottom = found.find((p) => p.id === "double_bottom");
  assert.ok(bottom, found.map((p) => p.id).join(","));
  assert.equal(bottom.direction, "long");
  const view = decide(candles, null, null, emptyMemory());
  assert.equal(view.verdict, "long");
});

test("голова и плечи смотрит вниз", () => {
  const candles = shape([
    [0, 100],
    [18, 100],
    [28, 108],
    [38, 100],
    [50, 120],
    [62, 100],
    [74, 108],
    [86, 100.2],
    [87, 100.2],
  ]);
  forceBreak(candles, true);
  const found = detectPatterns(candles);
  const hs = found.find((p) => p.id === "head_shoulders");
  assert.ok(hs, found.map((p) => p.id).join(","));
  assert.equal(hs.direction, "short");
  assert.ok(hs.drawings.some((d) => d.label === "ГиП" || d.role === "neck"));
});

test("молот после падения отмечается", () => {
  const candles = [];
  for (let i = 0; i < 45; i++) {
    const price = 150 - i;
    candles.push({ t: i * 900000, o: price + 0.6, h: price + 0.8, l: price - 0.4, c: price, v: 80 });
  }
  candles.push({ t: 45 * 900000, o: 104.1, h: 104.5, l: 100.2, c: 104.35, v: 200 });
  const found = detectPatterns(candles);
  assert.ok(found.some((p) => p.id === "hammer" || p.id === "pin_bull"), found.map((p) => p.id).join(","));
});

test("гартли узнаётся по пропорциям", () => {
  const X = { price: 100 };
  const A = { price: 110 };
  const B = { price: 110 - 6.18 };
  const C = { price: B.price + 3.09 };
  const D = { price: 110 - 7.86 };
  const found = classifyHarmonic(X, A, B, C, D);
  assert.equal(found.id, "gartley_bull");
});

test("новости по монете красят тон и не путают чужой тикер", () => {
  const news = scoreNews(
    [
      { title: "Solana столкнулась с взломом моста", link: "https://example.com/a" },
      { title: "ETF по Solana одобрен", link: "https://example.com/b" },
      { title: "Рынок акций вырос", link: "https://example.com/c" },
    ],
    "SOL",
    "Solana",
  );
  assert.ok(news.headlines[0].mentions);
  assert.equal(news.headlines[0].tone, "bear");
  assert.equal(news.headlines[1].tone, "bull");
});

test("стоп по бумажной сделке снижает вес фигуры", () => {
  const memory = emptyMemory();
  const spec = parseTvSymbol("ETHUSDT");
  const candles = shape([
    [0, 100],
    [20, 100],
    [40, 112],
    [55, 100],
    [70, 112],
    [84, 100.5],
    [85, 100.5],
  ]);
  forceBreak(candles, true);
  const first = step(memory, candles, null, null, spec, "15m");
  assert.equal(first.opened, true);
  assert.equal(memory.open.length, 1);
  const trade = memory.open[0];
  const next = candles.concat([
    {
      t: candles[candles.length - 1].t + 900000,
      o: trade.entry,
      h: trade.stop + 0.2,
      l: trade.entry - 0.2,
      c: trade.stop,
      v: 100,
    },
  ]);
  const second = step(memory, next, null, null, spec, "15m");
  assert.equal(second.closed.length, 1);
  assert.equal(second.closed[0].outcome, "stop");
  assert.ok(weightOf(memory, "double_top") < 1);
  const row = memory.weights.double_top;
  assert.equal(row.losses, 1);
});

test("серия побед поднимает вес", () => {
  const memory = emptyMemory();
  for (let i = 0; i < 6; i++) recordResult(memory, { patternId: "hammer", name: "Молот", r: 0.8, outcome: "target", symbol: "BTCUSDT", interval: "15m", direction: "long", at: i });
  assert.ok(weightOf(memory, "hammer") > 1);
});

test("старший таймфрейм собирается с конца ряда", () => {
  const candles = Array.from({ length: 10 }, (_, i) => ({
    t: i,
    o: i,
    h: i + 1,
    l: i - 1,
    c: i + 0.5,
    v: 1,
  }));
  const out = resampleFromEnd(candles, 4);
  assert.equal(out.length, 2);
  assert.equal(out[1].c, candles[9].c);
  assert.equal(out[1].h, 10);
});
