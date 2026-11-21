"""Planar registration: homography is valid only on the measured plane."""

import cv2
import numpy as np
from so101_lab.domain import Validated
from pydantic import Field


class PlaneRegistration(Validated):
    camera_id: str
    image_points: list[tuple[float, float]] = Field(min_length=4, max_length=100)
    robot_points: list[tuple[float, float]] = Field(min_length=4, max_length=100)
    plane_z: float
    max_error_m: float = Field(default=0.003, gt=0, le=0.01)

    def solve(self):
        a, b = np.array(self.image_points, float), np.array(self.robot_points, float)
        if len(a) != len(b) or np.linalg.matrix_rank(np.c_[a, np.ones(len(a))]) < 3:
            raise ValueError("Supply matching non-collinear correspondences")
        if cv2.contourArea(cv2.convexHull(a.astype(np.float32))) < 100:
            raise ValueError("Image calibration points are too close")
        if cv2.contourArea(cv2.convexHull(b.astype(np.float32))) < 0.0001:
            raise ValueError("Robot calibration points are too close")
        h, _ = cv2.findHomography(a, b, 0)
        if h is None or not np.isfinite(h).all() or np.linalg.cond(h) > 1e10:
            raise ValueError("Degenerate camera registration")
        predicted = cv2.perspectiveTransform(a.reshape(-1, 1, 2), h).reshape(-1, 2)
        rms = float(np.sqrt(np.mean(np.sum((predicted - b) ** 2, axis=1))))
        if rms > self.max_error_m:
            raise ValueError("Registration residual exceeds tolerance")
        return {
            **self.model_dump(),
            "homography": h.tolist(),
            "fit_rms_m": rms,
            "independent_validation_required": True,
            "validated": False,
            "limitation": "Planar geometry only; fitting four points is not an accuracy measurement",
        }


def plane_point(registration, uv):
    if not registration.get("validated"):
        raise ValueError("Check held-out calibration points before localization")
    hull = cv2.convexHull(np.array(registration["image_points"], np.float32))
    if cv2.pointPolygonTest(hull, tuple(map(float, uv)), False) < 0:
        raise ValueError("Point lies outside registered image region")
    xy = cv2.perspectiveTransform(np.array([[uv]], float), np.array(registration["homography"]))[0, 0]
    return [float(xy[0]), float(xy[1]), registration["plane_z"]]


def validate_plane(registration, image_points, robot_points):
    if len(image_points) < 2 or len(image_points) != len(robot_points):
        raise ValueError("Use at least two independent measured check points")
    old = np.array(registration["image_points"])
    if any(np.min(np.linalg.norm(old - np.array(p), axis=1)) < 5 for p in image_points):
        raise ValueError("Check points must differ from fitting points")
    r = {**registration, "validated": True}
    predicted = np.array([plane_point(r, p)[:2] for p in image_points])
    errors = np.linalg.norm(predicted - np.array(robot_points), axis=1)
    if float(errors.max()) > registration["max_error_m"]:
        raise ValueError("Independent calibration check failed")
    return {**r, "independent_max_error_m": float(errors.max()), "independent_validation_required": False}


def detect_markers(frame):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    corners, ids, _ = cv2.aruco.ArucoDetector(dictionary).detectMarkers(frame)
    return (
        []
        if ids is None
        else [{"id": int(i), "corners": c[0].tolist()} for i, c in zip(ids.ravel(), corners)]
    )


def intrinsics(object_points, image_points, image_size):
    if len(object_points) < 8 or len(object_points) != len(image_points):
        raise ValueError("Capture at least eight varied checkerboard views")
    rms, matrix, distortion, _, _ = cv2.calibrateCamera(
        [np.array(p, np.float32) for p in object_points],
        [np.array(p, np.float32) for p in image_points],
        tuple(image_size),
        None,
        None,
    )
    if not np.isfinite(rms) or rms > 1.5:
        raise ValueError("Intrinsics reprojection error exceeds 1.5 pixels")
    return {"matrix": matrix.tolist(), "distortion": distortion.tolist(), "rms_px": float(rms)}
