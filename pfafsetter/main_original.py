import pandas as pd
import geopandas as gpd
import networkx as nx

# Define the file path
shapefile_path = "/Users/maugh24/FEWS_Share/hybas_na_lev01-12_v1c/hybas_na_lev08_v1c.shp"

# Read the shapefile into a GeoDataFrame
hydrobasins = gpd.read_file(shapefile_path)
print("have basins")

nexus_points = gpd.read_file("/Users/maugh24/FEWS_Share/pfafsetter/v2-model-table.parquet")
print("have nexus points")

# Define the file path
parquet_file = "/Users/maugh24/FEWS_Share/pfafsetter/model-metadata-table.parquet"
print("have parquet file")

# Read the Parquet file into a DataFrame
meta_data = pd.read_parquet(parquet_file, engine="pyarrow")

hydrobasins_sorted = hydrobasins.sort_values(by="SORT", ascending=False)
nexus_points = nexus_points.to_crs(hydrobasins.crs)
# Step 1: Create the directed graph once outside the loop
# Create a directed graph
G = nx.DiGraph()

# Iterate through meta_data to build the graph using LINKNO and DSLINKNO
for _, row in meta_data.iterrows():
    upstream = str(row["LINKNO"])  # Ensure it's a string for consistency
    downstream = str(row["DSLINKNO"])  # Ensure it's a string for consistency

    # Add an edge from the upstream river to the downstream river
    G.add_edge(upstream, downstream)
results = []

# Step 2: Loop through each hydrobasin and process contained points
for index, basin in hydrobasins_sorted.iterrows():
    basin_area = basin["UP_AREA"]
    # Select nexus points contained within the current hydrobasin
    contained_points = nexus_points[nexus_points.within(basin.geometry)]

    # Extract all USLINKNO values from the contained nexus points
    uslinknos = [ln for sublist in contained_points["USLINKNOs"].str.split(',') for ln in sublist]  # Convert to a list

    # Match each USLINKNO to its corresponding USContArea (converted to km²)
    linkno_uscontarea_map = meta_data.set_index("LINKNO")["USContArea"].to_dict()

    # Filter USContAreas based on the basin_area and add to the filtered dictionary
    filtered_uscontareas = {
        ln: ratio for ln in uslinknos
        if (uscontarea := linkno_uscontarea_map.get(int(ln))) is not None and  # Convert ln to int before lookup
        (ratio := abs((uscontarea / 1e6) / basin_area - 1)) <= 0.50
    }

    # Get the top matches based on the smallest ratio (ascending order)
    top_matches = dict(sorted(filtered_uscontareas.items(), key=lambda item: item[1])[:30])
    print(top_matches)

    # Step 3: Find the best match based on the highest percentage of contained rivers
    best_match = None
    best_percentage = 0

    for uslinkno, _ in top_matches.items():
        # Find all upstream rivers for the current USLINKNO
        upstream_rivers = nx.ancestors(G, uslinkno)  # Get all upstream rivers

        # Calculate how many of the upstream rivers are in the 'contained_rivers' list
        #contained_rivers = set(filtered_uscontareas.keys())  # These are the rivers that match the basin criteria
        contained_upstream_rivers = upstream_rivers.intersection(uslinknos)

        # Calculate the percentage of upstream rivers that are contained
        percentage = len(contained_upstream_rivers) / len(upstream_rivers) if len(upstream_rivers) > 0 else 0

        # Keep track of the best match with the highest percentage
        if percentage > best_percentage:
            best_percentage = percentage
            best_match = uslinkno
            # Step 4: Save the basin ID and the best match into results
        results.append({"Basin_ID": basin["HYBAS_ID"], "Best_Match": best_match, "Match_Percentage": best_percentage})

    # Step 4: Print the best match for the current basin
    print(f"Best match for basin {basin['HYBAS_ID']}: {best_match} with {best_percentage * 100:.2f}% of upstream rivers contained.")

results_df = pd.DataFrame(results)
results_df.to_csv("/Users/maugh24/FEWS_Share/pfafsetter/resultsNEW22.csv")
