from ultralytics import YOLO
from ultralytics.engine.results import Results
import os
import math
import tempfile
import requests
import pandas as pd
from tqdm import tqdm
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from arcgis.gis import GIS
from arcgis.features import GeoAccessor, FeatureSet, Feature, FeatureCollection, FeatureLayer, FeatureLayerCollection, Table
from arcgis.geometry import Point
from arcgis import geometry
from typing import Any
from dotenv import load_dotenv

from utils import print_result


AFORO_ITEM_ID = '3f0ffdcab0a146988db816ce8426cd38'

# Time to retain raw records for, after that, the records are up for deletion once they've been processed
RECORD_RETENTION_MINUTES = 24 * 60 
SAMPLE_INTERVAL_MINUTES = 6.0
ALPHA = 0.25
TIMESLOTS = [
    {"label" : "madrugada",          "start" : 0,      "end" : 7    },
    {"label" : "hora_punta_mañana",  "start" : 7,      "end" : 10   },
    {"label" : "media_mañana",       "start" : 10,     "end" : 13.5 },
    {"label" : "hora_comida",        "start" : 13.5,   "end" : 16   },
    {"label" : "tarde",              "start" : 16,     "end" : 20.5 },
    {"label" : "noche",              "start" : 20.5,   "end" : 24   },
]
TIMESLOT_ORDER = {slot["label"]: i for i, slot in enumerate(TIMESLOTS)}
TIMESLOT_N_CAP = {
    slot["label"] : math.ceil(max(1, (slot["end"] - slot["start"]) * (60 / SAMPLE_INTERVAL_MINUTES)))
    for slot in TIMESLOTS
}


def get_tables(gis, item_id) -> list[Table]:
    item = gis.content.get(item_id)
    flc = FeatureLayerCollection(item.url, gis=gis)
    return flc.tables

def query_table(table: Table, where: str = "1=1", fields: str = "*", n: int = -1, order_by: str | None = None) -> list[dict[str, Any]]:
    """Paginate through all records in an ArcGIS table matching the where clause."""
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
            order_by_fields=order_by,
        )
        results.extend(chunk.features)
        offset += len(chunk.features)
        if len(chunk.features) < chunk_size:
            break
    return [f.attributes for f in results]

def get_timeslot(dt: datetime) -> str | None:
    """Return the timeslot label for a given datetime, or None if it falls in a gap.
    Does not handle timeslot overlaps."""
    hour = dt.hour + dt.minute / 60

    for slot in TIMESLOTS:
        if slot["start"] <= hour < slot["end"]:
            return slot["label"]
    
    return None

def group_by_timeslot_camera(rows: list[dict]) -> dict[tuple, dict[str, list[dict]]]:
    """Group rows into nested dict: (date, timeslot) -> camera_id -> [rows]."""
    grouped = {}
    for row in rows:
        dt = datetime.fromtimestamp(row["timestamp_registro"] / 1000, tz=timezone.utc).astimezone(ZoneInfo("Europe/Madrid"))
        slot = get_timeslot(dt)
        if slot is None:
            continue
        
        key = (dt.date(), slot)
        grouped.setdefault(key, {}).setdefault(row["id_camara"], []).append(row)
    return grouped

def get_complete_timeslots(grouped: dict[tuple, dict[str, list[dict]]]) -> dict[tuple, dict[str, list[dict]]]:
    """Always drops last timeslot as it may be incomplete. Log gaps in timeslot sequence."""
    if len(grouped) < 2:
        return {}

    ordered_keys = sorted(grouped.keys(), key=lambda x: (x[0], TIMESLOT_ORDER[x[1]]))
    
    n_slots = len(TIMESLOTS)
    ref_date = ordered_keys[0][0]

    def absolute_index(key: tuple) -> int:
        date, slot = key
        return (date - ref_date).days * n_slots + TIMESLOT_ORDER[slot]

    for i in range(1, len(ordered_keys)):
        prev_key = ordered_keys[i - 1]
        curr_key = ordered_keys[i]
        gap = absolute_index(curr_key) - absolute_index(prev_key)
        if gap > 1:
            print(f"Gap detected: {gap - 1} timeslot(s) skipped between {prev_key[0]} {prev_key[1]} and {curr_key[0]} {curr_key[1]}")

    complete_keys = ordered_keys[:-1]
    return {key: grouped[key] for key in complete_keys}

