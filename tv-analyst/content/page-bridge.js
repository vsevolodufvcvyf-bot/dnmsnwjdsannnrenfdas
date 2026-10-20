/** Код страницы TradingView. Ставит линии на сам график через TradingViewApi. */
(() => {
  if (window.__schemeBridge) return;
  window.__schemeBridge = true;
  const analysisIds = [];
  const orderIds = [];

  function chart() {
    try {
      const api = window.TradingViewApi;
      if (api && typeof api.activeChart === "function") return api.activeChart();
    } catch {
      /* график ещё поднимается */
    }
    return null;
  }

  function read() {
    const current = chart();
    if (!current) return null;
    try {
      return {
        symbol: typeof current.symbol === "function" ? current.symbol() : "",
        resolution: typeof current.resolution === "function" ? String(current.resolution()) : "",
      };
    } catch {
      return null;
    }
  }

  function dropIds(current, bucket) {
    const target = current || chart();
    if (target && typeof target.removeEntity === "function") {
      for (const id of bucket) {
        try {
          target.removeEntity(id, { disableUndo: true });
        } catch {
          try {
            target.removeEntity(id);
          } catch {
            /* уже удалена */
          }
        }
      }
    }
    bucket.length = 0;
  }

  function clear(current) {
    dropIds(current, analysisIds);
  }

  function remember(id, bucket) {
    if (id == null || id === false) return;
    const value = typeof id === "object" && id && "then" in id ? null : id;
    if (value != null) bucket.push(value);
  }

  async function place(current, pointOrPoints, options, bucket = analysisIds) {
    const method = Array.isArray(pointOrPoints) ? "createMultipointShape" : "createShape";
    if (typeof current[method] !== "function") return null;
    const attempt = async (opts) => {
      const created = current[method](pointOrPoints, opts);
      const id = created && typeof created.then === "function" ? await created : created;
      remember(id, bucket);
      return id;
    };
    try {
      return await attempt(options);
    } catch (err) {
      if (options.strict) throw err;
      const slim = { shape: options.shape, text: options.text, disableSave: true, disableUndo: true };
      return attempt(slim);
    }
  }

  function lineOptions(drawing, extra) {
    const palette = {
      pattern: "#5b8cff",
      neck: "#f0c14a",
      entry: "#d1d4dc",
      stop: "#ff4d6a",
      target: "#2fdb8a",
      swing: "#8b97a8",
    };
    const color = palette[drawing.role] || "#5b8cff";
    const dashed = drawing.role === "entry" || drawing.role === "stop" || drawing.role === "target";
    return {
      text: drawing.label || "",
      lock: false,
      disableSelection: false,
      disableSave: true,
      disableUndo: true,
      zOrder: "top",
      overrides: {
        linecolor: color,
        linewidth: drawing.role === "neck" || drawing.role === "pattern" ? 2 : 1,
        linestyle: dashed ? 2 : 0,
        textcolor: color,
        color,
      },
      ...extra,
    };
  }

  async function draw(drawings) {
    const current = chart();
    if (!current) return { ok: false, error: "График TradingView ещё не открылся" };
    clear(current);
    let placed = 0;
    let lastError = "";
    for (const drawing of drawings || []) {
      try {
        let id = null;
        if (drawing.type === "hline" && Number.isFinite(drawing.price) && drawing.time) {
          id = await place(
            current,
            { time: drawing.time, price: drawing.price },
            { shape: "horizontal_line", ...lineOptions(drawing) },
          );
        } else if (
          drawing.type === "segment" &&
          drawing.time1 &&
          drawing.time2 &&
          Number.isFinite(drawing.price1) &&
          Number.isFinite(drawing.price2)
        ) {
          id = await place(
            current,
            [
              { time: drawing.time1, price: drawing.price1 },
              { time: drawing.time2, price: drawing.price2 },
            ],
            { shape: "trend_line", ...lineOptions(drawing) },
          );
        } else if (drawing.type === "dot" && drawing.time && Number.isFinite(drawing.price)) {
          id = await place(
            current,
            { time: drawing.time, price: drawing.price },
            {
              shape: "arrow_down",
              text: drawing.label || "",
              disableSave: true,
              disableUndo: true,
              overrides: { color: "#8b97a8" },
            },
          );
        }
        if (id) placed += 1;
      } catch (err) {
        lastError = err && err.message ? err.message : String(err);
      }
    }
    return { ok: placed > 0 || !(drawings || []).length, placed, error: placed ? "" : lastError };
  }

  function guessTick(price) {
    const abs = Math.abs(price);
    if (!(abs > 0)) return 0.01;
    if (abs >= 100) return 0.01;
    if (abs >= 1) return 0.0001;
    const digits = Math.min(10, Math.ceil(-Math.log10(abs)) + 2);
    return 10 ** -digits;
  }

  async function tickSize(current, price) {
    try {
      if (typeof current.symbolExt === "function") {
        const info = await Promise.resolve(current.symbolExt());
        if (info && info.pricescale) return (info.minmov || 1) / info.pricescale;
      }
    } catch {
      /* нет справочника тика */
    }
    return guessTick(price);
  }

  async function placeOrder(order) {
    const current = chart();
    if (!current) return { ok: false, error: "График не открыт" };
    if (!order || (order.direction !== "long" && order.direction !== "short")) {
      return { ok: false, error: "Нет направления" };
    }
    const risk = Math.abs(order.entry - order.stop);
    const reward = Math.abs(order.target - order.entry);
    if (!(risk > 0) || !(reward > 0)) return { ok: false, error: "Нет стопа или цели" };
    dropIds(current, orderIds);
    const tick = await tickSize(current, order.entry);
    const stopLevel = Math.max(1, Math.round(risk / tick));
    const profitLevel = Math.max(1, Math.round(reward / tick));
    const shape = order.direction === "long" ? "long_position" : "short_position";
    try {
      const id = await place(current, { time: order.time, price: order.entry }, {
        shape,
        text: order.name || "",
        disableSave: true,
        disableUndo: true,
        strict: true,
        overrides: { stopLevel, profitLevel },
      }, orderIds);
      if (id) return { ok: true, mode: "bracket" };
    } catch {
      /* позиция рисуется уровнями ниже */
    }
    let placed = 0;
    for (const level of [
      { price: order.entry, role: "entry", label: "вход" },
      { price: order.stop, role: "stop", label: "стоп" },
      { price: order.target, role: "target", label: "цель" },
    ]) {
      try {
        const id = await place(
          current,
          { time: order.time, price: level.price },
          { shape: "horizontal_line", strict: true, ...lineOptions({ ...level }) },
          orderIds,
        );
        if (id) placed += 1;
      } catch {
        /* следующий уровень */
      }
    }
    if (!placed) return { ok: false, error: "Заявку на график поставить не получилось" };
    return { ok: true, mode: "levels", placed };
  }

  async function setResolution(resolution) {
    const current = chart();
    if (!current || typeof current.setResolution !== "function" || !resolution) return { ok: false };
    try {
      const result = current.setResolution(resolution);
      if (result && typeof result.then === "function") await result;
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err && err.message ? err.message : String(err) };
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.source !== "scheme-assistant") return;
    const reply = (payload) => {
      window.postMessage({ source: "scheme-page", requestId: event.data.requestId, ...payload }, "*");
    };
    if (event.data.type === "read") reply({ type: "read", context: read() });
    if (event.data.type === "draw") {
      draw(event.data.drawings).then((result) => reply({ type: "draw", result }));
    }
    if (event.data.type === "resolution") {
      setResolution(event.data.resolution).then((result) => reply({ type: "resolution", result }));
    }
    if (event.data.type === "order") {
      placeOrder(event.data.order).then((result) => reply({ type: "order", result }));
    }
  });
})();
