import { lineChart, sparkline } from "./chart.js";

// ------------------------------------------------------------------ data & formatting
const cache = new Map();
const load = (path) => {
  if (!cache.has(path)) cache.set(path, fetch(`data/${path}`).then((r) => (r.ok ? r.json() : null)));
  return cache.get(path);
};
const pct = (v, digits = 1, signed = false) =>
  v == null ? "—" : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
const num = (v, digits = 2) => (v == null ? "—" : v.toFixed(digits));
const cls = (v) => (v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—");
const money = (v) => (v == null ? "—" : v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T` : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v).toLocaleString()}`);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

let META = null;
let STOCKS = new Set();
const stockLink = (key, label = key) => (STOCKS.has(key) ? h("a", { href: `#/stock/${encodeURIComponent(key)}` }, label) : h("span", {}, label));
const stratName = (id) => META.strategies.find((s) => s.id === id)?.name || id;
const catOf = (id) => META.categories.find((c) => c.id === id);

/** Sortable table. columns: [{key, label, num, render(row), sort(row), title}] */
function table(columns, rows, { sortKey, desc = true, rowClass, compact } = {}) {
  let key = sortKey, down = desc;
  const wrap = h("div", { class: "table-wrap" });
  const render = () => {
    wrap.textContent = "";
    const col = columns.find((c) => c.key === key);
    const sorted = col ? [...rows].sort((a, b) => {
      const va = (col.sort || ((r) => r[col.key]))(a), vb = (col.sort || ((r) => r[col.key]))(b);
      if (va == null) return 1; if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * (down ? -1 : 1);
    }) : rows;
    const head = h("tr", {}, columns.map((c) => {
      const th = h("th", { class: `${c.num ? "num " : ""}${c.nosort ? "" : "sortable"}`, title: c.title }, c.label,
        c.key === key ? h("span", { class: "arrow" }, down ? "▼" : "▲") : null);
      if (!c.nosort) th.addEventListener("click", () => { down = key === c.key ? !down : true; key = c.key; render(); });
      return th;
    }));
    const body = sorted.map((r) => h("tr", { class: rowClass ? rowClass(r) : null },
      columns.map((c) => h("td", { class: `${c.num ? "num " : ""}${c.cls ? c.cls(r) : ""}` }, c.render ? c.render(r) : r[c.key] ?? "—"))));
    wrap.appendChild(h("table", { class: compact ? "table-compact" : null }, h("thead", {}, head), h("tbody", {}, body)));
  };
  render();
  return wrap;
}

function seg(options, current, onChange) {
  const box = h("div", { class: "seg", role: "group" });
  const draw = (value) => {
    box.textContent = "";
    for (const [v, label] of options) {
      box.appendChild(h("button", { class: v === value ? "on" : "", "aria-pressed": v === value, onclick: () => { draw(v); onChange(v); } }, label));
    }
  };
  draw(current);
  return box;
}

const state = { window: "all", basis: "nav", log: true };

// ------------------------------------------------------------------ category history helpers
async function categoryData(id) {
  const data = await load(`categories/${id}.json`);
  if (!data.byDate) {
    data.byDate = new Map();
    const f = Object.fromEntries(data.fields.map((name, i) => [name, i]));
    for (const row of data.rows) {
      const obj = Object.fromEntries(data.fields.map((name, i) => [name, row[i]]));
      if (!data.byDate.has(row[f.d])) data.byDate.set(row[f.d], []);
      data.byDate.get(row[f.d]).push(obj);
    }
  }
  return data;
}

/** Rows for report `date` (or the latest on/before it) plus the diff vs. the previous report. */
function reportWithDiff(data, date, compareTo = null) {
  let i = data.dates.findLastIndex((d) => d <= date);
  if (i < 0) return null;
  const rows = data.byDate.get(i) || [];
  let j = compareTo ? data.dates.findLastIndex((d) => d <= compareTo) : i - 1;
  if (j === i) j = -1;
  const prev = j >= 0 ? data.byDate.get(j) || [] : [];
  const prevRank = new Map(prev.map((r) => [r.key, r.rank]));
  const curKeys = new Set(rows.map((r) => r.key));
  return {
    date: data.dates[i], prevDate: j >= 0 ? data.dates[j] : null,
    rows: rows.map((r) => ({ ...r, prevRank: prevRank.get(r.key) ?? null, isNew: j >= 0 && !prevRank.has(r.key) })),
    dropped: prev.filter((r) => !curKeys.has(r.key)),
  };
}

function changeBadge(r, hasPrev) {
  if (!hasPrev) return h("span", { class: "badge flat" }, "");
  if (r.isNew) return h("span", { class: "badge new", title: "New since the previous report" }, "NEW");
  const move = r.prevRank - r.rank;
  if (move > 0) return h("span", { class: "badge up", title: `Up ${move} from #${r.prevRank}` }, `▲${move}`);
  if (move < 0) return h("span", { class: "badge down", title: `Down ${-move} from #${r.prevRank}` }, `▼${-move}`);
  return h("span", { class: "badge flat" }, "—");
}

const FEATURE_LABELS = {
  return_12m: ["12M", pct], return_1w: ["1W", (v) => pct(v, 1, true)], rank_change: ["Rank Δ (1M)", (v) => (v == null ? "—" : (v > 0 ? "+" : "") + v)],
  return_3m: ["3M", pct], return_6m: ["6M", pct], avg_rank: ["Avg rank", (v) => num(v, 1)],
  pct_vs_sma200: ["vs SMA200", (v) => pct(v, 1, true)], dip_date: ["Dipped", (v) => v], market_cap: ["Mkt cap", money],
};

function reportTable(cat, report, { compact = false, limit } = {}) {
  const hasPrev = !!report.prevDate;
  const rows = limit ? report.rows.slice(0, limit) : report.rows;
  const cols = [
    { key: "rank", label: "#", num: true, render: (r) => r.rank },
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => stockLink(r.key, r.ticker) },
    ...cat.features.slice(0, compact ? 1 : 4).map((f) => ({
      key: f, label: FEATURE_LABELS[f]?.[0] || f, num: f !== "dip_date",
      cls: (r) => (["return_1w", "pct_vs_sma200"].includes(f) ? cls(r[f]) : ""),
      render: (r) => (FEATURE_LABELS[f]?.[1] || String)(r[f]),
    })),
    { key: "chg", label: "vs prior", nosort: true, render: (r) => changeBadge(r, hasPrev) },
  ];
  return table(cols, rows, { sortKey: "rank", desc: false, compact });
}

