import time
import cv2
import numpy as np
import pytest
from so101_lab.agents.memory import Memory
from so101_lab.perception.cameras import Cameras, Frame
from so101_lab.perception.calibration import PlaneRegistration, plane_point, validate_plane, detect_markers
from so101_lab.perception.objects import colored_regions


def registration():
    return PlaneRegistration(
        camera_id="0",
        image_points=[(0, 0), (100, 0), (100, 100), (0, 100)],
        robot_points=[(0.1, 0), (0.2, 0), (0.2, 0.1), (0.1, 0.1)],
        plane_z=0.01,
    )


def test_planar_registration_requires_independent_validation():
    r = registration().solve()
    assert not r["validated"]
    with pytest.raises(ValueError):
        plane_point(r, [50, 50])
    r = validate_plane(r, [[25, 25], [75, 75]], [[0.125, 0.025], [0.175, 0.075]])
    assert plane_point(r, [50, 50]) == pytest.approx([0.15, 0.05, 0.01])
    with pytest.raises(ValueError):
        plane_point(r, [200, 200])
    with pytest.raises(ValueError):
        validate_plane(r, [[0, 0], [100, 100]], [[0.1, 0], [0.2, 0.1]])
    with pytest.raises(ValueError):
        validate_plane(r, [[25, 25], [75, 75]], [[0.15, 0.05], [0.2, 0.1]])


def test_degenerate_registration():
    r = registration()
    r.image_points = [(0, 0), (10, 10), (20, 20), (30, 30)]
    with pytest.raises(ValueError):
        r.solve()


def test_camera_failure_and_stale_capture():
    cameras = Cameras()
    with pytest.raises(ValueError):
        cameras.get("0")
    cameras.frames["0"] = Frame(np.zeros((20, 20, 3), np.uint8), time.monotonic() - 5)
    assert not cameras.fresh("0")
    cameras.frames["0"] = Frame(np.zeros((20, 20, 3), np.uint8), time.monotonic())
    assert cameras.fresh("0") and cameras.get("0").jpeg().startswith(b"\xff\xd8")
    with pytest.raises(ValueError):
        cameras.open("https://camera")


def test_aruco_and_color_regions_are_estimates():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    image = np.full((200, 200), 255, np.uint8)
    image[40:160, 40:160] = cv2.aruco.generateImageMarker(dictionary, 7, 120)
    assert detect_markers(image)[0]["id"] == 7
    image = np.zeros((100, 100, 3), np.uint8)
    image[20:70, 20:70] = (0, 0, 255)
    regions = colored_regions(image)
    assert regions[0]["label"] == "red region" and regions[0]["graspable"] == "unknown"
    assert regions[0]["confidence"] is None and regions[0]["position_robot"] is None


def test_memory_recovery_and_secret_redaction(tmp_path):
    key = "secret-test-do-not-record"
    memory = Memory(tmp_path)
    memory.secrets.add(key)
    memory.save("calibration", {"pose": [1, 2, 3]})
    memory.add("provider_error", {"message": "key " + key})
    memory.close()
    memory = Memory(tmp_path)
    assert memory.get("calibration") == {"pose": [1, 2, 3]}
    assert key not in str(memory.events())
    memory.close()
    import os

    if os.name != "nt":
        assert not (tmp_path.stat().st_mode & 0o077)
