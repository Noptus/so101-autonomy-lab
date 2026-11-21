import chess
import pytest
from so101_lab.skills.planners import (
    SkillSetup,
    drawing_strokes,
    plan_skill,
    chess_plan,
    ttt_move,
    ttt_winner,
    detect_human_move,
)


def test_drawing_and_painting_plans(lab):
    setup = lab.demo_setup()
    for name in ["line", "square", "triangle", "circle", "HELLO", "house"]:
        plan, meta = plan_skill("drawing", setup, {"shape": name})
        assert meta["strokes"] >= 1 and len(plan) > 3
        assert plan[0]["position"][2] > setup.origin[2]
    setup.palette = {}
    with pytest.raises(ValueError):
        plan_skill("painting", setup, {})
    with pytest.raises(ValueError):
        plan_skill("drawing", setup, {"strokes": [[[0, 0], [float("nan"), 1]]]})
    assert len(drawing_strokes("HELLO")) >= 5


def test_only_approved_objects_and_unknown_sorting_fail(lab):
    setup = lab.demo_setup()
    setup.objects[0].approved = False
    with pytest.raises(ValueError):
        plan_skill("cleanup", setup, {})
    setup = lab.demo_setup()
    setup.objects[0].color = "unknown"
    with pytest.raises(ValueError):
        plan_skill("sorting", setup, {})
    setup = lab.demo_setup()
    setup.destinations.pop("block_1")
    with pytest.raises(ValueError):
        plan_skill("cleanup", setup, {})


def test_stacking_uses_measured_heights(lab):
    setup = lab.demo_setup()
    plan, _ = plan_skill("stacking", setup, {})
    assert plan[6]["position"][2] == pytest.approx(setup.origin[2] + setup.objects[0].size_m / 2)
    assert plan[15]["position"][2] > plan[6]["position"][2]


def test_chess_rules_capture_castle_en_passant_promotion(lab):
    setup = lab.demo_setup()
    with pytest.raises(ValueError):
        chess_plan(setup, "e2e5")
    plan, result = chess_plan(setup, "e2e4")
    assert result["transfers"] == 1 and len(plan) == 9
    setup.fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert chess_plan(setup, "e1g1")[1]["transfers"] == 2
    setup.fen = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
    setup.destinations["capture"] = (0.28, 0.02, 0.09)
    assert chess_plan(setup, "e5d6")[1]["transfers"] == 2
    setup.fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    with pytest.raises(ValueError):
        chess_plan(setup, "a7a8q")
    setup.destinations.update(promotion_q=(0.28, 0.02, 0.09), pawn_return=(0.28, 0.03, 0.09))
    assert chess_plan(setup, "a7a8q")[1]["transfers"] == 3
    board = chess.Board()
    after = board.copy()
    after.push_uci("e2e4")
    assert detect_human_move(board.fen(), after.fen()) == "e2e4"


def test_tictactoe_legal_and_winning_moves():
    assert ttt_move(".........") == 4
    assert ttt_move("XX.OO....") == 2
    assert ttt_winner("XXXOO....") == "X"
    with pytest.raises(ValueError):
        ttt_move("XXXOO....")
    with pytest.raises(ValueError):
        ttt_move("X........", "X")
    with pytest.raises(ValueError):
        SkillSetup(origin=(0, 0, 0), axis_u=(2, 0, 0))
