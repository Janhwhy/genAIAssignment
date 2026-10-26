"""Tests that run without an API key: the AI is mocked. Run with:  python -m unittest -v"""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import ai
import game

BACKUP_CASES = json.loads(Path(__file__).with_name("backup_cases.json").read_text())
CASE = BACKUP_CASES[0]  # the hostel murder
JOSHI_MOTIVE = "Kale planned to expose that she faked lab results"


def streamed(*pieces):
    """Stands in for ai._stream: returns the reply in pieces, like the real streaming call."""
    return mock.Mock(side_effect=lambda *a, **k: iter(pieces))


class RulesTest(unittest.TestCase):
    def test_backup_cases_are_valid(self):
        self.assertEqual(len(BACKUP_CASES), 3)
        for case in BACKUP_CASES:
            self.assertEqual(game.validate_case(case), [], case["title"])
            self.assertIn(case["crime"], game.CRIMES)

    def test_showing_evidence(self):
        state = game.new_game(CASE)
        self.assertEqual(game.with_evidence(state, " Hi ", None), "Hi")
        with self.assertRaises(ValueError):
            game.with_evidence(state, "Explain this", 0)  # nothing found yet
        game.search(state, "Chemistry Lab")
        q = game.with_evidence(state, "", 0)
        self.assertTrue(q.startswith("[Shows Exhibit A: The lab door"))
        self.assertTrue(q.endswith("What can you tell me about this?"))
        self.assertLessEqual(len(game.with_evidence(state, "x" * 290, 0)), game.MAX_QUESTION_LENGTH)

    def test_rank_and_stars(self):
        state = game.new_game(CASE, "Normal")
        game.accuse(state, "Dr. Neha Joshi")  # right culprit, no motive or evidence picked
        self.assertEqual((game.stars(state), game.rank(state)), (1, "Constable"))
        lost = game.new_game(CASE)
        game.accuse(lost, "Kabir Shah", JOSHI_MOTIVE)
        self.assertEqual((game.stars(lost), game.rank(lost)), (0, "Back to the academy"))
        self.assertFalse(lost["deduction"]["motive"])  # the right motive doesn't count for the wrong person

    def test_full_deduction_scores_every_bonus(self):
        state = game.new_game(CASE, "Normal")
        game.search(state, "Chemistry Lab")  # Exhibit A points at Joshi
        game.accuse(state, "Dr. Neha Joshi", JOSHI_MOTIVE, 0)
        self.assertEqual((game.stars(state), game.rank(state)), (3, "Master Detective"))
        self.assertEqual(game.score(state), 100 + 40 + 40 + 10 * 11 + 20)
        state["hints"].append("x")
        self.assertEqual(game.score(state), 100 + 40 + 40 + 10 * 11)

    def test_red_herring_is_not_the_key_evidence(self):
        state = game.new_game(CASE)
        game.search(state, "Hostel Kitchen")  # A: chai pot (neutral), B: sandals (points at Riya)
        game.accuse(state, "Dr. Neha Joshi", None, 1)
        self.assertFalse(state["deduction"]["evidence"])

    def test_sealed_location_needs_a_warrant(self):
        state = game.new_game(CASE)
        self.assertEqual(state["sealed"], "Warden's Office")
        with self.assertRaisesRegex(ValueError, "sealed"):
            game.search(state, "Warden's Office")
        self.assertEqual(state["turns_left"], 12)  # refusing costs nothing
        game.search(state, "Hostel Kitchen")  # two clues: warrant granted
        self.assertEqual([e["kind"] for e in game.pop_news(state)], ["warrant"])
        self.assertEqual(game.pop_news(state), [])
        self.assertEqual(len(game.search(state, "Warden's Office")), 2)

    def test_witness_brings_a_free_clue(self):
        state = game.new_game(CASE, "Normal")
        for _ in range(state["witness_at"]):
            game.record_hint(state, "hint")
        self.assertEqual(len(state["found_clues"]), 1)
        self.assertEqual(state["found_clues"][0]["via"], "Witness")
        game.search(state, "Hostel Kitchen")
        game.search(state, "Warden's Office")  # the witness's clue isn't logged twice
        self.assertEqual(len({c["text"] for c in state["found_clues"]}), len(state["found_clues"]))

    def test_culprit_destroys_evidence_unless_you_get_there_first(self):
        state = game.new_game(CASE, "Normal")
        for _ in range(state["cleanup_at"]):
            game.record_hint(state, "hint")
        place, turns = game.cleanup_warning(state)
        self.assertEqual((place, turns), ("Chemistry Lab", 2))
        game.record_hint(state, "hint")
        game.record_hint(state, "hint")
        self.assertIsNone(game.cleanup_warning(state))
        self.assertEqual(state["events"][-1]["kind"], "destroyed")
        self.assertEqual(game.search(state, "Chemistry Lab"), [])

        saved = game.new_game(CASE, "Normal")
        for _ in range(saved["cleanup_at"]):
            game.record_hint(saved, "hint")
        self.assertEqual(len(game.search(saved, "Chemistry Lab")), 1)
        game.record_hint(saved, "hint")
        self.assertEqual(saved["destroyed"], [])

    def test_pressing_a_suspect_with_evidence_cracks_them(self):
        state = game.new_game(CASE)
        game.search(state, "Hostel Kitchen")   # A neutral, B points at Riya
        game.search(state, "Chemistry Lab")    # C points at Joshi
        game.search(state, "Staff Room")       # D points at Joshi
        self.assertFalse(game.record_answer(state, "Dr. Neha Joshi", "q", "a", 1))  # Riya's clue: no effect
        self.assertFalse(game.record_answer(state, "Dr. Neha Joshi", "q", "a", 2))
        self.assertEqual(state["nerve"]["Dr. Neha Joshi"], 1)
        self.assertFalse(game.record_answer(state, "Dr. Neha Joshi", "q", "a", 2))  # same clue twice
        self.assertEqual(state["nerve"]["Dr. Neha Joshi"], 1)
        self.assertTrue(game.record_answer(state, "Dr. Neha Joshi", "q", "a", 3))
        confession = state["found_clues"][-1]
        self.assertEqual(confession["via"], "Confession")
        self.assertIn("mixed the poison", confession["text"])
        self.assertEqual(confession["points_to"], "Dr. Neha Joshi")
        self.assertFalse(game.record_answer(state, "Dr. Neha Joshi", "q", "a", 3))  # already cracked

    def test_career(self):
        results = [{"won": w, "score": s} for w, s in [(True, 200), (True, 150), (False, 0), (True, 300), (True, 90)]]
        self.assertEqual(game.career(results),
                         {"played": 5, "solved": 4, "best": 300, "streak": 2, "best_streak": 2})
        self.assertEqual(game.career([])["best"], 0)

    def test_validation_catches_bad_ai_output(self):
        bad = copy.deepcopy(CASE)
        bad["suspects"][0]["is_culprit"] = True  # now two culprits
        bad["clues"][0]["location"] = "Moon"
        bad["clues"][1]["points_to"] = "Nobody"
        problems = game.validate_case(bad)
        self.assertIn("there must be exactly one culprit", problems)
        self.assertTrue(any("Moon" in p for p in problems))
        self.assertTrue(any("Nobody" in p for p in problems))
        weak = copy.deepcopy(CASE)
        for c in weak["clues"][1:]:
            c["points_to"] = None
        self.assertIn("at least 2 clues must point to the culprit", game.validate_case(weak))
        self.assertEqual(game.validate_case("not a dict"), ["case is not a JSON object"])
        plain = copy.deepcopy(CASE)
        plain["locations"] = [loc["name"] for loc in plain["locations"]]  # names only, no objects
        for clue in plain["clues"]:
            del clue["location"]
        self.assertIn("every location needs a name", game.validate_case(plain))

    def test_search_reveals_clues_once_and_costs_a_turn(self):
        state = game.new_game(CASE, "Hard")
        found = game.search(state, "Hostel Kitchen")
        self.assertEqual(len(found), 2)
        self.assertEqual(state["turns_left"], 7)
        with self.assertRaises(ValueError):
            game.search(state, "Hostel Kitchen")
        with self.assertRaises(ValueError):
            game.search(state, "Nowhere")

    def test_question_validation(self):
        for bad in ("", "   ", "x" * 301):
            with self.assertRaises(ValueError):
                game.clean_question(bad)
        self.assertEqual(game.clean_question("  Where were you?  "), "Where were you?")

    def test_turns_run_out(self):
        state = game.new_game(CASE, "Hard")
        for _ in range(8):
            game.record_hint(state, "hint")
        self.assertFalse(game.can_act(state))
        with self.assertRaises(ValueError):
            game.search(state, "Staff Room")

    def test_win_and_lose(self):
        won = game.new_game(CASE)
        self.assertTrue(game.accuse(won, "Dr. Neha Joshi"))
        self.assertEqual(game.score(won), 100 + 10 * 12 + 20)
        with self.assertRaises(ValueError):
            game.accuse(won, "Riya Desai")
        lost = game.new_game(CASE)
        self.assertFalse(game.accuse(lost, "Riya Desai"))
        self.assertEqual(game.score(lost), 0)


