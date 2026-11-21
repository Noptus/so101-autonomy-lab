# Working on SO-101 Autonomy Lab

Keep projects and work files under `/Volumes/Tsunami Utilities/Projects` when that
volume is available. Runtime data, keys, observations and calibration are private:
never commit `.so101-lab`, `.env`, `work`, API keys or personal camera images.

## Development

- Python 3.12–3.13; `uv sync --locked`, `uv run pytest`, `uv run ruff check src tests`.
- The default is an encoder simulator. Importing or testing modules must not open
  serial ports, turn on motors or probe cameras without an explicit operator action.
- Unit and integration tests use simulation, synthetic images and hardware stubs.
  Never run hardware commissioning or physical motion as part of automated tests.
- Read docs/ARCHITECTURE.md and docs/SAFETY.md before changing control behavior.
- Keep model IDs dynamic. Model-list presence is not a vision/tool capability guarantee.
- Do not fabricate measured precision, probabilities, physical success or hardware readiness.

## Safety-critical changes

`motion/`, `robot/lerobot_adapter.py`, `domain.py`, commissioning, operator presence,
contact approval and secret handling are safety-critical. Changes require regression
tests, a documented rationale and human review before any physical deployment.
Publishing development source is permitted; it does not establish hardware validation.

Never bypass MotionController, clear a stop from an agent tool, weaken calibration
requirements, add autonomous servo register tools, auto-connect hardware, auto-resume
recordings, or disable freshness/feedback checks. Only five joints position the TCP.
The gripper uses 0–100, arm joints use explicitly configured calibrated degrees.

UI, documentation, provider adapters and deterministic skill planners may be improved
freely while preserving those invariants. New skills must generate a fully preflighted
plan and use exact-plan operator contact approval. Do not add network services to the
local motion loop or arbitrary shell execution to the model harness.

## Physical validation

The owner has no SO-101 connected at repository creation. Keep all hardware validation
pending until the owner supplies an arm. Record the actual model, calibration digest,
fixtures, camera, limits, representative result and evidence when it is tested.
