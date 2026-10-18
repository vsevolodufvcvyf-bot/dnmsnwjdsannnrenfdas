/** Свечные ряды, свинги и индикаторы. Индексы совпадают с массивом свечей. */

export function tr(candles, i) {
  const cur = candles[i];
  const prev = candles[i - 1];
  const a = cur.h - cur.l;
  if (!prev) return a;
  return Math.max(a, Math.abs(cur.h - prev.c), Math.abs(cur.l - prev.c));
}

export function atr(candles, period = 14) {
  const out = new Array(candles.length).fill(null);
  if (candles.length < period + 1) return out;
  let sum = 0;
  for (let i = 1; i <= period; i++) sum += tr(candles, i);
  let prev = sum / period;
  out[period] = prev;
  for (let i = period + 1; i < candles.length; i++) {
    prev = (prev * (period - 1) + tr(candles, i)) / period;
    out[i] = prev;
  }
  return out;
}

export function rsi(candles, period = 14) {
  const out = new Array(candles.length).fill(null);
  if (candles.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = candles[i].c - candles[i - 1].c;
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let ag = gain / period;
  let al = loss / period;
  const at = (g, l) => (l === 0 ? 100 : 100 - 100 / (1 + g / l));
  out[period] = at(ag, al);
  for (let i = period + 1; i < candles.length; i++) {
    const d = candles[i].c - candles[i - 1].c;
    ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
    al = (al * (period - 1) + (d < 0 ? -d : 0)) / period;
    out[i] = at(ag, al);
  }
  return out;
}

export function smaAt(values, i, period) {
  if (i < period - 1) return null;
  let s = 0;
  for (let k = i - period + 1; k <= i; k++) s += values[k];
  return s / period;
}

export function pivotHighs(candles, left = 3, right = 3) {
  const res = [];
  for (let i = left; i < candles.length - right; i++) {
    let ok = true;
    for (let j = i - left; j <= i + right; j++) {
      if (j !== i && candles[j].h >= candles[i].h) {
        ok = false;
        break;
      }
    }
    if (ok) res.push({ i, price: candles[i].h, t: candles[i].t, kind: "H" });
  }
  return res;
}

export function pivotLows(candles, left = 3, right = 3) {
  const res = [];
  for (let i = left; i < candles.length - right; i++) {
    let ok = true;
    for (let j = i - left; j <= i + right; j++) {
      if (j !== i && candles[j].l <= candles[i].l) {
        ok = false;
        break;
      }
    }
    if (ok) res.push({ i, price: candles[i].l, t: candles[i].t, kind: "L" });
  }
  return res;
}

/** Чередование вершин и впадин. Два свингa подряд с одной стороны схлопываются в более крайний. */
export function alternating(highs, lows) {
  const all = [...highs, ...lows].sort((a, b) => a.i - b.i || (a.kind === "H" ? -1 : 1));
  const out = [];
  for (const p of all) {
    const prev = out[out.length - 1];
    if (!prev || prev.kind !== p.kind) {
      out.push(p);
      continue;
    }
    if (p.kind === "H" && p.price >= prev.price) out[out.length - 1] = p;
    if (p.kind === "L" && p.price <= prev.price) out[out.length - 1] = p;
  }
  return out;
}

export function linreg(points) {
  const n = points.length;
  if (n < 2) return null;
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  for (const p of points) {
    sx += p.i;
    sy += p.price;
    sxx += p.i * p.i;
    sxy += p.i * p.price;
  }
  const den = n * sxx - sx * sx;
  if (den === 0) return null;
  const slope = (n * sxy - sx * sy) / den;
  const intercept = (sy - slope * sx) / n;
  return { slope, intercept, at: (i) => slope * i + intercept };
}

export function relDiff(a, b) {
  const base = (Math.abs(a) + Math.abs(b)) / 2;
  if (base === 0) return 0;
  return Math.abs(a - b) / base;
}

export function minLow(candles, from, to) {
  let price = Infinity;
  let i = from;
  for (let k = from; k <= to; k++) {
    if (candles[k].l < price) {
      price = candles[k].l;
      i = k;
    }
  }
  return { i, price };
}

export function maxHigh(candles, from, to) {
  let price = -Infinity;
  let i = from;
  for (let k = from; k <= to; k++) {
    if (candles[k].h > price) {
      price = candles[k].h;
      i = k;
    }
  }
  return { i, price };
}

/** Сжать свечи в старший таймфрейм, последняя группа включает правый край. */
export function resampleFromEnd(candles, factor) {
  if (!candles?.length || factor <= 1) return candles ? candles.slice() : [];
  const rem = candles.length % factor;
  const src = rem === 0 ? candles : candles.slice(rem);
  const out = [];
  for (let i = 0; i < src.length; i += factor) {
    const g = src.slice(i, i + factor);
    if (g.length < factor) break;
    let h = -Infinity;
    let l = Infinity;
    let v = 0;
    for (const x of g) {
      if (x.h > h) h = x.h;
      if (x.l < l) l = x.l;
      v += x.v || 0;
    }
    out.push({ t: g[0].t, o: g[0].o, h, l, c: g[g.length - 1].c, v });
  }
  return out;
}

export function structureBias(candles) {
  if (!candles || candles.length < 40) return "flat";
  const highs = pivotHighs(candles, 3, 3);
  const lows = pivotLows(candles, 3, 3);
  if (highs.length < 2 || lows.length < 2) return "flat";
  const h1 = highs[highs.length - 2];
  const h2 = highs[highs.length - 1];
  const l1 = lows[lows.length - 2];
  const l2 = lows[lows.length - 1];
  if (h2.price > h1.price && l2.price > l1.price) return "up";
  if (h2.price < h1.price && l2.price < l1.price) return "down";
  return "flat";
}

export function averageVolume(candles, i, period = 20) {
  const from = Math.max(0, i - period);
  let s = 0;
  let n = 0;
  for (let k = from; k < i; k++) {
    s += candles[k].v || 0;
    n++;
  }
  return n ? s / n : 0;
}
