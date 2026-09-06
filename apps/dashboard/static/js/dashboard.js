/**
 * Trader Machine V3 — Real-Time Multi-Symbol Dashboard JS
 * Purely mathematical, zero random/simulated signals.
 * Full multi-symbol support: EURUSD, XAUUSD, GBPUSD, USDJPY, GBPJPY.
 */

"use strict";

// ── Symbol Configuration ──────────────────────────────────────────────────────
const SYMBOL_CONFIG = {
  EURUSD: { display: "EUR/USD",        decimals: 5, pipMul: 10000 },
  XAUUSD: { display: "XAU/USD (Gold)", decimals: 2, pipMul: 100   },
  GBPUSD: { display: "GBP/USD",        decimals: 5, pipMul: 10000 },
  USDJPY: { display: "USD/JPY",        decimals: 3, pipMul: 100   },
  GBPJPY: { display: "GBP/JPY",        decimals: 3, pipMul: 100   },
};

let currentSymbol = "EURUSD";
let btSymbol      = "EURUSD";
let prevBid       = null;
let tickCount     = 0;

// ── Socket.IO Connection ─────────────────────────────────────────────────────
const socket = io({ transports: ["websocket", "polling"] });

socket.on("connect", () => {
  setWsStatus(true);
  logEvent("INFO", "WebSocket connected — live multi-symbol feed active");
  // Request candles for the current symbol on connect
  socket.emit("request_candles", { symbol: currentSymbol });
});

socket.on("disconnect", () => {
  setWsStatus(false);
  logEvent("WARN", "WebSocket disconnected — attempting reconnect…");
});

// ── Multi-Symbol Price Update ─────────────────────────────────────────────────
socket.on("price_update", (data) => {
  if (!data || !data.symbol) return;
  const sym = data.symbol.toUpperCase();
  const cfg = SYMBOL_CONFIG[sym] || { decimals: 5, pipMul: 10000 };

  // 1. Update Watchlist Pill for this symbol
  const pillPrice = document.getElementById(`pill-price-${sym}`);
  if (pillPrice && data.bid) {
    pillPrice.textContent = Number(data.bid).toFixed(cfg.decimals);
  }
  const pillTag = document.getElementById(`pill-tag-${sym}`);
  if (pillTag) {
    const isReal = data.source && data.source !== "SIMULATION";
    pillTag.className = "sym-pill-tag " + (isReal ? "tag-real" : "tag-sim");
    pillTag.textContent = data.source === "POSTGRESQL" ? "DB REAL" : (isReal ? "LIVE" : "SIM");
  }

  // 2. If this tick is for currently selected symbol, update main display
  if (sym === currentSymbol) {
    tickCount++;
    updatePrice(data, cfg);
    updateStatBar(data, cfg);
  }
});

// ── Candle Updates ────────────────────────────────────────────────────────────
socket.on("candle_update", (data) => {
  if (!data) return;
  const sym = (data.symbol || "").toUpperCase();
  const c   = data.candle || data;

  if (sym === currentSymbol && candleSeries && c && c.time) {
    try {
      candleSeries.update(c);
    } catch (e) {
      console.debug("Candle update notice:", e);
    }
  }
});

socket.on("candles_full", (data) => {
  if (!data) return;
  const sym = (data.symbol || "").toUpperCase();
  if (sym === currentSymbol && candleSeries && Array.isArray(data.candles)) {
    try {
      candleSeries.setData(data.candles);
      if (chart) chart.timeScale().fitContent();
      if (data.smc) updateSMCOverlays(data.smc);
    } catch (e) {
      console.warn("Candle set error:", e);
    }
  }
});

// ── Signals Update ────────────────────────────────────────────────────────────
socket.on("signals_update", (data) => {
  if (!data) return;
  const sym = (data.symbol || "").toUpperCase();

  if (sym === currentSymbol) {
    renderSignalsMini(data.signals || []);
    renderSignalsFull(data.signals || []);
    if (data.smc) updateSMCOverlays(data.smc);

    const n = data.count || 0;
    const badge = document.getElementById("signal-count-badge");
    if (badge) badge.textContent = n;
    const ssig = document.getElementById("s-sigs");
    if (ssig) ssig.textContent = n;

    const ts = document.getElementById("sig-timestamp");
    if (ts) ts.textContent = new Date().toLocaleTimeString();

    if (n > 0) {
      logEvent("SIGNAL", `${sym}: ${n} verified setup(s) active (${data.status})`);
    }
  }
});

