import asyncio
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi import HTTPException

from app import assessments, database, item_analysis, main
from app.core.checks import suppress_check_exception_logging
from app.schemas import BuildTestRequest, RenameTestRequest


def pool_question(number, topic, question_type, likelihood=0.5, concept=None):
    concept = concept or f"{topic} concept {number}"
    item = {
        "id": f"{question_type[:2]}-{topic}-{number}",
        "question_text": f"{question_type} question about {concept}?",
        "question_type": question_type,
        "topic": topic,
        "choices": [],
        "correct_answer": "True",
        "likelihood_score": likelihood,
        "priority_score": 0.5,
        "confidence_score": 0.5,
        "cited_passage": f"{concept} — what it means.",
        "support_excerpt": "what it means",
        "source_material_name": "Lesson.txt",
    }
    if question_type == "Multiple Choice":
        item.update(choices=[f"{concept}", "Other one", "Other two", "Other three"], correct_answer=concept)
    if question_type == "Identification":
        item.update(correct_answer=concept)
    return item


class FakeUpload:
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content

    async def read(self, size=-1):
        return self._content


class AssessmentTestCase(unittest.TestCase):
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
        self.uploads.mkdir(parents=True, exist_ok=True)
        path = self.uploads / "lesson-1.txt"
        path.write_text("Usability is how easily people use a system.", encoding="utf-8")
        with database.connect() as db:
            db.execute(
                "INSERT INTO uploads(id, name, stored_path, bytes, text_chars) VALUES(?, ?, ?, ?, ?)",
                ("lesson-1", "Lesson.txt", str(path.resolve()), 10, 10),
            )

    def build(self, pool, passages, **request):
        def fake_generate(**kwargs):
            return {"questions": [dict(item) for item in pool if item["question_type"] == kwargs["question_type"]]}

        ranking = {"lesson_analysis": {"passages": [{"topic": topic} for topic, count in passages.items() for _ in range(count)]}}
        fields = {
            "title": "Midterm",
            "training_dataset_id": "builtin",
            "lesson_upload_ids": ["lesson-1"],
            "total_items": 10,
            "question_types": ["Multiple Choice"],
            **request,
        }
        with patch.object(main, "generate_questions", side_effect=fake_generate), patch.object(
            main, "rank_lesson_likelihood", return_value=ranking
        ):
            return main.build_test(BuildTestRequest(**fields))


class AllocationTests(unittest.TestCase):
    def test_items_follow_lesson_weight_and_add_up_exactly(self):
        allocation = assessments.allocate_items({"A": 10, "B": 5, "C": 1}, {"A": 20, "B": 20, "C": 20}, 10)
        self.assertEqual(allocation, {"A": 6, "B": 3, "C": 1})
        self.assertEqual(sum(allocation.values()), 10)

    def test_a_topic_never_gets_more_items_than_it_has_questions(self):
        allocation = assessments.allocate_items({"A": 10, "B": 5, "C": 1}, {"A": 2, "B": 20, "C": 20}, 10)
        self.assertEqual(allocation["A"], 2)
        self.assertEqual(sum(allocation.values()), 10)

    def test_unweighted_topics_only_fill_what_is_left(self):
        self.assertEqual(assessments.allocate_items({"A": 10, "B": 0}, {"A": 3, "B": 5}, 6), {"A": 3, "B": 3})
        self.assertEqual(assessments.allocate_items({"A": 10, "B": 0}, {"A": 9, "B": 5}, 6), {"A": 6, "B": 0})

    def test_total_is_limited_to_the_questions_that_exist(self):
        self.assertEqual(assessments.allocate_items({}, {"A": 2, "B": 3}, 20), {"A": 2, "B": 3})

    def test_number_ranges(self):
        self.assertEqual(assessments._number_ranges([1, 2, 3, 7, 9, 10]), "1-3, 7, 9-10")
        self.assertEqual(assessments._number_ranges([]), "")


