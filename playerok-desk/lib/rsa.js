(function (root, factory) {
  const api = factory();
  root.DeskRsa = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function modPow(base, exp, mod) {
    let result = 1n;
    let b = base % mod;
    let e = exp;
    while (e > 0n) {
      if (e & 1n) result = (result * b) % mod;
      e >>= 1n;
      b = (b * b) % mod;
    }
    return result;
  }

  function hexToBigInt(hex) {
    const clean = String(hex || "").trim().replace(/^0x/i, "");
    if (!/^[0-9a-fA-F]+$/.test(clean)) throw new Error("плохой RSA-ключ");
    return BigInt("0x" + clean);
  }

  function bytesToBigInt(bytes) {
    let n = 0n;
    for (const b of bytes) n = (n << 8n) + BigInt(b);
    return n;
  }

  function bigIntToBytes(n, length) {
    const out = new Uint8Array(length);
    let x = n;
    for (let i = length - 1; i >= 0; i--) {
      out[i] = Number(x & 0xffn);
      x >>= 8n;
    }
    return out;
  }

  function pkcs1Pad(message, keyLen) {
    if (message.length > keyLen - 11) throw new Error("пароль длиннее RSA-блока");
    const psLen = keyLen - message.length - 3;
    const ps = new Uint8Array(psLen);
    crypto.getRandomValues(ps);
    for (let i = 0; i < ps.length; i++) {
      if (ps[i] === 0) ps[i] = 1 + (ps[i] % 255);
    }
    const em = new Uint8Array(keyLen);
    em[0] = 0x00;
    em[1] = 0x02;
    em.set(ps, 2);
    em[2 + psLen] = 0x00;
    em.set(message, 3 + psLen);
    return em;
  }

  function encrypt(password, modHex, expHex) {
    const text = String(password);
    if (!/^[\x20-\x7e]+$/.test(text)) {
      throw new Error("пароль Steam должен быть из латинских букв, цифр и знаков");
    }
    const mod = hexToBigInt(modHex);
    const exp = hexToBigInt(expHex);
    const keyLen = Math.ceil(String(modHex).replace(/^0x/i, "").length / 2);
    const message = new TextEncoder().encode(text);
    const em = pkcs1Pad(message, keyLen);
    const cipher = modPow(bytesToBigInt(em), exp, mod);
    const bytes = bigIntToBytes(cipher, keyLen);
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    return btoa(bin);
  }

  return { encrypt };
});
