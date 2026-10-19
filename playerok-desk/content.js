const Desk = {
  busy: false,
  timer: 0,
  chip: null,
  status: null,
};

function loadDesk() {
  return chrome.storage.local.get("desk").then((stored) => DeskRules.normalize(stored.desk));
}

function saveDesk(desk) {
  return chrome.storage.local.set({ desk });
}

function edges(connection) {
  return ((connection && connection.edges) || []).map((edge) => edge && edge.node).filter(Boolean);
}

async function readBody(response) {
  const text = await response.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch (error) {
    body = { errors: [{ message: "Playerok ответил не JSON, HTTP " + response.status }] };
  }
  if (response.status === 429 || response.status === 403 || /cloudflare|captcha|just a moment/i.test(text)) {
    const pause = new Error(response.status === 429 ? "Playerok просит замедлиться" : "Playerok не пустил запрос. Обновите вкладку и пройдите проверку.");
    pause.pause = true;
    throw pause;
  }
  return body;
}

async function gql(operation, spec) {
  const headers = {
    accept: "*/*",
    "content-type": "application/json",
    "apollo-require-preflight": "true",
    "apollographql-client-name": "web",
    "x-apollo-operation-name": operation,
    "x-gql-op": operation,
    "x-timezone-offset": String(new Date().getTimezoneOffset()),
  };
  const post = async () => {
    const response = await fetch("https://playerok.com/graphql", {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify({
        operationName: operation,
        query: spec.query,
        variables: spec.variables || {},
      }),
    });
    return readBody(response);
  };
  let body;
  if (spec.hash) {
    const params = new URLSearchParams({
      operationName: operation,
      variables: JSON.stringify(spec.variables || {}),
      extensions: JSON.stringify({ persistedQuery: { version: 1, sha256Hash: spec.hash } }),
    });
    const response = await fetch("https://playerok.com/graphql?" + params.toString(), {
      method: "GET",
      credentials: "include",
      headers,
    });
    body = await readBody(response);
    if (JSON.stringify(body.errors || "").includes("PersistedQuery")) body = await post();
  } else {
    body = await post();
  }
  if (body.errors && body.errors.length) {
    throw new Error(body.errors.map((error) => error.message).filter(Boolean).join("; ") || "ошибка GraphQL");
  }
  return body.data || {};
}

async function steamNow() {
  const stored = await chrome.storage.local.get("steamOffset");
  return Math.floor(Date.now() / 1000) + Number(stored.steamOffset || 0);
}

function setStatus(text) {
  if (Desk.status) Desk.status.textContent = text;
}

async function sendChat(chatId, text) {
  const data = await gql("createChatMessage", {
    query: DeskQueries.DOC.createChatMessage,
    variables: { input: { chatId, text, imagesIds: [] } },
  });
  if (!data.createChatMessage || !data.createChatMessage.id) throw new Error("сообщение не принято");
  return data.createChatMessage;
}

async function markSent(dealId) {
  const data = await gql("updateDeal", {
    query: DeskQueries.DOC.updateDeal,
    variables: { input: { id: dealId, status: "SENT" } },
  });
  if (!data.updateDeal || data.updateDeal.status !== "SENT") throw new Error("статус «отправлен» не встал");
}

async function publishItem(itemId, priorityId) {
  await gql("publishItem", {
    query: DeskQueries.DOC.publishItem,
    variables: {
      input: {
        itemId,
        priorityStatuses: [priorityId],
        transactionProviderId: "LOCAL",
      },
      showForbiddenImage: true,
    },
  });
}

async function boostItem(itemId, priorityId) {
  await gql("increaseItemPriorityStatus", {
    query: DeskQueries.DOC.increaseItemPriorityStatus,
    variables: {
      input: {
        itemId,
        priorityStatuses: [priorityId],
        transactionProviderId: "LOCAL",
        transactionProviderData: { paymentMethodId: null },
      },
    },
  });
}

