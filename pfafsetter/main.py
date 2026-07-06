import pandas as pd
import geopandas as gpd
import networkx as nx
from multiprocessing import Pool, cpu_count
from tqdm import tqdm


def build_graph(meta_data):
    """Directed graph of upstream -> downstream LINKNO connectivity."""
    G = nx.DiGraph()
    for _, row in meta_data.iterrows():
        G.add_edge(str(row["LINKNO"]), str(row["DSLINKNO"]))
    return G


def init_worker(graph, nexus, linkno_map):
    """Runs once per worker process. Stashes the big read-only objects as
    globals so they aren't re-pickled for every basin."""
    global G, NEXUS_POINTS, LINKNO_USCONTAREA_MAP
    G = graph
    NEXUS_POINTS = nexus
    LINKNO_USCONTAREA_MAP = linkno_map


def process_basin(basin_data):
    """Find the best-matching nexus link for a single basin."""
    basin_geom, basin_area, basin_hybas_id = basin_data

    contained_points = NEXUS_POINTS[NEXUS_POINTS.within(basin_geom)]
    if contained_points.empty:
        return {"Basin_ID": basin_hybas_id, "Best_Match": None, "Match_Percentage": 0}

    uslinknos = [ln for sublist in contained_points["USLINKNOs"].str.split(",") for ln in sublist]

    filtered_uscontareas = {
        ln: ratio
        for ln in uslinknos
        if (uscontarea := LINKNO_USCONTAREA_MAP.get(int(ln))) is not None
        and (ratio := abs((uscontarea / 1e6) / basin_area - 1)) <= 0.50
    }

    top_matches = dict(sorted(filtered_uscontareas.items(), key=lambda item: item[1])[:30])

    best_match, best_percentage = None, 0
    for uslinkno in top_matches:
        upstream_rivers = nx.ancestors(G, uslinkno)
        contained_upstream_rivers = upstream_rivers.intersection(uslinknos)
        percentage = len(contained_upstream_rivers) / len(upstream_rivers) if upstream_rivers else 0
        if percentage > best_percentage:
            best_percentage = percentage
            best_match = uslinkno

    return {"Basin_ID": basin_hybas_id, "Best_Match": best_match, "Match_Percentage": best_percentage}


def main():
    shapefile_path = "/Users/maugh24/FEWS_Share/hybas_na_lev01-12_v1c/hybas_na_lev08_v1c.shp"
    hydrobasins = gpd.read_file(shapefile_path)
    print("have basins")

    nexus_points = gpd.read_file("/Users/maugh24/FEWS_Share/pfafsetter/global_nexus.gpkg")
    print("have nexus points")

    meta_data = pd.read_parquet("/Users/maugh24/FEWS_Share/pfafsetter/v2-model-table.parquet", engine="pyarrow")
    print("have parquet file")

    hydrobasins_sorted = hydrobasins.sort_values(by="SORT", ascending=False)
    nexus_points = nexus_points.to_crs(hydrobasins.crs)

    G = build_graph(meta_data)
    # Built once (was rebuilt every basin iteration in the original version).
    linkno_uscontarea_map = meta_data.set_index("LINKNO")["USContArea"].to_dict()

    basin_inputs = [
        (row.geometry, row["UP_AREA"], row["HYBAS_ID"])
        for _, row in hydrobasins_sorted.iterrows()
    ]

    n_workers = max(cpu_count() - 1, 1)
    results = []
    with Pool(processes=n_workers, initializer=init_worker,
              initargs=(G, nexus_points, linkno_uscontarea_map)) as pool:
        for result in tqdm(pool.imap(process_basin, basin_inputs),
                            total=len(basin_inputs), desc="Matching basins"):
            results.append(result)

    results_df = pd.DataFrame(results)
    results_df.to_csv("/Users/maugh24/FEWS_Share/pfafsetter/resultsNEW22.csv", index=False)
    print(f"Done. Wrote {len(results_df)} rows.")


if __name__ == "__main__":
    main()
