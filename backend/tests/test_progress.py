import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import database, main, progress
from app.core.checks import suppress_check_exception_logging
from app.routers import questions as questions_router
from app.schemas import SubmitAnswerRequest

NOW = datetime(2026, 11, 25, 8, 0, tzinfo=timezone.utc)


def question(question_id="q1", topic="Usability", question_type="Multiple Choice", **extra):
    item = {
        "id": question_id,
        "question_text": f"Which term matches {question_id}?",
        "question_type": question_type,
        "topic": topic,
        "difficulty": "Moderate",
        "choices": ["Usability", "Affordance", "Feedback", "Mapping"],
        "correct_answer": "Usability",
        "support_excerpt": "Usability is how easily people can use a system.",
        "source_material_id": "lesson-1",
        "source_material_name": "HCI 2.pdf",
        "likelihood_score": 0.8,
    }
    if question_type == "True or False":
        item.update(choices=[], correct_answer="True")
    if question_type == "Identification":
        item.update(choices=[], correct_answer="Usability")
    item.update(extra)
    return item


class ProgressTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = Path(temporary.name)
        self.uploads = storage / "uploads"
        for item in (
            patch.object(database, "STORAGE", storage),
            patch.object(database, "UPLOADS", self.uploads),
            patch.object(database, "DB_PATH", storage / "assistant.sqlite3"),
            patch.object(main, "UPLOADS", self.uploads),
        ):
            item.start()
            self.addCleanup(item.stop)
        database.initialize()
        main._question_batches.clear()
        self.addCleanup(main._question_batches.clear)

    def add_upload(self, upload_id="lesson-1", name="HCI 2.pdf"):
        self.uploads.mkdir(parents=True, exist_ok=True)
        path = self.uploads / f"{upload_id}.txt"
        path.write_text("Usability is how easily people can use a system.", encoding="utf-8")
        with database.connect() as db:
            db.execute(
                "INSERT INTO uploads(id, name, stored_path, bytes, text_chars) VALUES(?, ?, ?, ?, ?)",
                (upload_id, name, str(path.resolve()), 10, 10),
            )

    def add_batch(self, *items, generation_id="gen-1"):
        main._question_batches[generation_id] = {
            "result": {"questions": list(items)},
            "upload_ids": ["lesson-1"],
        }


class AnswerCheckingTests(ProgressTestCase):
    def test_answers_are_compared_without_case_spacing_or_end_punctuation(self):
        self.assertTrue(progress.is_correct_answer("Identification", "  usability. ", "Usability"))
        self.assertTrue(progress.is_correct_answer("Identification", "User   Interface", "user interface"))
        self.assertFalse(progress.is_correct_answer("Identification", "usable", "Usability"))

    def test_identification_accepts_the_term_without_its_note_or_the_abbreviation(self):
        for typed in ("User Acceptance Testing (UAT)", "user acceptance testing", "UAT"):
            with self.subTest(typed=typed):
                self.assertTrue(progress.is_correct_answer("Identification", typed, "User Acceptance Testing (UAT)"))
        self.assertTrue(progress.is_correct_answer("Identification", "Implementation", "Implementation (coding)"))
        self.assertFalse(progress.is_correct_answer("Identification", "Testing", "User Acceptance Testing (UAT)"))
        self.assertFalse(progress.is_correct_answer("Identification", "coding", "Implementation (coding)"))
        self.assertFalse(progress.is_correct_answer("Multiple Choice", "UAT", "User Acceptance Testing (UAT)"))

    def test_true_or_false_accepts_only_true_or_false(self):
        item = question(question_type="True or False")
        self.assertEqual(progress.validate_answer_format(item, "true"), "True")
        with self.assertRaises(HTTPException) as error:
            progress.validate_answer_format(item, "maybe")
        self.assertEqual(error.exception.status_code, 422)

    def test_multiple_choice_answer_must_be_one_of_the_choices(self):
        item = question()
        self.assertEqual(progress.validate_answer_format(item, "affordance"), "Affordance")
        with self.assertRaises(HTTPException) as error:
            progress.validate_answer_format(item, "Something else")
        self.assertEqual(error.exception.status_code, 422)

    def test_blank_answer_is_rejected(self):
        with self.assertRaises(HTTPException):
            progress.validate_answer_format(question(question_type="Identification"), "   ")


