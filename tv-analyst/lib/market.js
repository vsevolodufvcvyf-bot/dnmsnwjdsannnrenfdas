/** Любая монета с графика: спот Binance, дальше OKX, MEXC, KuCoin, Gate. */

const QUOTES = ["USDT", "USDC", "USD", "BUSD", "BTC", "ETH", "EUR"];

const INTERVAL_MS = {
  "1m": 60_000,
  "3m": 180_000,
  "5m": 300_000,
  "15m": 900_000,
  "30m": 1_800_000,
  "1h": 3_600_000,
  "2h": 7_200_000,
  "4h": 14_400_000,
  "1d": 86_400_000,
};

const HTF = {
  "1m": "15m",
  "3m": "30m",
  "5m": "1h",
  "15m": "1h",
  "30m": "4h",
  "1h": "4h",
  "2h": "1d",
  "4h": "1d",
  "1d": "1d",
};

export function intervalMs(interval) {
  return INTERVAL_MS[interval] || INTERVAL_MS["15m"];
}

export function higherInterval(interval) {
  return HTF[interval] || "1h";
}

export function mapInterval(raw) {
  const s = String(raw || "15").trim().toLowerCase().replace(/\s/g, "");
  const table = {
    "1": "1m",
    "1m": "1m",
    "1м": "1m",
    "3": "3m",
    "3m": "3m",
    "3м": "3m",
    "5": "5m",
    "5m": "5m",
    "5м": "5m",
    "15": "15m",
    "15m": "15m",
    "15м": "15m",
    "30": "30m",
    "30m": "30m",
    "30м": "30m",
    "45": "30m",
    "60": "1h",
    "1h": "1h",
    "1ч": "1h",
    "1hour": "1h",
    "120": "2h",
    "2h": "2h",
    "2ч": "2h",
    "240": "4h",
    "4h": "4h",
    "4ч": "4h",
    d: "1d",
    "1d": "1d",
    "1д": "1d",
    "1day": "1d",
  };
  return table[s] || "15m";
}

export function parseTvSymbol(input) {
  if (!input) return null;
  let raw = String(input).trim().toUpperCase();
  if (!raw || raw === "TRADINGVIEW") return null;
  let exchange = "";
  if (raw.includes(":")) {
    const parts = raw.split(":");
    exchange = parts[0];
    raw = parts.slice(1).join(":");
  }
  raw = raw.replace(/\s+/g, "");
  const perp = /\.P$|PERP$/.test(raw);
  raw = raw.replace(/\.P$/, "").replace(/PERP$/, "");
  raw = raw.replace(/[\/._-]/g, "");
  if (!/^[A-Z0-9]{2,20}$/.test(raw)) return null;

  let base = "";
  let quote = "";
  for (const q of QUOTES) {
    if (raw.endsWith(q) && raw.length > q.length + 1) {
      quote = q;
      base = raw.slice(0, -q.length);
      break;
    }
  }
  if (!base) {
    base = raw;
    quote = "USDT";
  }
  const settled = quote === "USD" || quote === "BUSD" ? "USDT" : quote;
  let binance = base + settled;
  return {
    exchange,
    perp,
    base,
    quote: settled,
    tv: String(input).trim(),
    binance,
    compact: base + settled,
  };
}

export function symbolCandidates(spec) {
  if (!spec) return [];
  const list = [spec.binance];
  if (/^1000[A-Z]/.test(spec.base)) {
    list.push(spec.base.replace(/^1000/, "") + spec.quote);
  }
  if (spec.quote === "USDT") list.push(spec.base + "USDC");
  return [...new Set(list)];
}

export function dropForming(candles, interval, now = Date.now()) {
  if (!candles?.length) return [];
  const ms = intervalMs(interval);
  const last = candles[candles.length - 1];
  if (last.t + ms > now + 2_000) return candles.slice(0, -1);
  return candles.slice();
}

function num(v) {
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

export function parseBinanceKlines(rows) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    if (!Array.isArray(r)) continue;
    const t = num(r[0]);
    const o = num(r[1]);
    const h = num(r[2]);
    const l = num(r[3]);
    const c = num(r[4]);
    const v = num(r[5]) ?? 0;
    if (t == null || o == null || h == null || l == null || c == null) continue;
    out.push({ t, o, h, l, c, v });
  }
  return out;
}

