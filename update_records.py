from timeit import default_timer as timer

from ultralytics import YOLO
from ultralytics.engine.results import Results
import os
import glob
import time
import logging
import tempfile
import requests
import pandas as pd
from tqdm import tqdm
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from arcgis.gis import GIS
from arcgis.features import GeoAccessor, FeatureSet, Feature, FeatureCollection, FeatureLayer, FeatureLayerCollection, Table
from arcgis.geometry import Point
from arcgis import geometry
from typing import Any
from dotenv import load_dotenv

from utils import log_result
from processing_lock import acquire_lock
from logging_settings import setup_logging

DGT_ITEM_ID = '8061c55d6a9a481885fa8f913101dcdd'
AFORO_ITEM_ID = '3f0ffdcab0a146988db816ce8426cd38'
CLASS_BICYCLE, CLASS_CAR, CLASS_MOTORCYCLE, CLASS_BUS, CLASS_TRUCK = 1, 2, 3, 5, 7

def get_layers(gis, item_id) -> list[FeatureLayer]:
    item = gis.content.get(item_id)
    flc = FeatureLayerCollection(item.url, gis=gis)
    return flc.layers

def get_tables(gis, item_id) -> list[Table]:
    item = gis.content.get(item_id)
    flc = FeatureLayerCollection(item.url, gis=gis)
    return flc.tables

def get_cameras(layer : FeatureLayer, where_expr : str = "1 = 1", fields : list[str] | None = None) -> list[dict[str, Any]]:
    if fields is None:
        fields = []
    else:
        valid = [field["name"] for field in layer.properties.fields]
        invalid_fields = [f for f in fields if f not in valid]
        if invalid_fields:
            raise ValueError(f"Fields not found: {invalid_fields}. Available: {valid}")

    if len(fields) == 0:
        fields = [
            "id", "pk", "sentido", "carretera", "provincia",
            "latitud", "longitud", "imagen",
            "NATCODE", "NAMEUNIT", "CODNUT1", "CODNUT2", "CODNUT3"
        ]

    raw_features = layer.query(
        where=where_expr,
        out_fields=",".join(fields),
        return_geometry=False
    )

    cameras = [f.attributes for f in raw_features]
    return cameras

def get_last_cameras_update(cameras: list[dict]) -> dict[str, datetime]:
    last_update = {}

    for camera in tqdm(cameras, desc="Fetching Last-Modified headers"):
        camera_id = camera["id"]
        url = camera["imagen"]
        time.sleep(0.1)

        try:
            response = requests.head(url, timeout=5)
            last_modified_str = response.headers.get("Last-Modified")
            if last_modified_str is None:
                logging.warning(f"No Last-Modified header for camera {camera_id} from {url}")
                continue

            # Parse datetime from string, and change timezone to Madrid. Then remove timezone for easier comparisons
            last_modified_dt = datetime.strptime(last_modified_str, "%a, %d %b %Y %H:%M:%S %Z")
            last_modified_dt = last_modified_dt.replace(tzinfo=timezone.utc)
            last_modified_dt = last_modified_dt.astimezone(ZoneInfo("Europe/Madrid"))

            last_update[camera_id] = last_modified_dt

        except requests.RequestException as e:
            logging.warning(f"Error fetching header for camera {camera_id}: {e}")

    return last_update

def run_inference(model : YOLO, batch_urls: list[str], classes: list[int]) -> list[Results]:
    """Run YOLO on URLs with class filter."""
    return model(batch_urls, conf=0.2, classes=classes, verbose=False)

def extract_stats(result : Results) -> dict[str, int]:
    """Extract vehicle counts from a single YOLO result."""
    classes = result.boxes.cls
    n_cars      = int((classes == CLASS_CAR).sum())
    n_trucks    = int((classes == CLASS_TRUCK).sum())
    n_buses     = int((classes == CLASS_BUS).sum())
    n_motorcycles  = int((classes == CLASS_MOTORCYCLE).sum())
    n_bicycles  = int((classes == CLASS_BICYCLE).sum())
    cam_stats = {
        "num_coches" : n_cars,
        "num_camiones" : n_trucks,
        "num_buses" : n_buses,
        "num_motos" : n_motorcycles,
        "num_bicicletas" : n_bicycles,
        "total_vehiculos" : n_cars + n_trucks + n_buses + n_motorcycles + n_bicycles,
    }
    return cam_stats

