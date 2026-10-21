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
const stratName = (id) => META.all.strategies.find((s) => s.id === id)?.name || id;
const catOf = (id) => META.all.categories.find((c) => c.id === id);
const windowLabel = (w) => (w === "all" ? "Since inception" : w === "since_added" ? "Since added" : w.toUpperCase());

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
      const th = h("th", { class: `${c.num ? "num " : ""}${c.nosort ? "" : "sortable"}${c.hideNarrow ? " hide-narrow" : ""}`, title: c.title }, c.label,
        c.key === key ? h("span", { class: "arrow" }, down ? "▼" : "▲") : null);
      if (!c.nosort) th.addEventListener("click", () => { down = key === c.key ? !down : true; key = c.key; render(); });
      return th;
    }));
    const body = sorted.map((r) => h("tr", { class: rowClass ? rowClass(r) : null },
      columns.map((c) => {
        const klass = `${c.num ? "num " : ""}${c.cls ? c.cls(r) : ""}${c.hideNarrow ? " hide-narrow" : ""}`;
        const content = c.render ? c.render(r) : r[c.key] ?? "—";
        return h("td", { class: klass, title: klass.includes("text-col") && typeof content === "string" ? content : null }, content);
      })));
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
  pct_vs_sma200: ["vs SMA200", (v) => pct(v, 1, true)],
  dip_date: ["Dipped", (v) => (v ? new Date(v + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—")],
  market_cap: ["Mkt cap", money],
  members: ["Members", (v) => v || "—"], dollars: ["Disclosed $", money],
  last_disclosed: ["Disclosed", (v) => shortDate(v)], return_since: ["Since disclosed", (v) => pct(v, 1, true)],
  funds: ["Funds", (v) => (v == null ? "—" : v.toFixed(0))], top_funds: ["Bought by", (v) => v || "—"],
  value: ["Value", money], held_by: ["Held by", (v) => (v == null ? "—" : v.toFixed(0))],
};
const TEXT_FEATURES = new Set(["dip_date", "members", "top_funds", "last_disclosed"]);
const GROUP_ORDER = ["Momentum", "Reversion", "Congress", "Hedge funds"];
const shortDate = (v) => (v ? new Date(v + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—");
const quarterOf = (d) => `Q${Math.floor((+d.slice(5, 7) - 1) / 3) + 1} ${d.slice(0, 4)}`;
const groups = () => [...new Set(META.categories.map((c) => c.group))].sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b));

function reportTable(cat, report, { compact = false, limit } = {}) {
  const hasPrev = !!report.prevDate;
  const rows = limit ? report.rows.slice(0, limit) : report.rows;
  const cols = [
    { key: "rank", label: "#", num: true, render: (r) => r.rank },
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => stockLink(r.key, r.ticker) },
    ...cat.features.slice(0, compact ? 1 : 4).map((f) => ({
      key: f, label: FEATURE_LABELS[f]?.[0] || f, num: !TEXT_FEATURES.has(f),
      cls: (r) => (["return_1w", "pct_vs_sma200", "return_since"].includes(f) ? cls(r[f]) : TEXT_FEATURES.has(f) && f !== "dip_date" ? "text-col" : ""),
      render: (r) => (FEATURE_LABELS[f]?.[1] || String)(r[f]),
    })),
    { key: "chg", label: "vs prior", nosort: true, render: (r) => changeBadge(r, hasPrev) },
  ];
  return table(cols, rows, { sortKey: "rank", desc: false, compact: true });
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
    const rows = META.strategies.filter((s) => s.visible && !s.options).map((s) => ({ ...s, m: s.metrics[w] || {} }));
    const bench = Object.entries(META.benchmarks).map(([t, m]) => ({ id: `bench.${t}`, name: `${t} (benchmark)`, bench: true, m: m[w] || {}, holdings: [] }));
    const cols = [
      { key: "name", label: "Strategy", sort: (r) => r.name, cls: () => "name-col", render: (r) => r.bench ? r.name : h("a", { href: `#/strategy/${r.id}` }, r.name) },
      { key: "spark", label: "", nosort: true, hideNarrow: true, render: (r) => r.spark ? sparkline(r.spark, { color: css("--series-1") }) : "" },
      { key: "cagr", label: "CAGR", num: true, sort: (r) => r.m.cagr, cls: (r) => cls(r.m.cagr), render: (r) => pct(r.m.cagr) },
      { key: "excess", label: "vs SPY", num: true, title: "CAGR minus SPY's CAGR over the same window", sort: (r) => r.m.excess_cagr, cls: (r) => cls(r.m.excess_cagr), render: (r) => pct(r.m.excess_cagr, 1, true) },
      { key: "total", label: "Total", num: true, sort: (r) => r.m.total_return, render: (r) => pct(r.m.total_return, 0) },
      { key: "sharpe", label: "Sharpe", num: true, sort: (r) => r.m.sharpe, render: (r) => num(r.m.sharpe) },
      { key: "dd", label: "Max DD", num: true, sort: (r) => r.m.max_drawdown, render: (r) => pct(r.m.max_drawdown, 0) },
      { key: "win", label: "Win %", num: true, sort: (r) => r.metrics?.all?.win_rate, render: (r) => r.bench ? "" : pct(r.metrics.all.win_rate, 0) },
      { key: "trades", label: "Trades", num: true, sort: (r) => r.metrics?.all?.closed_trades, render: (r) => r.bench ? "" : r.metrics.all.closed_trades },
      { key: "hold", label: "Holding now", nosort: true, cls: () => "nowrap", render: (r) => h("span", {}, (r.holdings || []).slice(0, 6).map((k) => h("span", { class: "chip link" }, stockLink(k)))) },
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
  const radar = await smartMoneyRadar(latest);
  for (const g of groups()) {
    root.appendChild(h("h3", { class: "group-head" }, g));
    const grid = h("div", { class: "grid cols-3" });
    root.appendChild(grid);
    for (const cat of META.categories.filter((c) => c.group === g)) {
      const report = reportWithDiff(await categoryData(cat.id), latest);
      if (!report) continue;
      const flagged = ["Congress", "Hedge funds"].includes(g) ? [] : report.rows.filter((r) => radar.has(r.key));
      grid.appendChild(h("div", { class: "card report-card" },
        h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name), h("span", { class: "muted small" }, cat.group)),
        reportTable(cat, report, { compact: true, limit: 10 }),
        droppedLine(report),
        flagged.length ? h("div", { class: "dropped" }, "Also on smart-money lists: ", flagged.map((r, i) => [i ? ", " : "", stockLink(r.key, r.ticker), ` (${[...radar.get(r.key)].join(", ")})`])) : null));
    }
  }
}

/** key → names of the smart-money lists it is on, as of a report date. */
async function smartMoneyRadar(date) {
  const radar = new Map();
  for (const cat of META.categories.filter((c) => ["Congress", "Hedge funds"].includes(c.group))) {
    const report = reportWithDiff(await categoryData(cat.id), date);
    for (const r of report?.rows || []) {
      if (!radar.has(r.key)) radar.set(r.key, new Set());
      radar.get(r.key).add(cat.name);
    }
  }
  return radar;
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
  const main = h("div");
  root.appendChild(h("div", { class: "report-layout" }, list, main));
  list.querySelector(".here")?.scrollIntoView({ block: "center" });
  const [congress, hedge] = await Promise.all([congressData(), hedgeData()]);
  for (const g of groups()) {
    main.appendChild(h("h2", { class: "group-head first" }, g));
    const grid = h("div", { class: "grid cols-2" });
    main.appendChild(grid);
    META.categories.forEach((cat, k) => {
      if (cat.group !== g) return;
      const report = reportWithDiff(all[k], date, compareTo);
      grid.appendChild(h("div", { class: "card report-card" },
        h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name),
          h("span", { class: "muted small" }, report ? `vs ${report.prevDate ? fmtDate(report.prevDate) : "—"}` : "")),
        report && report.rows.length ? [reportTable(cat, report), droppedLine(report)] : h("div", { class: "empty" }, report ? "Nothing listed on this date." : "No report yet on this date.")));
    });
    if (g === "Congress" && !compareTo) grid.appendChild(congressDigest(congress, date, { limit: 8 }));
    if (g === "Hedge funds" && !compareTo) grid.appendChild(hedgeDigest(hedge, date, { limit: 8 }));
  }
}

// ------------------------------------------------------------------ smart-money data (aligned to report dates)
function rankIndex(ranks) {
  const m = new Map();
  for (const [d, id, rank, score, size] of ranks) {
    if (!m.has(d)) m.set(d, new Map());
    m.get(d).set(id, { rank, score, size });
  }
  return m;
}

/** Index of the report whose window (previous as_of, as_of] contains `day`, or -1. */
function bucketOf(reports, day) {
  let lo = 0, hi = reports.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (reports[mid][1] >= day) { ans = mid; hi = mid - 1; } else lo = mid + 1; }
  return ans;
}

