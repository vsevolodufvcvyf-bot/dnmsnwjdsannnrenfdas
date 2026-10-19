(function (root, factory) {
  const api = factory();
  root.DeskRules = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const UNIT = "(ч(?!\\p{L})|час\\p{L}*|h\\b|hours?\\b|д(?!\\p{L})|дн\\p{L}*|день|сут\\p{L}*|d\\b|days?\\b|нед\\p{L}*|w\\b|weeks?\\b)";
  const TAG_RE = new RegExp("\\[\\s*(?:rent|аренда|срок)\\s*:?\\s*(\\d+)\\s*" + UNIT + "\\s*\\]", "iu");
  const PHRASE_RES = [
    new RegExp("аренд\\p{L}*\\s+на\\s+(\\d+)\\s*" + UNIT, "iu"),
    new RegExp("(\\d+)\\s*" + UNIT + "\\s+аренд\\p{L}*", "iu"),
    new RegExp("срок\\p{L}*\\s*(?:аренды)?\\s*[:\\-—]?\\s*(\\d+)\\s*" + UNIT, "iu"),
    new RegExp("(?<!\\p{L})на\\s+(\\d+)\\s*" + UNIT, "iu"),
  ];
  const WORD_RES = [
    [/аренд\p{L}*\s+на\s+сутки|(?<!\p{L})на\s+сутки/iu, 86400],
    [/аренд\p{L}*\s+на\s+недел\p{L}*|(?<!\p{L})на\s+недел[юи]/iu, 604800],
    [/аренд\p{L}*\s+на\s+час(?!\p{L})|(?<!\p{L})на\s+час(?!\p{L})|(?<!\p{L})на\s+1\s+час(?!\p{L})/iu, 3600],
  ];
  const RENT_BLOCK = [
    /instagram|инстаграм|tiktok|тикток|вконтакте/i,
    /аккаунт\s+telegram|telegram-аккаунт/i,
    /почтов\w*\s+ящик|аккаунт\s+gmail|аккаунт\s+outlook/i,
    /аренда\s+номера|прокат\s+номера/i,
    /\btdata\b|токен-аккаунт|cookie-аккаунт|через\s+cookie/i,
    /продажа\s+vpn|продажа\s+прокси|vpn\s+сервис/i,
  ];
  const GUARD_WORDS = ["код", "гвард", "guard", "2fa", "!code", "!код", "code"];
  const GUARD_PHRASES = ["где код", "дай код", "код стим"];

  function defaultDesk() {
    return {
      enabled: false,
      practice: true,
      pollSec: 15,
      proxy: "",
      markSent: true,
      maxGuardCodes: 10,
      maxRentHours: 336,
      relistSold: false,
      boostEnabled: false,
      boostMaxPrice: 25,
      boostDailyCap: 10,
      boostMinIntervalSec: 6 * 3600,
      boostAfterPosition: 20,
      rules: [],
      accounts: [],
      state: {
        processed: {},
        seenChats: {},
        chatsBootstrapped: false,
        relistAt: {},
        boostDay: {},
        waitLog: {},
        log: [],
      },
    };
  }

  function flag(value, fallback) {
    return typeof value === "boolean" ? value : fallback;
  }

  function clamp(n, min, max) {
    const x = Number(n);
    if (!Number.isFinite(x)) return min;
    return Math.min(max, Math.max(min, Math.round(x)));
  }

  function normalizeRule(rule) {
    return {
      id: String(rule.id || crypto.randomUUID()),
      kind: rule.kind === "rent" || rule.kind === "text" ? rule.kind : "stock",
      active: rule.active !== false,
      relist: Boolean(rule.relist),
      title: String(rule.title || ""),
      itemIds: splitList(rule.itemIds),
      keywords: String(rule.keywords || ""),
      template: String(rule.template || "Ваш товар:\n{product}"),
      stock: Array.isArray(rule.stock) ? rule.stock.map((x) => String(x)) : splitLines(rule.stockText || ""),
    };
  }

  function normalizeAccount(account) {
    return {
      id: String(account.id || crypto.randomUUID()),
      login: String(account.login || ""),
      password: String(account.password || ""),
      sharedSecret: String(account.sharedSecret || ""),
      identitySecret: String(account.identitySecret || ""),
      steamid: String(account.steamid || ""),
      keywords: String(account.keywords || ""),
      itemIds: splitList(account.itemIds),
      busy: Boolean(account.busy),
      needsReset: Boolean(account.needsReset),
      expireAt: Number(account.expireAt || 0),
      chatId: account.chatId || "",
      renterName: account.renterName || "",
      dealId: account.dealId || "",
      itemId: account.itemId || "",
      itemName: account.itemName || "",
      itemPrice: Number(account.itemPrice || 0),
      codesGiven: Number(account.codesGiven || 0),
      durationSec: Number(account.durationSec || 0),
      startedAt: Number(account.startedAt || 0),
    };
  }

  function normalize(raw) {
    const base = defaultDesk();
    if (!raw || typeof raw !== "object") return base;
    const state = raw.state || {};
    return {
      ...base,
      enabled: flag(raw.enabled, false),
      practice: flag(raw.practice, true),
      pollSec: clamp(raw.pollSec ?? base.pollSec, 12, 120),
      proxy: String(raw.proxy || ""),
      markSent: flag(raw.markSent, true),
      maxGuardCodes: clamp(raw.maxGuardCodes ?? 10, 1, 30),
      maxRentHours: clamp(raw.maxRentHours ?? 336, 1, 336),
      relistSold: flag(raw.relistSold, false),
      boostEnabled: flag(raw.boostEnabled, false),
      boostMaxPrice: clamp(raw.boostMaxPrice ?? 25, 0, 500),
      boostDailyCap: clamp(raw.boostDailyCap ?? 10, 0, 100),
      boostMinIntervalSec: clamp(raw.boostMinIntervalSec ?? base.boostMinIntervalSec, 600, 7 * 86400),
      boostAfterPosition: clamp(raw.boostAfterPosition ?? 20, 1, 500),
      rules: Array.isArray(raw.rules) ? raw.rules.map(normalizeRule) : [],
      accounts: Array.isArray(raw.accounts) ? raw.accounts.map(normalizeAccount) : [],
      state: {
        processed: state.processed && typeof state.processed === "object" ? state.processed : {},
        seenChats: state.seenChats && typeof state.seenChats === "object" ? state.seenChats : {},
        chatsBootstrapped: Boolean(state.chatsBootstrapped),
        relistAt: state.relistAt && typeof state.relistAt === "object" ? state.relistAt : {},
        boostDay: state.boostDay && typeof state.boostDay === "object" ? state.boostDay : {},
        waitLog: state.waitLog && typeof state.waitLog === "object" ? state.waitLog : {},
        log: Array.isArray(state.log) ? state.log.slice(0, 80) : [],
      },
    };
  }

  function splitList(value) {
    if (Array.isArray(value)) return value.map((x) => String(x).trim()).filter(Boolean);
    return String(value || "").split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
  }

  function splitLines(value) {
    return String(value || "").split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
  }

  function keywordsOf(value) {
    return String(value || "").split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  }

  function dealText(deal) {
    const item = deal && deal.item ? deal.item : {};
    const category = item.category && item.category.name ? item.category.name : "";
    return [item.name || "", category, deal && deal.commentFromBuyer || ""].join(" ");
  }

  function unitSeconds(unit) {
    const u = String(unit || "").toLowerCase();
    if (u.startsWith("ч") || u.startsWith("h")) return 3600;
    if (u.startsWith("н") || u.startsWith("w")) return 604800;
    return 86400;
  }

  function parseRentDuration(orderDesc, orderAmount, maxHours) {
    const text = orderDesc || "";
    const amount = Math.max(1, Number(orderAmount) || 1);
    const limit = Math.max(1, Number(maxHours) || 336);
    let base = null;
    let how = "";
    const tag = TAG_RE.exec(text);
    if (tag) {
      base = Number(tag[1]) * unitSeconds(tag[2]);
      how = "тег «" + tag[0] + "»";
    }
    if (base == null) {
      for (const rx of PHRASE_RES) {
        const m = rx.exec(text);
        if (m) {
          base = Number(m[1]) * unitSeconds(m[2]);
          how = "фраза «" + m[0].trim() + "»";
          break;
        }
      }
    }
    if (base == null) {
      for (const [rx, seconds] of WORD_RES) {
        const m = rx.exec(text);
        if (m) {
          base = seconds;
          how = "фраза «" + m[0].trim() + "»";
          break;
        }
      }
    }
    if (!base) {
      return { seconds: null, how: "в названии нет срока (нужен тег [rent: 3h] или «аренда на 3 часа»)" };
    }
    const total = base * amount;
    if (total > limit * 3600) {
      return { seconds: null, how: "срок " + Math.floor(total / 3600) + " ч больше лимита " + limit + " ч (" + how + ")" };
    }
    return { seconds: total, how };
  }

  function blockedRent(text) {
    return RENT_BLOCK.some((rx) => rx.test(text || ""));
  }

  function matchRule(rules, deal) {
    const itemId = deal && deal.item && deal.item.id;
    const name = dealText(deal).toLowerCase();
    const active = (rules || []).filter((rule) => rule.active !== false);
    const byId = active.find((rule) => (rule.itemIds || []).includes(itemId));
    if (byId) return byId;
    let best = null;
    let bestLen = 0;
    for (const rule of active) {
      if ((rule.itemIds || []).length) continue;
      for (const word of keywordsOf(rule.keywords)) {
        if (name.includes(word) && word.length > bestLen) {
          best = rule;
          bestLen = word.length;
        }
      }
    }
    return best;
  }

  function renderTemplate(template, fields) {
    return String(template || "").replace(/\{(\w+)\}/g, (all, key) => (
      Object.prototype.hasOwnProperty.call(fields, key) && fields[key] != null ? String(fields[key]) : all
    ));
  }

  function buyerFields(deal) {
    const rows = [];
    for (const field of (deal && deal.obtainingFields) || []) {
      if (!field || field.hidden) continue;
      if (field.value) rows.push((field.label || "поле") + ": " + field.value);
    }
    return rows.join("\n");
  }

  function missingRequired(deal) {
    return ((deal && deal.obtainingFields) || []).filter((field) => field && field.required && !String(field.value || "").trim());
  }

  function formatDuration(seconds) {
    const s = Math.max(0, Number(seconds) || 0);
    if (s >= 604800) {
      const weeks = Math.floor(s / 604800);
      return weeks > 1 ? weeks + " нед." : "1 неделя";
    }
    if (s >= 86400) {
      const days = Math.floor(s / 86400);
      return days > 1 ? days + " дн." : "1 день";
    }
    const hours = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    return mins > 0 ? hours + " ч. " + mins + " мин." : hours + " ч.";
  }

  function rentMessage(fields) {
    return [
      "Данные аренды (" + fields.lot + "):",
      "Логин: " + fields.login,
      "Пароль: " + fields.password,
      "Steam Guard: " + fields.guard + " (около 30 сек)",
      "Срок: " + fields.duration + ", до " + fields.until,
      "",
      "Новый код: напишите «код» в этот чат.",
      "Не меняйте почту и номер, не ставьте читы.",
      "Когда время выйдет, пароль сменится и вход закроется.",
      fields.note ? "\n" + fields.note : "",
    ].filter((line, index, list) => line !== "" || index < list.length - 1).join("\n");
  }

  function guardRequest(text) {
    const value = String(text || "").trim().toLowerCase();
    if (!value || value.length > 40) return false;
    if (GUARD_PHRASES.some((phrase) => value.includes(phrase))) return true;
    const parts = value.split(/\s+/);
    return parts.length <= 3 && parts.some((part) => GUARD_WORDS.includes(part));
  }

  function canRetry(prev, now) {
    if (!prev) return true;
    if (prev.status === "sent" || prev.status === "parked") return false;
    if (prev.status === "sent_pending_mark") return false;
    if (prev.status === "working" && now - Number(prev.at || 0) < 120000) return false;
    return prev.status === "failed" || prev.status === "working";
  }

  function accountMatches(account, deal) {
    const itemId = deal && deal.item && deal.item.id;
    if ((account.itemIds || []).includes(itemId)) return true;
    const name = dealText(deal).toLowerCase();
    return keywordsOf(account.keywords).some((word) => name.includes(word));
  }

  function accountFree(account, now) {
    if (!account || account.busy || account.needsReset) return false;
    if (!String(account.password || "").trim() || !account.sharedSecret) return false;
    if (account.expireAt && account.expireAt > now) return false;
    return true;
  }

  function pickAccount(accounts, deal, now) {
    return (accounts || []).find((account) => accountFree(account, now) && accountMatches(account, deal)) || null;
  }

  function decideDeal({ deal, rules, accounts, state, now, settings }) {
    const id = deal && deal.id;
    if (!id) return { action: "skip", reason: "нет сделки" };
    const prev = state && state.processed ? state.processed[id] : null;
    if (prev && prev.status === "sent_pending_mark") return { action: "markOnly", dealId: id };
    if (!canRetry(prev, now)) return { action: "skip", reason: "уже обработана" };
    if (deal.direction && deal.direction !== "OUT") return { action: "skip", reason: "это покупка, не продажа" };
    if (deal.status !== "PAID") return { action: "skip", reason: "статус " + (deal.status || "неизвестен") };
    if (deal.hasProblem) return { action: "park", reason: "по сделке проблема, сам не выдаю" };
    if (deal.isAutomated) return { action: "park", reason: "Playerok уже выдал товар сам" };
    const rule = matchRule(rules, deal);
    if (!rule) return { action: "skip", reason: "нет правила" };
    const required = missingRequired(deal);
    if (required.length) {
      return { action: "wait", reason: "нет данных покупателя: " + required.map((field) => field.label || "поле").join(", ") };
    }
    if (rule.kind === "rent") {
      const text = dealText(deal);
      if (blockedRent(text)) return { action: "park", reason: "лот похож на запрещённый товар Playerok (соцсеть, почта, номер, cookie, VPN)" };
      const duration = parseRentDuration(text, 1, settings.maxRentHours);
      if (!duration.seconds) return { action: "park", reason: duration.how };
      const account = pickAccount(accounts, deal, now);
      if (!account) return { action: "wait", reason: "нет свободного аккаунта с паролем и maFile под этот лот" };
      return { action: "rent", rule, account, durationSec: duration.seconds, how: duration.how };
    }
    if (rule.kind === "stock") {
      if (!(rule.stock || []).length) return { action: "wait", reason: "склад правила «" + (rule.title || rule.id) + "» пуст" };
      return { action: "deliver", rule, line: rule.stock[0] };
    }
    return { action: "deliver", rule, line: "" };
  }

  function deliveryText(rule, deal, line) {
    return renderTemplate(rule.template, {
      product: line || "",
      name: (deal.user && deal.user.username) || "",
      lot: (deal.item && deal.item.name) || "",
      fields: buyerFields(deal),
      comment: deal.commentFromBuyer || "",
    });
  }

  function takeStock(rule) {
    if (!rule || rule.kind !== "stock") return rule;
    return { ...rule, stock: (rule.stock || []).slice(1) };
  }

  function returnStock(rule, line) {
    if (!rule || rule.kind !== "stock" || !line) return rule;
    return { ...rule, stock: [line, ...(rule.stock || [])] };
  }

  function pickPriority(statuses, allowPaid, maxPrice) {
    const list = statuses || [];
    const free = list.filter((status) => Number(status.price) === 0);
    if (free.length) return { status: free[0], paid: false };
    if (!allowPaid) return { status: null, reason: "бесплатного выставления нет, платное выключено" };
    const cap = Number(maxPrice);
    const priced = list
      .filter((status) => Number(status.price) > 0 && Number(status.price) <= cap)
      .sort((a, b) => Number(a.price) - Number(b.price));
    if (!priced.length) return { status: null, reason: "нет статуса дешевле лимита " + cap + " ₽" };
    return { status: priced[0], paid: true };
  }

  function linkedAccounts(accounts, item) {
    const fakeDeal = { item };
    return (accounts || []).filter((account) => accountMatches(account, fakeDeal));
  }

  function relistAllowed(item, desk, now) {
    if (!item || (item.status !== "SOLD" && item.status !== "EXPIRED")) return false;
    const rule = matchRule(desk.rules || [], { item });
    if (rule && rule.kind !== "rent" && rule.relist) {
      if (rule.kind === "stock" && !(rule.stock || []).length) return false;
      return true;
    }
    if (!desk.relistSold) return false;
    return canRelistItem(item, desk.accounts, now);
  }

  function canRelistItem(item, accounts, now) {
    if (!item || (item.status !== "SOLD" && item.status !== "EXPIRED")) return false;
    const linked = linkedAccounts(accounts, item);
    if (!linked.length) return false;
    return linked.every((account) => !account.busy && !account.needsReset && !(account.expireAt > now));
  }

  function dayKey(now) {
    const date = new Date(now);
    return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
  }

  function canBoost(item, state, settings, now) {
    if (!settings.boostEnabled || !item || item.status !== "APPROVED") return false;
    const position = Number(item.priorityPosition || 0);
    if (position && position <= settings.boostAfterPosition) return false;
    const last = Number((state.relistAt || {})["boost:" + item.id] || 0);
    if (now - last < settings.boostMinIntervalSec * 1000) return false;
    const used = Number((state.boostDay || {})[dayKey(now)] || 0);
    return used < settings.boostDailyCap;
  }

  function addLog(state, text, now) {
    const clean = String(text || "")
      .replace(/[A-Za-z0-9+/]{20,}={0,2}/g, "•••")
      .slice(0, 500);
    state.log = [{ at: now || Date.now(), text: clean }, ...(state.log || [])].slice(0, 80);
  }

  function shouldLogWait(state, dealId, reason, now) {
    const prev = state.waitLog[dealId];
    if (prev && prev.reason === reason && now - prev.at < 30 * 60 * 1000) return false;
    state.waitLog[dealId] = { reason, at: now };
    return true;
  }

  function parseMafile(text) {
    const data = JSON.parse(text);
    const session = data.Session || data.session || {};
    const sharedSecret = data.shared_secret || data.sharedSecret || "";
    if (!sharedSecret) throw new Error("в maFile нет shared_secret");
    return {
      login: String(data.account_name || data.accountName || data.login || ""),
      sharedSecret: String(sharedSecret),
      identitySecret: String(data.identity_secret || data.identitySecret || ""),
      steamid: String(session.SteamID || session.steamid || data.steamid || data.SteamID || ""),
    };
  }

  function generatePassword() {
    const lower = "abcdefghijkmnopqrstuvwxyz";
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const digits = "23456789";
    const all = lower + upper + digits;
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    const chars = [
      lower[bytes[0] % lower.length],
      upper[bytes[1] % upper.length],
      digits[bytes[2] % digits.length],
    ];
    for (let i = 3; i < 16; i++) chars.push(all[bytes[i] % all.length]);
    for (let i = chars.length - 1; i > 0; i--) {
      const j = bytes[i % bytes.length] % (i + 1);
      const tmp = chars[i];
      chars[i] = chars[j];
      chars[j] = tmp;
    }
    return chars.join("");
  }

  function findRental(accounts, chat, viewerName, now) {
    const names = new Set(
      ((chat && chat.participants) || [])
        .map((user) => (user.username || "").toLowerCase())
        .filter((name) => name && name !== String(viewerName || "").toLowerCase())
    );
    return (accounts || []).find((account) => {
      if (!account.busy || !(account.expireAt > now) || !account.sharedSecret) return false;
      if (chat && account.chatId && chat.id === account.chatId) return true;
      return names.has(String(account.renterName || "").toLowerCase());
    }) || null;
  }

  return {
    defaultDesk,
    normalize,
    splitLines,
    splitList,
    parseRentDuration,
    blockedRent,
    matchRule,
    renderTemplate,
    buyerFields,
    formatDuration,
    rentMessage,
    guardRequest,
    decideDeal,
    deliveryText,
    takeStock,
    returnStock,
    pickPriority,
    canRelistItem,
    relistAllowed,
    canBoost,
    dayKey,
    addLog,
    shouldLogWait,
    parseMafile,
    generatePassword,
    findRental,
    pickAccount,
  };
});