function droppedLine(report) {
  if (!report.prevDate || !report.dropped.length) return null;
  return h("div", { class: "dropped" }, "Dropped: ", report.dropped.map((r, i) => [i ? ", " : "", stockLink(r.key, r.ticker)]));
}

// ------------------------------------------------------------------ pages
async function overview(root) {
  const head = h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Strategy evaluation"),
      h("p", { class: "lede" }, `Every category × method, evaluated on the same rules since ${fmtDate(META.first_report)}. Total return with dividends, equal weight per position, vs. SPY.`)),
    h("div", { class: "muted small" }, `Data through ${fmtDate(META.data_through)}`));
  const controls = h("div", { class: "controls" });
  const body = h("div");
  root.append(head, controls, body);

  const draw = () => {
    body.textContent = "";
    const w = state.window;
    const rows = META.strategies.filter((s) => s.visible).map((s) => ({ ...s, m: s.metrics[w] || {} }));
    const bench = Object.entries(META.benchmarks).map(([t, m]) => ({ id: `bench.${t}`, name: `${t} (benchmark)`, bench: true, m: m[w] || {}, holdings: [] }));
    const cols = [
      { key: "name", label: "Strategy", sort: (r) => r.name, render: (r) => r.bench ? r.name : h("a", { href: `#/strategy/${r.id}` }, r.name) },
      { key: "spark", label: "", nosort: true, render: (r) => r.spark ? sparkline(r.spark, { color: css("--series-1") }) : "" },
      { key: "cagr", label: "CAGR", num: true, sort: (r) => r.m.cagr, cls: (r) => cls(r.m.cagr), render: (r) => pct(r.m.cagr) },
      { key: "excess", label: "vs SPY", num: true, title: "CAGR minus SPY's CAGR over the same window", sort: (r) => r.m.excess_cagr, cls: (r) => cls(r.m.excess_cagr), render: (r) => pct(r.m.excess_cagr, 1, true) },
      { key: "total", label: "Total", num: true, sort: (r) => r.m.total_return, render: (r) => pct(r.m.total_return, 0) },
      { key: "sharpe", label: "Sharpe", num: true, sort: (r) => r.m.sharpe, render: (r) => num(r.m.sharpe) },
      { key: "dd", label: "Max DD", num: true, sort: (r) => r.m.max_drawdown, render: (r) => pct(r.m.max_drawdown, 0) },
      { key: "win", label: "Win %", num: true, sort: (r) => r.metrics?.all?.win_rate, render: (r) => r.bench ? "" : pct(r.metrics.all.win_rate, 0) },
      { key: "trades", label: "Trades", num: true, sort: (r) => r.metrics?.all?.closed_trades, render: (r) => r.bench ? "" : r.metrics.all.closed_trades },
      { key: "hold", label: "Holding now", nosort: true, render: (r) => h("span", {}, (r.holdings || []).slice(0, 6).map((k) => h("span", { class: "chip link" }, stockLink(k)))) },
    ];
    body.appendChild(table(cols, [...rows, ...bench], { sortKey: "cagr", rowClass: (r) => (r.bench ? "bench" : null) }));
    body.appendChild(h("p", { class: "muted small" }, w === "all"
      ? "Since inception: each strategy from its category's first report; vs SPY over the same dates."
      : `Trailing ${w.toUpperCase()} window.`));
  };
  controls.appendChild(seg(META.windows.map((w) => [w, w === "all" ? "Since inception" : w.toUpperCase()]), state.window, (v) => { state.window = v; draw(); }));
  draw();

  // Latest report, one card per category, with changes vs the previous report.
  const latest = META.categories.reduce((a, c) => (c.latest > a ? c.latest : a), "");
  root.appendChild(h("h2", {}, h("a", { href: `#/report/${latest}` }, `Latest report · ${fmtDate(latest)}`)));
  const grid = h("div", { class: "grid cols-3" });
  root.appendChild(grid);
  const sm = await load("smartmoney.json");
  const radar = new Map();
  for (const b of sm?.congress_buys || []) radar.set(b.ticker, [...(radar.get(b.ticker) || []), "Congress"]);
  for (const b of sm?.fund_buys || []) radar.set(b.ticker, [...(radar.get(b.ticker) || []), "13F"]);
  for (const cat of META.categories) {
    const data = await categoryData(cat.id);
    const report = reportWithDiff(data, latest);
    const flagged = report.rows.filter((r) => radar.has(r.key));
    grid.appendChild(h("div", { class: "card report-card" },
      h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name), h("span", { class: "muted small" }, cat.group)),
      reportTable(cat, report, { compact: true, limit: 10 }),
      droppedLine(report),
      flagged.length ? h("div", { class: "dropped" }, "Smart-money activity: ", flagged.map((r, i) => [i ? ", " : "", stockLink(r.key, r.ticker), ` (${radar.get(r.key).join(" + ")})`])) : null));
  }
}