async function congressData() {
  const c = await load("congress.json");
  if (!c._ready) {
    const f = Object.fromEntries(c.trade_fields.map((n, i) => [n, i]));
    c.rows = c.trades.map((t) => ({ disclosed: t[f.disclosed], traded: t[f.traded], member: t[f.member], ticker: t[f.ticker],
      key: t[f.key], type: t[f.type], lo: t[f.lo], hi: t[f.hi], owner: t[f.owner], bucket: bucketOf(c.reports, t[f.disclosed]) }));
    c.rankAt = rankIndex(c.ranks);
    c.counts = new Map();
    for (const r of c.rows) c.counts.set(r.bucket, (c.counts.get(r.bucket) || 0) + 1);
    c._ready = true;
  }
  return c;
}

async function hedgeData() {
  const d = await load("hedge.json");
  if (!d._ready) {
    const f = Object.fromEntries(d.filing_fields.map((n, i) => [n, i]));
    d.rows = d.filings.map((t) => ({ filed: t[f.filed], cik: t[f.cik], quarter: t[f.quarter], positions: t[f.positions],
      book: t[f.book], rank: t[f.rank], new: t[f.new], exits: t[f.exits], bucket: bucketOf(d.reports, t[f.filed]) }));
    d.rankAt = rankIndex(d.ranks);
    d.counts = new Map();
    for (const r of d.rows) if (r.rank != null) d.counts.set(r.bucket, (d.counts.get(r.bucket) || 0) + 1);
    d._ready = true;
  }
  return d;
}

const reportIndex = (reports, date) => {
  const i = date ? reports.findLastIndex((r) => r[0] <= date) : reports.length - 1;
  return i < 0 ? reports.length - 1 : i;
};

const amount = (lo, hi) => (lo == null ? "—" : hi && hi !== lo ? `${money(lo)}–${money(hi)}` : money(lo));
const typeBadge = (t) => h("span", { class: `badge ${t === "P" ? "up" : t === "S" ? "down" : "flat"}` }, { P: "buy", S: "sell", E: "exch." }[t] || t);
const rankBadge = (rank, title) => (rank ? h("span", { class: `badge ${rank <= 5 ? "new" : "flat"}`, title }, `#${rank}`) : null);

function congressDigest(c, date, { limit, topOnly = true } = {}) {
  const i = reportIndex(c.reports, date);
  const ranks = c.rankAt.get(i) || new Map();
  const rows = c.rows.filter((r) => r.bucket === i);
  const buys = rows.filter((r) => r.type === "P").length, sells = rows.filter((r) => r.type === "S").length;
  const ranked = rows.filter((r) => ranks.has(r.member)).sort((a, b) => ranks.get(a.member).rank - ranks.get(b.member).rank || (b.hi || 0) - (a.hi || 0));
  const shown = (topOnly ? ranked : rows).slice(0, limit || rows.length);
  const prev = i > 0 ? c.reports[i - 1][1] : null;
  return h("div", { class: "card report-card" },
    h("h3", {}, h("a", { href: `#/congress/${c.reports[i][0]}` }, "Congress disclosures"), h("span", { class: "muted small" }, prev ? `${shortDate(prev)} → ${shortDate(c.reports[i][1])}` : "")),
    h("p", { class: "small ink2", style: "margin:0 0 8px" }, `${rows.length} trades disclosed (${buys} buys, ${sells} sells) by ${new Set(rows.map((r) => r.member)).size} members; ${ranked.length} by top-25 members.`),
    shown.length ? disclosureTable(c, shown, ranks, { compact: true }) : h("div", { class: "empty" }, "No trades by top-ranked members in this window."),
    limit && ranked.length > limit ? h("div", { class: "dropped" }, h("a", { href: `#/congress/${c.reports[i][0]}` }, `All ${rows.length} disclosures →`)) : null);
}

function disclosureTable(c, rows, ranks, { compact } = {}) {
  return table([
    { key: "disclosed", label: "Disclosed", render: (r) => shortDate(r.disclosed) },
    { key: "member", label: "Member", sort: (r) => ranks.get(r.member)?.rank ?? 999, render: (r) => [memberLink(r.member, c.members[r.member]?.[0] || r.member), " ", rankBadge(ranks.get(r.member)?.rank, "Rank by follow-the-disclosure alpha at this report")] },
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => (r.key ? stockLink(r.key, r.ticker) : r.ticker) },
    { key: "type", label: "Type", render: (r) => typeBadge(r.type) },
    { key: "hi", label: "Amount", num: true, render: (r) => amount(r.lo, r.hi) },
    { key: "traded", label: "Traded", hideNarrow: true, render: (r) => shortDate(r.traded) },
  ], rows, { sortKey: compact ? "member" : "disclosed", desc: !compact, compact: true });
}

function hedgeDigest(d, date, { limit, rankedOnly = true } = {}) {
  const i = reportIndex(d.reports, date);
  const rows = d.rows.filter((r) => r.bucket === i && (!rankedOnly || r.rank != null)).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  const prev = i > 0 ? d.reports[i - 1][1] : null;
  return h("div", { class: "card report-card" },
    h("h3", {}, h("a", { href: `#/hedge/${d.reports[i][0]}` }, "13F filings"), h("span", { class: "muted small" }, prev ? `${shortDate(prev)} → ${shortDate(d.reports[i][1])}` : "")),
    h("p", { class: "small ink2", style: "margin:0 0 8px" }, rows.length ? `${rows.length} filings by ${rankedOnly ? "top-ranked funds" : "tracked funds"} in this window.` : "No filings by ranked funds in this window (13Fs arrive in waves ~45 days after each quarter)."),
    rows.length ? filingTable(d, rows.slice(0, limit || rows.length), { compact: true }) : null,
    limit && rows.length > limit ? h("div", { class: "dropped" }, h("a", { href: `#/hedge/${d.reports[i][0]}` }, `All ${rows.length} filings →`)) : null);
}

const chips = (items, title) => h("span", {}, items.map(([t, key, w]) => h("span", { class: "chip link", title: `${title} · ${pct(w, 1)} of book` }, key ? stockLink(key, t) : t, h("span", { class: "muted" }, ` ${pct(w, 0)}`))));

function filingTable(d, rows, { compact } = {}) {
  return table([
    { key: "filed", label: "Filed", render: (r) => shortDate(r.filed) },
    { key: "rank", label: "Fund", sort: (r) => r.rank ?? 999, cls: () => "name-col", render: (r) => [fundLink(r.cik, d.funds[r.cik] || r.cik), " ", rankBadge(r.rank, "Rank by follow-the-filing alpha when this filing was reported")] },
    { key: "quarter", label: "Qtr", hideNarrow: true, render: (r) => quarterOf(r.quarter) },
    { key: "new", label: "New positions", nosort: true, render: (r) => (r.new.length ? chips(r.new.slice(0, compact ? 4 : 8), "new") : h("span", { class: "muted" }, "none")) },
    { key: "exits", label: "Exited", nosort: true, hideNarrow: true, render: (r) => (r.exits.length ? chips(r.exits.slice(0, compact ? 3 : 5), "exited") : h("span", { class: "muted" }, "none")) },
  ], rows, { sortKey: "rank", desc: false, compact: true });
}

function dateList(reports, i, base, counts, label) {
  const list = h("div", { class: "date-list" });
  let year = null;
  for (let k = reports.length - 1; k >= 0; k--) {
    const d = reports[k][0];
    if (d.slice(0, 4) !== year) { year = d.slice(0, 4); list.appendChild(h("div", { class: "year" }, year)); }
    const n = counts.get(k) || 0;
    list.appendChild(h("a", { href: `#/${base}/${d}`, class: k === i ? "here" : null, title: `${n} ${label}` },
      shortDate(d), n ? h("span", { class: "count" }, n) : null));
  }
  return list;
}

function leaderTable(rows, { kind }) {
  return table([
    { key: "rank", label: "#", num: true },
    { key: "name", label: kind === "congress" ? "Member" : "Fund", cls: () => "name-col", render: (r) => [kind === "congress" ? memberLink(r.id, r.name) : fundLink(r.id, r.name), r.detail ? h("span", { class: "muted small" }, ` ${r.detail}`) : null] },
    { key: "size", label: kind === "congress" ? "Disclosed (2y)" : "13F book", num: true, title: kind === "congress" ? "Every purchase and sale disclosed in the last two years (range midpoints)" : "Reported value of long US positions in the latest 13F", render: (r) => money(r.size) },
    { key: "score", label: "Alpha", num: true, title: kind === "congress" ? "Dollar-weighted return above SPY, copying each purchase at disclosure" : "Follow-the-filing return minus SPY over completed quarters", cls: (r) => cls(r.score), render: (r) => pct(r.score, 0, true) },
    { key: "move", label: "vs prior", nosort: true, render: (r) => (r.prev == null ? h("span", { class: "badge new" }, "NEW") : r.prev > r.rank ? h("span", { class: "badge up" }, `▲${r.prev - r.rank}`) : r.prev < r.rank ? h("span", { class: "badge down" }, `▼${r.rank - r.prev}`) : h("span", { class: "badge flat" }, "—")) },
    ...(rows[0]?.extra || []).map((x, j) => ({ key: `x${j}`, label: x[0], num: true, hideNarrow: true, sort: (r) => r.extra[j][2], render: (r) => r.extra[j][1] })),
  ], rows, { sortKey: "rank", desc: false, compact: true });
}

