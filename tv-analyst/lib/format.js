export function formatPrice(p) {
  if (!Number.isFinite(p)) return "—";
  const a = Math.abs(p);
  let digits;
  if (a >= 1000) digits = 2;
  else if (a >= 100) digits = 2;
  else if (a >= 1) digits = 4;
  else if (a >= 0.01) digits = 5;
  else if (a > 0) digits = Math.min(10, Math.ceil(-Math.log10(a)) + 3);
  else digits = 2;
  return p.toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

export function formatPct(p) {
  if (!Number.isFinite(p)) return "—";
  const sign = p > 0 ? "+" : "";
  return sign + (p * 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + "%";
}

export function formatR(r) {
  if (!Number.isFinite(r)) return "—";
  const sign = r > 0 ? "+" : "";
  return sign + r.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + "R";
}
