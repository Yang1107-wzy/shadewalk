// ShadeWalk browser routing core (ES module, no dependencies; also runs in Node).
//
// Mirrors shadewalk.routing / shadewalk.access in Python: Dijkstra on
// cost = length + lambda * exposure, with exposure = length * (1 - shade) * heat.

export function decodeU8(b64) {
  const bin = typeof atob === "function" ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Turn a uint8 layer (255 = missing) into floats with the given scale/offset. */
export function u8ToFloat(u8, scale, offset = 0) {
  const out = new Float32Array(u8.length);
  for (let i = 0; i < u8.length; i++) out[i] = u8[i] === 255 ? NaN : u8[i] / scale + offset;
  return out;
}

class MinHeap {
  constructor() { this.k = []; this.v = []; }
  get size() { return this.k.length; }
  push(key, val) {
    const k = this.k, v = this.v;
    let i = k.length; k.push(key); v.push(val);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (k[p] <= key) break;
      k[i] = k[p]; v[i] = v[p]; i = p;
    }
    k[i] = key; v[i] = val;
  }
  pop() {
    const k = this.k, v = this.v;
    const topV = v[0], topK = k[0];
    const lastK = k.pop(), lastV = v.pop();
    if (k.length) {
      let i = 0; const n = k.length;
      while (true) {
        let c = 2 * i + 1;
        if (c >= n) break;
        if (c + 1 < n && k[c + 1] < k[c]) c++;
        if (k[c] >= lastK) break;
        k[i] = k[c]; v[i] = v[c]; i = c;
      }
      k[i] = lastK; v[i] = lastV;
    }
    return [topK, topV];
  }
}

/** Build forward and reverse adjacency (CSR-like) from the atlas edge arrays. */
export function buildGraph(data) {
  const nNodes = data.nodes.length / 2;
  const E = data.edges;
  const arcs = []; // [from, to, edgeIndex]
  for (let e = 0; e < E.u.length; e++) {
    const d = E.dir[e];
    if (d === 0 || d === 1) arcs.push([E.u[e], E.v[e], e]);
    if (d === 0 || d === -1) arcs.push([E.v[e], E.u[e], e]);
  }
  const mk = (src, dst) => {
    const start = new Int32Array(nNodes + 1);
    for (const a of arcs) start[a[src] + 1]++;
    for (let i = 0; i < nNodes; i++) start[i + 1] += start[i];
    const fill = start.slice(0, nNodes);
    const to = new Int32Array(arcs.length), edge = new Int32Array(arcs.length);
    for (const a of arcs) { const p = fill[a[src]]++; to[p] = a[dst]; edge[p] = a[2]; }
    return { start, to, edge };
  };
  const len = Float32Array.from(E.len, (x) => x / 10);
  return { nNodes, fwd: mk(0, 1), rev: mk(1, 0), len, covered: Uint8Array.from(E.covered) };
}

/** Per-edge exposure for one slot: len * (1 - shade) * heat. */
export function exposureFor(graph, shadeU8, heat) {
  const n = graph.len.length;
  const out = new Float32Array(n);
  for (let e = 0; e < n; e++) {
    const s = shadeU8[e] === 255 ? 0 : shadeU8[e] / 250;
    out[e] = graph.len[e] * (1 - s) * (heat ? heat[e] : 1);
  }
  return out;
}

function dijkstra(adj, sources, len, expo, lam, target = -1) {
  const n = adj.start.length - 1;
  const dist = new Float64Array(n).fill(Infinity);
  const prevEdge = new Int32Array(n).fill(-1);
  const prevNode = new Int32Array(n).fill(-1);
  const done = new Uint8Array(n);
  const h = new MinHeap();
  for (const s of sources) { dist[s] = 0; h.push(0, s); }
  while (h.size) {
    const [d, u] = h.pop();
    if (done[u]) continue;
    done[u] = 1;
    if (u === target) break;
    for (let p = adj.start[u]; p < adj.start[u + 1]; p++) {
      const v = adj.to[p], e = adj.edge[p];
      const nd = d + len[e] + lam * expo[e];
      if (nd < dist[v]) { dist[v] = nd; prevEdge[v] = e; prevNode[v] = u; h.push(nd, v); }
    }
  }
  return { dist, prevEdge, prevNode };
}

/** Route summary from source to target node indices. */
export function route(graph, expo, shadeU8, source, target, lam) {
  const r = dijkstra(graph.fwd, [source], graph.len, expo, lam, target);
  if (!isFinite(r.dist[target])) return null;
  const edges = [];
  let length = 0, sunlit = 0, exposure = 0;
  for (let v = target; v !== source; v = r.prevNode[v]) {
    const e = r.prevEdge[v];
    edges.push(e);
    const s = shadeU8[e] === 255 ? 0 : shadeU8[e] / 250;
    length += graph.len[e]; sunlit += graph.len[e] * (1 - s); exposure += expo[e];
  }
  edges.reverse();
  return { lam, edges, length, sunlit, exposure, shadedPct: length > 0 ? 100 * (1 - sunlit / length) : 100 };
}

/** Walk from `origin` to the nearest of `targets` (reverse multi-source search). */
export function nearestTarget(graph, expo, shadeU8, origin, targets, lam) {
  const r = dijkstra(graph.rev, targets, graph.len, expo, lam, origin);
  if (!isFinite(r.dist[origin])) return null;
  const edges = [];
  let length = 0, sunlit = 0, node = origin;
  // In the reverse search prevNode points one step closer to the target set.
  while (r.prevEdge[node] !== -1) {
    const e = r.prevEdge[node];
    edges.push(e);
    const s = shadeU8[e] === 255 ? 0 : shadeU8[e] / 250;
    length += graph.len[e]; sunlit += graph.len[e] * (1 - s);
    node = r.prevNode[node];
  }
  return { lam, edges, length, sunlit, shadedPct: length > 0 ? 100 * (1 - sunlit / length) : 100, target: node };
}

/** Index of the node nearest to (lon, lat) using an equirectangular metric. */
export function nearestNode(data, lon, lat) {
  const k = Math.cos((lat * Math.PI) / 180);
  let best = -1, bd = Infinity;
  const N = data.nodes;
  for (let i = 0; i < N.length; i += 2) {
    const dx = (N[i] - lon) * k, dy = N[i + 1] - lat;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = i / 2; }
  }
  return best;
}
