import { attachDrawingTimes } from "./lib/drawings.js";
import { step } from "./lib/engine.js";
import { formatPrice } from "./lib/format.js";
import { cloneMemory, memorySummary } from "./lib/learn.js";
import { loadMarket, mapInterval, parseTvSymbol } from "./lib/market.js";
import { newsQuery, parseRss, scoreNews } from "./lib/news.js";
import { CATALOG, patternName } from "./lib/patterns.js";
import { SEED } from "./lib/seed.js";

const MEMORY_KEY = "memory";
const WATCH_KEY = "watchlist";
const META_KEY = "meta";
const NAMES_KEY = "names";

const klineCache = new Map();
const newsCache = new Map();
let queue = Promise.resolve();

function enqueue(fn) {
  const run = queue.then(fn, fn);
  queue = run.then(
    () => {},
    () => {},
  );
  return run;
}

function cachingFetch(ttl) {
  return async (url, opts) => {
    const hit = klineCache.get(url);
    if (hit && Date.now() - hit.at < ttl) return hit.res.clone();
    const res = await fetch(url, opts);
    if (res.ok) klineCache.set(url, { at: Date.now(), res: res.clone() });
    return res;
  };
}

async function loadMemory() {
  const bag = await chrome.storage.local.get(MEMORY_KEY);
  if (!bag[MEMORY_KEY]) {
    const fresh = cloneMemory(SEED);
    await chrome.storage.local.set({ [MEMORY_KEY]: fresh });
    return fresh;
  }
  return cloneMemory(bag[MEMORY_KEY]);
}

function decorate(summary) {
  return {
    ...summary,
    rows: summary.rows.map((row) => ({ ...row, name: patternName(row.id) })),
    last: summary.last.map((row) => ({ ...row, name: row.name || patternName(row.patternId) })),
  };
}

function seedInfo() {
  return {
    note: SEED.note || "",
    trainedOn: SEED.trainedOn || [],
    test: SEED.test || null,
    catalog: CATALOG.length,
  };
}

async function rememberWatch(spec, interval) {
  const bag = await chrome.storage.local.get(WATCH_KEY);
  const list = Array.isArray(bag[WATCH_KEY]) ? bag[WATCH_KEY] : [];
  const next = [
    { symbol: spec.compact, tv: spec.tv, base: spec.base, interval },
    ...list.filter((item) => item.symbol !== spec.compact),
  ].slice(0, 8);
  await chrome.storage.local.set({ [WATCH_KEY]: next });
  return next;
}

async function coinName(base, fetchImpl) {
  const bag = await chrome.storage.local.get(NAMES_KEY);
  const names = bag[NAMES_KEY] || {};
  if (names[base]) return names[base];
  try {
    const res = await fetchImpl(`https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(base)}`, {
      headers: { accept: "application/json" },
    });
    if (!res.ok) return base;
    const json = await res.json();
    const coins = (json.coins || []).filter((coin) => String(coin.symbol || "").toUpperCase() === base);
    coins.sort((a, b) => (a.market_cap_rank ?? 9999) - (b.market_cap_rank ?? 9999));
    const name = coins[0]?.name || base;
    names[base] = name;
    await chrome.storage.local.set({ [NAMES_KEY]: names });
    return name;
  } catch {
    return base;
  }
}