function leadersAt(data, i, kind, n = 25) {
  const cur = data.rankAt.get(i) || new Map(), prev = data.rankAt.get(i - 1);
  const latest = i === data.reports.length - 1 || data.reports[i][0] === data.leaders[0]?.as_of_report;
  const byId = new Map((latest ? data.leaders : []).map((r) => [String(r.id), r]));
  return [...cur.entries()].sort((a, b) => a[1].rank - b[1].rank).slice(0, n).map(([id, v]) => {
    const L = byId.get(String(id));
    const name = kind === "congress" ? data.members[id]?.[0] || id : data.funds[id] || L?.name || id;
    const detail = kind === "congress" ? [data.members[id]?.[1], data.members[id]?.[3]].filter(Boolean).join(" · ") : "";
    const extra = !L ? [] : kind === "congress"
      ? [["Trades", L.trades ?? "—", L.trades], ["Positions", L.lots, L.lots], ["Return", pct(L.return, 0, true), L.return], ["Beat SPY", pct(L.beat_spy, 0), L.beat_spy]]
      : [["Qtrs", L.periods, L.periods], ["Return", pct(L.return, 0, true), L.return], ["Beat SPY", pct(L.hit_rate, 0), L.hit_rate]];
    return { id, rank: v.rank, score: v.score, size: v.size, name, detail, prev: prev ? prev.get(id)?.rank ?? null : v.rank, extra };
  });
}

async function smartPage(root, kind, date) {
  const isC = kind === "congress";
  const data = await (isC ? congressData() : hedgeData());
  const R = data.reports;
  const first = R.findIndex((_, k) => (data.counts.get(k) || 0) > 0 || data.rankAt.has(k));
  const i = Math.max(reportIndex(R, date), first);
  const [d, asOf] = R[i];
  const cats = META.categories.filter((c) => c.group === (isC ? "Congress" : "Hedge funds"));
  root.appendChild(h("div", { class: "page-head" }, h("div", {},
    h("h1", {}, isC ? "Congress" : "Hedge funds (13F)", h("span", { class: "muted", style: "font-weight:400" }, ` · report ${fmtDate(d)}`)),
    h("p", { class: "lede" }, isC
      ? "Periodic Transaction Reports from the House and Senate, bucketed into the Tuesday/Friday report dates by disclosure date. Members are ranked point-in-time: copy each disclosed purchase at the next close, hold until a sale is disclosed, scored on everything they held over the trailing two years — purchases in that time plus earlier purchases still owned when it began, counted from its start — as value-weighted alpha vs SPY (not annualized; at least 5 positions). The ledger starts Jun 18, 2024, so holdings bought before then are unknown. Click a member for 1-year and 2-year records and everything they disclosed."
      : "13F-HR filings, bucketed into the Tuesday/Friday report dates by filing date. Funds are ranked point-in-time by follow-the-filing alpha: buy each disclosed book the session after it is filed, hold to the next filing, value-weighted, vs SPY, over completed quarters that started in the trailing two years (the 13F ledger starts with filings from Jul 2024). Click a fund for its quarterly books, 1-year and 2-year records and holdings."),
    h("p", { class: "muted small" }, `Data through ${fmtDate(asOf)} · ledger updated ${(data.ledger_updated || "—").replace("T", " ")}`,
      !isC && data.wave?.quarter ? ` · ${quarterOf(data.wave.quarter)} filings: ${data.wave.filed} of today's top ${data.wave.top} funds have filed` : ""))));
  const main = h("div");
  root.appendChild(h("div", { class: "report-layout" }, dateList(R.slice(0), i, kind, data.counts, isC ? "disclosures" : "filings by ranked funds"), main));
  root.querySelector(".date-list .here")?.scrollIntoView({ block: "center" });

  const grid = h("div", { class: "grid cols-2" });
  main.appendChild(grid);
  for (const cat of cats) {
    const report = reportWithDiff(await categoryData(cat.id), d);
    grid.appendChild(h("div", { class: "card report-card" },
      h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name), h("span", { class: "muted small" }, report?.prevDate ? `vs ${shortDate(report.prevDate)}` : "")),
      report && report.rows.length ? [reportTable(cat, report), droppedLine(report)] : h("div", { class: "empty" }, "Nothing listed on this date.")));
  }

  let scope = "top";
  const box = h("div");
  const draw = () => {
    box.textContent = "";
    if (isC) {
      const ranks = data.rankAt.get(i) || new Map();
      const rows = data.rows.filter((r) => r.bucket === i && (scope === "all" || ranks.has(r.member)));
      box.appendChild(rows.length ? disclosureTable(data, rows, ranks) : h("p", { class: "empty" }, "No disclosures in this window."));
    } else {
      const rows = data.rows.filter((r) => r.bucket === i && (scope === "all" || r.rank != null));
      box.appendChild(rows.length ? filingTable(data, rows) : h("p", { class: "empty" }, "No filings in this window."));
    }
  };
  const prev = i > 0 ? R[i - 1][1] : null;
  main.append(h("h2", {}, isC ? "Disclosed since the previous report" : "Filed since the previous report",
      h("span", { class: "muted small", style: "font-weight:400" }, prev ? ` · ${fmtDate(prev)} → ${fmtDate(asOf)}` : "")),
    h("div", { class: "controls" }, seg([["top", isC ? "Top-25 members" : "Ranked funds"], ["all", "All"]], scope, (v) => { scope = v; draw(); })),
    box);
  draw();

  const leaders = leadersAt(data, i, kind);
  main.append(h("h2", {}, isC ? "Top members at this report" : "Top funds at this report"),
    leaders.length ? leaderTable(leaders, { kind }) : h("p", { class: "empty" }, isC ? "Not enough disclosures to rank members yet." : "Funds need three completed quarters to rank; the 13F ledger starts with filings from Aug 2024."));
}

// ---------------------------------------------------------------- member / fund profiles
const hasProfile = (kind, id) => (META.profiles?.[kind] || []).includes(String(id));
const memberLink = (id, label) => (hasProfile("congress", id) ? h("a", { href: `#/member/${encodeURIComponent(id)}` }, label) : label);
const fundLink = (cik, label) => (hasProfile("hedge", cik) ? h("a", { href: `#/fund/${cik}` }, label) : label);
const dollarRange = (x) => (x && x.count ? h("span", { title: `${x.count} disclosures · ranges sum to ${money(x.lo)}–${money(x.hi)}` }, money(x.mid), h("span", { class: "muted small" }, ` (${x.count})`)) : "—");

function historyChart(fields, rows, label) {
  const f = Object.fromEntries(fields.map((n, i) => [n, i]));
  if (rows.length < 2) return h("p", { class: "muted small" }, "Not enough report dates ranked yet.");
  const holder = h("div");
  lineChart(holder, { dates: rows.map((r) => r[f.report]), height: 200, baseline: 0, format: (v) => `${v.toFixed(0)}%`,
    series: [{ name: label, values: rows.map((r) => (r[f.alpha] == null ? null : r[f.alpha] * 100)), color: css("--series-1") }] });
  return holder;
}

