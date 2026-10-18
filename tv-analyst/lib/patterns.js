/**
 * Классические фигуры, свечи, RSI-дивергенция и гармоники.
 * Сигнал только на последней закрытой свече и только после пробоя или подтверждения.
 * Незавершённая фигура не рисуется.
 */
import {
  atr,
  rsi,
  smaAt,
  pivotHighs,
  pivotLows,
  alternating,
  linreg,
  relDiff,
  minLow,
  maxHigh,
  averageVolume,
} from "./indicators.js";

export const PIVOT_LEFT = 3;
export const PIVOT_RIGHT = 3;
const MIN_RR = 0.7;

export const CATALOG = [
  ["double_top", "Двойная вершина", "Фигуры"],
  ["double_bottom", "Двойное дно", "Фигуры"],
  ["triple_top", "Тройная вершина", "Фигуры"],
  ["triple_bottom", "Тройное дно", "Фигуры"],
  ["head_shoulders", "Голова и плечи", "Фигуры"],
  ["inverse_hs", "Перевёрнутая голова и плечи", "Фигуры"],
  ["rising_wedge", "Восходящий клин", "Фигуры"],
  ["falling_wedge", "Нисходящий клин", "Фигуры"],
  ["asc_triangle", "Восходящий треугольник", "Фигуры"],
  ["desc_triangle", "Нисходящий треугольник", "Фигуры"],
  ["sym_triangle", "Симметричный треугольник", "Фигуры"],
  ["exp_triangle", "Расширяющийся треугольник", "Фигуры"],
  ["bull_flag", "Бычий флаг", "Фигуры"],
  ["bear_flag", "Медвежий флаг", "Фигуры"],
  ["bull_pennant", "Бычий вымпел", "Фигуры"],
  ["bear_pennant", "Медвежий вымпел", "Фигуры"],
  ["range_up", "Выход из диапазона вверх", "Фигуры"],
  ["range_down", "Выход из диапазона вниз", "Фигуры"],
  ["trend_down", "Слом тренда вниз", "Структура"],
  ["trend_up", "Слом тренда вверх", "Структура"],
  ["channel_down", "Слом восходящего канала", "Фигуры"],
  ["channel_up", "Слом нисходящего канала", "Фигуры"],
  ["rounding_top", "Круглая вершина", "Фигуры"],
  ["rounding_bottom", "Круглое дно", "Фигуры"],
  ["cup_handle", "Чаша с ручкой", "Фигуры"],
  ["inv_cup_handle", "Перевёрнутая чаша с ручкой", "Фигуры"],
  ["diamond_top", "Бриллиант сверху", "Фигуры"],
  ["diamond_bottom", "Бриллиант снизу", "Фигуры"],
  ["hammer", "Молот", "Свечи"],
  ["inv_hammer", "Перевёрнутый молот", "Свечи"],
  ["hanging", "Повешенный", "Свечи"],
  ["shooting", "Падающая звезда", "Свечи"],
  ["bull_engulf", "Бычье поглощение", "Свечи"],
  ["bear_engulf", "Медвежье поглощение", "Свечи"],
  ["morning_star", "Утренняя звезда", "Свечи"],
  ["evening_star", "Вечерняя звезда", "Свечи"],
  ["bull_harami", "Бычья харами", "Свечи"],
  ["bear_harami", "Медвежья харами", "Свечи"],
  ["piercing", "Просвет в облаках", "Свечи"],
  ["dark_cloud", "Завеса из тёмных облаков", "Свечи"],
  ["three_soldiers", "Три белых солдата", "Свечи"],
  ["three_crows", "Три чёрные вороны", "Свечи"],
  ["pin_bull", "Бычий пин-бар", "Свечи"],
  ["pin_bear", "Медвежий пин-бар", "Свечи"],
  ["tweezer_top", "Пинцет сверху", "Свечи"],
  ["tweezer_bottom", "Пинцет снизу", "Свечи"],
  ["inside_up", "Выход из внутренней свечи вверх", "Свечи"],
  ["inside_down", "Выход из внутренней свечи вниз", "Свечи"],
  ["doji_low", "Доджи у минимума", "Свечи"],
  ["doji_high", "Доджи у максимума", "Свечи"],
  ["rsi_bull", "Бычья дивергенция RSI", "Индикаторы"],
  ["rsi_bear", "Медвежья дивергенция RSI", "Индикаторы"],
  ["gartley_bull", "Бычий Гартли", "Гармоники"],
  ["gartley_bear", "Медвежий Гартли", "Гармоники"],
  ["bat_bull", "Бычий Бат", "Гармоники"],
  ["bat_bear", "Медвежий Бат", "Гармоники"],
  ["butterfly_bull", "Бычья бабочка", "Гармоники"],
  ["butterfly_bear", "Медвежья бабочка", "Гармоники"],
  ["crab_bull", "Бычий краб", "Гармоники"],
  ["crab_bear", "Медвежий краб", "Гармоники"],
  ["impulse_up", "Импульс вверх", "Движение"],
  ["impulse_down", "Импульс вниз", "Движение"],
];

const NAMES = Object.fromEntries(CATALOG.map(([id, name]) => [id, name]));
export function patternName(id) {
  return NAMES[id] || id;
}

function hline(role, price, i1, i2, label) {
  return { type: "hline", role, price, i1, i2, label };
}
function seg(role, i1, p1, i2, p2, label) {
  return { type: "segment", role, i1, price1: p1, i2, price2: p2, label };
}

function pack(direction, entry, stop, target, atrValue) {
  if (![entry, stop, target, atrValue].every(Number.isFinite)) return null;
  const risk = Math.abs(entry - stop);
  if (!(risk > 0) || risk < atrValue * 0.12) return null;
  if (risk > atrValue * 40) return null;
  if (direction === "long" && !(stop < entry && target > entry)) return null;
  if (direction === "short" && !(stop > entry && target < entry)) return null;
  const rr = Math.abs(target - entry) / risk;
  if (rr < MIN_RR) return null;
  return { entry, stop, target, rr };
}

function signal(c, spec) {
  const entry = c.candles[c.last].c;
  const lv = pack(spec.direction, entry, spec.stop, spec.target, c.atr);
  if (!lv) return null;
  return {
    id: spec.id,
    name: NAMES[spec.id] || spec.id,
    direction: spec.direction,
    quality: Math.max(0.35, Math.min(0.93, spec.quality)),
    reason: spec.reason,
    ...lv,
    drawings: [
      ...(spec.drawings || []),
      hline("entry", lv.entry, Math.max(0, c.last - 12), c.last, "вход"),
      hline("stop", lv.stop, Math.max(0, c.last - 12), c.last, "стоп"),
      hline("target", lv.target, Math.max(0, c.last - 12), c.last, "цель"),
    ],
  };
}

function twoR(direction, entry, stop) {
  const risk = Math.abs(entry - stop);
  return direction === "long" ? entry + risk * 2 : entry - risk * 2;
}