def build_camera_feature(camera: dict, stats: dict, estado: str = "pendiente") -> Feature:
    """Combine camera attributes + stats into an ArcGIS Feature."""
    attributes = {**camera, **stats, "estado":estado}
    geometry = {"x": float(attributes.pop("longitud")), 
                "y": float(attributes.pop("latitud")),
                "spatialReference": {"wkid": 4326}}
    return Feature(geometry=geometry, attributes=attributes)

def upsert_camera_features(layer : FeatureLayer, features: list[Feature], id_to_objectid: dict[str, int]) -> dict[str, int]:
    """Push adds/updates, return updated id -> OBJECTID map."""
    to_add, to_update = [], []

    for f in features:
        cam_id = f.attributes["id"]
        if cam_id in id_to_objectid:
            f.attributes["OBJECTID"] = id_to_objectid[cam_id]
            to_update.append(f)
        else:
            to_add.append(f)

    if to_update:
        result = layer.edit_features(updates=to_update)
        log_result(result, msg="Cameras updated", insert=False)

    if to_add:
        result = layer.edit_features(adds=to_add)
        log_result(result, msg="Cameras added", insert=True)
        # Map new OBJECTIDs back- Order of addResults matches order of adds
        for feature, add_result in zip(to_add, result["addResults"]):
            if add_result.get("success"):
                id_to_objectid[feature.attributes["id"]] = add_result["objectId"]

    return id_to_objectid

def build_raw_feature(camera_id: str, timestamp: int, stats: dict) -> Feature:
    """Append one row to detecciones_raw. Called from process_batch."""
    attributes = {
        "id_camara" : camera_id,
        "timestamp_registro" : timestamp,
        **stats,
    }
    return Feature(attributes=attributes)

def insert_raw_features(table : Table, features: list[Feature]) -> None:
    """Push adds/updates, return updated id -> OBJECTID map."""
    result = table.edit_features(adds=features)
    log_result(result, msg="Raw detections inserted", insert=True)

def save_temp_image(result : Results) -> str:
    """Save annotated image from results to temp file, return path."""
    tmp = tempfile.NamedTemporaryFile(prefix="aforo_", suffix=".jpg", delete=False)
    result.save(filename=tmp.name)
    return tmp.name

def replace_attachment(layer : FeatureLayer, objectid: int, img_path: str) -> bool:
    try:
        existing = layer.attachments.get_list(objectid)
        for att in existing:
            layer.attachments.delete(objectid, att["id"])
        
        res = layer.attachments.add(objectid, img_path)
        return res.get("addAttachmentResult", {}).get("success", False)
    except Exception as e:
        logging.warning(f"Attachment failed for OBJECTID {objectid}: {e}")
        return False

def process_batch(model : YOLO, layer : FeatureLayer, raw_table : Table, cameras_batch : list[dict[str, Any]], id_to_objectid : dict[str, int], classes : list[int]) -> dict[str, int]:
    """Infer -> upsert -> attach for one batch. Discards images before returning."""
    urls = [camera['imagen'] for camera in cameras_batch]
    logging.debug("Running inference...")
    results = run_inference(model, urls, classes)

    img_paths = {}
    features = []
    raw_features = []

    logging.debug(f"Building features for every camera's results...")
    for idx, r in enumerate(results):
        camera = cameras_batch[idx]
        stats = extract_stats(r)
        img_paths[camera["id"]] = save_temp_image(r)

        features.append(build_camera_feature(camera, stats))
        stats.pop("total_vehiculos")
        raw_features.append(build_raw_feature(camera["id"], camera["timestamp_registro"], stats))
    
    logging.debug("Features completed.")

    logging.debug("Uploading features to ArcGIS...")
    id_to_objectid = upsert_camera_features(layer, features, id_to_objectid)
    insert_raw_features(raw_table, raw_features)
    logging.debug("Feature uploading complete.")
    
    logging.debug("Uploading attachments to ArcGIS...")
    status_updates = []
    for camera in tqdm(cameras_batch, desc="Updating attachments"):
        cam_id = camera["id"]
        success = replace_attachment(layer, id_to_objectid[cam_id], img_paths[cam_id])

        status_updates.append(Feature(attributes={
            "OBJECTID": id_to_objectid[cam_id],
            "estado": "actualizado" if success else "error_imagen"
        }))

        os.unlink(img_paths[cam_id])
    logging.debug("Attachment uploading complete.")

    layer.edit_features(updates=status_updates)
    logging.debug("Status update complete")

    return id_to_objectid