async function memberPage(root, id) {
  const m = await load(`members/${encodeURIComponent(id)}.json`);
  if (!m) return root.appendChild(h("p", { class: "empty" }, "No profile for this member (profiles cover members who have ranked in the top 25)."));
  const now = m.windows.find((w) => w.key === "2y") || m.windows[0];
  root.appendChild(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "muted small" }, h("a", { href: "#/congress" }, "Congress"), " / member"),
    h("h1", {}, m.name), h("p", { class: "lede" }, [m.chamber ? m.chamber[0].toUpperCase() + m.chamber.slice(1) : "", m.party, m.state].filter(Boolean).join(" · ")),
    h("p", { class: "muted small" }, `As of ${fmtDate(m.as_of)} · the disclosure ledger starts ${fmtDate(m.data_start)}`))));
  const tile = (label, value, sub) => h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "delta" }, sub) : null);
  root.appendChild(h("div", { class: "tiles" },
    tile("Rank (2y)", now.rank ? `#${now.rank}` : "—", now.rank ? `of ${now.ranked_of} ranked` : now.lots < 5 ? "needs 5 buys in window" : "unranked"),
    tile("Alpha (2y)", pct(now.alpha, 0, true), `return ${pct(now.return, 0, true)}`),
    tile("Disclosed (2y)", money((now.bought.mid || 0) + (now.sold.mid || 0)), `${now.bought.count} buys ${money(now.bought.mid)} · ${now.sold.count} sales ${money(now.sold.mid)}`),
    tile("All disclosures", `${m.all_disclosures.trades} trades`, `since ${fmtDate(m.data_start)}: buys ${money(m.all_disclosures.buys.mid)} · sales ${money(m.all_disclosures.sales.mid)}`),
    tile("Beat SPY", pct(now.beat_spy, 0), `${now.lots} positions (${now.carried} held from before) · ${now.open_lots} still held`)));
  root.appendChild(h("p", { class: "muted small", style: "max-width:780px" },
    "Alpha copies each disclosed purchase at the close after it was disclosed and keeps it until a sale of that stock is disclosed (or marks it today). Over a window it counts everything held in it: purchases made inside it from purchase, and earlier purchases still owned when it began from its first day, at their value then. Each position's return minus SPY's over the same days is averaged by value (disclosed range midpoints). It is not annualized. Sales of stock bought before the ledger starts (Jun 18, 2024) appear in the disclosures but can't be scored."));
  root.append(h("h2", {}, "By time period"), table([
    { key: "label", label: "Period", nosort: true, render: (w) => [w.label, h("div", { class: "muted small" }, `since ${fmtDate(w.start)}`)] },
    { key: "rank", label: "Rank", num: true, nosort: true, render: (w) => (w.rank ? `#${w.rank} of ${w.ranked_of}` : "—") },
    { key: "alpha", label: "Alpha", num: true, nosort: true, cls: (w) => cls(w.alpha), render: (w) => pct(w.alpha, 0, true) },
    { key: "return", label: "Return", num: true, nosort: true, render: (w) => pct(w.return, 0, true) },
    { key: "beat", label: "Beat SPY", num: true, nosort: true, render: (w) => pct(w.beat_spy, 0) },
    { key: "carried", label: "Positions", num: true, nosort: true, title: "Purchases held in the window (held from before it began)", render: (w) => `${w.lots} (${w.carried} from before)` },
    { key: "bought", label: "Bought", num: true, nosort: true, render: (w) => dollarRange(w.bought) },
    { key: "sold", label: "Sold", num: true, nosort: true, render: (w) => dollarRange(w.sold) },
    { key: "open", label: "Still held", num: true, nosort: true, hideNarrow: true, render: (w) => `${w.open_lots} of ${w.lots}` },
  ], m.windows, { compact: true }));
  root.append(h("h2", {}, "Alpha at each report (2-year window, as ranked)"), h("div", { class: "card" }, historyChart(m.history_fields, m.history, "Alpha")));

  const lf = Object.fromEntries(m.lot_fields.map((n, i) => [n, i]));
  const lots = m.lots.map((r) => ({ ...Object.fromEntries(m.lot_fields.map((n) => [n, r[lf[n]]])), alpha: r[lf.ret] != null && r[lf.spy] != null ? r[lf.ret] - r[lf.spy] : null }));
  root.append(h("h2", {}, `Copied purchases (${lots.length})`), lots.length ? table([
    { key: "disclosed", label: "Disclosed", render: (r) => legDate(r.disclosed) },
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => (r.key ? stockLink(r.key, r.ticker) : r.ticker) },
    { key: "hi", label: "Amount", num: true, render: (r) => amount(r.lo, r.hi) },
    { key: "entry", label: "Bought", hideNarrow: true, render: (r) => legDate(r.entry) },
    { key: "exit", label: "Sold", render: (r) => (r.open ? h("span", { class: "badge new" }, "held") : legDate(r.exit)) },
    { key: "ret", label: "Return", num: true, cls: (r) => cls(r.ret), render: (r) => pct(r.ret, 0, true) },
    { key: "spy", label: "SPY", num: true, hideNarrow: true, render: (r) => pct(r.spy, 0, true) },
    { key: "alpha", label: "Alpha", num: true, cls: (r) => cls(r.alpha), render: (r) => pct(r.alpha, 0, true) },
  ], lots, { sortKey: "disclosed", compact: true }) : h("p", { class: "empty" }, "No priced purchases."));

  const tf = Object.fromEntries(m.trade_fields.map((n, i) => [n, i]));
  const trades = m.trades.map((r) => Object.fromEntries(m.trade_fields.map((n) => [n, r[tf[n]]])));
  root.append(h("h2", {}, `Every disclosed trade (${trades.length})`), table([
    { key: "disclosed", label: "Disclosed", render: (r) => legDate(r.disclosed) },
    { key: "traded", label: "Traded", hideNarrow: true, render: (r) => legDate(r.traded) },
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => (STOCKS.has(r.ticker) ? stockLink(r.ticker) : r.ticker || "—") },
    { key: "asset", label: "Asset", hideNarrow: true, render: (r) => h("span", { class: "muted small" }, (r.asset || "").slice(0, 48)) },
    { key: "type", label: "Type", render: (r) => typeBadge(r.type) },
    { key: "hi", label: "Amount", num: true, render: (r) => amount(r.lo, r.hi) },
    { key: "owner", label: "Owner", hideNarrow: true, render: (r) => r.owner || "" },
  ], trades, { sortKey: "disclosed", compact: true }));
}

async function fundPage(root, cik) {
  const f = await load(`funds/${cik}.json`);
  if (!f) return root.appendChild(h("p", { class: "empty" }, "No profile for this fund (profiles cover funds that have ranked in the top 25)."));
  const now = f.windows.find((w) => w.key === "2y") || f.windows[0];
  root.appendChild(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "muted small" }, h("a", { href: "#/hedge" }, "Hedge funds"), " / fund"),
    h("h1", {}, f.name),
    h("p", { class: "muted small" }, `CIK ${f.cik} · `, h("a", { href: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${f.cik}&type=13F`, target: "_blank", rel: "noopener" }, "EDGAR filings"),
      ` · as of ${fmtDate(f.as_of)} · the 13F ledger starts with filings from ${fmtDate(f.data_start)}`))));
  const tile = (label, value, sub) => h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), sub ? h("div", { class: "delta" }, sub) : null);
  root.appendChild(h("div", { class: "tiles" },
    tile("Rank (2y)", now.rank ? `#${now.rank}` : "—", now.rank ? `of ${now.ranked_of} ranked` : "not eligible now"),
    tile("Alpha (2y)", pct(now.alpha, 0, true), `return ${pct(now.return, 0, true)} vs SPY ${pct(now.spy_return, 0, true)}`),
    tile("13F book", money(f.latest.book), `${f.latest.positions} long positions`),
    tile("Latest filing", quarterOf(f.latest.quarter), `filed ${fmtDate(f.latest.filed)}`),
    tile("Changes", `${f.latest.new} new · ${f.latest.exits} exits`, "vs the previous quarter")));
  root.appendChild(h("p", { class: "muted small", style: "max-width:780px" },
    "Alpha buys each quarterly 13F book (long shares, value-weighted) at the close after it is filed and holds it to the close after the next filing; quarters compound, minus SPY over the same days. Only completed quarters count. Ranking needs 3+ quarters, 90% of the book priced, beating SPY in more than half of quarters, 5–150 positions and a book of at least $100M. The 13F book is the reported market value of long US positions, not total assets."));
  root.append(h("h2", {}, "By time period"), table([
    { key: "label", label: "Period", nosort: true, render: (w) => [w.label, h("div", { class: "muted small" }, `since ${fmtDate(w.start)}`)] },
    { key: "rank", label: "Rank", num: true, nosort: true, render: (w) => (w.rank ? `#${w.rank} of ${w.ranked_of}` : w.periods ? "not eligible" : "—") },
    { key: "alpha", label: "Alpha", num: true, nosort: true, cls: (w) => cls(w.alpha), render: (w) => pct(w.alpha, 0, true) },
    { key: "return", label: "Return", num: true, nosort: true, render: (w) => pct(w.return, 0, true) },
    { key: "spy", label: "SPY", num: true, nosort: true, render: (w) => pct(w.spy_return, 0, true) },
    { key: "periods", label: "Quarters", num: true, nosort: true, render: (w) => w.periods },
    { key: "hit", label: "Beat SPY", num: true, nosort: true, render: (w) => pct(w.hit_rate, 0) },
    { key: "cov", label: "Priced", num: true, nosort: true, hideNarrow: true, render: (w) => pct(w.coverage, 0) },
  ], f.windows, { compact: true }));
  root.append(h("h2", {}, "Alpha at each report (2-year window, as ranked)"), h("div", { class: "card" }, historyChart(f.history_fields, f.history, "Alpha")));

  const qf = Object.fromEntries(f.quarter_fields.map((n, i) => [n, i]));
  const quarters = f.quarters.map((r) => ({ ...Object.fromEntries(f.quarter_fields.map((n) => [n, r[qf[n]]])), excess: r[qf.ret] != null ? r[qf.ret] - r[qf.spy] : null }));
  root.append(h("h2", {}, "Quarterly books"), table([
    { key: "filed", label: "Filed", render: (r) => legDate(r.filed) },
    { key: "quarter", label: "Quarter", render: (r) => quarterOf(r.quarter) },
    { key: "positions", label: "Positions", num: true },
    { key: "book", label: "Book", num: true, render: (r) => [money(r.book), r.gated ? null : h("span", { class: "muted small", title: "Outside the 5–150 positions / $100M gates this quarter" }, " ✕")] },
    { key: "ret", label: "Held-period return", num: true, cls: (r) => cls(r.ret), render: (r) => (r.ret == null ? h("span", { class: "muted small" }, r.exit ? "—" : "in progress") : pct(r.ret, 1, true)) },
    { key: "spy", label: "SPY", num: true, hideNarrow: true, render: (r) => pct(r.spy, 1, true) },
    { key: "excess", label: "vs SPY", num: true, cls: (r) => cls(r.excess), render: (r) => pct(r.excess, 1, true) },
  ], quarters, { sortKey: "filed", compact: true }));

  const hf = Object.fromEntries(f.holding_fields.map((n, i) => [n, i]));
  const holdings = f.holdings.map((r) => Object.fromEntries(f.holding_fields.map((n) => [n, r[hf[n]]])));
  const ef = Object.fromEntries(f.exit_fields.map((n, i) => [n, i]));
  const exits = f.exits.map((r) => Object.fromEntries(f.exit_fields.map((n) => [n, r[ef[n]]])));
  const posTable = (rows, isNew) => table([
    { key: "ticker", label: "Ticker", cls: () => "ticker", render: (r) => [r.key ? stockLink(r.key, r.ticker) : r.ticker || "—", isNew && r.new ? h("span", { class: "badge new", style: "margin-left:6px" }, "new") : null] },
    { key: "issuer", label: "Issuer", hideNarrow: true, render: (r) => h("span", { class: "muted small" }, r.issuer || "") },
    { key: "value", label: "Value", num: true, render: (r) => money(r.value) },
    { key: "weight", label: "% of book", num: true, render: (r) => pct(r.weight, 1) },
  ], rows, { sortKey: "weight", compact: true });
  const grid = h("div", { class: "grid cols-2" });
  grid.append(h("div", { class: "card" }, h("h3", {}, `Latest book · ${quarterOf(f.latest.quarter)} (top ${holdings.length})`), holdings.length ? posTable(holdings, true) : h("p", { class: "empty" }, "No positions.")),
    h("div", { class: "card" }, h("h3", {}, `Exited since the previous quarter (${f.latest.exits})`), exits.length ? posTable(exits, false) : h("p", { class: "empty" }, "No exits.")));
  root.append(h("h2", {}, "Holdings"), grid);
}

