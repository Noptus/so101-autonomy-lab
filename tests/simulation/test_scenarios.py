import pytest
from so101_lab.robot.simulator import SimulatedRobot
from so101_lab.recording.episodes import export_jsonl, replay_simulation
import json


@pytest.mark.parametrize(
    "skill,params",
    [
        ("drawing", {"shape": "square"}),
        ("sorting", {}),
        ("chess", {"move": "e2e4"}),
        ("cleanup", {}),
        ("painting", {"shape": "line"}),
        ("stacking", {}),
        ("tic_tac_toe", {}),
    ],
)
def test_seven_skills_complete_geometric_execution(lab, skill, params):
    draft = lab.draft_skill(skill, params)
    assert draft["requests"]
    result = lab.execute_draft(draft["id"])
    assert result["result"]["ok"], result
    assert not result["physical_verified"]
    assert "simulated" in result["status"]
    assert any(s["name"] == skill and s["status"] == "validated in simulation" for s in lab.skill_status())
    assert lab.robot.commands


def test_bounded_exploration_records_only_measured_claims(lab):
    baseline = dict(lab.robot.joints)
    report = lab.explorer.run(budget=2)
    assert report["experiments"] == 2
    assert report["validated_encoder_experiments"] == 2
    assert report["camera_visibility_coverage"] is None
    assert lab.robot.joints == baseline
    assert lab.memory.get("capability_report") == report
    assert len([e for e in lab.memory.events(1000) if e["kind"] == "experiment"]) == 2


def test_plan_invalidated_if_arm_moves_after_preview(lab):
    draft = lab.draft_gripper(0.5)
    lab.controller.move_joints({"shoulder_pan.pos": 1})
    with pytest.raises(ValueError):
        lab.execute_draft(draft["id"])


def test_recording_and_simulation_replay(lab, tmp_path):
    result = lab.controller.move_joints({"shoulder_pan.pos": 1})
    assert result.ok
    events = [json.loads(line) for line in export_jsonl(lab.memory)]
    assert any(e["kind"] == "motion_feedback" for e in events)
    lab.controller.move_joints(SimulatedRobot().joints)
    replay = replay_simulation(events, lab)
    assert replay[0]["ok"] and lab.robot.joints["shoulder_pan.pos"] == pytest.approx(1)
    lab.robot.hardware = True
    with pytest.raises(ValueError):
        replay_simulation(events, lab)
    lab.robot.hardware = False


def test_optional_mujoco_backend(lab):
    pytest.importorskip("mujoco")
    lab.connect(backend="mujoco")
    result = lab.robot.move_joints({"shoulder_pan.pos": 1}, 1)
    assert result.ok, result.message
    assert abs(lab.robot.get_state().joints["shoulder_pan.pos"] - 1) < 0.5


def test_simulation_evidence_cannot_be_marked_hardware_validated(lab):
    draft = lab.draft_gripper(0.5)
    outcome = lab.execute_draft(draft["id"])
    lab.robot.hardware = True
    lab.robot.robot_id = "supplied_later"
    try:
        with pytest.raises(ValueError, match="Simulation"):
            lab.verify_outcome(outcome["id"], True, "looks good")
    finally:
        lab.robot.hardware = False


def test_reconnect_invalidates_previously_approved_drafts(lab):
    draft = lab.draft_gripper(0.5)
    lab.connect(backend="simulation")
    with pytest.raises(ValueError, match="expired"):
        lab.execute_draft(draft["id"])
