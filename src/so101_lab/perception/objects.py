import cv2
import numpy as np
from so101_lab.perception.calibration import plane_point


def colored_regions(image, registration=None):
    """HSV connected regions. A color region is an estimate, never a verified grasp."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colors = {
        "red": ((0, 100, 60), (10, 255, 255)),
        "blue": ((95, 100, 60), (135, 255, 255)),
        "green": ((35, 90, 50), (85, 255, 255)),
    }
    regions = []
    for color, (low, high) in colors.items():
        mask = cv2.inRange(hsv, np.array(low), np.array(high))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 80:
                continue
            x, y, w, h = cv2.boundingRect(c)
            uv = [x + w / 2, y + h / 2]
            position = None
            if registration:
                try:
                    position = plane_point(registration, uv)
                except ValueError:
                    pass
            regions.append(
                {
                    "id": f"{color}_{len(regions)}",
                    "label": f"{color} region",
                    "pixel": uv,
                    "bbox": [x, y, w, h],
                    "area_px": area,
                    "position_robot": position,
                    "evidence": "HSV segmentation; assumes object lies on registered plane",
                    "confidence": None,
                    "graspable": "unknown",
                }
            )
    return regions
