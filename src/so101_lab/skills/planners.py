"""Seven deterministic planners. Registered physical geometry is always explicit."""

from __future__ import annotations

import math
from functools import lru_cache
import chess
import chess.engine
import numpy as np
from pydantic import Field, model_validator
from so101_lab.domain import Validated

SKILLS = {
    "drawing": {"requires": ["pen holder", "paper plane", "TCP offset"], "exercise": "square"},
    "painting": {
        "requires": ["brush holder", "paper plane", "palette", "brush loading depth"],
        "exercise": "flower",
    },
    "chess": {
        "requires": ["registered board", "known piece heights", "capture tray", "verified grasp"],
        "exercise": "e2e4",
    },
    "cleanup": {
        "requires": ["approved lightweight objects", "registered tray", "verified grasp"],
        "exercise": "three blocks",
    },
    "sorting": {
        "requires": ["registered objects", "labeled trays", "verified grasp"],
        "exercise": "red / blue blocks",
    },
    "stacking": {
        "requires": ["measured blocks", "registered target", "verified grasp"],
        "exercise": "two blocks",
    },
    "tic_tac_toe": {
        "requires": ["pen holder", "paper plane", "registered 3×3 grid"],
        "exercise": "first move",
    },
}


class RegisteredObject(Validated):
    id: str
    position: tuple[float, float, float]
    color: str = "unknown"
    size_m: float = Field(default=0.015, gt=0.002, le=0.04)
    approved: bool = False
    lightweight_foam: bool = False


class SkillSetup(Validated):
    origin: tuple[float, float, float]
    axis_u: tuple[float, float, float] = (1, 0, 0)
    axis_v: tuple[float, float, float] = (0, 1, 0)
    width: float = Field(default=0.02, gt=0.002, le=0.3)
    height: float = Field(default=0.02, gt=0.002, le=0.3)
    lift: float = Field(default=0.02, ge=0.005, le=0.1)
    orientation: tuple[float, float, float] | None = None
    tcp_verified: bool = False
    plane_verified: bool = False
    grasp_verified: bool = False
    objects: list[RegisteredObject] = Field(default_factory=list, max_length=20)
    destinations: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    palette: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    clean_station: tuple[float, float, float] | None = None
    brush_dip_depth: float = Field(default=0.001, ge=0, le=0.003)
    gripper_open: float = Field(default=80, ge=0, le=100)
    gripper_closed: float = Field(default=35, ge=0, le=100)
    piece_height: float = Field(default=0.025, gt=0.005, le=0.08)
    fen: str = chess.STARTING_FEN
    grid: str = "........."
    measured_on_hardware: bool = False

    @model_validator(mode="after")
    def axes(self):
        u, v = np.array(self.axis_u), np.array(self.axis_v)
        if abs(np.linalg.norm(u) - 1) > 0.001 or abs(np.linalg.norm(v) - 1) > 0.001 or abs(u @ v) > 0.001:
            raise ValueError("Plane axes must be orthonormal")
        if np.cross(u, v)[2] < 0.99:
            raise ValueError("Initial contact skills require a horizontal, upward facing plane")
        if len(self.grid) != 9 or any(x not in ".XO" for x in self.grid):
            raise ValueError("Grid requires nine . X O cells")
        if len({o.id for o in self.objects}) != len(self.objects):
            raise ValueError("Object IDs must be unique")
        if self.gripper_closed >= self.gripper_open:
            raise ValueError("Closed gripper value must be smaller than open")
        chess.Board(self.fen)
        return self

    def point(self, u, v, dz=0):
        return (
            np.array(self.origin) + np.array(self.axis_u) * u + np.array(self.axis_v) * v + [0, 0, dz]
        ).tolist()


def position(xyz, setup, duration=0.4):
    return {"position": list(xyz), "orientation": setup.orientation, "duration": duration}


def path_segment(a, b, setup):
    # Cartesian line subdivision, then every interpolated joint sample is also checked.
    count = max(1, int(math.ceil(np.linalg.norm(np.array(b) - a) / 0.004)))
    return [
        position((np.array(a) + (np.array(b) - a) * t).tolist(), setup) for t in np.linspace(0, 1, count + 1)
    ]