async function listDeals(userId) {
  const out = [];
  let after = null;
  for (let page = 0; page < 3; page++) {
    const data = await gql("deals", {
      hash: DeskQueries.HASH.deals,
      query: DeskQueries.DOC.deals,
      variables: {
        pagination: { first: 24, after },
        filter: { userId, direction: "OUT", status: ["PAID"] },
        showForbiddenImage: true,
      },
    });
    out.push(...edges(data.deals));
    if (!data.deals || !data.deals.pageInfo || !data.deals.pageInfo.hasNextPage) break;
    after = data.deals.pageInfo.endCursor;
  }
  return out;
}

async function listItems(userId, statuses) {
  const out = [];
  let after = null;
  for (let page = 0; page < 4; page++) {
    const data = await gql("items", {
      hash: DeskQueries.HASH.items,
      query: DeskQueries.DOC.items,
      variables: {
        pagination: { first: 24, after },
        filter: { userId, status: statuses },
        showForbiddenImage: true,
      },
    });
    out.push(...edges(data.items));
    if (!data.items || !data.items.pageInfo || !data.items.pageInfo.hasNextPage) break;
    after = data.items.pageInfo.endCursor;
  }
  return out;
}

async function handleDeal(desk, brief) {
  const now = Date.now();
  const full = await gql("deal", {
    hash: DeskQueries.HASH.deal,
    query: DeskQueries.DOC.deal,
    variables: { id: brief.id, hasSupportAccess: false, showForbiddenImage: true },
  });
  const deal = full.deal;
  if (!deal) return desk;
  const decision = DeskRules.decideDeal({
    deal,
    rules: desk.rules,
    accounts: desk.accounts,
    state: desk.state,
    now,
    settings: desk,
  });
  if (decision.action === "skip") return desk;
  if (decision.action === "park" || decision.action === "wait") {
    if (decision.action === "park") desk.state.processed[deal.id] = { status: "parked", at: now, reason: decision.reason };
    if (DeskRules.shouldLogWait(desk.state, deal.id, decision.reason, now)) {
      DeskRules.addLog(desk.state, (deal.item && deal.item.name ? deal.item.name + ": " : "") + decision.reason, now);
    }
    return desk;
  }
  if (decision.action === "markOnly") {
    if (!desk.practice && desk.markSent) {
      try {
        await markSent(deal.id);
        desk.state.processed[deal.id] = { status: "sent", at: now };
        DeskRules.addLog(desk.state, "отметил отправленным " + (deal.item && deal.item.name || deal.id), now);
      } catch (error) {
        DeskRules.addLog(desk.state, "отметка не встала: " + error.message, now);
      }
    }
    return desk;
  }
  const chatId = deal.chat && deal.chat.id;
  if (!chatId) {
    DeskRules.addLog(desk.state, "у сделки нет чата, не отправляю", now);
    return desk;
  }
  if (desk.practice) {
    const label = decision.action === "rent"
      ? "учебный: сдал бы " + decision.account.login + " на " + DeskRules.formatDuration(decision.durationSec)
      : "учебный: выдал бы «" + ((deal.item && deal.item.name) || "товар") + "»";
    if (DeskRules.shouldLogWait(desk.state, deal.id, label, now)) DeskRules.addLog(desk.state, label, now);
    return desk;
  }
  desk.state.processed[deal.id] = { status: "working", at: now };
  if (decision.action === "deliver") {
    const line = decision.line || "";
    const text = DeskRules.deliveryText(decision.rule, deal, line);
    if (decision.rule.kind === "stock") {
      desk.rules = desk.rules.map((rule) => rule.id === decision.rule.id ? DeskRules.takeStock(rule) : rule);
    }
    await saveDesk(desk);
    try {
      await sendChat(chatId, text);
    } catch (error) {
      desk.rules = desk.rules.map((rule) => rule.id === decision.rule.id ? DeskRules.returnStock(rule, line) : rule);
      desk.state.processed[deal.id] = { status: "failed", at: now };
      DeskRules.addLog(desk.state, "выдача не ушла, склад вернул: " + error.message, now);
      return desk;
    }
    desk.state.processed[deal.id] = { status: desk.markSent ? "sent_pending_mark" : "sent", at: now };
    DeskRules.addLog(desk.state, "выдал «" + (deal.item && deal.item.name || "товар") + "»", now);
    if (desk.markSent) {
      try {
        await markSent(deal.id);
        desk.state.processed[deal.id] = { status: "sent", at: Date.now() };
      } catch (error) {
        DeskRules.addLog(desk.state, "товар ушёл, отметка «отправлен» нет: " + error.message, now);
      }
    }
    return desk;
  }
  const account = desk.accounts.find((item) => item.id === decision.account.id);
  account.busy = true;
  account.dealId = deal.id;
  account.chatId = chatId;
  account.renterName = (deal.user && deal.user.username) || "";
  account.itemId = deal.item && deal.item.id;
  account.itemName = deal.item && deal.item.name;
  account.itemPrice = Number(deal.item && deal.item.price) || 0;
  account.startedAt = now;
  account.expireAt = now + decision.durationSec * 1000;
  account.durationSec = decision.durationSec;
  account.codesGiven = 0;
  await saveDesk(desk);
  const code = await DeskGuard.generateGuardCode(account.sharedSecret, await steamNow());
  const text = DeskRules.rentMessage({
    lot: account.itemName || "Steam",
    login: account.login,
    password: account.password,
    guard: code,
    duration: DeskRules.formatDuration(decision.durationSec),
    until: new Date(account.expireAt).toLocaleString("ru-RU"),
    note: decision.rule.template && decision.rule.template !== "Ваш товар:\n{product}" ? decision.rule.template : "",
  });
  try {
    await sendChat(chatId, text);
  } catch (error) {
    account.busy = false;
    account.expireAt = 0;
    desk.state.processed[deal.id] = { status: "failed", at: now };
    DeskRules.addLog(desk.state, "аренда " + account.login + " не ушла: " + error.message, now);
    return desk;
  }
  desk.state.processed[deal.id] = { status: "sent", at: now };
  DeskRules.addLog(desk.state, "сдал " + account.login + " до " + new Date(account.expireAt).toLocaleTimeString("ru-RU"), now);
  if (desk.markSent) {
    try { await markSent(deal.id); } catch (error) {
      DeskRules.addLog(desk.state, "доступ ушёл, отметка «отправлен» нет: " + error.message, now);
    }
  }
  return desk;
}

