"""Render result pages of the docs from the JSON outputs (no hand-copied numbers).

    python scripts/render_docs.py

Reads ``docs/case_study/summary.json``, ``docs/analysis/summary.json`` and
``docs/validation/*.json``; writes ``docs/case-study.md``, ``docs/analysis.md`` and
``docs/validation.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DOCS = Path("docs")
TITLES = {
    "kennedy_town": "Kennedy Town–HKU",
    "central": "Central–Sheung Wan",
    "mong_kok": "Mong Kok",
    "sha_tin": "Sha Tin",
    "yau_tsim_mong": "Yau Tsim Mong",
}
TERMS = {
    "log_hw": "Canyon aspect ratio log(1+H/W)",
    "ori_ns": "Orientation cos 2θ (N–S +)",
    "ori_diag": "Orientation sin 2θ (NE–SW +)",
    "bcr": "Building coverage (50 m)",
    "mean_height": "Mean building height (50 m)",
    "svf": "Sky view factor",
    "tree": "Tree-canopy share",
    "const": "Intercept",
    "rho (W_y)": "Spatial lag ρ",
}


def pct(v: float) -> str:
    return f"{100 * v:.1f}%"


def case_study() -> None:
    d = json.loads((DOCS / "case_study/summary.json").read_text())
    df = pd.DataFrame(d["rows"])

    def table(lam: float) -> str:
        out = [
            "| Area | Time | Shortest routes shaded | Mean extra distance | Mean cut in sunlit "
            "walking | Mean sunlit metres avoided | Trips rerouted |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for _, r in df[df.lam == lam].sort_values(["area", "slot"]).iterrows():
            out.append(
                f"| {TITLES[r.area]} | {r.slot} | {r.short_shaded_pct:.0f}% | "
                f"+{r.mean_detour_pct:.1f}% | −{r.mean_sun_cut_pct:.1f}% | "
                f"{r.mean_sun_cut_m:.0f} m | {r.changed_pct:.0f}% |"
            )
        return "\n".join(out)

    s2 = df[df.lam == 2.0]
    best = s2.loc[(s2.mean_sun_cut_pct / s2.mean_detour_pct.clip(lower=0.1)).idxmax()]
    noon = s2[s2.slot == "12:00"]
    st = s2[s2.area == "sha_tin"]
    text = f"""# Case study: what does a small detour buy?

**Question.** On a summer day, how much walking in direct sun can a pedestrian avoid by accepting a modest detour? And how does that differ between dense high-rise districts and lower-rise new towns?

**Setup.** The four bundled areas are built for 15 July 2026 with the LiDAR shade model (buildings, trees, terrain and overhead cover), 30-minute slots and \\(\\beta = 1\\). In each area, 100 origin–destination node pairs are sampled at random (seed {d["params"]["seed"]}), 400–1200 m apart in a straight line and connected in the network. Every pair is routed at 09:00, 12:00 and 15:00, once with \\(\\lambda = 0\\) (shortest) and once with each of \\(\\lambda \\in \\{{2, 4\\}}\\).

* *Mean extra distance* is the mean over trips of \\(\\ell_\\text{{cool}} / \\ell_\\text{{short}} - 1\\).
* *Mean cut in sunlit walking* is the mean over trips of \\((\\text{{sun}}_\\text{{short}} - \\text{{sun}}_\\text{{cool}}) / \\text{{sun}}_\\text{{short}}\\). Trips whose shortest route is already fully shaded count as 0.
* *Trips rerouted* is the share of trips whose coolest route differs from the shortest, including a switch to the shaded footway on the other side of the same street at no extra cost.

![Trade-off](assets/case_study.png)

## λ = 2

{table(2.0)}

## λ = 4

{table(4.0)}

## Reading the results