class AIModuleTest(unittest.TestCase):
    def test_missing_key_gives_friendly_error(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            with self.assertRaisesRegex(ai.AIError, "GROQ_API_KEY"):
                ai.generate_case("a train")

    def test_generate_case_retries_on_invalid_json(self):
        replies = ["not json at all", json.dumps(CASE)]
        with mock.patch.object(ai, "_chat", side_effect=replies) as chat:
            case = ai.generate_case("a hostel", "Theft")
            self.assertEqual(case["title"], CASE["title"])
            self.assertEqual(case["crime"], "Theft")
            self.assertIn("high-value theft", chat.call_args.args[0][0]["content"])
            self.assertEqual(chat.call_count, 2)

    def test_generate_case_retries_when_groq_rejects_the_json(self):
        replies = [ai.BadJSON("The AI's reply was not valid JSON."), json.dumps(CASE)]
        with mock.patch.object(ai, "_chat", side_effect=replies):
            self.assertEqual(ai.generate_case("a hostel")["title"], CASE["title"])

    def test_generate_case_gives_up_after_two_bad_cases(self):
        with mock.patch.object(ai, "_chat", return_value=json.dumps({"title": "x"})):
            with self.assertRaisesRegex(ai.AIError, "incomplete case"):
                ai.generate_case("")

    def test_interrogation_prompt_knows_guilt_and_history(self):
        state = game.new_game(CASE)
        game.record_answer(state, "Dr. Neha Joshi", "Where were you?", "Grading papers.")
        with mock.patch.object(ai, "_stream", streamed("I told ", "you already.")) as chat:
            reply = "".join(ai.interrogate(state, "Dr. Neha Joshi", "Then why are the papers unmarked?"))
        self.assertEqual(reply, "I told you already.")
        messages = chat.call_args.args[0]
        self.assertIn("You ARE the culprit behind the murder", messages[0]["content"])
        self.assertIn("You are composed.", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "Where were you?")
        self.assertEqual(messages[-1]["content"], "Then why are the papers unmarked?")


class AppFlowTest(unittest.TestCase):
    """Drives the real Streamlit UI from start to a meaningful outcome, with the AI mocked."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.history = Path(folder.name) / "history.json"
        env = mock.patch.dict(os.environ, {"AI_DETECTIVE_HISTORY": str(self.history)})
        env.start()
        self.addCleanup(env.stop)

    def selectbox(self, at, label):
        return next(s for s in at.selectbox if s.label == label)

    def test_full_game(self):
        with mock.patch.object(ai, "_chat", side_effect=[
            json.dumps(CASE),                     # case generation
            "Check the lab sign-out sheet.",      # partner hint
            "Joshi is led away.\nDetective's report: Sharp.",  # ending
        ]), mock.patch.object(ai, "_stream", streamed("I was in the staff room, ", "grading.")):
            at = AppTest.from_file("app.py", default_timeout=10).run()
            next(b for b in at.button if b.label == "Open the case file").click().run()
            self.assertEqual(at.title[0].value, CASE["title"])

            at.radio[0].set_value("Dr. Neha Joshi").run()
            next(b for b in at.button if b.label.startswith("Search Chemistry Lab")).click().run()

            at.text_input[0].input("Explain this.")
            self.selectbox(at, "Slam evidence on the table (optional)").set_value(0)  # show Exhibit A
            next(b for b in at.button if b.label == "Ask").click().run()
            self.assertTrue(any("grading" in m.value for m in at.markdown))
            asked = at.session_state.game["transcripts"]["Dr. Neha Joshi"][0]["question"]
            self.assertTrue(asked.startswith("[Shows Exhibit A"))
            self.assertEqual(at.session_state.game["nerve"]["Dr. Neha Joshi"], 1)
            self.assertIn("hit a nerve", at.info[0].value)

            next(b for b in at.button if b.label == "Your alibi?").click().run()  # one-click question
            self.assertIn("Where exactly were you", at.session_state.game["transcripts"]["Dr. Neha Joshi"][1]["question"])
            next(b for b in at.button if b.label == "Ask partner for a hint").click().run()
            self.assertEqual(at.session_state.game["turns_left"], 8)

            self.selectbox(at, "Who did it?").set_value("Dr. Neha Joshi")
            self.selectbox(at, "Why?").set_value(JOSHI_MOTIVE)
            self.selectbox(at, "Which exhibit proves it?").set_value(0)
            at.text_area[0].input("Her papers were ungraded and she signed out the lab.")
            at.checkbox[0].check()
            next(b for b in at.button if b.label == "Make the accusation").click().run()
            self.assertEqual(at.session_state.game["status"], "won")
            self.assertTrue(any("SOLVED" in m.value for m in at.markdown))
            self.assertTrue(any("Rank: Master Detective" in m.value for m in at.markdown))
            saved = json.loads(self.history.read_text())
            self.assertEqual((saved[0]["won"], saved[0]["stars"]), (True, 3))

            next(b for b in at.button if b.label == "Take a new case").click().run()
            self.assertTrue(any('class="career"' in m.value for m in at.markdown))  # career shows on the start screen

    def test_failed_answer_costs_no_turn(self):
        with mock.patch.object(ai, "_chat", return_value=json.dumps(CASE)), \
                mock.patch.object(ai, "_stream", side_effect=ai.AIError("Could not reach Groq.")):
            at = AppTest.from_file("app.py", default_timeout=10).run()
            next(b for b in at.button if b.label == "Open the case file").click().run()
            next(b for b in at.button if b.label == "Who did it?").click().run()
            self.assertIn("Could not reach Groq", at.warning[0].value)
            self.assertEqual(at.session_state.game["turns_left"], 12)

    def test_ai_failure_on_start_shows_error_and_backup_option(self):
        with mock.patch.object(ai, "_chat", side_effect=ai.AIError("Could not reach Groq.")):
            at = AppTest.from_file("app.py", default_timeout=10).run()
            next(b for b in at.button if b.label == "Open the case file").click().run()
            self.assertIn("Could not reach Groq", at.error[0].value)
            self.assertNotIn("game", at.session_state)
            next(b for b in at.button if b.label == "Play a backup case").click().run()
            self.assertTrue(at.session_state.game["offline"])


if __name__ == "__main__":
    unittest.main()