async function reports(root, date, compareTo) {
  const all = await Promise.all(META.categories.map((c) => categoryData(c.id)));
  const dates = [...new Set(all.flatMap((d) => d.dates))].sort().reverse();
  date = date && dates.includes(date) ? date : dates[0];
  root.appendChild(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, compareTo ? `Compare ${fmtDate(compareTo)} → ${fmtDate(date)}` : `Report · ${fmtDate(date)}`),
      h("p", { class: "lede" }, compareTo ? "Changes between two report dates." : "Each category as published before the open on this date, with changes since the previous report.")),
    h("div", { class: "controls" }, h("span", { class: "muted small" }, "Compare with"),
      h("select", { onchange: (e) => { location.hash = e.target.value ? `#/compare/${e.target.value}/${date}` : `#/report/${date}`; } },
        h("option", { value: "" }, "previous report"),
        dates.filter((d) => d < date).slice(0, 120).map((d) => h("option", { value: d, selected: d === compareTo ? "" : null }, fmtDate(d)))))));

  const list = h("div", { class: "date-list" });
  let year = null;
  for (const d of dates) {
    if (d.slice(0, 4) !== year) { year = d.slice(0, 4); list.appendChild(h("div", { class: "year" }, year)); }
    list.appendChild(h("a", { href: `#/report/${d}`, class: d === date ? "here" : null }, fmtDate(d).replace(/, \d{4}$/, "")));
  }
  const main = h("div", { class: "grid cols-2" });
  root.appendChild(h("div", { class: "report-layout" }, list, main));
  list.querySelector(".here")?.scrollIntoView({ block: "center" });
  META.categories.forEach((cat, k) => {
    const report = reportWithDiff(all[k], date, compareTo);
    main.appendChild(h("div", { class: "card report-card" },
      h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name),
        h("span", { class: "muted small" }, report ? `vs ${report.prevDate ? fmtDate(report.prevDate) : "—"}` : "")),
      report ? [reportTable(cat, report), droppedLine(report)] : h("div", { class: "empty" }, "No report yet on this date.")));
  });
}

