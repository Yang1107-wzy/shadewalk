"""Street-level spatial analysis and MTR accessibility for every built area.

    python scripts/district_report.py --outputs outputs_lidar \
        --areas yau_tsim_mong,kennedy_town,central,mong_kok,sha_tin

For each area this runs :func:`shadewalk.analysis.street_analysis` (Moran's I, LISA,
Gi*, OLS + spatial lag on daily sun hours) and
:func:`shadewalk.access.access_summary` (population-weighted walking access to MTR
at 09:00 / 12:00 / 15:00, shortest vs lambda=2). Results go to
``docs/analysis/summary.json`` and figures to ``docs/assets/``.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D

from shadewalk.access import access_summary, dasymetric_population, station_nodes
from shadewalk.analysis import street_analysis
from shadewalk.data.census import load_lsug
from shadewalk.data.csdi import load_terminals
from shadewalk.pipeline import load_area

warnings.filterwarnings("ignore")
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
LISA_COLORS = {
    "High-High": "#d1495b",
    "Low-Low": "#2f4b7c",
    "High-Low": "#f4a582",
    "Low-High": "#9ecae1",
    "Not significant": "#d9d9d9",
}


def lisa_map(res, bld, title, dest: Path) -> None:
    d = res.data
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 5.6), constrained_layout=True)
    x0, y0, x1, y1 = d.total_bounds
    for ax in axes:
        bld.cx[x0:x1, y0:y1].plot(ax=ax, color="#ece9e4", linewidth=0)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_axis_off()
    d.plot(
        ax=axes[0],
        column="sun_hours",
        cmap="magma_r",
        linewidth=1.3,
        legend=True,
        legend_kwds={"label": "Hours of direct sun, 15 July", "shrink": 0.6},
    )
    axes[0].set_title("Daily sun exposure per street segment", loc="left")
    for cat, col in LISA_COLORS.items():
        sub = d[d["lisa_cluster"] == cat]
        if len(sub):
            sub.plot(ax=axes[1], color=col, linewidth=1.6 if cat != "Not significant" else 0.7)
    axes[1].set_title(
        f"Local Moran's I clusters (p < 0.05), global I = {res.moran.I:.2f}", loc="left"
    )
    axes[1].legend(
        handles=[Line2D([], [], color=c, lw=3, label=k) for k, c in LISA_COLORS.items()],
        frameon=False,
        loc="lower left",
        fontsize=8,
    )
    fig.suptitle(title, x=0.01, ha="left", fontweight="bold")
    fig.savefig(dest, dpi=150)
    plt.close(fig)


def access_map(pts, edges, bld, title, dest: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 6.0), constrained_layout=True)
    x0, y0, x1, y1 = edges.total_bounds
    bld.cx[x0:x1, y0:y1].plot(ax=ax, color="#ece9e4", linewidth=0)
    edges.plot(ax=ax, color="#bdbdbd", linewidth=0.4)
    cut = (pts["sun_m"] - pts["cool_sun_m"]).clip(lower=0)
    sc = ax.scatter(
        pts.geometry.x,
        pts.geometry.y,
        s=np.clip(pts["pop65"], 1, 120) * 0.6,
        c=pts["sun_m"],
        cmap=ListedColormap(plt.cm.YlOrRd(np.linspace(0.15, 1, 8))),
        vmin=0,
        vmax=300,
        alpha=0.85,
        linewidths=0,
    )
    fig.colorbar(sc, ax=ax, shrink=0.6, label="Sunlit metres on shortest walk to MTR (15:00)")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    ax.set_title(
        f"{title}\nresidents aged 65+ (dot size); mean avoidable sun "
        f"{np.average(cut, weights=pts['pop65'] + 1e-9):.0f} m",
        loc="left",
        fontsize=9,
    )
    fig.savefig(dest, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", type=Path, default=Path("outputs_lidar"))
    ap.add_argument("--areas", default="yau_tsim_mong,kennedy_town,central,mong_kok,sha_tin")
    ap.add_argument("--times", default="09:00,12:00,15:00")
    ap.add_argument("--lam", type=float, default=2.0)
    ap.add_argument("--permutations", type=int, default=999)
    ap.add_argument("--out", type=Path, default=Path("docs/analysis"))
    ap.add_argument("--assets", type=Path, default=Path("docs/assets"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    terminals = load_terminals()
    report = {
        "params": {
            "lam": args.lam,
            "times": args.times.split(","),
            "permutations": args.permutations,
        },
        "areas": {},
    }
    for key in args.areas.split(","):
        path = args.outputs / key
        if not (path / "meta.json").exists():
            print("skip", key)
            continue
        m = load_area(path)
        title = m.meta["area"]["title"]
        res = street_analysis(m.edges, m.buildings, m.meta, permutations=args.permutations)
        res.layers().to_parquet(path / "analysis_layers.parquet")
        (path / "analysis.json").write_text(json.dumps(res.summary(), indent=2, default=float))
        lisa_map(res, m.buildings, title, args.assets / f"lisa_{key}.png")
        entry = {
            "title": title,
            "segments_km": round(float(m.edges["length"].sum()) / 1000, 1),
            "street": res.summary(),
            "access": {},
        }
        if "svf" in m.edges:
            L = m.edges["length"]
            entry["lidar"] = {
                "svf_median": round(float(np.nanmedian(m.edges["svf"])), 3),
                "overhead_cover_share": round(
                    float(np.average(m.edges["cover"].fillna(0), weights=L)), 3
                ),
                "tree_cover_share": round(
                    float(np.average(m.edges["tree"].fillna(0), weights=L)), 3
                ),
            }
        stations = station_nodes(m.graph, m.edges, terminals)
        if stations:
            people = dasymetric_population(m.buildings, load_lsug(m.meta["area"]["bbox"]))
            people = people[people.within(m.study_polygon())]
            for slot in args.times.split(","):
                pts, s = access_summary(m.graph, m.edge_table(slot), stations, people, lam=args.lam)
                s["stations"] = sorted(set(stations.values()))
                entry["access"][slot] = s
                if slot == "15:00":
                    pts.to_parquet(path / "access_1500.parquet")
                    access_map(pts, m.edges, m.buildings, title, args.assets / f"access_{key}.png")
        report["areas"][key] = entry
        print(
            key,
            "Moran",
            round(res.moran.I, 3),
            "R2",
            round(res.regression.r2, 3),
            {
                k: round(v["share_65plus_sun_over_200m_shortest"], 3)
                for k, v in entry["access"].items()
            },
        )
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, default=float))
    print("written", args.out / "summary.json")


if __name__ == "__main__":
    main()
