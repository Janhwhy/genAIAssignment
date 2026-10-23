"""Tests that run without an API key: the AI is mocked. Run with:  python -m unittest -v"""

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import ai
import game

BACKUP_CASES = json.loads(Path(__file__).with_name("backup_cases.json").read_text())
CASE = BACKUP_CASES[0]  # the hostel murder


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

    def test_rank(self):
        state = game.new_game(CASE, "Normal")
        game.accuse(state, "Dr. Neha Joshi")
        self.assertEqual(game.rank(state), "Master Detective")
        state["turns_left"] = 1
        self.assertEqual(game.rank(state), "Constable")
        lost = game.new_game(CASE)
        game.accuse(lost, "Kabir Shah")
        self.assertEqual(game.rank(lost), "Back to the academy")

    def test_validation_catches_bad_ai_output(self):
        bad = copy.deepcopy(CASE)
        bad["suspects"][0]["is_culprit"] = True  # now two culprits
        bad["clues"][0]["location"] = "Moon"
        problems = game.validate_case(bad)
        self.assertIn("there must be exactly one culprit", problems)
        self.assertTrue(any("Moon" in p for p in problems))
        self.assertEqual(game.validate_case("not a dict"), ["case is not a JSON object"])

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
        self.assertEqual(game.score(won), 100 + 10 * 12)
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

    def test_generate_case_gives_up_after_two_bad_cases(self):
        with mock.patch.object(ai, "_chat", return_value=json.dumps({"title": "x"})):
            with self.assertRaisesRegex(ai.AIError, "incomplete case"):
                ai.generate_case("")

    def test_interrogation_prompt_knows_guilt_and_history(self):
        state = game.new_game(CASE)
        game.record_answer(state, "Dr. Neha Joshi", "Where were you?", "Grading papers.")
        with mock.patch.object(ai, "_chat", return_value="I told you already.") as chat:
            ai.interrogate(state, "Dr. Neha Joshi", "Then why are the papers unmarked?")
        messages = chat.call_args.args[0]
        self.assertIn("You ARE the culprit behind the murder", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "Where were you?")
        self.assertEqual(messages[-1]["content"], "Then why are the papers unmarked?")


class AppFlowTest(unittest.TestCase):
    """Drives the real Streamlit UI from start to a meaningful outcome, with the AI mocked."""

    def test_full_game(self):
        with mock.patch.object(ai, "_chat", side_effect=[
            json.dumps(CASE),                     # case generation
            "I was in the staff room, grading.",  # interrogation answer
            "Check the lab sign-out sheet.",      # partner hint
            "Joshi is led away.\nDetective's report: Sharp.",  # ending
        ]):
            at = AppTest.from_file("app.py", default_timeout=10).run()
            next(b for b in at.button if b.label == "Open the case file").click().run()
            self.assertEqual(at.title[0].value, CASE["title"])

            at.radio[0].set_value("Dr. Neha Joshi").run()
            next(b for b in at.button if b.label.startswith("Search Chemistry Lab")).click().run()

            at.text_input[0].input("Explain this.")
            at.selectbox[0].set_value(0)  # show Exhibit A
            next(b for b in at.button if b.label == "Ask").click().run()
            self.assertTrue(any("grading" in m.value for m in at.markdown))
            asked = at.session_state.game["transcripts"]["Dr. Neha Joshi"][0]["question"]
            self.assertTrue(asked.startswith("[Shows Exhibit A"))
            next(b for b in at.button if b.label == "Ask partner for a hint").click().run()
            self.assertEqual(at.session_state.game["turns_left"], 9)

            at.selectbox[-1].set_value("Dr. Neha Joshi")
            at.text_area[0].input("Her papers were ungraded and she signed out the lab.")
            at.checkbox[0].check()
            next(b for b in at.button if b.label == "Make the accusation").click().run()
            self.assertEqual(at.session_state.game["status"], "won")
            self.assertTrue(any("SOLVED" in m.value for m in at.markdown))
            self.assertTrue(any("Rank: Master Detective" in m.value for m in at.markdown))

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
