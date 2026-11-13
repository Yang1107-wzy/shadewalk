"""ShadeWalk HK interactive demo.

Run locally:  streamlit run app/streamlit_app.py
Looks for built areas in ``$SHADEWALK_OUTPUTS`` (default ``outputs/``, then ``demo_data/``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from shadewalk.pipeline import load_area
from shadewalk.viz import route_map

st.set_page_config(page_title="ShadeWalk HK", page_icon="🌳", layout="wide")

REPO = Path(__file__).resolve().parents[1]
ROOTS = [
    Path(os.environ.get("SHADEWALK_OUTPUTS", "outputs")),
    REPO / "outputs",
    REPO / "demo_data",
]


def built_areas() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in ROOTS:
        if root.exists():
            for p in sorted(root.iterdir()):
                if (p / "meta.json").exists() and p.name not in found:
                    found[p.name] = p
    return found


@st.cache_resource(show_spinner="Loading area model ...")
def get_model(path: str):
    return load_area(path)


areas = built_areas()
st.title("ShadeWalk HK")
st.caption(
    "Shade- and heat-aware walking routes from LandsD 3D buildings and pedestrian network, "
    "solar geometry and Landsat surface temperature."
)
if not areas:
    st.error("No built areas found. Run `shadewalk build kennedy_town` first.")
    st.stop()

with st.sidebar:
    key = st.selectbox("Area", list(areas), format_func=lambda k: k.replace("_", " ").title())
    model = get_model(str(areas[key]))
    slot = st.select_slider("Time of day", options=model.slots, value=model.nearest_slot("15:00"))
    lam = st.slider("Shade preference λ (detour metres per sunlit metre)", 0.0, 16.0, 2.0, 0.5)
    show_segments = st.checkbox("Colour streets by shade", value=True)
    show_shadows = st.checkbox("Show building shadows", value=True)
    st.markdown(
        f"**Date** {model.meta['date']}  \n"
        f"**Sun** alt {model.meta['sun'][slot]['altitude']:.1f}°, "
        f"az {model.meta['sun'][slot]['azimuth']:.0f}°"
    )
    st.caption("Click the map to set start, then end. Click again to restart.")

state_key = f"pts_{key}"
pts: list[tuple[float, float]] = st.session_state.setdefault(state_key, [])

routes, labels = [], []
if len(pts) == 2:
    try:
        shortest = model.route(pts[0], pts[1], slot, 0.0)
        coolest = model.route(pts[0], pts[1], slot, lam)
        routes, labels = [shortest, coolest], ["Shortest", "Coolest"]
    except Exception as exc:  # disconnected nodes etc.
        st.warning(f"No route: {exc}")

col_map, col_stats = st.columns([3, 1])
with col_map:
    fmap = route_map(
        model, slot, routes, labels, show_shadows=show_shadows, show_segments=show_segments
    )
    out = st_folium(fmap, height=620, use_container_width=True, returned_objects=["last_clicked"])
    click = (out or {}).get("last_clicked")
    if click:
        pt = (round(click["lng"], 6), round(click["lat"], 6))
        if not pts or pts[-1] != pt:
            if len(pts) >= 2:
                pts.clear()
            pts.append(pt)
            st.rerun()

with col_stats:
    if len(routes) == 2:
        s, c = routes
        st.metric(
            "Shortest", f"{s.length_m:,.0f} m", f"{s.shaded_pct:.0f}% shaded", delta_color="off"
        )
        st.metric(
            "Coolest",
            f"{c.length_m:,.0f} m",
            f"+{(c.length_m / s.length_m - 1) * 100:.0f}% distance",
            delta_color="inverse",
        )
        st.metric(
            "Sunlit walking saved",
            f"{s.sunlit_m - c.sunlit_m:,.0f} m",
            f"{c.shaded_pct:.0f}% shaded",
            delta_color="off",
        )
        sweep = model.compare(pts[0], pts[1], slot)
        df = pd.DataFrame([r.summary() for r in sweep])
        st.markdown("**Trade-off across λ**")
        st.scatter_chart(df, x="length_m", y="shaded_pct", height=220)
        st.dataframe(
            df[["lam", "length_m", "sunlit_m", "shaded_pct"]].round(1),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(f"{len(pts)}/2 points selected.")
    if st.button("Reset points"):
        pts.clear()
        st.rerun()

st.caption(
    "Data: Lands Department (CSDI / DATA.GOV.HK), Landsat 8/9 courtesy of USGS via Microsoft "
    "Planetary Computer. LST is a relative surface-heat weight, not a thermal-comfort index. "
    "Shadows consider buildings only (no trees or terrain)."
)
