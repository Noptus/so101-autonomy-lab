from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ARM = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
JOINTS = (*ARM, "gripper")
KEYS = tuple(f"{j}.pos" for j in JOINTS)


class Validated(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class State(Validated):
    joints: dict[str, float]
    sampled_at: float = Field(default_factory=time.monotonic)
    connected: bool = True
    calibrated: bool = True

    @model_validator(mode="after")
    def complete(self):
        if set(self.joints) != set(KEYS):
            raise ValueError("Feedback must contain all six calibrated .pos keys")
        if not all(__import__("math").isfinite(v) for v in self.joints.values()):
            raise ValueError("Non-finite motor feedback")
        return self


class Box(Validated):
    lower: tuple[float, float, float]
    upper: tuple[float, float, float]

    @model_validator(mode="after")
    def bounds(self):
        if any(a >= b for a, b in zip(self.lower, self.upper)):
            raise ValueError("Box lower bounds must be below upper bounds")
        return self


class SafetyConfig(Validated):
    # Demo limits. A physical installation must explicitly commission its own profile.
    joint_limits: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "shoulder_pan.pos": (-100, 100),
            "shoulder_lift.pos": (-90, 90),
            "elbow_flex.pos": (-90, 90),
            "wrist_flex.pos": (-90, 90),
            "wrist_roll.pos": (-150, 150),
            "gripper.pos": (0, 100),
        }
    )
    workspace: Box = Field(default_factory=lambda: Box(lower=(-0.45, -0.45, 0.015), upper=(0.45, 0.45, 0.5)))
    exclusions: list[Box] = Field(default_factory=list)
    table_z: float = 0
    clearance: float = Field(default=0.012, ge=0.005)
    link_radius: float = Field(default=0.012, ge=0.005, le=0.08)
    max_velocity: float = Field(default=12, gt=0, le=30)
    max_acceleration: float = Field(default=30, gt=0, le=60)
    feedback_tolerance: float = Field(default=5, gt=0, le=10)
    max_camera_age: float = Field(default=0.75, gt=0, le=2)
    max_feedback_age: float = Field(default=0.3, gt=0, le=1)
    max_motion_seconds: float = Field(default=30, gt=0, le=120)
    max_plan_seconds: float = Field(default=180, gt=0, le=600)

    @model_validator(mode="after")
    def limits(self):
        if set(self.joint_limits) != set(KEYS):
            raise ValueError("Supply limits for all six .pos keys")
        if any(a >= b for a, b in self.joint_limits.values()):
            raise ValueError("Invalid joint bounds")
        return self


class Commissioning(Validated):
    robot_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    port: str
    calibration_sha256: str = Field(min_length=64, max_length=64)
    safety: SafetyConfig
    motor_signs: dict[str, Literal[-1, 1]]
    motor_offsets: dict[str, float]
    tcp: tuple[float, float, float] = (0, 0, 0)
    standby: dict[str, float]
    operator_present: Literal[True]
    supported_arm: Literal[True]
    mapping_verified: Literal[True]
    envelope_verified: Literal[True]
    camera_id: str

    @model_validator(mode="after")
    def mapping(self):
        if set(self.motor_signs) != set(ARM) or set(self.motor_offsets) != set(ARM):
            raise ValueError("Verify signs and offsets for the five positioning joints")
        State(joints=self.standby)
        return self


class Result(Validated):
    ok: bool
    stage: Literal["planning", "validation", "execution", "verification"] = "validation"
    message: str
    data: dict = Field(default_factory=dict)
    physical_verified: bool = False
