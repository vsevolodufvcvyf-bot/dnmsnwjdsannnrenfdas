(() => {
  const HOST_ID = "scheme-assistant-host";
  if (document.getElementById(HOST_ID)) return;

  const host = document.createElement("div");
  host.id = HOST_ID;
  host.style.cssText = "position:fixed;top:0;right:0;z-index:2147483647;height:100vh;pointer-events:none;";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      .wrap { pointer-events: auto; height: 100vh; display: flex; align-items: stretch; font-family: "Segoe UI", system-ui, sans-serif; color: #e7ecf3; }
      .tab {
        width: 42px; writing-mode: vertical-rl; transform: rotate(180deg);
        display: flex; align-items: center; justify-content: center; gap: 8px;
        background: #12161d; color: #e7ecf3; border: 0; border-left: 1px solid #2c3544;
        cursor: pointer; letter-spacing: 0.08em; font-size: 13px; font-weight: 650;
      }
      .tab i { font-style: normal; color: #f0c14a; }
      .panel {
        width: 392px; height: 100vh; overflow: auto; background: #0e1116;
        border-left: 1px solid #2c3544; padding: 12px 12px 18px;
      }
      .wrap.collapsed .panel { display: none; }
      .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
      h1 { font-size: 16px; margin: 0; font-weight: 700; letter-spacing: 0.01em; }
      .sub { color: #93a0b5; font-size: 12px; margin-top: 3px; line-height: 1.35; }
      .icon-btn, button, select, input {
        font: inherit; color: inherit; background: #171b22; border: 1px solid #2c3544; border-radius: 8px;
      }
      .icon-btn { width: 28px; height: 28px; cursor: pointer; }
      .row { display: flex; gap: 8px; margin-top: 10px; }
      input, select { height: 32px; padding: 0 8px; min-width: 0; }
      input { flex: 1; }
      select { width: 84px; }
      button.primary, button.ghost { height: 32px; padding: 0 10px; cursor: pointer; }
      button.primary { background: #f0c14a; color: #1b1403; border-color: #f0c14a; font-weight: 700; }
      button.ghost { background: transparent; }
      .banner {
        margin-top: 12px; border-radius: 12px; padding: 12px 12px 10px; background: #171b22; border: 1px solid #2c3544;
      }
      .banner .title { font-size: 28px; font-weight: 760; letter-spacing: 0.02em; line-height: 1; }
      .banner.long .title, .up { color: #3dd68c; }
      .banner.short .title, .down { color: #ff5d73; }
      .banner.wait .title { color: #f0c14a; }
      .meta { color: #93a0b5; font-size: 12px; margin-top: 6px; }
      .levels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 10px; }
      .level { background: #10141b; border-radius: 8px; padding: 6px 8px; }
      .level span { display: block; color: #93a0b5; font-size: 11px; }
      .level b { font-size: 13px; font-weight: 680; }
      .reasons { margin: 8px 0 0; padding-left: 16px; color: #d5dbe6; font-size: 13px; line-height: 1.4; }
      .reasons li { margin: 3px 0; }
      canvas { width: 100%; height: 250px; margin-top: 10px; background: #10141b; border-radius: 12px; display: block; }
      h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: #93a0b5; margin: 14px 0 6px; }
      .news { display: flex; flex-direction: column; gap: 6px; }
      .news a { color: #d5dbe6; text-decoration: none; font-size: 13px; line-height: 1.35; border-left: 2px solid #2c3544; padding-left: 8px; }
      .news a.bull { border-color: #3dd68c; }
      .news a.bear { border-color: #ff5d73; }
      .news a:hover { color: white; }
      .learn { font-size: 12px; color: #c5cedb; line-height: 1.45; white-space: pre-line; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip { border: 1px solid #2c3544; border-radius: 999px; padding: 3px 8px; font-size: 12px; cursor: pointer; background: #171b22; color: inherit; }
      .err { background: #2a1518; color: #ffd0d6; border-radius: 8px; padding: 8px; margin-top: 10px; font-size: 13px; }
      .foot { color: #7f8b9e; font-size: 11px; line-height: 1.4; margin-top: 12px; }
      .check { display: flex; align-items: center; gap: 6px; color: #c5cedb; font-size: 12px; margin-top: 8px; }
    </style>
    <div class="wrap">
      <button class="tab" type="button">Схема <i>●</i></button>
      <section class="panel">
        <div class="head">
          <div>
            <h1>Схема</h1>
            <div class="sub" id="sub">Смотрю график…</div>
          </div>
          <button class="icon-btn" id="collapse" type="button" title="Свернуть">›</button>
        </div>
        <div class="row">
          <input id="symbol" placeholder="Тикер, если график не узнался" />
          <select id="interval">
            <option>1m</option><option>5m</option><option>15m</option>
            <option>30m</option><option>1h</option><option>4h</option><option>1d</option>
          </select>
        </div>
        <div class="row">
          <button class="primary" id="go" type="button">Разобрать</button>
          <button class="ghost" id="mute" type="button">Звук вкл</button>
          <button class="ghost" id="reset" type="button">Сбросить опыт</button>
        </div>
        <label class="check"><input id="watch" type="checkbox" checked /> Следить за этой монетой и присылать уведомление</label>
        <div id="err"></div>
        <div class="banner wait" id="banner">
          <div class="title" id="title">ЖДАТЬ</div>
          <div class="meta" id="meta">Открой любую монету на TradingView.</div>
          <div class="levels" id="levels"></div>
          <ul class="reasons" id="reasons"></ul>
        </div>
        <canvas id="chart" width="720" height="500"></canvas>
        <h2>Новости монеты</h2>
        <div class="news" id="news"></div>
        <h2>Что ещё видно</h2>
        <div class="learn" id="others">Пока пусто.</div>
        <h2>Опыт по своим ошибкам</h2>
        <div class="learn" id="learn">Бумажные сделки ещё не закрывались.</div>
        <h2>Слежу</h2>
        <div class="chips" id="watchlist"></div>
        <div class="foot" id="foot"></div>
      </section>
    </div>
  `;
  document.documentElement.appendChild(host);

  const $ = (id) => shadow.getElementById(id);
  const wrap = shadow.querySelector(".wrap");
  let intervalTouched = false;
  let symbolTouched = false;
  let detectedSymbol = "";
  let busy = false;
  let mute = false;
  let lastKey = "";

  function formatPrice(p) {
    if (!Number.isFinite(p)) return "—";
    const a = Math.abs(p);
    let digits = 2;
    if (a >= 100) digits = 2;
    else if (a >= 1) digits = 4;
    else if (a >= 0.01) digits = 5;
    else if (a > 0) digits = Math.min(10, Math.ceil(-Math.log10(a)) + 3);
    return p.toLocaleString("ru-RU", { maximumFractionDigits: digits });
  }

  function readContext() {
    const url = new URL(location.href);
    let symbol = url.searchParams.get("symbol");
    if (!symbol) {
      const match = location.pathname.match(/\/symbols\/([^/?#]+)/);
      if (match) symbol = decodeURIComponent(match[1]);
    }
    if (!symbol) {
      const legend = document.querySelector('[data-name="legend-source-title"]');
      const text = legend && legend.textContent ? legend.textContent.trim().split("\n")[0].trim() : "";
      if (text && /[A-Za-z]{2,}/.test(text)) symbol = text;
    }
    if (!symbol) {
      const first = (document.title || "").split(/\s+/)[0];
      if (/^[A-Z0-9.]{2,20}$/i.test(first) && first.toLowerCase() !== "tradingview") symbol = first;
    }
    let interval = "";
    const bar = document.querySelector("#header-toolbar-intervals");
    if (bar) {
      const active = [...bar.querySelectorAll("button")].find((button) => {
        const cls = String(button.className || "");
        return button.getAttribute("aria-pressed") === "true" || button.getAttribute("aria-selected") === "true" || /active|selected/i.test(cls);
      });
      if (active) interval = active.textContent.trim();
    }
    return { symbol: symbol || "", interval };
  }

  function mapInterval(raw) {
    const s = String(raw || "").trim().toLowerCase().replace(/\s/g, "");
    const table = {
      "1": "1m", "1m": "1m", "1м": "1m",
      "5": "5m", "5m": "5m", "5м": "5m",
      "15": "15m", "15m": "15m", "15м": "15m",
      "30": "30m", "30m": "30m",
      "60": "1h", "1h": "1h", "1ч": "1h",
      "240": "4h", "4h": "4h", "4ч": "4h",
      d: "1d", "1d": "1d", "1д": "1d",
    };
    return table[s] || "";
  }

  function chosenSymbol() {
    if (symbolTouched && $("symbol").value.trim()) return $("symbol").value.trim();
    return detectedSymbol || $("symbol").value.trim();
  }

  function chosenInterval() {
    return $("interval").value || "15m";
  }

  function drawChart(candles, drawings) {
    const canvas = $("chart");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(280, rect.width);
    const h = Math.max(220, rect.height);
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.fillStyle = "#10141b";
    g.fillRect(0, 0, w, h);
    if (!candles || candles.length < 2) {
      g.fillStyle = "#93a0b5";
      g.font = "13px sans-serif";
      g.fillText("Свечи появятся после разбора", 16, 28);
      return;
    }
    const padL = 8;
    const padR = 64;
    const padT = 12;
    const padB = 16;
    let min = Infinity;
    let max = -Infinity;
    const take = (price) => {
      if (!Number.isFinite(price)) return;
      if (price < min) min = price;
      if (price > max) max = price;
    };
    for (const candle of candles) {
      take(candle.h);
      take(candle.l);
    }
    for (const drawing of drawings || []) {
      take(drawing.price);
      take(drawing.price1);
      take(drawing.price2);
    }
    if (!Number.isFinite(min) || min === max) {
      min -= 1;
      max += 1;
    }
    const span = max - min;
    min -= span * 0.08;
    max += span * 0.08;
    const xAt = (i) => padL + (i + 0.5) * ((w - padL - padR) / candles.length);
    const yAt = (price) => padT + ((max - price) / (max - min)) * (h - padT - padB);
    g.strokeStyle = "#222836";
    g.lineWidth = 1;
    g.font = "11px sans-serif";
    for (let step = 0; step < 4; step++) {
      const price = min + ((max - min) * step) / 3;
      const y = yAt(price);
      g.beginPath();
      g.moveTo(padL, y);
      g.lineTo(w - padR, y);
      g.stroke();
      g.fillStyle = "#93a0b5";
      g.fillText(formatPrice(price), w - padR + 6, y + 3);
    }
    const bodyW = Math.max(2, ((w - padL - padR) / candles.length) * 0.62);
    candles.forEach((candle, i) => {
      const x = xAt(i);
      const up = candle.c >= candle.o;
      g.strokeStyle = up ? "#3dd68c" : "#ff5d73";
      g.fillStyle = g.strokeStyle;
      g.beginPath();
      g.moveTo(x, yAt(candle.h));
      g.lineTo(x, yAt(candle.l));
      g.stroke();
      const y1 = yAt(Math.max(candle.o, candle.c));
      const y2 = yAt(Math.min(candle.o, candle.c));
      g.fillRect(x - bodyW / 2, y1, bodyW, Math.max(1, y2 - y1));
    });
    const roleColor = { pattern: "#7aa2ff", neck: "#f0c14a", entry: "#d5dbe6", stop: "#ff5d73", target: "#3dd68c", swing: "#6d7b90" };
    for (const drawing of drawings || []) {
      g.strokeStyle = roleColor[drawing.role] || "#7aa2ff";
      g.fillStyle = g.strokeStyle;
      g.lineWidth = drawing.role === "pattern" || drawing.role === "neck" ? 1.6 : 1;
      if (drawing.type === "dot") {
        g.beginPath();
        g.arc(xAt(drawing.i), yAt(drawing.price), 2.4, 0, Math.PI * 2);
        g.fill();
        continue;
      }
      const i1 = drawing.i1 ?? 0;
      const i2 = drawing.i2 ?? candles.length - 1;
      const p1 = drawing.type === "hline" ? drawing.price : drawing.price1;
      const p2 = drawing.type === "hline" ? drawing.price : drawing.price2;
      g.setLineDash(drawing.role === "stop" || drawing.role === "target" || drawing.role === "entry" ? [4, 3] : []);
      g.beginPath();
      g.moveTo(xAt(Math.max(0, i1)), yAt(p1));
      g.lineTo(xAt(Math.min(candles.length - 1, i2)), yAt(p2));
      g.stroke();
      g.setLineDash([]);
      if (drawing.label) {
        g.fillText(drawing.label, xAt(Math.max(0, i1)) + 4, yAt(p1) - 4);
      }
    }
  }

  function directionClass(title) {
    if (title === "ВВЕРХ" || title === "УЖЕ РАСТЁТ") return "long";
    if (title === "ВНИЗ" || title === "УЖЕ ПАДАЕТ") return "short";
    return "wait";
  }

  function render(data) {
    $("err").textContent = "";
    $("err").className = "";
    if (!data || data.ok === false) {
      $("err").className = "err";
      $("err").textContent = data?.error || "Не получилось разобрать график";
      return;
    }
    const analysis = data.analysis;
    const banner = $("banner");
    banner.className = "banner " + directionClass(analysis.title);
    $("title").textContent = analysis.title;
    const dot = shadow.querySelector(".tab i");
    dot.style.color = banner.className.includes("long") ? "#3dd68c" : banner.className.includes("short") ? "#ff5d73" : "#f0c14a";
    const pattern = analysis.pattern;
    const bits = [
      data.symbol.base + (data.news?.name && data.news.name !== data.symbol.base ? " · " + data.news.name : ""),
      data.interval,
      "данные " + data.source,
      "старший " + data.higherInterval,
      data.seed?.catalog ? data.seed.catalog + " схем" : "",
    ];
    $("sub").textContent = bits.filter(Boolean).join(" · ");
    $("meta").textContent = pattern
      ? `${pattern.name} · сила ${pattern.score.toFixed(2)} · цель/стоп ${pattern.rr.toFixed(2)}`
      : analysis.move
        ? analysis.move.text
        : "Фигура не завершена";
    const levels = $("levels");
    levels.innerHTML = "";
    if (pattern) {
      for (const [label, value, cls] of [
        ["Вход", pattern.entry, ""],
        ["Стоп", pattern.stop, "down"],
        ["Цель", pattern.target, "up"],
      ]) {
        const cell = document.createElement("div");
        cell.className = "level";
        const span = document.createElement("span");
        span.textContent = label;
        const strong = document.createElement("b");
        strong.className = cls;
        strong.textContent = formatPrice(value);
        cell.append(span, strong);
        levels.append(cell);
      }
    }
    const reasons = $("reasons");
    reasons.innerHTML = "";
    for (const line of analysis.reasons || []) {
      const li = document.createElement("li");
      li.textContent = line;
      reasons.append(li);
    }
    if (data.closed?.length) {
      const li = document.createElement("li");
      const hit = data.closed[0];
      li.textContent = `${hit.name} дошла до ${hit.outcome === "stop" ? "стопа" : "цели"}. Вес этой фигуры обновлён.`;
      reasons.append(li);
    }
    drawChart(data.candles, analysis.drawings);
    const news = $("news");
    news.innerHTML = "";
    const headlines = [...(data.news?.headlines || [])].sort((a, b) => Number(b.mentions) - Number(a.mentions));
    if (data.news?.error) {
      const div = document.createElement("div");
      div.className = "meta";
      div.textContent = data.news.error;
      news.append(div);
    } else if (!headlines.length) {
      const div = document.createElement("div");
      div.className = "meta";
      div.textContent = "Свежих заголовков по этой монете нет.";
      news.append(div);
    } else {
      for (const item of headlines) {
        const link = document.createElement("a");
        link.className = item.tone || "";
        link.textContent = item.title;
        if (item.link) {
          link.href = item.link;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
        news.append(link);
      }
    }
    const others = $("others");
    if (!analysis.others?.length) others.textContent = "Других завершённых фигур на последней свече нет.";
    else {
      others.textContent = analysis.others
        .map((item) => `${item.name} · ${item.direction === "long" ? "вверх" : "вниз"} · ${item.score.toFixed(2)}`)
        .join("\n");
    }
    renderMemory(data.summary, data.seed, data.openTrades);
    renderWatch(data.watchlist);
  }

  function renderMemory(summary, seed, openTrades) {
    const box = $("learn");
    const lines = [];
    if (seed?.test) {
      const mean = seed.test.meanR;
      lines.push(
        `Стартовый прогон ${ (seed.trainedOn || []).join(", ") }: на контроле ${seed.test.trades} сделок, средний ${mean > 0 ? "+" : ""}${Number(mean).toFixed(2)}R.`,
      );
    } else if (seed?.note) lines.push(seed.note);
    for (const trade of openTrades || []) {
      lines.push(`Слежу бумажно: ${trade.name} от ${formatPrice(trade.entry)}, стоп ${formatPrice(trade.stop)}.`);
    }
    const rows = summary?.rows || [];
    if (!rows.length) lines.push("Пока вес у всех фигур одинаковый. После стопа или цели он изменится.");
    for (const row of rows.slice(0, 6)) {
      const mean = row.meanR > 0 ? "+" : "";
      lines.push(`${row.name}: ${row.samples} сд., средний ${mean}${row.meanR.toFixed(2)}R, вес ${row.weight.toFixed(2)}.`);
    }
    box.textContent = lines.join("\n");
  }

  function renderWatch(list) {
    const box = $("watchlist");
    box.innerHTML = "";
    if (!list?.length) {
      box.textContent = "Список пуст.";
      return;
    }
    for (const item of list) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = item.base || item.symbol;
      chip.title = "Убрать из слежки";
      chip.addEventListener("click", () => {
        chrome.runtime.sendMessage({ type: "unwatch", symbol: item.symbol }, (res) => {
          if (res?.watchlist) renderWatch(res.watchlist);
        });
      });
      box.append(chip);
    }
  }

  function refresh() {
    const symbol = chosenSymbol();
    if (!symbol || busy) return;
    busy = true;
    $("go").textContent = "Смотрю…";
    chrome.runtime.sendMessage(
      { type: "analyze", symbol, interval: chosenInterval(), watch: $("watch").checked },
      (data) => {
        busy = false;
        $("go").textContent = "Разобрать";
        if (chrome.runtime.lastError) {
          render({ ok: false, error: "Расширение перезагрузилось. Обнови страницу TradingView." });
          return;
        }
        const key = data?.ok ? `${data.analysis?.title}:${data.analysis?.pattern?.id || ""}:${data.analysis?.barTime || ""}` : "";
        render(data);
        if (key && key !== lastKey && data?.analysis?.alert) beep();
        if (key) lastKey = key;
      },
    );
  }

  function beep() {
    if (mute) return;
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 740;
      gain.gain.value = 0.03;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.09);
      osc.onended = () => ctx.close();
    } catch {
      /* звук мог быть закрыт браузером до клика по странице */
    }
  }

  function syncFromPage() {
    const ctx = readContext();
    if (ctx.symbol && ctx.symbol !== detectedSymbol) {
      detectedSymbol = ctx.symbol;
      symbolTouched = false;
      $("symbol").value = ctx.symbol;
    } else if (!$("symbol").value && ctx.symbol) {
      $("symbol").value = ctx.symbol;
      detectedSymbol = ctx.symbol;
    }
    const mapped = mapInterval(ctx.interval);
    if (mapped && !intervalTouched && mapped !== $("interval").value) $("interval").value = mapped;
  }

  $("collapse").addEventListener("click", () => wrap.classList.toggle("collapsed"));
  shadow.querySelector(".tab").addEventListener("click", () => wrap.classList.remove("collapsed"));
  $("go").addEventListener("click", refresh);
  $("symbol").addEventListener("change", () => {
    symbolTouched = true;
    refresh();
  });
  $("interval").addEventListener("change", () => {
    intervalTouched = true;
    refresh();
  });
  $("watch").addEventListener("change", refresh);
  $("reset").addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "reset" }, () => refresh());
  });
  $("mute").addEventListener("click", () => {
    mute = !mute;
    $("mute").textContent = mute ? "Звук выкл" : "Звук вкл";
    chrome.runtime.sendMessage({ type: "mute", on: mute });
  });
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg?.type === "toggle") wrap.classList.toggle("collapsed");
  });

  $("foot").textContent =
    "Один вывод на последней закрытой свече. Линии стоят на тех же ценах, по которым посчитаны вход, стоп и цель. Если фигура не дорисована, разметки сделки нет. Бумажный стоп снижает вес схемы, бумажная цель его поднимает. Это не ордер на бирже.";

  chrome.runtime.sendMessage({ type: "state" }, (data) => {
    if (!data?.ok) return;
    mute = !!data.mute;
    $("mute").textContent = mute ? "Звук выкл" : "Звук вкл";
    renderMemory(data.summary, data.seed, []);
    renderWatch(data.watchlist);
  });

  syncFromPage();
  refresh();
  setInterval(() => {
    const before = detectedSymbol;
    syncFromPage();
    if (detectedSymbol !== before || !busy) refresh();
  }, 12000);
})();
