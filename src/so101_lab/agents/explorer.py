"""Finite, evidence-ranked free-space experiments. Scores are heuristics, not probabilities."""

import time
import numpy as np
from so101_lab.domain import ARM


class Explorer:
    def __init__(self, lab):
        self.lab = lab

    def proposals(self):
        state = self.lab.robot.get_state()
        history = [e["data"] for e in self.lab.memory.events(1000) if e["kind"] == "experiment"]
        validated = [e for e in history if e.get("outcome") == "encoder_validated"]
        visited = {e["experiment"] for e in validated}
        candidates = []
        for joint in ARM:
            for sign in (1, -1):
                candidates.append(
                    {
                        "experiment": f"{joint}:{sign:+}",
                        "kind": "single_joint",
                        "joint": joint,
                        "delta": float(sign),
                        "requests": [
                            {"joints": {f"{joint}.pos": state.joints[f"{joint}.pos"] + sign}, "duration": 1}
                        ],
                    }
                )
        if len(visited) >= 5:
            candidates.append(
                {
                    "experiment": "coordinated_free_space",
                    "kind": "multi_joint",
                    "requests": [
                        {
                            "joints": {f"{j}.pos": state.joints[f"{j}.pos"] + 0.5 for j in ARM[:2]},
                            "duration": 1.5,
                        }
                    ],
                }
            )
            xyz = self.lab.controller.safety.kinematics.fk(state.joints)[:3, 3]
            candidates.append(
                {
                    "experiment": "short_cartesian_line",
                    "kind": "cartesian_path",
                    "requests": [
                        {"position": (xyz + [0.002 * t, 0, 0]).tolist(), "duration": 0.5} for t in (1, 2)
                    ],
                }
            )
        experiments = []
        for candidate in candidates:
            if candidate["experiment"] in visited:
                continue
            try:
                planned = self.lab.controller.plan(candidate["requests"])
                final = planned[-1][-1][1]
                tip = np.array(self.lab.controller.safety.kinematics.fk(final)[:3, 3])
            except ValueError:
                continue
            similar = [
                e
                for e in history
                if e.get("kind") == candidate["kind"] and e.get("joint") == candidate.get("joint")
            ]
            coverage = sum(
                np.linalg.norm(tip - np.array(e["reachable_point_fk_estimate"])) < 0.003
                for e in validated
                if e.get("reachable_point_fk_estimate")
            )
            novelty = 1 / (1 + sum(e["experiment"] == candidate["experiment"] for e in history))
            information_gain = 1 / (1 + len(similar))
            coverage_gain = 1 / (1 + coverage)
            relevance = 1.0 if candidate["kind"] != "single_joint" else 0.7
            expected_seconds = sum(frames[-1][0] for frames in planned) * 2
            uncertainty = 0.5 + min(
                0.5, sum(e.get("encoder_error_deg", 0) for e in similar) / (1 + len(similar)) / 5
            )
            table_margin = tip[2] - self.lab.controller.safety.config.table_z
            risk = min(
                1.0,
                0.15 + 0.01 / max(table_margin, 0.005) + (0.15 if candidate["kind"] != "single_joint" else 0),
            )
            score = (
                2 * information_gain
                + novelty
                + coverage_gain
                + relevance
                - 0.1 * expected_seconds
                - 2 * risk
                - uncertainty
            )
            experiments.append(
                {
                    **candidate,
                    "heuristic_score": score,
                    "score_components": {
                        "information_gain": information_gain,
                        "novelty": novelty,
                        "workspace_coverage_gain": coverage_gain,
                        "skill_relevance": relevance,
                        "expected_seconds": expected_seconds,
                        "risk": risk,
                        "uncertainty": uncertainty,
                    },
                    "information_gain_objective": "Compare local kinematic prediction with measured joint displacement",
                    "uncertainty_note": "Visual tip displacement is not independently measured; scores are scheduling heuristics",
                }
            )
        return sorted(experiments, key=lambda e: e["heuristic_score"], reverse=True)

    def run(self, budget=6):
        budget = min(max(int(budget), 1), 10)
        self.lab.observe(record=True)
        baseline = self.lab.controller.guard().joints
        measured = []
        proposals = self.proposals()[:budget]
        for experiment in proposals:
            if self.lab.controller.stopped.is_set():
                break
            current = self.lab.robot.get_state().joints
            frames = self.lab.controller.plan(experiment["requests"])
            target = frames[-1][-1][1]
            expected = self.lab.controller.safety.kinematics.fk(target)[:3, 3]
            before = self.lab.controller.safety.kinematics.fk(current)[:3, 3]
            result = self.lab.controller.execute(experiment["requests"])
            actual = self.lab.robot.get_state().joints if result.ok else current
            error = max(abs(actual[k] - target[k]) for k in current)
            record = {
                **experiment,
                "result": result.model_dump(),
                "expected_tip_delta_m": (expected - before).tolist(),
                "encoder_error_deg": error,
                "measured_at": time.time(),
                "outcome": "encoder_validated" if result.ok else "rejected",
                "visual_validation": "pending",
                "confidence": None,
                "reachable_point_fk_estimate": self.lab.controller.safety.kinematics.fk(actual)[
                    :3, 3
                ].tolist()
                if result.ok
                else None,
            }
            self.lab.memory.add("experiment", record)
            measured.append(record)
            if not result.ok:
                break
            returned = self.lab.controller.move_joints(baseline, 1)
            if not returned.ok:
                break
        report = {
            "backend": "hardware" if self.lab.robot.hardware else "simulation",
            "experiments": len(measured),
            "validated_encoder_experiments": sum(m["outcome"] == "encoder_validated" for m in measured),
            "reachable_points_fk_estimates": [
                m["reachable_point_fk_estimate"] for m in measured if m["result"]["ok"]
            ],
            "known_unreachable_regions": [],
            "camera_visibility_coverage": None,
            "mean_encoder_error_deg": float(np.mean([m["encoder_error_deg"] for m in measured]))
            if measured
            else None,
            "calibrated_cartesian_precision_m": None,
            "validated_primitives": [m["experiment"] for m in measured if m["result"]["ok"]],
            "reliable_tool_configurations": [],
            "unknown": [
                "visual displacement",
                "contact forces",
                "unobserved obstacles",
                "absolute Cartesian accuracy",
            ],
            "next": "Validate tip displacement against held-out visual calibration points; commission contact separately",
            "completion_reason": "finite catalogue exhausted"
            if not proposals
            else "bounded experiment budget or safety interruption",
            "hardware_skills_ready": [],
        }
        self.lab.memory.add("capability_report", report)
        self.lab.memory.save("capability_report", report)
        return report
