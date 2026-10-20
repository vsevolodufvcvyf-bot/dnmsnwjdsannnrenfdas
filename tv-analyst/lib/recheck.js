import { THRESHOLD } from "./decide.js";

function riskOf(pattern) {
  return Math.abs(pattern.entry - pattern.stop);
}

/**
 * Второй проход должен сойтись с первым: та же фигура, то же направление,
 * цена ещё внутри стопа и цели, старший график и новости не против.
 */
export function recheckSetup(first, second, lastPrice, news) {
  const reasons = [];
  const pattern = first?.pattern;
  const direction = first?.verdict;
  if (!pattern || (direction !== "long" && direction !== "short")) {
    return { ok: false, reasons: ["Первый проход не дал сделки"] };
  }
  if (!second?.pattern || second.verdict !== direction) {
    reasons.push("Повторный проход не подтвердил это направление");
  } else if (second.pattern.id !== pattern.id) {
    reasons.push(`На повторе другая фигура: ${second.pattern.name}`);
  } else if (!(second.pattern.score >= THRESHOLD)) {
    reasons.push("На повторе сила сигнала упала ниже порога");
  } else {
    const risk = riskOf(pattern) || riskOf(second.pattern);
    if (risk > 0 && Math.abs(second.pattern.entry - pattern.entry) > risk * 0.35) {
      reasons.push("На повторе вход уехал от первого");
    }
    if (risk > 0 && Math.abs(second.pattern.stop - pattern.stop) > risk * 0.5) {
      reasons.push("На повторе стоп уехал от первого");
    }
  }

  const live = second?.pattern && second.pattern.id === pattern.id ? second.pattern : pattern;
  if (Number.isFinite(lastPrice)) {
    const risk = riskOf(live);
    if (direction === "long") {
      if (lastPrice <= live.stop) reasons.push("Цена уже на стопе или ниже");
      if (lastPrice >= live.target) reasons.push("Цена уже дошла до цели");
      if (risk > 0 && lastPrice < live.entry && live.entry - lastPrice > risk) reasons.push("Цена ушла от входа дальше, чем стоп");
    } else {
      if (lastPrice >= live.stop) reasons.push("Цена уже на стопе или выше");
      if (lastPrice <= live.target) reasons.push("Цена уже дошла до цели");
      if (risk > 0 && lastPrice > live.entry && lastPrice - live.entry > risk) reasons.push("Цена ушла от входа дальше, чем стоп");
    }
    const reward = Math.abs(live.target - live.entry);
    if (!(risk > 0) || reward / risk < 0.7) reasons.push("Цель больше не оправдывает стоп");
  } else {
    reasons.push("Нет свежей цены для проверки");
  }

  if (second?.bias === "up" && direction === "short") reasons.push("Старший график смотрит вверх");
  if (second?.bias === "down" && direction === "long") reasons.push("Старший график смотрит вниз");

  if (news?.tone === "bear" && direction === "long" && news.score <= -2) reasons.push("Новости против лонга");
  if (news?.tone === "bull" && direction === "short" && news.score >= 2) reasons.push("Новости против шорта");

  return {
    ok: reasons.length === 0,
    reasons,
    pattern: live,
    direction,
  };
}
