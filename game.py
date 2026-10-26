"""Game rules for AI Detective. Pure Python, no AI calls, so it can be unit tested."""

DIFFICULTY_TURNS = {"Easy": 15, "Normal": 12, "Hard": 8}
MAX_QUESTION_LENGTH = 300
NERVE_TO_CRACK = 2       # pieces of evidence against a suspect that make them break down
WARRANT_CLUES = 2        # evidence needed before the sealed location can be searched
CLEANUP_GRACE = 2        # turns the player has to beat the culprit to the evidence
POINTS = {"solved": 100, "motive": 40, "evidence": 40, "per_turn": 10, "no_hints": 20}

# Each crime type: what the case's "victim" field means, and how the crime is described to the AI
CRIMES = {
    "Murder": {"victim_label": "The victim",
               "brief": "a murder. The victim is found dead (non-graphic: poison, a fall, a blow to the head)."},
    "Theft": {"victim_label": "Robbed",
              "brief": "a high-value theft. The 'victim' is the owner; describe what was stolen and when it was "
                       "found missing."},
    "Disappearance": {"victim_label": "Missing",
                      "brief": "a disappearance. The 'victim' is a person who vanished; they are alive but were "
                               "lured away or hidden by the culprit. Describe when they were last seen."},
    "Sabotage": {"victim_label": "Sabotaged",
                 "brief": "an act of sabotage. The 'victim' is the person or team whose big moment was ruined; "
                          "describe what was damaged and when it was discovered."},
}


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
        if not isinstance(s, dict) or not all(s.get(k) for k in ("name", "role", "personality", "alibi", "motive")):
            problems.append("a suspect is missing name/role/personality/alibi/motive")
    names = [s.get("name") for s in suspects if isinstance(s, dict)]
    if len(set(names)) != len(names):
        problems.append("suspect names are not unique")
    guilty = [s for s in suspects if isinstance(s, dict) and s.get("is_culprit") is True]
    if len(guilty) != 1:
        problems.append("there must be exactly one culprit")

    locations = case["locations"]
    if not isinstance(locations, list) or len(locations) < 3:
        return problems + ["need at least 3 locations"]
    if not all(isinstance(loc, dict) and loc.get("name") for loc in locations):
        return problems + ["every location needs a name"]
    location_names = {loc["name"] for loc in locations}

    clues = case["clues"]
    if not isinstance(clues, list) or len(clues) < 4:
        return problems + ["need at least 4 clues"]
    for c in clues:
        if not isinstance(c, dict) or not c.get("text"):
            problems.append("a clue has no text")
        elif c.get("location") not in location_names:
            problems.append(f"clue placed in unknown location '{c.get('location')}'")
        elif c.get("points_to") and c["points_to"] not in names:
            problems.append(f"clue points to unknown suspect '{c['points_to']}'")
    if len(guilty) == 1 and sum(1 for c in clues if isinstance(c, dict)
                                and c.get("points_to") == guilty[0]["name"]) < 2:
        problems.append("at least 2 clues must point to the culprit")
    return problems


def culprit(case):
    return next(s for s in case["suspects"] if s.get("is_culprit") is True)


def _culprit_clues_at(case, location_name, exclude=()):
    name = culprit(case)["name"]
    return [c for c in case["clues"] if c["location"] == location_name
            and c.get("points_to") == name and c["text"] not in exclude]


def sealed_location(case):
    """The location holding the most evidence against the culprit starts sealed until the player earns a warrant."""
    return max((loc["name"] for loc in case["locations"]), key=lambda n: len(_culprit_clues_at(case, n)))