async function strategyPage(root, id) {
  const [s, sessions] = await Promise.all([load(`strategies/${id}.json`), load("sessions.json")]);
  if (!s) return root.appendChild(h("p", { class: "empty" }, "Unknown strategy."));
  const cat = catOf(s.category);
  const dates = sessions.slice(s.start, s.start + s.nav.length);
  root.appendChild(h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "muted small" }, h("a", { href: "#/strategies" }, "Strategies"), " / ", h("a", { href: `#/category/${cat.id}` }, cat.name)),
      h("h1", {}, s.name),
      h("p", { class: "lede" }, `${cat.description} Take the ${s.slot}; ${s.hold}; instrument: ${s.instrument}.`))));
  const controls = h("div", { class: "controls" });
  const tiles = h("div", { class: "tiles" });
  const navBox = h("div", { class: "card" });
  const ddBox = h("div", { class: "card", style: "margin-top:14px" });
  root.append(controls, tiles, navBox, ddBox);

  const draw = () => {
    const m = s.metrics[state.window] || s.metrics.all;
    const all = s.metrics.all;
    tiles.textContent = "";
    const tile = (label, value, delta, deltaCls) => h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), delta ? h("div", { class: `delta ${deltaCls || ""}` }, delta) : null);
    tiles.append(
      tile("CAGR", pct(m.cagr), `SPY ${pct(m.benchmark_cagr)}`, cls(m.excess_cagr)),
      tile("Total return", pct(m.total_return, 0), `SPY ${pct(m.benchmark_total_return, 0)}`),
      tile("Sharpe", num(m.sharpe), `Sortino ${num(m.sortino)}`),
      tile("Max drawdown", pct(m.max_drawdown, 0), m.max_drawdown_trough ? `trough ${fmtDate(m.max_drawdown_trough)}` : ""),
      tile("Beta vs SPY", num(m.beta), `alpha ${pct(m.alpha, 1, true)} · corr ${num(m.correlation)}`),
      tile("Win rate", pct(all.win_rate, 0), `${all.closed_trades} closed · ${all.open_trades} open`),
      tile("Avg trade", pct(all.avg_trade, 1, true), `payoff ${num(all.payoff_ratio)} · hold ${all.median_hold_days ?? "—"}d`),
      tile("Half-Kelly", pct(all.half_kelly, 0), all.half_kelly == null ? "needs ≥20 closed trades" : "historical, not advice"));

    const startIdx = state.window === "all" ? 0 : Math.max(0, dates.findIndex((d) => d >= (m.start || dates[0])));
    const slice = (arr) => arr.slice(startIdx);
    const rebase = (arr) => { const a = slice(arr); const b = a.find((v) => v != null); return a.map((v) => (v == null ? null : (100 * v) / b)); };
    const basis = state.basis;
    const series = [{ name: "Strategy", values: rebase(s[basis]), color: css("--series-1") }];
    Object.entries(s.benchmarks).forEach(([t, b], i) => series.push({ name: t, values: rebase(b[basis]), color: css(i ? "--series-3" : "--series-2") }));
    navBox.textContent = "";
    navBox.appendChild(h("h3", {}, `Growth of 100 · ${basis === "nav" ? "total return" : "price return"}`));
    const chartHolder = h("div");
    navBox.appendChild(chartHolder);
    lineChart(chartHolder, { dates: slice(dates), series, height: 320, baseline: 100, log: state.log, format: (v) => v.toFixed(0) });
    navBox.appendChild(h("div", { class: "chart-actions" }, h("button", { class: "linkish", onclick: () => {
      const rows = slice(dates).map((d, i) => ({ d, ...Object.fromEntries(series.map((x) => [x.name, x.values[i]])) }));
      chartHolder.textContent = "";
      chartHolder.appendChild(table([{ key: "d", label: "Date", render: (r) => r.d }, ...series.map((x) => ({ key: x.name, label: x.name, num: true, render: (r) => num(r[x.name], 1) }))], rows.reverse(), { sortKey: "d" }));
    } }, "Show as table")));

    const nav = rebase(s[basis]);
    let peak = -Infinity;
    const dd = nav.map((v) => { if (v == null) return null; peak = Math.max(peak, v); return v / peak - 1; });
    ddBox.textContent = "";
    ddBox.appendChild(h("h3", {}, "Drawdown from peak"));
    const ddHolder = h("div");
    ddBox.appendChild(ddHolder);
    lineChart(ddHolder, { dates: slice(dates), series: [{ name: "Drawdown", values: dd, color: css("--series-1") }], height: 160, baseline: 0, area: true, format: (v) => pct(v, 0) });
  };
  controls.append(
    seg(META.windows.map((w) => [w, w === "all" ? "Since inception" : w.toUpperCase()]), state.window, (v) => { state.window = v; draw(); }),
    seg([["nav", "Total return"], ["nav_price", "Price only"]], state.basis, (v) => { state.basis = v; draw(); }),
    seg([[true, "Log scale"], [false, "Linear"]], state.log, (v) => { state.log = v; draw(); }));
  draw();

  const f = Object.fromEntries(s.trade_fields.map((n, i) => [n, i]));
  const trades = s.trades.map((t) => Object.fromEntries(Object.entries(f).map(([k, i]) => [k, t[i]])));
  const tradeBox = h("div");
  let filter = "all";
  const drawTrades = () => {
    tradeBox.textContent = "";
    const rows = trades.filter((t) => filter === "all" || t.status === filter);
    tradeBox.appendChild(table([
      { key: "ticker", label: "Ticker", cls: () => "ticker", render: (t) => stockLink(t.key, t.ticker) },
      { key: "entry", label: "Entry", render: (t) => fmtDate(t.entry) },
      { key: "exit", label: "Exit", render: (t) => (t.exit ? fmtDate(t.exit) : h("span", { class: "badge new" }, "open")) },
      { key: "days", label: "Days", num: true, sort: (t) => ((t.exit ? new Date(t.exit) : new Date()) - new Date(t.entry)), render: (t) => Math.round(((t.exit ? new Date(t.exit) : new Date(META.data_through)) - new Date(t.entry)) / 864e5) },
      { key: "ret_total", label: "Return", num: true, cls: (t) => cls(t.ret_total), render: (t) => pct(t.ret_total, 1, true) },
      { key: "reason", label: "Exit reason", render: (t) => t.reason || "" },
    ], rows, { sortKey: "entry" }));
  };
  root.append(h("h2", {}, `Trades (${trades.length})`),
    h("div", { class: "controls" }, seg([["all", "All"], ["open", "Open"], ["closed", "Closed"]], filter, (v) => { filter = v; drawTrades(); })),
    tradeBox);
  drawTrades();
}