async function strategyPage(root, id) {
  const [s, sessions] = await Promise.all([load(`strategies/${id}.json`), load("sessions.json")]);
  if (!s) return root.appendChild(h("p", { class: "empty" }, "Unknown strategy."));
  const cat = catOf(s.category);
  const dates = sessions.slice(s.start, s.start + s.nav.length);
  root.appendChild(h("div", { class: "page-head" },
    h("div", {}, h("div", { class: "muted small" }, s.stage === "lab"
        ? [h("a", { href: "#/lab" }, "Lab"), " / ", h("a", { href: `#/category/${cat.id}` }, cat.name), s.added ? ` · added ${fmtDate(s.added)}` : ""]
        : s.options
        ? [h("a", { href: "#/options" }, "Options"), " / ", h("a", { href: `#/strategy/${s.base}` }, stratName(s.base))]
        : [h("a", { href: "#/strategies" }, "Strategies"), " / ", h("a", { href: `#/category/${cat.id}` }, cat.name)]),
      h("h1", {}, s.name),
      h("p", { class: "lede" }, s.options
        ? `${cat.description} Take the ${s.slot}; ${s.hold}. ${s.instrument} on each holding, opened and closed with the stock (option history only, about 2 years).`
        : `${cat.description} Take the ${s.slot}; ${s.hold}; instrument: ${s.instrument}.`))));
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
    if (s.options) tiles.append(
      tile("Stock, same windows", pct(all.stock_same?.cagr), `Sharpe ${num(all.stock_same?.sharpe)} · DD ${pct(all.stock_same?.max_drawdown, 0)}`),
      tile("Exposure · position", `${num(all.stock_equiv)}× · ${pct(all.position, 0)}`, "stock-equivalent at entry · half-Kelly ÷ exposure"),
      tile("Premium collected", pct(all.premium_yield, 1), "per year of capital deployed"),
      tile("Assigned · called", `${pct(all.assignment_rate, 0)} · ${pct(all.called_away_rate, 0)}`, `options on ${pct(all.option_coverage, 0)} of windows`));

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
    seg([...META.windows, ...(s.metrics.since_added ? ["since_added"] : [])].map((w) => [w, windowLabel(w)]), state.window, (v) => { state.window = v; draw(); }),
    seg([["nav", "Total return"], ["nav_price", "Price only"]], state.basis, (v) => { state.basis = v; draw(); }),
    seg([[true, "Log scale"], [false, "Linear"]], state.log, (v) => { state.log = v; draw(); }));
  draw();

  const f = Object.fromEntries(s.trade_fields.map((n, i) => [n, i]));
  const trades = s.trades.map((t, n) => ({ ...Object.fromEntries(Object.entries(f).map(([k, i]) => [k, t[i]])), n }));
  const legsOf = (t) => (s.legs?.[t.n] || []).map((l) => Object.fromEntries(s.leg_fields.map((k, i) => [k, l[i]])));
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
      ...(s.options ? [{ key: "legs", label: "Legs", nosort: true, render: (t) => legSummary(legsOf(t)) }] : []),
    ], rows, { sortKey: "entry" }));
  };
  root.append(h("h2", {}, `Trades (${trades.length})`),
    h("div", { class: "controls" }, seg([["all", "All"], ["open", "Open"], ["closed", "Closed"]], filter, (v) => { filter = v; drawTrades(); })),
    tradeBox);
  drawTrades();
}

const legDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" }) : "");
const contractLabel = (l) => `${l.side === "short" ? "−" : "+"}${legDate(l.expiry)} ${l.strike}${l.kind}`;

function legSummary(legs) {
  return h("span", { class: "legs" }, legs.map((l) => h("span", {
    class: "chip",
    title: l.kind === "S"
      ? `Shares bought ${l.open} at ${num(l.open_px)}; ${l.reason || "open"} ${l.close || ""} ${l.close_px != null ? "at " + num(l.close_px) : ""}`
      : `${l.side} ${l.kind === "P" ? "put" : "call"} ${l.strike} exp ${l.expiry} · opened ${l.open} at ${num(l.open_px)} (Δ ${num(l.delta)}, IV ${pct(l.iv, 0)}) · ${l.reason || "open"} ${l.close || ""} ${l.close_px != null ? "at " + num(l.close_px) : ""}`,
  }, l.kind === "S" ? "shares" : contractLabel(l), l.reason && l.reason !== "window end" ? h("span", { class: "muted" }, ` ${l.reason}`) : null)));
}

// "Better than the stock" = higher Sharpe over exactly the same windows; within ±0.05 counts as a tie.
const SHARPE_TIE = 0.05;
const TIERS = ["Defensive", "Balanced", "Aggressive"];

function vsStock(mm, stock) {
  const out = [];
  if (mm.sharpe != null && stock.sharpe != null) {
    const d = mm.sharpe - stock.sharpe;
    out.push(d >= SHARPE_TIE ? ["up", "Higher Sharpe"] : d <= -SHARPE_TIE ? ["down", "Lower Sharpe"] : ["flat", "Sharpe ≈ stock"]);
  }
  if (mm.cagr != null && stock.cagr != null && mm.cagr > stock.cagr) out.push(["up", "More return"]);
  if (mm.max_drawdown != null && stock.max_drawdown != null && mm.max_drawdown - stock.max_drawdown >= 0.05) out.push(["up", "Smaller drop"]);
  return out;
}
const beatsStock = (mm, stock) => mm.sharpe != null && stock.sharpe != null && mm.sharpe - stock.sharpe >= SHARPE_TIE;
const badges = (list) => h("span", { class: "vs" }, list.map(([c, t]) => h("span", { class: `badge ${c}` }, t)));

// Takeaways from the option method grid run of 2026-10-09 (docs/options_grid.md, all 25 methods × 4 strategies).
const OPTION_PATTERNS = [
  ["12-month calls at Δ0.60 are the best way to add return.", " On S&P 500 Leaders, 50% of capital in them made 166% a year at Sharpe 1.49 (stock 101%, 1.23) with about the stock's worst drop; 100% in them made 365% at Sharpe 1.54 but fell 57%. Rank Momentum shows the same at a smaller margin."],
  ["Cash-secured puts at Δ−0.20 are the low-risk way in.", " Worst drops of 10–20% against the stock's 39–44%, and a higher Sharpe on all three momentum strategies (1.80 vs 1.14 on Rank Momentum) — but only about a third of the stock's return."],
  ["Covered calls never beat the stock.", " At ~21 days and Δ0.10–0.50 they at best tie its Sharpe. Momentum profits come from a few names that run hard, which is exactly the upside a call sells; on Megacap Laggards (no big runs) Δ0.10 ties at 1.50 vs 1.51. None are tracked."],
  ["Six-month calls with all capital in them look biggest and are worst.", " 266–534% a year, but Sharpe below the stock on three of four strategies and worst drops of 69–80%. Not tracked."],
  ["Megacap Leaders is weak whatever the method.", " The stock version's Sharpe is 0.82; the best option method reaches 0.97. Options don't fix a weak signal."],
  ["On Megacap Laggards nothing beats the stock by much.", " Its stock Sharpe is already 1.51. The diagonal ties it while cutting the worst drop from 19% to 14%; calls add return at a lower Sharpe."],
  ["Leverage doesn't move half-Kelly; position size does.", " Win rate and payoff hardly change when every win and loss is scaled up, so half-Kelly stays near the stock's. Divide by exposure: 100% in 12-month calls (≈2.6× the stock) sizes at about 7% of a portfolio per position, against 16% for the stock."],
];
const OPTION_CAVEATS = "Two years of option history in a strong market; fills at the traded price with no spread, which flatters the leveraged methods most; for 24–28% of S&P 500 holdings no 12-month call with a traded strike near the target delta existed, and those holdings held the stock.";

