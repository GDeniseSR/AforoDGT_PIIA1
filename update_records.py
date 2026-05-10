from timeit import default_timer as timer

from ultralytics import YOLO
from ultralytics.engine.results import Results
import torch
import os
import cv2
import glob
import time
import json
import logging
import tempfile
import requests
from tqdm import tqdm
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from arcgis.gis import GIS
from arcgis.features import Feature, FeatureLayer, Table
from typing import Any
from dotenv import load_dotenv

from utils import log_result, get_layers, get_tables, query_table
from draw_results_image import draw_results_to_image
from processing_lock import acquire_lock
from logging_settings import setup_logging

DGT_ITEM_ID = '8061c55d6a9a481885fa8f913101dcdd'
AFORO_ITEM_ID = '3f0ffdcab0a146988db816ce8426cd38'
BATCH_SIZE = 35
CLASS_BICYCLE, CLASS_CAR, CLASS_MOTORCYCLE, CLASS_BUS, CLASS_TRUCK = 1, 2, 3, 5, 7

FILTER_REQUIRED_DETECTIONS = 2
FILTER_WINDOW_SIZE = 4
FILTER_IOU_THRESHOLD = 0.4
FILTER_MAX_AGE_MINUTES = 60

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
    return model(batch_urls, conf=0.15, imgsz=800, classes=classes, verbose=False)

def fetch_recent_bboxes(bbox_table: Table, camera_ids: list[str], window_size: int, max_age_minutes: int) -> dict[str, list[list[dict]]]:
    """Fetch the last window_size-1 bbox records per camera. Returns {camera_id: [[bboxes_frame_0], [bboxes_frame_1], ...]}"""
    if not camera_ids:
        return {}
    
    history: dict[str, list[list[dict]]] = {cid: [] for cid in camera_ids}

    cutoff_ms = int((datetime.now(tz=timezone.utc) - timedelta(minutes=max_age_minutes)).timestamp() * 1000)
    ids_expr = ",".join(f"'{cid}'" for cid in camera_ids)
    where_expr = f"id_camara IN ({ids_expr})"

    rows = query_table(bbox_table, where=where_expr, fields="id_camara,bboxes,timestamp_registro", order_by="id_camara,timestamp_registro DESC")
    
    for row in rows:
        cam_id = row["id_camara"]
        raw    = row["bboxes"]
        ts     = row["timestamp_registro"] or 0
        if raw and ts >= cutoff_ms and len(history[cam_id]) < window_size - 1:
            history[cam_id].append(json.loads(raw))

    return history

def compute_iou(box_a: list[float], box_b: list[float]) -> float:
    """Compute IoU between two [x1,y1,x2,y2] boxes."""
    xa1, ya1, xa2, ya2 = box_a
    xb1, yb1, xb2, yb2 = box_b

    ix1, iy1 = max(xa1, xb1), max(ya1, yb1)
    ix2, iy2 = min(xa2, xb2), min(ya2, yb2)
    inter    = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0

    area_a = (xa2 - xa1) * (ya2 - ya1)
    area_b = (xb2 - xb1) * (yb2 - yb1)
    return inter / (area_a + area_b - inter)

def is_parked(box_xyxy: list[float], cls: int, frame_history: list[list[dict]], required_detections: int, iou_threshold: float, classes_to_filter: list[int]) -> bool:
    """Return True if box_xyxy of a filtered class matches a detection in at least required_detections historical frames."""
    if cls not in classes_to_filter:
        return False
    matches = 0
    for frame_bboxes in frame_history:
        for prev in frame_bboxes:
            if prev["cls"] == cls and compute_iou(box_xyxy, prev["xyxy"]) >= iou_threshold:
                matches += 1
                break  # one match per frame is enough
    return matches >= required_detections

def filter_parked_from_result(result: Results, camera_history: list[list[dict]], required_detections: int, iou_threshold: float, classes_to_filter: list[int]) -> Results:
    """Remove static detections of filtered classes from a single Results object. Modifies result in place."""
    device = result.boxes.xyxy.device
    keep_mask = torch.ones(len(result.boxes), dtype=torch.bool, device=device)

    for i, (xyxy, cls) in enumerate(zip(result.boxes.xyxy, result.boxes.cls)):
        if is_parked(xyxy.tolist(), int(cls), camera_history, required_detections, iou_threshold, classes_to_filter):
            keep_mask[i] = False

    moving = result[keep_mask]
    parked = result[~keep_mask]
    return moving, parked