export function parseOkxCandles(body) {
  const rows = body?.data;
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    const t = num(r[0]);
    const o = num(r[1]);
    const h = num(r[2]);
    const l = num(r[3]);
    const c = num(r[4]);
    const v = num(r[5]) ?? 0;
    if (t == null || o == null || h == null || l == null || c == null) continue;
    out.push({ t, o, h, l, c, v });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

export function parseKucoinCandles(body) {
  const rows = body?.data;
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    const t = num(r[0]);
    const o = num(r[1]);
    const c = num(r[2]);
    const h = num(r[3]);
    const l = num(r[4]);
    const v = num(r[5]) ?? 0;
    if (t == null || o == null || h == null || l == null || c == null) continue;
    out.push({ t: t < 1e12 ? t * 1000 : t, o, h, l, c, v });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

function okxBar(interval) {
  return { "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H", "1d": "1D" }[interval];
}

function kucoinType(interval) {
  return {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hour",
    "2h": "2hour",
    "4h": "4hour",
    "1d": "1day",
  }[interval];
}

function sourcesFor(symbol, interval, limit) {
  const base = symbol.replace(/USDT$|USDC$/, "");
  const quote = symbol.endsWith("USDC") ? "USDC" : "USDT";
  const pair = `${base}-${quote}`;
  const src = [];
  src.push({
    name: "Binance",
    url: `https://data-api.binance.vision/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`,
    parse: parseBinanceKlines,
  });
  src.push({
    name: "MEXC",
    url: `https://api.mexc.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`,
    parse: parseBinanceKlines,
  });
  const bar = okxBar(interval);
  if (bar) {
    src.push({
      name: "OKX",
      url: `https://www.okx.com/api/v5/market/candles?instId=${pair}&bar=${bar}&limit=${Math.min(limit, 300)}`,
      parse: parseOkxCandles,
    });
  }
  const kt = kucoinType(interval);
  if (kt) {
    src.push({
      name: "KuCoin",
      url: `https://api.kucoin.com/api/v1/market/candles?type=${kt}&symbol=${pair}`,
      parse: parseKucoinCandles,
    });
  }
  return src;
}

export async function fetchCandles(symbol, interval, limit = 400, fetchImpl = fetch) {
  const errors = [];
  for (const src of sourcesFor(symbol, interval, limit)) {
    try {
      const res = await fetchImpl(src.url, { headers: { accept: "application/json" } });
      if (!res.ok) {
        errors.push(`${src.name} ${res.status}`);
        continue;
      }
      const json = await res.json();
      const candles = src.parse(json);
      if (candles.length >= 40) return { candles, source: src.name, symbol };
      errors.push(`${src.name} мало свечей`);
    } catch (err) {
      errors.push(`${src.name}`);
    }
  }
  const error = new Error(errors.join(", ") || "нет данных");
  error.errors = errors;
  throw error;
}

export async function loadMarket(spec, interval, fetchImpl = fetch, now = Date.now()) {
  const tried = [];
  let lastError = null;
  for (const symbol of symbolCandidates(spec)) {
    try {
      const main = await fetchCandles(symbol, interval, 400, fetchImpl);
      const candles = dropForming(main.candles, interval, now);
      const htf = higherInterval(interval);
      let higher = [];
      let higherSource = main.source;
      if (htf !== interval) {
        try {
          const hi = await fetchCandles(symbol, htf, 220, fetchImpl);
          higher = dropForming(hi.candles, htf, now);
          higherSource = hi.source;
        } catch {
          higher = [];
        }
      } else {
        higher = candles;
      }
      if (candles.length < 40) {
        tried.push(symbol);
        continue;
      }
      return {
        candles,
        higher,
        source: main.source,
        higherSource,
        symbol,
        interval,
        higherInterval: htf,
        tried,
      };
    } catch (err) {
      lastError = err;
      tried.push(symbol);
    }
  }
  const error = new Error(
    `Пара ${spec?.compact || ""} не нашлась на Binance, MEXC, OKX и KuCoin` +
      (lastError ? ` (${lastError.message})` : ""),
  );
  error.tried = tried;
  throw error;
}
