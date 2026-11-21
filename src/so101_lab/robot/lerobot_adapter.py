"""Official LeRobot follower transport. No devices open during import or construction."""

from so101_lab.robot.base import ControlledRobot
import hashlib
import tempfile
import threading
import time
from pathlib import Path

from filelock import FileLock
from so101_lab.domain import KEYS, State
from so101_lab.robot.calibration import validate_calibration


class SO101Robot(ControlledRobot):
    hardware = True

    def __init__(self, port, robot_id, calibration_path, factory=None):
        self.port, self.robot_id = port, robot_id
        self.calibration_path = Path(calibration_path)
        self.factory = factory
        self.device = None
        self.lock = threading.RLock()
        digest = hashlib.sha256(port.encode()).hexdigest()[:20]
        self.ownership = FileLock(str(Path(tempfile.gettempdir()) / f"so101-lab-{digest}.lock"))

    def connect(self):
        validate_calibration(self.calibration_path)
        self.ownership.acquire(timeout=0)
        try:
            if self.factory:
                device = self.factory()
            else:
                from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

                class CommissionedFollower(SO101Follower):
                    def configure(inner):
                        if not inner.is_calibrated:
                            raise ValueError(
                                "Motor calibration differs from saved file; run official calibration"
                            )
                        # Avoid enabling torque against a goal left over from a prior session.
                        # Official bus API, used only at operator-supervised connection.
                        with inner.bus.torque_disabled():
                            measured = inner.bus.sync_read("Present_Position")
                            inner.bus.sync_write("Goal_Position", measured)
                            super().configure()

                device = CommissionedFollower(
                    SO101FollowerConfig(
                        port=self.port,
                        id=self.robot_id,
                        calibration_dir=self.calibration_path.parent,
                        use_degrees=True,
                        max_relative_target=2.0,
                        disable_torque_on_disconnect=False,
                    )
                )
            if not device.calibration:
                raise ValueError("LeRobot did not load saved calibration")
            device.connect(calibrate=False)
            self.device = device
            if not device.is_calibrated:
                raise ValueError("Uncalibrated follower")
            self.get_state()
        except Exception:
            if "device" in locals() and getattr(device, "is_connected", False):
                device.disconnect()
            self.device = None
            self.ownership.release()
            raise

    def get_state(self):
        with self.lock:
            if self.device is None or not self.device.is_connected:
                raise ConnectionError("SO-101 disconnected")
            started = time.monotonic()
            observation = self.device.get_observation()
            return State(
                joints={k: float(observation[k]) for k in KEYS},
                sampled_at=started,
                calibrated=bool(self.device.is_calibrated),
            )

    def send(self, targets):
        State(joints=targets)
        with self.lock:
            if self.device is None or not self.device.is_connected:
                raise ConnectionError("SO-101 disconnected")
            if not self.device.is_calibrated:
                raise ValueError("Calibration was lost")
            self.device.send_action(targets)

    def stop(self):
        with self.lock:
            if self.device is not None and self.device.is_connected:
                state = self.get_state()
                if state.calibrated and time.monotonic() - state.sampled_at < 0.3:
                    self.device.send_action(state.joints)
                # Never automatically drop torque on a gravity-loaded arm.

    def disconnect(self):
        with self.lock:
            try:
                self.stop()
            finally:
                try:
                    if self.device is not None and self.device.is_connected:
                        self.device.disconnect()
                finally:
                    self.device = None
                    self.ownership.release()
