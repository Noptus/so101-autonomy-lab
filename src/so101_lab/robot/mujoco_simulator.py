"""Optional MuJoCo joint-dynamics backend using the same calibrated-degree interface.

Geometry comes from our URDF link transforms, represented as capsules. It is not a
validated dynamic model of the servos and does not simulate grasp/contact success.
"""

import numpy as np
from scipy.spatial.transform import Rotation
from so101_lab.domain import ARM
from so101_lab.robot.simulator import SimulatedRobot
from so101_lab.motion.kinematics import Kinematics


class MuJoCoRobot(SimulatedRobot):
    name = "mujoco"

    def connect(self):
        try:
            import mujoco
        except ImportError as exc:
            raise ValueError("Install optional simulator: uv sync --extra mujoco") from exc
        self.mj = mujoco
        k = Kinematics()
        root = __import__("xml.etree.ElementTree", fromlist=["Element"]).Element
        import xml.etree.ElementTree as ET

        model = root("mujoco", model="so101_capsule_approximation")
        ET.SubElement(model, "option", timestep="0.002", gravity="0 0 0", integrator="implicitfast")
        world = ET.SubElement(model, "worldbody")
        actuator = ET.SubElement(model, "actuator")
        parent = world
        for name in ARM:
            j = next(j for j in k.joints if j.get("name") == name)
            origin = j.find("origin")
            quat_xyzw = Rotation.from_euler("xyz", np.fromstring(origin.get("rpy"), sep=" ")).as_quat()
            quat = np.roll(quat_xyzw, 1)
            body = ET.SubElement(
                parent, "body", name=name, pos=origin.get("xyz"), quat=" ".join(map(str, quat))
            )
            lo, hi = k.limits[name]
            ET.SubElement(
                body,
                "joint",
                name=name,
                type="hinge",
                axis=j.find("axis").get("xyz"),
                range=f"{lo} {hi}",
                damping="1",
                armature=".02",
            )
            ET.SubElement(
                body, "geom", type="capsule", size=".012 .025", mass=".1", contype="0", conaffinity="0"
            )
            ET.SubElement(actuator, "position", joint=name, kp="60", kv="4")
            parent = body
        self.model = mujoco.MjModel.from_xml_string(ET.tostring(model, encoding="unicode"))
        self.data = mujoco.MjData(self.model)
        self.data.qpos[:] = np.deg2rad([self.joints[f"{j}.pos"] for j in ARM])
        self.data.ctrl[:] = self.data.qpos[:]
        mujoco.mj_forward(self.model, self.data)
        self.connected = True

    def send(self, targets):
        if not self.connected:
            raise ConnectionError("MuJoCo disconnected")
        self.data.ctrl[:] = np.deg2rad([targets[f"{j}.pos"] for j in ARM])
        for _ in range(17):
            self.mj.mj_step(self.model, self.data)
        for j, q in zip(ARM, np.rad2deg(self.data.qpos)):
            self.joints[f"{j}.pos"] = float(q)
        self.joints["gripper.pos"] = targets["gripper.pos"]
        self.commands.append(dict(targets))

    def stop(self):
        if self.connected:
            self.data.ctrl[:] = self.data.qpos[:]
            self.data.qvel[:] = 0