def aggregate_timeslot_camera(records: list[dict[str, Any]]) -> dict[str, float]:
    """For a list of records from one camera in one timeslot, return mean/max of vehicle counts."""
    n = len(records)

    n_cars        = [r["num_coches"]     for r in records]
    n_trucks      = [r["num_camiones"]   for r in records]
    n_buses       = [r["num_buses"]      for r in records]
    n_motorcycles = [r["num_motos"]      for r in records]
    n_bicycles    = [r["num_bicicletas"] for r in records]
    total = [
        c + t + b + m + bi
        for c, t, b, m, bi in zip(
            n_cars, n_trucks, n_buses, n_motorcycles, n_bicycles
        )
    ]

    return {
        "media_coches":     sum(n_cars) / n,
        "max_coches":       max(n_cars),
        "media_camiones":   sum(n_trucks) / n,
        "max_camiones":     max(n_trucks),
        "media_buses":      sum(n_buses) / n,
        "max_buses":        max(n_buses),
        "media_motos":      sum(n_motorcycles) / n,
        "max_motos":        max(n_motorcycles),
        "media_bicicletas": sum(n_bicycles) / n,
        "max_bicicletas":   max(n_bicycles),
        "media_total":      sum(total) / n,
        "max_total":        max(total),
    }

def compute_effective_alpha(alpha: float, n_new: int, timeslot: str) -> float:
    """Scale alpha based on how complete the timeslot is."""
    if n_new <= 0:
        return 0.0

    n_cap = TIMESLOT_N_CAP[timeslot]
    scale = min(1.0, n_new / n_cap)
    return alpha * scale

def update_ema_values(old_values: dict[str, float] | None, new_values: dict[str, float], timeslot : str, n_records : int, alpha: float) -> dict:
    if old_values is None:
        return new_values.copy()
    
    eff_alpha = compute_effective_alpha(alpha, n_records, timeslot)
    
    updated = {}    
    for key in new_values:
        old = old_values.get(key)
        new = new_values[key]

        if old is None:
            updated[key] = new
        else:
            updated[key] = (1 - eff_alpha) * old + eff_alpha * new

    return updated

def build_aggregate_feature(camera_id : str, day_of_week : int, timeslot_name : str, n_records : int, last_update : int, aggregates : dict) -> Feature:
    """Append one row to detecciones_raw. Called from process_batch."""
    attributes = {
        "id_camara"            : camera_id,
        "dia_semana"           : day_of_week,
        "timeslot"             : timeslot_name,
        "n_observaciones"      : n_records,
        "ultima_actualizacion" : last_update,
        **aggregates,
    }
    return Feature(attributes=attributes)

def upsert_ema_features(table : Table, features: list[Feature], id_to_objectid: dict[tuple[str, int, str], int]) -> None:
    """Push adds/updates into EMAs table"""
    to_add, to_update = [], []

    for f in features:
        cam_id = f.attributes["id_camara"]
        day_of_week = f.attributes["dia_semana"]
        timeslot = f.attributes["timeslot"]
        key = (cam_id, day_of_week, timeslot)
        if key in id_to_objectid:
            f.attributes["OBJECTID"] = id_to_objectid[key]
            to_update.append(f)
        else:
            to_add.append(f)

    if to_update:
        result = table.edit_features(updates=to_update)
        print_result(result, msg="EMAs updated for existing timeslots", insert=False)

    if to_add:
        result = table.edit_features(adds=to_add)
        print_result(result, msg="EMAs added for new timeslots", insert=True)

def mark_processed(table : Table, timestamp : int, record_ids: list[int]) -> None:
    """Set timestamp_procesado on the given record OBJECTIDs."""
    processed_updates = [
        Feature(attributes={
            "OBJECTID" : objectid,
            "timestamp_procesado" : timestamp
        })
        for objectid in record_ids
    ]
    table.edit_features(updates=processed_updates)

def delete_old_records(table: Table, cutoff_minutes: int = 1440) -> None:
    """Delete records older than cutoff_minutes that have already been processed."""
    cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=cutoff_minutes)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    rows = query_table(
        table,
        where=f"timestamp_registro < TIMESTAMP '{cutoff_str}' AND timestamp_procesado IS NOT NULL",
        fields="OBJECTID"
    )

    if not rows:
        print("No old records to delete.")
        return

    object_ids = [r["OBJECTID"] for r in rows]
    result = table.edit_features(deletes=object_ids)
    print(f"Deleted {len(object_ids)} old records.")