async function optionsPage(root) {
  const data = await load("options.json");
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Options"),
    h("p", { class: "lede" }, "Three tracked option methods for each of four strategies — one defensive, one balanced, one aggressive — each run on the strategy's own entries and exits and compared with holding the stock over exactly the same windows. Option history starts ",
      data ? fmtDate(data.first_session) : "—", ".")),
  ));
  if (!data || !data.bases?.length) return root.appendChild(h("p", { class: "empty" }, "No option results yet."));
  const sessions = await load("sessions.json");
  const all = (r) => r.metrics?.all || {};

  // ---- summary: every tracked method against its stock
  const summary = h("div", { class: "opt-summary" });
  for (const base of data.bases) {
    const stock = base.stock_same.all || {};
    const cell = (title, label, mm, extra, beat) => h("div", { class: `opt-cell${beat ? " beats" : ""}` },
      h("div", { class: "muted small" }, title), h("div", { class: "opt-label" }, label),
      h("div", { class: "opt-nums" }, `${pct(mm.cagr, 0)} / yr · Sharpe ${num(mm.sharpe)} · worst ${pct(mm.max_drawdown, 0)}`),
      h("div", { class: "muted small" }, `½-Kelly ${pct(mm.half_kelly, 0)} · position ${pct(mm.position, 0)}`), extra);
    const methods = TIERS.map((t) => base.methods.find((x) => x.tier === t)).filter(Boolean);
    summary.append(h("div", { class: "opt-row" },
      h("div", { class: "opt-name" }, h("a", { href: `#/strategy/${base.id}` }, base.name)),
      cell("Stock, same windows", "Stock", stock, null, false),
      ...methods.map((x) => cell(x.tier, h("a", { href: `#/strategy/${x.id}` }, x.label), all(x), badges(vsStock(all(x), stock)), beatsStock(all(x), stock)))));
  }
  root.append(h("h2", {}, "Tracked methods vs the stock"),
    h("p", { class: "muted small", style: "max-width:780px" }, "Highlighted = a higher Sharpe than the stock over the same windows (by 0.05 or more), i.e. better risk-adjusted. Badges also flag more total return and a worst drop at least 5 points smaller."),
    summary);

  // ---- patterns
  root.append(h("h2", {}, "Patterns"),
    h("p", { class: "muted small" }, "From the full method grid (25 methods × 4 strategies) run on Oct 9, 2026; numbers are that run's two-year results. Re-run with python -m market.evaluate.option_grid."),
    h("ul", { class: "patterns" }, OPTION_PATTERNS.map(([lead, rest]) => h("li", {}, h("strong", {}, lead), rest))),
    h("p", { class: "muted small", style: "max-width:780px" }, h("strong", {}, "Caveats. "), OPTION_CAVEATS));

  // ---- how to read
  root.append(h("details", { class: "opt-help" }, h("summary", {}, "How to read sizing, exposure and position"),
    h("p", {}, "For $10,000 and a $100 stock: the stock is 100 shares. ", h("strong", {}, "Match stock"), " buys enough calls to move like 100 shares (at Δ0.60, 167 shares' worth, about $2,500) and keeps the rest in T-bills. ",
      h("strong", {}, "50% in calls"), " spends $5,000 on calls (moves like ~200 shares); ", h("strong", {}, "100% in calls"), " spends all $10,000 (~400 shares) and can lose it all."),
    h("p", {}, h("strong", {}, "Exposure"), " is how much stock a position moves like per dollar at entry (1.0× = the stock; a Δ−0.20 put ≈ 0.22×). ",
      h("strong", {}, "Half-Kelly"), " is the site's 0.5 × (p − q/b) on closed trades. ", h("strong", {}, "Position"), " = half-Kelly ÷ exposure (capped at 100%): the share of a portfolio per position once leverage is counted."),
    h("p", {}, "Cash-secured puts use any expiry 14–21 days out (30–45 for Megacap Laggards); diagonal short calls the expiry nearest 21 days; 6m / 12m calls the first expiry at least 180 / 365 days out with a traded strike within ±0.05 of the target delta, preferring the most-traded strike. Contracts are chosen on the report's as-of close and filled at the next session's traded price (mid of open and close). Every leg closes the session the stock would exit; cash earns 4%.")));

  // ---- per base
  for (const base of data.bases) {
    const section = h("section", { class: "options-base" });
    root.appendChild(section);
    const stock = base.stock_same.all || {};
    let pick = base.methods[0].method;
    const dates = sessions.slice(base.start, base.start + base.series.SPY.length);
    const chartBox = h("div", { class: "card" });
    const picksBox = h("div");
    const stockRow = { id: `${base.id}.stock_same`, label: "Stock (same windows)", stock: true, tier: "", metrics: { all: stock } };
    const rows = [stockRow, ...base.methods];
    const m = all;
    const cols = [
      { key: "tier", label: "Tier", sort: (r) => (r.stock ? -1 : TIERS.indexOf(r.tier)), render: (r) => r.tier || "" },
      { key: "label", label: "Method", sort: (r) => r.label, cls: () => "name-col", render: (r) => r.stock ? h("a", { href: `#/strategy/${base.id}` }, r.label) : h("a", { href: `#/strategy/${r.id}` }, r.label) },
      { key: "cagr", label: "CAGR", num: true, sort: (r) => m(r).cagr, cls: (r) => cls(m(r).cagr), render: (r) => pct(m(r).cagr) },
      { key: "total", label: "Total", num: true, hideNarrow: true, sort: (r) => m(r).total_return, render: (r) => pct(m(r).total_return, 0) },
      { key: "sharpe", label: "Sharpe", num: true, sort: (r) => m(r).sharpe, render: (r) => num(m(r).sharpe) },
      { key: "dd", label: "Max DD", num: true, sort: (r) => m(r).max_drawdown, render: (r) => pct(m(r).max_drawdown, 0) },
      { key: "vol", label: "Vol", num: true, hideNarrow: true, sort: (r) => m(r).volatility, render: (r) => pct(m(r).volatility, 0) },
      { key: "win", label: "Win %", num: true, hideNarrow: true, sort: (r) => m(r).win_rate, render: (r) => pct(m(r).win_rate, 0) },
      { key: "hk", label: "½-Kelly", num: true, sort: (r) => m(r).half_kelly, render: (r) => pct(m(r).half_kelly, 0) },
      { key: "exp", label: "Exposure", num: true, title: "Stock-equivalent exposure at entry (1.0× = the stock)", sort: (r) => m(r).stock_equiv, render: (r) => (m(r).stock_equiv == null ? "—" : `${num(m(r).stock_equiv)}×`) },
      { key: "pos", label: "Position", num: true, title: "Half-Kelly ÷ exposure, capped at 100%", sort: (r) => m(r).position, render: (r) => pct(m(r).position, 0) },
      { key: "vs", label: "vs stock", nosort: true, render: (r) => (r.stock ? "" : badges(vsStock(m(r), stock))) },
    ];
    section.append(h("h2", {}, h("a", { href: `#/strategy/${base.id}` }, base.name)),
      h("p", { class: "muted small" }, `${base.hold} · ${m(base.methods[0]).windows ?? "—"} windows`),
      table(cols, rows, { sortKey: "tier", desc: false, rowClass: (r) => (r.stock ? "bench" : beatsStock(m(r), stock) ? "beats" : null), compact: true }));
    const controls = h("div", { class: "controls" });
    section.append(controls, chartBox, h("h3", {}, "If opened today"), picksBox);

    const draw = () => {
      const method = base.methods.find((x) => x.method === pick);
      chartBox.textContent = "";
      chartBox.appendChild(h("h3", {}, `Growth of 100 · ${method.label} vs stock, same windows`));
      const holder = h("div");
      chartBox.appendChild(holder);
      lineChart(holder, { dates, height: 260, baseline: 100, log: state.log, format: (v) => v.toFixed(0), series: [
        { name: method.label, values: base.series[method.id], color: css("--series-1") },
        { name: "Stock", values: base.series[`${base.id}.stock_same`], color: css("--series-2") },
        { name: "SPY", values: base.series.SPY, color: css("--series-3") }] });
      picksBox.textContent = "";
      const picks = base.picks.filter((p) => p.method === pick);
      if (!picks.length) { picksBox.appendChild(h("p", { class: "muted small" }, "No current holdings.")); return; }
      const legCell = (p, side) => { const l = p.legs.find((x) => x.side === side); return l ? (l.missing ? h("span", { class: "muted" }, side === "long" ? "no liquid contract (holds the stock)" : "no liquid contract (cash)") : contractLabel(l)) : ""; };
      const val = (p, side, k) => p.legs.find((x) => x.side === side && !x.missing)?.[k];
      const isLong = method.instrument === "leap" || method.instrument === "diagonal";
      const isShort = method.instrument !== "leap";
      picksBox.appendChild(table([
        { key: "ticker", label: "Ticker", cls: () => "ticker", render: (p) => stockLink(p.ticker) },
        { key: "spot", label: "Price", num: true, render: (p) => num(p.spot) },
        ...(isLong ? [
          { key: "long", label: "Long call", nosort: true, render: (p) => legCell(p, "long") },
          { key: "ldte", label: "DTE", num: true, sort: (p) => val(p, "long", "dte"), render: (p) => val(p, "long", "dte") ?? "" },
          { key: "ldelta", label: "Δ", num: true, sort: (p) => val(p, "long", "delta"), render: (p) => num(val(p, "long", "delta")) },
          { key: "lcost", label: "Cost / price", num: true, sort: (p) => val(p, "long", "cost_pct"), render: (p) => pct(val(p, "long", "cost_pct"), 0) },
          { key: "lext", label: "Time value", num: true, hideNarrow: true, title: "Extrinsic value as a share of the stock price", sort: (p) => val(p, "long", "extrinsic_pct"), render: (p) => pct(val(p, "long", "extrinsic_pct"), 1) },
          { key: "lexp", label: "Exposure", num: true, title: "Stock-equivalent exposure of this sizing", sort: (p) => val(p, "long", "exposure"), render: (p) => (val(p, "long", "exposure") == null ? "" : `${num(val(p, "long", "exposure"))}×`) },
        ] : []),
        ...(isShort ? [
          { key: "short", label: method.instrument === "csp" ? "Short put" : "Short call", nosort: true, render: (p) => legCell(p, "short") },
          { key: "sdte", label: "DTE", num: true, sort: (p) => val(p, "short", "dte"), render: (p) => val(p, "short", "dte") ?? "" },
          { key: "prem", label: "Premium", num: true, sort: (p) => val(p, "short", "premium"), render: (p) => num(val(p, "short", "premium")) },
          { key: "delta", label: "Δ", num: true, sort: (p) => val(p, "short", "delta"), render: (p) => num(val(p, "short", "delta")) },
          { key: "iv", label: "IV", num: true, hideNarrow: true, sort: (p) => val(p, "short", "iv"), render: (p) => pct(val(p, "short", "iv"), 0) },
          { key: "yield", label: "Yield / yr", num: true, sort: (p) => val(p, "short", "yield_annual"), render: (p) => pct(val(p, "short", "yield_annual"), 0) },
          method.instrument === "csp"
            ? { key: "be", label: "Breakeven", num: true, title: "Strike minus premium, vs today's price", sort: (p) => val(p, "short", "breakeven_pct"), render: (p) => pct(val(p, "short", "breakeven_pct"), 1, true) }
            : { key: "cap", label: "Upside cap", num: true, title: "Strike vs today's price", sort: (p) => val(p, "short", "cap_pct"), render: (p) => pct(val(p, "short", "cap_pct"), 1, true) },
        ] : []),
      ], picks, { sortKey: "ticker", desc: false, compact: true }));
      picksBox.appendChild(h("p", { class: "muted small" }, `From the ${fmtDate(base.picks_as_of)} option close; delayed data, not a quote.`));
    };
    controls.append(seg(base.methods.map((x) => [x.method, `${x.tier}: ${x.label.replace("Cash-secured put", "Put")}`]), pick, (v) => { pick = v; draw(); }));
    draw();
  }
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
    h("div", { class: "muted small" }, h("a", { href: cat.stage === "lab" ? "#/lab" : "#/categories" }, cat.stage === "lab" ? "Lab" : "Categories"), " / ", cat.group),
    h("h1", {}, cat.name), h("p", { class: "lede" }, cat.description),
    h("p", { class: "muted small" }, `${cat.reports} reports since ${fmtDate(cat.first)} · universe ${cat.universe}`),
    leadTimeLine(cat))));
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

  const strategies = META.all.strategies.filter((s) => s.category === id && !s.options);
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
    h("p", { class: "lede" }, "Ranked lists computed for every report date from point-in-time data. Options methods come next."))));
  const groups = [...new Set(META.categories.map((c) => c.group))];
  for (const g of groups) {
    root.appendChild(h("h2", {}, g));
    const grid = h("div", { class: "grid cols-2" });
    for (const c of META.categories.filter((x) => x.group === g)) {
      const strategies = META.strategies.filter((s) => s.category === c.id && !s.options);
      grid.appendChild(h("div", { class: "card" }, h("h3", {}, h("a", { href: `#/category/${c.id}` }, c.name)),
        h("p", { class: "ink2", style: "margin:0 0 8px" }, c.description),
        h("div", { class: "muted small" }, `${c.reports} reports · since ${fmtDate(c.first)} · ${strategies.length} strategies`)));
    }
    root.appendChild(grid);
  }
}

