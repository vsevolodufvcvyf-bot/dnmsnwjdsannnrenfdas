import { step } from "../lib/engine.js";
import { cloneMemory } from "../lib/learn.js";
import { loadMarket, parseTvSymbol } from "../lib/market.js";
import { newsQuery, parseRss, scoreNews } from "../lib/news.js";
import { SEED } from "../lib/seed.js";
import { formatPrice } from "../lib/format.js";

const symbol = process.argv[2] || "SOLUSDT";
const interval = process.argv[3] || "15m";
const spec = parseTvSymbol(symbol);
const market = await loadMarket(spec, interval);
let news = { tone: "neutral", headlines: [], name: spec.base };
try {
  const nameRes = await fetch(`https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(spec.base)}`);
  const coins = ((await nameRes.json()).coins || []).filter((coin) => String(coin.symbol).toUpperCase() === spec.base);
  const name = coins[0]?.name || spec.base;
  const query = newsQuery(spec.base, name);
  const rss = await fetch(`https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=ru&gl=RU&ceid=RU:ru`);
  news = { ...scoreNews(parseRss(await rss.text(), 5), spec.base, name), name };
} catch (err) {
  news.error = err.message;
}
const memory = cloneMemory(SEED);
const result = step(memory, market.candles, market.higher, news, { compact: market.symbol }, interval);
const view = result.analysis;
console.log(JSON.stringify({
  symbol: market.symbol,
  source: market.source,
  interval,
  title: view.title,
  verdict: view.verdict,
  pattern: view.pattern && {
    name: view.pattern.name,
    entry: formatPrice(view.pattern.entry),
    stop: formatPrice(view.pattern.stop),
    target: formatPrice(view.pattern.target),
    score: Number(view.pattern.score.toFixed(2)),
  },
  move: view.move?.text || null,
  reasons: view.reasons,
  news: news.headlines?.slice(0, 3).map((item) => item.title),
  drawings: view.drawings.length,
}, null, 2));
