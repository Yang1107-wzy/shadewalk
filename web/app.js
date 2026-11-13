import {
  buildGraph, decodeU8, exposureFor, nearestNode, nearestTarget, route, u8ToFloat,
} from "./router.js";

const BASEMAP = "https://tiles.openfreemap.org/styles/positron";
const LAYERS = {
  shade: { label: "Share of segment in shade", stops: [[0, "#f28e2b"], [0.5, "#f1e3b4"], [1, "#2f4b7c"]], fmt: (v) => `${Math.round(v * 100)}%` },
  sun_hours: { label: "Hours of direct sun (whole day)", stops: [[0, "#2f4b7c"], [3, "#a5b5c9"], [6, "#f7c873"], [10, "#d1495b"]], fmt: (v) => `${v} h` },
  svf: { label: "Sky view factor (LiDAR)", stops: [[0, "#2b2d42"], [0.25, "#8d99ae"], [0.6, "#edf2f4"]], fmt: (v) => v.toFixed(2) },
  tree: { label: "Share under tree canopy (LiDAR + NDVI)", stops: [[0, "#d9d9d9"], [0.5, "#86bf6b"], [1, "#1b7837"]], fmt: (v) => `${Math.round(v * 100)}%` },
  lisa: { label: "Sun-hours clusters (Local Moran's I, p < 0.05)", cats: [[0, "#cfd4dc", "n.s."], [1, "#d1495b", "Hot spot (High-High)"], [3, "#2f4b7c", "Cool spot (Low-Low)"], [2, "#9ecae1", "Low-High"], [4, "#f4a582", "High-Low"]] },
};

const state = { data: null, graph: null, heat: null, slot: 0, lam: 2, layer: "shade", mode: "route", pts: [], expo: null, shade: null, static: {}, features: [] };
const $ = (id) => document.getElementById(id);

const map = new maplibregl.Map({ container: "map", style: BASEMAP, center: [114.17, 22.31], zoom: 14, attributionControl: { compact: true } });
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

async function loadIndex() {
  const idx = await (await fetch("data/index.json")).json();
  const sel = $("area");
  for (const a of idx.areas) sel.add(new Option(a.title, a.key));
  sel.onchange = () => loadArea(sel.value);
  await loadArea(idx.areas[0].key);
}

function lineFeatures(data) {
  const [bx, by] = data.coords.base;
  return data.coords.lines.map((flat, i) => {
    const c = [];
    for (let k = 0; k < flat.length; k += 2) c.push([(flat[k] + bx) / 1e6, (flat[k + 1] + by) / 1e6]);
    return { type: "Feature", id: i, properties: {}, geometry: { type: "LineString", coordinates: c } };
  });
}

async function loadArea(key) {
  $("hint").textContent = "Loading…";
  const data = await (await fetch(`data/${key}.json`)).json();
  state.data = data;
  state.graph = buildGraph(data);
  state.heat = u8ToFloat(decodeU8(data.heat), 250, 1);
  state.static = {};
  for (const [name, spec] of Object.entries(data.layers || {})) state.static[name] = u8ToFloat(decodeU8(spec.data), spec.scale);
  for (const b of document.querySelectorAll("#layer button")) b.disabled = b.dataset.layer !== "shade" && !state.static[b.dataset.layer];
  const t = $("time");
  t.max = data.meta.slots.length - 1;
  const def = data.meta.slots.indexOf("15:00");
  state.slot = def >= 0 ? def : 0;
  t.value = state.slot;
  state.pts = [];
  const src = map.getSource("streets");
  const fc = { type: "FeatureCollection", features: lineFeatures(data) };
  state.features = fc.features;
  if (src) src.setData(fc);
  else {
    map.addSource("streets", { type: "geojson", data: fc });
    map.addLayer({ id: "streets", type: "line", source: "streets", paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 13, 1.2, 17, 4], "line-color": "#999" } });
    map.addSource("routes", { type: "geojson", data: emptyFC() });
    map.addLayer({ id: "route-short", type: "line", source: "routes", filter: ["==", ["get", "kind"], "short"], paint: { "line-color": "#d1495b", "line-width": 6, "line-opacity": 0.9 } });
    map.addLayer({ id: "route-cool", type: "line", source: "routes", filter: ["==", ["get", "kind"], "cool"], paint: { "line-color": "#00798c", "line-width": 6, "line-dasharray": [2, 1] } });
    map.addSource("pins", { type: "geojson", data: emptyFC() });
    map.addLayer({ id: "pins", type: "circle", source: "pins", paint: { "circle-radius": 7, "circle-color": ["get", "c"], "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
  }
  const [x0, y0, x1, y1] = data.meta.bbox;
  map.fitBounds([[x0, y0], [x1, y1]], { padding: 40, duration: 600 });
  clearRoute();
  onSlot();
  $("hint").textContent = hintText();
}

const emptyFC = () => ({ type: "FeatureCollection", features: [] });

function colorExpr(stops) {
  const e = ["interpolate", ["linear"], ["coalesce", ["feature-state", "v"], -1], -1, "#cccccc"];
  for (const [v, c] of stops) e.push(v, c);
  return e;
}

function paint() {
  const L = LAYERS[state.layer];
  const n = state.data.edges.u.length;
  const vals = state.layer === "shade" ? Float32Array.from(state.shade, (q) => (q === 255 ? NaN : q / 250)) : state.static[state.layer];
  for (let i = 0; i < n; i++) {
    const v = vals[i];
    map.setFeatureState({ source: "streets", id: i }, { v: Number.isFinite(v) ? v : -1 });
  }
  if (L.cats) {
    const m = ["match", ["coalesce", ["feature-state", "v"], -1]];
    for (const [v, c] of L.cats) m.push(v, c);
    m.push("#cccccc");
    map.setPaintProperty("streets", "line-color", m);
  } else map.setPaintProperty("streets", "line-color", colorExpr(L.stops));
  legend();
}

function legend() {
  const L = LAYERS[state.layer];
  if (L.cats) {
    $("legend").innerHTML = `<div>${L.label}</div><div class="cats">${L.cats.map(([, c, t]) => `<span><i style="background:${c}"></i>${t}</span>`).join("")}</div>`;
    return;
  }
  const grad = L.stops.map(([v, c], i) => `${c} ${(i / (L.stops.length - 1)) * 100}%`).join(",");
  $("legend").innerHTML = `<div>${L.label}</div><div class="ramp" style="background:linear-gradient(90deg,${grad})"></div><div class="ramp-labels"><span>${L.fmt(L.stops[0][0])}</span><span>${L.fmt(L.stops[L.stops.length - 1][0])}</span></div>`;
}

function onSlot() {
  const d = state.data;
  const slot = d.meta.slots[state.slot];
  state.shade = decodeU8(d.shade[slot]);
  state.expo = exposureFor(state.graph, state.shade, state.heat);
  $("timeOut").textContent = `${slot} · ${d.meta.date}`;
  const s = d.meta.sun[slot];
  $("sun").textContent = s.altitude > 0 ? `Sun ${s.altitude.toFixed(0)}° above the horizon, from ${s.azimuth.toFixed(0)}°` : "Sun below the horizon";
  paint();
  recompute();
}

function geomFor(edges) {
  const out = [];
  for (const e of edges) out.push(state.features[e].geometry.coordinates);
  return { type: "MultiLineString", coordinates: out };
}

const fmtM = (m) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);

