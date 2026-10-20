import { structureBias } from "./indicators.js";
import { weightOf } from "./learn.js";
import { CATALOG, detectImpulse, detectPatterns, swingDots } from "./patterns.js";

export const THRESHOLD = 0.64;

function factor(pattern, bias, news, move) {
  let score = pattern.quality;
  if (bias === "up" && pattern.direction === "long") score *= 1.12;
  if (bias === "down" && pattern.direction === "short") score *= 1.12;
  if (bias === "up" && pattern.direction === "short") score *= 0.62;
  if (bias === "down" && pattern.direction === "long") score *= 0.62;
  if (news?.tone === "bull" && pattern.direction === "long") score *= 1.08;
  if (news?.tone === "bear" && pattern.direction === "short") score *= 1.08;
  if (news?.tone === "bull" && pattern.direction === "short") score *= 0.7;
  if (news?.tone === "bear" && pattern.direction === "long") score *= 0.7;
  if (move?.direction === "up" && pattern.direction === "long") score *= 1.05;
  if (move?.direction === "down" && pattern.direction === "short") score *= 1.05;
  if (move?.direction === "up" && pattern.direction === "short") score *= 0.78;
  if (move?.direction === "down" && pattern.direction === "long") score *= 0.78;
  return score;
}

export function decide(candles, higher, news, memory) {
  const found = detectPatterns(candles);
  const bias = structureBias(higher);
  const move = detectImpulse(candles);
  const scored = found
    .map((pattern) => ({
      ...pattern,
      score: factor(pattern, bias, news, move) * weightOf(memory, pattern.id),
    }))
    .sort((a, b) => b.score - a.score);

  const best = scored[0] || null;
  const opposite = best
    ? scored.find((item) => item.direction !== best.direction && item.score >= THRESHOLD && item.id !== best.id)
    : null;

  let verdict = "wait";
  let chosen = null;
  const reasons = [];

  if (best && best.score >= THRESHOLD && !(opposite && opposite.score > best.score * 0.82)) {
    verdict = best.direction;
    chosen = best;
    reasons.push(best.reason);
    const biasText = bias === "up" ? " Старший график тоже вверх." : bias === "down" ? " Старший график тоже вниз." : "";
    const against = (bias === "up" && best.direction === "short") || (bias === "down" && best.direction === "long");
    reasons.push(
      (against ? "Старший график смотрит в другую сторону, сила из-за этого ниже." : `Сила сигнала ${best.score.toFixed(2)}.`) +
        (against ? "" : biasText),
    );
    if (news?.tone === "bull") reasons.push("Свежие заголовки по монете скорее положительные.");
    if (news?.tone === "bear") reasons.push("Свежие заголовки по монете скорее негативные.");
    if (move && ((move.direction === "down" && verdict === "long") || (move.direction === "up" && verdict === "short"))) {
      reasons.push(move.text + " Короткое движение против фигуры.");
    }
  } else if (best && opposite && opposite.score > best.score * 0.82 && best.score >= THRESHOLD) {
    reasons.push(`${best.name} и ${opposite.name} смотрят в разные стороны. Пока обе сильные, входа нет.`);
  } else if (move) {
    reasons.push(move.text);
    reasons.push("Завершённой фигуры для входа нет, поэтому цель по схеме не ставится.");
  } else {
    reasons.push("Завершённой фигуры нет. Полуготовый контур не размечается, чтобы не рисовать ложный уровень.");
  }

  const drawings = [];
  if (chosen) drawings.push(...chosen.drawings);
  else {
    drawings.push(...swingDots(candles));
    if (move) {
      drawings.push({
        type: "segment",
        role: "pattern",
        i1: move.i1,
        price1: move.from,
        i2: move.i2,
        price2: move.to,
        label: "импульс",
      });
    }
  }

  let title = "ЖДАТЬ";
  if (verdict === "long") title = "ВВЕРХ";
  else if (verdict === "short") title = "ВНИЗ";
  else if (move?.direction === "down") title = "УЖЕ ПАДАЕТ";
  else if (move?.direction === "up") title = "УЖЕ РАСТЁТ";

  return {
    verdict,
    title,
    alert: verdict !== "wait" ? verdict : move ? (move.direction === "down" ? "falling" : "rising") : null,
    pattern: chosen
      ? {
          id: chosen.id,
          name: chosen.name,
          direction: chosen.direction,
          quality: chosen.quality,
          score: chosen.score,
          entry: chosen.entry,
          stop: chosen.stop,
          target: chosen.target,
          rr: chosen.rr,
          reason: chosen.reason,
        }
      : null,
    move,
    reasons,
    drawings,
    others: scored
      .filter((item) => !chosen || item.id !== chosen.id)
      .slice(0, 5)
      .map((item) => ({ id: item.id, name: item.name, direction: item.direction, score: item.score })),
    bias,
    catalogSize: CATALOG.length,
    barTime: candles?.length ? candles[candles.length - 1].t : null,
  };
}
