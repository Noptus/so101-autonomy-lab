"""URDF FK and bounded, current-pose-seeded numerical IK. SI geometry, motor degrees."""

from importlib.resources import files
from functools import lru_cache
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from so101_lab.domain import ARM


def transform(xyz=(0, 0, 0), rpy=(0, 0, 0)):
    t = np.eye(4)
    t[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
    t[:3, 3] = xyz
    return t


class Kinematics:
    def __init__(self, *, tcp=(0, 0, 0), signs=None, offsets=None, urdf=None):
        root = ET.parse(urdf or files("so101_lab").joinpath("assets/so101.urdf")).getroot()
        self.joints = list(root.findall("joint"))
        self.tcp = np.array(tcp, float)
        self.signs = signs or dict.fromkeys(ARM, 1)
        self.offsets = offsets or dict.fromkeys(ARM, 0.0)
        self.limits = {}
        for j in self.joints:
            if j.get("name") in ARM:
                lim = j.find("limit")
                self.limits[j.get("name")] = np.rad2deg([float(lim.get("lower")), float(lim.get("upper"))])

    def frames(self, joints):
        return self._frames(tuple(joints[f"{j}.pos"] for j in ARM))

    @lru_cache(maxsize=4096)
    def _frames(self, arm_positions):
        joints = {f"{j}.pos": q for j, q in zip(ARM, arm_positions)}
        frames = {"base_link": np.eye(4)}
        pending = list(self.joints)
        while pending:
            progressed = False
            for j in list(pending):
                parent, child = j.find("parent").get("link"), j.find("child").get("link")
                if parent not in frames:
                    continue
                origin = j.find("origin")
                xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ") if origin is not None else [0, 0, 0]
                rpy = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ") if origin is not None else [0, 0, 0]
                t = transform(xyz, rpy)
                name = j.get("name")
                if name in ARM:
                    angle = np.deg2rad(self.signs[name] * (joints[f"{name}.pos"] - self.offsets[name]))
                    axis = np.fromstring(j.find("axis").get("xyz"), sep=" ")
                    rot = np.eye(4)
                    rot[:3, :3] = Rotation.from_rotvec(axis * angle).as_matrix()
                    t = t @ rot
                # Gripper is not an arm DOF; fixed jaw/TCP geometry is used for planning.
                frames[child] = frames[parent] @ t
                pending.remove(j)
                progressed = True
            if not progressed:
                raise ValueError("URDF contains a disconnected or cyclic joint tree")
        return frames

    def fk(self, joints):
        t = self.frames(joints)["gripper_frame_link"].copy()
        t[:3, 3] += t[:3, :3] @ self.tcp
        return t

    def segments(self, joints):
        f = self.frames(joints)
        names = [
            "shoulder_link",
            "upper_arm_link",
            "lower_arm_link",
            "wrist_link",
            "gripper_link",
            "gripper_frame_link",
        ]
        points = [f[n][:3, 3] for n in names] + [self.fk(joints)[:3, 3]]
        return list(zip(points[:-1], points[1:]))

    def ik(self, xyz, current, limits, orientation=None):
        xyz = np.asarray(xyz, float)
        if xyz.shape != (3,) or not np.isfinite(xyz).all() or np.linalg.norm(xyz) > 0.65:
            raise ValueError("Unreachable or invalid Cartesian target")
        desired = Rotation.from_euler("xyz", orientation, degrees=True) if orientation is not None else None
        bounds = []
        for j in ARM:
            lo, hi = limits[f"{j}.pos"]
            a, b = self.limits[j]
            model_bounds = sorted([self.offsets[j] + a / self.signs[j], self.offsets[j] + b / self.signs[j]])
            bounds.append((max(lo, model_bounds[0]), min(hi, model_bounds[1])))
        low, high = np.array(bounds).T
        seed = np.clip([current[f"{j}.pos"] for j in ARM], low + 1e-6, high - 1e-6)

        def joint_map(q):
            return {**current, **{f"{j}.pos": float(v) for j, v in zip(ARM, q)}}

        def error(q):
            pose = self.fk(joint_map(q))
            e = (pose[:3, 3] - xyz) * 100
            if desired is not None:
                e = np.r_[e, (desired.inv() * Rotation.from_matrix(pose[:3, :3])).as_rotvec()]
            return np.r_[e, (q - seed) * 0.00001]

        candidates = []
        for q0 in (seed, (seed + (low + high) / 2) / 2):
            solved = least_squares(
                error, q0, bounds=(low, high), max_nfev=150, ftol=1e-9, xtol=1e-9, gtol=1e-9
            )
            q = joint_map(solved.x)
            pose = self.fk(q)
            pos_error = float(np.linalg.norm(pose[:3, 3] - xyz))
            rot_error = (desired.inv() * Rotation.from_matrix(pose[:3, :3])).magnitude() if desired else 0
            if pos_error < 0.001 and rot_error < np.deg2rad(5):
                candidates.append((np.linalg.norm(solved.x - seed), q))
        if not candidates:
            raise ValueError("IK cannot satisfy position/orientation within 1 mm / 5 degrees (five arm DOF)")
        return min(candidates, key=lambda c: c[0])[1]