async function stockPage(root, key) {
  const [s, sessions] = await Promise.all([load(`stocks/${encodeURIComponent(key)}.json`), load("sessions.json")]);
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
  lineChart(holder, { dates, series: [{ name: s.ticker, values: s.close, color: css("--series-1") }], height: 300, markers, format: (v) => (v > 0 && v < 10 ? v.toFixed(2) : v.toFixed(0)) });

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

  root.appendChild(h("h2", {}, "Smart money"));
  const grid = h("div", { class: "grid cols-2" });
  root.appendChild(grid);
  grid.appendChild(h("div", { class: "card" }, h("h3", {}, `Congress trades (${s.congress.length})`),
    s.congress.length ? table([
      { key: "disclosed", label: "Disclosed", render: (t) => fmtDate(t.disclosed) },
      { key: "member", label: "Member", render: (t) => [memberLink(t.member_id, t.member), t.top ? h("span", { class: "badge new", style: "margin-left:6px", title: "Top 10 by follow-the-disclosure alpha today" }, "top 10") : null] },
      { key: "type", label: "Type", render: (t) => h("span", { class: `badge ${t.type === "buy" ? "up" : t.type === "sell" ? "down" : "flat"}` }, t.type) },
      { key: "amount_hi", label: "Amount", num: true, render: (t) => amount(t.amount_lo, t.amount_hi) },
    ], s.congress, { sortKey: "disclosed", compact: true }) : h("p", { class: "empty" }, "No disclosed trades in the ledger.")));
  grid.appendChild(h("div", { class: "card" }, h("h3", {}, `Held by top-200 13F funds (${s.n_funds || 0})`),
    s.funds?.length ? table([
      { key: "rank", label: "#", num: true },
      { key: "name", label: "Fund", render: (r) => [fundLink(r.cik, r.name), r.new ? h("span", { class: "badge new", style: "margin-left:6px", title: `New in the filing of ${fmtDate(r.filed)}` }, "new") : null] },
      { key: "alpha", label: "Fund alpha", num: true, cls: (r) => cls(r.alpha), render: (r) => pct(r.alpha, 0, true) },
      { key: "weight", label: "% of book", num: true, render: (r) => pct(r.weight, 1) },
      { key: "value", label: "Value", num: true, hideNarrow: true, render: (r) => money(r.value) },
    ], s.funds, { sortKey: "rank", desc: false, compact: true }) : h("p", { class: "empty" }, "Not in the latest books of today's top-ranked funds.")));
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
    h("h2", {}, "Rank Momentum"),
    p("Every index member is ranked on its 3-, 6- and 12-month return (1 = best); the list is the best average rank, ties to the stronger 12-month return. Fast Rank Momentum is the same on 1-, 3- and 6-month returns, ties to the stronger 6-month return."),
    h("h2", {}, "Isolated stall"),
    p("S&P 500 Leaders, Isolated Stall is S&P 500 Leaders with momentum10's stall rule applied: a leader whose highest close of the last 60 sessions is more than 15 sessions old has stalled. When at most 3 of the top 10 S&P 500 names by 12-month return have stalled, the stall is isolated and stalled leaders are skipped, so the next unstalled leader takes the slot (a held one exits). When more have stalled it is a broad pullback and the list is unchanged."),
    h("h2", {}, "Reasonable Growth Leaders"),
    p("Index members ranked by 12-month return, keeping only those whose 14-day RSI (Wilder) is above 20 and below 80 on the report's as-of close, which skips names that are short-term overbought or oversold. No rank-improvement filter."),
    h("h2", {}, "Options"),
    p("Option methods run on a select set of names: the stocks entering the S&P 500 Leaders, S&P 500 Rank Momentum and Megacap Leaders top 5 and the Megacap Laggards top 2, plus option watchlists. Day bars come from the OPRA flat files (no quotes or open interest), kept only around the periods a name is held and inside strike/expiry bands. Each method reuses the stock strategy's windows; contracts are chosen by Black-Scholes delta on the report's as-of close and filled the next session at the traded price, mid(open, close), with no spread haircut (the plan has no bid/ask history). A held contract with no trade that day is valued at its last implied volatility. Three methods are tracked per strategy, chosen from a grid of 25 (docs/options_grid.md)."),
    p("Cash-secured puts: collateral is the strike; an expiring out-of-the-money put is replaced the next session; an assigned put's shares are held until the name leaves the list. Covered calls: shares plus calls on all of them; called-away shares are re-bought the next session. Long calls (6m / 12m): the first expiry at least 180 / 365 days out with a traded strike within ±0.05 of the target delta (the most-traded one), sized to move like the stock (match stock) or with 50% / 100% of capital in calls, the rest in T-bills; rolled at the window's value below 120 / 180 DTE. If no call qualifies the holding keeps the stock until one does. Diagonal: a 6m Δ0.80 call matched to the stock plus a ~21-day short call on the same shares, settled at intrinsic if in the money at expiry. A split closes everything the session before and reopens after."),
    h("h2", {}, "Congress"),
    p("Periodic Transaction Reports (House Clerk and Senate eFD, including OCR'd paper filings) are checked daily. A member's skill is measured point-in-time over the trailing two years of disclosures: each purchase is bought at the close of the first session after it was disclosed and sold the session after the member discloses a sale of that name; open lots are marked at the report date. Dollar-weighted (range midpoint) alpha vs SPY; at least 5 purchases to rank."),
    p("Top-5 Buys: purchases disclosed in the last 120 days by the five best-ranked members, scored by each name's share of a member's recent buying, summed across members. Top-5 Holdings: names those members still hold (no sale disclosed), scored by share of each member's open book."),
    h("h2", {}, "Hedge funds (13F)"),
    p("13F-HR filings are checked daily against EDGAR's daily index. Each fund's quarterly book (its first 13F-HR for the quarter; amendments ignored; long shares only) is bought the session after it is filed and held to the session after the next filing, value-weighted. Funds rank point-in-time on completed quarters only: at least 3 quarters, ≥ 90% of book priced, beating SPY in more than half of quarters, positive alpha, 5–150 positions, ≥ $100M, no passive giants. The top 200 are the skilled set."),
    p("Skilled-Fund Buys: positions new in a top fund's latest book (filed in the last 135 days), scored Σ fund alpha × hit rate × position weight. Alpha Drivers: names whose holding-period returns contributed most to the top funds' alpha, among names they still hold. History starts mid-2025: the 13F ledger begins with the August 2024 filings, and funds need three completed quarters to rank."),
    p("Both feeds are read from the smartmoney ledgers (fetching still runs through its code); every score here is recomputed point-in-time from the raw filings."));
}

