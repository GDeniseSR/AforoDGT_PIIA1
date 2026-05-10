from typing import Any
import logging
from arcgis.features import FeatureLayer, FeatureLayerCollection, Table

def get_layers(gis, item_id) -> list[FeatureLayer]:
    item = gis.content.get(item_id)
    flc = FeatureLayerCollection(item.url, gis=gis)
    return flc.layers

def get_tables(gis, item_id) -> list[Table]:
    item = gis.content.get(item_id)
    flc = FeatureLayerCollection(item.url, gis=gis)
    return flc.tables

def query_layer(layer: FeatureLayer, where: str = "1=1", fields: str = "*", n: int = -1, order_by: str | None = None) -> list[dict[str, Any]]:
    """Paginate through n records in an ArcGIS layer matching the where clause."""
    offset = 0
    batch = 1000
    results = []
    while n < 0 or len(results) < n:
        chunk_size = batch if n < 0 else min(batch, n - len(results))
        chunk = layer.query(
            where=where,
            out_fields=fields,
            result_offset=offset,
            result_record_count=chunk_size,
            order_by_fields=order_by,
            return_geometry=False
        )
        results.extend(chunk.features)
        offset += len(chunk.features)
        if len(chunk.features) < chunk_size:
            break
    return [f.attributes for f in results]

def query_table(table: Table, where: str = "1=1", fields: str = "*", n: int = -1, order_by: str | None = None) -> list[dict[str, Any]]:
    """Paginate through n records in an ArcGIS table matching the where clause."""
    offset = 0
    batch = 1000
    results = []
    while n < 0 or len(results) < n:
        chunk_size = batch if n < 0 else min(batch, n - len(results))
        chunk = table.query(
            where=where,
            out_fields=fields,
            result_offset=offset,
            result_record_count=chunk_size,
            order_by_fields=order_by
        )
        results.extend(chunk.features)
        offset += len(chunk.features)
        if len(chunk.features) < chunk_size:
            break
    return [f.attributes for f in results]

def log_result(result, msg="", insert=False):
    key = "addResults" if insert else "updateResults"
    action = "added" if insert else "updated"

    successes = sum(1 for r in result[key] if r.get("success"))
    failures  = [r for r in result[key] if not r.get("success")]

    if msg != "":
        logging.debug(msg)

    logging.debug(f"{successes} {action}, {len(failures)} failed")
    if failures:
        logging.debug(f"Failures: {failures}")
        
def print_result(result, msg="", insert=False):
    key = "addResults" if insert else "updateResults"
    action = "added" if insert else "updated"

    successes = sum(1 for r in result[key] if r.get("success"))
    failures  = [r for r in result[key] if not r.get("success")]

    if msg != "":
        print(msg)

    print(f"{successes} {action}, {len(failures)} failed")
    if failures:
        print("Failures:", failures)