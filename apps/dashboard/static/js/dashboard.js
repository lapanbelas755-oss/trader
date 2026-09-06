/**
 * Trader Machine V2 — Real-Time Dashboard JS
 * Uses Socket.IO WebSocket for live data push from server.
 */

"use strict";

// ── Socket.IO Connection ─────────────────────────────────────────────────────
const socket = io({ transports: ["websocket", "polling"] });

let prevBid = null;
let tickCount = 0;

socket.on("connect", () => {
  setWsStatus(true);
  logEvent("INFO", "WebSocket connected — live data active");
});

socket.on("disconnect", () => {
  setWsStatus(false);
  logEvent("WARN", "WebSocket disconnected — attempting reconnect…");
});

socket.on("price_update", (data) => {
  tickCount++;
  updatePrice(data);
  updateStatBar(data);
});

socket.on("candle_update", (candle) => {
  if (candleSeries) {
    candleSeries.update(candle);
  }
});

socket.on("candles_full", (data) => {
  if (candleSeries && data.candles && data.candles.length) {
    candleSeries.setData(data.candles);
    chart.timeScale().fitContent();
  }
});

socket.on("signals_update", (data) => {
  renderSignalsMini(data.signals || []);
  renderSignalsFull(data.signals || []);
  const n = data.count || 0;
  const badge = document.getElementById("signal-count-badge");
  if (badge) badge.textContent = n;
  const ssig = document.getElementById("s-sigs");
  if (ssig) ssig.textContent = n;
  const ts = document.getElementById("sig-timestamp");
  if (ts) ts.textContent = new Date().toLocaleTimeString();
  if (n > 0) {
    logEvent("SIGNAL", `${n} signal(s) updated`);
  }
});

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
function updatePrice(d) {
  const bidEl    = document.getElementById("lp-bid");
  const dirEl    = document.getElementById("lp-dir");
  const spreadEl = document.getElementById("lp-spread");
  const srcEl    = document.getElementById("lp-source");
  const chipEl   = document.getElementById("data-source-chip");

  if (bidEl) {
    const bid = d.bid;
    if (prevBid !== null) {
      const up = bid > prevBid;
      bidEl.classList.remove("up", "down");
      void bidEl.offsetWidth;
      bidEl.classList.add(up ? "up" : "down");
      if (dirEl) dirEl.textContent = up ? "▲" : "▼";
      setTimeout(() => bidEl.classList.remove("up", "down"), 600);
    }
    bidEl.textContent = bid.toFixed(5);
    prevBid = bid;
  }
  if (spreadEl) spreadEl.textContent = d.spread_pips + " pips";
  if (srcEl) {
    const src = d.source || d.data_type || "—";
    srcEl.textContent = src;
    srcEl.style.color = src === "SIMULATION" ? "var(--yellow)" : "var(--green)";
  }
  if (chipEl) {
    const isReal = d.source && d.source !== "SIMULATION";
    chipEl.textContent = isReal ? "LIVE DATA" : "SIMULATED";
    chipEl.className = "chip " + (isReal ? "chip-obs" : "chip-sim");
  }
}

function updateStatBar(d) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("s-bid",    d.bid ? d.bid.toFixed(5) : "—");
  set("s-ask",    d.ask ? d.ask.toFixed(5) : "—");
  set("s-spread", d.spread_pips ? d.spread_pips + " p" : "—");
  set("s-source", d.source || "—");
  set("s-ticks",  tickCount);
}

// ── Chart ─────────────────────────────────────────────────────────────────────
let chart = null;
let candleSeries = null;

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

  candleSeries = chart.addCandlestickSeries({
    upColor: "#00e676", downColor: "#ff4d6d",
    borderUpColor: "#00e676", borderDownColor: "#ff4d6d",
    wickUpColor: "#00e676", wickDownColor: "#ff4d6d",
  });

  // Volume as histogram
  const volSeries = chart.addHistogramSeries({
    color: "rgba(0,212,255,0.2)",
    priceFormat: { type: "volume" },
    priceScaleId: "",
    scaleMargins: { top: 0.85, bottom: 0 },
  });
  window._volSeries = volSeries;

  window.addEventListener("resize", () => {
    if (chart && el) chart.applyOptions({ width: el.offsetWidth });
  });
}

// ── Signals ───────────────────────────────────────────────────────────────────
function dirBadgeClass(dir) {
  return { BUY: "b-buy", SELL: "b-sell", WAIT: "b-wait" }[dir] || "b-wait";
}

function renderSignalsMini(signals) {
  const el = document.getElementById("signals-mini");
  if (!el) return;
  if (!signals.length) { el.innerHTML = `<div class="empty">No active signals — system watching</div>`; return; }
  el.innerHTML = signals.map(s => `
    <div class="sig-item">
      <div class="sig-badge ${dirBadgeClass(s.direction)}">${s.direction}</div>
      <div class="sig-info">
        <div class="sig-name">${s.setup}</div>
        <div class="sig-tags">
          <span class="stag">${s.regime}</span>
          <span class="stag">${s.session}</span>
          <span class="stag">${s.state}</span>
        </div>
        <div class="sig-conf">${s.confidence}%</div>
        <div class="conf-bar"><div class="conf-fill" style="width:${s.confidence}%"></div></div>
      </div>
    </div>`).join("");
}

