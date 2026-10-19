let desk = DeskRules.defaultDesk();

const fields = ["enabled", "practice", "markSent", "relistSold", "boostEnabled"];

function load() {
  return chrome.storage.local.get("desk").then((stored) => {
    desk = DeskRules.normalize(stored.desk);
    paint();
  });
}

function readCommon() {
  for (const name of fields) desk[name] = document.getElementById(name).checked;
  desk.pollSec = Number(document.getElementById("pollSec").value);
  desk.proxy = document.getElementById("proxy").value.trim();
  desk.maxGuardCodes = Number(document.getElementById("maxGuardCodes").value);
  desk.maxRentHours = Number(document.getElementById("maxRentHours").value);
  desk.boostMaxPrice = Number(document.getElementById("boostMaxPrice").value);
  desk.boostDailyCap = Number(document.getElementById("boostDailyCap").value);
  desk.boostAfterPosition = Number(document.getElementById("boostAfterPosition").value);
}

function paint() {
  for (const name of fields) document.getElementById(name).checked = Boolean(desk[name]);
  document.getElementById("pollSec").value = desk.pollSec;
  document.getElementById("proxy").value = desk.proxy;
  document.getElementById("maxGuardCodes").value = desk.maxGuardCodes;
  document.getElementById("maxRentHours").value = desk.maxRentHours;
  document.getElementById("boostMaxPrice").value = desk.boostMaxPrice;
  document.getElementById("boostDailyCap").value = desk.boostDailyCap;
  document.getElementById("boostAfterPosition").value = desk.boostAfterPosition;
  paintRules();
  paintAccounts();
  paintLog();
}

function paintRules() {
  const root = document.getElementById("rules");
  root.replaceChildren();
  if (!desk.rules.length) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "Правил нет, ничего само не уйдёт покупателю.";
    root.append(empty);
  }
  desk.rules.forEach((rule, index) => root.append(ruleCard(rule, index)));
}

function ruleCard(rule, index) {
  const box = document.createElement("div");
  box.className = "rule";
  box.append(
    labeled("Название", input("title", rule.title, (value) => { rule.title = value; })),
    labeled("Тип", select([["stock", "Склад, одна строка одному покупателю"], ["text", "Один и тот же текст"], ["rent", "Аренда Steam"]], rule.kind, (value) => { rule.kind = value; })),
    labeled("ID товаров через запятую", input("items", (rule.itemIds || []).join(", "), (value) => { rule.itemIds = DeskRules.splitList(value); })),
    labeled("Слова в названии, если ID нет", input("words", rule.keywords, (value) => { rule.keywords = value; })),
    labeled("Сообщение. Для склада: {product} {name} {lot} {fields} {comment}", area(rule.template, (value) => { rule.template = value; })),
    labeled("Склад, одна выдача на строку", area((rule.stock || []).join("\n"), (value) => { rule.stock = DeskRules.splitLines(value); }))
  );
  const active = check("Правило включено", rule.active !== false, (value) => { rule.active = value; });
  const relist = check("Перевыставлять этот лот после продажи, если склад не пуст", Boolean(rule.relist), (value) => { rule.relist = value; });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "quiet";
  remove.textContent = "Удалить правило";
  remove.addEventListener("click", () => {
    desk.rules.splice(index, 1);
    paintRules();
  });
  box.append(active, relist, remove);
  return box;
}

function paintAccounts() {
  const root = document.getElementById("accounts");
  root.replaceChildren();
  if (!desk.accounts.length) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "Аккаунтов нет.";
    root.append(empty);
  }
  desk.accounts.forEach((account, index) => root.append(accountCard(account, index)));
}

