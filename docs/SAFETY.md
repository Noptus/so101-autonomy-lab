# Safety model and limits

This is experimental, supervised robotics software, not a certified safety controller.
No physical validation has occurred. An SO-101 can pinch, collide, break tools or fall
under gravity. Work with a mounted arm and a reachable motor power disconnect.

## Stop and fault behavior

The red Stop and Pause controls latch a threading event immediately. The provider
request is cancelled separately. The motion worker checks the latch before each
setpoint; it does not wait for the AI. When communication is usable it holds measured
positions. Serial I/O can block or fail: software cannot guarantee an emergency stop
latency under a failed driver. Remove motor power in an emergency. Support the arm
before releasing power because gravity may move it.

Stop does not automatically release torque. Disconnect attempts a measured hold and
keeps LeRobot's disconnect torque-release option disabled; this prevents an unexpected
fall. Manually support and power down the arm. Faulted motion never resumes by itself.
Validate & Resume rechecks encoders, calibration, geometry, operator presence and a
fresh camera, then only permits new requests. It never restarts the old task.

## Authoritative command path

All manual and model motion passes through one MotionController. It serializes
execution, solves five-joint IK, creates bounded quintic trajectories, preflights the
entire plan, checks table and exclusion geometry, monitors feedback/freshness and
verifies final encoders. A file lock prevents two Lab processes with different data
directories from opening the same serial port. LeRobot also enforces a 2-degree
relative setpoint limit. Other external robotics programs must remain disconnected.

The HTTP server has one worker and a separate data-directory owner lock. Serial
transport has its own I/O lock. Do not run the app under a multi-worker/reload server.

## Mandatory hardware gates

- Saved six-motor calibration, matching calibration digest and verified model mapping.
- Operator-supported connection, measured limits and a clear commissioned envelope.
- Fresh required camera and calibrated motor feedback before every movement sample.
- Operator heartbeat (visible dashboard and supervision checkbox); expiration rejects
  further motion and latches a running motion fault. This is a supervision aid, not
  certified presence detection.
- Exact-plan, one-use operator approval for physical contact and gripper movement.
- No autonomous shell, servo register tools, calibration editing, safety relaxation,
  physical probing of obstacles or automatic retry after rejected motion.

## Collision and physical verification limits

The URDF supplies actual joint transforms and kinematic bounds. Collision checks use
capsules between link frames, a table plane and operator-declared axis-aligned boxes.
They sample the joint trajectory at the controller rate; they are not continuous swept
full-mesh collision detection. Choose conservative radii and clearance and validate
the entire installation slowly. Base-adjacent links are exempt from table checks
because the model includes the mounted base. Only the final TCP segment is allowed
contact with the table plane during an approved contact plan; arm links remain checked.

Missing objects, self-collision geometry, compliance, cable snagging, fingers, force,
brush pressure, object dynamics and model-to-physical errors are not fully modeled.
Monocular vision cannot establish depth or obstacle solidity. Servo currents are not
used as a force or collision guarantee. Do not equate geometric acceptance with a
safe physical trajectory or an achieved task.

The simulator validates command behavior, kinematics and rejection paths. It does not
validate grasps, ink, paint, physical chess recognition, motor torque or contact force.
Task success on hardware requires independent inspection and an operator evidence
record. Confidence values remain unknown unless actually measured.
