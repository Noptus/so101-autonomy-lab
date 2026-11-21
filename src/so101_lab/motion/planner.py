"""One authoritative command path. Stop latch is independent of provider requests."""

import threading
import time

from so101_lab.domain import Result
from so101_lab.motion.safety import Unsafe
from so101_lab.motion.trajectories import trajectory


class MotionController:
    def __init__(self, robot, safety, memory, camera_ready=lambda: True, realtime=True):
        self.robot, self.safety, self.memory = robot, safety, memory
        self.camera_ready, self.realtime = camera_ready, realtime
        self.stopped = threading.Event()
        self.busy = threading.Lock()
        self.commissioned = not robot.hardware
        self.contact_approved = False
        self.operator_ready = lambda: True
        self.last_result = None

    def stop(self):
        # Never wait on a servo or a model lock on the HTTP thread.
        self.stopped.set()
        if not self.busy.locked():

            def hold():
                if not self.busy.acquire(blocking=False):
                    return
                try:
                    if self.stopped.is_set():
                        self.robot.stop()
                except Exception:
                    pass
                finally:
                    self.busy.release()

            threading.Thread(target=hold, daemon=True).start()
        self.memory.add(
            "stop", {"latched": True, "message": "Software stop; use power disconnect for emergencies"}
        )
        return Result(ok=True, stage="execution", message="Stop latched; no automatic resume")

    def resume(self):
        if self.busy.locked():
            raise Unsafe("Wait for the interrupted controller to finish")
        self.guard(allow_stopped=True)
        self.safety.pose(self.robot.get_state().joints)
        self.stopped.clear()
        self.contact_approved = False

    def guard(self, allow_stopped=False):
        if self.stopped.is_set() and not allow_stopped:
            raise Unsafe("Stop latched; operator must validate and resume")
        if not self.commissioned:
            raise Unsafe("Supervised commissioning required")
        if self.robot.hardware and not self.operator_ready():
            raise Unsafe("Operator presence expired; keep the supervised dashboard visible")
        if not self.camera_ready():
            raise Unsafe("A required camera frame is missing or stale")
        state = self.robot.get_state()
        self.safety.state(state)
        return state

    def plan(self, requests, *, contact=False, preview=False):
        current = self.guard().joints
        if contact and self.robot.hardware and not self.contact_approved and not preview:
            raise Unsafe("Operator approval required for this contact task")
        planned = []
        total_duration = 0.0
        if len(requests) > 2000:
            raise Unsafe("Plan exceeds 2000 waypoints")
        for request in requests:
            if self.stopped.is_set():
                raise Unsafe("Stop latched during preflight")
            target = {**current, **request.get("joints", {})}
            if "position" in request:
                target = self.safety.kinematics.ik(
                    request["position"], current, self.safety.config.joint_limits, request.get("orientation")
                )
            frames = trajectory(
                current,
                target,
                request.get("duration", 1.0),
                self.safety.config.max_velocity,
                self.safety.config.max_acceleration,
            )
            if frames[-1][0] > self.safety.config.max_motion_seconds:
                raise Unsafe("Segment exceeds motion timeout")
            total_duration += frames[-1][0]
            if total_duration > self.safety.config.max_plan_seconds:
                raise Unsafe("Plan exceeds total motion-time budget")
            for _, q in frames:
                if self.stopped.is_set():
                    raise Unsafe("Stop latched during preflight")
                self.safety.pose(q, contact=contact)
            planned.append(frames)
            current = target
        return planned

    def execute(self, requests, *, contact=False):
        if not self.busy.acquire(blocking=False):
            return Result(ok=False, message="Another motion owns the controller")
        stage = "validation"
        try:
            planned = self.plan(requests, contact=contact)
            self.memory.add("motion_plan", {"requests": requests, "contact": contact})
            stage = "execution"
            count = 0
            for frames in planned:
                start = time.monotonic()
                previous = self.robot.get_state().joints
                previous_offset = 0.0
                last_command_at = start
                for offset, q in frames:
                    if self.realtime:
                        deadline = max(start + offset, last_command_at + offset - previous_offset)
                        self.stopped.wait(max(0, deadline - time.monotonic()))
                    state = self.guard()
                    if time.monotonic() - start > self.safety.config.max_motion_seconds + 1:
                        raise Unsafe("Motion timeout")
                    if (
                        max(abs(state.joints[k] - previous[k]) for k in previous)
                        > self.safety.config.feedback_tolerance
                    ):
                        raise Unsafe("Motor tracking error")
                    self.safety.pose(state.joints, contact=contact)
                    last_command_at = time.monotonic()
                    self.robot.send(q)
                    previous_offset = offset
                    previous = q
                    count += 1
                # Feedback, not send_action's echo, determines motor completion.
                deadline = time.monotonic() + 1
                while True:
                    state = self.guard()
                    error = max(abs(state.joints[k] - previous[k]) for k in previous)
                    if error <= self.safety.config.feedback_tolerance:
                        break
                    if time.monotonic() >= deadline:
                        raise Unsafe("Final encoder verification failed")
                    self.stopped.wait(0.03)
                self.memory.add("motion_feedback", state.model_dump())
            stage = "verification"
            result = Result(
                ok=True,
                stage=stage,
                message="Encoder target reached; physical task outcome needs visual verification",
                data={"setpoints": count, "state": self.robot.get_state().model_dump()},
            )
        except Exception as exc:
            if stage == "execution":
                self.stopped.set()
            result = Result(ok=False, stage=stage, message=str(exc))
        finally:
            if self.stopped.is_set():
                try:
                    self.robot.stop()
                except Exception:
                    pass
            self.busy.release()
            self.contact_approved = False
        self.operator_ready = lambda: True
        self.last_result = result
        self.memory.add("motion_result", result.model_dump())
        return result

    def move_joints(self, targets, duration=1):
        return self.execute([{"joints": targets, "duration": duration}])

    def move_tip(self, position, orientation=None, duration=1):
        return self.execute([{"position": position, "orientation": orientation, "duration": duration}])

    def set_gripper(self, open_fraction):
        if not 0 <= open_fraction <= 1:
            return Result(ok=False, message="Gripper fraction must be between 0 and 1")
        if self.robot.hardware and not self.contact_approved:
            return Result(ok=False, message="Approve contact before actuating the physical gripper")
        return self.execute([{"joints": {"gripper.pos": open_fraction * 100}, "duration": 1}], contact=True)

    def get_tool_pose(self):
        return self.safety.kinematics.fk(self.robot.get_state().joints).tolist()