function brokeDown(candles, levelAt) {
  const last = candles.length - 1;
  if (last < 1) return false;
  return candles[last].c < levelAt(last) && candles[last - 1].c >= levelAt(last - 1);
}
function brokeUp(candles, levelAt) {
  const last = candles.length - 1;
  if (last < 1) return false;
  return candles[last].c > levelAt(last) && candles[last - 1].c <= levelAt(last - 1);
}

function volumeNote(c) {
  const avg = averageVolume(c.candles, c.last, 20);
  if (avg > 0 && c.candles[c.last].v >= avg * 1.3) return " Объём на пробое выше среднего.";
  return "";
}

function makeCtx(candles) {
  const last = candles.length - 1;
  const atrArr = atr(candles, 14);
  const fallback = Math.max(candles[last].h - candles[last].l, Math.abs(candles[last].c) * 0.0015);
  return {
    candles,
    last,
    atr: atrArr[last] || fallback,
    atrArr,
    rsi: rsi(candles, 14),
    highs: pivotHighs(candles, PIVOT_LEFT, PIVOT_RIGHT),
    lows: pivotLows(candles, PIVOT_LEFT, PIVOT_RIGHT),
  };
}

function neckBetween(candles, i1, i2) {
  return minLow(candles, i1 + 1, i2 - 1);
}
function roofBetween(candles, i1, i2) {
  return maxHigh(candles, i1 + 1, i2 - 1);
}

function similarPeaks(a, b) {
  return relDiff(a, b) <= 0.025;
}

function doubleTop(c) {
  const { candles, last, highs, atr: a } = c;
  let best = null;
  for (let bi = highs.length - 1; bi >= 1; bi--) {
    const b = highs[bi];
    if (last - b.i > 48) break;
    if (last - b.i < PIVOT_RIGHT) continue;
    for (let ai = bi - 1; ai >= 0; ai--) {
      const left = highs[ai];
      const gap = b.i - left.i;
      if (gap > 70) break;
      if (gap < 6) continue;
      if (!similarPeaks(left.price, b.price)) continue;
      const neck = neckBetween(candles, left.i, b.i);
      if (!Number.isFinite(neck.price)) continue;
      const peak = (left.price + b.price) / 2;
      const depth = peak - neck.price;
      if (depth < Math.max(a * 1.15, peak * 0.004)) continue;
      const level = () => neck.price;
      if (!brokeDown(candles, level)) continue;
      const target = neck.price - depth;
      const stop = Math.max(left.price, b.price) + a * 0.15;
      const quality = 0.72 + Math.max(0, 0.12 - relDiff(left.price, b.price) * 4);
      const item = signal(c, {
        id: "double_top",
        direction: "short",
        quality,
        stop,
        target,
        reason: `Две вершины на одном уровне, закрытие под линией шеи.${volumeNote(c)}`,
        drawings: [
          seg("pattern", left.i, left.price, b.i, b.price, "вершины"),
          hline("neck", neck.price, left.i, last, "шея"),
        ],
      });
      if (item && (!best || item.quality > best.quality)) best = item;
    }
  }
  return best;
}

function doubleBottom(c) {
  const { candles, last, lows, atr: a } = c;
  let best = null;
  for (let bi = lows.length - 1; bi >= 1; bi--) {
    const b = lows[bi];
    if (last - b.i > 48) break;
    if (last - b.i < PIVOT_RIGHT) continue;
    for (let ai = bi - 1; ai >= 0; ai--) {
      const left = lows[ai];
      const gap = b.i - left.i;
      if (gap > 70) break;
      if (gap < 6) continue;
      if (!similarPeaks(left.price, b.price)) continue;
      const roof = roofBetween(candles, left.i, b.i);
      if (!Number.isFinite(roof.price)) continue;
      const trough = (left.price + b.price) / 2;
      const depth = roof.price - trough;
      if (depth < Math.max(a * 1.15, trough * 0.004)) continue;
      if (!brokeUp(candles, () => roof.price)) continue;
      const target = roof.price + depth;
      const stop = Math.min(left.price, b.price) - a * 0.15;
      const quality = 0.72 + Math.max(0, 0.12 - relDiff(left.price, b.price) * 4);
      const item = signal(c, {
        id: "double_bottom",
        direction: "long",
        quality,
        stop,
        target,
        reason: `Два минимума на одном уровне, закрытие над линией шеи.${volumeNote(c)}`,
        drawings: [
          seg("pattern", left.i, left.price, b.i, b.price, "дно"),
          hline("neck", roof.price, left.i, last, "шея"),
        ],
      });
      if (item && (!best || item.quality > best.quality)) best = item;
    }
  }
  return best;
}

function tripleTop(c) {
  const { candles, last, highs, atr: a } = c;
  const hs = highs.filter((h) => last - h.i <= 90);
  for (let i = hs.length - 1; i >= 2; i--) {
    const c3 = hs[i];
    const c2 = hs[i - 1];
    const c1 = hs[i - 2];
    if (last - c3.i > 40 || c3.i - c1.i > 90 || c3.i - c1.i < 12) continue;
    if (!similarPeaks(c1.price, c2.price) || !similarPeaks(c2.price, c3.price)) continue;
    const neck = neckBetween(candles, c1.i, c3.i);
    const peak = (c1.price + c2.price + c3.price) / 3;
    const depth = peak - neck.price;
    if (depth < a * 1.2) continue;
    if (!brokeDown(candles, () => neck.price)) continue;
    return signal(c, {
      id: "triple_top",
      direction: "short",
      quality: 0.76,
      stop: Math.max(c1.price, c2.price, c3.price) + a * 0.15,
      target: neck.price - depth,
      reason: `Три вершины на одном уровне, шея пробита вниз.${volumeNote(c)}`,
      drawings: [
        seg("pattern", c1.i, c1.price, c2.i, c2.price, ""),
        seg("pattern", c2.i, c2.price, c3.i, c3.price, "тройная вершина"),
        hline("neck", neck.price, c1.i, last, "шея"),
      ],
    });
  }
  return null;
}

function tripleBottom(c) {
  const { candles, last, lows, atr: a } = c;
  const ls = lows.filter((h) => last - h.i <= 90);
  for (let i = ls.length - 1; i >= 2; i--) {
    const c3 = ls[i];
    const c2 = ls[i - 1];
    const c1 = ls[i - 2];
    if (last - c3.i > 40 || c3.i - c1.i > 90 || c3.i - c1.i < 12) continue;
    if (!similarPeaks(c1.price, c2.price) || !similarPeaks(c2.price, c3.price)) continue;
    const roof = roofBetween(candles, c1.i, c3.i);
    const trough = (c1.price + c2.price + c3.price) / 3;
    const depth = roof.price - trough;
    if (depth < a * 1.2) continue;
    if (!brokeUp(candles, () => roof.price)) continue;
    return signal(c, {
      id: "triple_bottom",
      direction: "long",
      quality: 0.76,
      stop: Math.min(c1.price, c2.price, c3.price) - a * 0.15,
      target: roof.price + depth,
      reason: `Три минимума на одном уровне, шея пробита вверх.${volumeNote(c)}`,
      drawings: [
        seg("pattern", c1.i, c1.price, c2.i, c2.price, ""),
        seg("pattern", c2.i, c2.price, c3.i, c3.price, "тройное дно"),
        hline("neck", roof.price, c1.i, last, "шея"),
      ],
    });
  }
  return null;
}