def filter_parked_vehicles(results: list[Results], cameras_batch: list[dict], bbox_table: Table, required_detections: int, window_size: int, max_age_minutes: int, iou_threshold: float = 0.5, classes_to_filter: list[int] = [CLASS_CAR]) -> list[Results]:
    """Spatio-temporal persistence filtering over a batch. Removes static detections from results."""
    results = results.copy()

    camera_ids = [cam["id"] for cam in cameras_batch]
    history    = fetch_recent_bboxes(bbox_table, camera_ids, window_size, max_age_minutes)
    parked_results = [None] * len(results)

    for idx, result in enumerate(results):
        cam_id         = cameras_batch[idx]["id"]
        camera_history = history.get(cam_id, [])

        if len(camera_history) < required_detections:
            continue # Not enough history to do temporal NMS

        results[idx], parked_results[idx] = filter_parked_from_result(result, camera_history, required_detections, iou_threshold, classes_to_filter)

    return results, parked_results

def build_bbox_feature(camera_id: str, timestamp: int, result: Results) -> Feature:
    """Serialize bboxes from a single Results object into a table-ready dict."""
    boxes = result.boxes
    bboxes = [
        {
            "xyxy": boxes.xyxy[i].tolist(),
            "conf": float(boxes.conf[i]),
            "cls":  int(boxes.cls[i])
        }
        for i in range(len(boxes))
    ]
    return Feature(
        attributes={
            "id_camara":          camera_id,
            "timestamp_registro": timestamp,
            "bboxes":             json.dumps(bboxes),
        }
    )

def insert_bbox_records(bbox_table: Table, cameras_batch: list[dict], results: list[Results]) -> None:
    """Insert one bbox row per camera into the bbox table. Called after filtering."""
    records = [
        build_bbox_feature(cam["id"], cam["timestamp_registro"], result)
        for cam, result in zip(cameras_batch, results)
    ]
    res = bbox_table.edit_features(adds=records)
    log_result(res, msg="Bounding boxes inserted", insert=True)

def delete_old_bbox_records(bbox_table: Table, camera_ids: list[str], window_size: int, max_age_minutes:int) -> None:
    """Delete rows beyond window_size per camera, keeping only the most recent ones."""
    if not camera_ids:
        return

    cutoff_ms  = int((datetime.now(tz=timezone.utc) - timedelta(minutes=max_age_minutes)).timestamp() * 1000)
    ids_expr   = ",".join(f"'{cid}'" for cid in camera_ids)
    where_expr = f"id_camara IN ({ids_expr})"

    rows = query_table(bbox_table, where=where_expr, fields="OBJECTID,id_camara,timestamp_registro", order_by="id_camara,timestamp_registro DESC")
    
    # Group OBJECTIDs by camera, already sorted newest-first
    camera_objectids: dict[str, list[int]] = {cid: [] for cid in camera_ids}
    for row in rows:
        cam_id = row["id_camara"]
        camera_objectids[cam_id].append((row["OBJECTID"], row["timestamp_registro"]))

    to_delete = []
    for objectids in camera_objectids.values():
        for i, (oid, ts) in enumerate(objectids):
            if i >= window_size or ts < cutoff_ms:
                to_delete.append(oid)

    if not to_delete:
        return

    bbox_table.edit_features(deletes=[{"objectId": oid} for oid in to_delete])
    logging.info(f"Deleted {len(to_delete)} stale bbox records.")

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

def build_raw_feature(camera_id: str, long: float, lat: float, timestamp: int, stats: dict) -> Feature:
    """Append one row to detecciones_raw. Called from process_batch."""
    attributes = {
        "id_camara" : camera_id,
        "timestamp_registro" : timestamp,
        **stats,
    }
    geometry = {"x": long,
                "y": lat,
                "spatialReference": {"wkid": 4326}}
    return Feature(geometry=geometry, attributes=attributes)

def insert_raw_features(layer : FeatureLayer, features: list[Feature]) -> None:
    """Inserts raw detections into the specified layer."""
    result = layer.edit_features(adds=features)
    log_result(result, msg="Raw detections inserted", insert=True)

def save_results_temp_image(moving_results : Results, parked_results : Results) -> str:
    """Save annotated image from results to temp file, return path."""
    tmp = tempfile.NamedTemporaryFile(prefix="aforo_", suffix=".jpg", delete=False)
    img = draw_results_to_image(moving_results, parked_results)
    cv2.imwrite(tmp.name, img)
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