function accountCard(account, index) {
  const box = document.createElement("div");
  box.className = "account";
  const state = account.needsReset ? "ждёт смены пароля" : account.busy ? "в аренде" : "свободен";
  const secrets = (account.sharedSecret ? "Guard есть" : "нет Guard") + ", " + (account.identitySecret ? "подтверждение есть" : "нет identity_secret");
  const meta = document.createElement("p");
  meta.className = "note";
  meta.textContent = state + " · " + secrets;
  box.append(
    labeled("Логин", input("login", account.login, (value) => { account.login = value; })),
    labeled("Пароль", input("password", account.password, (value) => { account.password = value; }, "password")),
    labeled("Слова лота", input("words", account.keywords, (value) => { account.keywords = value; })),
    labeled("ID лотов", input("items", (account.itemIds || []).join(", "), (value) => { account.itemIds = DeskRules.splitList(value); })),
    meta
  );
  const code = document.createElement("button");
  code.type = "button";
  code.className = "quiet";
  code.textContent = "Показать код";
  code.addEventListener("click", async () => {
    readCommon();
    await chrome.storage.local.set({ desk });
    const result = await chrome.runtime.sendMessage({ type: "guard-code", accountId: account.id });
    meta.textContent = result && result.ok ? "код " + result.code + " · обновится через 30 сек" : (result && result.error) || "код не вышел";
  });
  const rotate = document.createElement("button");
  rotate.type = "button";
  rotate.className = "quiet";
  rotate.textContent = "Сменить пароль";
  rotate.addEventListener("click", async () => {
    readCommon();
    await chrome.storage.local.set({ desk });
    meta.textContent = "вхожу в Steam…";
    const result = await chrome.runtime.sendMessage({ type: "rotate", accountId: account.id });
    if (!result || !result.ok) {
      meta.textContent = (result && result.error) || "не сменился";
      return;
    }
    await load();
  });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "quiet";
  remove.textContent = "Удалить";
  remove.addEventListener("click", () => {
    desk.accounts.splice(index, 1);
    paintAccounts();
  });
  box.append(code, rotate, remove);
  return box;
}

function paintLog() {
  const root = document.getElementById("log");
  root.replaceChildren();
  for (const row of desk.state.log) {
    const item = document.createElement("li");
    const time = new Date(row.at).toLocaleString("ru-RU");
    item.textContent = time + " — " + row.text;
    root.append(item);
  }
  if (!desk.state.log.length) {
    const item = document.createElement("li");
    item.textContent = "Пока пусто.";
    root.append(item);
  }
}

function labeled(title, control) {
  const label = document.createElement("label");
  label.append(document.createTextNode(title), control);
  return label;
}

function input(name, value, onInput, type) {
  const field = document.createElement("input");
  field.type = type || "text";
  field.value = value || "";
  field.autocomplete = "off";
  field.addEventListener("input", () => onInput(field.value));
  return field;
}

function area(value, onInput) {
  const field = document.createElement("textarea");
  field.value = value || "";
  field.addEventListener("input", () => onInput(field.value));
  return field;
}

function select(options, value, onChange) {
  const field = document.createElement("select");
  for (const [id, title] of options) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = title;
    field.append(option);
  }
  field.value = value;
  field.addEventListener("change", () => onChange(field.value));
  return field;
}

function check(title, value, onChange) {
  const label = document.createElement("label");
  label.className = "check";
  const field = document.createElement("input");
  field.type = "checkbox";
  field.checked = Boolean(value);
  field.addEventListener("change", () => onChange(field.checked));
  label.append(field, document.createTextNode(title));
  return label;
}

document.getElementById("save").addEventListener("click", async () => {
  readCommon();
  await chrome.storage.local.set({ desk });
  const button = document.getElementById("save");
  button.textContent = "Сохранено";
  setTimeout(() => { button.textContent = "Сохранить"; }, 1200);
});

document.getElementById("addRule").addEventListener("click", () => {
  readCommon();
  desk.rules.push(DeskRules.normalize({ rules: [{ kind: "stock", active: true }] }).rules[0]);
  paintRules();
});

document.getElementById("mafile").addEventListener("change", async (event) => {
  readCommon();
  for (const file of event.target.files || []) {
    try {
      const parsed = DeskRules.parseMafile(await file.text());
      const existing = desk.accounts.find((account) => account.login && account.login === parsed.login);
      if (existing) {
        existing.sharedSecret = parsed.sharedSecret;
        existing.identitySecret = parsed.identitySecret || existing.identitySecret;
        existing.steamid = parsed.steamid || existing.steamid;
      } else {
        desk.accounts.push(DeskRules.normalize({ accounts: [parsed] }).accounts[0]);
      }
    } catch (error) {
      DeskRules.addLog(desk.state, file.name + ": " + error.message, Date.now());
    }
  }
  event.target.value = "";
  paint();
});

load();
