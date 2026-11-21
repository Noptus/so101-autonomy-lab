import inspect
import json
import pytest
from so101_lab.domain import JOINTS
from so101_lab.robot.calibration import validate_calibration
from so101_lab.robot.lerobot_adapter import SO101Robot


@pytest.fixture
def calibration(tmp_path):
    path = tmp_path / "test_arm.json"
    path.write_text(
        json.dumps(
            {
                name: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 100, "range_max": 3900}
                for i, name in enumerate(JOINTS, 1)
            }
        )
    )
    return path


class FakeFollower:
    def __init__(self):
        self.calibration = {"exists": True}
        self.is_connected = False
        self.is_calibrated = True
        self.calls = []
        self.observation = {f"{j}.pos": 0.0 for j in JOINTS}

    def connect(self, calibrate=True):
        self.calls.append(("connect", calibrate))
        self.is_connected = True

    def get_observation(self):
        return dict(self.observation)

    def send_action(self, action):
        self.calls.append(("send", action))
        self.observation = dict(action)
        return action

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.is_connected = False


def test_connection_reads_six_calibrated_motors_and_stop(calibration):
    fake = FakeFollower()
    robot = SO101Robot("/fake/so101", "test_arm", calibration, factory=lambda: fake)
    assert robot.device is None
    robot.connect()
    assert fake.calls[0] == ("connect", False)
    state = robot.get_state()
    assert len(state.joints) == 6 and state.calibrated
    robot.send({**state.joints, "elbow_flex.pos": 1})
    robot.stop()
    assert fake.calls[-1][0] == "send"
    robot.disconnect()
    assert not fake.is_connected
    assert fake.calls[-1][0] == "disconnect"


def test_calibration_missing_or_mismatched_fails_before_motion(calibration, tmp_path):
    with pytest.raises(ValueError):
        SO101Robot("/fake", "arm", tmp_path / "missing.json").connect()
    data = json.loads(calibration.read_text())
    data.pop("gripper")
    calibration.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        validate_calibration(calibration)


def test_uncalibrated_driver_is_rejected(calibration):
    fake = FakeFollower()
    fake.is_calibrated = False
    robot = SO101Robot("/fake/uncalibrated", "test_arm", calibration, factory=lambda: fake)
    with pytest.raises(ValueError):
        robot.connect()
    assert all(c[0] != "send" for c in fake.calls)
    assert not fake.is_connected


def test_bad_feedback_never_substitutes_commanded_position(calibration):
    fake = FakeFollower()
    fake.observation.pop("wrist_roll.pos")
    robot = SO101Robot("/fake/partial", "test_arm", calibration, factory=lambda: fake)
    with pytest.raises(KeyError):
        robot.connect()
    assert not fake.is_connected


def test_installed_lerobot_signatures_and_units():
    module = pytest.importorskip("lerobot.robots.so_follower")
    config = module.SO101FollowerConfig(
        port="/not/opened", id="signature-test", use_degrees=True, max_relative_target=2
    )
    assert config.use_degrees is True
    assert "calibrate" in inspect.signature(module.SO101Follower.connect).parameters
    assert "action" in inspect.signature(module.SO101Follower.send_action).parameters
    assert "calibration_dir" in inspect.signature(module.SO101FollowerConfig).parameters


def test_official_adapter_seeds_current_goal_before_enabling_torque(calibration, monkeypatch):
    module = pytest.importorskip("lerobot.robots.so_follower")
    from contextlib import contextmanager

    calls = []

    class Bus:
        @contextmanager
        def torque_disabled(self):
            calls.append("torque_off")
            yield
            calls.append("torque_restore")

        def sync_read(self, key):
            calls.append("read_" + key)
            return {"joint": 12}

        def sync_write(self, key, value):
            calls.append(("write_" + key, value))

    class OfficialStub(FakeFollower):
        def __init__(self, config):
            super().__init__()
            self.bus = Bus()
            self.config = config

        def connect(self, calibrate=True):
            assert calibrate is False
            self.is_connected = True
            self.configure()

        def configure(self):
            calls.append("official_configure")

    monkeypatch.setattr(module, "SO101Follower", OfficialStub)
    robot = SO101Robot("/fake/official", "test_arm", calibration)
    robot.connect()
    assert calls[:4] == [
        "torque_off",
        "read_Present_Position",
        ("write_Goal_Position", {"joint": 12}),
        "official_configure",
    ]
    assert robot.device.config.disable_torque_on_disconnect is False
    robot.disconnect()


def test_commissioning_reuse_and_calibration_change_invalidates(lab, calibration):
    import time
    import numpy as np
    from so101_lab.domain import ARM, Commissioning, SafetyConfig
    from so101_lab.perception.cameras import Frame

    lab.robot.hardware = True
    lab.robot.robot_id = "test_arm"
    lab.robot.port = "/fake"
    lab.robot.calibration_path = calibration
    lab.cameras.frames["0"] = Frame(np.zeros((10, 10, 3), np.uint8), time.monotonic())
    profile = Commissioning(
        robot_id="test_arm",
        port="/fake",
        calibration_sha256=validate_calibration(calibration),
        safety=SafetyConfig(),
        motor_signs=dict.fromkeys(ARM, 1),
        motor_offsets=dict.fromkeys(ARM, 0.0),
        standby=lab.robot.joints,
        operator_present=True,
        supported_arm=True,
        mapping_verified=True,
        envelope_verified=True,
        camera_id="0",
    )
    lab.controller.stopped.set()
    lab.apply_commissioning(profile)
    assert lab.controller.commissioned and lab.controller.stopped.is_set()
    saved = Commissioning.model_validate(lab.memory.get("commissioning"))
    lab.apply_commissioning(saved, persist=False)
    raw = json.loads(calibration.read_text())
    raw["gripper"]["range_min"] += 1
    calibration.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="calibration changed"):
        lab.apply_commissioning(saved, persist=False)
    lab.robot.hardware = False
