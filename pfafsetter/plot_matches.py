"""
Turn basin -> nexus match results (resultsNEW22.csv) into a GeoPackage for
manual inspection in QGIS, plus a histogram of match quality.

Outputs:
  1. basin_match_review.gpkg - three layers, all in the same CRS:
       - "basins"               every hydrobasin polygon + Best_Match /
                                 Match_Percentage. Style this by
                                 Match_Percentage (graduated/color ramp) to
                                 get the heat-map effect in QGIS.
       - "matched_nexus_points" the nexus point each matched basin resolved to.
       - "connectors"           a line from each matched basin's centroid to
                                 its matched nexus point, for spotting matches
                                 that jumped to an implausible location.
  2. match_percentage_histogram.png - just the statistic, no map.

Note on the join: nexus points don't carry their own LINKNO. Each nexus point
has a DSLINKNO and a comma-separated USLINKNOs list (the river segments that
flow INTO that junction). `Best_Match` in resultsNEW22.csv is one of those
upstream LINKNOs, so to plot it we explode every nexus point's USLINKNOs list
into (LINKNO -> nexus geometry) rows and join on that.
"""

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import LineString

# ---- Adjust these to match your local paths (same convention as main.py) ----
HYDROBASINS_PATH = "/Users/maugh24/FEWS_Share/hybas_na_lev01-12_v1c/hybas_na_lev08_v1c.shp"
NEXUS_PATH = "/Users/maugh24/FEWS_Share/pfafsetter/global_nexus.gpkg"
RESULTS_CSV = "/Users/maugh24/FEWS_Share/pfafsetter/resultsNEW22.csv"
OUT_GPKG = "/Users/maugh24/FEWS_Share/pfafsetter/basin_match_review.gpkg"
OUT_HIST_PNG = "/Users/maugh24/FEWS_Share/pfafsetter/match_percentage_histogram.png"


def load_data(hydrobasins_path=HYDROBASINS_PATH, nexus_path=NEXUS_PATH, results_csv=RESULTS_CSV):
    results = pd.read_csv(results_csv)
    hydrobasins = gpd.read_file(hydrobasins_path)
    nexus_points = gpd.read_file(nexus_path).to_crs(hydrobasins.crs)
    return results, hydrobasins, nexus_points


def build_link_to_nexus_lookup(nexus_points):
    """Explode USLINKNOs so every upstream LINKNO maps to the nexus point
    geometry it flows into. A given LINKNO should only feed one nexus point;
    if it somehow appears more than once, just keep the first."""
    exploded = nexus_points.assign(
        LINKNO=nexus_points["USLINKNOs"].str.split(",")
    ).explode("LINKNO")
    exploded["LINKNO"] = exploded["LINKNO"].astype("int64")
    return (
        exploded.drop_duplicates("LINKNO", keep="first")[["LINKNO", "geometry"]]
        .rename(columns={"geometry": "nexus_geometry"})
    )


def join_results(results, hydrobasins, nexus_points):
    """Returns:
        basins        - every hydrobasin polygon + Best_Match/Match_Percentage
        matched_points - one row per successfully matched basin, with the
                         matched nexus point's geometry
    """
    basins = hydrobasins.merge(results, left_on="HYBAS_ID", right_on="Basin_ID", how="left")
    basins = basins.drop(columns=["Basin_ID"])  # duplicate of HYBAS_ID

    link_lookup = build_link_to_nexus_lookup(nexus_points)

    matched = results.dropna(subset=["Best_Match"]).copy()
    matched["Best_Match"] = matched["Best_Match"].astype("int64")
    matched = matched.merge(link_lookup, left_on="Best_Match", right_on="LINKNO", how="left")
    matched = matched.drop(columns=["LINKNO"])
    matched_points = gpd.GeoDataFrame(matched, geometry="nexus_geometry", crs=nexus_points.crs)

    return basins, matched_points


def make_connector_lines(basins, matched_points):
    """One line per matched basin, from its centroid to the matched nexus point.
    Useful for spotting matches that jump to an implausibly distant basin."""
    basin_geoms = basins[["HYBAS_ID", "geometry"]].rename(columns={"geometry": "basin_geometry"})
    merged = matched_points.merge(basin_geoms, left_on="Basin_ID", right_on="HYBAS_ID")
    lines = merged.apply(
        lambda r: LineString([r["basin_geometry"].centroid, r["nexus_geometry"]]), axis=1
    )
    return gpd.GeoDataFrame(
        merged.drop(columns=["basin_geometry", "nexus_geometry"]), geometry=lines, crs=basins.crs
    )


def write_gpkg(basins, matched_points, connectors, out_path=OUT_GPKG):
    # First layer creates/overwrites the file; the rest append as new layers
    # in the same GeoPackage so QGIS sees all three at once.
    basins.to_file(out_path, layer="basins", driver="GPKG", mode="w")
    matched_points.to_file(out_path, layer="matched_nexus_points", driver="GPKG", mode="a")
    connectors.to_file(out_path, layer="connectors", driver="GPKG", mode="a")
    print(f"Saved {out_path} (layers: basins, matched_nexus_points, connectors)")


def plot_histogram(basins, out_path=OUT_HIST_PNG):
    match_pct = basins["Match_Percentage"].dropna()
    n_no_match = basins["Match_Percentage"].isna().sum()

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.hist(match_pct, bins=30, color="steelblue")
    ax.set_title("Match Percentage Distribution")
    ax.set_xlabel("Match Percentage")
    ax.set_ylabel("Basin Count")
    ax.text(
        0.98, 0.95,
        f"No match: {n_no_match} / {len(basins)} basins\n"
        f"Median (matched only): {match_pct.median():.2f}",
        transform=ax.transAxes, ha="right", va="top",
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"Saved {out_path}")


def main():
    results, hydrobasins, nexus_points = load_data()
    basins, matched_points = join_results(results, hydrobasins, nexus_points)
    connectors = make_connector_lines(basins, matched_points)

    write_gpkg(basins, matched_points, connectors)
    plot_histogram(basins)


if __name__ == "__main__":
    main()