class SelectionTests(unittest.TestCase):
    def test_types_alternate_and_one_sentence_is_tested_only_once(self):
        pool = [
            pool_question(1, "A", "Multiple Choice", concept="Shared idea"),
            pool_question(1, "A", "True or False", concept="Shared idea"),
            pool_question(2, "A", "True or False"),
            pool_question(3, "A", "Multiple Choice"),
        ]
        chosen = assessments.select_items(pool, {"A": 3}, ["Multiple Choice", "True or False"])
        self.assertEqual(len(chosen), 3)
        concepts = [assessments.concept_key(item) for item in chosen]
        self.assertEqual(len(concepts), len(set(concepts)))
        self.assertEqual(
            {item["question_type"] for item in chosen}, {"Multiple Choice", "True or False"}
        )

    def test_higher_likelihood_questions_are_picked_first(self):
        pool = [pool_question(1, "A", "Multiple Choice", 0.1), pool_question(2, "A", "Multiple Choice", 0.9)]
        chosen = assessments.select_items(pool, {"A": 1}, ["Multiple Choice"])
        self.assertEqual(chosen[0]["id"], pool[1]["id"])

    def test_explanation_prefers_the_full_source_sentence(self):
        self.assertEqual(assessments.explanation_for({"cited_passage": "AR — overlay.", "support_excerpt": "overlay"}), "AR — overlay.")
        self.assertEqual(
            assessments.explanation_for({"source_reference": "Source Topic: X\nSource Text/Reference: AR — overlay.", "support_excerpt": "overlay"}),
            "AR — overlay.",
        )
        self.assertEqual(assessments.explanation_for({"support_excerpt": "overlay"}), "overlay")


class BuildTestTests(AssessmentTestCase):
    def setUp(self):
        super().setUp()
        self.pool = (
            [pool_question(i, "Usability", "Multiple Choice", 0.9) for i in range(8)]
            + [pool_question(i, "Usability", "True or False", 0.9) for i in range(8, 12)]
            + [pool_question(i, "Affordance", "Multiple Choice", 0.4) for i in range(6)]
            + [pool_question(i, "Affordance", "True or False", 0.4) for i in range(6, 9)]
        )

    def test_build_makes_a_tos_two_sets_and_answer_keys(self):
        test = self.build(
            self.pool, {"Usability": 6, "Affordance": 4},
            question_types=["True or False", "Multiple Choice"],
        )
        rows = {row["topic"]: row for row in test["specification"]["rows"]}
        self.assertEqual(rows["Usability"]["items"], 6)
        self.assertEqual(rows["Affordance"]["items"], 4)
        self.assertEqual(rows["Usability"]["weight_percent"], 60.0)
        self.assertEqual(test["total_items"], 10)
        self.assertEqual(test["question_types"], ["Multiple Choice", "True or False"])
        types = [item["question_type"] for item in test["items"]]
        self.assertEqual(types, sorted(types, key=assessments.QUESTION_TYPE_ORDER.index))
        self.assertEqual(sorted(test["sets"]), ["A", "B"])
        set_b_items = [entry["item"] for entry in test["sets"]["B"]]
        self.assertEqual(sorted(set_b_items), list(range(10)))
        for label in ("A", "B"):
            for number, key in enumerate(test["answer_keys"][label]):
                entry = test["sets"][label][number]
                item = test["items"][entry["item"]]
                if item["question_type"] == "Multiple Choice":
                    self.assertEqual(entry["choices"][assessments.LETTERS.index(key["answer"])], item["correct_answer"])
                    self.assertEqual(sorted(entry["choices"]), sorted(item["choices"]))
                else:
                    self.assertEqual(key["answer"], item["correct_answer"].upper())
        self.assertEqual(main.read_test(test["id"])["sets"], test["sets"])
        self.assertEqual(main.list_tests()["tests"][0]["total_items"], 10)

    def test_set_b_is_the_same_every_time(self):
        items = [assessments._public_item(item, index) for index, item in enumerate(self.pool[:6])]
        first = assessments.arrange_sets(items, "fixed-id", True)
        self.assertEqual(first, assessments.arrange_sets(items, "fixed-id", True))
        self.assertNotIn("B", assessments.arrange_sets(items, "fixed-id", False))

    def test_teacher_can_set_items_per_topic(self):
        test = self.build(self.pool, {"Usability": 6, "Affordance": 4}, items_per_topic={"Usability": 2, "Affordance": 5})
        rows = {row["topic"]: row["items"] for row in test["specification"]["rows"]}
        self.assertEqual(rows, {"Usability": 2, "Affordance": 5})
        self.assertEqual(test["total_items"], 7)

    def test_unknown_topic_in_custom_counts_is_rejected(self):
        with suppress_check_exception_logging(), self.assertRaises(HTTPException) as error:
            self.build(self.pool, {"Usability": 6}, items_per_topic={"Networks": 3})
        self.assertEqual(error.exception.status_code, 422)

    def test_shortfall_is_reported(self):
        test = self.build(self.pool[:3], {"Usability": 1}, total_items=10)
        self.assertEqual(test["total_items"], 3)
        self.assertTrue(any("Only 3" in warning for warning in test["warnings"]))

    def test_lessons_without_questions_are_rejected(self):
        with suppress_check_exception_logging(), self.assertRaises(HTTPException) as error:
            self.build([], {"Usability": 1})
        self.assertEqual(error.exception.status_code, 422)

    def test_missing_lesson_is_not_found(self):
        with suppress_check_exception_logging(), self.assertRaises(HTTPException) as error:
            self.build(self.pool, {}, lesson_upload_ids=["missing"])
        self.assertEqual(error.exception.status_code, 404)

    def test_exports_are_word_files_with_the_right_content(self):
        test = self.build(self.pool, {"Usability": 6, "Affordance": 4}, question_types=["Multiple Choice", "True or False"])
        paper = Document(io.BytesIO(main.export_test(test["id"], document="test", set_label="B").body))
        text = "\n".join(paragraph.text for paragraph in paper.paragraphs)
        self.assertIn("Set B", text)
        self.assertIn("Test I. Multiple Choice", text)
        self.assertIn("Test II. True or False", text)
        key = Document(io.BytesIO(main.export_test(test["id"], document="key").body))
        self.assertEqual(len(key.tables[0].rows), test["total_items"] + 1)
        tos = Document(io.BytesIO(main.export_test(test["id"], document="tos").body))
        self.assertEqual(tos.tables[0].rows[-1].cells[0].text, "Total")
        response = main.export_test(test["id"], document="test", set_label="A")
        self.assertIn("Midterm-Set-A.docx", response.headers["Content-Disposition"])

    def test_rename_and_delete(self):
        test = self.build(self.pool, {"Usability": 6})
        self.assertEqual(main.rename_test(test["id"], RenameTestRequest(title=" Final "))["title"], "Final")
        self.assertEqual(main.read_test(test["id"])["title"], "Final")
        main.delete_test(test["id"])
        with self.assertRaises(HTTPException):
            main.read_test(test["id"])