// ── Telegram Test Result ──────────────────────────────────────────────────────
socket.on("telegram_test_result", (data) => {
  const el = document.getElementById("tg-test-result");
  if (el) {
    el.innerHTML = data.success
      ? `<span class="tg-ok">✅ Message sent! Check your Telegram.</span>`
      : `<span class="tg-fail">❌ Failed — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env</span>`;
  }
});

// ── WS Status ────────────────────────────────────────────────────────────────
function setWsStatus(connected) {
  const dot = document.getElementById("ws-dot");
  const label = document.getElementById("ws-label");
  if (dot) {
    dot.className = "ws-dot " + (connected ? "connected" : "disconnected");
  }
  if (label) label.textContent = connected ? "Live" : "Reconnecting…";
}

// ── Price Display ─────────────────────────────────────────────────────────────
function updatePrice(d, cfg) {
  const dec = (cfg && cfg.decimals) || 5;
  const bidEl    = document.getElementById("lp-bid");
  const dirEl    = document.getElementById("lp-dir");
  const spreadEl = document.getElementById("lp-spread");
  const srcEl    = document.getElementById("lp-source");
  const chipEl   = document.getElementById("data-source-chip");
  const symEl    = document.getElementById("lp-symbol");

  if (symEl) {
    symEl.textContent = (cfg && cfg.display) || d.symbol;
  }

  if (bidEl && d.bid != null) {
    const bid = Number(d.bid);
    if (prevBid !== null) {
      const up = bid > prevBid;
      bidEl.classList.remove("up", "down");
      void bidEl.offsetWidth;
      bidEl.classList.add(up ? "up" : "down");
      if (dirEl) dirEl.textContent = up ? "▲" : "▼";
      setTimeout(() => bidEl.classList.remove("up", "down"), 600);
    }
    bidEl.textContent = bid.toFixed(dec);
    prevBid = bid;
  }

  if (spreadEl) {
    spreadEl.textContent = (d.spread_pips != null ? d.spread_pips : "—") + " pips";
  }

  if (srcEl) {
    const src = d.source || d.data_type || "—";
    srcEl.textContent = src;
    srcEl.style.color = (src === "SIMULATION") ? "var(--yellow)" : "var(--green)";
  }

  if (chipEl) {
    const isReal = d.source && d.source !== "SIMULATION";
    chipEl.textContent = isReal ? (d.source === "POSTGRESQL" ? "POSTGRESQL" : "LIVE DATA") : "SIMULATED";
    chipEl.className = "chip " + (isReal ? "chip-obs" : "chip-sim");
  }
}

function updateStatBar(d, cfg) {
  const dec = (cfg && cfg.decimals) || 5;
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("s-bid",    d.bid != null ? Number(d.bid).toFixed(dec) : "—");
  set("s-ask",    d.ask != null ? Number(d.ask).toFixed(dec) : "—");
  set("s-spread", d.spread_pips != null ? d.spread_pips + " p" : "—");
  set("s-source", d.source || "—");
  set("s-ticks",  tickCount);
}

// ── Chart & SMC Visual Overlay ────────────────────────────────────────────────
let chart = null;
let candleSeries = null;
let zigzagSeries = null;
let msbPriceLines = [];
let latestSMC = null;

