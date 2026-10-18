/** Код страницы TradingView. Ставит линии на сам график через TradingViewApi. */
(() => {
  if (window.__schemeBridge) return;
  window.__schemeBridge = true;
  const ids = [];

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

  function clear(current) {
    const target = current || chart();
    if (target && typeof target.removeEntity === "function") {
      for (const id of ids) {
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
    ids.length = 0;
  }

  function remember(id) {
    if (id == null || id === false) return;
    const value = typeof id === "object" && id && "then" in id ? null : id;
    if (value != null) ids.push(value);
  }

  async function place(current, pointOrPoints, options) {
    const method = Array.isArray(pointOrPoints) ? "createMultipointShape" : "createShape";
    if (typeof current[method] !== "function") return null;
    const attempt = async (opts) => {
      const created = current[method](pointOrPoints, opts);
      const id = created && typeof created.then === "function" ? await created : created;
      remember(id);
      return id;
    };
    try {
      return await attempt(options);
    } catch (err) {
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
  });
})();