def drawing_strokes(shape="square"):
    if shape == "line":
        return [[[0, 0], [1, 0]]]
    if shape == "square":
        return [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
    if shape == "triangle":
        return [[[0, 0], [1, 0], [0.5, 1], [0, 0]]]
    if shape == "circle":
        return [
            [[0.5 + 0.45 * math.cos(t), 0.5 + 0.45 * math.sin(t)] for t in np.linspace(0, 2 * math.pi, 33)]
        ]
    if shape == "house":
        return drawing_strokes("square") + [
            [[0, 1], [0.5, 1.4], [1, 1]],
            [[0.4, 0], [0.4, 0.5], [0.6, 0.5], [0.6, 0]],
        ]
    if shape.upper() == "HELLO":
        glyphs = {
            "H": [[[0, 0], [0, 1]], [[1, 0], [1, 1]], [[0, 0.5], [1, 0.5]]],
            "E": [[[1, 0], [0, 0], [0, 1], [1, 1]], [[0, 0.5], [0.8, 0.5]]],
            "L": [[[0, 1], [0, 0], [1, 0]]],
            "O": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
        }
        return [
            [[(i * 1.3 + x) / 6.2, y] for x, y in stroke]
            for i, letter in enumerate("HELLO")
            for stroke in glyphs[letter]
        ]
    raise ValueError("Choose line, square, triangle, circle, HELLO or house, or provide polylines")


def draw_plan(setup, strokes):
    if not strokes or len(strokes) > 100:
        raise ValueError("Supply 1–100 strokes")
    plan = []
    for stroke in strokes:
        if not 2 <= len(stroke) <= 200:
            raise ValueError("Each stroke needs 2–200 points")
        if any(len(p) != 2 or not all(math.isfinite(x) and -0.1 <= x <= 1.5 for x in p) for p in stroke):
            raise ValueError("Normalized stroke coordinates out of bounds")
        points = [setup.point(x * setup.width, y * setup.height) for x, y in stroke]
        plan.extend([position(np.array(points[0]) + [0, 0, setup.lift], setup), position(points[0], setup)])
        for a, b in zip(points, points[1:]):
            plan.extend(path_segment(a, b, setup))
        plan.append(position(np.array(points[-1]) + [0, 0, setup.lift], setup))
    return plan


def pick_place(setup, source, destination):
    source, destination = np.array(source), np.array(destination)
    lift = max(source[2], destination[2]) + setup.lift
    above_s, above_d = source.copy(), destination.copy()
    above_s[2] = above_d[2] = lift
    return [
        position(above_s, setup),
        {"joints": {"gripper.pos": setup.gripper_open}},
        position(source, setup),
        {"joints": {"gripper.pos": setup.gripper_closed}},
        position(above_s, setup),
        position(above_d, setup),
        position(destination, setup),
        {"joints": {"gripper.pos": setup.gripper_open}},
        position(above_d, setup),
    ]


def approved_objects(setup):
    if not setup.objects:
        raise ValueError("Register at least one object")
    if any(not o.approved or not o.lightweight_foam for o in setup.objects):
        raise ValueError("Only explicitly approved lightweight foam objects may be manipulated")
    return setup.objects


def chess_plan(setup, uci):
    board = chess.Board(setup.fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise ValueError("Illegal chess move")

    def square(s):
        p = setup.point(
            (chess.square_file(s) + 0.5) * setup.width / 8, (chess.square_rank(s) + 0.5) * setup.height / 8
        )
        p[2] += setup.piece_height / 2
        return p

    transfers = []
    capture_square = move.to_square
    if board.is_en_passant(move):
        capture_square = move.to_square + (-8 if board.turn else 8)
    if board.is_capture(move):
        if "capture" not in setup.destinations:
            raise ValueError("Register a free capture-tray slot")
        transfers.append((square(capture_square), setup.destinations["capture"]))
    transfers.append((square(move.from_square), square(move.to_square)))
    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        kingside = chess.square_file(move.to_square) > 4
        transfers.append(
            (
                square(chess.square(7 if kingside else 0, rank)),
                square(chess.square(5 if kingside else 3, rank)),
            )
        )
    if move.promotion:
        replacement = f"promotion_{chess.piece_symbol(move.promotion)}"
        if replacement not in setup.destinations or "pawn_return" not in setup.destinations:
            raise ValueError("Register promotion replacement and pawn-return slots")
        transfers.extend(
            [
                (square(move.to_square), setup.destinations["pawn_return"]),
                (setup.destinations[replacement], square(move.to_square)),
            ]
        )
    plan = [step for a, b in transfers for step in pick_place(setup, a, b)]
    board.push(move)
    return plan, {"next_fen": board.fen(), "transfers": len(transfers), "uci": uci}


def stockfish_move(fen, executable, seconds=0.2):
    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(executable) as engine:
        return engine.play(board, chess.engine.Limit(time=seconds)).move.uci()


def detect_human_move(before_fen, observed_fen):
    before, observed = chess.Board(before_fen), chess.Board(observed_fen)
    matches = []
    for move in before.legal_moves:
        after = before.copy()
        after.push(move)
        if after.board_fen() == observed.board_fen():
            matches.append(move.uci())
    if len(matches) != 1:
        raise ValueError("Observed board does not identify one unambiguous legal human move")
    return matches[0]


def ttt_winner(grid):
    for a, b, c in ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)):
        if grid[a] != "." and grid[a] == grid[b] == grid[c]:
            return grid[a]
    return "draw" if "." not in grid else None