function initChart() {
  const el = document.getElementById("chart");
  if (!el || chart) return;

  chart = LightweightCharts.createChart(el, {
    layout: { background: { type: "solid", color: "#10142a" }, textColor: "#8892b0" },
    grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "rgba(255,255,255,0.08)", scaleMargins: { top: 0.08, bottom: 0.15 } },
    timeScale: { borderColor: "rgba(255,255,255,0.08)", timeVisible: true, secondsVisible: false },
    width: el.offsetWidth,
    height: 340,
  });

  // 1. Candlestick Series
  candleSeries = chart.addCandlestickSeries({
    upColor: "#00e676", downColor: "#ff4d6d",
    borderUpColor: "#00e676", borderDownColor: "#ff4d6d",
    wickUpColor: "#00e676", wickDownColor: "#ff4d6d",
  });

  // 2. Blue ZigZag Structure Series (connecting Swings)
  zigzagSeries = chart.addLineSeries({
    color: "#2979ff",
    lineWidth: 2,
    lineStyle: LightweightCharts.LineStyle.Solid,
    crosshairMarkerVisible: true,
    priceLineVisible: false,
    lastValueVisible: false,
  });

  setupSMCCanvas();

  // Redraw canvas on chart scroll/pan/zoom
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    requestAnimationFrame(redrawSMCCanvas);
  });

  window.addEventListener("resize", () => {
    if (chart && el) {
      chart.applyOptions({ width: el.offsetWidth });
      resizeSMCCanvas();
      requestAnimationFrame(redrawSMCCanvas);
    }
  });
}

function setupSMCCanvas() {
  const canvas = document.getElementById("smc-canvas");
  const chartEl = document.getElementById("chart");
  if (!canvas || !chartEl) return;
  canvas.width = chartEl.offsetWidth || 600;
  canvas.height = chartEl.offsetHeight || 340;
}

function resizeSMCCanvas() {
  const canvas = document.getElementById("smc-canvas");
  const chartEl = document.getElementById("chart");
  if (!canvas || !chartEl) return;
  canvas.width = chartEl.offsetWidth;
  canvas.height = chartEl.offsetHeight || 340;
}

function updateSMCOverlays(smc) {
  if (!smc) return;
  latestSMC = smc;

  // 1. Update Blue ZigZag Line
  if (zigzagSeries && Array.isArray(smc.zigzag)) {
    try {
      const pts = smc.zigzag
        .filter(p => p.time && p.value != null)
        .map(p => ({ time: Number(p.time), value: Number(p.value) }));
      zigzagSeries.setData(pts);
    } catch (e) {
      console.debug("Zigzag set error:", e);
    }
  }

  // 2. Update MSB Horizontal Lines
  if (candleSeries && Array.isArray(smc.msb_lines)) {
    msbPriceLines.forEach(pl => {
      try { candleSeries.removePriceLine(pl); } catch (e) {}
    });
    msbPriceLines = [];

    smc.msb_lines.slice(-4).forEach(item => {
      try {
        const isBull = (item.type === "MSB_BULLISH");
        const pl = candleSeries.createPriceLine({
          price: Number(item.price),
          color: isBull ? "#00e676" : "#ff4d6d",
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: isBull ? "MSB (Bull)" : "MSB (Bear)",
        });
        msbPriceLines.push(pl);
      } catch (e) {}
    });
  }

  // 3. Redraw Canvas Boxes (Bu-OB, Be-OB, Bu-BB, Be-MB)
  requestAnimationFrame(redrawSMCCanvas);
}

function redrawSMCCanvas() {
  const canvas = document.getElementById("smc-canvas");
  if (!canvas || !chart || !candleSeries || !latestSMC) return;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const orderBlocks   = latestSMC.order_blocks || [];
  const breakerBlocks = latestSMC.breaker_blocks || [];
  const allZones      = [...orderBlocks, ...breakerBlocks];
  const chartWidth    = canvas.width;
  const timeScale     = chart.timeScale();

  allZones.forEach(zone => {
    if (zone.top == null || zone.bottom == null || !zone.start_time) return;

    let x1 = timeScale.timeToCoordinate(Number(zone.start_time));
    let x2 = zone.end_time ? timeScale.timeToCoordinate(Number(zone.end_time)) : null;

    if (x1 == null) x1 = 0;
    if (x2 == null || isNaN(x2)) x2 = chartWidth - 55; // Leave margin for right price axis

    let y1 = candleSeries.priceToCoordinate(Number(zone.top));
    let y2 = candleSeries.priceToCoordinate(Number(zone.bottom));

    if (y1 == null || y2 == null || isNaN(y1) || isNaN(y2)) return;

    const topY = Math.min(y1, y2);
    const boxH = Math.max(Math.abs(y2 - y1), 4);
    const boxW = Math.max(x2 - x1, 20);

    // Draw shaded rectangle
    ctx.fillStyle = zone.color || "rgba(0, 230, 118, 0.22)";
    ctx.fillRect(x1, topY, boxW, boxH);

    // Draw border
    ctx.strokeStyle = zone.border_color || "#00e676";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x1, topY, boxW, boxH);

    // Draw label tag (e.g. Bu-OB, Be-OB, Bu-BB, Be-MB)
    ctx.fillStyle = zone.border_color || "#ffffff";
    ctx.font = "bold 10px 'JetBrains Mono', monospace";
    const labelX = Math.max(x1 + 6, 8);
    const labelY = Math.min(topY + 12, canvas.height - 6);
    ctx.fillText(zone.label || zone.type, labelX, labelY);
  });
}

