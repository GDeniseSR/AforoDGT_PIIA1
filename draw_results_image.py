import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.engine.results import Results

PARKED_COLOR = (0, 0, 255)
PARKED_FILL_ALPHA = 0.2

def draw_parked_boxes(img: np.ndarray, parked_results: Results) -> np.ndarray:
    """Overlay parked detections with a semi-transparent filled box + solid border."""
    if parked_results is None or len(parked_results.boxes) == 0:
        return img

    overlay = img.copy()
    for xyxy in parked_results.boxes.xyxy:
        x1, y1, x2, y2 = map(int, xyxy.tolist())
        cv2.rectangle(overlay, (x1, y1), (x2, y2), PARKED_COLOR, thickness=-1)  # filled

    # Blend the filled overlay onto the image
    img = cv2.addWeighted(overlay, PARKED_FILL_ALPHA, img, 1 - PARKED_FILL_ALPHA, 0)

    # Draw solid border and label on top
    for xyxy in parked_results.boxes.xyxy:
        x1, y1, x2, y2 = map(int, xyxy.tolist())
        cv2.rectangle(img, (x1, y1), (x2, y2), PARKED_COLOR, thickness=2)
        cv2.putText(img, "parked", (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, PARKED_COLOR, 1)

    return img


def draw_results_to_image(moving_results: Results, parked_results: Results | None) -> str:
    """Save annotated image with moving (green) and parked (red, semi-transparent fill) detections."""
    img = moving_results.plot(labels=True, boxes=True)  # draws moving boxes, returns BGR numpy array
    img = draw_parked_boxes(img, parked_results)

    return img