async function strategiesPage(root) {
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Strategies"),
    h("p", { class: "lede" }, "Strategy = category × slot × method. Edit strategies.yaml to add variants; hidden variants keep being evaluated."))));
  await overview(root.appendChild(h("div")));
}

async function categoryPage(root, id) {
  const cat = catOf(id);
  if (!cat) return root.appendChild(h("p", { class: "empty" }, "Unknown category."));
  const data = await categoryData(id);
  const latest = reportWithDiff(data, data.dates[data.dates.length - 1]);
  root.appendChild(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "muted small" }, h("a", { href: "#/categories" }, "Categories"), " / ", cat.group),
    h("h1", {}, cat.name), h("p", { class: "lede" }, cat.description),
    h("p", { class: "muted small" }, `${cat.reports} reports since ${fmtDate(cat.first)} · universe ${cat.universe}`))));
  root.append(h("h2", {}, `Latest · ${fmtDate(latest.date)}`), reportTable(cat, latest), droppedLine(latest));

  // Membership over the last 40 reports: who was listed, at what rank.
  const recent = data.dates.slice(-40);
  const startIdx = data.dates.length - recent.length;
  const ranks = new Map();
  for (let i = startIdx; i < data.dates.length; i++) for (const r of data.byDate.get(i) || []) {
    if (!ranks.has(r.key)) ranks.set(r.key, { ticker: r.ticker, cells: new Array(recent.length).fill(null), n: 0 });
    const e = ranks.get(r.key); e.cells[i - startIdx] = r.rank; e.n++;
  }
  const names = [...ranks.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 30);
  const maxRank = Math.max(...data.rows.map((r) => r[3]), 10);
  const heat = h("div", { class: "heat", style: `grid-template-columns: 70px repeat(${recent.length}, 1fr)` });
  for (const [key, e] of names) {
    heat.appendChild(h("div", { class: "label" }, stockLink(key, e.ticker)));
    e.cells.forEach((rank, i) => heat.appendChild(h("div", {
      class: "cell", title: `${e.ticker} · ${fmtDate(recent[i])}${rank ? ` · #${rank}` : " · not listed"}`,
      style: rank ? `background: color-mix(in oklab, var(--series-1) ${Math.round(100 - ((rank - 1) / maxRank) * 70)}%, var(--surface))` : "background: var(--surface-2)",
    })));
  }
  root.append(h("h2", {}, "Membership, last 40 reports"),
    h("p", { class: "muted small" }, `Darker = higher rank. ${fmtDate(recent[0])} → ${fmtDate(recent[recent.length - 1])}.`),
    h("div", { class: "card" }, heat));

  const strategies = META.strategies.filter((s) => s.category === id);
  root.append(h("h2", {}, "Strategies on this category"), table([
    { key: "name", label: "Strategy", render: (s) => h("a", { href: `#/strategy/${s.id}` }, s.name) },
    { key: "hold", label: "Method", render: (s) => `${s.instrument}, ${s.hold}` },
    { key: "cagr", label: "CAGR", num: true, sort: (s) => s.metrics.all.cagr, cls: (s) => cls(s.metrics.all.cagr), render: (s) => pct(s.metrics.all.cagr) },
    { key: "sharpe", label: "Sharpe", num: true, sort: (s) => s.metrics.all.sharpe, render: (s) => num(s.metrics.all.sharpe) },
    { key: "dd", label: "Max DD", num: true, sort: (s) => s.metrics.all.max_drawdown, render: (s) => pct(s.metrics.all.max_drawdown, 0) },
  ], strategies, { sortKey: "cagr" }));
}

async function categoriesPage(root) {
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Categories"),
    h("p", { class: "lede" }, "Ranked lists computed for every report date from point-in-time data. Options methods and smart-money categories come next."))));
  const groups = [...new Set(META.categories.map((c) => c.group))];
  for (const g of groups) {
    root.appendChild(h("h2", {}, g));
    const grid = h("div", { class: "grid cols-2" });
    for (const c of META.categories.filter((x) => x.group === g)) {
      const strategies = META.strategies.filter((s) => s.category === c.id);
      grid.appendChild(h("div", { class: "card" }, h("h3", {}, h("a", { href: `#/category/${c.id}` }, c.name)),
        h("p", { class: "ink2", style: "margin:0 0 8px" }, c.description),
        h("div", { class: "muted small" }, `${c.reports} reports · since ${fmtDate(c.first)} · ${strategies.length} strategies`)));
    }
    root.appendChild(grid);
  }
}

