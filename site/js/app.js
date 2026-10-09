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
    const rows = META.strategies.filter((s) => s.visible).map((s) => ({ ...s, m: s.metrics[w] || {} }));
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
  for (const [d, id, rank, score] of ranks) {
    if (!m.has(d)) m.set(d, new Map());
    m.get(d).set(id, { rank, score });
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
    { key: "member", label: "Member", sort: (r) => ranks.get(r.member)?.rank ?? 999, render: (r) => [c.members[r.member]?.[0] || r.member, " ", rankBadge(ranks.get(r.member)?.rank, "Rank by follow-the-disclosure alpha at this report")] },
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
    { key: "rank", label: "Fund", sort: (r) => r.rank ?? 999, cls: () => "name-col", render: (r) => [d.funds[r.cik] || r.cik, " ", rankBadge(r.rank, "Rank by follow-the-filing alpha when this filing was reported")] },
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
    { key: "name", label: kind === "congress" ? "Member" : "Fund", cls: () => "name-col", render: (r) => [r.name, r.detail ? h("span", { class: "muted small" }, ` ${r.detail}`) : null] },
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
      ? [["Lots", L.lots, L.lots], ["Return", pct(L.return, 0, true), L.return], ["Beat SPY", pct(L.beat_spy, 0), L.beat_spy]]
      : [["Qtrs", L.periods, L.periods], ["Return", pct(L.return, 0, true), L.return], ["Beat SPY", pct(L.hit_rate, 0), L.hit_rate], ["Book", money(L.book), L.book]];
    return { rank: v.rank, score: v.score, name, detail, prev: prev ? prev.get(id)?.rank ?? null : v.rank, extra };
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
      ? "Periodic Transaction Reports from the House and Senate, bucketed into the Tuesday/Friday report dates by disclosure date. Members are ranked point-in-time: copy each disclosed purchase at the next close, hold until a sale is disclosed, dollar-weighted alpha vs SPY over the trailing two years."
      : "13F-HR filings, bucketed into the Tuesday/Friday report dates by filing date. Funds are ranked point-in-time by follow-the-filing alpha: buy each disclosed book the session after it is filed, hold to the next filing, value-weighted, vs SPY, completed quarters only."),
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
    h("p", { class: "lede" }, "Ranked lists computed for every report date from point-in-time data. Options methods come next."))));
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
      { key: "member", label: "Member", render: (t) => [t.member, t.top ? h("span", { class: "badge new", style: "margin-left:6px", title: "Top 10 by follow-the-disclosure alpha today" }, "top 10") : null] },
      { key: "type", label: "Type", render: (t) => h("span", { class: `badge ${t.type === "buy" ? "up" : t.type === "sell" ? "down" : "flat"}` }, t.type) },
      { key: "amount_hi", label: "Amount", num: true, render: (t) => amount(t.amount_lo, t.amount_hi) },
    ], s.congress, { sortKey: "disclosed", compact: true }) : h("p", { class: "empty" }, "No disclosed trades in the ledger.")));
  grid.appendChild(h("div", { class: "card" }, h("h3", {}, `Held by top-200 13F funds (${s.n_funds || 0})`),
    s.funds?.length ? table([
      { key: "rank", label: "#", num: true },
      { key: "name", label: "Fund", render: (r) => [r.name, r.new ? h("span", { class: "badge new", style: "margin-left:6px", title: `New in the filing of ${fmtDate(r.filed)}` }, "new") : null] },
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
    p("Every index member is ranked on its 3-, 6- and 12-month return (1 = best); the list is the best average rank, ties to the stronger 12-month return."),
    h("h2", {}, "Congress"),
    p("Periodic Transaction Reports (House Clerk and Senate eFD, including OCR'd paper filings) are checked daily. A member's skill is measured point-in-time over the trailing two years of disclosures: each purchase is bought at the close of the first session after it was disclosed and sold the session after the member discloses a sale of that name; open lots are marked at the report date. Dollar-weighted (range midpoint) alpha vs SPY; at least 5 purchases to rank."),
    p("Top-5 Buys: purchases disclosed in the last 120 days by the five best-ranked members, scored by each name's share of a member's recent buying, summed across members. Top-5 Holdings: names those members still hold (no sale disclosed), scored by share of each member's open book."),
    h("h2", {}, "Hedge funds (13F)"),
    p("13F-HR filings are checked daily against EDGAR's daily index. Each fund's quarterly book (its first 13F-HR for the quarter; amendments ignored; long shares only) is bought the session after it is filed and held to the session after the next filing, value-weighted. Funds rank point-in-time on completed quarters only: at least 3 quarters, ≥ 90% of book priced, beating SPY in more than half of quarters, positive alpha, 5–150 positions, ≥ $100M, no passive giants. The top 200 are the skilled set."),
    p("Skilled-Fund Buys: positions new in a top fund's latest book (filed in the last 135 days), scored Σ fund alpha × hit rate × position weight. Alpha Drivers: names whose holding-period returns contributed most to the top funds' alpha, among names they still hold. History starts mid-2025: the 13F ledger begins with the August 2024 filings, and funds need three completed quarters to rank."),
    p("Both feeds are read from the smartmoney ledgers (fetching still runs through its code); every score here is recomputed point-in-time from the raw filings."));
}

// ------------------------------------------------------------------ shell
const NAV = [["#/", "Overview"], ["#/reports", "Reports"], ["#/strategies", "Strategies"], ["#/categories", "Categories"], ["#/congress", "Congress"], ["#/hedge", "Hedge funds"], ["#/stocks", "Stocks"], ["#/methodology", "Methodology"]];

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
    else if (page === "congress") await smartPage(root, "congress", a);
    else if (page === "hedge") await smartPage(root, "hedge", a);
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
  STOCKS = new Set(META.stocks.map((s) => s[0]));
  navEl = shell();
  document.querySelector("footer").textContent = `Generated ${META.generated_at.replace("T", " ")} · data through ${fmtDate(META.data_through)} · research tool, not investment advice`;
  window.addEventListener("hashchange", route);
  route();
})();
