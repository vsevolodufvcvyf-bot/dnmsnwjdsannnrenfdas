/** Тон заголовков. Это фильтр, не самостоятельный сигнал направления. */

const BEAR = [
  [/взлом|хакер|hack|exploit|утечк|drain/i, 2],
  [/иск|судеб|sec\b|запрет|\bban\b|lawsuit|делист|delist|санкц/i, 2],
  [/банкрот|обвал|\bcrash\b|rug|скам|scam|мошен|взят/i, 2],
  [/unlock|разлок|outage|сбо[йя]|halt|приостанов/i, 1],
  [/паден|обвал|sell[- ]?off|ликвидац/i, 1],
];

const BULL = [
  [/листинг|\blisting\b|\betf\b/i, 2],
  [/одобрен|approval|adopt|внедрен/i, 2],
  [/партн[её]р|partnership|integrat|интеграц/i, 1],
  [/апгрейд|upgrade|mainnet|мейннет|запуск/i, 1],
  [/рекорд|\brally\b|ath|покупк[аи] кит/i, 1],
];

export function decodeXml(s) {
  return String(s || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/<[^>]+>/g, "")
    .trim();
}

export function parseRss(xml, limit = 8) {
  const items = [];
  const blocks = String(xml || "").split(/<item[\s>]/i).slice(1);
  for (const block of blocks) {
    if (items.length >= limit) break;
    const title = decodeXml((block.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || "");
    const link = decodeXml((block.match(/<link[^>]*>([\s\S]*?)<\/link>/i) || [])[1] || "");
    const pub = decodeXml((block.match(/<pubDate[^>]*>([\s\S]*?)<\/pubDate>/i) || [])[1] || "");
    if (!title || title === "Google Новости") continue;
    items.push({ title, link, published: pub });
  }
  return items;
}

function toneOf(text) {
  let score = 0;
  for (const [re, w] of BEAR) if (re.test(text)) score -= w;
  for (const [re, w] of BULL) if (re.test(text)) score += w;
  return score;
}

export function scoreNews(items, base, name) {
  const key = String(base || "").toLowerCase();
  const full = String(name || "").toLowerCase();
  let score = 0;
  let used = 0;
  const headlines = [];
  for (const item of items || []) {
    const title = item.title || "";
    const low = title.toLowerCase();
    const mentions =
      (key.length >= 2 && new RegExp(`(^|[^a-zа-я0-9])${key}([^a-zа-я0-9]|$)`, "i").test(title)) ||
      (full.length >= 3 && low.includes(full));
    const weight = mentions || !full ? 1 : 0.35;
    const s = toneOf(title) * weight;
    score += s;
    used++;
    headlines.push({
      title,
      link: item.link || "",
      published: item.published || "",
      mentions,
      tone: s > 0.4 ? "bull" : s < -0.4 ? "bear" : "neutral",
    });
  }
  let tone = "neutral";
  if (score >= 2) tone = "bull";
  else if (score <= -2) tone = "bear";
  return {
    tone,
    score,
    used,
    headlines: headlines.slice(0, 6),
  };
}

export function newsQuery(base, name) {
  const label = name && name.toLowerCase() !== String(base || "").toLowerCase() ? `${name} ${base}` : base;
  return `${label} криптовалюта`;
}