function headShoulders(c) {
  const { candles, last, highs, atr: a } = c;
  const hs = highs.filter((h) => last - h.i <= 100);
  for (let i = hs.length - 1; i >= 2; i--) {
    const right = hs[i];
    const head = hs[i - 1];
    const left = hs[i - 2];
    if (last - right.i > 36 || right.i - left.i < 10) continue;
    if (!(head.price > left.price && head.price > right.price)) continue;
    if (relDiff(left.price, right.price) > 0.04) continue;
    const lift = head.price - Math.max(left.price, right.price);
    if (lift < a * 0.8) continue;
    const t1 = neckBetween(candles, left.i, head.i);
    const t2 = neckBetween(candles, head.i, right.i);
    if (!Number.isFinite(t1.price) || !Number.isFinite(t2.price)) continue;
    const slope = (t2.price - t1.price) / Math.max(1, t2.i - t1.i);
    const neckAt = (i) => t2.price + slope * (i - t2.i);
    if (!brokeDown(candles, neckAt)) continue;
    const height = head.price - neckAt(head.i);
    if (height < a) continue;
    return signal(c, {
      id: "head_shoulders",
      direction: "short",
      quality: 0.8,
      stop: head.price + a * 0.12,
      target: neckAt(last) - height,
      reason: `Голова выше плеч, закрытие под линией шеи.${volumeNote(c)}`,
      drawings: [
        seg("pattern", left.i, left.price, head.i, head.price, ""),
        seg("pattern", head.i, head.price, right.i, right.price, "ГиП"),
        seg("neck", t1.i, t1.price, last, neckAt(last), "шея"),
      ],
    });
  }
  return null;
}

function inverseHs(c) {
  const { candles, last, lows, atr: a } = c;
  const ls = lows.filter((h) => last - h.i <= 100);
  for (let i = ls.length - 1; i >= 2; i--) {
    const right = ls[i];
    const head = ls[i - 1];
    const left = ls[i - 2];
    if (last - right.i > 36 || right.i - left.i < 10) continue;
    if (!(head.price < left.price && head.price < right.price)) continue;
    if (relDiff(left.price, right.price) > 0.04) continue;
    const lift = Math.min(left.price, right.price) - head.price;
    if (lift < a * 0.8) continue;
    const t1 = roofBetween(candles, left.i, head.i);
    const t2 = roofBetween(candles, head.i, right.i);
    const slope = (t2.price - t1.price) / Math.max(1, t2.i - t1.i);
    const neckAt = (i) => t2.price + slope * (i - t2.i);
    if (!brokeUp(candles, neckAt)) continue;
    const height = neckAt(head.i) - head.price;
    if (height < a) continue;
    return signal(c, {
      id: "inverse_hs",
      direction: "long",
      quality: 0.8,
      stop: head.price - a * 0.12,
      target: neckAt(last) + height,
      reason: `Перевёрнутая голова и плечи, закрытие над линией шеи.${volumeNote(c)}`,
      drawings: [
        seg("pattern", left.i, left.price, head.i, head.price, ""),
        seg("pattern", head.i, head.price, right.i, right.price, "перевёрнутая ГиП"),
        seg("neck", t1.i, t1.price, last, neckAt(last), "шея"),
      ],
    });
  }
  return null;
}

function lineTouches(points, line, atrValue) {
  if (!line) return false;
  return points.every((p) => Math.abs(p.price - line.at(p.i)) <= atrValue * 0.9);
}

function geometry(c) {
  const highs = c.highs.filter((p) => c.last - p.i <= 80).slice(-4);
  const lows = c.lows.filter((p) => c.last - p.i <= 80).slice(-4);
  if (highs.length < 3 || lows.length < 3) return null;
  const hs = linreg(highs);
  const ls = linreg(lows);
  if (!hs || !ls) return null;
  if (!lineTouches(highs, hs, c.atr) || !lineTouches(lows, ls, c.atr)) return null;
  const i0 = Math.min(highs[0].i, lows[0].i);
  const span = c.last - i0;
  if (span < 16) return null;
  const w0 = hs.at(i0) - ls.at(i0);
  const w1 = hs.at(c.last) - ls.at(c.last);
  if (!(w0 > 0)) return null;
  const slopeUnit = c.atr / span;
  return { highs, lows, hs, ls, i0, w0, w1, slopeUnit };
}

function wedgeOrTriangle(c) {
  const g = geometry(c);
  if (!g || !(g.w1 > 0) || g.w1 > g.w0 * 0.72) return null;
  const { hs, ls, slopeUnit, w0, i0, highs, lows } = g;
  const up = hs.slope > slopeUnit * 0.25 && ls.slope > slopeUnit * 0.25;
  const down = hs.slope < -slopeUnit * 0.25 && ls.slope < -slopeUnit * 0.25;
  const flatHigh = Math.abs(hs.slope) < slopeUnit * 0.35;
  const flatLow = Math.abs(ls.slope) < slopeUnit * 0.35;
  const risingLows = ls.slope > slopeUnit * 0.35;
  const fallingHighs = hs.slope < -slopeUnit * 0.35;
  const drawings = [
    seg("pattern", i0, hs.at(i0), c.last, hs.at(c.last), ""),
    seg("pattern", i0, ls.at(i0), c.last, ls.at(c.last), ""),
  ];
  if (up && brokeDown(c.candles, ls.at.bind(ls))) {
    return signal(c, {
      id: "rising_wedge",
      direction: "short",
      quality: 0.7,
      stop: Math.max(...highs.map((p) => p.price)) + c.atr * 0.1,
      target: c.candles[c.last].c - w0,
      reason: `Восходящий клин сузился и закрытие ушло под нижнюю границу.${volumeNote(c)}`,
      drawings,
    });
  }
  if (down && brokeUp(c.candles, hs.at.bind(hs))) {
    return signal(c, {
      id: "falling_wedge",
      direction: "long",
      quality: 0.7,
      stop: Math.min(...lows.map((p) => p.price)) - c.atr * 0.1,
      target: c.candles[c.last].c + w0,
      reason: `Нисходящий клин сузился и закрытие ушло над верхней границей.${volumeNote(c)}`,
      drawings,
    });
  }
  if (flatHigh && risingLows && brokeUp(c.candles, hs.at.bind(hs))) {
    return signal(c, {
      id: "asc_triangle",
      direction: "long",
      quality: 0.7,
      stop: Math.min(...lows.map((p) => p.price)) - c.atr * 0.1,
      target: c.candles[c.last].c + w0,
      reason: `Восходящий треугольник: ровные вершины, растущие минимумы, выход вверх.${volumeNote(c)}`,
      drawings,
    });
  }
  if (flatLow && fallingHighs && brokeDown(c.candles, ls.at.bind(ls))) {
    return signal(c, {
      id: "desc_triangle",
      direction: "short",
      quality: 0.7,
      stop: Math.max(...highs.map((p) => p.price)) + c.atr * 0.1,
      target: c.candles[c.last].c - w0,
      reason: `Нисходящий треугольник: ровные минимумы, падающие вершины, выход вниз.${volumeNote(c)}`,
      drawings,
    });
  }
  if (fallingHighs && risingLows && !flatHigh && !flatLow) {
    if (brokeUp(c.candles, hs.at.bind(hs))) {
      return signal(c, {
        id: "sym_triangle",
        direction: "long",
        quality: 0.64,
        stop: Math.min(...lows.map((p) => p.price)) - c.atr * 0.1,
        target: c.candles[c.last].c + w0 * 0.8,
        reason: `Симметричный треугольник пробит вверх.${volumeNote(c)}`,
        drawings,
      });
    }
    if (brokeDown(c.candles, ls.at.bind(ls))) {
      return signal(c, {
        id: "sym_triangle",
        direction: "short",
        quality: 0.64,
        stop: Math.max(...highs.map((p) => p.price)) + c.atr * 0.1,
        target: c.candles[c.last].c - w0 * 0.8,
        reason: `Симметричный треугольник пробит вниз.${volumeNote(c)}`,
        drawings,
      });
    }
  }
  return null;
}

