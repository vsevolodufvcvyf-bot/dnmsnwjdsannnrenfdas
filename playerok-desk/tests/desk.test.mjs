import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const rules = require("../lib/rules.js");
const proxy = require("../lib/proxy.js");
require("../lib/guard.js");
require("../lib/rsa.js");
const steam = require("../lib/steam.js");

const now = Date.parse("2026-10-19T12:00:00Z");

function pkcs1Decrypt(privateKey, encrypted) {
  const raw = crypto.privateDecrypt(
    { key: privateKey, padding: crypto.constants.RSA_NO_PADDING },
    Buffer.from(encrypted, "base64")
  );
  assert.equal(raw[0], 0);
  assert.equal(raw[1], 2);
  const marker = raw.indexOf(0, 2);
  assert.ok(marker > 2);
  return raw.subarray(marker + 1).toString();
}

function deal(extra) {
  return Object.assign({
    id: "deal-1",
    status: "PAID",
    direction: "OUT",
    hasProblem: false,
    isAutomated: false,
    commentFromBuyer: "",
    user: { username: "buyer" },
    chat: { id: "chat-1" },
    item: { id: "item-1", name: "Аренда CS2 [rent: 3h]", price: 100, category: { name: "Аккаунты" } },
    obtainingFields: [],
  }, extra);
}

function account(extra) {
  return rules.normalize({
    accounts: [Object.assign({
      id: "acc-1",
      login: "steam_user",
      password: "OldPass123",
      sharedSecret: "cnOgv/KdpLoP6Nbh0GMkXkPXALQ=",
      identitySecret: "AAAAAAAAAAAAAAAAAAAAAA==",
      keywords: "cs2",
      itemIds: [],
    }, extra)],
  }).accounts[0];
}

test("steam guard code matches the known vector", async () => {
  const code = await DeskGuard.generateGuardCode("cnOgv/KdpLoP6Nbh0GMkXkPXALQ=", 1469184209);
  assert.equal(code, "87JP8");
});

test("confirmation key matches the known vector", async () => {
  const key = await DeskGuard.confirmationKey("AAAAAAAAAAAAAAAAAAAAAA==", "conf", 1600000000);
  assert.equal(key, "/Wlhe4F1OkCpalik7tz4NJLkPu8=");
});

test("rsa pkcs1 ciphertext decrypts with the matching private key", () => {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = publicKey.export({ format: "jwk" });
  const mod = Buffer.from(jwk.n, "base64url").toString("hex");
  const exp = Buffer.from(jwk.e, "base64url").toString("hex");
  const encrypted = DeskRsa.encrypt("NewPass123", mod, exp);
  assert.equal(pkcs1Decrypt(privateKey, encrypted), "NewPass123");
});

test("duration comes from a rent tag, not from hours played", () => {
  assert.equal(rules.parseRentDuration("Аренда CS2 [rent: 3h]", 1, 336).seconds, 10800);
  assert.equal(rules.parseRentDuration("аренда на 3 часа", 1, 336).seconds, 10800);
  assert.equal(rules.parseRentDuration("2500 часов в игре", 1, 336).seconds, null);
  assert.equal(rules.parseRentDuration("на 400 часов", 1, 336).seconds, null);
});

test("item id beats a keyword, and the longer keyword wins", () => {
  const idRule = { id: "id", active: true, kind: "stock", itemIds: ["item-1"], keywords: "" };
  const shortRule = { id: "short", active: true, kind: "text", itemIds: [], keywords: "cs2" };
  const longRule = { id: "long", active: true, kind: "text", itemIds: [], keywords: "cs2 prime" };
  assert.equal(rules.matchRule([shortRule, idRule], deal()).id, "id");
  assert.equal(rules.matchRule([shortRule, longRule], deal({ item: { id: "x", name: "CS2 Prime аккаунт", category: { name: "" } } })).id, "long");
});