async function scanChats(desk) {
  const data = await gql("userChats", {
    hash: DeskQueries.HASH.userChats,
    query: DeskQueries.DOC.userChats,
    variables: { pagination: { first: 24 }, filter: {} },
  });
  const chats = edges(data.chats);
  if (!desk.state.chatsBootstrapped) {
    for (const chat of chats) {
      if (chat.lastMessage) desk.state.seenChats[chat.id] = chat.lastMessage.id;
    }
    desk.state.chatsBootstrapped = true;
    return desk;
  }
  for (const chat of chats) {
    const message = chat.lastMessage;
    if (!message || desk.state.seenChats[chat.id] === message.id) continue;
    desk.state.seenChats[chat.id] = message.id;
    const author = message.user && message.user.username;
    if (!author || author === desk.viewerName) continue;
    if (!DeskRules.guardRequest(message.text)) continue;
    const account = DeskRules.findRental(desk.accounts, chat, desk.viewerName, Date.now());
    if (!account) continue;
    if (account.codesGiven >= desk.maxGuardCodes) {
      DeskRules.addLog(desk.state, "лимит кодов для " + account.login, Date.now());
      continue;
    }
    if (desk.practice) {
      DeskRules.addLog(desk.state, "учебный: отправил бы код для " + account.login, Date.now());
      continue;
    }
    const code = await DeskGuard.generateGuardCode(account.sharedSecret, await steamNow());
    await sendChat(chat.id, "Steam Guard для " + account.login + ": " + code);
    account.codesGiven += 1;
    DeskRules.addLog(desk.state, "код для " + account.login + ", осталось " + (desk.maxGuardCodes - account.codesGiven), Date.now());
  }
  return desk;
}