def process_raw_batch(batch_timeslots : dict[tuple, dict[str, list[dict]]], raw_table : Table, ema_table : Table, alpha : float = 0.3):
    print("Retrieving previous EMA values")
    ema_existing = query_table(ema_table)
    ema_existing_indexed = {
        (
            r["id_camara"],
            r["dia_semana"],
            r["timeslot"]
        ) : r
        for r in ema_existing
    }
    del ema_existing
    

    ema_id_to_objectid : dict[tuple[str, int, str], int] = {}
    features : list[Feature] = []
    for (day, timeslot), cameras in batch_timeslots.items():
        day_of_week = day.weekday()

        for camera_id, records in cameras.items():
            new_aggregates = aggregate_timeslot_camera(records)

            old_ema = ema_existing_indexed.get((camera_id, day_of_week, timeslot))
            
            if old_ema is not None:
                ema_id_to_objectid[(camera_id, day_of_week, timeslot)] = old_ema["OBJECTID"]
            
            n = len(records)
            
            new_ema_values = update_ema_values(
                old_values=old_ema,
                new_values=new_aggregates,
                timeslot=timeslot,
                n_records=n,
                alpha=alpha
            )
            feature = build_aggregate_feature(
                camera_id,
                day_of_week,
                timeslot,
                n,
                max(r["timestamp_registro"] for r in records),
                new_ema_values
            )
            features.append(feature)
    
    print("Uploading new EMA values...")
    upsert_ema_features(ema_table, features, ema_id_to_objectid)
    
    print("Marking raw values as processed...")
    processed_record_ids = [
        r["OBJECTID"]
        for cameras in batch_timeslots.values()
        for records in cameras.values()
        for r in records
    ]
    
    chunk_size = math.ceil(len(processed_record_ids) / 3)
    for i in range(0, len(processed_record_ids), chunk_size):
        mark_processed(
            raw_table,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            record_ids=processed_record_ids[i:i+chunk_size],
        )    
    
def process_raw_data(raw_table, ema_table, batch_size=15000, alpha: float = 0.3) -> None:
    """Main orchestrator. Fetch, group, aggregate, and update EMA.
    
    batch_size must be greater than the maximum record count in a timeslot.
    """
    iteration = 0
    while True:
        iteration += 1
        print(f"\nBatch {iteration}: querying up to {batch_size} unprocessed rows...")
        rows = query_table(
            raw_table,
            where="timestamp_procesado IS NULL",
            fields="*",
            n=batch_size,
            order_by="timestamp_registro ASC",
        )
        print(f"{len(rows)} rows fetched")
        
        if not rows:
            print("Nothing left to process.")
            break
        
        grouped = group_by_timeslot_camera(rows)
        complete_timeslots = get_complete_timeslots(grouped)
        print(f"{len(grouped)} timeslots in batch, {len(complete_timeslots)} complete")
        
        # all rows are in the current incomplete timeslot
        if not complete_timeslots:
            if len(rows) >= batch_size:  # we hit the batch cap
                print(f"WARNING: batch size ({batch_size}) may be smaller than a single timeslot. Consider increasing it.")
            break
        
        process_raw_batch(complete_timeslots, raw_table, ema_table, alpha)
        print(f"Finished batch {iteration}")
        print("Deleting old raw records...")
        delete_old_records(raw_table, cutoff_minutes=RECORD_RETENTION_MINUTES)
    
    print("Deleting old raw records...")
    delete_old_records(raw_table, cutoff_minutes=RECORD_RETENTION_MINUTES)
    
    
if __name__ == "__main__":
    load_dotenv()

    gis = GIS("https://xuntasix.maps.arcgis.com",
              os.environ["ARCGIS_USERNAME"],
              os.environ["ARCGIS_PASSWORD"])

    tables = get_tables(gis, AFORO_ITEM_ID)
    raw_table = tables[0]
    ema_table = tables[1]

    print("Starting processing...")
    process_raw_data(raw_table, ema_table, batch_size=15000, alpha=ALPHA)
    print("Done.")