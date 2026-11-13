"""Command line interface: ``shadewalk build | route | map | areas | sun | weather``."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.table import Table

from shadewalk import __version__
from shadewalk.areas import AREAS, get_area

app = typer.Typer(
    add_completion=False,
    help="Shade- and heat-aware walking routes for Hong Kong.",
    no_args_is_help=True,
)
console = Console()
OUT = Path("outputs")


def _area(key: str):
    try:
        return get_area(key)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="AREA") from exc


def _version(value: bool) -> None:
    if value:
        console.print(f"shadewalk {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """ShadeWalk HK command line tools."""


@app.command()
def areas() -> None:
    """List built-in study areas."""
    t = Table("key", "title", "bbox (lon/lat)")
    for a in AREAS.values():
        t.add_row(a.key, a.title, ", ".join(f"{v:.3f}" for v in a.bbox))
    console.print(t)


@app.command()
def sun(
    when: str = typer.Argument(..., help="Local Hong Kong time, e.g. 2026-07-15T15:00"),
    lat: float = 22.302,
    lon: float = 114.174,
) -> None:
    """Print sun altitude/azimuth for a Hong Kong local time."""
    from shadewalk.sun import solar_position

    ts = datetime.fromisoformat(when).replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
    p = solar_position(ts, lat, lon)
    assert not isinstance(p, list)
    console.print(f"altitude {p.altitude:.2f} deg, azimuth {p.azimuth:.2f} deg")


@app.command()
def build(
    area: str = typer.Argument(..., help="Built-in area key or 'min_lon,min_lat,max_lon,max_lat'"),
    day: str = typer.Option(date.today().isoformat(), "--date", help="Date (YYYY-MM-DD)"),
    start: str = "07:00",
    end: str = "19:00",
    step: int = typer.Option(30, help="Minutes between time slots"),
    lst: bool = typer.Option(True, help="Weight segments by Landsat surface temperature"),
    beta: float = typer.Option(1.0, help="Extra weight for the hottest surfaces"),
    lidar: bool = typer.Option(False, help="Use CEDD LiDAR DSM/DTM (trees, terrain, cover)"),
    lidar_res: float = typer.Option(1.0, help="LiDAR grid size in metres (multiple of 0.5)"),
    out: Path = OUT,
) -> None:
    """Download open data for AREA and precompute shade and exposure per time slot."""
    from shadewalk.pipeline import build_area, time_slots

    build_area(
        _area(area),
        date.fromisoformat(day),
        time_slots(start, end, step),
        out,
        with_lst=lst,
        beta=beta,
        lidar=lidar,
        lidar_res=lidar_res,
        log=console.print,
    )


@app.command()
def region(
    key: str = typer.Argument(..., help="Name for the merged output folder"),
    bbox: str = typer.Argument(..., help="min_lon,min_lat,max_lon,max_lat"),
    title: str = typer.Option("", help="Human-readable title"),
    day: str = typer.Option(date.today().isoformat(), "--date"),
    step: int = typer.Option(30, help="Minutes between time slots"),
    tile_m: float = typer.Option(1000.0, help="Tile size in metres"),
    workers: int = typer.Option(2, help="Parallel tile builds"),
    lidar: bool = typer.Option(False),
    out: Path = OUT,
) -> None:
    """Build a large area as parallel tiles and merge them (district scale)."""
    from shadewalk.pipeline import time_slots
    from shadewalk.region import build_region

    b = _area(bbox).bbox
    build_region(
        key,
        title or key,
        b,
        date.fromisoformat(day),
        time_slots("07:00", "19:00", step),
        out,
        tile_m=tile_m,
        workers=workers,
        log=console.print,
        lidar=lidar,
    )


@app.command()
def analyze(
    area: str,
    out: Path = OUT,
    permutations: int = typer.Option(999, help="Permutations for Moran's I / LISA"),
    neighbours: int = typer.Option(8, "--k", help="k nearest neighbours for spatial weights"),
) -> None:
    """Spatial statistics of daily sun exposure: Moran's I, LISA, Gi*, OLS and spatial lag."""
    from shadewalk.analysis import street_analysis

    model = _load(area, out)
    res = street_analysis(
        model.edges, model.buildings, model.meta, k=neighbours, permutations=permutations
    )
    summ = res.summary()
    (model.path / "analysis.json").write_text(json.dumps(summ, indent=2, default=float))
    res.layers().to_parquet(model.path / "analysis_layers.parquet")
    console.print(f"Moran's I (sun hours) = {res.moran.I:.3f}, p = {res.moran.p_sim:.3f}")
    console.print(f"LISA clusters (p<0.05): {res.lisa_counts}")
    console.print(str(res.regression))
    if res.lag is not None:
        console.print(str(res.lag))
    console.print(f"Written {model.path / 'analysis.json'}")