async function finishOneRental(desk) {
  const now = Date.now();
  const account = desk.accounts.find((item) => item.busy && item.expireAt && item.expireAt <= now);
  if (!account) return desk;
  if (account.chatId && !desk.practice) {
    try {
      await sendChat(account.chatId, "Срок аренды закончился, доступ закрываю.");
    } catch (error) {
      DeskRules.addLog(desk.state, "не написал об окончании " + account.login + ": " + error.message, now);
    }
  }
  const item = { id: account.itemId, name: account.itemName, price: account.itemPrice, status: "SOLD" };
  account.busy = false;
  account.needsReset = true;
  account.expireAt = 0;
  await saveDesk(desk);
  if (desk.practice) {
    DeskRules.addLog(desk.state, "учебный: пароль " + account.login + " не менял", now);
    return desk;
  }
  const result = await chrome.runtime.sendMessage({ type: "rotate", accountId: account.id });
  desk = await loadDesk();
  if (!result || !result.ok) {
    DeskRules.addLog(desk.state, "пароль " + account.login + " не сменился: " + ((result && result.error) || "нет ответа"), Date.now());
    await saveDesk(desk);
    return desk;
  }
  DeskRules.addLog(desk.state, "пароль " + account.login + " сменён", Date.now());
  if (item.id) await relistOne(desk, item);
  await saveDesk(desk);
  return desk;
}

async function relistOne(desk, item) {
  const now = Date.now();
  const last = Number(desk.state.relistAt[item.id] || 0);
  if (last && now - last < 10 * 60 * 1000) return;
  const data = await gql("itemPriorityStatuses", {
    hash: DeskQueries.HASH.itemPriorityStatuses,
    query: DeskQueries.DOC.itemPriorityStatuses,
    variables: { itemId: item.id, price: Math.max(0, Number(item.price) || 0) },
  });
  const pick = DeskRules.pickPriority(data.itemPriorityStatuses, false, 0);
  desk.state.relistAt[item.id] = now;
  if (!pick.status) {
    DeskRules.addLog(desk.state, (item.name || item.id) + ": " + pick.reason, now);
    return;
  }
  if (desk.practice) {
    DeskRules.addLog(desk.state, "учебный: перевыставил бы «" + (item.name || item.id) + "» бесплатно", now);
    return;
  }
  await publishItem(item.id, pick.status.id);
  DeskRules.addLog(desk.state, "перевыставил «" + (item.name || item.id) + "»", now);
}

async function relistScan(desk) {
  if (!desk.viewerId) return desk;
  const wantSold = desk.relistSold || desk.rules.some((rule) => rule.relist && rule.active !== false);
  if (!wantSold && !desk.boostEnabled) return desk;
  if (wantSold) {
    const items = await listItems(desk.viewerId, ["SOLD", "EXPIRED"]);
    for (const item of items) {
      if (!DeskRules.relistAllowed(item, desk, Date.now())) continue;
      await relistOne(desk, item);
    }
  }
  if (desk.boostEnabled) {
    const active = await listItems(desk.viewerId, ["APPROVED"]);
    for (const item of active) {
      const blocked = desk.accounts.some((account) => account.itemId === item.id && (account.busy || account.needsReset));
      if (blocked) continue;
      if (!DeskRules.canBoost(item, desk.state, desk, Date.now())) continue;
      const data = await gql("itemPriorityStatuses", {
        hash: DeskQueries.HASH.itemPriorityStatuses,
        query: DeskQueries.DOC.itemPriorityStatuses,
        variables: { itemId: item.id, price: Math.max(0, Number(item.price) || 0) },
      });
      const pick = DeskRules.pickPriority(data.itemPriorityStatuses, true, desk.boostMaxPrice);
      if (!pick.status || !pick.paid) continue;
      const day = DeskRules.dayKey(Date.now());
      if (desk.practice) {
        DeskRules.addLog(desk.state, "учебный: поднял бы «" + item.name + "» за " + pick.status.price + " ₽", Date.now());
      } else {
        await boostItem(item.id, pick.status.id);
        DeskRules.addLog(desk.state, "поднял «" + item.name + "» за " + pick.status.price + " ₽", Date.now());
        desk.state.boostDay[day] = Number(desk.state.boostDay[day] || 0) + 1;
      }
      desk.state.relistAt["boost:" + item.id] = Date.now();
    }
  }
  return desk;
}

