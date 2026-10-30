// Small SVG line chart with crosshair + tooltip (one y-axis, ≤3 series), and sparklines.
// Labels are inserted with textContent only (data is untrusted).

const NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function niceTicks(min, max, count = 5) {
  const span = max - min || Math.abs(max) || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

function dateTicks(dates, width) {
  const n = Math.max(2, Math.min(8, Math.floor(width / 110)));
  const out = [];
  for (let i = 0; i < n; i++) out.push(Math.round((i * (dates.length - 1)) / (n - 1)));
  return [...new Set(out)];
}

function fmtDate(d, long = false) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString(undefined, long ? { year: "numeric", month: "short", day: "numeric" } : { year: "2-digit", month: "short" });
}

/**
 * lineChart(container, {dates, series:[{name, values, color}], height, format, baseline, area, markers})
 * values align with dates (null = gap). Returns {destroy}.
 */
export function lineChart(container, opts) {
  const { dates, series, height = 300, format = (v) => v.toFixed(1), baseline = null, area = false, markers = [], log = false } = opts;
  container.textContent = "";
  container.classList.add("chart");

  if (series.length > 1) {
    const legend = document.createElement("div");
    legend.className = "legend";
    for (const s of series) {
      const item = document.createElement("span");
      item.className = "item";
      const key = document.createElement("span");
      key.className = "key";
      key.style.background = s.color;
      const name = document.createElement("span");
      name.textContent = s.name;
      item.append(key, name);
      legend.appendChild(item);
    }
    container.appendChild(legend);
  }

  const holder = document.createElement("div");
  holder.style.position = "relative";
  container.appendChild(holder);
  const tip = document.createElement("div");
  tip.className = "tooltip";
  holder.appendChild(tip);

  const draw = () => {
    holder.querySelectorAll("svg").forEach((s) => s.remove());
    const width = holder.clientWidth || 600;
    const pad = { top: 8, right: 14, bottom: 26, left: 52 };
    const w = width - pad.left - pad.right;
    const h = height - pad.top - pad.bottom;
    const all = series.flatMap((s) => s.values).filter((v) => v != null && isFinite(v));
    if (!all.length) return;
    let lo = Math.min(...all, ...(baseline != null ? [baseline] : []));
    let hi = Math.max(...all, ...(baseline != null ? [baseline] : []));
    const useLog = log && lo > 0;
    let ticks;
    if (useLog) {
      // 1–2–5 steps per decade, trimmed to the data range (with one step of margin).
      ticks = [];
      for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
        for (const m of [1, 2, 5]) ticks.push(m * 10 ** e);
      const below = ticks.filter((t) => t <= lo).pop() ?? ticks[0];
      const above = ticks.find((t) => t >= hi) ?? ticks[ticks.length - 1];
      ticks = ticks.filter((t) => t >= below && t <= above);
      lo = below; hi = above;
    } else {
      ticks = niceTicks(lo, hi);
      lo = Math.min(lo, ticks[0]);
      hi = Math.max(hi, ticks[ticks.length - 1]);
    }
    const x = (i) => pad.left + (dates.length > 1 ? (i / (dates.length - 1)) * w : w / 2);
    const scale = (v) => (useLog ? Math.log(v) : v);
    const y = (v) => pad.top + h - ((scale(v) - scale(lo)) / (scale(hi) - scale(lo) || 1)) * h;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img" });
    holder.insertBefore(svg, tip);
    for (const t of ticks) {
      if (t < lo - 1e-9 || t > hi + 1e-9) continue;
      el("line", { class: "gridline", x1: pad.left, x2: pad.left + w, y1: y(t), y2: y(t) }, svg);
      const label = el("text", { class: "tick", x: pad.left - 8, y: y(t) + 4, "text-anchor": "end" }, svg);
      label.textContent = format(t);
    }
    if (baseline != null) el("line", { class: "baseline", x1: pad.left, x2: pad.left + w, y1: y(baseline), y2: y(baseline) }, svg);
    for (const i of dateTicks(dates, w)) {
      const label = el("text", { class: "tick", x: x(i), y: height - 6, "text-anchor": i === 0 ? "start" : i === dates.length - 1 ? "end" : "middle" }, svg);
      label.textContent = fmtDate(dates[i]);
    }

    series.forEach((s, si) => {
      let d = "";
      let pen = false;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      if (area && si === 0 && baseline != null) {
        const first = s.values.findIndex((v) => v != null);
        const last = s.values.length - 1 - [...s.values].reverse().findIndex((v) => v != null);
        el("path", { class: "wash", d: `${d}L${x(last)},${y(baseline)}L${x(first)},${y(baseline)}Z`, fill: s.color }, svg);
      }
      el("path", { class: "series", d, stroke: s.color }, svg);
      const lastIdx = s.values.length - 1 - [...s.values].reverse().findIndex((v) => v != null);
      if (lastIdx >= 0 && lastIdx < s.values.length) el("circle", { class: "dot", cx: x(lastIdx), cy: y(s.values[lastIdx]), r: 4, fill: s.color }, svg);
    });

    for (const m of markers) {
      if (m.index == null || m.value == null) continue;
      el("circle", { class: "dot", cx: x(m.index), cy: y(m.value), r: 4, fill: m.color }, svg);
    }

    const cross = el("line", { class: "crosshair", y1: pad.top, y2: pad.top + h, visibility: "hidden" }, svg);
    const hot = series.map((s) => el("circle", { class: "dot", r: 4, fill: s.color, visibility: "hidden" }, svg));
    const hit = el("rect", { x: pad.left, y: pad.top, width: w, height: h, fill: "transparent", tabindex: 0 }, svg);

    const show = (i) => {
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.textContent = "";
      const when = document.createElement("div");
      when.className = "when";
      when.textContent = fmtDate(dates[i], true);
      tip.appendChild(when);
      series.forEach((s, si) => {
        const v = s.values[i];
        if (v == null) { hot[si].setAttribute("visibility", "hidden"); return; }
        hot[si].setAttribute("cx", x(i)); hot[si].setAttribute("cy", y(v)); hot[si].setAttribute("visibility", "visible");
        const row = document.createElement("div");
        row.className = "row";
        const key = document.createElement("span"); key.className = "key"; key.style.background = s.color;
        const val = document.createElement("span"); val.className = "val"; val.textContent = format(v);
        const name = document.createElement("span"); name.className = "name"; name.textContent = s.name;
        row.append(key, val, name);
        tip.appendChild(row);
      });
      for (const m of markers.filter((mk) => mk.index === i && mk.label)) {
        const row = document.createElement("div"); row.className = "row small"; row.textContent = m.label; tip.appendChild(row);
      }
      tip.style.display = "block";
      const left = x(i) + 14 + tip.offsetWidth > width ? x(i) - tip.offsetWidth - 14 : x(i) + 14;
      tip.style.left = `${left}px`;
      tip.style.top = `${pad.top + 4}px`;
    };
    const hide = () => {
      tip.style.display = "none";
      cross.setAttribute("visibility", "hidden");
      hot.forEach((c) => c.setAttribute("visibility", "hidden"));
    };
    const indexAt = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * width;
      return Math.max(0, Math.min(dates.length - 1, Math.round(((px - pad.left) / w) * (dates.length - 1))));
    };
    let focusIdx = dates.length - 1;
    hit.addEventListener("pointermove", (e) => show((focusIdx = indexAt(e.clientX))));
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(focusIdx));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") show((focusIdx = Math.max(0, focusIdx - 1)));
      if (e.key === "ArrowRight") show((focusIdx = Math.min(dates.length - 1, focusIdx + 1)));
    });
  };

  draw();
  let lastWidth = holder.clientWidth;
  const observer = new ResizeObserver(() => {
    if (holder.clientWidth !== lastWidth) { lastWidth = holder.clientWidth; draw(); }   // width only: drawing changes height
  });
  observer.observe(holder);
  return { destroy: () => observer.disconnect() };
}

/** Tiny inline trend line (de-emphasized; no axes). */
export function sparkline(values, { width = 96, height = 26, color = "var(--series-1)" } = {}) {
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height, "aria-hidden": "true" });
  const v = values.filter((n) => n != null);
  if (v.length < 2) return svg;
  const lo = Math.min(...v), hi = Math.max(...v);
  const pts = values.map((n, i) => n == null ? null : `${((i / (values.length - 1)) * (width - 4) + 2).toFixed(1)},${(height - 3 - ((n - lo) / (hi - lo || 1)) * (height - 6)).toFixed(1)}`).filter(Boolean);
  el("polyline", { points: pts.join(" "), fill: "none", stroke: color, "stroke-width": 1.5, "stroke-linejoin": "round" }, svg);
  return svg;
}