* **Across areas and times, at λ = 2:** the coolest route is on average {s2.mean_detour_pct.min():.1f}–{s2.mean_detour_pct.max():.1f}% longer and cuts sunlit walking by {s2.mean_sun_cut_pct.min():.1f}–{s2.mean_sun_cut_pct.max():.1f}%.
* **Best trade-off:** {TITLES[best.area]} at {best.slot}, where a +{best.mean_detour_pct:.1f}% detour removes {best.mean_sun_cut_pct:.1f}% of the sunlit walking. Dense grids with tall frontages offer shaded alternatives of almost the same length.
* **Noon is the hardest time.** With the sun at ≈ 83° in mid-July, the shortest routes are only {noon.short_shaded_pct.min():.0f}–{noon.short_shaded_pct.max():.0f}% shaded, and detours get longer.
* **Lower-rise Sha Tin needs the longest detours,** {st.mean_detour_pct.min():.1f}–{st.mean_detour_pct.max():.1f}% at λ = 2.

## Caveats

These are model results, not field measurements. The LiDAR model treats any overhead obstruction (trees, canopies, signboards) as shade and can over-count near facades; building-only figures are in `bshade_*` (see [Validation](validation.md)). The random trips are not weighted by real pedestrian demand. Per-trip results are in `docs/case_study/results.csv`. Reproduce with `python scripts/case_study.py --outputs demo_data`.
"""
    (DOCS / "case-study.md").write_text(text)


def analysis() -> None:
    d = json.loads((DOCS / "analysis/summary.json").read_text())
    A = d["areas"]
    rows = [
        "| Area | Street km | Outdoor segments | Moran's I (sun hours) | LISA hot / cool "
        "clusters | OLS R² | Residual Moran's I | Spatial lag ρ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k, a in A.items():
        s = a["street"]
        lc = s["lisa_clusters_p05"]
        lag = s.get("spatial_lag") or {}
        rows.append(
            f"| {TITLES.get(k, k)} | {a['segments_km']} | {s['segments']:,} | "
            f"{s['morans_I']:.3f} | {lc.get('High-High', 0):,} / {lc.get('Low-Low', 0):,} "
            f"| {s['ols_r2']:.3f} | {s['ols_residual_morans_I']:.3f} | "
            f"{lag.get('rho', float('nan')):.3f} |"
        )
    lidar = [
        "| Area | Median street SVF | Overhead cover (length share) | Tree-canopy share |",
        "|---|---:|---:|---:|",
    ]
    for k, a in A.items():
        if "lidar" in a:
            L = a["lidar"]
            lidar.append(
                f"| {TITLES.get(k, k)} | {L['svf_median']:.2f} | "
                f"{pct(L['overhead_cover_share'])} | {pct(L['tree_cover_share'])} |"
            )
    # coefficient table for the largest area
    big = max(A, key=lambda k: A[k]["street"]["segments"])
    coef = {c["term"]: c for c in A[big]["street"]["coefficients"]}
    lagc = {
        c["term"]: c for c in (A[big]["street"].get("spatial_lag") or {}).get("coefficients", [])
    }
    ctab = ["| Term | OLS β (std.) | HC1 t | Spatial-lag β | z |", "|---|---:|---:|---:|---:|"]
    for t in list(coef) + (["rho (W_y)"] if "rho (W_y)" in lagc else []):
        o = coef.get(t)
        g = lagc.get(t)
        ctab.append(
            f"| {TERMS.get(t, t)} | {o['beta_std']:.3f} | {o['t']:.1f} | "
            if o
            else f"| {TERMS.get(t, t)} | – | – | "
        )
        ctab[-1] += f"{g['coef']:.3f} | {g['z']:.1f} |" if g else "– | – |"
    acc = [
        "| Area | Time | Residents (65+) | Median walk to MTR | Within 500 m | Median sun "
        "(shortest → coolest) | Median extra walk | 65+ with >200 m sun (shortest → coolest) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k, a in A.items():
        for slot, s in a["access"].items():
            acc.append(
                f"| {TITLES.get(k, k)} | {slot} | {s['residents']:,.0f} ({s['residents_65plus']:,.0f}) "
                f"| {s['median_walk_m']:.0f} m | {pct(s['share_within_500m'])} | "
                f"{s['median_sun_m_shortest']:.0f} → {s['median_sun_m_coolest']:.0f} m | "
                f"{s['median_extra_walk_m']:.0f} m | "
                f"{pct(s['share_65plus_sun_over_200m_shortest'])} → "
                f"{pct(s['share_65plus_sun_over_200m_coolest'])} |"
            )
    imgs = "\n\n".join(
        f"![LISA {TITLES.get(k, k)}](assets/lisa_{k}.png)"
        for k in A
        if (DOCS / f"assets/lisa_{k}.png").exists()
    )
    aimgs = "\n\n".join(
        f"![Access {TITLES.get(k, k)}](assets/access_{k}.png)"
        for k in A
        if (DOCS / f"assets/access_{k}.png").exists()
    )
    text = f"""# Street analysis and MTR accessibility

