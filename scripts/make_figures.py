"""Static figures for the README and docs (matplotlib; no basemap tiles needed).

    python scripts/make_figures.py --outputs outputs

Writes PNGs to ``docs/assets/``:

* ``hero_mong_kok.png``  - shortest vs coolest route at 09:00 and 15:00
* ``shade_by_hour.png``  - share of walkable length in shade through the day
* ``case_study.png``     - mean detour vs. reduction in sunlit walking (case study)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from shadewalk.pipeline import load_area
from shadewalk.routing import route_geometry
from shadewalk.viz import shadows_at

C_SHORT, C_COOL = "#d1495b", "#00798c"
C_BLD, C_SHADOW, C_STREET = "#b9b4aa", "#3b4a6b", "#9a9a9a"
AREA_COLORS = {
    "kennedy_town": "#4477aa",
    "central": "#ee6677",
    "mong_kok": "#228833",
    "sha_tin": "#ccbb44",
}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def hero(outputs: Path, dest: Path) -> None:
    model = load_area(outputs / "mong_kok")
    o, d = model.find_place("Langham Place"), model.find_place("Sino Centre")
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.2), constrained_layout=True)
    for ax, slot in zip(axes, ["12:00", "15:00"], strict=True):
        s = model.route(o, d, slot, 0.0)
        c = model.route(o, d, slot, 4.0)
        gs = gpd.GeoSeries(
            [route_geometry(s, model.edges), route_geometry(c, model.edges)], crs=model.edges.crs
        )
        x0, y0, x1, y1 = gs.total_bounds
        pad = 140
        box = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        bld = model.buildings.cx[box[0] : box[2], box[1] : box[3]]
        sh = shadows_at(model, slot)
        if sh is not None:
            sh.cx[box[0] : box[2], box[1] : box[3]].plot(
                ax=ax, color=C_SHADOW, alpha=0.35, linewidth=0
            )
        bld.plot(ax=ax, color=C_BLD, linewidth=0)
        model.edges.cx[box[0] : box[2], box[1] : box[3]].plot(ax=ax, color=C_STREET, linewidth=0.5)
        gpd.GeoSeries([gs.iloc[0]]).plot(ax=ax, color=C_SHORT, linewidth=3.2)
        gpd.GeoSeries([gs.iloc[1]]).plot(
            ax=ax, color=C_COOL, linewidth=3.2, linestyle=(0, (4, 1.5))
        )
        ax.set_xlim(box[0], box[2])
        ax.set_ylim(box[1], box[3])
        ax.set_axis_off()
        sun = model.meta["sun"][slot]
        ax.set_title(
            f"{slot}  (sun {sun['altitude']:.0f}° high, from {sun['azimuth']:.0f}°)\n"
            f"shortest {s.length_m:.0f} m, {s.shaded_pct:.0f}% shaded   |   "
            f"coolest {c.length_m:.0f} m, {c.shaded_pct:.0f}% shaded",
            fontsize=9,
            loc="left",
        )
    handles = [
        Line2D([], [], color=C_SHORT, lw=3, label="Shortest route"),
        Line2D([], [], color=C_COOL, lw=3, ls=(0, (4, 1.5)), label="Coolest route (λ=4)"),
        Patch(color=C_SHADOW, alpha=0.35, label="Building shadow"),
        Patch(color=C_BLD, label="Building (LandsD)"),
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.05)
    )
    fig.suptitle(
        "Langham Place → Sino Centre, Mong Kok, 15 July",
        x=0.01,
        ha="left",
        fontsize=11,
        fontweight="bold",
    )
    fig.savefig(dest / "hero_mong_kok.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def shade_by_hour(outputs: Path, dest: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.8, 3.8), constrained_layout=True)
    for key, color in AREA_COLORS.items():
        p = outputs / key
        if not (p / "meta.json").exists():
            continue
        meta = json.loads((p / "meta.json").read_text())
        e = gpd.read_parquet(p / "edges.parquet")
        hours = [int(s[:2]) + int(s[3:]) / 60 for s in meta["slots"]]
        for prefix, lw, ls in (("shade", 2.0, "-"), ("bshade", 1.2, "--")):
            if f"{prefix}_{meta['slots'][0].replace(':', '')}" not in e:
                continue
            vals = [
                100 * (e[f"{prefix}_{s.replace(':', '')}"] * e.length).sum() / e.length.sum()
                for s in meta["slots"]
            ]
            label = meta["area"]["title"] if prefix == "shade" else None
            ax.plot(hours, vals, color=color, lw=lw, ls=ls, label=label)
    ax.set_xlabel("Local time (15 July)")
    ax.set_ylabel("Walkable length in shade (%)")
    ax.set_ylim(0, 102)
    ax.set_xticks(range(7, 20, 2))
    ax.grid(axis="y", color="#e5e5e5")
    handles, labels = ax.get_legend_handles_labels()
    handles += [Line2D([], [], color="#555", lw=2), Line2D([], [], color="#555", lw=1.2, ls="--")]
    labels += ["LiDAR model (buildings, trees, terrain, cover)", "Buildings only (vector)"]
    ax.legend(handles, labels, frameon=False, fontsize=7.5, loc="lower left")
    fig.savefig(dest / "shade_by_hour.png", dpi=160)
    plt.close(fig)


def case_study(dest: Path, summary: Path) -> None:
    if not summary.exists():
        return
    df = pd.DataFrame(json.loads(summary.read_text())["rows"])
    df = df[df["lam"] == 2.0]
    fig, ax = plt.subplots(figsize=(6.4, 3.6), constrained_layout=True)
    markers = {"09:00": "o", "12:00": "s", "15:00": "^"}
    for _, r in df.iterrows():
        ax.scatter(
            r.mean_detour_pct,
            r.mean_sun_cut_pct,
            s=60,
            color=AREA_COLORS[r.area],
            marker=markers.get(r.slot, "o"),
            edgecolor="white",
            linewidth=0.6,
        )
    ax.set_xlabel("Mean extra distance vs. shortest route (%)")
    ax.set_ylabel("Mean reduction in sunlit walking (%)")
    ax.set_xlim(0, None)
    ax.set_ylim(0, None)
    ax.grid(color="#eeeeee")
    area_h = [
        Line2D([], [], color=c, marker="o", ls="", label=k.replace("_", " ").title())
        for k, c in AREA_COLORS.items()
    ]
    time_h = [Line2D([], [], color="#555", marker=m, ls="", label=t) for t, m in markers.items()]
    ax.legend(handles=area_h + time_h, frameon=False, fontsize=8, ncol=2, loc="lower right")
    ax.set_title("100 random 0.4–1.2 km trips per area, λ = 2", fontsize=9, loc="left")
    fig.savefig(dest / "case_study.png", dpi=160)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", type=Path, default=Path("outputs"))
    ap.add_argument("--dest", type=Path, default=Path("docs/assets"))
    args = ap.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    hero(args.outputs, args.dest)
    shade_by_hour(args.outputs, args.dest)
    case_study(args.dest, Path("docs/case_study/summary.json"))
    print("figures written to", args.dest)


if __name__ == "__main__":
    main()