// ── Symbol Switcher ───────────────────────────────────────────────────────────
function setSymbol(sym) {
  if (!sym) return;
  sym = sym.toUpperCase();
  currentSymbol = sym;
  prevBid = null;
  const cfg = SYMBOL_CONFIG[sym] || { display: sym, decimals: 5, pipMul: 10000 };

  // Update watchlist pill active state
  document.querySelectorAll("#symbol-bar .sym-pill").forEach(p => {
    p.classList.toggle("active", p.dataset.symbol === sym);
  });

  // Update headers
  const subEl = document.getElementById("page-sub");
  if (subEl) subEl.textContent = `${sym} · M5 · WebSocket`;

  const chartTitleEl = document.getElementById("chart-title");
  if (chartTitleEl) chartTitleEl.textContent = `${cfg.display} — M5 Live Chart`;

  const lpSymEl = document.getElementById("lp-symbol");
  if (lpSymEl) lpSymEl.textContent = cfg.display;

  logEvent("INFO", `Switched chart view to ${cfg.display}`);

  // Fetch current price & candles immediately
  fetch(`/api/price?symbol=${sym}`)
    .then(r => r.json())
    .then(d => {
      if (d && d.bid) {
        updatePrice(d, cfg);
        updateStatBar(d, cfg);
      }
    })
    .catch(() => {});

  // Fetch SMC structure overlays immediately
  fetch(`/api/smc?symbol=${sym}`)
    .then(r => r.json())
    .then(d => {
      if (d && d.smc) {
        updateSMCOverlays(d.smc);
      }
    })
    .catch(() => {});

  // Request fresh candles via WebSocket
  socket.emit("request_candles", { symbol: sym });
}

function setupSymbolSwitcher() {
  document.querySelectorAll("#symbol-bar .sym-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const sym = pill.dataset.symbol;
      if (sym && sym !== currentSymbol) {
        setSymbol(sym);
      }
    });
  });

  // Backtest symbol pills
  document.querySelectorAll("#bt-symbol-bar .sym-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const sym = pill.dataset.btsym;
      if (sym) {
        document.querySelectorAll("#bt-symbol-bar .sym-pill").forEach(p => p.classList.toggle("active", p.dataset.btsym === sym));
        btSymbol = sym;
        loadBacktest(sym);
      }
    });
  });
}

// ── Signals ───────────────────────────────────────────────────────────────────
function dirBadgeClass(dir) {
  return { BUY: "b-buy", SELL: "b-sell", WAIT: "b-wait" }[dir] || "b-wait";
}

function renderSignalsMini(signals) {
  const el = document.getElementById("signals-mini");
  if (!el) return;
  if (!signals.length) {
    el.innerHTML = `<div class="empty">No active signals — Sniper waiting for strict SMC confluence & momentum</div>`;
    return;
  }
  el.innerHTML = signals.map(s => {
    const isMom = (s.momentum === "CONFIRMED");
    return `
    <div class="sig-item">
      <div class="sig-badge ${dirBadgeClass(s.direction)}">${s.direction}</div>
      <div class="sig-info">
        <div class="sig-name">${s.setup}</div>
        <div class="sig-tags">
          <span class="stag">${s.symbol}</span>
          <span class="stag stag-rr">${s.rr_ratio || "1:3 RR"}</span>
          <span class="stag ${isMom ? 'stag-mom' : 'stag-pending'}">${isMom ? '⚡ MOMENTUM' : '⏳ PENDING MOM'}</span>
          <span class="stag">${s.state}</span>
        </div>
        <div style="font-size:10px;color:var(--text-sec);font-family:'JetBrains Mono',monospace;margin-top:2px;">
          SL: ${s.sl_pips}p | TP: ${s.tp_pips}p (1:3+)
        </div>
        <div class="sig-conf">${s.confidence}%</div>
        <div class="conf-bar"><div class="conf-fill" style="width:${s.confidence}%"></div></div>
      </div>
    </div>`;
  }).join("");
}

