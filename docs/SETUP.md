# Install and start

Install uv, Git, and a modern browser. uv selects Python 3.12 automatically. Python
3.12 and 3.13 are supported; other Python versions are deliberately excluded from
the lock to keep optional robotics packages reproducible.

```sh
git clone https://github.com/Noptus/so101-autonomy-lab.git
cd so101-autonomy-lab
uv sync --locked
uv run so101-lab
```

Open http://127.0.0.1:8765. There is no Node.js build, external database or cloud
account required for simulation. If the port is occupied, leave the other service
running and use `uv run so101-lab --port 8766`.

The application always starts in simulation. It does not open a serial port or
energize an arm automatically. Previously selected cameras may be reopened.

## Try it without hardware or API keys

1. Preview Drawing with `{"shape":"square"}` and run the simulated plan.
2. Preview Sorting, Cleanup, Chess (`{"move":"e2e4"}`), Stacking, Painting
   (`{"shape":"line"}`), and Tic-Tac-Toe using the supplied demo fixtures.
3. Run Explore My Workspace. The finite experiment budget produces a report.
4. Use Stop during a simulated task. Wait for the worker to finish, then Validate
   & Resume. No interrupted task resumes by itself.
5. Export JSONL to inspect recorded commands, actual encoder results and outcomes.

Demo paper is a plane in free space, not a physical desk. The default simulator is
an exact encoder-setpoint model, not a physics model of paint, grasps or friction.

## Optional MuJoCo

```sh
uv sync --locked --extra mujoco
uv run --extra mujoco so101-lab
```

Choose MuJoCo in Backend and Connect. This exercises joint dynamics using approximate
capsules and servo gains; gravity and object contact are intentionally not modeled.
It does not prove that a real grasp or pen contact will succeed.

## Optional hardware package

```sh
uv sync --locked --extra hardware
uv run --extra hardware so101-lab
```

Keep using `--extra hardware` on `uv run` so environment synchronization includes
LeRobot. See HARDWARE.md before connecting. macOS and Linux are primary hardware
targets. Windows core simulation/API are supported; native hardware compatibility
is not validated here. WSL USB pass-through is an option for Windows users familiar
with USB device forwarding. Placo is not required by this application.

## Models and API keys

Choose a provider preset, enter its key or export its environment variable, then
Save and Discover Models. Select an actual ID, save, and run the synthetic image +
tool probe. No live model call has been validated with a real key in this repository's
creation session; protocol behavior is tested with HTTP stubs.

The test sends a synthetic red image and asks for a structured color tool call.
A listed model is not considered compatible until it passes. The probe expires
after a day. Use the custom OpenAI-compatible endpoint for vLLM, llama.cpp or other
servers with a compatible chat, models, image and tool API. Some models are text-only
or lack tools; they will fail the probe explicitly.

Keys stay in server memory by default. Optional persistence uses the OS keychain.
If the keychain is unavailable, the app reports it; it never silently writes plaintext
keys. Keys are scoped to endpoint URLs. A changed custom endpoint does not receive
a key stored for another provider. `.env.example` is not automatically loaded.

Image sharing is off by default. Enabling it sends selected camera images and
structured tool context to the chosen endpoint. Local model servers can themselves
route requests to cloud models, so inspect their configuration.

## Runtime storage and remote use

State, camera settings, commissioning references and recordings live in `.so101-lab/`
under the working directory, or `--data-dir` / `SO101_DATA_DIR`. The directory is
permission-restricted and ignored by Git. Recordings include private camera images.
Back it up deliberately; never commit it.

Local requests use same-origin protection and a required custom mutation header.
Remote binding requires a 32-character `SO101_REMOTE_TOKEN`; deploy only behind a
trusted TLS proxy and provide the token when the dashboard asks. The token is kept
in browser memory, not local storage. Hardware still requires a visible supervised
dashboard heartbeat. Do not expose a robot controller on an untrusted public network.

## Troubleshooting

| Symptom | Action |
|---|---|
| Port 8765 in use | Start with `--port 8766`; do not kill the other service. |
| No serial devices | Check data-capable USB cable, adapter power and OS permissions. |
| Several serial devices | Select the follower explicitly; USB identity cannot prove arm role. |
| No motor calibration | Disconnect the app, run official LeRobot calibration and rediscover. |
| Calibration digest changed | Repeat measured commissioning; do not reuse the previous declaration. |
| Camera not found | Grant camera permission to the Python/terminal process; close other camera apps. |
| Camera stale | Check cable and lighting, restart capture while idle; validate before resuming. |
| Operator presence expired | Keep the dashboard visible with the supervision checkbox checked. |
| Unreachable orientation | SO-101 has five positioning DOF; adjust the task fixture or target. |
| Capsule/table rejection | Inspect real geometry and TCP mapping; never disable the check to force a path. |
| Provider 401/404 | Check endpoint, API key and actual model ID; aliases and availability can change. |
| Probe fails | Choose a model that supports both images and tools on that endpoint. |
| Keychain unavailable | Use session-only key storage or an environment variable. |