@app.command()
def access(
    area: str,
    at: str = typer.Option("15:00", "--time"),
    lam: float = typer.Option(2.0, "--lambda"),
    out: Path = OUT,
) -> None:
    """Population-weighted shade-aware walking access to MTR stations (2021 census)."""
    from shadewalk.access import access_summary, dasymetric_population, station_nodes
    from shadewalk.data.census import load_lsug
    from shadewalk.data.csdi import load_terminals

    model = _load(area, out)
    stations = station_nodes(model.graph, model.edges, load_terminals())
    if not stations:
        console.print("[red]No MTR station access points inside this area.[/red]")
        raise typer.Exit(1)
    people = dasymetric_population(model.buildings, load_lsug(model.meta["area"]["bbox"]))
    people = people[people.within(model.study_polygon())]
    pts, summ = access_summary(model.graph, model.edge_table(at), stations, people, lam=lam)
    summ["time"] = model.nearest_slot(at)
    summ["stations"] = sorted(set(stations.values()))
    (model.path / f"access_{summ['time'].replace(':', '')}.json").write_text(
        json.dumps(summ, indent=2)
    )
    pts.to_parquet(model.path / f"access_{summ['time'].replace(':', '')}.parquet")
    t = Table(title=f"MTR access, {model.meta['area']['title']} {summ['time']}")
    t.add_column("metric")
    t.add_column("value", justify="right")
    for k, v in summ.items():
        if isinstance(v, float):
            t.add_row(k, f"{v:,.3f}" if v < 10 else f"{v:,.0f}")
    console.print(t)


@app.command()
def export(
    area: str,
    output: Path = typer.Option(..., "--output", "-o", help=".gpkg or .geojson file"),
    out: Path = OUT,
) -> None:
    """Export segments (with per-slot shade) and buildings to GeoPackage / GeoJSON."""
    model = _load(area, out)
    if output.suffix == ".gpkg":
        model.edges.to_file(output, layer="segments", driver="GPKG")
        model.buildings.to_file(output, layer="buildings", driver="GPKG")
        lay = model.path / "analysis_layers.parquet"
        if lay.exists():
            import geopandas as gpd
            import pandas as pd

            a = pd.read_parquet(lay)
            seg = gpd.GeoDataFrame(
                model.edges[["geometry"]].join(a, how="inner"),
                geometry="geometry",
                crs=model.edges.crs,
            )
            seg.to_file(output, layer="street_analysis", driver="GPKG")
    else:
        model.edges.to_crs(4326).to_file(output, driver="GeoJSON")
    console.print(f"Written {output}")


@app.command()
def atlas(
    areas: list[str] = typer.Argument(..., help="Built areas to include"),
    web_dir: Path = typer.Option(Path("web"), help="Static site folder"),
    out: Path = OUT,
) -> None:
    """Export built areas for the static web atlas (web/data/*.json + index.json)."""
    from shadewalk.access import station_nodes
    from shadewalk.analysis import daily_metrics
    from shadewalk.atlas import export_atlas
    from shadewalk.data.csdi import load_terminals

    terminals = load_terminals()
    index = []
    for a in areas:
        model = _load(a, out)
        layers = daily_metrics(model.edges, model.meta)
        for c in ("svf", "tree"):
            if c in model.edges:
                layers[c] = model.edges[c]
        lay = model.path / "analysis_layers.parquet"
        if lay.exists():
            import pandas as pd

            layers["lisa"] = (
                pd.read_parquet(lay)["lisa_cluster"].reindex(layers.index).fillna("Not significant")
            )
        st = station_nodes(model.graph, model.edges, terminals)
        key = model.meta["area"]["key"]
        p = export_atlas(model, web_dir / "data" / f"{key}.json", layers, st)
        index.append({"key": key, "title": model.meta["area"]["title"]})
        console.print(f"{key}: {p.stat().st_size / 1e6:.2f} MB")
    (web_dir / "data" / "index.json").write_text(json.dumps({"areas": index}, indent=2))