def new_game(case, difficulty="Normal", offline=False):
    max_turns = DIFFICULTY_TURNS[difficulty]
    return {
        "case": case,
        "offline": offline,
        "difficulty": difficulty,
        "max_turns": max_turns,
        "turns_left": max_turns,
        "found_clues": [],
        "searched": [],
        "destroyed": [],  # clue texts the culprit got rid of
        "sealed": sealed_location(case),
        "warrant": False,
        "transcripts": {s["name"]: [] for s in case["suspects"]},
        "nerve": {s["name"]: 0 for s in case["suspects"]},
        "pressed": [],    # [suspect, clue text] pairs already used to raise nerve
        "cracked": [],
        "hints": [],
        # Scripted twists, triggered by how many turns have been used (scaled to the difficulty)
        "witness_at": max(2, max_turns // 3),
        "cleanup_at": max(3, max_turns // 2),
        "cleanup": None,  # {"location": ..., "deadline": turns_used} once the culprit makes a move
        "events": [],     # the case wire: every twist so far, newest last
        "news": [],       # twists the player hasn't been shown as a pop-up yet
        "status": "playing",  # playing | won | lost
        "accused": None,
        "deduction": None,
        "ending": None,
    }


def turns_used(state):
    return state["max_turns"] - state["turns_left"]


def can_act(state):
    return state["status"] == "playing" and state["turns_left"] > 0


def _found_texts(state):
    return {c["text"] for c in state["found_clues"]}


def is_sealed(state, location_name):
    return location_name == state["sealed"] and len(state["found_clues"]) < WARRANT_CLUES


def _announce(state, kind, text):
    event = {"kind": kind, "text": text, "turn": turns_used(state)}
    state["events"].append(event)
    state["news"].append(event)


def _tick(state):
    """Advance the scripted twists after every turn spent."""
    used = turns_used(state)
    case = state["case"]
    taken = _found_texts(state) | set(state["destroyed"])

    if used == state["witness_at"]:
        tip = next((c for c in case["clues"] if c["text"] not in taken
                    and c.get("points_to") in (None, "", culprit(case)["name"])), None)
        if tip:
            state["found_clues"].append({**tip, "via": "Witness"})
            _announce(state, "witness", f"A witness comes forward with something from the {tip['location']}.")

    if not state["warrant"] and len(state["found_clues"]) >= WARRANT_CLUES:
        state["warrant"] = True
        _announce(state, "warrant", f"Warrant granted. The {state['sealed']} is open for search.")

    if used == state["cleanup_at"] and state["cleanup"] is None:
        targets = [loc["name"] for loc in case["locations"] if loc["name"] not in state["searched"]
                   and not is_sealed(state, loc["name"]) and _culprit_clues_at(case, loc["name"], taken)]
        if targets:
            target = max(targets, key=lambda n: len(_culprit_clues_at(case, n, taken)))
            state["cleanup"] = {"location": target, "deadline": used + CLEANUP_GRACE}
            _announce(state, "threat", f"Someone was seen heading for the {target}. Search it within "
                                       f"{CLEANUP_GRACE} turns before the evidence disappears!")

    threat = state["cleanup"]
    if threat and used == threat["deadline"] and threat["location"] not in state["searched"]:
        left = _culprit_clues_at(case, threat["location"], taken)
        if left:
            state["destroyed"].append(left[0]["text"])
            _announce(state, "destroyed", f"Too late. Evidence in the {threat['location']} has been destroyed.")


def require_turn(state):
    if not can_act(state):
        raise ValueError("You have no investigation turns left. Make your accusation.")


def _spend_turn(state):
    require_turn(state)
    state["turns_left"] -= 1
    _tick(state)


def pop_news(state):
    news, state["news"] = state["news"], []
    return news


def cleanup_warning(state):
    """The live threat, if the culprit is still on their way: (location, turns left to stop them)."""
    threat = state["cleanup"]
    if not threat or threat["location"] in state["searched"] or turns_used(state) >= threat["deadline"]:
        return None
    return threat["location"], threat["deadline"] - turns_used(state)


def clean_question(text):
    """Validate a player's question to a suspect. Raises ValueError with a friendly message."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Type a question first.")
    if len(text) > MAX_QUESTION_LENGTH:
        raise ValueError(f"Keep questions under {MAX_QUESTION_LENGTH} characters.")
    return text


def with_evidence(state, question, exhibit):
    """Attach a found clue the detective shows the suspect. exhibit is an index into found_clues, or None."""
    if exhibit is None:
        return clean_question(question)
    if not 0 <= exhibit < len(state["found_clues"]):
        raise ValueError("You can only show evidence you have found.")
    question = (question or "").strip() or "What can you tell me about this?"
    clue = state["found_clues"][exhibit]
    return clean_question(f"[Shows Exhibit {chr(65 + exhibit)}: {clue['text']}] {question}"[:MAX_QUESTION_LENGTH])


def record_answer(state, suspect_name, question, answer, exhibit=None):
    """Called only after the AI answered, so a failed AI call never costs a turn.

    Showing a suspect evidence that really points at them raises their nerve; at NERVE_TO_CRACK they crack and
    their secret is logged as a free exhibit. Returns True if the suspect cracked on this question.
    """
    if suspect_name not in state["transcripts"]:
        raise ValueError(f"Unknown suspect '{suspect_name}'.")
    require_turn(state)
    state["transcripts"][suspect_name].append({"question": question, "answer": answer})
    cracked = _press(state, suspect_name, exhibit)
    _spend_turn(state)  # after logging, so a confession counts toward this turn's warrant check
    return cracked


def _press(state, suspect_name, exhibit):
    if exhibit is None or suspect_name in state["cracked"]:
        return False
    clue = state["found_clues"][exhibit]
    pair = [suspect_name, clue["text"]]
    if clue.get("points_to") != suspect_name or pair in state["pressed"]:
        return False
    state["pressed"].append(pair)
    state["nerve"][suspect_name] += 1
    if state["nerve"][suspect_name] < NERVE_TO_CRACK:
        return False
    state["cracked"].append(suspect_name)
    s = next(x for x in state["case"]["suspects"] if x["name"] == suspect_name)
    state["found_clues"].append({
        "location": "Confession", "via": "Confession", "text": f"{suspect_name} admits: {s.get('secret', '')}",
        "points_to": suspect_name if s.get("is_culprit") else None,
    })
    return True


def search(state, location_name):
    """Search a location: costs a turn and reveals every clue still hidden there."""
    if location_name not in {loc["name"] for loc in state["case"]["locations"]}:
        raise ValueError(f"Unknown location '{location_name}'.")
    if location_name in state["searched"]:
        raise ValueError(f"You already searched {location_name}.")
    require_turn(state)
    if is_sealed(state, location_name):
        raise ValueError(f"{location_name} is sealed. Log {WARRANT_CLUES} pieces of evidence to get a warrant.")
    taken = _found_texts(state) | set(state["destroyed"])
    found = [c for c in state["case"]["clues"] if c["location"] == location_name and c["text"] not in taken]
    state["searched"].append(location_name)
    state["found_clues"].extend(found)
    _spend_turn(state)  # after logging, so a twist on this turn sees the search
    return found


def record_hint(state, hint):
    _spend_turn(state)
    state["hints"].append(hint)


def motive_options(case):
    return sorted(s["motive"] for s in case["suspects"])


def accuse(state, suspect_name, motive=None, exhibit=None):
    """Final accusation with the deduction board. Ends the game and returns True if the culprit is right."""
    if state["status"] != "playing":
        raise ValueError("This case is already closed.")
    if suspect_name not in state["transcripts"]:
        raise ValueError(f"Unknown suspect '{suspect_name}'.")
    real = culprit(state["case"])
    correct = suspect_name == real["name"]
    key = state["found_clues"][exhibit] if exhibit is not None and 0 <= exhibit < len(state["found_clues"]) else None
    state["accused"] = suspect_name
    state["status"] = "won" if correct else "lost"
    state["deduction"] = {
        "motive": correct and motive == real["motive"],
        "evidence": correct and key is not None and key.get("points_to") == real["name"],
    }
    return correct


def score_breakdown(state):
    """Lines of (reason, points). Empty for a wrong accusation."""
    if state["status"] != "won":
        return []
    lines = [("Case solved", POINTS["solved"])]
    if state["deduction"]["motive"]:
        lines.append(("Named the motive", POINTS["motive"]))
    if state["deduction"]["evidence"]:
        lines.append(("Picked the evidence that proves it", POINTS["evidence"]))
    if state["turns_left"]:
        lines.append((f"{state['turns_left']} turns to spare", POINTS["per_turn"] * state["turns_left"]))
    if not state["hints"]:
        lines.append(("Lone wolf: no hints", POINTS["no_hints"]))
    return lines


def score(state):
    return sum(points for _, points in score_breakdown(state))


def stars(state):
    """One star for the culprit, one each for the motive and the evidence."""
    if state["status"] != "won":
        return 0
    return 1 + state["deduction"]["motive"] + state["deduction"]["evidence"]


def rank(state):
    """A title for the ending screen, from the deduction and the share of turns left."""
    if state["status"] != "won":
        return "Back to the academy"
    if stars(state) == 3 and state["turns_left"] / state["max_turns"] >= 0.25:
        return "Master Detective"
    if stars(state) >= 2:
        return "Inspector"
    return "Constable"


def career(history):
    """Summary stats from past results (newest last): played, solved, best score, current and best streak."""
    streak = best_streak = 0
    for r in history:
        streak = streak + 1 if r["won"] else 0
        best_streak = max(best_streak, streak)
    return {
        "played": len(history),
        "solved": sum(1 for r in history if r["won"]),
        "best": max((r["score"] for r in history), default=0),
        "streak": streak,
        "best_streak": best_streak,
    }