async function tick() {
  if (Desk.busy) return;
  Desk.busy = true;
  try {
    let desk = await loadDesk();
    if (!desk.enabled) {
      setStatus("выключен");
      return;
    }
    const now = Date.now();
    for (const account of desk.accounts) {
      if (!account.busy || !account.dealId) continue;
      const prev = desk.state.processed[account.dealId];
      if (prev && prev.status === "working" && now - Number(prev.at || 0) > 120000) {
        account.busy = false;
        account.expireAt = 0;
        prev.status = "failed";
        DeskRules.addLog(desk.state, "зависшую аренду " + account.login + " снял, товар не ушёл", now);
      }
    }
    setStatus(desk.practice ? "учебный проход" : "проверяю сделки");
    const viewer = await gql("viewer", { query: DeskQueries.DOC.viewer, variables: {} });
    if (!viewer.viewer || !viewer.viewer.id) throw new Error("нет входа на Playerok");
    desk.viewerId = viewer.viewer.id;
    desk.viewerName = viewer.viewer.username;
    const deals = await listDeals(viewer.viewer.id);
    for (const brief of deals) {
      desk = await handleDeal(desk, brief);
      await saveDesk(desk);
    }
    desk = await scanChats(desk);
    await saveDesk(desk);
    desk = await finishOneRental(desk);
    await saveDesk(desk);
    desk = await relistScan(desk);
    await saveDesk(desk);
    const last = desk.state.log[0];
    setStatus(desk.practice ? "учебный" : "включён");
    if (last) setStatus((desk.practice ? "учебный · " : "") + last.text);
  } catch (error) {
    setStatus(error.message || "ошибка");
    try {
      const desk = await loadDesk();
      DeskRules.addLog(desk.state, error.message || "ошибка", Date.now());
      await saveDesk(desk);
    } catch (ignore) {
      /* журнал уже недоступен */
    }
    if (error.pause) {
      clearInterval(Desk.timer);
      Desk.timer = setInterval(tick, 60000);
    }
  } finally {
    Desk.busy = false;
  }
}

function mountChip() {
  if (document.getElementById("playerok-desk-chip")) return;
  const chip = document.createElement("div");
  chip.id = "playerok-desk-chip";
  const title = document.createElement("strong");
  title.textContent = "Desk";
  const status = document.createElement("span");
  const run = document.createElement("button");
  run.type = "button";
  run.textContent = "Сейчас";
  run.addEventListener("click", () => tick());
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = "Настройки";
  open.addEventListener("click", () => chrome.runtime.sendMessage({ type: "open-options" }));
  chip.append(title, status, run, open);
  document.documentElement.append(chip);
  Desk.chip = chip;
  Desk.status = status;
}

function schedule(seconds) {
  clearInterval(Desk.timer);
  Desk.timer = setInterval(tick, Math.max(12, seconds) * 1000);
}

mountChip();
loadDesk().then((desk) => {
  setStatus(desk.enabled ? (desk.practice ? "учебный, жду проход" : "включён") : "выключен");
  schedule(desk.pollSec);
  if (desk.enabled) tick();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.desk) return;
  const desk = DeskRules.normalize(changes.desk.newValue);
  schedule(desk.pollSec);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "tick") return;
  tick().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});