function channel(c) {
  const g = geometry(c);
  if (!g) return null;
  const ratio = g.w1 / g.w0;
  if (ratio < 0.82 || ratio > 1.25) return null;
  const { hs, ls, slopeUnit, i0, highs, lows } = g;
  const same =
    Math.abs(hs.slope - ls.slope) < slopeUnit * 0.7 &&
    ((hs.slope > slopeUnit * 0.3 && ls.slope > slopeUnit * 0.3) ||
      (hs.slope < -slopeUnit * 0.3 && ls.slope < -slopeUnit * 0.3));
  if (!same) return null;
  const drawings = [
    seg("pattern", i0, hs.at(i0), c.last, hs.at(c.last), ""),
    seg("pattern", i0, ls.at(i0), c.last, ls.at(c.last), "канал"),
  ];
  if (hs.slope > 0 && brokeDown(c.candles, ls.at.bind(ls))) {
    return signal(c, {
      id: "channel_down",
      direction: "short",
      quality: 0.66,
      stop: Math.max(...highs.map((p) => p.price)) + c.atr * 0.1,
      target: c.candles[c.last].c - (hs.at(c.last) - ls.at(c.last)),
      reason: `Цена вышла вниз из восходящего канала.${volumeNote(c)}`,
      drawings,
    });
  }
  if (hs.slope < 0 && brokeUp(c.candles, hs.at.bind(hs))) {
    return signal(c, {
      id: "channel_up",
      direction: "long",
      quality: 0.66,
      stop: Math.min(...lows.map((p) => p.price)) - c.atr * 0.1,
      target: c.candles[c.last].c + (hs.at(c.last) - ls.at(c.last)),
      reason: `Цена вышла вверх из нисходящего канала.${volumeNote(c)}`,
      drawings,
    });
  }
  return null;
}

function expanding(c) {
  const g = geometry(c);
  if (!g || g.w1 < g.w0 * 1.35) return null;
  if (!(g.hs.slope > g.slopeUnit * 0.2 && g.ls.slope < -g.slopeUnit * 0.2)) return null;
  const lastHigh = g.highs[g.highs.length - 1];
  const lastLow = g.lows[g.lows.length - 1];
  if (brokeDown(c.candles, () => lastLow.price)) {
    return signal(c, {
      id: "exp_triangle",
      direction: "short",
      quality: 0.62,
      stop: lastHigh.price + c.atr * 0.1,
      target: c.candles[c.last].c - (lastHigh.price - lastLow.price) * 0.6,
      reason: `Расширяющийся треугольник, закрытие под последним минимумом.${volumeNote(c)}`,
      drawings: [seg("pattern", g.i0, g.hs.at(g.i0), c.last, g.hs.at(c.last), "расширение")],
    });
  }
  if (brokeUp(c.candles, () => lastHigh.price)) {
    return signal(c, {
      id: "exp_triangle",
      direction: "long",
      quality: 0.62,
      stop: lastLow.price - c.atr * 0.1,
      target: c.candles[c.last].c + (lastHigh.price - lastLow.price) * 0.6,
      reason: `Расширяющийся треугольник, закрытие над последней вершиной.${volumeNote(c)}`,
      drawings: [seg("pattern", g.i0, g.ls.at(g.i0), c.last, g.ls.at(c.last), "расширение")],
    });
  }
  return null;
}

function findPole(c) {
  const { candles, last, atr: a } = c;
  let best = null;
  for (let len = 4; len <= 10; len++) {
    const end = last - 5;
    const start = end - len;
    if (start < 1) continue;
    const move = candles[end].c - candles[start].o;
    if (Math.abs(move) < a * 2.6) continue;
    if (!best || Math.abs(move) > Math.abs(best.move)) best = { start, end, move };
  }
  return best;
}

function flagFamily(c) {
  const pole = findPole(c);
  if (!pole) return null;
  const { candles, last, atr: a } = c;
  const from = pole.end + 1;
  const to = last - 1;
  if (to - from < 3) return null;
  let hi = -Infinity;
  let lo = Infinity;
  const highs = [];
  const lows = [];
  for (let i = from; i <= to; i++) {
    if (candles[i].h > hi) hi = candles[i].h;
    if (candles[i].l < lo) lo = candles[i].l;
    highs.push({ i, price: candles[i].h });
    lows.push({ i, price: candles[i].l });
  }
  const range = hi - lo;
  if (range > Math.abs(pole.move) * 0.55 || range > a * 2.4) return null;
  const up = pole.move > 0;
  const mid = Math.floor((from + to) / 2);
  let early = 0;
  let late = 0;
  for (let i = from; i <= to; i++) {
    const span = candles[i].h - candles[i].l;
    if (i <= mid) early = Math.max(early, span);
    else late = Math.max(late, span);
  }
  const pennant = late < early * 0.85;
  if (up && brokeUp(candles, () => hi)) {
    return signal(c, {
      id: pennant ? "bull_pennant" : "bull_flag",
      direction: "long",
      quality: 0.68,
      stop: lo - a * 0.08,
      target: candles[last].c + Math.abs(pole.move),
      reason: `${pennant ? "Бычий вымпел" : "Бычий флаг"} после импульса, выход вверх.${volumeNote(c)}`,
      drawings: [
        seg("pattern", pole.start, candles[pole.start].o, pole.end, candles[pole.end].c, "древко"),
        hline("neck", hi, from, last, "флаг"),
      ],
    });
  }
  if (!up && brokeDown(candles, () => lo)) {
    return signal(c, {
      id: pennant ? "bear_pennant" : "bear_flag",
      direction: "short",
      quality: 0.68,
      stop: hi + a * 0.08,
      target: candles[last].c - Math.abs(pole.move),
      reason: `${pennant ? "Медвежий вымпел" : "Медвежий флаг"} после импульса, выход вниз.${volumeNote(c)}`,
      drawings: [
        seg("pattern", pole.start, candles[pole.start].o, pole.end, candles[pole.end].c, "древко"),
        hline("neck", lo, from, last, "флаг"),
      ],
    });
  }
  return null;
}

