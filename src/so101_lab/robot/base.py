from typing import Protocol
from so101_lab.domain import State


class RobotBackend(Protocol):
    hardware: bool

    def connect(self) -> None: ...
    def get_state(self) -> State: ...
    def send(self, targets: dict[str, float]) -> None: ...
    def stop(self) -> None: ...
    def disconnect(self) -> None: ...


class ControlledRobot:
    """Convenience API always delegates to the bound authoritative controller."""

    controller = None

    def _controller(self):
        if self.controller is None:
            raise RuntimeError("Bind a MotionController before requesting movement")
        return self.controller

    def move_joints(self, targets, duration=1):
        return self._controller().move_joints(targets, duration)

    def move_tip(self, position, orientation=None, duration=1):
        return self._controller().move_tip(position, orientation, duration)

    def set_gripper(self, open_fraction):
        return self._controller().set_gripper(open_fraction)

    def get_tool_pose(self):
        return self._controller().get_tool_pose()
