import math
import threading
import time
import numpy as np
import pytest
from pydantic import ValidationError
from so101_lab.domain import Box, SafetyConfig, State
from so101_lab.motion.safety import Unsafe, segment_box, segment_distance
from so101_lab.motion.trajectories import trajectory
from so101_lab.agents.tools import JointDelta


def test_joint_schema_and_nonfinite_rejected(lab):
    with pytest.raises(ValidationError):
        State(joints={"gripper.pos": 50})
    for value in [float("nan"), float("inf")]:
        q = dict(lab.robot.joints, **{"shoulder_pan.pos": value})
        with pytest.raises(ValidationError):
            State(joints=q)
    with pytest.raises(ValidationError):
        JointDelta(joint="gripper", delta=1)
    with pytest.raises(ValidationError):
        JointDelta(joint="elbow_flex", delta=9)


def test_joint_limit_rejected_before_any_command(lab):
    result = lab.controller.move_joints({"elbow_flex.pos": 999}, 1)
    assert not result.ok and result.stage == "validation"
    assert lab.robot.commands == []


def test_fk_ik_roundtrip_preserves_gripper(lab):
    k = lab.controller.safety.kinematics
    q = lab.robot.get_state().joints
    target = k.fk(q)[:3, 3] + [0.004, 0.002, 0.002]
    solved = k.ik(target, q, lab.controller.safety.config.joint_limits)
    assert np.linalg.norm(k.fk(solved)[:3, 3] - target) < 0.001
    assert solved["gripper.pos"] == q["gripper.pos"]


def test_unreachable_and_orientation_rejected(lab):
    k = lab.controller.safety.kinematics
    for target in ([2, 0, 0], [float("nan"), 0, 0.1]):
        with pytest.raises(ValueError):
            k.ik(target, lab.robot.joints, lab.controller.safety.config.joint_limits)
    assert not lab.controller.move_tip([0.4, 0, -0.1]).ok
    assert lab.robot.commands == []


def test_mapping_and_tcp(lab):
    from so101_lab.motion.kinematics import Kinematics

    q = lab.robot.joints
    k = lab.controller.safety.kinematics
    other = Kinematics(tcp=(0, 0, 0.02))
    assert np.linalg.norm(other.fk(q)[:3, 3] - k.fk(q)[:3, 3]) == pytest.approx(0.02)
    signs = dict.fromkeys(other.signs, 1)
    signs["shoulder_pan"] = -1
    q1 = {**q, "shoulder_pan.pos": 10}
    q2 = {**q, "shoulder_pan.pos": -10}
    assert np.allclose(Kinematics(signs=signs).fk(q1), k.fk(q2))


def test_interpolation_endpoints_velocity_acceleration():
    frames = trajectory({"a": 0.0}, {"a": 20.0}, 0.1, 12, 30, hz=100)
    times = np.array([t for t, _ in frames])
    positions = np.array([p["a"] for _, p in frames])
    assert positions[0] == 0 and positions[-1] == 20
    assert (np.diff(positions) >= 0).all()
    assert max(abs(np.diff(positions) / np.diff(times))) <= 12.01
    dt = times[1] - times[0]
    assert max(abs(np.diff(positions, n=2) / (dt * dt))) <= 30.1
    for duration in [-1, 0, math.nan]:
        with pytest.raises(ValueError):
            trajectory({"a": 0}, {"a": 1}, duration, 12, 30)


def test_exclusion_volume_and_link_collision(lab):
    point = lab.controller.get_tool_pose()
    tip = np.array(point)[:3, 3]
    lab.controller.safety.config.exclusions = [
        Box(lower=(tip - 0.005).tolist(), upper=(tip + 0.005).tolist())
    ]
    result = lab.controller.move_joints({"shoulder_pan.pos": 1})
    assert not result.ok and "exclusion" in result.message
    assert not lab.robot.commands
    assert segment_box(np.array([0, 0, 0]), [1, 0, 0], [0.4, -0.1, -0.1], [0.5, 0.1, 0.1])
    assert not segment_box(np.array([0, 1, 0]), [1, 1, 0], [0.4, -0.1, -0.1], [0.5, 0.1, 0.1])
    assert segment_distance([0, 0, 0], [1, 0, 0], [0.5, -1, 0], [0.5, 1, 0]) == pytest.approx(0)
    assert segment_distance([0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]) == pytest.approx(1)