function rangeBreak(c) {
  const { candles, last, highs, lows, atr: a } = c;
  const hs = highs.filter((p) => last - p.i <= 60 && last - p.i >= PIVOT_RIGHT);
  const ls = lows.filter((p) => last - p.i <= 60 && last - p.i >= PIVOT_RIGHT);
  if (hs.length < 2 || ls.length < 2) return null;
  const top = hs.slice(-2);
  const bot = ls.slice(-2);
  if (!similarPeaks(top[0].price, top[1].price) || !similarPeaks(bot[0].price, bot[1].price)) return null;
  const roof = (top[0].price + top[1].price) / 2;
  const floor = (bot[0].price + bot[1].price) / 2;
  const height = roof - floor;
  if (height < a * 1.4) return null;
  const i0 = Math.min(top[0].i, bot[0].i);
  if (brokeUp(candles, () => roof)) {
    return signal(c, {
      id: "range_up",
      direction: "long",
      quality: 0.66,
      stop: floor,
      target: roof + height,
      reason: `Диапазон пробит вверх.${volumeNote(c)}`,
      drawings: [
        hline("pattern", roof, i0, last, "край"),
        hline("pattern", floor, i0, last, ""),
      ],
    });
  }
  if (brokeDown(candles, () => floor)) {
    return signal(c, {
      id: "range_down",
      direction: "short",
      quality: 0.66,
      stop: roof,
      target: floor - height,
      reason: `Диапазон пробит вниз.${volumeNote(c)}`,
      drawings: [
        hline("pattern", roof, i0, last, ""),
        hline("pattern", floor, i0, last, "край"),
      ],
    });
  }
  return null;
}

function trendChange(c) {
  const { candles, last, highs, lows, atr: a } = c;
  if (highs.length < 2 || lows.length < 2) return null;
  const h1 = highs[highs.length - 2];
  const h2 = highs[highs.length - 1];
  const l1 = lows[lows.length - 2];
  const l2 = lows[lows.length - 1];
  if (last - l2.i > 30 || last - l2.i < 1) {
    /* checked below per side */
  }
  if (h2.price > h1.price && l2.price > l1.price && last - l2.i <= 28 && last - l2.i >= 2 && brokeDown(candles, () => l2.price)) {
    const depth = h2.price - l2.price;
    if (depth >= a) {
      return signal(c, {
        id: "trend_down",
        direction: "short",
        quality: 0.67,
        stop: h2.price + a * 0.1,
        target: l2.price - depth,
        reason: "Рост с более высокими минимумами сломан: закрытие под последним минимумом.",
        drawings: [seg("pattern", l1.i, l1.price, l2.i, l2.price, "слом"), hline("neck", l2.price, l2.i, last, "минимум")],
      });
    }
  }
  if (h2.price < h1.price && l2.price < l1.price && last - h2.i <= 28 && last - h2.i >= 2 && brokeUp(candles, () => h2.price)) {
    const depth = h2.price - l2.price;
    if (depth >= a) {
      return signal(c, {
        id: "trend_up",
        direction: "long",
        quality: 0.67,
        stop: l2.price - a * 0.1,
        target: h2.price + depth,
        reason: "Падение с более низкими вершинами сломано: закрытие над последней вершиной.",
        drawings: [seg("pattern", h1.i, h1.price, h2.i, h2.price, "слом"), hline("neck", h2.price, h2.i, last, "вершина")],
      });
    }
  }
  return null;
}

function rounding(c, side) {
  const pivots = side === "top" ? c.highs : c.lows;
  const pts = pivots.filter((p) => c.last - p.i <= 90);
  if (pts.length < 4) return null;
  const use = pts.slice(-5);
  let peakAt = 0;
  for (let i = 1; i < use.length; i++) {
    if (side === "top" ? use[i].price > use[peakAt].price : use[i].price < use[peakAt].price) peakAt = i;
  }
  if (peakAt === 0 || peakAt === use.length - 1) return null;
  for (let i = 1; i <= peakAt; i++) {
    if (side === "top" && use[i].price < use[i - 1].price - c.atr * 0.2) return null;
    if (side === "bottom" && use[i].price > use[i - 1].price + c.atr * 0.2) return null;
  }
  for (let i = peakAt + 1; i < use.length; i++) {
    if (side === "top" && use[i].price > use[i - 1].price + c.atr * 0.2) return null;
    if (side === "bottom" && use[i].price < use[i - 1].price - c.atr * 0.2) return null;
  }
  const extreme = use[peakAt];
  if (side === "top") {
    const floor = minLow(c.candles, extreme.i, c.last - 1);
    if (!brokeDown(c.candles, () => floor.price)) return null;
    const height = extreme.price - floor.price;
    if (height < c.atr * 1.5) return null;
    return signal(c, {
      id: "rounding_top",
      direction: "short",
      quality: 0.63,
      stop: extreme.price + c.atr * 0.1,
      target: floor.price - height * 0.8,
      reason: "Дуга вершины и закрытие под правым краем.",
      drawings: [seg("pattern", use[0].i, use[0].price, extreme.i, extreme.price, "дуга"), seg("pattern", extreme.i, extreme.price, use[use.length - 1].i, use[use.length - 1].price, "")],
    });
  }
  const roof = maxHigh(c.candles, extreme.i, c.last - 1);
  if (!brokeUp(c.candles, () => roof.price)) return null;
  const height = roof.price - extreme.price;
  if (height < c.atr * 1.5) return null;
  return signal(c, {
    id: "rounding_bottom",
    direction: "long",
    quality: 0.63,
    stop: extreme.price - c.atr * 0.1,
    target: roof.price + height * 0.8,
    reason: "Дуга дна и закрытие над правым краем.",
    drawings: [seg("pattern", use[0].i, use[0].price, extreme.i, extreme.price, "дуга"), seg("pattern", extreme.i, extreme.price, use[use.length - 1].i, use[use.length - 1].price, "")],
  });
}