def _load(area: str, out: Path):
    from shadewalk.pipeline import load_area

    # Any folder already built under ``out`` (areas or merged regions) loads by name.
    path = out / area if (out / area / "meta.json").exists() else out / _area(area).key
    if not (path / "meta.json").exists():
        console.print(f"[red]{path} not built. Run: shadewalk build {area}[/red]")
        raise typer.Exit(1)
    return load_area(path)


@app.command()
def route(
    area: str,
    origin: str = typer.Option(..., "--from", help="'lon,lat' or a LandsD building name"),
    dest: str = typer.Option(..., "--to", help="'lon,lat' or a LandsD building name"),
    at: str = typer.Option("15:00", "--time", help="Local time HH:MM (nearest built slot)"),
    lam: float = typer.Option(2.0, "--lambda", help="Metres of detour accepted per sunlit metre"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table"),
    html: Path | None = typer.Option(None, help="Also write an HTML map here"),
    out: Path = OUT,
) -> None:
    """Compare the shortest route with the coolest route between two places."""
    model = _load(area, out)
    o, d = model.find_place(origin), model.find_place(dest)
    slot = model.nearest_slot(at)
    shortest = model.route(o, d, slot, 0.0)
    coolest = model.route(o, d, slot, lam)
    rows = {"shortest": shortest.summary(), "coolest": coolest.summary()}
    if as_json:
        console.print_json(json.dumps({"slot": slot, "date": model.meta["date"], **rows}))
    else:
        t = Table(title=f"{model.meta['area']['title']} | {model.meta['date']} {slot}")
        t.add_column("")
        t.add_column("length (m)", justify="right")
        t.add_column("in sun (m)", justify="right")
        t.add_column("shaded", justify="right")
        t.add_column("surface temp", justify="right")
        for name, r in (("shortest", shortest), ("coolest", coolest)):
            lst = f"{r.mean_lst_c:.1f} C" if r.mean_lst_c is not None else "-"
            t.add_row(name, f"{r.length_m:,.0f}", f"{r.sunlit_m:,.0f}", f"{r.shaded_pct:.0f}%", lst)
        console.print(t)
        if shortest.length_m > 0:
            detour = coolest.length_m / shortest.length_m - 1
            saved = shortest.sunlit_m - coolest.sunlit_m
            console.print(
                f"Detour +{detour * 100:.0f}% buys {saved:,.0f} m less walking in the sun."
            )
    if html:
        from shadewalk.viz import route_map

        route_map(model, slot, [shortest, coolest], ["Shortest", "Coolest"]).save(str(html))
        console.print(f"Map written to {html}")


@app.command(name="map")
def map_(
    area: str,
    at: str = typer.Option("15:00", "--time"),
    output: Path = typer.Option(Path("shadewalk_map.html"), "--output", "-o"),
    out: Path = OUT,
) -> None:
    """Write an HTML map of shadows and segment shade for one time slot."""
    from shadewalk.viz import route_map

    model = _load(area, out)
    route_map(model, at).save(str(output))
    console.print(f"Map written to {output}")


@app.command()
def weather() -> None:
    """Current temperature and UV index from the Hong Kong Observatory."""
    from shadewalk.data.weather import current_weather

    w = current_weather()
    console.print(
        f"{w.station}: {w.temperature_c} C, UV {w.uv_index}, RH {w.humidity_pct}% "
        f"(updated {w.update_time})"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