test("paid deal decisions", () => {
  const rentRule = { id: "rent", active: true, kind: "rent", itemIds: ["item-1"], keywords: "", template: "", stock: [] };
  const stockRule = { id: "stock", active: true, kind: "stock", itemIds: ["item-1"], keywords: "", template: "{product}", stock: ["KEY-1", "KEY-2"] };
  const settings = rules.defaultDesk();
  const rented = rules.decideDeal({
    deal: deal(),
    rules: [rentRule],
    accounts: [account()],
    state: { processed: {} },
    now,
    settings,
  });
  assert.equal(rented.action, "rent");
  assert.equal(rented.durationSec, 10800);

  const social = rules.decideDeal({
    deal: deal({ item: { id: "item-1", name: "Аккаунт Instagram [rent: 1h]", price: 1, category: { name: "" } } }),
    rules: [rentRule],
    accounts: [account()],
    state: { processed: {} },
    now,
    settings,
  });
  assert.equal(social.action, "park");

  const auto = rules.decideDeal({
    deal: deal({ isAutomated: true }),
    rules: [stockRule],
    accounts: [],
    state: { processed: {} },
    now,
    settings,
  });
  assert.equal(auto.action, "park");

  const empty = rules.decideDeal({
    deal: deal({ item: { id: "item-1", name: "Ключ", price: 1, category: { name: "" } } }),
    rules: [{ ...stockRule, stock: [] }],
    accounts: [],
    state: { processed: {} },
    now,
    settings,
  });
  assert.equal(empty.action, "wait");

  const first = rules.decideDeal({
    deal: deal({ item: { id: "item-1", name: "Ключ", price: 1, category: { name: "" } } }),
    rules: [stockRule],
    accounts: [],
    state: { processed: {} },
    now,
    settings,
  });
  assert.equal(first.action, "deliver");
  assert.equal(first.line, "KEY-1");
  const taken = rules.takeStock(stockRule);
  assert.deepEqual(taken.stock, ["KEY-2"]);
  assert.deepEqual(rules.returnStock(taken, "KEY-1").stock, ["KEY-1", "KEY-2"]);

  const again = rules.decideDeal({
    deal: deal(),
    rules: [rentRule],
    accounts: [account()],
    state: { processed: { "deal-1": { status: "sent", at: now } } },
    now: now + 1000,
    settings,
  });
  assert.equal(again.action, "skip");
});

test("guard request is a short buyer message", () => {
  assert.equal(rules.guardRequest("код"), true);
  assert.equal(rules.guardRequest("где код"), true);
  assert.equal(rules.guardRequest("encode"), false);
  assert.equal(rules.guardRequest("можно код ещё раз пожалуйста прямо сейчас"), false);
});

test("rent message has the login and not the mafile secret", () => {
  const text = rules.rentMessage({
    lot: "CS2",
    login: "steam_user",
    password: "OldPass123",
    guard: "87JP8",
    duration: "3 ч.",
    until: "15:00",
    note: "",
  });
  assert.match(text, /steam_user/);
  assert.match(text, /OldPass123/);
  assert.equal(text.includes("cnOgv"), false);
  assert.equal(text.includes("отзыв"), false);
});

test("relist stays on the free status unless boost is explicitly paid", () => {
  const free = rules.pickPriority([{ id: "free", price: 0 }, { id: "pro", price: 19 }], false, 25);
  assert.equal(free.status.id, "free");
  const blocked = rules.pickPriority([{ id: "pro", price: 19 }], false, 25);
  assert.equal(blocked.status, null);
  const paid = rules.pickPriority([{ id: "pro", price: 19 }, { id: "max", price: 49 }], true, 25);
  assert.equal(paid.status.id, "pro");
  const busy = account({ busy: true, itemIds: ["item-9"] });
  assert.equal(rules.canRelistItem({ id: "item-9", status: "SOLD" }, [busy], now), false);
  assert.equal(rules.relistAllowed(
    { id: "item-9", status: "SOLD", name: "Ключ" },
    { relistSold: false, rules: [{ id: "s", active: true, kind: "stock", relist: true, itemIds: ["item-9"], keywords: "", stock: [] }], accounts: [] },
    now
  ), false);
});

test("mafile keeps secrets and drops the steam session blob", () => {
  const parsed = rules.parseMafile(JSON.stringify({
    account_name: "steam_user",
    shared_secret: "abc",
    identity_secret: "def",
    Session: { SteamID: 765, RefreshToken: "should-not-matter" },
  }));
  assert.equal(parsed.login, "steam_user");
  assert.equal(parsed.steamid, "765");
  assert.equal(JSON.stringify(parsed).includes("RefreshToken"), false);
});

test("password change confirms only the matching steam recovery and encrypts the new password", async () => {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = publicKey.export({ format: "jwk" });
  const mod = Buffer.from(jwk.n, "base64url").toString("hex");
  const exp = Buffer.from(jwk.e, "base64url").toString("hex");
  const calls = [];
  const headers = { getSetCookie: () => [] };
  const http = async (request) => {
    calls.push(request);
    const url = request.url;
    const base = { status: 200, headers, text: "", json: { success: true }, url };
    if (url.includes("GetPasswordRSAPublicKey") || url.includes("getrsakey")) {
      return { ...base, json: { response: { publickey_mod: mod, publickey_exp: exp, timestamp: "5" }, publickey_mod: mod, publickey_exp: exp, timestamp: "5" } };
    }
    if (url.includes("BeginAuthSessionViaCredentials")) {
      return { ...base, json: { response: { client_id: "7", request_id: "req", steamid: "76561198000000000", allowed_confirmations: [{ confirmation_type: 3 }] } } };
    }
    if (url.includes("PollAuthSessionStatus")) {
      return { ...base, json: { response: { access_token: "access", refresh_token: "refresh" } } };
    }
    if (url.includes("finalizelogin")) return { ...base, json: { steamID: "76561198000000000", transfer_info: [] } };
    if (url.includes("HelpChangePassword")) {
      return { ...base, url: "https://help.steampowered.com/en/wizard/HelpWithLoginInfoEnterCode?s=555&account=9&reset=1&lost=0&issueid=406" };
    }
    if (url.includes("mobileconf/getlist")) {
      return { ...base, json: { success: true, conf: [{ id: "bad", nonce: "1", creator_id: "999" }, { id: "good", nonce: "2", creator_id: "555" }] } };
    }
    if (url.includes("AjaxCheckPasswordAvailable")) return { ...base, json: { available: true } };
    return base;
  };
  const owned = account();
  await steam.changeOwnedPassword(owned, "NewPass123", http, { sleep: async () => {} });
  const urls = calls.map((call) => call.url);
  assert.equal(urls.some((url) => url.includes("createItem") || url.includes("removeItem")), false);
  const allow = calls.find((call) => call.url.includes("ajaxop"));
  assert.equal(allow.form.cid, "good");
  assert.equal(allow.form.op, "allow");
  const verify = calls.find((call) => call.url.includes("AjaxAccountRecoveryVerifyPassword"));
  const changed = calls.find((call) => call.url.includes("AjaxAccountRecoveryChangePassword"));
  const decrypt = (value) => pkcs1Decrypt(privateKey, value);
  assert.equal(decrypt(verify.form.password), "OldPass123");
  assert.equal(decrypt(changed.form.password), "NewPass123");
});

