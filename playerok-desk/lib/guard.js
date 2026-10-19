(function (root, factory) {
  const api = factory();
  root.DeskGuard = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const ALPHABET = "23456789BCDFGHJKMNPQRTVWXY";

  function b64decode(input) {
    let s = String(input || "").trim().replace(/-/g, "+").replace(/_/g, "/");
    if (!s) throw new Error("пустой секрет");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64(bytes) {
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s);
  }

  async function hmacSha1(key, data) {
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      key,
      { name: "HMAC", hash: "SHA-1" },
      false,
      ["sign"]
    );
    const sig = await crypto.subtle.sign("HMAC", cryptoKey, data);
    return new Uint8Array(sig);
  }

  function packTime(timestamp) {
    const buf = new ArrayBuffer(8);
    const view = new DataView(buf);
    const n = BigInt(Math.floor(timestamp));
    view.setUint32(0, Number((n >> 32n) & 0xffffffffn));
    view.setUint32(4, Number(n & 0xffffffffn));
    return new Uint8Array(buf);
  }

  async function generateGuardCode(sharedSecret, timestampSec) {
    const secret = b64decode(sharedSecret);
    const counter = packTime(Math.floor(Number(timestampSec)) / 30);
    const hash = await hmacSha1(secret, counter);
    const start = hash[19] & 0x0f;
    let full = (
      ((hash[start] & 0x7f) << 24) |
      (hash[start + 1] << 16) |
      (hash[start + 2] << 8) |
      hash[start + 3]
    ) >>> 0;
    let code = "";
    for (let i = 0; i < 5; i++) {
      code += ALPHABET[full % ALPHABET.length];
      full = Math.floor(full / ALPHABET.length);
    }
    return code;
  }

  async function confirmationKey(identitySecret, tag, timestampSec) {
    const secret = b64decode(identitySecret);
    const time = packTime(timestampSec);
    const tagBytes = new TextEncoder().encode(String(tag));
    const msg = new Uint8Array(time.length + tagBytes.length);
    msg.set(time, 0);
    msg.set(tagBytes, time.length);
    return bytesToB64(await hmacSha1(secret, msg));
  }

  async function deviceId(steamid) {
    const data = new TextEncoder().encode(String(steamid));
    const buf = await crypto.subtle.digest("SHA-1", data);
    const hex = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
    return "android:" + [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20, 32)].join("-");
  }

  return { generateGuardCode, confirmationKey, deviceId, b64decode };
});
