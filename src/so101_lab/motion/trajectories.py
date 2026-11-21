import math
import numpy as np


def trajectory(start, target, duration, velocity, acceleration, hz=30):
    """Quintic interpolation with analytic bounds; stretch duration to respect dynamics."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be finite and positive")
    if set(target) != set(start) or not all(math.isfinite(v) for v in target.values()):
        raise ValueError("A complete finite target is required")
    distance = max(abs(target[k] - start[k]) for k in start)
    duration = max(duration, 1.875 * distance / velocity, math.sqrt(5.774 * distance / acceleration))
    n = max(2, math.ceil(duration * hz))
    return [
        (
            duration * i / n,
            {k: start[k] + (target[k] - start[k]) * (10 * u**3 - 15 * u**4 + 6 * u**5) for k in start},
        )
        for i, u in enumerate(np.linspace(0, 1, n + 1))
    ]