async function loadNews(spec, fetchImpl) {
  const cached = newsCache.get(spec.base);
  if (cached && Date.now() - cached.at < 180_000) return cached.value;
  const name = await coinName(spec.base, fetchImpl);
  const query = newsQuery(spec.base, name);
  const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=ru&gl=RU&ceid=RU:ru`;
  const res = await fetchImpl(url, { headers: { accept: "application/rss+xml, text/xml, */*" } });
  if (!res.ok) throw new Error("новости " + res.status);
  const scored = scoreNews(parseRss(await res.text(), 8), spec.base, name);
  const value = { ...scored, name, query };
  newsCache.set(spec.base, { at: Date.now(), value });
  return value;
}

function clipDrawings(drawings, shift, len) {
  const out = [];
  for (const drawing of drawings || []) {
    if (drawing.type === "dot") {
      const i = drawing.i - shift;
      if (i >= 0 && i < len) out.push({ ...drawing, i });
      continue;
    }
    if (drawing.type === "hline") {
      const i1 = Math.max(0, (drawing.i1 ?? 0) - shift);
      const i2 = Math.min(len - 1, (drawing.i2 ?? len - 1) - shift);
      if (i2 >= 0 && i1 <= len - 1) out.push({ ...drawing, i1, i2 });
      continue;
    }
    let i1 = drawing.i1 - shift;
    let i2 = drawing.i2 - shift;
    let p1 = drawing.price1;
    let p2 = drawing.price2;
    if (i2 === i1) {
      if (i1 >= 0 && i1 < len) out.push({ ...drawing, i1, i2, price1: p1, price2: p2 });
      continue;
    }
    const priceAt = (i) => p1 + ((p2 - p1) * (i - i1)) / (i2 - i1);
    if (i1 < 0) {
      p1 = priceAt(0);
      i1 = 0;
    }
    if (i2 > len - 1) {
      p2 = priceAt(len - 1);
      i2 = len - 1;
    }
    if (i2 >= 0 && i1 <= len - 1 && i2 >= i1) out.push({ ...drawing, i1, i2, price1: p1, price2: p2 });
  }
  return out;
}

async function notify(spec, interval, analysis) {
  const bag = await chrome.storage.local.get(META_KEY);
  const meta = bag[META_KEY] || {};
  const alerts = meta.alerts || {};
  const impulseAt = meta.impulseAt || {};
  const slot = `${spec.compact}:${interval}`;
  const directional = analysis.verdict === "long" || analysis.verdict === "short";
  let key = "quiet";
  if (directional && analysis.pattern) key = `${analysis.verdict}:${analysis.pattern.id}:${analysis.barTime}`;
  else if (analysis.alert === "falling" || analysis.alert === "rising") key = analysis.alert;

  if (key === "quiet") {
    alerts[slot] = "quiet";
    meta.alerts = alerts;
    await chrome.storage.local.set({ [META_KEY]: meta });
    return;
  }
  if (alerts[slot] === key) {
    if (directional) return;
    if (Date.now() - (impulseAt[slot] || 0) < 20 * 60 * 1000) return;
  }
  alerts[slot] = key;
  if (!directional) impulseAt[slot] = Date.now();
  meta.alerts = alerts;
  meta.impulseAt = impulseAt;
  await chrome.storage.local.set({ [META_KEY]: meta });
  if (meta.mute) return;

  const down = analysis.verdict === "short" || analysis.alert === "falling";
  const title = `${spec.base} — ${down ? "вниз" : "вверх"}`;
  let message;
  if (directional && analysis.pattern) {
    message = `${analysis.pattern.name}. Вход ${formatPrice(analysis.pattern.entry)}, стоп ${formatPrice(analysis.pattern.stop)}, цель ${formatPrice(analysis.pattern.target)}.`;
  } else {
    message = analysis.move?.text || analysis.reasons[0] || "";
  }
  const newsLine = analysis.reasons.find((line) => line.includes("заголовк"));
  if (newsLine) message += " " + newsLine;
  chrome.notifications.create(`scheme-${slot}-${Date.now()}`, {
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon128.png"),
    title,
    message: message.slice(0, 240),
    priority: 2,
  });
}

async function analyze(rawSymbol, rawInterval, options = {}) {
  const spec = parseTvSymbol(rawSymbol);
  if (!spec) return { ok: false, error: "Не вижу тикер. Открой график монеты или впиши его, например SOLUSDT." };
  const interval = mapInterval(rawInterval);
  const fetchImpl = cachingFetch(12_000);
  let market;
  try {
    market = await loadMarket(spec, interval, fetchImpl);
  } catch (err) {
    return { ok: false, error: err.message, symbol: spec, interval };
  }
  let news = { tone: "neutral", score: 0, headlines: [], name: spec.base, error: "" };
  try {
    news = await loadNews(spec, fetchImpl);
  } catch (err) {
    news = { ...news, error: "Новости сейчас не открылись" };
  }

  const memory = await loadMemory();
  const result = step(memory, market.candles, market.higher, news, { compact: market.symbol }, interval);
  await chrome.storage.local.set({ [MEMORY_KEY]: memory });

  let watchlist = [];
  if (options.watch !== false) watchlist = await rememberWatch({ ...spec, compact: market.symbol, tv: spec.tv }, interval);
  else {
    const bag = await chrome.storage.local.get(WATCH_KEY);
    watchlist = bag[WATCH_KEY] || [];
  }

  if (options.notify !== false) await notify({ ...spec, compact: market.symbol }, interval, result.analysis);

  const viewCount = 180;
  const candles = market.candles.slice(-viewCount);
  const shift = market.candles.length - candles.length;
  const drawings = attachDrawingTimes(clipDrawings(result.analysis.drawings, shift, candles.length), candles);
  return {
    ok: true,
    symbol: { ...spec, compact: market.symbol },
    interval,
    higherInterval: market.higherInterval,
    source: market.source,
    news,
    candles,
    analysis: {
      ...result.analysis,
      drawings,
    },
    closed: result.closed,
    opened: result.opened,
    summary: decorate(result.summary),
    watchlist,
    seed: seedInfo(),
    openTrades: (memory.open || []).filter((trade) => trade.symbol === market.symbol),
  };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return;
  if (msg.type === "analyze") {
    enqueue(() => analyze(msg.symbol, msg.interval, { watch: msg.watch !== false, notify: true }))
      .then(sendResponse)
      .catch((err) => sendResponse({ ok: false, error: err.message || String(err) }));
    return true;
  }
  if (msg.type === "reset") {
    enqueue(async () => {
      await chrome.storage.local.set({ [MEMORY_KEY]: cloneMemory(SEED) });
      return { ok: true };
    })
      .then(sendResponse)
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "unwatch") {
    enqueue(async () => {
      const bag = await chrome.storage.local.get(WATCH_KEY);
      const list = (bag[WATCH_KEY] || []).filter((item) => item.symbol !== msg.symbol);
      await chrome.storage.local.set({ [WATCH_KEY]: list });
      return { ok: true, watchlist: list };
    }).then(sendResponse);
    return true;
  }
  if (msg.type === "mute") {
    enqueue(async () => {
      const bag = await chrome.storage.local.get(META_KEY);
      const meta = bag[META_KEY] || {};
      meta.mute = !!msg.on;
      await chrome.storage.local.set({ [META_KEY]: meta });
      return { ok: true, mute: meta.mute };
    }).then(sendResponse);
    return true;
  }
  if (msg.type === "state") {
    enqueue(async () => {
      const memory = await loadMemory();
      const bag = await chrome.storage.local.get([WATCH_KEY, META_KEY]);
      return {
        ok: true,
        summary: decorate(memorySummary(memory)),
        watchlist: bag[WATCH_KEY] || [],
        mute: !!bag[META_KEY]?.mute,
        seed: seedInfo(),
      };
    }).then(sendResponse);
    return true;
  }
});

chrome.action.onClicked.addListener((tab) => {
  if (tab?.id && tab.url && tab.url.includes("tradingview.com")) {
    chrome.tabs.sendMessage(tab.id, { type: "toggle" }).catch(() => {});
    return;
  }
  chrome.tabs.create({ url: "https://www.tradingview.com/chart/?symbol=BINANCE:ETHUSDT" });
});

chrome.notifications.onClicked.addListener(() => {
  chrome.tabs.query({ url: ["https://*.tradingview.com/*", "https://www.tradingview.com/*"] }, (tabs) => {
    if (tabs && tabs[0]) {
      chrome.tabs.update(tabs[0].id, { active: true });
      if (tabs[0].windowId != null) chrome.windows.update(tabs[0].windowId, { focused: true });
    }
  });
});

async function watchPass() {
  const bag = await chrome.storage.local.get(WATCH_KEY);
  for (const item of bag[WATCH_KEY] || []) {
    try {
      await analyze(item.tv || item.symbol, item.interval || "15m", { watch: false, notify: true });
    } catch (err) {
      console.warn("watch", item.symbol, err);
    }
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("watch", { periodInMinutes: 1 });
});
chrome.alarms.create("watch", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== "watch") return;
  enqueue(() => watchPass()).catch((err) => console.warn(err));
});