def ttt_move(grid, player="X"):
    if player not in "XO" or len(grid) != 9 or any(c not in ".XO" for c in grid):
        raise ValueError("Invalid tic-tac-toe state")
    if grid.count("X") not in (grid.count("O"), grid.count("O") + 1) or (player == "X") != (
        grid.count("X") == grid.count("O")
    ):
        raise ValueError("Wrong player turn")
    if ttt_winner(grid):
        raise ValueError("Game already finished")

    @lru_cache(maxsize=None)
    def score(g, turn):
        winner = ttt_winner(g)
        if winner:
            return 0 if winner == "draw" else (1 if winner == player else -1)
        values = [
            score(g[:i] + turn + g[i + 1 :], "O" if turn == "X" else "X") for i in range(9) if g[i] == "."
        ]
        return (max if turn == player else min)(values)

    order = [4, 0, 2, 6, 8, 1, 3, 5, 7]
    return max(
        (i for i in order if grid[i] == "."),
        key=lambda i: score(grid[:i] + player + grid[i + 1 :], "O" if player == "X" else "X"),
    )


def plan_skill(name, setup, params):
    if name not in SKILLS:
        raise ValueError("Unknown skill")
    if name == "drawing":
        strokes = params.get("strokes") or drawing_strokes(params.get("shape", "square"))
        return draw_plan(setup, strokes), {
            "strokes": len(strokes),
            "verification": "Compare after-image against intended polylines",
        }
    if name == "painting":
        if not setup.palette:
            raise ValueError("Register palette wells and brush loading depth")
        shape = params.get("shape", "line")
        strokes = params.get("strokes") or (
            drawing_strokes("circle") if shape == "flower" else drawing_strokes(shape)
        )
        plan = []
        for color, station in setup.palette.items():
            above = np.array(station) + [0, 0, setup.lift]
            dip = np.array(station) - [0, 0, setup.brush_dip_depth]
            plan.extend([position(above, setup), position(dip, setup), position(above, setup)])
            plan.extend(draw_plan(setup, strokes))
            if setup.clean_station:
                station = np.array(setup.clean_station)
                plan.extend(
                    [
                        position(station + [0, 0, setup.lift], setup),
                        position(station, setup),
                        position(station + [0, 0, setup.lift], setup),
                    ]
                )
        return plan, {
            "colors": list(setup.palette),
            "verification": "Inspect color coverage and stroke placement; no fluid or force simulation",
        }
    if name == "chess":
        return chess_plan(setup, params.get("move", "e2e4"))
    if name == "tic_tac_toe":
        player = params.get("player", "X")
        cell = ttt_move(setup.grid, player)
        col, row = cell % 3, cell // 3
        if player == "X":
            strokes = [[[0.15, 0.15], [0.85, 0.85]], [[0.15, 0.85], [0.85, 0.15]]]
        else:
            strokes = drawing_strokes("circle")
        strokes = [[[(col + x) / 3, (row + y) / 3] for x, y in s] for s in strokes]
        return draw_plan(setup, strokes), {
            "cell": cell,
            "next_grid": setup.grid[:cell] + player + setup.grid[cell + 1 :],
        }
    objects = approved_objects(setup)
    plan = []
    for i, obj in enumerate(objects):
        if name == "sorting":
            if obj.color not in setup.destinations:
                raise ValueError(f"No approved destination for {obj.color}; request clarification")
            dest = setup.destinations[obj.color]
        elif name == "stacking":
            if "stack" not in setup.destinations:
                raise ValueError("Register stacking target")
            dest = list(setup.destinations["stack"])
            dest[2] += sum(o.size_m for o in objects[:i]) + obj.size_m / 2
        else:
            if obj.id not in setup.destinations:
                raise ValueError("Register a separate free tray slot for each object")
            dest = setup.destinations[obj.id]
        plan.extend(pick_place(setup, obj.position, dest))
    return plan, {
        "objects": [o.id for o in objects],
        "verification": "Re-localize objects after each transfer; encoder completion cannot prove a grasp",
    }