// ------------------------------------------------------------------ lab
/** Lab categories and strategies (new, on trial) are kept off every other list; META.all has everything. */
function splitLab(meta) {
  meta.all = { categories: meta.categories, strategies: meta.strategies };
  const labCats = new Set(meta.categories.filter((c) => c.stage === "lab").map((c) => c.id));
  const isLab = (s) => s.stage === "lab" || labCats.has(s.category);
  meta.lab = { categories: meta.categories.filter((c) => labCats.has(c.id)), strategies: meta.strategies.filter(isLab) };
  meta.categories = meta.categories.filter((c) => !labCats.has(c.id));
  meta.strategies = meta.strategies.filter((s) => !isLab(s));
}

function leadTimeLine(cat) {
  const lt = cat.lead_time;
  if (!lt) return null;
  return h("p", { class: "muted small", title: "An entry leads if the name was not a Leaders top-10 name in the prior 30 days and joins within a year." },
    `Lead time: ${pct(lt.became_leader, 0)} of ${lt.entries} entries later joined ${catOf(lt.leaders)?.name || lt.leaders} top 10`,
    lt.median_lead_days != null ? ` (median ${lt.median_lead_days} days later)` : "", `; ${pct(lt.already_leader, 0)} were already there.`);
}

async function labPage(root) {
  root.appendChild(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Lab"),
    h("p", { class: "lede" }, "New categories and methods on trial. Each runs with the same evaluation as everything else; its rules are frozen on the date it was added, so results since then are out of sample. Promoted, edited or retired at each quarterly review."))));
  const rows = META.lab.strategies;
  if (!rows.length) {
    root.appendChild(h("p", { class: "empty" }, "Nothing on trial yet. New signal families (docs/PLAN-signals.md) appear here as they are built."));
  } else {
    const added = (s) => s.metrics.since_added || {};
    const days = (s) => (s.added ? Math.round((new Date(META.data_through) - new Date(s.added)) / 864e5) : null);
    root.appendChild(table([
      { key: "name", label: "Strategy", sort: (r) => r.name, cls: () => "name-col", render: (r) => h("a", { href: `#/strategy/${r.id}` }, r.name) },
      { key: "added", label: "Added", sort: (r) => r.added, render: (r) => (r.added ? fmtDate(r.added) : "—") },
      { key: "cagr", label: "Backtest CAGR", num: true, sort: (r) => r.metrics.all?.cagr, cls: (r) => cls(r.metrics.all?.excess_cagr), render: (r) => pct(r.metrics.all?.cagr) },
      { key: "sharpe", label: "Sharpe", num: true, sort: (r) => r.metrics.all?.sharpe, render: (r) => num(r.metrics.all?.sharpe) },
      { key: "dd", label: "Max DD", num: true, sort: (r) => r.metrics.all?.max_drawdown, render: (r) => pct(r.metrics.all?.max_drawdown, 0) },
      { key: "since", label: "Since added", num: true, title: "Total return since the added date (out of sample)", sort: (r) => added(r).total_return, cls: (r) => cls(added(r).total_return), render: (r) => pct(added(r).total_return, 1) },
      { key: "since_spy", label: "SPY same", num: true, sort: (r) => added(r).benchmark_total_return, render: (r) => pct(added(r).benchmark_total_return, 1) },
      { key: "days", label: "Days", num: true, title: "Calendar days on trial", sort: days, render: (r) => days(r) ?? "—" },
      { key: "hold", label: "Holding now", nosort: true, cls: () => "nowrap", render: (r) => h("span", {}, (r.holdings || []).slice(0, 6).map((k) => h("span", { class: "chip link" }, stockLink(k)))) },
    ], rows, { sortKey: "cagr" }));
  }
  if (META.lab.categories.length) {
    root.appendChild(h("h2", {}, "Lab categories"));
    const grid = h("div", { class: "grid cols-2" });
    root.appendChild(grid);
    for (const cat of META.lab.categories) {
      const data = await categoryData(cat.id);
      const report = reportWithDiff(data, data.dates[data.dates.length - 1]);
      grid.appendChild(h("div", { class: "card report-card" },
        h("h3", {}, h("a", { href: `#/category/${cat.id}` }, cat.name), h("span", { class: "muted small" }, cat.group)),
        h("p", { class: "ink2 small", style: "margin:0 0 8px" }, cat.description),
        report ? reportTable(cat, report, { compact: true, limit: 10 }) : h("p", { class: "empty" }, "No report yet."),
        leadTimeLine(cat)));
    }
  }
}

// ------------------------------------------------------------------ shell
const NAV = [["#/", "Overview"], ["#/reports", "Reports"], ["#/strategies", "Strategies"], ["#/options", "Options"], ["#/lab", "Lab"], ["#/categories", "Categories"], ["#/congress", "Congress"], ["#/hedge", "Hedge funds"], ["#/stocks", "Stocks"], ["#/methodology", "Methodology"]];

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
      || (target === "strategies" && page === "strategy" && META.strategies.find((x) => x.id === a) && !META.strategies.find((x) => x.id === a).options)
      || (target === "options" && page === "strategy" && META.strategies.find((x) => x.id === a)?.options)
      || (target === "lab" && ((page === "strategy" && META.lab.strategies.some((x) => x.id === a)) || (page === "category" && META.lab.categories.some((x) => x.id === a))))
      || (target === "categories" && page === "category" && !META.lab.categories.some((x) => x.id === a)) || (target === "stocks" && page === "stock") || (target === "congress" && page === "member") || (target === "hedge" && page === "fund"));
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
    else if (page === "options") await optionsPage(root);
    else if (page === "lab") await labPage(root);
    else if (page === "categories") await categoriesPage(root);
    else if (page === "category") await categoryPage(root, a);
    else if (page === "stocks") await stocksPage(root);
    else if (page === "stock") await stockPage(root, a);
    else if (page === "congress") await smartPage(root, "congress", a);
    else if (page === "hedge") await smartPage(root, "hedge", a);
    else if (page === "member") await memberPage(root, a);
    else if (page === "fund") await fundPage(root, a);
    else if (page === "smart-money") location.hash = "#/congress";
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
  splitLab(META);
  STOCKS = new Set(META.stocks.map((s) => s[0]));
  navEl = shell();
  document.querySelector("footer").textContent = `Generated ${META.generated_at.replace("T", " ")} · data through ${fmtDate(META.data_through)} · research tool, not investment advice`;
  window.addEventListener("hashchange", route);
  route();
})();
