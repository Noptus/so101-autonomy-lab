import time
import numpy as np
from so101_lab.domain import ARM, KEYS, SafetyConfig


class Unsafe(ValueError):
    pass


def segment_box(a, b, lower, upper):
    """Closed segment / AABB slab intersection, including tangencies."""
    t0, t1 = 0.0, 1.0
    for p, d, lo, hi in zip(a, np.array(b) - a, lower, upper):
        if abs(d) < 1e-12:
            if p < lo or p > hi:
                return False
        else:
            x, y = sorted(((lo - p) / d, (hi - p) / d))
            t0, t1 = max(t0, x), min(t1, y)
            if t0 > t1:
                return False
    return True


def segment_distance(a, b, c, d):
    # Minimum of the interior stationary point and four convex edge minima.
    a, b, c, d = map(np.asarray, (a, b, c, d))
    u, v, w = b - a, d - c, a - c
    aa, bb, cc, dd, ee = float(u @ u), float(u @ v), float(v @ v), float(u @ w), float(v @ w)

    def clamp(x):
        return max(0.0, min(1.0, x))

    candidates = [
        (0.0, clamp(ee / cc) if cc > 1e-15 else 0.0),
        (1.0, clamp((ee + bb) / cc) if cc > 1e-15 else 0.0),
        (clamp(-dd / aa) if aa > 1e-15 else 0.0, 0.0),
        (clamp((bb - dd) / aa) if aa > 1e-15 else 0.0, 1.0),
    ]
    determinant = aa * cc - bb * bb
    if determinant > 1e-15:
        x, y = (bb * ee - cc * dd) / determinant, (aa * ee - bb * dd) / determinant
        if 0 <= x <= 1 and 0 <= y <= 1:
            candidates.append((x, y))
    return min(float(np.linalg.norm(w + x * u - y * v)) for x, y in candidates)


class Safety:
    def __init__(self, config: SafetyConfig, kinematics):
        self.config, self.kinematics = config, kinematics

    def state(self, state):
        if not state.connected or not state.calibrated:
            raise Unsafe("Connected, calibrated feedback required")
        age = time.monotonic() - state.sampled_at
        if age < -0.01 or age > self.config.max_feedback_age:
            raise Unsafe("Motor feedback is stale or has an invalid timestamp")
        self.joints(state.joints)

    def joints(self, target):
        if set(target) != set(KEYS):
            raise Unsafe("Expected all six calibrated .pos keys")
        for key, value in target.items():
            lo, hi = self.config.joint_limits[key]
            if not np.isfinite(value) or not lo <= value <= hi:
                raise Unsafe(f"Joint limit: {key}")
        for j in ARM:
            q = self.kinematics.signs[j] * (target[f"{j}.pos"] - self.kinematics.offsets[j])
            if not self.kinematics.limits[j][0] <= q <= self.kinematics.limits[j][1]:
                raise Unsafe(f"URDF limit: {j}")

    def pose(self, target, *, contact=False):
        self.joints(target)
        cfg = self.config
        tip = self.kinematics.fk(target)[:3, 3]
        lo, hi = np.array(cfg.workspace.lower), np.array(cfg.workspace.upper)
        if contact:
            lo[2] = cfg.table_z - 0.001
        if np.any(tip < lo) or np.any(tip > hi):
            raise Unsafe("TCP leaves configured workspace")
        if tip[2] < cfg.table_z + (0 if contact else cfg.clearance) - 0.001:
            raise Unsafe("TCP violates table-plane clearance")
        segments = self.kinematics.segments(target)
        for i, (a, b) in enumerate(segments):
            # First two attached links intersect the mounted base by design.
            if (
                i >= 1
                and min(a[2], b[2]) - (0 if contact and i == len(segments) - 1 else cfg.link_radius)
                < cfg.table_z - 0.001
            ):
                raise Unsafe("Link capsule intersects table plane")
            for box in cfg.exclusions:
                if segment_box(
                    a, b, np.array(box.lower) - cfg.link_radius, np.array(box.upper) + cfg.link_radius
                ):
                    raise Unsafe("Link capsule intersects an exclusion zone")
        for i in range(len(segments) - 1):
            for j in range(i + 3, len(segments) - 1):
                if segment_distance(*segments[i], *segments[j]) < 2 * cfg.link_radius:
                    raise Unsafe("Non-adjacent link capsules intersect")
        return tip.tolist()
