# Exercise manual

Every exercise has four stages: plan, local validation, execution, and independent
physical verification. Simulation demonstrates geometric paths and rejection behavior.
It cannot prove that ink touched paper or a block stayed in the gripper.

## 0. Work without an arm

Start simulation, inspect all six motors, jog one arm joint by one degree, preview a
gripper opening and move the TCP a few millimetres. Preview a square, run it and stop
mid-path. Validate & Resume and request a new plan. Inspect/export the event timeline.
Try an unreachable target and verify that no setpoints are sent.

Run Explore: experiments are ranked by explicit information-gain objectives, novelty,
coverage/relevance heuristics, time and risk. Initial trials move one joint by one
degree and return to the measured baseline. The budget is finite. Reports distinguish
encoder validation, FK estimates and unknown camera/physical precision.

## 1. Commission hardware

Follow HARDWARE.md with an operator and a fresh camera. Test connection, read six
calibrated motor values, one-degree jog, Stop, disconnect and revalidation. Verify
signs and offsets before using Cartesian control. Keep the initial envelope small.
Then fit the paper plane and measure independent check points.

## 2. Drawing

Install a secure marker holder; measure the tip offset and a feasible tool orientation.
Register a flat paper plane matching the commissioned contact plane. In Drawing Setup,
provide origin, orthonormal planar axes, width/height in metres, pen lift and verified
flags. In physical mode also set `measured_on_hardware` after measurements.

Preview parameters progress from `{"shape":"line"}` to `square`, `triangle`, `circle`,
`HELLO`, then `house`. Custom normalized polylines use
`{"strokes":[[[0,0],[1,0],[1,1]]]}`. An agent can generate these through draw_strokes;
it cannot generate contact approval. Review each full plan before execution.

Measure line placement with a ruler or registered overhead image and record maximum
or RMS error plus stroke completion count in the verification notes. Compare before
and after images. Adjust the next plan using measured offsets; never increase contact
depth blindly or claim a geometric trajectory proves a visible drawing.

## 3. Tic-tac-toe

Use the drawing fixture and a registered grid within the setup rectangle. `grid` has
nine characters (`.` empty, `X`, `O`) in row-major order. Start with `.........` and
`{"player":"X"}`. The minimax planner chooses a legal move and emits pen-up/down
strokes. Observe a human's reply, enter the measured grid in Setup and plan the next
turn. Illegal turns and finished games are rejected. Automatic camera grid recognition
is not provided in 0.1; board transcription is explicit.

## 4. Sorting and table cleanup

Start with one measured, lightweight foam block. Register its grasp-center position,
size, ID and color; set `approved` and `lightweight_foam` only for appropriate objects.
Register an empty tray slot for each cleanup object. Sorting uses color-named trays.
Measure gripper open/closed values, approach lift and a feasible grasp orientation.

Validate a representative grasp, then progress to one transfer, three transfers and
several approved objects. Sorting rejects unknown categories without a registered
tray. The color detector can suggest regions, but physical grasps use explicit measured
object registration. Do not attempt sharp, hot, heavy, fragile, powered or liquid-filled
objects. Inspect each grasp/placement; a failed transfer invalidates the remainder's
assumptions. Use short plans initially, one object at a time, with fresh registration.

## 5. Stacking

Reuse a validated foam-block grasp. Register `destinations.stack`, measure each block's
height, and start with one placement, then two blocks, then three. The planner adds
measured heights for successive placements. Verify stack alignment before continuing.
If a stack falls, Stop, clear/re-register positions and request a new plan. The simulator
does not model stability or permit autonomous recovery based only on a previous plan.

## 6. Chess

Register an aligned board rectangle (`origin`, `width`, `height`) and piece grasp-center
height. Confirm the entire board and approach paths fit the arm's reachable envelope.
Start with a small board, known FEN and manually registered pieces. Use `{"move":"e2e4"}`
in the demo; physical work starts with one representative piece between empty squares.

python-chess validates legality. Captures require an empty `capture` tray slot;
en passant transfers the pawn from the correct adjacent square. Castling adds the
rook transfer. Promotion requires `promotion_q` (or r/b/n) and `pawn_return` fixture
slots, otherwise planning rejects it. Clear/re-register the capture slot after use.

Progress through five known moves, one capture and a simple endgame. Before a human
move, record the FEN. Enter the observed board FEN and use
`detect_human_move(before_fen, observed_fen)` to identify the unique legal transition.
The source has a configurable `stockfish_move(fen, executable)` helper using UCI;
install Stockfish separately and pass its local executable. No model invents legal
moves or piece poses. Automatic full-board visual recognition and unattended physical
games are not implemented. Inspect every physical move before advancing saved FEN.

## 7. Painting

Use a marker first. Then securely install a brush, measure its tip, the paper plane,
paint wells, dip depth and optional cleaning station. Enter `palette` coordinates and
`brush_dip_depth` (0–3 mm). Start with one color and `{"shape":"line"}`, then use
explicit polylines for parallel lines, a filled square, flower, landscape or an
AI-generated illustration. Color order follows the configured palette; review the
station approaches and whole stroke sequence. Use a cleaning station for color changes.

The planner includes brush loading and cleaning approaches, but neither paint viscosity,
brush force, fluid level nor station wall geometry is inferred. Declare station walls
as exclusion zones. Verify actual coverage, color and smearing. Wet-paint readiness
requires its own representative physical test; drawing validation does not imply it.

## Record completion honestly

Readiness is “setup required”, “ready to test”, “validated in simulation”, or
“validated on hardware (operator attested)”. Hardware validation requires actual
execution, independent evidence and an explicit success attestation. Record remaining
uncertainty and the safest next experiment; do not convert a model estimate into a
measurement or silently advance game state after an unverified move.
