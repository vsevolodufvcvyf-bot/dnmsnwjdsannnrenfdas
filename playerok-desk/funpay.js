let busy = false;
let timer = 0;

function loadDesk() {
  return chrome.storage.local.get("desk").then((stored) => DeskRules.normalize(stored.desk));
}

function saveDesk(desk) {
  return chrome.storage.local.set({ desk });
}

function mountChip() {
  if (document.getElementById("playerok-desk-chip")) return;
  const chip = document.createElement("div");
  chip.id = "playerok-desk-chip";
  const title = document.createElement("strong");
  title.textContent = "FPH";
  const status = document.createElement("span");
  status.id = "playerok-desk-status";
  chip.append(title, status);
  document.documentElement.append(chip);
}

function setStatus(text) {
  const node = document.getElementById("playerok-desk-status");
  if (node) node.textContent = text;
}

async function runner(csrf, request) {
  const body = new URLSearchParams();
  body.set("objects", "[]");
  body.set("request", JSON.stringify(request));
  body.set("csrf_token", csrf);
  const response = await fetch("https://funpay.com/runner/", {
    method: "POST",
    credentials: "include",
    headers: {
      accept: "*/*",
      "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
      "x-requested-with": "XMLHttpRequest",
    },
    body,
  });
  const json = await response.json();
  if (!response.ok || json.error) throw new Error((json && json.msg) || "FunPay не принял сообщение");
  return json;
}

async function raiseGame(csrf, gameId) {
  const body = new URLSearchParams();
  const parts = String(gameId).split(":");
  body.set("game_id", parts[0]);
  body.set("node_id", parts[1] || parts[0]);
  body.set("node_ids[]", parts[1] || parts[0]);
  if (csrf) body.set("csrf_token", csrf);
  const response = await fetch("https://funpay.com/lots/raise", {
    method: "POST",
    credentials: "include",
    headers: {
      accept: "*/*",
      "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
      "x-requested-with": "XMLHttpRequest",
    },
    body,
  });
  return response.json();
}

async function tick() {
  if (busy) return;
  busy = true;
  try {
    const desk = await loadDesk();
    if (!desk.enabled || !desk.fph.enabled) {
      setStatus(desk.fph.enabled ? "выключен" : "FPH выключен");
      return;
    }
    const response = await fetch("https://funpay.com/orders/trade", { credentials: "include" });
    const html = await response.text();
    const page = DeskPlugins.parseFunpaySales(html);
    if (!page.userId) {
      setStatus("нет входа на FunPay");
      return;
    }
    for (const sale of page.sales) {
      if (sale.status !== "paid") continue;
      DeskPlugins.rememberBuyer(desk.state, sale.buyer, sale.id, sale.price, sale.status);
      const decision = DeskRules.decideDeal({
        deal: {
          id: sale.id,
          status: "PAID",
          direction: "OUT",
          hasProblem: false,
          isAutomated: false,
          user: { username: sale.buyer },
          chat: { id: sale.chatId },
          item: { id: sale.id, name: sale.description, price: sale.price, category: { name: "" } },
          obtainingFields: [],
        },
        rules: desk.rules,
        accounts: desk.accounts,
        state: desk.state,
        now: Date.now(),
        settings: Object.assign({}, desk, { market: "funpay" }),
      });
      if (decision.action === "rent") {
        if (DeskRules.shouldLogWait(desk.state, sale.id, "fph-rent", Date.now())) {
          DeskRules.addLog(desk.state, "FPH не сдаёт Steam, это остаётся на Playerok: " + sale.description, Date.now());
        }
        continue;
      }
      if (decision.action !== "deliver") continue;
      const line = decision.line || "";
      if (decision.rule.kind === "stock") DeskPlugins.consumeStock(desk, decision.rule);
      const text = DeskRules.deliveryText(decision.rule, {
        user: { username: sale.buyer },
        item: { name: sale.description },
        obtainingFields: [],
        commentFromBuyer: "",
      }, line);
      if (desk.practice) {
        DeskPlugins.restoreStock(desk, decision.rule, line);
        if (DeskRules.shouldLogWait(desk.state, sale.id, "fph-preview", Date.now())) {
          DeskRules.addLog(desk.state, "учебный FPH: выдал бы «" + sale.description + "»", Date.now());
        }
        continue;
      }
      try {
        await runner(page.csrf, { action: "chat_message", data: { node: sale.chatId, last_message: -1, content: text } });
        desk.state.processed[sale.id] = { status: "sent", at: Date.now() };
        DeskRules.addLog(desk.state, "FPH выдал «" + sale.description + "»", Date.now());
      } catch (error) {
        DeskPlugins.restoreStock(desk, decision.rule, line);
        desk.state.processed[sale.id] = { status: "failed", at: Date.now() };
        DeskRules.addLog(desk.state, "FPH не выдал: " + error.message, Date.now());
      }
    }
    if (DeskPlugins.hourAllows(desk.boostSlots, new Date()) && desk.fph.gameIds.length) {
      for (const gameId of desk.fph.gameIds) {
        const last = Number(desk.state.relistAt["fph:" + gameId] || 0);
        if (Date.now() - last < 10 * 60 * 1000) continue;
        desk.state.relistAt["fph:" + gameId] = Date.now();
        if (desk.practice) {
          DeskRules.addLog(desk.state, "учебный FPH: поднял бы игру " + gameId, Date.now());
          continue;
        }
        const raised = await raiseGame(page.csrf, gameId);
        DeskRules.addLog(desk.state, raised && raised.error ? "FPH поднятие " + gameId + ": " + (raised.msg || "отказ") : "FPH поднял игру " + gameId, Date.now());
      }
    }
    await saveDesk(desk);
    const last = desk.state.log[0];
    setStatus(last ? last.text : (desk.practice ? "учебный" : "включён"));
  } catch (error) {
    setStatus(error.message || "ошибка FPH");
  } finally {
    busy = false;
  }
}

mountChip();
loadDesk().then((desk) => {
  setStatus(desk.fph && desk.fph.enabled ? "FPH ждёт проход" : "FPH выключен");
  timer = setInterval(tick, Math.max(20, desk.pollSec) * 1000);
  if (desk.enabled && desk.fph.enabled) tick();
});