async function stockPage(root, key) {
  const [s, sessions, sm] = await Promise.all([load(`stocks/${encodeURIComponent(key)}.json`), load("sessions.json"), load("smartmoney.json")]);
  if (!s) return root.appendChild(h("p", { class: "empty" }, `No page for ${key} (only names that have appeared in a category or watchlist are tracked).`));
  const dates = sessions.slice(s.start, s.start + s.close.length);
  const last = s.close[s.close.length - 1];
  const yearAgo = s.close[Math.max(0, s.close.length - 253)];
  root.appendChild(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "muted small" }, h("a", { href: "#/stocks" }, "Stocks")),
    h("h1", {}, `${s.ticker}`, h("span", { class: "muted", style: "font-weight:400" }, s.name ? ` · ${s.name}` : "")),
    h("p", { class: "lede" }, `${num(last)} · 1Y `, h("span", { class: cls(last / yearAgo - 1) }, pct(last / yearAgo - 1, 1, true)),
      ` · data through ${fmtDate(dates[dates.length - 1])}`))));

  const markers = [];
  for (const [strategy, entry] of s.trades) {
    const i = dates.indexOf(entry);
    if (i >= 0) markers.push({ index: i, value: s.close[i], color: css("--series-2"), label: `Entry · ${stratName(strategy)}` });
  }
  const chartBox = h("div", { class: "card" }, h("h3", {}, "Price (split-adjusted)"),
    h("div", { class: "legend" }, h("span", { class: "item" }, h("span", { class: "key", style: `background:${css("--series-2")};height:8px;width:8px;border-radius:4px` }), "strategy entry")));
  const holder = h("div");
  chartBox.appendChild(holder);
  root.appendChild(chartBox);
  lineChart(holder, { dates, series: [{ name: s.ticker, values: s.close, color: css("--series-1") }], height: 300, markers, format: (v) => v.toFixed(v < 10 ? 2 : 0) });

  const cats = Object.entries(s.categories).map(([id, apps]) => ({ id, name: catOf(id)?.name || id, n: apps.length, first: apps[0][0], last: apps[apps.length - 1][0], best: Math.min(...apps.map((a) => a[1])) }));
  root.append(h("h2", {}, "Category history"), cats.length ? table([
    { key: "name", label: "Category", render: (r) => h("a", { href: `#/category/${r.id}` }, r.name) },
    { key: "n", label: "Reports listed", num: true }, { key: "best", label: "Best rank", num: true },
    { key: "first", label: "First", render: (r) => fmtDate(r.first) }, { key: "last", label: "Most recent", render: (r) => fmtDate(r.last) },
  ], cats, { sortKey: "last" }) : h("p", { class: "empty" }, "Not listed in any category (watchlist name)."));

  if (s.trades.length) root.append(h("h2", {}, "Strategy trades"), table([
    { key: 0, label: "Strategy", render: (t) => h("a", { href: `#/strategy/${t[0]}` }, stratName(t[0])) },
    { key: 1, label: "Entry", render: (t) => fmtDate(t[1]) },
    { key: 2, label: "Exit", render: (t) => (t[2] ? fmtDate(t[2]) : h("span", { class: "badge new" }, "open")) },
    { key: 3, label: "Return", num: true, cls: (t) => cls(t[3]), render: (t) => pct(t[3], 1, true) },
  ], s.trades, { sortKey: 1, compact: true }));

  root.appendChild(h("h2", {}, "Smart money ", h("span", { class: "muted small", style: "font-weight:400" }, "· display only, not used in categories or evaluation")));
  const grid = h("div", { class: "grid cols-2" });
  root.appendChild(grid);
  grid.appendChild(h("div", { class: "card" }, h("h3", {}, `Congress trades (${s.congress.length})`),
    s.congress.length ? table([
      { key: "disclosed", label: "Disclosed", render: (t) => fmtDate(t.disclosed) },
      { key: "member", label: "Member", render: (t) => [t.member, t.outperformer ? h("span", { class: "badge up", style: "margin-left:6px" }, "out-performer") : null] },
      { key: "type", label: "Type", render: (t) => h("span", { class: `badge ${t.type === "buy" ? "up" : "down"}` }, t.type) },
      { key: "amount_hi", label: "Amount", num: true, render: (t) => `${money(t.amount_lo)}–${money(t.amount_hi)}` },
    ], s.congress, { sortKey: "disclosed", compact: true }) : h("p", { class: "empty" }, "No disclosed trades in the ledger.")));
  const f = s.funds || {};
  grid.appendChild(h("div", { class: "card" }, h("h3", {}, `13F holders${f.n_holders ? ` (${f.n_holders})` : ""}`),
    f.holders?.length ? table([
      { key: "name", label: "Fund", render: (r) => r.name },
      { key: "alpha", label: "Fund alpha", num: true, cls: (r) => cls(r.alpha), render: (r) => pct(r.alpha, 0, true) },
      { key: "value", label: "Position", num: true, render: (r) => money(r.value) },
      { key: "conv", label: "% of book", num: true, render: (r) => pct(r.conv, 1) },
    ], f.holders, { sortKey: "alpha", compact: true }) : h("p", { class: "empty" }, "Not held by the ranked 13F funds."),
    f.buyers?.length ? h("p", { class: "small ink2" }, "New buyers last quarter: ", f.buyers.map((b) => b.name).join(", ")) : null,
    h("p", { class: "muted small" }, `13F data as of ${sm?.generated?.hedge || "—"}`)));
}

