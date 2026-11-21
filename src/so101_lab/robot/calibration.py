import hashlib
import json
import os
from pathlib import Path
from so101_lab.domain import JOINTS


def calibration_root():
    if os.getenv("HF_LEROBOT_CALIBRATION"):
        return Path(os.environ["HF_LEROBOT_CALIBRATION"]).expanduser()
    if os.getenv("HF_LEROBOT_HOME"):
        return Path(os.environ["HF_LEROBOT_HOME"]).expanduser() / "calibration"
    return (
        Path(
            os.getenv(
                "HF_HOME", str(Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "huggingface")
            )
        ).expanduser()
        / "lerobot/calibration"
    )


def calibrations():
    result = []
    for name in ("so_follower", "so101_follower"):
        for path in (calibration_root() / "robots" / name).glob("*.json"):
            try:
                digest = validate_calibration(path)
                result.append({"robot_id": path.stem, "path": str(path), "sha256": digest})
            except ValueError:
                continue
    return result


def validate_calibration(path):
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw)
        if set(data) != set(JOINTS):
            raise ValueError("Calibration requires all six motors")
        for index, name in enumerate(JOINTS, 1):
            item = data[name]
            if item["id"] != index or not 0 <= item["range_min"] < item["range_max"] <= 4095:
                raise ValueError(f"Invalid calibration for {name}")
            if not all(k in item for k in ("drive_mode", "homing_offset")):
                raise ValueError("Incomplete motor calibration")
        return hashlib.sha256(raw).hexdigest()
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("A valid saved LeRobot calibration is required") from exc
