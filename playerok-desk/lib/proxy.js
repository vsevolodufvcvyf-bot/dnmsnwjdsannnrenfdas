(function (root, factory) {
  const api = factory();
  root.DeskProxy = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function describe(proxyUrl) {
    const raw = String(proxyUrl || "").trim();
    if (!raw) return { enabled: false };
    let parsed;
    try {
      parsed = new URL(raw.includes("://") ? raw : "http://" + raw);
    } catch (error) {
      return { enabled: false, error: "не разобрал адрес прокси" };
    }
    const scheme = parsed.protocol.replace(":", "");
    const kind = scheme.startsWith("socks5") ? "SOCKS5"
      : scheme.startsWith("socks4") ? "SOCKS4"
      : scheme === "https" ? "HTTPS"
      : scheme === "http" ? "PROXY"
      : "";
    const port = parsed.port || (scheme.startsWith("socks") ? "1080" : "8080");
    if (!kind || !/^[\w.-]+$/.test(parsed.hostname) || !/^\d+$/.test(String(port))) {
      return { enabled: false, error: "прокси: нужны хост и порт, например http://логин:пароль@хост:8080" };
    }
    return {
      enabled: true,
      user: decodeURIComponent(parsed.username || ""),
      pass: decodeURIComponent(parsed.password || ""),
      pac: [
        "function FindProxyForURL(url, host) {",
        "  if (host === 'steampowered.com' || host === 'steamcommunity.com' || shExpMatch(host, '*.steampowered.com') || shExpMatch(host, '*.steamcommunity.com')) {",
        "    return '" + kind + " " + parsed.hostname + ":" + port + "';",
        "  }",
        "  return 'DIRECT';",
        "}",
      ].join("\n"),
    };
  }

  return { describe };
});