def process_cameras(model : YOLO, layer : FeatureLayer, raw_table : Table, cameras : list[dict[str, Any]], last_camera_records : dict[str, datetime], id_to_objectid : dict[str, int], batch_size : int = 15, classes : list[int] = [1, 2, 3, 5, 7]) -> dict[str, int]:
    """Drive process_batch over all cameras."""
    logging.debug("Processing cameras...")

    n_cameras_processed = 0

    for i in range(0, len(cameras), batch_size):
        batch = cameras[i : i + batch_size]
        batch_idx = i // batch_size + 1
        logging.info(f"Starting batch {batch_idx}/{-(-len(cameras) // batch_size)}")
        
        # We get the newest update datetime of all cameras of the batcch
        last_cameras_update = get_last_cameras_update(batch)
                
        # And for each camera, if it's more recent than the one we stored, we must process said camera
        ids_to_process = []
        for cam_id in last_cameras_update.keys():
            last_update = last_cameras_update[cam_id]
            last_record = last_camera_records.get(cam_id, datetime.min.replace(tzinfo=timezone.utc))
            
            if last_update > last_record:
                ids_to_process.append(cam_id)
        
        # We get the camera attributes and add to them the timestamp
        cameras_to_process = [
            {
                **cam,
                "timestamp_registro": int(
                    last_cameras_update[cam["id"]]
                    .timestamp() * 1000
                )
            }
            for cam in cameras
            if cam["id"] in ids_to_process
        ]
        
        logging.info(f"Processing {len(ids_to_process)}/{len(batch)} cameras in batch {batch_idx}")

        id_to_objectid = process_batch(model, layer, raw_table, cameras_to_process, id_to_objectid, classes)
        n_cameras_processed += len(ids_to_process)
    
    logging.info(f"Processed {n_cameras_processed} / {len(cameras)} available cameras.")
    return id_to_objectid


def main():
    setup_logging(app_name="update_records")
    logging.info("=== SCRIPT START ===")
    # Make sure we don't execute twice at the same time
    lock_fd = acquire_lock()

    logging.debug("Removing left tempfile images.")
    # Remove any pending temp images
    for f in glob.glob(os.path.join(tempfile.gettempdir(), "aforo_*.jpg")):
        os.unlink(f)
    
    logging.debug("Start log-in.")
    load_dotenv()
    gis = GIS("https://xuntasix.maps.arcgis.com",
          os.environ["ARCGIS_USERNAME"],
          os.environ["ARCGIS_PASSWORD"])
    
    logging.debug("Logged-in.")

    dgt_layer = get_layers(gis, DGT_ITEM_ID)[0]

    layers_aforo = get_layers(gis, AFORO_ITEM_ID)
    current_layer = layers_aforo[0]
    raw_table = get_tables(gis, AFORO_ITEM_ID)[0]

    logging.debug("Obtained layers and tables.")

    # We get the cameras from Galicia from the DGT, and select values from our own layer's cameras
    cameras_dgt = get_cameras(dgt_layer, where_expr="CODNUT2 = 'ES11'")
    current_cameras = get_cameras(current_layer, fields=["OBJECTID", "id", "imagen", "timestamp_registro"])
    logging.debug("Obtained cameras form layers.")

    # We get the latest registered update of each camera. If there's none we send in the minimum datetime
    last_camera_records = {}
    for c in current_cameras:
        if c["timestamp_registro"] is not None:
            ts = datetime.fromtimestamp(int(c["timestamp_registro"]) / 1000, tz=timezone.utc)
            last_camera_records[c["id"]] = ts.astimezone(ZoneInfo("Europe/Madrid"))

    # id -> OBJECTID map from current_cameras
    id_to_objectid = {c["id"]: c["OBJECTID"] for c in current_cameras}

    logging.debug("Initialize model")
    # We process all images from the dgt and add the stats to the dictionary
    model = YOLO("yolo26l.pt", task="detect")
    logging.debug("Start processing.")
    start = timer()
    _ = process_cameras(
        model,
        current_layer,
        raw_table,
        cameras_dgt,
        last_camera_records,
        id_to_objectid,
        batch_size=50,
        classes=[1, 2, 3, 5, 7]
    )
    elapsed = timer() - start
    logging.info(f"=== SCRIPT END | Duration: {elapsed:.2f}s ===")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error in main run")
        raise