function renderSignalsFull(signals) {
  const el = document.getElementById("signals-full");
  if (!el) return;
  if (!signals.length) {
    el.innerHTML = `<div class="empty" style="padding:40px;">No active signals — Sniper waiting for strict setup confirmation (S01–S05 with 1:3+ RR)</div>`;
    return;
  }
  el.innerHTML = signals.map(s => {
    const sym = s.symbol || currentSymbol;
    const cfg = SYMBOL_CONFIG[sym] || { decimals: 5, pipMul: 10000 };
    const dec = cfg.decimals;
    const sl_pips = s.sl_pips != null ? s.sl_pips : (s.entry && s.sl ? Math.abs(s.entry - s.sl) * cfg.pipMul : 0);
    const tp_pips = s.tp_pips != null ? s.tp_pips : (s.entry && s.tp ? Math.abs(s.tp - s.entry) * cfg.pipMul : 0);
    const isMom   = (s.momentum === "CONFIRMED");
    const evList  = s.evidence || [];

    return `
    <div class="sig-full-item">
      <div class="sig-badge ${dirBadgeClass(s.direction)}" style="width:64px;height:64px;font-size:13px;">${s.direction}</div>
      <div>
        <div class="sig-name" style="font-size:14px;margin-bottom:8px;">${s.setup}</div>
        <div class="sig-tags">
          <span class="stag" style="color:var(--cyan);font-weight:700;">${sym}</span>
          <span class="stag stag-rr">R:R ${s.rr_ratio || "1:3"}</span>
          <span class="stag ${isMom ? 'stag-mom' : 'stag-pending'}">${isMom ? '⚡ MOMENTUM CONFIRMED' : '⏳ PENDING MOMENTUM'}</span>
          <span class="stag">State: ${s.state}</span>
        </div>
        <div style="margin-top:10px;font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;line-height:1.8;">
          Entry: <span style="color:var(--text)">${Number(s.entry).toFixed(dec)}</span> &nbsp;|&nbsp;
          SL: <span style="color:var(--red)">${Number(s.sl).toFixed(dec)}</span> (${Number(sl_pips).toFixed(1)}p) &nbsp;|&nbsp;
          TP: <span style="color:var(--green)">${Number(s.tp).toFixed(dec)}</span> (${Number(tp_pips).toFixed(1)}p — 1:3 RR)
        </div>
        <div style="margin-top:8px;">
          ${evList.map(e => `<div style="font-size:11px;color:var(--text-sec);margin-top:3px;">• ${e}</div>`).join("")}
        </div>
      </div>
      <div style="text-align:right;min-width:70px;">
        <div style="font-size:26px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--cyan);">${s.confidence}%</div>
        <div style="font-size:10px;color:var(--muted);">confidence</div>
      </div>
    </div>`;
  }).join("");
}

// ── Event Log ──────────────────────────────────────────────────────────────────
const _events = [];
const MAX_EVENTS = 40;

function logEvent(level, msg) {
  _events.unshift({ level, msg, time: new Date().toLocaleTimeString() });
  if (_events.length > MAX_EVENTS) _events.length = MAX_EVENTS;
  renderEvents();
}

function levelClass(l) {
  return { INFO: "lv-info", SIGNAL: "lv-signal", WARN: "lv-warn", ERROR: "lv-error" }[l] || "lv-info";
}

function renderEvents() {
  const el = document.getElementById("event-log");
  if (!el) return;
  el.innerHTML = _events.map(e => `
    <div class="ev-item">
      <span class="ev-badge ${levelClass(e.level)}">${e.level}</span>
      <span class="ev-msg">${e.msg}</span>
      <span class="ev-time">${e.time}</span>
    </div>`).join("");
}