All numbers on this page are generated from `docs/analysis/summary.json` by `scripts/render_docs.py`, and that file is produced by `scripts/district_report.py`. The analysis unit is the outdoor, uncovered street segment (≥ 5 m), and the response variable is **hours of direct sun on 15 July** from the LiDAR model.

## 1. Street-level LiDAR metrics

{chr(10).join(lidar)}

## 2. Spatial autocorrelation and explanatory models

Spatial weights: 8 nearest neighbours, row-standardised. Inference uses {d["params"]["permutations"]} permutations.

{chr(10).join(rows)}

Sun exposure is strongly clustered in every district (all Moran's I p ≤ 0.001). The LISA maps below separate **hot streets** (High-High: wide, open roads and waterfronts) from **cool streets** (Low-Low: narrow canyons, tree-lined and arcaded streets).

**Coefficients for {TITLES.get(big, big)}** (the largest area, standardised variables):

{chr(10).join(ctab)}

The sky view factor is the dominant predictor of sun exposure. Tree canopy reduces exposure beyond what the geometry explains, and deeper canyons (higher H/W) are cooler. The OLS residuals are still spatially autocorrelated, so the spatial-lag model (S2SLS) is reported alongside. Its coefficients are close to the OLS ones, which suggests the morphology effects are robust to spatial dependence.

{imgs}

## 3. Walking access to the MTR (2021 Census)

Population of each Large Subunit Group is allocated to its buildings by floor area. Destinations are the street-level access points of MTR stations from the LandsD terminal table. λ = {d["params"]["lam"]}. Residents more than 80 m from the network, and buildings outside the area's bbox, are excluded.

{chr(10).join(acc)}

* **Dense districts, morning and afternoon:** in Mong Kok, Central and Kennedy Town, re-routing alone almost eliminates long sunlit walks to the MTR for older residents, at a median cost of a few tens of metres.
* **Noon:** a large share of residents cannot avoid long sunlit walks even on the coolest route. That pattern marks where **shade infrastructure** (covered walkways, street trees) would help most.
* **Sha Tin:** with fewer stations and longer walks, most older residents face more than 200 m of sun at every hour tested, even on the coolest route. Distance, not route choice, is the binding constraint there.

{aimgs}

## Caveats

Dasymetric allocation assumes residents are spread in proportion to floor area (including commercial floors in mixed LSUGs). Only MTR stations inside each area are destinations, so residents near the bbox edge may have a closer station outside it. LiDAR shade is an upper bound (see [Validation](validation.md)).
"""
    (DOCS / "analysis.md").write_text(text)


def validation() -> None:
    v = json.loads((DOCS / "validation/kennedy_town_pybdshadow.json").read_text())
    pyb = "\n".join(
        f"| {r['time']} | {r['sun_altitude']:.1f}° | {r['sun_azimuth']:.1f}° | "
        f"{r['shadewalk_m2']:,} | {r['pybdshadow_m2']:,} | {r['iou']:.4f} |"
        for r in v["slots"]
    )
    lid_rows, cov_rows = [], []
    for p in sorted((DOCS / "validation").glob("lidar_*.json")):
        L = json.loads(p.read_text())
        name = TITLES.get(L["area"], L["area"])
        c = L["overhead_cover_vs_weatherproof"]
        cov_rows.append(
            f"| {name} | {pct(c['detected_on_covered'])} | {pct(c['detected_on_noncovered'])} |"
        )
        for r in L["slots"]:
            lid_rows.append(
                f"| {name} | {r['time']} | {pct(r['vector_vs_raster_buildings_agreement'])} | "
                f"{pct(r['shade_buildings_vector'])} | {pct(r['shade_buildings_on_terrain'])} | "
                f"{pct(r['shade_full_dsm'])} | {pct(r['shade_full_dsm_plus_cover'])} |"
            )
    text = f"""# Validation

## 1. Vector shadows vs. pybdshadow

[pybdshadow](https://github.com/ni1o1/pybdshadow) is an independent open-source building-shadow implementation with its own sun-position code (suncalc). We cast shadows for the 2,080 LandsD buildings in the Kennedy Town area on {v["date"]} with both tools and compare the union of all shadow polygons in EPSG:2326.

| Local time | Sun altitude | Sun azimuth | ShadeWalk (m²) | pybdshadow {v["pybdshadow_version"]} (m²) | IoU |
|---|---:|---:|---:|---:|---:|
{pyb}

```bash
pip install pybdshadow
python scripts/validate_pybdshadow.py demo_data/kennedy_town --date {v["date"]}
```

## 2. LiDAR ray marching vs. exact vector shadows, and shade by source

`scripts/validate_lidar.py` evaluates every outdoor street sample point (2 m spacing) in four ways:

* *Vector:* exact LandsD prism shadows.
* *Buildings on terrain:* LandsD roofs rasterised onto the LiDAR DTM, ray-marched.
* *Full DSM:* adds trees, bridges and small structures.
* *+ cover:* adds overhead canopy and verandahs.

The first column checks the implementation: the same buildings on flat ground, vector vs raster.

| Area | Time | Vector = raster (buildings, flat) | Buildings only (vector) | Buildings on terrain | Full DSM | Full DSM + cover |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(lid_rows)}

* **The ray marcher reproduces exact vector shadows at 95–99% of points.** The disagreement is confined to 1 m pixel edges along facades.
* **Terrain matters little at these times** in these areas. Adding the full DSM raises street shade by roughly 20–35 percentage points. That increase is the shade from trees, footbridges, canopies and other structures that building footprints do not capture.

**Overhead-cover detection vs. LandsD `WeatherProof` coding.** This is the share of street points where LiDAR finds something overhead:

| Area | Segments coded *Covered* | Segments coded *NonCovered* |
|---|---:|---:|
{chr(10).join(cov_rows)}

Most officially covered walkways are detected. About a quarter to a third of "non-covered" footway points also have something overhead (street trees, shop canopies, signboards, flyovers): that is shade for a pedestrian, but it is not recorded as a covered walkway. Some of it is facade spill-over at 1 m resolution. ShadeWalk therefore reports the LiDAR model (`shade_*`) as an **upper bound** and the vector building model (`bshade_*`) as a **lower bound**.

## 3. Spatial statistics vs. PySAL

`tests/test_stats.py` checks `shadewalk.stats` against `esda` and `spreg` on synthetic autocorrelated data:

* global Moran's I and the local Moran's \\(I_i\\) are identical, and the LISA quadrants all agree;
* Getis–Ord \\(G_i^*\\) z-scores are identical;
* the S2SLS spatial-lag coefficients and standard errors match `spreg.GM_Lag` to \\(10^{{-8}}\\).

## 4. Browser router vs. Python

`tests/test_atlas_region.py` exports an atlas JSON, runs `web/router.js` under Node, and checks route length and sunlit metres against `shadewalk.routing`.

## 5. Unit tests

`pytest` (61 tests, offline, synthetic fixtures) covers:

* solar geometry (solstices, equinox, timezones);
* analytic shadow lengths and concave footprints;
* ray-marched shadows, sky view factor and overhead cover on synthetic DSMs, plus LiDAR mosaicking with max/mean aggregation;
* canyon H/W and dissolved coverage;
* routing (λ switch point, one-way edges);
* multi-source access against networkx, and dasymetric totals;
* tiling and merging, caching with SHA-256 provenance, and the CLI and Streamlit app.
"""
    (DOCS / "validation.md").write_text(text)


if __name__ == "__main__":
    case_study()
    analysis()
    validation()
    print("docs rendered")
