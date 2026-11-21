from typing import Literal
from pydantic import Field
from so101_lab.domain import ARM, Validated


class Empty(Validated):
    pass


class JointDelta(Validated):
    joint: Literal[*ARM]
    delta: float = Field(ge=-3, le=3)
    duration: float = Field(default=1, ge=0.5, le=10)


class Tip(Validated):
    x: float = Field(ge=-0.5, le=0.5)
    y: float = Field(ge=-0.5, le=0.5)
    z: float = Field(ge=-0.05, le=0.6)
    duration: float = Field(default=1, ge=0.5, le=10)


class Gripper(Validated):
    open_fraction: float = Field(ge=0, le=1)


class Camera(Validated):
    camera_id: str = Field(max_length=64)


class Objective(Validated):
    objective: str = Field(max_length=500)


class Description(Validated):
    description: str = Field(max_length=200)


class ObjectID(Validated):
    object_id: str = Field(max_length=100)


class Place(ObjectID):
    destination: tuple[float, float, float]


class Skill(Validated):
    skill_name: Literal["drawing", "painting", "chess", "cleanup", "sorting", "stacking", "tic_tac_toe"]
    params: dict = Field(default_factory=dict)


class Strokes(Validated):
    strokes: list[list[tuple[float, float]]] = Field(min_length=1, max_length=100)


class Path(Validated):
    waypoints: list[tuple[float, float, float]] = Field(min_length=1, max_length=100)


class Discovery(Validated):
    data: dict


TOOLS = {
    "observe_environment": (
        Empty,
        "Observe current camera regions and robot encoders. Image estimates are not verified grasps.",
    ),
    "get_robot_state": (Empty, "Read all six calibrated motor positions."),
    "get_workspace_map": (Empty, "Read known workspace facts, estimates and exclusions."),
    "get_camera_frame": (Camera, "Request a fresh image; sharing must be enabled by operator."),
    "propose_experiment": (
        Objective,
        "List bounded information-gain experiments; this does not move the arm.",
    ),
    "move_joint_delta": (JointDelta, "Request a small free-space motion through the safety controller."),
    "move_tip_safe": (Tip, "Request a position-only IK move; local trajectory validation may reject it."),
    "follow_path": (Path, "Preflight and execute a Cartesian waypoint path."),
    "set_gripper": (Gripper, "Request gripper opening; hardware contact approval required."),
    "locate_object": (Description, "Return image-derived object estimates, not validated grasps."),
    "plan_grasp": (ObjectID, "Read registered grasp prerequisites for a known object."),
    "pick_object": (ObjectID, "Execute an approved registered object's configured pick-and-place transfer."),
    "place_object": (Place, "Plan an approved registered transfer to an explicit destination."),
    "draw_strokes": (Strokes, "Execute normalized paper polylines using commissioned drawing setup."),
    "load_skill": (Skill, "Read setup and readiness of a skill."),
    "execute_skill": (
        Skill,
        "Preflight a skill; physical contact requires operator approval of its exact plan.",
    ),
    "get_experiment_history": (Empty, "Read recent recorded experiments."),
    "save_discovery": (
        Discovery,
        "Record an unverified agent hypothesis. Does not update safety or calibration.",
    ),
    "assess_last_action": (Empty, "Read encoder result and explicit limits of physical verification."),
    "pause": (Empty, "Latch a software pause immediately."),
    "stop": (Empty, "Latch software stop immediately; only operator may resume."),
}


def schemas():
    return [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": model.model_json_schema()},
        }
        for name, (model, description) in TOOLS.items()
    ]
