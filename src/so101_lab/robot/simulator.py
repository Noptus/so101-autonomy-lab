from so101_lab.robot.base import ControlledRobot
from so101_lab.domain import State


class SimulatedRobot(ControlledRobot):
    """Deterministic encoder simulator, not a claim of contact/force realism."""

    hardware = False

    def __init__(self):
        self.connected = False
        self.joints = {
            "shoulder_pan.pos": 0.0,
            "shoulder_lift.pos": -20.0,
            "elbow_flex.pos": 40.0,
            "wrist_flex.pos": 20.0,
            "wrist_roll.pos": 0.0,
            "gripper.pos": 70.0,
        }
        self.commands = []

    def connect(self):
        self.connected = True

    def get_state(self):
        if not self.connected:
            raise ConnectionError("Simulator disconnected")
        return State(joints=dict(self.joints))

    def send(self, targets):
        if not self.connected:
            raise ConnectionError("Simulator disconnected")
        State(joints=targets)
        self.joints = dict(targets)
        self.commands.append(dict(targets))

    def stop(self):
        pass  # Immediate setpoints: no outstanding motion exists in this backend.

    def disconnect(self):
        self.connected = False
