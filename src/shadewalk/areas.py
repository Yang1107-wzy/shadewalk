"""Built-in study areas (WGS84 bounding boxes: min_lon, min_lat, max_lon, max_lat)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AREAS", "Area", "get_area"]


@dataclass(frozen=True)
class Area:
    key: str
    title: str
    bbox: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        """(lat, lon) of the bbox centre."""
        return ((self.bbox[1] + self.bbox[3]) / 2, (self.bbox[0] + self.bbox[2]) / 2)


AREAS: dict[str, Area] = {
    a.key: a
    for a in [
        Area("kennedy_town", "Kennedy Town - HKU (Pok Fu Lam)", (114.120, 22.278, 114.140, 22.290)),
        Area("central", "Central - Sheung Wan", (114.148, 22.276, 114.164, 22.289)),
        Area("mong_kok", "Mong Kok", (114.162, 22.312, 114.176, 22.325)),
        Area("sha_tin", "Sha Tin town centre", (114.182, 22.376, 114.196, 22.388)),
        # District-scale region; build with `shadewalk region` (tiled) for best results
        Area(
            "yau_tsim_mong",
            "Yau Tsim Mong (Tsim Sha Tsui - Mong Kok)",
            (114.163, 22.293, 114.180, 22.326),
        ),
    ]
}


def get_area(key_or_bbox: str) -> Area:
    """Look up a built-in area, or parse ``"min_lon,min_lat,max_lon,max_lat"``."""
    if key_or_bbox in AREAS:
        return AREAS[key_or_bbox]
    try:
        vals = tuple(float(v) for v in key_or_bbox.split(","))
    except ValueError:
        vals = ()
    if len(vals) != 4 or not (vals[0] < vals[2] and vals[1] < vals[3]):
        known = ", ".join(AREAS)
        raise ValueError(f"unknown area {key_or_bbox!r}; use one of {known} or a lon/lat bbox")
    return Area("custom_" + "_".join(f"{v:.3f}" for v in vals), "Custom area", vals)