def test_camera_freshness_and_feedback_fail_closed(lab):
    lab.controller.camera_ready = lambda: False
    assert not lab.controller.move_joints({"shoulder_pan.pos": 1}).ok
    assert not lab.robot.commands
    lab.controller.camera_ready = lambda: True
    original = lab.robot.get_state

    def stale():
        s = original()
        s.sampled_at -= 10
        return s

    lab.robot.get_state = stale
    result = lab.controller.move_joints({"shoulder_pan.pos": 1})
    assert not result.ok and "stale" in result.message
    assert not lab.robot.commands


def test_disconnect_during_motion_latches_stop(lab):
    original = lab.robot.send

    def unplug(q):
        original(q)
        lab.robot.connected = False

    lab.robot.send = unplug
    result = lab.controller.move_joints({"shoulder_pan.pos": 2})
    assert not result.ok and result.stage == "execution"
    assert lab.controller.stopped.is_set()
    lab.robot.connected = True
    assert not lab.controller.move_joints({"shoulder_pan.pos": 1}).ok
    lab.controller.resume()
    assert not lab.controller.stopped.is_set()


def test_software_stop_interrupts_without_model_or_command_lock(lab):
    lab.controller.realtime = True
    result = []
    thread = threading.Thread(
        target=lambda: result.append(lab.controller.move_joints({"shoulder_pan.pos": 3}, 3))
    )
    thread.start()
    deadline = time.monotonic() + 2
    while not lab.robot.commands and time.monotonic() < deadline:
        time.sleep(0.01)
    start = time.monotonic()
    lab.controller.stop()
    assert time.monotonic() - start < 0.1
    thread.join(1)
    assert not thread.is_alive() and not result[0].ok
    count = len(lab.robot.commands)
    time.sleep(0.1)
    assert len(lab.robot.commands) == count
    assert lab.controller.stopped.is_set()


def test_contact_gate_and_no_agent_override(lab):
    lab.robot.hardware = True
    lab.controller.commissioned = True
    denied = lab.controller.set_gripper(0.3)
    assert not denied.ok and not lab.robot.commands
    lab.robot.hardware = False
    with pytest.raises(ValidationError):
        JointDelta.model_validate({"joint": "shoulder_pan", "delta": 1, "disable_safety": True})


def test_invalid_safety_bounds():
    with pytest.raises(ValidationError):
        Box(lower=(0, 0, 0), upper=(-1, 1, 1))
    with pytest.raises(ValidationError):
        SafetyConfig(joint_limits={})


def test_operator_presence_is_required_for_hardware(lab):
    lab.robot.hardware = True
    lab.controller.commissioned = True
    lab.controller.operator_ready = lambda: False
    result = lab.controller.move_joints({"shoulder_pan.pos": 1})
    assert not result.ok and "presence" in result.message
    assert not lab.robot.commands
    lab.robot.hardware = False


def test_approved_tool_contact_only_exempts_final_tcp_segment(lab):
    # A pen tip may touch the table during approved contact; the wrist cannot.
    safety = lab.controller.safety
    q = lab.robot.joints
    original_fk = safety.kinematics.fk
    original_segments = safety.kinematics.segments
    tcp = np.array(original_fk(q)[:3, 3])
    plane = tcp[2]
    safety.config.table_z = plane
    # Make every arm segment clear the test plane; only the tool ends on it.
    segments = [
        (np.array([0.1 + i * 0.03, 0, plane + 0.08]), np.array([0.12 + i * 0.03, 0, plane + 0.08]))
        for i in range(5)
    ]
    segments.append((tcp + [0, 0, 0.04], tcp.copy()))
    safety.kinematics.segments = lambda joints: segments
    with pytest.raises(Unsafe):
        safety.pose(q, contact=False)
    safety.pose(q, contact=True)
    segments[2] = (tcp.copy(), tcp + [0.01, 0, 0])
    with pytest.raises(Unsafe):
        safety.pose(q, contact=True)
    safety.kinematics.segments = original_segments


def test_driver_delay_does_not_burst_catchup_setpoints(lab):
    lab.controller.realtime = True
    sent = []
    original = lab.robot.send

    def delayed(target):
        sent.append(time.monotonic())
        original(target)
        if len(sent) == 3:
            time.sleep(0.1)

    lab.robot.send = delayed
    result = lab.controller.move_joints({"shoulder_pan.pos": 1}, 0.6)
    assert result.ok
    assert min(np.diff(sent)) >= 0.025