def process_batch(
    model: YOLO,
    cameras_layer: FeatureLayer,
    raw_layer: FeatureLayer,
    bbox_table: Table,
    cameras_batch: list[dict[str, Any]],
    id_to_objectid: dict[str, int],
    classes: list[int],
    filter_required_detections: int,
    filter_window_size: int,
    filter_iou_threshold: float,
    classes_to_filter: list[int],
    filter_max_age_minutes: int,
) -> dict[str, int]:
    
    """Infer -> upsert -> attach for one batch. Discards images before returning."""
    urls = [camera['imagen'] for camera in cameras_batch]
    logging.debug("Running inference...")
    results = run_inference(model, urls, classes)

    logging.debug("Filtering parked vehicles...")
    moving_results, parked_results = filter_parked_vehicles(results, cameras_batch, bbox_table, filter_required_detections, filter_window_size, filter_max_age_minutes, filter_iou_threshold, classes_to_filter)

    total_before  = sum(len(r.boxes) for r in results)
    total_after   = sum(len(r.boxes) for r in moving_results)
    total_parked  = sum(len(r.boxes) for r in parked_results if r is not None)
    logging.debug(f"Parked filter: {total_before} detections -> {total_after} moving, {total_parked} parked ({total_before - total_after} removed)")

    logging.debug("Inserting raw bbox records...")
    insert_bbox_records(bbox_table, cameras_batch, results)
    del results
    logging.debug("Deleting old bbox records...")
    delete_old_bbox_records(bbox_table, [cam["id"] for cam in cameras_batch], filter_window_size, filter_max_age_minutes)

    img_paths = {}
    features = []
    raw_features = []

    logging.debug(f"Building features for every camera's results...")
    for idx, r in enumerate(moving_results):
        camera = cameras_batch[idx]
        stats = extract_stats(r)
        img_paths[camera["id"]] = save_results_temp_image(r, parked_results[idx])

        features.append(build_camera_feature(camera, stats))
        stats.pop("total_vehiculos")
        raw_features.append(
            build_raw_feature(camera["id"], float(camera["longitud"]), float(camera["latitud"]), camera["timestamp_registro"], stats)
        )
    
    logging.debug("Features completed.")

    logging.debug("Uploading features to ArcGIS...")
    id_to_objectid = upsert_camera_features(cameras_layer, features, id_to_objectid)
    insert_raw_features(raw_layer, raw_features)
    logging.debug("Feature uploading complete.")
    
    logging.debug("Uploading attachments to ArcGIS...")
    status_updates = []
    for camera in tqdm(cameras_batch, desc="Updating attachments"):
        cam_id = camera["id"]
        success = replace_attachment(cameras_layer, id_to_objectid[cam_id], img_paths[cam_id])

        status_updates.append(Feature(attributes={
            "OBJECTID": id_to_objectid[cam_id],
            "estado": "actualizado" if success else "error_imagen"
        }))

        os.unlink(img_paths[cam_id])
    logging.debug("Attachment uploading complete.")

    cameras_layer.edit_features(updates=status_updates)
    logging.debug("Status update complete")

    return id_to_objectid

def process_cameras(
    model : YOLO,
    cameras_layer : FeatureLayer,
    raw_layer : FeatureLayer,
    bbox_table : Table,
    cameras : list[dict[str, Any]],
    last_camera_records : dict[str, datetime],
    id_to_objectid : dict[str, int],
    batch_size : int,
    classes : list[int],
    filter_required_detections: int,
    filter_window_size: int,
    filter_iou_threshold: float,
    classes_to_filter: list[int],
    filter_max_age_minutes: int,
) -> dict[str, int]:
    
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

        id_to_objectid = process_batch(model, cameras_layer, raw_layer, bbox_table, cameras_to_process, id_to_objectid, classes, filter_required_detections, filter_window_size, filter_iou_threshold, classes_to_filter, filter_max_age_minutes)
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
    raw_layer = layers_aforo[1]

    bbox_table = get_tables(gis, AFORO_ITEM_ID)[2]

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
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = YOLO("yolo26l.pt", task="detect")
    model.to(device)

    logging.debug("Start processing.")
    start = timer()
    _ = process_cameras(
        model,
        current_layer,
        raw_layer,
        bbox_table,
        cameras_dgt,
        last_camera_records,
        id_to_objectid,
        batch_size=BATCH_SIZE,
        classes=[1, 2, 3, 5, 7],
        filter_required_detections=FILTER_REQUIRED_DETECTIONS,
        filter_window_size=FILTER_WINDOW_SIZE,
        filter_iou_threshold=FILTER_IOU_THRESHOLD,
        classes_to_filter=[1, 2, 3, 5, 7],
        filter_max_age_minutes=FILTER_MAX_AGE_MINUTES
    )
    elapsed = timer() - start
    logging.info(f"=== SCRIPT END | Duration: {elapsed:.2f}s ===")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error in main run")
        raise