class MasteryAndPriorityTests(unittest.TestCase):
    def test_new_topic_starts_at_fifty_percent_and_is_not_measured(self):
        result = progress.mastery_from_results([])
        self.assertEqual(result["mastery"], 0.5)
        self.assertFalse(result["mastery_measured"])

    def test_mastery_is_measured_after_three_answers(self):
        self.assertFalse(progress.mastery_from_results([1, 1])["mastery_measured"])
        result = progress.mastery_from_results([1, 1, 1])
        self.assertTrue(result["mastery_measured"])
        self.assertGreater(result["mastery"], 0.7)

    def test_newer_answers_count_more_than_older_answers(self):
        recently_wrong = progress.mastery_from_results([0, 1, 1, 1])["mastery"]
        recently_right = progress.mastery_from_results([1, 1, 1, 0])["mastery"]
        self.assertLess(recently_wrong, recently_right)

    def test_only_the_last_ten_answers_count(self):
        old_mistakes = [1] * 10 + [0] * 20
        self.assertEqual(
            progress.mastery_from_results(old_mistakes),
            progress.mastery_from_results([1] * 10),
        )

    def test_priority_is_likelihood_times_what_is_left_to_learn(self):
        self.assertEqual(progress.study_priority(0.8, 0.25), 0.6)
        self.assertGreater(progress.study_priority(0.9, 0.2), progress.study_priority(0.9, 0.9))
        self.assertGreater(progress.study_priority(0.9, 0.5), progress.study_priority(0.2, 0.5))
        self.assertEqual(progress.study_priority(None, 0.5), 0.25)

    def test_leitner_boxes_move_up_on_correct_and_reset_on_wrong(self):
        self.assertEqual(progress.next_box(None, True), 2)
        self.assertEqual(progress.next_box(None, False), 1)
        self.assertEqual(progress.next_box(3, True), 4)
        self.assertEqual(progress.next_box(5, True), 5)
        self.assertEqual(progress.next_box(4, False), 1)


class SubmitAnswerTests(ProgressTestCase):
    def test_correct_answer_is_saved_and_scheduled_for_later(self):
        self.add_batch(question())
        with patch.object(progress, "_now", return_value=NOW):
            result = main.submit_answer(
                SubmitAnswerRequest(question_id="q1", answer="usability", generation_id="gen-1")
            )
        self.assertTrue(result["correct"])
        self.assertEqual(result["correct_answer"], "Usability")
        self.assertIn("easily people", result["explanation"])
        self.assertEqual(result["review_box"], 2)
        self.assertEqual(result["next_review_at"], progress._stamp(NOW + timedelta(days=1)))
        with database.connect() as db:
            attempt = db.execute("SELECT * FROM attempts").fetchone()
            item = db.execute("SELECT * FROM practice_items").fetchone()
        self.assertEqual(attempt["correct"], 1)
        self.assertEqual(attempt["chosen_answer"], "Usability")
        self.assertEqual(attempt["source"], "practice")
        self.assertEqual(json.loads(item["choices"])[0], "Usability")
        self.assertEqual(item["likelihood_score"], 0.8)

    def test_wrong_answer_goes_back_to_box_one_and_is_due_now(self):
        self.add_batch(question())
        with patch.object(progress, "_now", return_value=NOW):
            main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Usability", generation_id="gen-1"))
            result = main.submit_answer(
                SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1")
            )
            due = progress.due_reviews(now=NOW)
        self.assertFalse(result["correct"])
        self.assertEqual(result["review_box"], 1)
        self.assertEqual(due["due_now"], 1)
        self.assertEqual(due["questions"][0]["question_id"], "q1")
        self.assertNotIn("correct_answer", due["questions"][0])
        self.assertFalse(due["questions"][0]["last_correct"])

    def test_review_questions_can_be_answered_after_the_practice_set_is_gone(self):
        self.add_batch(question())
        main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1"))
        main._question_batches.clear()
        result = main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Usability"))
        self.assertTrue(result["correct"])
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 2)

    def test_saved_questions_can_be_answered(self):
        item = question("saved-1")
        with database.connect() as db:
            db.execute(
                "INSERT INTO generated_questions("
                "id, question_text, question_type, topic, difficulty, choices, correct_answer, "
                "priority_score, confidence_score, source_dataset_id, source_dataset_name, "
                "source_material_id, source_material_name, source_reference, support_excerpt"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, 0.5, 0.5, 'builtin', 'Built-in', ?, ?, 'ref', ?)",
                (
                    item["id"], item["question_text"], item["question_type"], item["topic"],
                    item["difficulty"], json.dumps(item["choices"]), item["correct_answer"],
                    item["source_material_id"], item["source_material_name"], item["support_excerpt"],
                ),
            )
        result = main.submit_answer(SubmitAnswerRequest(question_id="saved-1", answer="Usability"))
        self.assertTrue(result["correct"])
        self.assertIn("easily people", result["explanation"])

    def test_unknown_question_is_not_found(self):
        with self.assertRaises(HTTPException) as error:
            main.submit_answer(SubmitAnswerRequest(question_id="missing", answer="x"))
        self.assertEqual(error.exception.status_code, 404)

    def test_expired_practice_set_says_to_generate_again(self):
        with self.assertRaises(HTTPException) as error:
            main.submit_answer(
                SubmitAnswerRequest(question_id="missing", answer="x", generation_id="old-set")
            )
        self.assertEqual(error.exception.status_code, 410)

    def test_review_list_can_show_only_mistakes_or_one_topic(self):
        self.add_batch(question("q1"), question("q2", topic="Affordance"))
        later = NOW + timedelta(days=30)
        with patch.object(progress, "_now", return_value=NOW):
            main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1"))
            main.submit_answer(SubmitAnswerRequest(question_id="q2", answer="Usability", generation_id="gen-1"))
        self.assertEqual(progress.due_reviews(now=NOW)["due_now"], 1)
        self.assertEqual(progress.due_reviews(now=later)["due_now"], 2)
        mistakes = progress.due_reviews(now=later, mistakes_only=True)
        self.assertEqual([item["question_id"] for item in mistakes["questions"]], ["q1"])
        one_topic = progress.due_reviews(now=later, topic="Affordance")
        self.assertEqual([item["question_id"] for item in one_topic["questions"]], ["q2"])
        with suppress_check_exception_logging(), self.assertRaises(HTTPException):
            progress.due_reviews(limit=0)


