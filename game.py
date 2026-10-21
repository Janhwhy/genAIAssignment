"""Game rules for AI Detective. Pure Python, no AI calls, so it can be unit tested."""

DIFFICULTY_TURNS = {"Easy": 15, "Normal": 12, "Hard": 8}
MAX_QUESTION_LENGTH = 300


def validate_case(case):
    """Check that an AI-generated case is complete and solvable. Returns a list of problems."""
    problems = []
    if not isinstance(case, dict):
        return ["case is not a JSON object"]
    for key in ("title", "setting", "intro", "victim", "suspects", "locations", "clues", "solution"):
        if not case.get(key):
            problems.append(f"missing '{key}'")
    if problems:
        return problems

    suspects = case["suspects"]
    if not isinstance(suspects, list) or not 3 <= len(suspects) <= 5:
        return ["need 3 to 5 suspects"]
    for s in suspects:
        if not isinstance(s, dict) or not all(s.get(k) for k in ("name", "role", "personality", "alibi")):
            problems.append("a suspect is missing name/role/personality/alibi")
    names = [s.get("name") for s in suspects if isinstance(s, dict)]
    if len(set(names)) != len(names):
        problems.append("suspect names are not unique")
    if sum(1 for s in suspects if isinstance(s, dict) and s.get("is_culprit") is True) != 1:
        problems.append("there must be exactly one culprit")

    locations = case["locations"]
    if not isinstance(locations, list) or len(locations) < 3:
        return problems + ["need at least 3 locations"]
    location_names = {loc.get("name") for loc in locations if isinstance(loc, dict)}

    clues = case["clues"]
    if not isinstance(clues, list) or len(clues) < 4:
        return problems + ["need at least 4 clues"]
    for c in clues:
        if not isinstance(c, dict) or not c.get("text"):
            problems.append("a clue has no text")
        elif c.get("location") not in location_names:
            problems.append(f"clue placed in unknown location '{c.get('location')}'")
    return problems


def culprit(case):
    return next(s for s in case["suspects"] if s.get("is_culprit") is True)


def new_game(case, difficulty="Normal", offline=False):
    return {
        "case": case,
        "offline": offline,
        "max_turns": DIFFICULTY_TURNS[difficulty],
        "turns_left": DIFFICULTY_TURNS[difficulty],
        "found_clues": [],
        "searched": [],
        "transcripts": {s["name"]: [] for s in case["suspects"]},
        "hints": [],
        "status": "playing",  # playing | won | lost
        "accused": None,
        "ending": None,
    }


def can_act(state):
    return state["status"] == "playing" and state["turns_left"] > 0


def _spend_turn(state):
    if not can_act(state):
        raise ValueError("You have no investigation turns left. Make your accusation.")
    state["turns_left"] -= 1


def clean_question(text):
    """Validate a player's question to a suspect. Raises ValueError with a friendly message."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type a question first.")
    if len(text) > MAX_QUESTION_LENGTH:
        raise ValueError(f"Keep questions under {MAX_QUESTION_LENGTH} characters.")
    return text


def record_answer(state, suspect_name, question, answer):
    """Called only after the AI answered, so a failed AI call never costs a turn."""
    if suspect_name not in state["transcripts"]:
        raise ValueError(f"Unknown suspect '{suspect_name}'.")
    _spend_turn(state)
    state["transcripts"][suspect_name].append({"question": question, "answer": answer})


def search(state, location_name):
    """Search a location: costs a turn and reveals every clue hidden there."""
    if location_name not in {loc["name"] for loc in state["case"]["locations"]}:
        raise ValueError(f"Unknown location '{location_name}'.")
    if location_name in state["searched"]:
        raise ValueError(f"You already searched {location_name}.")
    _spend_turn(state)
    state["searched"].append(location_name)
    found = [c for c in state["case"]["clues"] if c["location"] == location_name]
    state["found_clues"].extend(found)
    return found


def record_hint(state, hint):
    _spend_turn(state)
    state["hints"].append(hint)


def accuse(state, suspect_name):
    """Final accusation. Ends the game and returns True if correct."""
    if state["status"] != "playing":
        raise ValueError("This case is already closed.")
    if suspect_name not in state["transcripts"]:
        raise ValueError(f"Unknown suspect '{suspect_name}'.")
    correct = suspect_name == culprit(state["case"])["name"]
    state["accused"] = suspect_name
    state["status"] = "won" if correct else "lost"
    return correct


def score(state):
    """100 for solving the case plus 10 per unused turn; 0 for a wrong accusation."""
    if state["status"] != "won":
        return 0
    return 100 + 10 * state["turns_left"]