async function stocksPage(root) {
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Stocks"),
    h("p", { class: "lede" }, "Every name that has appeared in a category or a watchlist."))));
  for (const wl of META.watchlists) {
    root.appendChild(h("div", { class: "card", style: "margin-bottom:12px" }, h("h3", {}, `Watchlist · ${wl.name}`, wl.options ? h("span", { class: "badge new", style: "margin-left:8px" }, "options") : null),
      h("p", { class: "ink2 small", style: "margin:0 0 6px" }, wl.description || ""),
      wl.tickers.map((t) => h("span", { class: "chip link" }, stockLink(t)))));
  }
  root.appendChild(table([
    { key: 0, label: "Ticker", cls: () => "ticker", render: (r) => stockLink(r[0]) },
    { key: 1, label: "Name", render: (r) => r[1] || "" },
  ], META.stocks, { sortKey: 0, desc: false, compact: true }));
}

async function smartMoneyPage(root) {
  const sm = await load("smartmoney.json");
  const tracked = new Set(sm.tracked);
  const link = (t) => (tracked.has(t) ? stockLink(t) : t);
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Smart money"),
    h("p", { class: "lede" }, "Congressional disclosures and 13F filings from the smartmoney tracker. Shown for context only — not yet part of the categories or evaluations."),
    h("p", { class: "muted small" }, `Congress as of ${sm.generated.congress || "—"} · 13F as of ${sm.generated.hedge || "—"}`))));
  const grid = h("div", { class: "grid cols-2" });
  root.appendChild(grid);
  grid.appendChild(h("div", {}, h("h2", {}, "Congress · top members by alpha"), table([
    { key: "member", label: "Member", render: (r) => r.member },
    { key: "chamber", label: "Chamber", render: (r) => r.chamber },
    { key: "dw_alpha", label: "Alpha", num: true, title: "Dollar-weighted return above SPY from copying trades at disclosure", cls: (r) => cls(r.dw_alpha), render: (r) => `${r.dw_alpha > 0 ? "+" : ""}${num(r.dw_alpha, 0)}%` },
    { key: "n_positions", label: "Positions", num: true },
    { key: "win_rate", label: "Win %", num: true, render: (r) => `${num(r.win_rate, 0)}%` },
  ], sm.congress_leaders, { sortKey: "dw_alpha", compact: true })));
  grid.appendChild(h("div", {}, h("h2", {}, "Congress · recent buys by out-performers"), table([
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => link(r.ticker) },
    { key: "latest", label: "Disclosed", render: (r) => fmtDate(r.latest) },
    { key: "n_outperformers", label: "Buyers", num: true },
    { key: "buyers", label: "Who", nosort: true, render: (r) => r.buyers.map((b) => b.member).join(", ") },
  ], sm.congress_buys, { sortKey: "latest", compact: true })));
  grid.appendChild(h("div", {}, h("h2", {}, "13F · top funds by alpha"), table([
    { key: "name", label: "Fund", render: (r) => r.name },
    { key: "alpha", label: "Alpha", num: true, cls: (r) => cls(r.alpha), render: (r) => pct(r.alpha, 0, true) },
    { key: "hit_rate", label: "Beat SPY", num: true, title: "Share of quarters beating SPY", render: (r) => pct(r.hit_rate, 0) },
    { key: "latest_book", label: "Book", num: true, render: (r) => money(r.latest_book) },
  ], sm.fund_leaders, { sortKey: "alpha", compact: true })));
  grid.appendChild(h("div", {}, h("h2", {}, "13F · new buys by skilled funds"), table([
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => link(r.ticker) },
    { key: "issuer", label: "Issuer", render: (r) => r.issuer || "" },
    { key: "score", label: "Conviction", num: true, title: "Σ max(fund alpha, 0) × position / book", render: (r) => num(r.score * 1000, 1) },
    { key: "n_buyers", label: "Funds", num: true },
  ], sm.fund_buys, { sortKey: "score", compact: true })));
}

function methodologyPage(root) {
  const p = (...t) => h("p", { class: "ink2", style: "max-width:780px" }, ...t);
  root.append(h("h1", {}, "Methodology"),
    h("h2", {}, "Data"),
    p("Daily bars from Massive (Polygon) grouped-daily for every security that has been an S&P 500 or S&P 400 member since late 2021, plus watchlists and benchmarks. Prices are stored unadjusted and split-adjusted on read; total return reinvests cash dividends on the ex-date."),
    p("Index membership is rebuilt from Wikipedia's change history and matched to permanent security ids (FIGI), so renames (FB→META) and reused tickers (BNY, INFO, COR) map to the right company. The S&P 400 history is the noisier of the two."),
    p("Megacap cohorts rank by point-in-time company market cap (quarterly anchors carried forward by price) in place of index weight; share classes of one company (GOOG/GOOGL) count once."),
    h("h2", {}, "Reports and signals"),
    p("Every Tuesday and Friday a report is computed from data through the prior session's close. Lists use only data available at that time. Report pages show changes against the previous report, or any earlier one."),
    h("h2", {}, "Execution and portfolios"),
    p("Entries and report-driven exits fill at the session's VWAP on the report date (reports publish before the open). Price-indicator exits are decided on a completed close and fill the next session. Positions are equal-weighted, rebalanced only on days a trade opens or closes, and marked at the close. Idle cash earns nothing. No fees or slippage."),
    h("h2", {}, "Metrics"),
    p("CAGR, total return, Sharpe and Sortino on daily log returns (4% risk-free), max drawdown, beta/alpha and correlation vs SPY, win rate, payoff ratio, and half-Kelly (0.5 × max(0, p − q/b), shown only with ≥20 closed trades). Half-Kelly is a historical capital-at-risk heuristic, not advice."),
    h("h2", {}, "Smart money"),
    p("Congress and 13F panels are read from the smartmoney tracker and shown for context. They are not yet part of any category or evaluation."));
}

