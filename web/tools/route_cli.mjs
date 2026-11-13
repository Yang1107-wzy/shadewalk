// Usage: node web/tools/route_cli.mjs <atlas.json> <slot> <lam> <srcNode> <dstNode>
// Prints the browser router's result as JSON (used by tests/test_atlas.py).
import { readFileSync } from "node:fs";
import { buildGraph, decodeU8, exposureFor, route, u8ToFloat } from "../router.js";

const [file, slot, lam, s, t] = process.argv.slice(2);
const data = JSON.parse(readFileSync(file, "utf8"));
const g = buildGraph(data);
const heat = u8ToFloat(decodeU8(data.heat), 250, 1);
const shade = decodeU8(data.shade[slot]);
const expo = exposureFor(g, shade, heat);
const r = route(g, expo, shade, +s, +t, +lam);
console.log(JSON.stringify(r && { length: r.length, sunlit: r.sunlit, shadedPct: r.shadedPct, edges: r.edges.length }));
