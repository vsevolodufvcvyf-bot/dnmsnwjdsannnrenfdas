(function (root, factory) {
  const api = factory();
  root.DeskSteam = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function guardApi() {
    return typeof DeskGuard !== "undefined" ? DeskGuard : null;
  }

  function rsaApi() {
    return typeof DeskRsa !== "undefined" ? DeskRsa : null;
  }

  function need(name, value) {
    if (!value) throw new Error("нет модуля " + name);
    return value;
  }

  function cookieHeader(jar, url) {
    const host = new URL(url).hostname;
    const bits = [];
    for (const [domain, cookies] of Object.entries(jar || {})) {
      if (host === domain || host.endsWith("." + domain)) {
        for (const [name, value] of Object.entries(cookies)) bits.push(name + "=" + value);
      }
    }
    return bits.join("; ");
  }

  function setCookie(jar, domain, name, value) {
    jar[domain] = jar[domain] || {};
    jar[domain][name] = value;
  }

  function absorbCookies(jar, host, response) {
    if (!response || !response.headers || typeof response.headers.getSetCookie !== "function") return;
    for (const line of response.headers.getSetCookie()) {
      const pair = String(line).split(";")[0];
      const cut = pair.indexOf("=");
      if (cut < 1) continue;
      const domainMatch = /domain=([^;]+)/i.exec(line);
      const domain = (domainMatch ? domainMatch[1] : host).replace(/^\./, "").trim();
      setCookie(jar, domain, pair.slice(0, cut).trim(), pair.slice(cut + 1).trim());
    }
  }

  function randomId() {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function steamError(json, fallback) {
    const response = json && json.response;
    const message = (json && (json.errorMsg || json.message))
      || (response && (response.extended_error_message || response.error))
      || fallback;
    const error = new Error(message || fallback || "Steam не ответил");
    error.payload = json || null;
    return error;
  }

  async function login(account, http, jar, sleep) {
    const guard = need("guard", guardApi());
    const rsa = need("rsa", rsaApi());
    const rsaRes = await http({
      method: "GET",
      url: "https://api.steampowered.com/IAuthenticationService/GetPasswordRSAPublicKey/v1/",
      query: { account_name: account.login },
      jar,
    });
    const key = rsaRes.json && rsaRes.json.response;
    if (!key || !key.publickey_mod) throw steamError(rsaRes.json, "Steam не отдал RSA-ключ");
    const encrypted = rsa.encrypt(account.password, key.publickey_mod, key.publickey_exp);
    const begin = await http({
      method: "POST",
      url: "https://api.steampowered.com/IAuthenticationService/BeginAuthSessionViaCredentials/v1/",
      form: {
        account_name: account.login,
        encrypted_password: encrypted,
        encryption_timestamp: key.timestamp,
        remember_login: "true",
        platform_type: "2",
        persistence: "1",
        website_id: "Community",
        device_friendly_name: "Playerok Desk",
      },
      jar,
    });
    const session = begin.json && begin.json.response;
    if (!session || !session.client_id) throw steamError(begin.json, "Steam не открыл вход");
    const confirmations = session.allowed_confirmations || [];
    const needsGuard = confirmations.some((item) => Number(item.confirmation_type) === 3);
    const needsEmail = confirmations.some((item) => Number(item.confirmation_type) === 2) && !needsGuard;
    if (needsEmail) throw new Error("Steam просит код с почты, а в maFile его нет");
    if (needsGuard) {
      const code = await guard.generateGuardCode(account.sharedSecret, Math.floor(Date.now() / 1000));
      const updated = await http({
        method: "POST",
        url: "https://api.steampowered.com/IAuthenticationService/UpdateAuthSessionWithSteamGuardCode/v1/",
        form: {
          client_id: session.client_id,
          steamid: session.steamid,
          code,
          code_type: "3",
        },
        jar,
      });
      if (updated.status >= 400) throw steamError(updated.json, "Steam не принял код Guard");
    }
    let tokens = null;
    for (let attempt = 0; attempt < 8; attempt++) {
      const poll = await http({
        method: "POST",
        url: "https://api.steampowered.com/IAuthenticationService/PollAuthSessionStatus/v1/",
        form: { client_id: session.client_id, request_id: session.request_id },
        jar,
      });
      const response = poll.json && poll.json.response;
      if (response && response.access_token && response.refresh_token) {
        tokens = response;
        break;
      }
      await sleep(400);
    }
    if (!tokens) throw new Error("Steam не выдал токен входа");
    const steamid = String(session.steamid || account.steamid || "");
    const sessionid = randomId();
    const secure = steamid + "%7C%7C" + tokens.access_token;
    for (const domain of ["steamcommunity.com", "help.steampowered.com", "store.steampowered.com", "steampowered.com"]) {
      setCookie(jar, domain, "sessionid", sessionid);
      setCookie(jar, domain, "steamLoginSecure", secure);
    }
    const finalized = await http({
      method: "POST",
      url: "https://login.steampowered.com/jwt/finalizelogin",
      form: {
        nonce: tokens.refresh_token,
        sessionid,
        redir: "https://help.steampowered.com/en/wizard/HelpChangePassword?redir=store/account/",
      },
      jar,
    });
    const transfers = (finalized.json && finalized.json.transfer_info) || [];
    for (const transfer of transfers) {
      await http({
        method: "POST",
        url: transfer.url,
        form: {
          nonce: transfer.params && transfer.params.nonce,
          auth: transfer.params && transfer.params.auth,
          steamID: finalized.json.steamID || steamid,
        },
        jar,
      });
    }
    return { steamid, sessionid, accessToken: tokens.access_token };
  }

  async function openWizard(http, jar) {
    const response = await http({
      method: "GET",
      url: "https://help.steampowered.com/wizard/HelpChangePassword",
      query: { redir: "store/account/" },
      headers: { referer: "https://store.steampowered.com/" },
      jar,
    });
    const url = new URL(response.url || "https://help.steampowered.com/");
    const params = {
      s: url.searchParams.get("s"),
      account: url.searchParams.get("account"),
      reset: url.searchParams.get("reset"),
      lost: url.searchParams.get("lost") || "0",
      issueid: url.searchParams.get("issueid"),
    };
    if (!params.s || !params.account || !params.issueid) {
      throw new Error("Steam не открыл смену пароля. Проверьте логин и что maFile от этого аккаунта.");
    }
    return params;
  }

  async function form(http, jar, url, data, extra) {
    const response = await http({
      method: "POST",
      url,
      form: data,
      jar,
      headers: Object.assign({
        origin: "https://help.steampowered.com",
        "x-requested-with": "XMLHttpRequest",
      }, extra || {}),
    });
    if (response.json && response.json.errorMsg) throw new Error(response.json.errorMsg);
    return response;
  }

  async function confirmRecovery(account, steam, creatorId, http, jar, sleep) {
    const guard = need("guard", guardApi());
    const device = await guard.deviceId(steam.steamid);
    for (let attempt = 0; attempt < 4; attempt++) {
      const timestamp = Math.floor(Date.now() / 1000);
      const list = await http({
        method: "GET",
        url: "https://steamcommunity.com/mobileconf/getlist",
        query: {
          p: device,
          a: steam.steamid,
          k: await guard.confirmationKey(account.identitySecret, "conf", timestamp),
          t: timestamp,
          m: "android",
          tag: "conf",
        },
        headers: { referer: "https://steamcommunity.com/mobileconf" },
        jar,
      });
      const confs = (list.json && (list.json.conf || list.json.confirmations)) || [];
      const match = confs.find((conf) => String(conf.creator_id || conf.creator) === String(creatorId));
      if (match) {
        const allowTime = Math.floor(Date.now() / 1000);
        const allow = await http({
          method: "POST",
          url: "https://steamcommunity.com/mobileconf/ajaxop",
          form: {
            op: "allow",
            cid: match.id,
            ck: match.nonce || match.key || match.ck,
            p: device,
            a: steam.steamid,
            k: await guard.confirmationKey(account.identitySecret, "allow", allowTime),
            t: allowTime,
            m: "android",
            tag: "allow",
          },
          headers: { origin: "https://steamcommunity.com", referer: "https://steamcommunity.com/mobileconf" },
          jar,
        });
        if (allow.json && allow.json.success) return;
        throw new Error("Steam не принял подтверждение смены пароля");
      }
      await sleep(300);
    }
    throw new Error("нет подтверждения смены пароля в Guard. Другие подтверждения не трогаю");
  }

  async function changeOwnedPassword(account, newPassword, http, options) {
    const sleep = (options && options.sleep) || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    if (!account.identitySecret) throw new Error("в maFile нет identity_secret, пароль сам не сменю");
    if (!account.sharedSecret) throw new Error("в maFile нет shared_secret");
    if (!account.login || !account.password) throw new Error("нет логина или текущего пароля");
    if (!newPassword) throw new Error("пустой новый пароль");
    if (newPassword === account.password) throw new Error("новый пароль совпадает со старым");
    const jar = {};
    const steam = await login(account, http, jar, sleep);
    const params = await openWizard(http, jar);
    const sessionid = (jar["help.steampowered.com"] && jar["help.steampowered.com"].sessionid) || steam.sessionid;
    await http({
      method: "GET",
      url: "https://help.steampowered.com/en/wizard/HelpWithLoginInfoEnterCode",
      query: Object.assign({}, params, { sessionid, wizard_ajax: 1, gamepad: 0 }),
      jar,
    });
    await form(http, jar, "https://help.steampowered.com/en/wizard/AjaxSendAccountRecoveryCode", {
      sessionid,
      wizard_ajax: "1",
      gamepad: "0",
      s: params.s,
      method: "8",
      link: "",
      n: "1",
    });
    await confirmRecovery(account, steam, params.s, http, jar, sleep);
    let polled = null;
    for (let attempt = 0; attempt < 5; attempt++) {
      polled = await form(http, jar, "https://help.steampowered.com/en/wizard/AjaxPollAccountRecoveryConfirmation", {
        sessionid,
        wizard_ajax: 1,
        s: params.s,
        reset: params.reset,
        lost: params.lost,
        method: 8,
        issueid: params.issueid,
        gamepad: 0,
      });
      if (polled.json && polled.json.success) break;
      await sleep(300);
    }
    await http({
      method: "GET",
      url: "https://help.steampowered.com/en/wizard/AjaxVerifyAccountRecoveryCode",
      query: {
        code: "",
        s: params.s,
        reset: params.reset,
        lost: params.lost,
        method: 8,
        issueid: params.issueid,
        sessionid,
        wizard_ajax: 1,
        gamepad: 0,
      },
      jar,
    });
    await form(http, jar, "https://help.steampowered.com/en/wizard/AjaxAccountRecoveryGetNextStep", {
      sessionid,
      wizard_ajax: 1,
      s: params.s,
      account: params.account,
      reset: params.reset,
      issueid: params.issueid,
      lost: 2,
    });
    const rsa = need("rsa", rsaApi());
    async function rsaKey() {
      const response = await form(http, jar, "https://help.steampowered.com/en/login/getrsakey/", {
        sessionid,
        username: account.login,
      });
      const body = response.json || {};
      if (!body.publickey_mod) throw steamError(body, "Steam не отдал ключ для пароля");
      return body;
    }
    const oldKey = await rsaKey();
    await form(http, jar, "https://help.steampowered.com/en/wizard/AjaxAccountRecoveryVerifyPassword/", {
      sessionid,
      s: params.s,
      lost: 2,
      reset: 1,
      password: rsa.encrypt(account.password, oldKey.publickey_mod, oldKey.publickey_exp),
      rsatimestamp: oldKey.timestamp,
    });
    const checked = await form(http, jar, "https://help.steampowered.com/en/wizard/AjaxCheckPasswordAvailable/", {
      sessionid,
      wizard_ajax: 1,
      password: newPassword,
    });
    if (!checked.json || !checked.json.available) throw new Error("Steam не принял новый пароль");
    const newKey = await rsaKey();
    await form(http, jar, "https://help.steampowered.com/ru/wizard/AjaxAccountRecoveryChangePassword/", {
      sessionid,
      wizard_ajax: 1,
      s: params.s,
      account: params.account,
      password: rsa.encrypt(newPassword, newKey.publickey_mod, newKey.publickey_exp),
      rsatimestamp: newKey.timestamp,
    });
    return { steamid: steam.steamid };
  }

  return { changeOwnedPassword, cookieHeader, absorbCookies };
});
