"""Case study: how much sun can a small detour avoid in four Hong Kong districts?

For every built area, sample random origin-destination node pairs 400-1200 m apart
(straight line, fixed seed), route them at several times of day with lambda = 0
(shortest) and lambda in {2, 4}, and record distance and sunlit metres.

    python scripts/case_study.py --outputs outputs --pairs 100

Writes ``docs/case_study/results.csv`` and ``docs/case_study/summary.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from shadewalk.pipeline import load_area
from shadewalk.routing import find_route

AREAS = ["kennedy_town", "central", "mong_kok", "sha_tin"]


def sample_pairs(
    g: nx.MultiDiGraph, n: int, rng: np.random.Generator, dmin: float = 400, dmax: float = 1200
) -> list[tuple]:
    nodes = list(g.nodes)
    xy = np.asarray(nodes)
    pairs: list[tuple] = []
    tries = 0
    while len(pairs) < n and tries < n * 200:
        tries += 1
        i, j = rng.integers(len(nodes), size=2)
        d = float(np.hypot(*(xy[i] - xy[j])))
        if dmin <= d <= dmax and nx.has_path(g, nodes[i], nodes[j]):
            pairs.append((nodes[i], nodes[j], d))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", type=Path, default=Path("outputs"))
    ap.add_argument("--pairs", type=int, default=100)
    ap.add_argument("--slots", default="09:00,12:00,15:00")
    ap.add_argument("--lams", default="2,4")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("docs/case_study"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lams = [float(v) for v in args.lams.split(",")]

    rows = []
    for key in AREAS:
        path = args.outputs / key
        if not (path / "meta.json").exists():
            continue
        model = load_area(path)
        rng = np.random.default_rng(args.seed)
        pairs = sample_pairs(model.graph, args.pairs, rng)
        print(f"{key}: {len(pairs)} pairs")
        for slot in args.slots.split(","):
            table = model.edge_table(slot)
            for k, (s, t, d) in enumerate(pairs):
                base = find_route(model.graph, table, s, t, 0.0)
                for lam in lams:
                    r = find_route(model.graph, table, s, t, lam)
                    rows.append(
                        {
                            "area": key,
                            "slot": slot,
                            "pair": k,
                            "crow_m": d,
                            "lam": lam,
                            "short_len": base.length_m,
                            "short_sun": base.sunlit_m,
                            "cool_len": r.length_m,
                            "cool_sun": r.sunlit_m,
                            "changed": r.edge_ids != base.edge_ids,
                        }
                    )
    df = pd.DataFrame(rows)
    df["detour_pct"] = 100 * (df.cool_len / df.short_len - 1)
    df["sun_cut_m"] = df.short_sun - df.cool_sun
    df["sun_cut_pct"] = np.where(df.short_sun > 1, 100 * df.sun_cut_m / df.short_sun, 0.0)
    df.round(2).to_csv(args.out / "results.csv", index=False)

    summary = (
        df.groupby(["area", "slot", "lam"])
        .agg(
            trips=("pair", "count"),
            changed_pct=("changed", lambda s: 100 * s.mean()),
            median_short_m=("short_len", "median"),
            mean_detour_pct=("detour_pct", "mean"),
            mean_sun_cut_pct=("sun_cut_pct", "mean"),
            mean_sun_cut_m=("sun_cut_m", "mean"),
        )
        .reset_index()
    )
    shaded = df.groupby(["area", "slot", "lam"]).apply(
        lambda g: 100 * (1 - g.short_sun.sum() / g.short_len.sum()), include_groups=False
    )
    summary["short_shaded_pct"] = shaded.to_numpy()
    summary = summary.round(1)
    print(summary.to_string(index=False))
    (args.out / "summary.json").write_text(
        json.dumps(
            {
                "params": {
                    "pairs_per_area": args.pairs,
                    "seed": args.seed,
                    "crow_m": [400, 1200],
                    "slots": args.slots.split(","),
                    "lams": lams,
                },
                "rows": summary.to_dict(orient="records"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