function show(short, cool, label) {
  if (!short || !cool) { $("hint").textContent = "No connected route between these points."; return; }
  map.getSource("routes").setData({ type: "FeatureCollection", features: [
    { type: "Feature", properties: { kind: "short" }, geometry: geomFor(short.edges) },
    { type: "Feature", properties: { kind: "cool" }, geometry: geomFor(cool.edges) },
  ] });
  $("stats").hidden = false;
  $("sLen").textContent = fmtM(short.length); $("sSun").textContent = fmtM(short.sunlit); $("sPct").textContent = `${short.shadedPct.toFixed(0)}%`;
  $("cLen").textContent = fmtM(cool.length); $("cSun").textContent = fmtM(cool.sunlit); $("cPct").textContent = `${cool.shadedPct.toFixed(0)}%`;
  const extra = cool.length - short.length, saved = short.sunlit - cool.sunlit;
  $("verdict").textContent = saved > 1
    ? `${label}Walk ${fmtM(extra)} further to spend ${fmtM(saved)} less in the sun.`
    : `${label}The shortest route is already the coolest at this time.`;
}

function recompute() {
  const { graph, expo, shade, pts, lam } = state;
  if (state.mode === "route" && pts.length === 2) {
    show(route(graph, expo, shade, pts[0], pts[1], 0), route(graph, expo, shade, pts[0], pts[1], lam), "");
  } else if (state.mode === "mtr" && pts.length === 1) {
    const targets = state.data.stations.flatMap((s) => s.nodes);
    if (!targets.length) { $("hint").textContent = "No MTR station in this area."; return; }
    const a = nearestTarget(graph, expo, shade, pts[0], targets, 0);
    const b = nearestTarget(graph, expo, shade, pts[0], targets, lam);
    const st = state.data.stations.find((s) => a && s.nodes.includes(a.target));
    show(a, b, st ? `${st.name}: ` : "");
  }
}

function setPins() {
  const N = state.data.nodes;
  map.getSource("pins").setData({ type: "FeatureCollection", features: state.pts.map((n, i) => ({
    type: "Feature", properties: { c: i === 0 ? "#1d2330" : "#ffffff" }, geometry: { type: "Point", coordinates: [N[2 * n], N[2 * n + 1]] },
  })) });
}

function clearRoute() {
  state.pts = [];
  if (map.getSource("routes")) { map.getSource("routes").setData(emptyFC()); setPins(); }
  $("stats").hidden = true;
  $("hint").textContent = hintText();
}

const hintText = () => (state.mode === "route"
  ? ["Click the map to set a start point.", "Click again to set the destination.",
    "Click the map to start a new route."][state.pts.length]
  : "Click anywhere to find the coolest walk to the nearest MTR station.");

map.on("click", (ev) => {
  if (!state.data) return;
  const n = nearestNode(state.data, ev.lngLat.lng, ev.lngLat.lat);
  const need = state.mode === "route" ? 2 : 1;
  if (state.pts.length >= need) state.pts = [];
  state.pts.push(n);
  setPins();
  $("hint").textContent = hintText();
  recompute();
});

$("time").oninput = (e) => { state.slot = +e.target.value; onSlot(); };
$("lam").oninput = (e) => { state.lam = +e.target.value; $("lamOut").textContent = state.lam; recompute(); };
$("reset").onclick = clearRoute;
for (const b of document.querySelectorAll("#layer button")) b.onclick = () => {
  state.layer = b.dataset.layer;
  for (const o of document.querySelectorAll("#layer button")) o.classList.toggle("on", o === b);
  paint();
};
for (const b of document.querySelectorAll("#mode button")) b.onclick = () => {
  state.mode = b.dataset.mode;
  for (const o of document.querySelectorAll("#mode button")) o.classList.toggle("on", o === b);
  clearRoute();
};

// "style.load" fires once the style is parsed; unlike "load" it does not wait for the
// first rendered frame, so data loads even in background tabs.
let started = false;
const start = () => { if (!started) { started = true; loadIndex(); } };
map.on("style.load", start);
map.on("load", start);
window.shadewalk = { map, state }; // handy for debugging in the console