class ItemAnalysisTests(AssessmentTestCase):
    def setUp(self):
        super().setUp()
        pool = [pool_question(i, "Usability", "Multiple Choice", 0.9) for i in range(3)] + [
            pool_question(i, "Affordance", "True or False", 0.4) for i in range(3, 5)
        ]
        self.test = self.build(
            pool, {"Usability": 3, "Affordance": 2}, total_items=5,
            question_types=["Multiple Choice", "True or False"],
        )

    def results_csv(self, rows):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["student", "set", 1, 2, 3, 4, 5])
        writer.writerows(rows)
        return output.getvalue().encode()

    def import_rows(self, rows):
        return asyncio.run(main.import_results(self.test["id"], FakeUpload("results.csv", self.results_csv(rows))))

    def perfect(self, label):
        return [key["answer"] for key in self.test["answer_keys"][label]]

    def test_template_lists_every_item_and_sample_rows_are_skipped(self):
        template = main.results_template(self.test["id"]).body
        template = template.decode("utf-8") if isinstance(template, bytes) else template
        rows = list(csv.reader(io.StringIO(template)))
        self.assertEqual(rows[0], ["student", "set", "1", "2", "3", "4", "5"])
        with suppress_check_exception_logging(), self.assertRaises(HTTPException):
            asyncio.run(main.import_results(self.test["id"], FakeUpload("results.csv", template.encode())))

    def test_answers_are_graded_with_each_sets_own_key(self):
        result = self.import_rows([
            ["Ana", "A", *self.perfect("A")],
            ["Ben", "Set B", *self.perfect("B")],
        ])
        self.assertEqual(result["students"], 2)
        self.assertEqual(result["sets"], {"A": 1, "B": 1})
        analysis = main.read_analysis(self.test["id"])
        self.assertEqual([student["score"] for student in analysis["students"]], [5, 5])

    def test_letters_text_and_true_false_shortcuts_are_accepted(self):
        answers = self.perfect("A")
        first = self.test["items"][self.test["sets"]["A"][0]["item"]]
        answers[0] = first["correct_answer"].lower()
        answers[3] = answers[3][0].lower()
        self.import_rows([["Ana", "A", *answers], ["Ben", "A", "", "", "", "", ""]])
        analysis = main.read_analysis(self.test["id"])
        self.assertEqual(analysis["students"][0]["score"], 5)
        self.assertEqual(analysis["students"][1]["score"], 0)
        self.assertEqual(analysis["items"][0]["unanswered"], 1)

    def test_difficulty_discrimination_and_decisions(self):
        key = self.perfect("A")
        wrong_mc = next(letter for letter in "ABCD" if letter != key[0])
        rows = []
        for index in range(10):
            answers = list(key)
            if index >= 5:
                answers[0] = wrong_mc
                answers[3] = "FALSE" if key[3] == "TRUE" else "TRUE"
            if index >= 8:
                answers[1] = "D" if key[1] != "D" else "A"
            rows.append([f"Student {index}", "A", *answers])
        self.import_rows(rows)
        analysis = main.read_analysis(self.test["id"])
        self.assertEqual(analysis["summary"]["students"], 10)
        self.assertEqual(analysis["summary"]["group_size"], 3)
        first = analysis["items"][0]
        self.assertEqual(first["difficulty_index"], 0.5)
        self.assertEqual(first["discrimination_index"], 1.0)
        self.assertEqual(first["decision"], "Retain")
        last = analysis["items"][4]
        self.assertEqual(last["difficulty_index"], 1.0)
        self.assertEqual(last["discrimination_index"], 0.0)
        self.assertEqual(last["decision"], "Discard")
        options = {option["choice"]: option for option in first["options"]}
        unused = [option for option in options.values() if not option["is_answer"] and option["chosen_by"] == 0]
        self.assertTrue(all(option["flag"] for option in unused))
        self.assertIsNotNone(analysis["summary"]["kr20"])
        self.assertTrue(analysis["warnings"])

    def test_labels_and_kr20(self):
        self.assertEqual(item_analysis.difficulty_label(0.85), "Very easy")
        self.assertEqual(item_analysis.difficulty_label(0.5), "Average")
        self.assertEqual(item_analysis.discrimination_label(0.45), "Very good")
        self.assertEqual(item_analysis.discrimination_label(-0.1), "Negative")
        self.assertEqual(item_analysis.decision(0.5, 0.25), "Revise")
        self.assertEqual(item_analysis.decision(0.9, 0.35), "Revise")
        self.assertEqual(item_analysis.decision(0.5, 0.35), "Retain")
        self.assertEqual(item_analysis.kr20([0.5, 0.5], [0, 2]), 2 * (1 - 0.5 / 1))
        self.assertIsNone(item_analysis.kr20([1.0, 1.0], [2, 2]))

    def test_bad_csv_files_are_explained(self):
        cases = [
            b"student,score\nAna,5\n",
            b"student,set,1,2,3,4,5,6\nAna,A,a,b,c,d,e,f\n",
            b"student,set,1,2,3,4,5\nAna,C,a,b,c,d,e\n",
        ]
        for content in cases:
            with self.subTest(content=content), suppress_check_exception_logging(), self.assertRaises(HTTPException) as error:
                asyncio.run(main.import_results(self.test["id"], FakeUpload("results.csv", content)))
            self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.import_results(self.test["id"], FakeUpload("results.xlsx", b"x")))
        self.assertEqual(error.exception.status_code, 415)

    def test_analysis_needs_two_students_and_import_replaces_old_results(self):
        self.import_rows([["Ana", "A", *self.perfect("A")]])
        with suppress_check_exception_logging(), self.assertRaises(HTTPException) as error:
            main.read_analysis(self.test["id"])
        self.assertEqual(error.exception.status_code, 422)
        self.import_rows([["Ana", "A", *self.perfect("A")], ["Ben", "A", "", "", "", "", ""]])
        self.assertEqual(main.read_analysis(self.test["id"])["summary"]["students"], 2)

    def test_deleting_a_test_deletes_its_results(self):
        self.import_rows([["Ana", "A", *self.perfect("A")], ["Ben", "A", "", "", "", "", ""]])
        main.delete_test(self.test["id"])
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assessment_results").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