function cupHandle(c) {
  const { candles, last, highs, lows, atr: a } = c;
  if (highs.length < 2 || lows.length < 1) return null;
  const right = highs[highs.length - 1];
  if (last - right.i > 24 || last - right.i < PIVOT_RIGHT) return null;
  for (let i = highs.length - 2; i >= 0; i--) {
    const left = highs[i];
    if (right.i - left.i < 16 || right.i - left.i > 90) continue;
    if (relDiff(left.price, right.price) > 0.03) continue;
    const bottom = minLow(candles, left.i, right.i);
    const rim = (left.price + right.price) / 2;
    const depth = rim - bottom.price;
    if (depth < a * 2) continue;
    const handle = minLow(candles, right.i, last - 1);
    if (handle.i <= right.i) continue;
    if (rim - handle.price > depth * 0.5) continue;
    if (handle.price <= bottom.price) continue;
    if (!brokeUp(candles, () => rim)) continue;
    return signal(c, {
      id: "cup_handle",
      direction: "long",
      quality: 0.74,
      stop: handle.price - a * 0.1,
      target: rim + depth,
      reason: "Чаша вернулась к краю, ручка неглубокая, край пробит вверх.",
      drawings: [
        seg("pattern", left.i, left.price, bottom.i, bottom.price, "чаша"),
        seg("pattern", bottom.i, bottom.price, right.i, right.price, ""),
        hline("neck", rim, left.i, last, "край"),
      ],
    });
  }
  return null;
}

function invCup(c) {
  const { candles, last, highs, lows, atr: a } = c;
  if (lows.length < 2) return null;
  const right = lows[lows.length - 1];
  if (last - right.i > 24 || last - right.i < PIVOT_RIGHT) return null;
  for (let i = lows.length - 2; i >= 0; i--) {
    const left = lows[i];
    if (right.i - left.i < 16 || right.i - left.i > 90) continue;
    if (relDiff(left.price, right.price) > 0.03) continue;
    const top = maxHigh(candles, left.i, right.i);
    const rim = (left.price + right.price) / 2;
    const depth = top.price - rim;
    if (depth < a * 2) continue;
    const handle = maxHigh(candles, right.i, last - 1);
    if (handle.i <= right.i) continue;
    if (handle.price - rim > depth * 0.5) continue;
    if (!brokeDown(candles, () => rim)) continue;
    return signal(c, {
      id: "inv_cup_handle",
      direction: "short",
      quality: 0.7,
      stop: handle.price + a * 0.1,
      target: rim - depth,
      reason: "Перевёрнутая чаша с ручкой, край пробит вниз.",
      drawings: [
        seg("pattern", left.i, left.price, top.i, top.price, "чаша"),
        seg("pattern", top.i, top.price, right.i, right.price, ""),
        hline("neck", rim, left.i, last, "край"),
      ],
    });
  }
  return null;
}

function diamond(c) {
  const swings = alternating(c.highs, c.lows);
  if (swings.length < 6) return null;
  const s = swings.slice(-6);
  const ranges = [];
  for (let i = 1; i < s.length; i++) ranges.push(Math.abs(s[i].price - s[i - 1].price));
  if (ranges.length < 5) return null;
  const expand = ranges[1] > ranges[0] * 1.08 && ranges[2] > ranges[1] * 1.05;
  const contract = ranges[3] < ranges[2] * 0.92 && ranges[4] < ranges[3] * 0.95;
  if (!expand || !contract) return null;
  const lastSwing = s[s.length - 1];
  if (c.last - lastSwing.i > 20) return null;
  const height = Math.max(...ranges);
  if (lastSwing.kind === "H" && brokeDown(c.candles, () => lastSwing.price - (ranges[4] || 0) * 0.2)) {
    const level = Math.min(s[s.length - 1].price, s[s.length - 2].price);
    if (!brokeDown(c.candles, () => level)) return null;
    return signal(c, {
      id: "diamond_top",
      direction: "short",
      quality: 0.6,
      stop: Math.max(...s.map((p) => p.price)) + c.atr * 0.05,
      target: c.candles[c.last].c - height,
      reason: "Бриллиант: размах сначала вырос, потом сжался, и цена закрылась ниже.",
      drawings: [seg("pattern", s[0].i, s[0].price, s[s.length - 1].i, s[s.length - 1].price, "бриллиант")],
    });
  }
  if (lastSwing.kind === "L" && brokeUp(c.candles, () => Math.max(s[s.length - 1].price, s[s.length - 2].price))) {
    return signal(c, {
      id: "diamond_bottom",
      direction: "long",
      quality: 0.6,
      stop: Math.min(...s.map((p) => p.price)) - c.atr * 0.05,
      target: c.candles[c.last].c + height,
      reason: "Бриллиант у дна: размах сжался и цена закрылась выше фигуры.",
      drawings: [seg("pattern", s[0].i, s[0].price, s[s.length - 1].i, s[s.length - 1].price, "бриллиант")],
    });
  }
  return null;
}

function parts(bar) {
  const body = Math.abs(bar.c - bar.o);
  const upper = bar.h - Math.max(bar.o, bar.c);
  const lower = Math.min(bar.o, bar.c) - bar.l;
  const range = Math.max(bar.h - bar.l, 1e-12);
  return { body, upper, lower, range, bull: bar.c >= bar.o, bear: bar.c < bar.o };
}

function trendAt(c, i) {
  const closes = c.candles.map((x) => x.c);
  const m = smaAt(closes, i, 20);
  if (m == null) return "flat";
  if (c.candles[i].c < m * 0.995) return "down";
  if (c.candles[i].c > m * 1.005) return "up";
  return "flat";
}

function isLocalLow(c, i, back = 6) {
  let m = Infinity;
  for (let k = Math.max(0, i - back); k <= i; k++) m = Math.min(m, c.candles[k].l);
  return c.candles[i].l <= m + c.atr * 0.05;
}
function isLocalHigh(c, i, back = 6) {
  let m = -Infinity;
  for (let k = Math.max(0, i - back); k <= i; k++) m = Math.max(m, c.candles[k].h);
  return c.candles[i].h >= m - c.atr * 0.05;
}

function candleSignal(c, id, direction, quality, stop, reason) {
  const entry = c.candles[c.last].c;
  const target = twoR(direction, entry, stop);
  return signal(c, { id, direction, quality, stop, target, reason, drawings: [] });
}