class ProgressSummaryTests(ProgressTestCase):
    def test_recommends_likely_topics_with_low_mastery_first(self):
        self.add_upload()
        progress.record_topic_likelihood(
            ["lesson-1"],
            [
                {"topic": "Usability", "likelihood_score": 0.9, "likelihood": "High"},
                {"topic": "Affordance", "likelihood_score": 0.9, "likelihood": "High"},
                {"topic": "Mapping", "likelihood_score": 0.2, "likelihood": "Low"},
                {"topic": "Unclassified", "likelihood_score": 1.0, "likelihood": "High"},
            ],
        )
        self.add_batch(*(question(f"u{i}") for i in range(4)))
        for index in range(4):
            main.submit_answer(
                SubmitAnswerRequest(question_id=f"u{index}", answer="Usability", generation_id="gen-1")
            )
        summary = main.read_progress()
        names = [item["topic"] for item in summary["recommendations"]]
        self.assertEqual(names[0], "Affordance")
        self.assertNotIn("Unclassified", names)
        self.assertLess(names.index("Affordance"), names.index("Usability"))
        usability = next(item for item in summary["topics"] if item["topic"] == "Usability")
        self.assertEqual(usability["attempts"], 4)
        self.assertTrue(usability["mastery_measured"])
        self.assertEqual(usability["likelihood"], "High")
        self.assertIn("not practiced yet", summary["recommendations"][0]["reason"])
        self.assertEqual(summary["totals"]["attempts"], 4)
        self.assertEqual(summary["totals"]["accuracy"], 1.0)

    def test_topics_without_likelihood_use_a_neutral_score(self):
        self.add_batch(question(topic="Feedback", likelihood_score=None))
        main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1"))
        topic = main.read_progress()["topics"][0]
        self.assertIsNone(topic["likelihood_score"])
        self.assertEqual(topic["likelihood"], "Unknown")
        self.assertEqual(topic["priority"], progress.study_priority(None, topic["mastery"]))

    def test_likelihood_is_ignored_for_missing_lessons_and_updated_for_existing_ones(self):
        self.add_upload()
        self.assertEqual(
            progress.record_topic_likelihood(["gone"], [{"topic": "Usability", "likelihood_score": 0.9}]),
            0,
        )
        progress.record_topic_likelihood(["lesson-1"], [{"topic": "Usability", "likelihood_score": 0.9}])
        progress.record_topic_likelihood(["lesson-1"], [{"topic": "Usability", "likelihood_score": 0.3}])
        topic = main.read_progress()["topics"][0]
        self.assertEqual(topic["likelihood_score"], 0.3)
        self.assertEqual(topic["likelihood"], "Low")

    def test_deleting_a_lesson_removes_its_review_questions_but_keeps_answer_history(self):
        self.add_upload()
        progress.record_topic_likelihood(["lesson-1"], [{"topic": "Usability", "likelihood_score": 0.9}])
        self.add_batch(question())
        main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1"))
        main.delete_upload("lesson-1")
        with database.connect() as db:
            counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("topic_likelihood", "practice_items", "review_schedule", "attempts")
            }
        self.assertEqual(counts, {"topic_likelihood": 0, "practice_items": 0, "review_schedule": 0, "attempts": 1})

    def test_reset_clears_all_progress(self):
        self.add_batch(question())
        main.submit_answer(SubmitAnswerRequest(question_id="q1", answer="Mapping", generation_id="gen-1"))
        result = main.clear_progress()
        self.assertEqual(result, {"attempts_deleted": 1, "questions_deleted": 1})
        summary = main.read_progress()
        self.assertEqual(summary["topics"], [])
        self.assertEqual(summary["totals"]["due_now"], 0)

    def test_saving_likelihood_never_breaks_question_generation(self):
        with patch.object(
            questions_router, "record_topic_likelihood", side_effect=RuntimeError("disk full")
        ), self.assertLogs(questions_router.__name__, level="WARNING"):
            questions_router._remember_topic_likelihood(["lesson-1"], [{"topic": "A", "likelihood_score": 1}])


if __name__ == "__main__":
    unittest.main()
