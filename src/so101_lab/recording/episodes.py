"""Portable event export, intentionally not mislabeled as a LeRobot dataset."""

import json


def export_jsonl(memory):
    cursor = 0
    while True:
        with memory.lock:
            rows = memory.db.execute(
                "SELECT id,ts,kind,data FROM events WHERE id>? ORDER BY id LIMIT 500", (cursor,)
            ).fetchall()
        if not rows:
            return
        for row in rows:
            cursor = row[0]
            yield (
                json.dumps({"id": row[0], "timestamp": row[1], "kind": row[2], "data": json.loads(row[3])})
                + "\n"
            )


def replay_simulation(events, lab):
    if lab.robot.hardware:
        raise ValueError("Replay is simulation-only; never resume recorded hardware commands")
    results = []
    for event in events:
        if event.get("kind") == "motion_plan":
            results.append(
                lab.controller.execute(
                    event["data"]["requests"], contact=event["data"].get("contact", False)
                ).model_dump()
            )
            if not results[-1]["ok"]:
                break
    return results