function candlesPatterns(c) {
  const out = [];
  const bar = c.candles[c.last];
  const prev = c.candles[c.last - 1];
  const p = parts(bar);
  const q = parts(prev);
  if (p.range < c.atr * 0.45) return out;
  const down = trendAt(c, c.last) === "down" || trendAt(c, c.last - 1) === "down";
  const up = trendAt(c, c.last) === "up" || trendAt(c, c.last - 1) === "up";

  if (down && isLocalLow(c, c.last) && p.lower >= p.body * 2 && p.upper <= p.body * 0.8 && p.body > 0 && p.bull) {
    out.push(candleSignal(c, "hammer", "long", 0.6, bar.l - c.atr * 0.08, "Молот у минимума после снижения."));
  } else if (down && isLocalLow(c, c.last) && p.lower >= p.range * 0.6 && p.body <= p.range * 0.35) {
    out.push(candleSignal(c, "pin_bull", "long", 0.56, bar.l - c.atr * 0.08, "Бычий пин-бар у минимума."));
  }
  if (down && isLocalLow(c, c.last) && p.upper >= p.body * 2 && p.lower <= p.body && p.bull && !out.length) {
    out.push(candleSignal(c, "inv_hammer", "long", 0.52, bar.l - c.atr * 0.08, "Перевёрнутый молот после снижения."));
  }
  if (up && isLocalHigh(c, c.last) && p.lower >= p.body * 2 && p.upper <= p.body && p.bear) {
    out.push(candleSignal(c, "hanging", "short", 0.55, bar.h + c.atr * 0.08, "Повешенный после роста."));
  }
  if (up && isLocalHigh(c, c.last) && p.upper >= p.body * 2 && p.lower <= p.body * 0.7 && p.bear) {
    out.push(candleSignal(c, "shooting", "short", 0.6, bar.h + c.atr * 0.08, "Падающая звезда у вершины."));
  } else if (up && isLocalHigh(c, c.last) && p.upper >= p.range * 0.6 && p.body <= p.range * 0.35) {
    out.push(candleSignal(c, "pin_bear", "short", 0.56, bar.h + c.atr * 0.08, "Медвежий пин-бар у вершины."));
  }

  if (down && q.bear && p.bull && bar.o <= prev.c && bar.c >= prev.o && p.body > q.body * 0.9) {
    out.push(candleSignal(c, "bull_engulf", "long", 0.64, Math.min(bar.l, prev.l) - c.atr * 0.05, "Бычье поглощение."));
  }
  if (up && q.bull && p.bear && bar.o >= prev.c && bar.c <= prev.o && p.body > q.body * 0.9) {
    out.push(candleSignal(c, "bear_engulf", "short", 0.64, Math.max(bar.h, prev.h) + c.atr * 0.05, "Медвежье поглощение."));
  }

  if (c.last >= 2) {
    const a = c.candles[c.last - 2];
    const mid = c.candles[c.last - 1];
    const ap = parts(a);
    const mp = parts(mid);
    if (down && ap.bear && mp.body <= ap.body * 0.6 && p.bull && bar.c > (a.o + a.c) / 2) {
      out.push(candleSignal(c, "morning_star", "long", 0.66, Math.min(a.l, mid.l, bar.l) - c.atr * 0.05, "Утренняя звезда."));
    }
    if (up && ap.bull && mp.body <= ap.body * 0.6 && p.bear && bar.c < (a.o + a.c) / 2) {
      out.push(candleSignal(c, "evening_star", "short", 0.66, Math.max(a.h, mid.h, bar.h) + c.atr * 0.05, "Вечерняя звезда."));
    }
  }

  if (down && q.bear && p.bull && bar.o >= Math.min(prev.o, prev.c) && bar.c <= Math.max(prev.o, prev.c) && p.body < q.body) {
    out.push(candleSignal(c, "bull_harami", "long", 0.5, prev.l - c.atr * 0.05, "Бычья харами."));
  }
  if (up && q.bull && p.bear && bar.c >= Math.min(prev.o, prev.c) && bar.o <= Math.max(prev.o, prev.c) && p.body < q.body) {
    out.push(candleSignal(c, "bear_harami", "short", 0.5, prev.h + c.atr * 0.05, "Медвежья харами."));
  }
  if (down && q.bear && p.bull && bar.o <= prev.c && bar.c > (prev.o + prev.c) / 2 && bar.c < prev.o) {
    out.push(candleSignal(c, "piercing", "long", 0.58, bar.l - c.atr * 0.05, "Просвет в облаках."));
  }
  if (up && q.bull && p.bear && bar.o >= prev.c && bar.c < (prev.o + prev.c) / 2 && bar.c > prev.o) {
    out.push(candleSignal(c, "dark_cloud", "short", 0.58, bar.h + c.atr * 0.05, "Завеса из тёмных облаков."));
  }

  if (c.last >= 2) {
    const a = c.candles[c.last - 2];
    const b = c.candles[c.last - 1];
    if (down && a.c > a.o && b.c > b.o && bar.c > bar.o && b.c > a.c && bar.c > b.c && bar.o <= b.c && bar.o >= b.o) {
      out.push(candleSignal(c, "three_soldiers", "long", 0.62, a.l - c.atr * 0.05, "Три белых солдата."));
    }
    if (up && a.c < a.o && b.c < b.o && bar.c < bar.o && b.c < a.c && bar.c < b.c && bar.o >= b.c && bar.o <= b.o) {
      out.push(candleSignal(c, "three_crows", "short", 0.62, a.h + c.atr * 0.05, "Три чёрные вороны."));
    }
  }

  if (up && relDiff(bar.h, prev.h) < 0.003 && p.bear && q.bull && isLocalHigh(c, c.last)) {
    out.push(candleSignal(c, "tweezer_top", "short", 0.54, Math.max(bar.h, prev.h) + c.atr * 0.05, "Пинцет сверху."));
  }
  if (down && relDiff(bar.l, prev.l) < 0.003 && p.bull && q.bear && isLocalLow(c, c.last)) {
    out.push(candleSignal(c, "tweezer_bottom", "long", 0.54, Math.min(bar.l, prev.l) - c.atr * 0.05, "Пинцет снизу."));
  }

  if (c.last >= 2) {
    const mother = c.candles[c.last - 2];
    const inside = c.candles[c.last - 1];
    if (inside.h <= mother.h && inside.l >= mother.l && mother.h - mother.l >= c.atr * 0.5) {
      if (brokeUp(c.candles, () => mother.h)) {
        out.push(candleSignal(c, "inside_up", "long", 0.57, mother.l - c.atr * 0.05, "Выход вверх из внутренней свечи."));
      } else if (brokeDown(c.candles, () => mother.l)) {
        out.push(candleSignal(c, "inside_down", "short", 0.57, mother.h + c.atr * 0.05, "Выход вниз из внутренней свечи."));
      }
    }
  }

  if (p.body <= p.range * 0.12 && p.range >= c.atr * 0.5) {
    if (down && isLocalLow(c, c.last)) out.push(candleSignal(c, "doji_low", "long", 0.42, bar.l - c.atr * 0.05, "Доджи у минимума."));
    if (up && isLocalHigh(c, c.last)) out.push(candleSignal(c, "doji_high", "short", 0.42, bar.h + c.atr * 0.05, "Доджи у максимума."));
  }
  return out.filter(Boolean);
}