// ── Health ────────────────────────────────────────────────────────────────────
async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    const d = await res.json();
    const colorMap = { green: "hb-green", yellow: "hb-yellow", red: "hb-red" };
    const comps = d.components || {};

    const miniEl = document.getElementById("health-mini");
    if (miniEl) {
      miniEl.innerHTML = Object.entries(comps).map(([k, c]) =>
        `<div class="h-item">
          <span class="h-name">${k.replace(/_/g, " ")}</span>
          <span class="h-badge ${colorMap[c.color] || "hb-yellow"}">${c.status}</span>
        </div>`).join("");
    }

    const sysEl = document.getElementById("sys-grid");
    if (sysEl) {
      sysEl.innerHTML = Object.entries(comps).map(([k, c]) =>
        `<div class="sys-item">
          <span class="sys-name">${k.replace(/_/g, " ")}</span>
          <span class="h-badge ${colorMap[c.color] || "hb-yellow"}">${c.status}</span>
        </div>`).join("");
    }

    const uptimeEl = document.getElementById("sys-uptime");
    if (uptimeEl) uptimeEl.textContent = `Uptime: ${d.uptime}`;

    renderTelegramStatus(d.telegram || {});
  } catch (e) {
    console.warn("Health fetch error:", e);
  }
}

function renderTelegramStatus(info) {
  const el = document.getElementById("tg-status-block");
  if (!el) return;
  if (info.configured) {
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;padding:14px 18px;background:rgba(0,230,118,.06);border:1px solid rgba(0,230,118,.2);border-radius:10px;margin-bottom:12px;">
        <span style="font-size:20px;">✅</span>
        <div>
          <div style="font-size:13px;font-weight:600;color:var(--green);">Telegram Connected</div>
          <div style="font-size:12px;color:var(--text-sec);margin-top:2px;">Bot: @${info.bot_username || "—"} &nbsp;|&nbsp; Chat ID: ${info.chat_id || "—"}</div>
        </div>
      </div>`;
  } else {
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;padding:14px 18px;background:rgba(255,152,0,.06);border:1px solid rgba(255,152,0,.2);border-radius:10px;margin-bottom:12px;">
        <span style="font-size:20px;">⚠️</span>
        <div>
          <div style="font-size:13px;font-weight:600;color:var(--orange);">Telegram Not Configured</div>
          <div style="font-size:12px;color:var(--text-sec);margin-top:2px;">${info.error || "Add token and chat ID to .env"}</div>
        </div>
      </div>`;
  }
}

