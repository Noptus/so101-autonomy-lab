from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from so101_lab.agents.explorer import Explorer
from so101_lab.agents.memory import Memory
from so101_lab.agents.providers import ProviderConfig, SecretStore
from so101_lab.agents.supervisor import Supervisor
from so101_lab.domain import Commissioning, Result, SafetyConfig
from so101_lab.motion.kinematics import Kinematics
from so101_lab.motion.planner import MotionController
from so101_lab.motion.safety import Safety, Unsafe
from so101_lab.perception.cameras import Cameras
from so101_lab.perception.objects import colored_regions
from so101_lab.robot.calibration import calibrations, validate_calibration
from so101_lab.robot.lerobot_adapter import SO101Robot
from so101_lab.robot.simulator import SimulatedRobot
from so101_lab.skills.planners import SKILLS, SkillSetup, plan_skill


class Lab:
    def __init__(self, data_dir, realtime=True):
        self.directory = Path(data_dir)
        self.memory = Memory(self.directory)
        self.cameras = Cameras()
        self.provider_config = ProviderConfig.model_validate(self.memory.get("provider", {}))
        self.secrets = SecretStore(self.memory)
        self.operator_seen = 0.0
        self.robot = SimulatedRobot()
        self.robot.connect()
        self.realtime = realtime
        self.controller = self.make_controller(SafetyConfig(), Kinematics())
        self.supervisor = Supervisor(self)
        self.explorer = Explorer(self)
        self.drafts = {}
        self.operations = threading.Lock()
        self.operation_active = False
        self.recorded_paths = []
        previous = self.memory.get("last_agent_session")
        if previous and previous.get("status") == "running":
            self.memory.save("last_agent_session", {**previous, "status": "interrupted_by_restart"})
        self.memory.add("startup", {"backend": "simulation", "resume_motion": False})

    def make_controller(self, config, kinematics):
        def camera_ready():
            if not self.robot.hardware:
                return True
            profile = self.memory.get("commissioning", {})
            return self.cameras.fresh(profile.get("camera_id"), config.max_camera_age)

        controller = MotionController(
            self.robot, Safety(config, kinematics), self.memory, camera_ready, self.realtime
        )
        controller.operator_ready = lambda: time.monotonic() - self.operator_seen < 2.0
        self.robot.controller = controller
        return controller

    def idle(self):
        if self.controller.busy.locked() or self.supervisor.running or self.operation_active:
            raise Unsafe("Pause and wait for the active operation before changing setup")

    def connect(
        self, backend="simulation", port="", robot_id="", calibration_path="", operator_present=False
    ):
        self.idle()
        with self.operations:
            if backend not in ("simulation", "hardware", "mujoco"):
                raise ValueError("Unknown backend")
            if backend == "hardware" and not operator_present:
                raise Unsafe(
                    "Operator must support the arm and confirm the selected follower before connecting"
                )
            if backend == "hardware":
                known = [
                    c for c in calibrations() if c["robot_id"] == robot_id and c["path"] == calibration_path
                ]
                if not known:
                    raise Unsafe("Choose a discovered, validated LeRobot calibration")
                if not port or port not in {d["port"] for d in self.serial_devices()}:
                    raise Unsafe("Choose an available local USB serial port")
            self.controller.stop()
            self.drafts.clear()
            self.robot.disconnect()
            if backend == "hardware":
                robot = SO101Robot(port, robot_id, calibration_path)
            elif backend == "mujoco":
                from so101_lab.robot.mujoco_simulator import MuJoCoRobot

                robot = MuJoCoRobot()
            else:
                robot = SimulatedRobot()
            self.robot = robot
            self.controller = self.make_controller(SafetyConfig(), Kinematics())
            try:
                robot.connect()
                self.operator_seen = time.monotonic() if operator_present else 0.0
                self.controller.commissioned = not robot.hardware
                if robot.hardware:
                    stored = self.memory.get("commissioning")
                    if stored:
                        self.apply_commissioning(Commissioning.model_validate(stored), persist=False)
                self.memory.add("connection", {"backend": backend, "port": port, "robot_id": robot_id})
                return self.status()
            except Exception:
                self.controller.stopped.set()
                raise

    @staticmethod
    def serial_devices():
        from so101_lab.robot.discovery import discover_serial

        return discover_serial()

    def apply_commissioning(self, profile, persist=True):
        if not self.robot.hardware:
            raise ValueError("Commissioning profiles apply only to hardware; demo geometry is separate")
        if self.controller.busy.locked() or self.supervisor.running:
            raise Unsafe("Cannot change calibration during execution")
        if (profile.robot_id, profile.port) != (self.robot.robot_id, self.robot.port):
            raise ValueError("Commissioning profile belongs to a different arm/port")
        if profile.calibration_sha256 != validate_calibration(self.robot.calibration_path):
            raise ValueError("Motor calibration changed; repeat commissioning")
        if not self.cameras.fresh(profile.camera_id, profile.safety.max_camera_age):
            raise ValueError("Select and start a fresh camera before commissioning")
        safety = Safety(
            profile.safety,
            Kinematics(tcp=profile.tcp, signs=profile.motor_signs, offsets=profile.motor_offsets),
        )
        safety.pose(profile.standby)
        safety.state(self.robot.get_state())
        safety.pose(self.robot.get_state().joints)
        self.controller.safety = safety
        self.controller.commissioned = True
        # Commissioning never clears an existing stop latch or approves contact.
        self.controller.contact_approved = False
        if persist:
            self.drafts.clear()
            self.memory.save("commissioning", profile.model_dump())
            self.memory.add(
                "commissioning",
                {"robot_id": profile.robot_id, "status": "operator_declared; physical test pending"},
            )

    def disconnect(self):
        self.controller.stop()
        if self.controller.busy.locked() or self.operation_active:
            raise Unsafe("Stop has been latched; wait for the controller to finish before disconnecting")
        self.robot.disconnect()
        return {"ok": True, "message": "Disconnected; motion cannot resume automatically"}

    def status(self):
        try:
            state = self.robot.get_state().model_dump()
            pose = self.controller.get_tool_pose()
        except Exception as exc:
            state, pose = {"connected": False, "error": str(exc)}, None
        return {
            "backend": "hardware" if self.robot.hardware else getattr(self.robot, "name", "simulation"),
            "state": state,
            "pose": pose,
            "stopped": self.controller.stopped.is_set(),
            "commissioned": self.controller.commissioned,
            "motion_busy": self.controller.busy.locked(),
            "operation_active": self.operation_active,
            "agent_running": self.supervisor.running,
            "cameras": self.cameras.status(),
            "provider": self.provider_config.model_dump(),
            "provider_verified": self.provider_verified(),
            "skills": self.skill_status(),
            "cloud_image_sharing": self.provider_config.share_images,
            "capability_report": self.memory.get("capability_report"),
            "session": self.memory.get("last_agent_session"),
        }

    def provider_identity(self):
        c = self.provider_config
        return hashlib.sha256(json.dumps([c.resolved()[:2], c.model]).encode()).hexdigest()

    def provider_verified(self):
        record = self.memory.get("provider_probe", {})
        # Re-probe after a day; aliases, routing and local model installations can change.
        return (
            record.get("identity") == self.provider_identity() and time.time() - record.get("time", 0) < 86400
        )

    def configure_provider(self, config, key="", persist=False):
        self.idle()
        config.resolved()
        if key:
            self.secrets.put(config, key, persist)
        self.provider_config = config
        self.memory.save("provider", config.model_dump())
        return config.model_dump()

    def demo_setup(self):
        # Deliberately in free space: demo drawings are trajectories, not table contact physics.
        return SkillSetup(
            origin=(0.275, -0.02, 0.085),
            width=0.02,
            height=0.02,
            lift=0.012,
            plane_verified=True,
            tcp_verified=True,
            palette={"red": (0.27, -0.025, 0.085)},
            objects=[
                {
                    "id": f"block_{i}",
                    "position": (0.272, -0.018 + i * 0.012, 0.088),
                    "color": "red" if i % 2 == 0 else "blue",
                    "approved": True,
                    "lightweight_foam": True,
                }
                for i in range(3)
            ],
            destinations={
                "red": (0.285, -0.018, 0.088),
                "blue": (0.285, 0.008, 0.088),
                "stack": (0.28, -0.01, 0.085),
                **{f"block_{i}": (0.285, -0.018 + i * 0.012, 0.088) for i in range(3)},
            },
            grasp_verified=True,
        )

    def setup_for(self, skill):
        if not self.robot.hardware:
            saved = self.memory.get(f"sim_skill_setup:{skill}")
            return SkillSetup.model_validate(saved) if saved else self.demo_setup()
        saved = self.memory.get(f"hardware_skill_setup:{self.robot.robot_id}:{skill}")
        if not saved:
            raise ValueError(f"Commission {skill} geometry, tool offset and fixtures first")
        return SkillSetup.model_validate(saved)

    def save_skill_setup(self, skill, setup):
        self.idle()
        if skill not in SKILLS:
            raise ValueError("Unknown skill")
        key = (
            f"hardware_skill_setup:{self.robot.robot_id}:{skill}"
            if self.robot.hardware
            else f"sim_skill_setup:{skill}"
        )
        self.memory.save(key, setup.model_dump())
        # Changed geometry invalidates any prior readiness claim and approval.
        self.memory.save(key + ":validation", None)
        self.drafts.clear()

    def skill_status(self):
        status = []
        for name, meta in SKILLS.items():
            key = (
                f"hardware_skill_setup:{self.robot.robot_id}:{name}"
                if self.robot.hardware
                else f"sim_skill_setup:{name}"
            )
            validation = self.memory.get(key + ":validation")
            configured = bool(self.memory.get(key)) or not self.robot.hardware
            state = (
                "validated in simulation"
                if validation and not self.robot.hardware
                else ("ready to test" if configured else "setup required")
            )
            if validation and self.robot.hardware:
                state = "validated on hardware (operator attested)"
            status.append({"name": name, **meta, "status": state})
        return status

    def draft_skill(self, name, params):
        setup = self.setup_for(name)
        if self.robot.hardware:
            if not setup.measured_on_hardware or not setup.tcp_verified or not setup.plane_verified:
                raise Unsafe("Measure tool TCP and task plane on this installation")
            if setup.orientation is None:
                raise Unsafe("Commission a feasible tool orientation for physical contact")
            if name in ("sorting", "cleanup", "stacking", "chess") and not setup.grasp_verified:
                raise Unsafe("Commission a representative grasp first")
            if (
                name in ("drawing", "painting", "tic_tac_toe")
                and abs(setup.origin[2] - self.controller.safety.config.table_z) > 0.001
            ):
                raise Unsafe("Task plane must match the commissioned contact plane")
        requests, metrics = plan_skill(name, setup, params)
        self.controller.plan(requests, contact=True, preview=True)
        token = uuid.uuid4().hex
        draft = {
            "id": token,
            "skill": name,
            "requests": requests,
            "metrics": metrics,
            "start": self.robot.get_state().joints,
            "created_at": time.monotonic(),
            "physical_verified": False,
            "setup": setup.model_dump(),
        }
        self.drafts[token] = draft
        return {k: v for k, v in draft.items() if k != "created_at"}

    def draft_gripper(self, open_fraction):
        if not 0 <= open_fraction <= 1:
            raise ValueError("Gripper fraction must be between 0 and 1")
        self.controller.guard()
        requests = [{"joints": {"gripper.pos": open_fraction * 100}, "duration": 2}]
        self.controller.plan(requests, contact=True, preview=True)
        token = uuid.uuid4().hex
        draft = {
            "id": token,
            "skill": "gripper",
            "requests": requests,
            "metrics": {"target_open_fraction": open_fraction},
            "start": self.robot.get_state().joints,
            "created_at": time.monotonic(),
            "physical_verified": False,
            "setup": {},
        }
        self.drafts[token] = draft
        return {k: v for k, v in draft.items() if k != "created_at"}

    def execute_draft(self, draft_id, operator_approval=False):
        draft = self.drafts.pop(draft_id, None)
        if not draft or time.monotonic() - draft["created_at"] > 120:
            raise Unsafe("Plan expired; preview a new plan")
        if self.robot.hardware and not operator_approval:
            raise Unsafe("Operator approval is required for this exact contact plan")
        current = self.robot.get_state().joints
        if max(abs(current[k] - draft["start"][k]) for k in current) > 0.5:
            raise Unsafe("Robot moved after preview; generate a new plan")
        with self.operations:
            self.operation_active = True
            try:
                before = self.snapshot("before")
                self.controller.contact_approved = bool(operator_approval)
                result = self.controller.execute(draft["requests"], contact=True)
                after = self.snapshot("after")
                outcome_id = uuid.uuid4().hex
                outcome = {
                    "id": outcome_id,
                    "skill": draft["skill"],
                    "backend": "hardware" if self.robot.hardware else "simulation",
                    "robot_id": self.robot.robot_id if self.robot.hardware else None,
                    "calibration_sha256": validate_calibration(self.robot.calibration_path)
                    if self.robot.hardware
                    else None,
                    "result": result.model_dump(),
                    "metrics": draft["metrics"],
                    "before": before,
                    "after": after,
                    "status": "awaiting_visual_verification"
                    if self.robot.hardware
                    else "simulated_trajectory_completed",
                    "physical_verified": False,
                    "setup": draft["setup"],
                }
                self.memory.save("last_skill_outcome", outcome)
                self.memory.add("skill_outcome", outcome)
                if result.ok:
                    if not self.robot.hardware:
                        self.memory.save(
                            f"sim_skill_setup:{draft['skill']}:validation", {"outcome_id": outcome_id}
                        )
                    self.recorded_paths.append([r["position"] for r in draft["requests"] if "position" in r])
                return outcome
            finally:
                self.operation_active = False

    def verify_outcome(self, outcome_id, success, notes, placement_error_m=None):
        outcome = self.memory.get("last_skill_outcome")
        if (
            not self.robot.hardware
            or not outcome
            or outcome["id"] != outcome_id
            or not outcome["result"]["ok"]
        ):
            raise ValueError("No matching hardware outcome to verify")
        if outcome.get("backend") != "hardware" or outcome.get("robot_id") != self.robot.robot_id:
            raise ValueError("Simulation or another arm's outcome cannot establish hardware validation")
        if outcome.get("calibration_sha256") != validate_calibration(self.robot.calibration_path):
            raise ValueError("Calibration changed after execution")
        if outcome["status"] != "awaiting_visual_verification":
            raise ValueError("This outcome has already been reviewed")
        setup_key = f"hardware_skill_setup:{self.robot.robot_id}:{outcome['skill']}"
        if outcome["skill"] != "gripper" and self.memory.get(setup_key) != outcome["setup"]:
            raise ValueError("Task setup changed after execution; re-test before claiming validation")
        if not notes.strip():
            raise ValueError("Describe the independent physical evidence")
        outcome.update(
            physical_verified=success,
            status="operator_verified" if success else "verification_failed",
            operator_evidence=notes,
            placement_error_m=placement_error_m,
        )
        if success:
            key = f"hardware_skill_setup:{self.robot.robot_id}:{outcome['skill']}"
            self.memory.save(key + ":validation", {"outcome_id": outcome_id, "evidence": notes})
            setup = outcome["setup"]
            if "next_fen" in outcome["metrics"]:
                setup["fen"] = outcome["metrics"]["next_fen"]
            if "next_grid" in outcome["metrics"]:
                setup["grid"] = outcome["metrics"]["next_grid"]
            self.memory.save(key, setup)
        self.memory.save("last_skill_outcome", outcome)
        self.memory.add("physical_verification", outcome)
        return outcome

    def simulation_image(self):
        image = np.full((480, 640, 3), (25, 29, 37), np.uint8)

        def pixel(p):
            return (int(90 + p[0] * 1350), int(245 - p[1] * 1350))

        for x in np.arange(0, 0.4, 0.05):
            cv2.line(image, pixel([x, -0.15]), pixel([x, 0.15]), (45, 50, 60), 1)
        for y in np.arange(-0.15, 0.2, 0.05):
            cv2.line(image, pixel([0, y]), pixel([0.4, y]), (45, 50, 60), 1)
        for path in self.recorded_paths[-12:]:
            for a, b in zip(path, path[1:]):
                cv2.line(image, pixel(a), pixel(b), (120, 210, 155), 2)
        for a, b in self.controller.safety.kinematics.segments(self.robot.get_state().joints):
            cv2.line(image, pixel(a), pixel(b), (235, 200, 110), 8)
            cv2.circle(image, pixel(a), 7, (245, 235, 210), -1)
        tip = self.controller.safety.kinematics.fk(self.robot.get_state().joints)[:3, 3]
        cv2.circle(image, pixel(tip), 9, (110, 235, 160), -1)
        cv2.putText(
            image,
            "SIMULATION / geometric preview",
            (20, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (180, 190, 205),
            1,
        )
        cv2.putText(
            image,
            f"TCP z = {tip[2]:.3f} m | no contact physics",
            (20, 452),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (160, 170, 185),
            1,
        )
        return image

    def frame(self, camera_id):
        if camera_id == "simulation" and not self.robot.hardware:
            return self.simulation_image()
        return self.cameras.get(camera_id).image

    def preview_frame(self, camera_id):
        image = self.frame(camera_id).copy()
        if camera_id == "simulation":
            return image
        registration = self.memory.get(f"plane:{camera_id}")
        for obj in colored_regions(image, registration):
            x, y, w, h = obj["bbox"]
            cv2.rectangle(image, (x, y), (x + w, y + h), (110, 220, 150), 1)
            cv2.putText(
                image,
                obj["label"] + " / estimate",
                (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (110, 220, 150),
                1,
            )
        if registration and registration.get("validated"):
            inverse = np.linalg.inv(np.array(registration["homography"]))
            cfg = self.controller.safety.config
            lo, hi = cfg.workspace.lower, cfg.workspace.upper
            corners = np.array([[[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]], float)
            pixels = cv2.perspectiveTransform(corners, inverse).astype(np.int32)
            cv2.polylines(image, pixels, True, (150, 200, 235), 1)
            cv2.putText(
                image,
                "Configured XY envelope / planar projection",
                (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (150, 200, 235),
                1,
            )
        return image

    def image_uri(self, camera_id):
        ok, data = cv2.imencode(".jpg", self.frame(camera_id))
        if not ok:
            raise ValueError("Image encoding failed")
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()

    def snapshot(self, label):
        directory = self.directory / "observations"
        directory.mkdir(exist_ok=True)
        result = []
        ids = list(self.cameras.roles) if self.robot.hardware else ["simulation"]
        for camera_id in ids:
            try:
                image = self.frame(camera_id)
                filename = f"{uuid.uuid4().hex}-{label}.jpg"
                if cv2.imwrite(str(directory / filename), image):
                    result.append(filename)
            except ValueError:
                pass
        return result

    def observe(self, record=False):
        state = self.robot.get_state()
        observations = []
        for camera_id in self.cameras.roles:
            try:
                image = self.frame(camera_id)
                registration = self.memory.get(f"plane:{camera_id}")
                observations.append(
                    {"camera_id": camera_id, "objects": colored_regions(image, registration), "fresh": True}
                )
            except ValueError:
                observations.append({"camera_id": camera_id, "objects": [], "fresh": False})
        result = {
            "ok": True,
            "state": state.model_dump(),
            "cameras": observations,
            "backend": "hardware" if self.robot.hardware else "simulation",
            "workspace": self.workspace_map(),
            "evidence": "Encoders measured; image regions estimated; no grasp established",
        }
        if record:
            objects = [{**obj, "camera_id": c["camera_id"]} for c in observations for obj in c["objects"]]
            self.memory.save("workspace_objects", objects)
            result["images"] = self.snapshot("observe")
            self.memory.add("observation", result)
        return result

    def workspace_map(self):
        config = self.controller.safety.config
        return {
            "workspace": "local",
            "surface": "configured table plane",
            "table_z": config.table_z,
            "known_free_regions": [],
            "unknown_regions": ["all regions without independent visual validation"],
            "excluded_regions": [b.model_dump() for b in config.exclusions],
            "objects": self.memory.get("workspace_objects", []),
            "capability_report": self.memory.get("capability_report"),
        }

    def call_tool(self, name, args):
        controller = self.controller
        if name == "get_robot_state":
            return {"ok": True, **self.robot.get_state().model_dump()}
        if name == "observe_environment":
            return self.observe(record=True)
        if name == "get_workspace_map":
            return {"ok": True, **self.workspace_map()}
        if name == "get_camera_frame":
            if not self.provider_config.share_images:
                return {"ok": False, "message": "Operator has disabled image sharing"}
            return {"ok": True, "image_uri": self.image_uri(args["camera_id"])}
        if name == "propose_experiment":
            return {"ok": True, "proposals": self.explorer.proposals(), "objective": args["objective"]}
        if name == "move_joint_delta":
            joint = args["joint"] + ".pos"
            current = self.robot.get_state().joints[joint]
            return controller.move_joints({joint: current + args["delta"]}, args["duration"]).model_dump()
        if name == "move_tip_safe":
            return controller.move_tip(
                [args["x"], args["y"], args["z"]], duration=args["duration"]
            ).model_dump()
        if name == "follow_path":
            return controller.execute(
                [{"position": p, "duration": 1} for p in args["waypoints"]]
            ).model_dump()
        if name == "set_gripper":
            return controller.set_gripper(args["open_fraction"]).model_dump()
        if name == "locate_object":
            observed = self.observe()
            regions = [
                o
                for c in observed["cameras"]
                for o in c["objects"]
                if args["description"].lower() in o["label"].lower()
            ]
            return {"ok": True, "estimates": regions, "graspable": "unknown"}
        if name == "load_skill":
            try:
                setup = self.setup_for(args["skill_name"]).model_dump()
            except ValueError:
                setup = None
            return {
                "ok": True,
                "skill": next(s for s in self.skill_status() if s["name"] == args["skill_name"]),
                "registered_setup": setup,
                "instructions": "Use measured setup and legal task state. Missing setup needs operator commissioning. Contact requires exact-plan approval and independent physical verification.",
            }
        if name in ("execute_skill", "draw_strokes"):
            skill = args.get("skill_name", "drawing")
            params = args.get("params", args)
            draft = self.draft_skill(skill, params)
            if self.robot.hardware:
                return {
                    "ok": False,
                    "stage": "validation",
                    "message": "Operator must review and approve this exact plan in dashboard",
                    "draft": draft,
                }
            outcome = self.execute_draft(draft["id"])
            return {"ok": outcome["result"]["ok"], **outcome}
        if name in ("plan_grasp", "pick_object", "place_object"):
            setup = self.setup_for("cleanup")
            objects = [o for o in setup.objects if o.id == args["object_id"]]
            if not objects:
                return {"ok": False, "message": "Register and approve this object before grasp planning"}
            setup.objects = objects
            if name == "place_object":
                setup.destinations[objects[0].id] = args["destination"]
            plan, metrics = plan_skill("cleanup", setup, {})
            if name == "plan_grasp":
                return {
                    "ok": True,
                    "plan": plan,
                    "prerequisites": SKILLS["cleanup"]["requires"],
                    "metrics": metrics,
                }
            # Contact tools cannot create their own approval or replace operator-measured setup.
            if self.robot.hardware:
                return {
                    "ok": False,
                    "message": "Use the cleanup skill preview and exact-plan operator approval",
                }
            return controller.execute(plan, contact=True).model_dump()
        if name == "get_experiment_history":
            return {"ok": True, "events": [e for e in self.memory.events(1000) if e["kind"] == "experiment"]}
        if name == "save_discovery":
            self.memory.add("agent_hypothesis", {"claim": args["data"], "verified": False})
            return {"ok": True, "message": "Hypothesis recorded; no safety settings changed"}
        if name == "assess_last_action":
            return (
                controller.last_result.model_dump()
                if controller.last_result
                else Result(ok=False, message="No action recorded").model_dump()
            )
        if name in ("pause", "stop"):
            return controller.stop().model_dump()
        raise ValueError("Unknown tool")

    def close(self):
        self.controller.stop()
        self.cameras.close()
        if not self.controller.busy.locked():
            self.robot.disconnect()
        self.memory.close()