function rsiDivergence(c) {
  const out = [];
  const { lows, highs, rsi: rs, last } = c;
  if (lows.length >= 2) {
    const b = lows[lows.length - 1];
    const a = lows[lows.length - 2];
    if (b.i + PIVOT_RIGHT === last && b.price < a.price && rs[b.i] != null && rs[a.i] != null && rs[b.i] > rs[a.i] + 3) {
      const item = candleSignal(c, "rsi_bull", "long", 0.6, b.price - c.atr * 0.1, "Цена обновила минимум, RSI нет.");
      if (item) out.push(item);
    }
  }
  if (highs.length >= 2) {
    const b = highs[highs.length - 1];
    const a = highs[highs.length - 2];
    if (b.i + PIVOT_RIGHT === last && b.price > a.price && rs[b.i] != null && rs[a.i] != null && rs[b.i] < rs[a.i] - 3) {
      const item = candleSignal(c, "rsi_bear", "short", 0.6, b.price + c.atr * 0.1, "Цена обновила максимум, RSI нет.");
      if (item) out.push(item);
    }
  }
  return out;
}

function near(value, target, tol) {
  return Math.abs(value - target) <= tol;
}
function between(value, a, b, pad = 0) {
  return value >= a - pad && value <= b + pad;
}

/** X-A-B-C-D. Бычья схема идёт снизу: X минимум, A максимум, D минимум. */
export function classifyHarmonic(X, A, B, C, D) {
  const bull =
    A.price > X.price &&
    B.price < A.price &&
    C.price > B.price &&
    C.price < A.price &&
    D.price < B.price &&
    D.price < C.price;
  const bear =
    A.price < X.price &&
    B.price > A.price &&
    C.price < B.price &&
    C.price > A.price &&
    D.price > B.price &&
    D.price > C.price;
  if (!bull && !bear) return null;
  const XA = Math.abs(A.price - X.price);
  const AB = Math.abs(B.price - A.price);
  const BC = Math.abs(C.price - B.price);
  const AD = Math.abs(A.price - D.price);
  if (XA === 0 || AB === 0) return null;
  const ab = AB / XA;
  const bc = BC / AB;
  const ad = AD / XA;
  if (!between(bc, 0.382, 0.886, 0.06)) return null;
  const side = bull ? "bull" : "bear";
  if (near(ab, 0.618, 0.07) && near(ad, 0.786, 0.07)) return { id: side === "bull" ? "gartley_bull" : "gartley_bear", side };
  if (between(ab, 0.382, 0.5, 0.04) && near(ad, 0.886, 0.07)) return { id: side === "bull" ? "bat_bull" : "bat_bear", side };
  if (near(ab, 0.786, 0.07) && between(ad, 1.27, 1.618, 0.08)) return { id: side === "bull" ? "butterfly_bull" : "butterfly_bear", side };
  if (between(ab, 0.382, 0.618, 0.05) && near(ad, 1.618, 0.1)) return { id: side === "bull" ? "crab_bull" : "crab_bear", side };
  return null;
}

function harmonics(c) {
  const swings = alternating(c.highs, c.lows);
  if (swings.length < 5) return null;
  const pts = swings.slice(-5);
  const [X, A, B, C, D] = pts;
  if (c.last !== D.i + PIVOT_RIGHT && c.last !== D.i + PIVOT_RIGHT + 1) return null;
  const found = classifyHarmonic(X, A, B, C, D);
  if (!found) return null;
  const direction = found.side === "bull" ? "long" : "short";
  const entry = c.candles[c.last].c;
  const stop = direction === "long" ? D.price - c.atr * 0.2 : D.price + c.atr * 0.2;
  const target = direction === "long" ? D.price + Math.abs(A.price - D.price) * 0.618 : D.price - Math.abs(A.price - D.price) * 0.618;
  return signal(c, {
    id: found.id,
    direction,
    quality: 0.69,
    stop,
    target,
    reason: `${NAMES[found.id]} сошёлся в точке D.`,
    drawings: [
      seg("pattern", X.i, X.price, A.i, A.price, ""),
      seg("pattern", A.i, A.price, B.i, B.price, ""),
      seg("pattern", B.i, B.price, C.i, C.price, ""),
      seg("pattern", C.i, C.price, D.i, D.price, NAMES[found.id]),
    ],
  });
}

export function detectImpulse(candles) {
  if (!candles || candles.length < 8) return null;
  const last = candles.length - 1;
  const atrArr = atr(candles, 14);
  const a = atrArr[last] || candles[last].h - candles[last].l;
  const back = candles[last - 4];
  const move = candles[last].c - back.o;
  const pct = back.o ? move / back.o : 0;
  if (!(a > 0) || Math.abs(move) < a * 1.8 || Math.abs(pct) < 0.008) return null;
  const direction = move > 0 ? "up" : "down";
  return {
    direction,
    pct,
    from: back.o,
    to: candles[last].c,
    i1: last - 4,
    i2: last,
    text:
      direction === "down"
        ? `За 4 свечи цена уже прошла вниз ${(Math.abs(pct) * 100).toFixed(2)}%.`
        : `За 4 свечи цена уже прошла вверх ${(Math.abs(pct) * 100).toFixed(2)}%.`,
  };
}

export function impulseSignal(c) {
  const move = detectImpulse(c.candles);
  if (!move) return null;
  const id = move.direction === "up" ? "impulse_up" : "impulse_down";
  const direction = move.direction === "up" ? "long" : "short";
  const stop = move.direction === "up" ? Math.min(move.from, c.candles[c.last].l) : Math.max(move.from, c.candles[c.last].h);
  const dist = Math.abs(c.candles[c.last].c - stop);
  const target = direction === "long" ? c.candles[c.last].c + dist : c.candles[c.last].c - dist;
  return signal(c, {
    id,
    direction,
    quality: 0.5,
    stop,
    target,
    reason: move.text + " Это уже идущее движение, не фигура с картинки.",
    drawings: [seg("pattern", move.i1, move.from, move.i2, move.to, "импульс")],
  });
}

export function detectPatterns(candles) {
  if (!candles || candles.length < 40) return [];
  const c = makeCtx(candles);
  const found = [
    doubleTop(c),
    doubleBottom(c),
    tripleTop(c),
    tripleBottom(c),
    headShoulders(c),
    inverseHs(c),
    wedgeOrTriangle(c),
    channel(c),
    expanding(c),
    flagFamily(c),
    rangeBreak(c),
    trendChange(c),
    rounding(c, "top"),
    rounding(c, "bottom"),
    cupHandle(c),
    invCup(c),
    diamond(c),
    harmonics(c),
    ...candlesPatterns(c),
    ...rsiDivergence(c),
    impulseSignal(c),
  ].filter(Boolean);
  found.sort((a, b) => b.quality - a.quality);
  return found;
}

export function swingDots(candles) {
  if (!candles || candles.length < 20) return [];
  const highs = pivotHighs(candles, PIVOT_LEFT, PIVOT_RIGHT).slice(-4);
  const lows = pivotLows(candles, PIVOT_LEFT, PIVOT_RIGHT).slice(-4);
  return [...highs, ...lows].map((p) => ({
    type: "dot",
    role: "swing",
    i: p.i,
    price: p.price,
    label: p.kind === "H" ? "свинг" : "свинг",
  }));
}