// ── Backtest & Research Analytics ─────────────────────────────────────────────
async function loadBacktest(symbol = btSymbol) {
  try {
    const res = await fetch(`/api/backtest?symbol=${symbol}`);
    const d = await res.json();

    const noteEl = document.getElementById("bt-source-note");
    const chipEl = document.getElementById("bt-source-chip");

    if (noteEl) {
      noteEl.textContent = d.data_period
        ? `Dataset: ${d.data_period} (${d.total_setups || 0} setups)`
        : (d.note || "Awaiting research run");
    }

    if (chipEl) {
      const isReal = d.source === "POSTGRESQL_REAL";
      chipEl.textContent = isReal ? "POSTGRESQL REAL" : "PLACEHOLDER";
      chipEl.className = "chip " + (isReal ? "chip-obs" : "chip-sim");
    }

    const el = document.getElementById("bt-grid");
    if (!el) return;

    const stats = [
      { l: "Total Setups",    v: d.total_setups != null ? d.total_setups : "—",       u: "archetypes detected" },
      { l: "Bullish Setups",  v: d.bullish_count != null ? d.bullish_count : "—",     u: "S01-S05 long" },
      { l: "Bearish Setups",  v: d.bearish_count != null ? d.bearish_count : "—",     u: "S01-S05 short" },
      { l: "Win Rate",        v: d.win_rate != null ? d.win_rate + "%" : "—",         u: "verified trades" },
      { l: "Profit Factor",   v: d.profit_factor || "—",                             u: "gross profit/loss" },
      { l: "Expectancy",      v: d.expectancy_r != null ? d.expectancy_r + "R" : "—", u: "per trade" },
      { l: "Bars Analyzed",   v: d.row_count != null ? d.row_count : "—",             u: `${symbol} M5 bars` },
      { l: "Data Source",     v: d.source || "—",                                     u: "integrity verified" },
    ];

    el.innerHTML = stats.map(s => `
      <div class="bt-card">
        <div class="bt-lbl">${s.l}</div>
        <div class="bt-val">${s.v}</div>
        <div class="bt-unit">${s.u}</div>
      </div>`).join("");
  } catch (e) {
    console.warn("Backtest fetch error:", e);
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────
const PAGES = ["dashboard", "signals", "backtest", "system", "telegram"];
const PAGE_LABELS = {
  dashboard: ["Dashboard",      "EURUSD · M5 · WebSocket"],
  signals:   ["Live Signals",   "Real-time S01–S05 setup detection"],
  backtest:  ["Analytics",      "Historical research & backtest statistics"],
  system:    ["System Health",  "Component status & diagnostics"],
  telegram:  ["Telegram Bot",   "Notification configuration"],
};

function showPage(name) {
  PAGES.forEach(p => {
    const pg  = document.getElementById(`page-${p}`);
    const nav = document.querySelector(`[data-page="${p}"]`);
    if (pg)  pg.classList.toggle("active", p === name);
    if (nav) nav.classList.toggle("active", p === name);
  });
  const [t, s] = PAGE_LABELS[name] || ["Dashboard", ""];
  const titleEl = document.getElementById("page-title");
  const subEl   = document.getElementById("page-sub");
  if (titleEl) titleEl.textContent = t;
  if (subEl)   subEl.textContent = (name === "dashboard") ? `${currentSymbol} · M5 · WebSocket` : s;

  if (name === "system" || name === "telegram") loadHealth();
  if (name === "backtest") loadBacktest(btSymbol);
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById("clock");
  const update = () => {
    if (el) {
      const now = new Date();
      el.textContent = now.toLocaleTimeString("en-GB") + " UTC+" + (-now.getTimezoneOffset() / 60);
    }
  };
  update();
  setInterval(update, 1000);
}

// ── Telegram Test Button ──────────────────────────────────────────────────────
function setupTelegramBtn() {
  const btn = document.getElementById("btn-tg-test");
  if (btn) {
    btn.addEventListener("click", () => {
      const el = document.getElementById("tg-test-result");
      if (el) el.textContent = "Sending test message…";
      socket.emit("send_test_telegram");
    });
  }
}

// ── Initial State Fetch ───────────────────────────────────────────────────────
async function fetchInitialSymbols() {
  try {
    const res = await fetch("/api/symbols");
    const data = await res.json();
    if (data && data.feeds) {
      Object.entries(data.feeds).forEach(([sym, info]) => {
        const latest = info.latest || {};
        const cfg = SYMBOL_CONFIG[sym] || { decimals: 5 };
        const pillPrice = document.getElementById(`pill-price-${sym}`);
        if (pillPrice && latest.bid != null) {
          pillPrice.textContent = Number(latest.bid).toFixed(cfg.decimals);
        }
        const pillTag = document.getElementById(`pill-tag-${sym}`);
        if (pillTag) {
          const isReal = info.source && info.source !== "SIMULATION";
          pillTag.className = "sym-pill-tag " + (isReal ? "tag-real" : "tag-sim");
          pillTag.textContent = info.source === "POSTGRESQL" ? "DB REAL" : (isReal ? "LIVE" : "SIM");
        }
      });
    }
  } catch (e) {
    console.debug("Initial symbols notice:", e);
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
function init() {
  initChart();
  startClock();
  setupSymbolSwitcher();
  setupTelegramBtn();
  loadHealth();
  loadBacktest(btSymbol);
  fetchInitialSymbols();

  document.querySelectorAll("[data-page]").forEach(nav => {
    nav.addEventListener("click", e => {
      e.preventDefault();
      showPage(nav.dataset.page);
    });
  });

  // Periodic refreshes
  setInterval(loadHealth, 30000);
  setInterval(fetchInitialSymbols, 5000);

  logEvent("INFO", "Trader Machine V3 multi-symbol dashboard initialized");
  logEvent("INFO", "Monitoring EURUSD, XAUUSD, GBPUSD, USDJPY, GBPJPY");
}

document.addEventListener("DOMContentLoaded", init);
