importScripts("lib/guard.js", "lib/rsa.js", "lib/rules.js", "lib/steam.js", "lib/proxy.js");

const proxyAuth = { user: "", pass: "" };
let appliedProxy = null;

function loadDesk() {
  return chrome.storage.local.get("desk").then((stored) => DeskRules.normalize(stored.desk));
}

function saveDesk(desk) {
  return chrome.storage.local.set({ desk });
}

function applyProxy(proxyUrl) {
  const next = String(proxyUrl || "").trim();
  if (next === appliedProxy) return;
  const described = DeskProxy.describe(next);
  if (next && !described.enabled) {
    console.warn(described.error || "прокси не применён");
    return;
  }
  appliedProxy = next;
  proxyAuth.user = described.user || "";
  proxyAuth.pass = described.pass || "";
  const value = described.enabled
    ? { mode: "pac_script", pacScript: { data: described.pac } }
    : { mode: "system" };
  try {
    const pending = chrome.proxy.settings.set({ value, scope: "regular" });
    if (pending && typeof pending.catch === "function") pending.catch((error) => console.warn(error));
  } catch (error) {
    console.warn(error);
  }
}

try {
  chrome.webRequest.onAuthRequired.addListener(
    (details, callback) => {
      if (!details.isProxy || !proxyAuth.user) {
        callback({});
        return;
      }
      callback({ authCredentials: { username: proxyAuth.user, password: proxyAuth.pass } });
    },
    { urls: ["https://*.steampowered.com/*", "https://*.steamcommunity.com/*", "https://steamcommunity.com/*"] },
    ["asyncBlocking"]
  );
} catch (error) {
  console.warn("proxy auth", error);
}

async function syncSteamTime() {
  try {
    const response = await fetch("https://api.steampowered.com/ITwoFactorService/QueryTime/v0001/", { method: "POST" });
    const data = await response.json();
    const server = Number(data && data.response && data.response.server_time);
    if (!server) return;
    await chrome.storage.local.set({ steamOffset: server - Math.floor(Date.now() / 1000) });
  } catch (error) {
    /* время Steam необязательно, код живёт 30 секунд */
  }
}

async function rotate(accountId) {
  const desk = await loadDesk();
  const account = desk.accounts.find((item) => item.id === accountId);
  if (!account) return { ok: false, error: "аккаунт не найден" };
  const next = DeskRules.generatePassword();
  try {
    const result = await DeskSteam.changeOwnedPassword(account, next, extensionHttp, { sleep });
    account.password = next;
    account.needsReset = false;
    if (result.steamid) account.steamid = String(result.steamid);
    await saveDesk(desk);
    return { ok: true, login: account.login };
  } catch (error) {
    account.needsReset = true;
    await saveDesk(desk);
    return { ok: false, error: error.message || "смена пароля не удалась" };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function extensionHttp(request) {
  const url = new URL(request.url);
  if (request.query) {
    for (const [key, value] of Object.entries(request.query)) {
      if (value != null) url.searchParams.set(key, String(value));
    }
  }
  const headers = Object.assign({
    accept: "*/*",
    "user-agent": navigator.userAgent,
  }, request.headers || {});
  const cookie = DeskSteam.cookieHeader(request.jar, url.href);
  if (cookie) headers.cookie = cookie;
  let body;
  if (request.form) {
    headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8";
    body = new URLSearchParams(Object.entries(request.form).map(([key, value]) => [key, value == null ? "" : String(value)])).toString();
  }
  const response = await fetch(url, { method: request.method || "GET", headers, body, redirect: "follow" });
  const text = await response.text();
  let json = null;
  try { json = JSON.parse(text); } catch (error) { json = null; }
  DeskSteam.absorbCookies(request.jar, url.hostname, response);
  return { url: response.url, status: response.status, text, json, headers: response.headers };
}

async function guardCode(accountId) {
  const desk = await loadDesk();
  const account = desk.accounts.find((item) => item.id === accountId);
  if (!account || !account.sharedSecret) return { ok: false, error: "нет shared_secret" };
  const stored = await chrome.storage.local.get("steamOffset");
  const now = Math.floor(Date.now() / 1000) + Number(stored.steamOffset || 0);
  const code = await DeskGuard.generateGuardCode(account.sharedSecret, now);
  return { ok: true, code, login: account.login };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const run = async () => {
    if (!message || !message.type) return { ok: false };
    if (message.type === "open-options") {
      chrome.runtime.openOptionsPage();
      return { ok: true };
    }
    if (message.type === "rotate") return rotate(message.accountId);
    if (message.type === "guard-code") return guardCode(message.accountId);
    if (message.type === "proxy") {
      applyProxy(message.proxy || "");
      return { ok: true };
    }
    return { ok: false, error: "неизвестная команда" };
  };
  run().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("desk-steam", { periodInMinutes: 30 });
  loadDesk().then((desk) => applyProxy(desk.proxy));
  syncSteamTime();
});

chrome.runtime.onStartup.addListener(() => {
  loadDesk().then((desk) => applyProxy(desk.proxy));
  syncSteamTime();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "desk-steam") syncSteamTime();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.desk) applyProxy(DeskRules.normalize(changes.desk.newValue).proxy);
});

loadDesk().then((desk) => applyProxy(desk.proxy));
syncSteamTime();
