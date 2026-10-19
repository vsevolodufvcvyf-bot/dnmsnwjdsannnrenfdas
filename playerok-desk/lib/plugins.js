(function (root, factory) {
  const api = factory();
  root.DeskPlugins = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const REWARD = /бонус|скидк|подар(?:ок|ю|ка)|бесплатн|промокод|\+\s*\d+\s*час/i;

  function rewardOffer(text) {
    return REWARD.test(String(text || ""));
  }

  function consumeStock(desk, rule) {
    if (!rule || rule.kind !== "stock") return "";
    if (rule.warehouseId) {
      const warehouse = (desk.warehouses || []).find((item) => item.id === rule.warehouseId);
      if (!warehouse || !(warehouse.stock || []).length) return "";
      return warehouse.stock.shift();
    }
    const live = (desk.rules || []).find((item) => item.id === rule.id) || rule;
    if (!(live.stock || []).length) return "";
    return live.stock.shift();
  }

  function restoreStock(desk, rule, line) {
    if (!rule || !line) return;
    if (rule.warehouseId) {
      const warehouse = (desk.warehouses || []).find((item) => item.id === rule.warehouseId);
      if (warehouse) warehouse.stock.unshift(line);
      return;
    }
    const live = (desk.rules || []).find((item) => item.id === rule.id) || rule;
    live.stock = live.stock || [];
    live.stock.unshift(line);
  }

  function replyForRating(replies, rating) {
    if (!replies || !replies.enabled) return "";
    const text = String((replies.stars || {})[String(rating)] || "").trim();
    if (!text || rewardOffer(text)) return "";
    return text;
  }

  function safeText(text) {
    const value = String(text || "").trim();
    if (!value || rewardOffer(value)) return "";
    return value;
  }

  function planReminder(entry, reminder, now, hasReview) {
    if (!reminder || !reminder.enabled) return null;
    if (hasReview) return { stop: true };
    const sent = Number(entry && entry.sent || 0);
    if (sent >= Number(reminder.times || 1)) return null;
    const first = Number(reminder.firstDelayMin || 60) * 60000;
    const gap = Number(reminder.intervalMin || 1440) * 60000;
    const due = entry && entry.nextAt ? Number(entry.nextAt) : Number(entry && entry.confirmedAt || now) + first;
    if (now < due) return { wait: true };
    return { send: true, nextAt: now + gap, sent: sent + 1 };
  }

  function hourAllows(slots, date) {
    if (!slots || !slots.length) return true;
    const day = (date.getDay() + 6) % 7;
    return slots.includes(day + ":" + date.getHours());
  }

  function rememberBuyer(state, buyer, dealId, price, status) {
    if (!buyer || !dealId) return;
    const rows = state.buyers[buyer] || [];
    if (rows.some((row) => row.id === dealId)) return;
    rows.push({ id: dealId, price: Number(price) || 0, status: status || "" });
    state.buyers[buyer] = rows.slice(-30);
  }

  function dossier(state, buyer) {
    const rows = (state.buyers && state.buyers[buyer]) || [];
    const refunds = rows.filter((row) => row.status === "ROLLED_BACK" || row.status === "refunded").length;
    const sales = rows.filter((row) => row.status !== "ROLLED_BACK" && row.status !== "refunded");
    const sum = sales.reduce((total, row) => total + Number(row.price || 0), 0);
    return { count: sales.length, sum, refunds };
  }

  function funpayChatId(selfId, buyerId) {
    const ids = [Number(selfId), Number(buyerId)].sort((a, b) => a - b);
    return "users-" + ids[0] + "-" + ids[1];
  }

  function parseFunpaySales(html) {
    const text = String(html || "");
    const app = /data-app-data="([^"]+)"/.exec(text);
    let csrf = "";
    let userId = "";
    if (app) {
      try {
        const data = JSON.parse(app[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
        csrf = data["csrf-token"] || "";
        userId = data.userId || "";
      } catch (error) {
        csrf = "";
      }
    }
    const sales = [];
    const opener = /<a\b[^>]*class="([^"]*\btc-item\b[^"]*)"[^>]*>/ig;
    let opened;
    while ((opened = opener.exec(text))) {
      const classes = opened[1];
      const part = text.slice(opened.index, text.indexOf("</a>", opened.index));
      let status = "closed";
      if (/\bwarning\b/.test(classes)) status = "refunded";
      else if (/\binfo\b/.test(classes)) status = "paid";
      const order = /class="tc-order"[^>]*>\s*#?\s*([^<]+)/i.exec(part);
      const desc = /class="order-desc"[\s\S]*?<div[^>]*>\s*([^<]+)/i.exec(part);
      const priceText = /class="tc-price"[^>]*>([\s\S]*?)<\/div>/i.exec(part);
      const buyer = /class="media-user-name"[\s\S]*?data-href="([^"]+)"[^>]*>\s*(?:<span[^>]*>)?\s*([^<]+)/i.exec(part)
        || /data-href="([^"]+)"[\s\S]*?class="media-user-name"[\s\S]*?<span[^>]*>\s*([^<]+)/i.exec(part);
      if (!order || !priceText || !buyer) continue;
      const rawPrice = priceText[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      const priceMatch = /^([\d\s]+(?:[.,]\d+)?)\s+\S+/.exec(rawPrice);
      const href = buyer[1];
      const buyerId = href.split("?")[0].replace(/\/+$/, "").split("/").pop();
      sales.push({
        id: order[1].trim().replace(/^#/, ""),
        status,
        description: desc ? desc[1].trim() : "",
        price: priceMatch ? Number(priceMatch[1].replace(/\s/g, "").replace(",", ".")) : 0,
        buyer: buyer[2].trim(),
        buyerId,
        chatId: funpayChatId(userId || 0, buyerId),
      });
    }
    return { csrf, userId, sales };
  }

  return {
    rewardOffer,
    consumeStock,
    restoreStock,
    replyForRating,
    safeText,
    planReminder,
    hourAllows,
    rememberBuyer,
    dossier,
    funpayChatId,
    parseFunpaySales,
  };
});