function renderSignalsFull(signals) {
  const el = document.getElementById("signals-full");
  if (!el) return;
  if (!signals.length) { el.innerHTML = `<div class="empty" style="padding:40px;">No active signals — system is observing market conditions</div>`; return; }
  el.innerHTML = signals.map(s => {
    const sl_pips = s.entry && s.sl ? Math.abs(s.entry - s.sl) * 10000 : 0;
    const tp_pips = s.entry && s.tp ? Math.abs(s.tp - s.entry) * 10000 : 0;
    return `
    <div class="sig-full-item">
      <div class="sig-badge ${dirBadgeClass(s.direction)}" style="width:64px;height:64px;font-size:13px;">${s.direction}</div>
      <div>
        <div class="sig-name" style="font-size:14px;margin-bottom:8px;">${s.setup}</div>
        <div class="sig-tags">
          <span class="stag">Regime: ${s.regime}</span>
          <span class="stag">Session: ${s.session}</span>
          <span class="stag">State: ${s.state}</span>
        </div>
        <div style="margin-top:10px;font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;line-height:1.8;">
          Entry: <span style="color:var(--text)">${s.entry.toFixed(5)}</span> &nbsp;|&nbsp;
          SL: <span style="color:var(--red)">${s.sl.toFixed(5)}</span> (${sl_pips.toFixed(1)}p) &nbsp;|&nbsp;
          TP: <span style="color:var(--green)">${s.tp.toFixed(5)}</span> (${tp_pips.toFixed(1)}p)
        </div>
        <div style="margin-top:8px;">
          ${s.evidence.map(e => `<div style="font-size:11px;color:var(--text-sec);margin-top:3px;">• ${e}</div>`).join("")}
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

    // Telegram page
    renderTelegramStatus(d.telegram || {});
  } catch (e) { console.warn("Health error:", e); }
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

// ── Backtest ──────────────────────────────────────────────────────────────────
async function loadBacktest() {
  try {
    const res = await fetch("/api/backtest");
    const d = await res.json();
    const el = document.getElementById("bt-grid");
    if (!el) return;
    const stats = [
      { l: "Total Trades",    v: d.total_trades,              u: "trades" },
      { l: "Win Rate",        v: d.win_rate + "%",            u: "of completed" },
      { l: "Profit Factor",   v: d.profit_factor,             u: "ratio" },
      { l: "Expectancy",      v: "+" + d.expectancy_r + "R",  u: "per trade" },
      { l: "Max Drawdown",    v: d.max_drawdown_pct + "%",    u: "peak–trough" },
      { l: "Sharpe Ratio",    v: d.sharpe_ratio,              u: "annualized" },
      { l: "Avg Win",         v: d.avg_win_r + "R",           u: "per winner" },
      { l: "Max Loss Streak", v: d.consecutive_losses_max,    u: "in a row" },
    ];
    el.innerHTML = stats.map(s => `
      <div class="bt-card">
        <div class="bt-lbl">${s.l}</div>
        <div class="bt-val">${s.v}</div>
        <div class="bt-unit">${s.u}</div>
      </div>`).join("");
  } catch (e) { console.warn("Backtest error:", e); }
}

// ── Navigation ────────────────────────────────────────────────────────────────
const PAGES = ["dashboard", "signals", "backtest", "system", "telegram"];
const PAGE_LABELS = {
  dashboard: ["Dashboard",      "EURUSD · M5 · WebSocket"],
  signals:   ["Live Signals",   "Real-time setup detection"],
  backtest:  ["Analytics",      "Historical backtest statistics"],
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
  if (subEl)   subEl.textContent = s;

  if (name === "system" || name === "telegram") loadHealth();
  if (name === "backtest") loadBacktest();
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById("clock");
  const update = () => {
    if (el) {
      const now = new Date();
      el.textContent = now.toLocaleTimeString("en-GB") + " UTC+" +
        (-now.getTimezoneOffset() / 60);
    }
  };
  update();
  setInterval(update, 1000);
}

// ── Telegram test button ──────────────────────────────────────────────────────
function setupTelegramBtn() {
  const btn = document.getElementById("btn-tg-test");
  if (btn) {
    btn.addEventListener("click", () => {
      const el = document.getElementById("tg-test-result");
      if (el) el.textContent = "Sending…";
      socket.emit("send_test_telegram");
    });
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
function init() {
  initChart();
  startClock();
  setupTelegramBtn();
  loadHealth();
  loadBacktest();

  document.querySelectorAll("[data-page]").forEach(nav => {
    nav.addEventListener("click", e => {
      e.preventDefault();
      showPage(nav.dataset.page);
    });
  });

  // Periodic health refresh
  setInterval(loadHealth, 30000);

  logEvent("INFO", "Trader Machine V2 initialized");
  logEvent("INFO", "Connecting to WebSocket server…");
}

document.addEventListener("DOMContentLoaded", init);
