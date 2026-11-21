# SO-101 physical commissioning

**No physical arm was connected or moved during initial development.** The owner
will supply an arm later. The adapter is tested with stubs and installed LeRobot
0.7.0 signatures; every item below still needs a supervised representative test.

## Prepare

Mount the follower securely, inspect wiring and install appropriate tools. Support
the arm before connecting: LeRobot configuration can briefly release torque. Identify
the motor supply power connector and keep it accessible. USB disconnect alone does
not reliably remove servo power. Remove sharp/heavy objects and keep people clear.

Install the hardware extra as described in SETUP.md. macOS: select a `/dev/cu.usb...`
port where available. Linux: use the serial device's appropriate group, commonly
`dialout` or `uucp`, then log in again; avoid making every serial device world-writable.

Use official LeRobot tools to identify ports. Never guess which device is the
follower when a leader or another serial board is connected.

## Motor calibration

Disconnect the application from hardware first. With the arm supported, follow the
[official SO-101 calibration](https://huggingface.co/docs/lerobot/main/so101):

```sh
uv run --extra hardware lerobot-find-port
uv run --extra hardware lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/CHOOSE_YOUR_FOLLOWER_PORT \
  --robot.id=my_follower
```

These are interactive procedures requiring your hands. Do not run them in the
background or while another process owns the arm. The application discovers saved
six-motor JSON calibration under LeRobot's configured calibration directories.
It validates ranges and IDs, hashes the file and never invents missing calibration.

## Connect and register a safe envelope

1. Start the app, Discover, and select the follower USB port and matching calibration.
2. Start an overhead or observation camera. Verify the live view and its role.
3. Support the arm, check the operator checkbox, select Physical SO-101 and Connect.
4. Open Commissioning Guide. Replace the example JSON with measured values.
5. For each of the five arm axes, verify motor-to-URDF sign and offset. Formula:
   `urdf_degrees = sign * (motor_degrees - offset)`. Do not assume every arm or
   calibration convention maps identically. Use official manual/teleoperation setup
   to establish this mapping before declaring it verified.
6. Measure the TCP in the tool frame in metres. Mount changes invalidate this offset.
7. Set tight motor bounds around a known clear installation, table Z, workspace box,
   and exclusion boxes for fixtures, cables, palette rims and known obstacles. Choose
   capsule radius to conservatively include your actual links and tool fixtures.
8. Save the actual measured standby pose; there is no stock physical home command.
9. Set the confirmation flags only after measuring and checking the installation.
   Saving does not clear Stop. Validate & Resume, then jog one degree in a clear area.
10. Compare measured encoders and visible direction. Test Stop and physical power
    disconnect before extending the envelope or running exploration.

The guide requires manual measurements rather than claiming that camera pixels or
an AI model can supply precise depth. A planar homography maps measured tabletop
points only; it is not a full camera-to-robot 3D reconstruction.

## Camera calibration

Use Register Plane with at least four non-collinear measured point pairs (image
pixels to robot XY metres) and plane Z. Check the fit using at least two different,
independently measured points. The first four points can fit exactly even when the
physical measurement is wrong; fitting residual is not an accuracy claim.

The ArUco detector is available at `/api/cameras/{id}/markers`. Use known marker
corners as correspondences. Intrinsics can be estimated with eight or more varied
checkerboard views through `/api/calibration/intrinsics`. The 0.1 release uses raw
planar correspondences; supply rectified imagery/measurements for lenses with
significant distortion. The saved intrinsics are not automatically applied to capture.

Changing a camera's mount, focus, crop or resolution invalidates registration. The
color-region detector only estimates colored regions on the registered plane and
never establishes object depth, graspability or safety. Register and explicitly
approve lightweight objects before manipulation.

## First contact

Start with a marker and one straight line. Measure the pen holder, TCP, paper plane
and a feasible orientation. The paper plane must match the commissioned contact
plane. The local planner checks the whole path before any setpoint is sent.
Review that exact plan and approve contact. Approval is one-use, expires with the
plan, and is cleared by Stop. An AI tool cannot approve contact or change safety.

Inspect the actual line and before/after images; record independent evidence and
placement error. Only an explicit operator attestation can mark a hardware skill
validated. A motor target being reached does not prove that a pen drew or a gripper
held an object. Do not attempt wet paint before dry marker work is repeatable.

## Required validation record

- Robot/adapter identity, LeRobot version and calibration digest.
- Clamp, power supply, physical disconnect test and supported-arm connection test.
- Motor signs, offsets, units, per-joint limits and measured standby configuration.
- TCP/tool geometry, table height, exclusion zones and conservative collision radius.
- Camera roles, freshness, held-out calibration errors and mount stability.
- One-degree motion direction/feedback, Stop, unplug, stale-camera and motor-fault behavior.
- Drawing fixture/contact test, then separate representative tests for every other skill.
- Live provider compatibility using an owner-supplied key, including timeout and Stop.

Never label these completed until physical evidence is recorded.