// ------------------------------------------------------------------ shell
const NAV = [["#/", "Overview"], ["#/reports", "Reports"], ["#/strategies", "Strategies"], ["#/categories", "Categories"], ["#/stocks", "Stocks"], ["#/smart-money", "Smart money"], ["#/methodology", "Methodology"]];

function shell() {
  const nav = h("nav", { class: "main" }, NAV.map(([href, label]) => h("a", { href }, label)));
  const input = h("input", { type: "search", placeholder: "Find a ticker", "aria-label": "Find a ticker" });
  const results = h("div", { class: "results", hidden: "" });
  input.addEventListener("input", () => {
    const q = input.value.trim().toUpperCase();
    results.textContent = "";
    if (!q) return results.setAttribute("hidden", "");
    const hits = META.stocks.filter(([t, n]) => t.startsWith(q) || (n || "").toUpperCase().includes(q)).slice(0, 12);
    hits.forEach(([t, n]) => results.appendChild(h("a", { href: `#/stock/${encodeURIComponent(t)}`, onclick: () => { input.value = ""; results.setAttribute("hidden", ""); } }, h("b", {}, t), h("span", { class: "muted" }, ` ${n || ""}`))));
    results.toggleAttribute("hidden", !hits.length);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") results.querySelector("a")?.click(); });
  const themes = ["auto", "light", "dark"];
  let theme = (() => { try { return localStorage.getItem("theme") || "auto"; } catch { return "auto"; } })();
  const applyTheme = () => { if (theme === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", theme); };
  const themeBtn = h("button", { class: "theme", title: "Theme" }, `◐ ${theme}`);
  themeBtn.addEventListener("click", () => {
    theme = themes[(themes.indexOf(theme) + 1) % 3];
    try { localStorage.setItem("theme", theme); } catch {}
    themeBtn.textContent = `◐ ${theme}`; applyTheme(); route();
  });
  applyTheme();
  document.body.prepend(h("header", { class: "top" }, h("div", { class: "bar" },
    h("a", { class: "brand", href: "#/" }, "Market Lab"), nav, h("div", { class: "search" }, input, results), themeBtn)));
  return nav;
}

let navEl;
async function route() {
  const main = document.querySelector("main");
  const [, page = "", a, b] = decodeURIComponent(location.hash.replace(/^#\/?/, "#/")).split("/");
  navEl.querySelectorAll("a").forEach((x) => {
    const target = x.getAttribute("href").slice(2);
    x.classList.toggle("here", target === page || (target === "reports" && ["report", "compare"].includes(page))
      || (target === "strategies" && page === "strategy") || (target === "categories" && page === "category") || (target === "stocks" && page === "stock"));
  });
  main.classList.add("loading");
  const root = h("div");
  try {
    if (!page) await overview(root);
    else if (page === "reports") await reports(root);
    else if (page === "report") await reports(root, a);
    else if (page === "compare") await reports(root, b, a);
    else if (page === "strategies") await strategiesPage(root);
    else if (page === "strategy") await strategyPage(root, a);
    else if (page === "categories") await categoriesPage(root);
    else if (page === "category") await categoryPage(root, a);
    else if (page === "stocks") await stocksPage(root);
    else if (page === "stock") await stockPage(root, a);
    else if (page === "smart-money") await smartMoneyPage(root);
    else if (page === "methodology") methodologyPage(root);
    else root.appendChild(h("p", { class: "empty" }, "Page not found."));
  } catch (err) {
    console.error(err);
    root.appendChild(h("p", { class: "empty" }, `Something went wrong loading this page: ${err.message}`));
  }
  main.textContent = "";
  main.appendChild(root);
  main.classList.remove("loading");
  if (!a) window.scrollTo(0, 0);
}

(async function start() {
  META = await load("meta.json");
  STOCKS = new Set(META.stocks.map((s) => s[0]));
  navEl = shell();
  document.querySelector("footer").textContent = `Generated ${META.generated_at.replace("T", " ")} · data through ${fmtDate(META.data_through)} · research tool, not investment advice`;
  window.addEventListener("hashchange", route);
  route();
})();