test("steam proxy is assembled only after host and port are known", () => {
  const described = proxy.describe("http://user:p%40ss@127.0.0.1:9050");
  assert.equal(described.enabled, true);
  assert.match(described.pac, /PROXY 127\.0\.0\.1:9050/);
  assert.equal(described.user, "user");
  assert.equal(described.pass, "p@ss");
  assert.match(proxy.describe("socks5://10.0.0.2:1080").pac, /SOCKS5 10\.0\.0\.2:1080/);
  assert.equal(proxy.describe("").enabled, false);
  assert.match(proxy.describe("http://bad host").error, /прокси/);
});

test("shared warehouse, review reply and funpay order parse", () => {
  const desk = rules.defaultDesk();
  desk.market = "playerok";
  desk.warehouses = [{ id: "w", title: "ключи", stock: ["A", "B"] }];
  const rule = { id: "r", active: true, kind: "stock", itemIds: ["item-1"], warehouseId: "w", stock: [], market: "playerok", keywords: "", template: "{product}" };
  const decision = rules.decideDeal({
    deal: deal({ item: { id: "item-1", name: "Ключ", price: 10, category: { name: "" } } }),
    rules: [rule, { id: "fp", active: true, kind: "stock", itemIds: ["item-1"], keywords: "", stock: ["X"], market: "funpay" }],
    accounts: [],
    state: { processed: {} },
    now,
    settings: desk,
  });
  assert.equal(decision.rule.id, "r");
  assert.equal(decision.line, "A");
  const plugins = require("../lib/plugins.js");
  assert.equal(plugins.consumeStock({ warehouses: desk.warehouses, rules: [rule] }, rule), "A");
  assert.deepEqual(desk.warehouses[0].stock, ["B"]);
  plugins.restoreStock({ warehouses: desk.warehouses, rules: [rule] }, rule, "A");
  assert.deepEqual(desk.warehouses[0].stock, ["A", "B"]);
  assert.equal(plugins.replyForRating({ enabled: true, stars: { "5": "бонус за пятёрку" } }, 5), "");
  assert.equal(plugins.replyForRating({ enabled: true, stars: { "5": "Спасибо за заказ." } }, 5), "Спасибо за заказ.");
  const plan = plugins.planReminder({ confirmedAt: now, sent: 0 }, { enabled: true, firstDelayMin: 60, intervalMin: 1440, times: 2 }, now + 61 * 60000, false);
  assert.equal(plan.send, true);
  assert.equal(plugins.hourAllows(["0:14"], new Date("2026-10-19T14:30:00")), true);
  const page = plugins.parseFunpaySales(`<body data-app-data="{&quot;csrf-token&quot;:&quot;tok&quot;,&quot;userId&quot;:10}"><a class="tc-item info" href="https://funpay.com/orders/ABCD/"><div class="tc-order">#ABCD</div><div class="order-desc"><div>Ключ CS2</div></div><div class="tc-price">150 ₽</div><div class="media-user-name"><span data-href="https://funpay.com/users/20/">buyer</span></div></a></body>`);
  assert.equal(page.csrf, "tok");
  assert.equal(page.sales.length, 1);
  assert.equal(page.sales[0].status, "paid");
  assert.equal(page.sales[0].id, "ABCD");
  assert.equal(page.sales[0].buyer, "buyer");
  assert.equal(page.sales[0].chatId, "users-10-20");
  assert.equal(page.sales[0].price, 150);
});

test("extension does not create or delete playerok items", () => {
  const files = ["content.js", "background.js", "lib/queries.js", "options.js"];
  const source = files.map((file) => fs.readFileSync(new URL("../" + file, import.meta.url), "utf8")).join("\n");
  assert.equal(source.includes("createItem"), false);
  assert.equal(source.includes("removeItem"), false);
});
