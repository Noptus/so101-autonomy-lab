"""Run geometric scenarios without an arm, camera or provider. Writes local runtime data."""

from so101_lab.lab import Lab


def main():
    lab = Lab(".so101-lab/demo", realtime=False)
    try:
        for skill, params in [
            ("drawing", {"shape": "square"}),
            ("sorting", {}),
            ("chess", {"move": "e2e4"}),
            ("cleanup", {}),
        ]:
            draft = lab.draft_skill(skill, params)
            outcome = lab.execute_draft(draft["id"])
            print(skill, outcome["result"]["message"])
            if not outcome["result"]["ok"]:
                break
        print(lab.explorer.run(budget=2))
    finally:
        lab.close()


if __name__ == "__main__":
    main()
