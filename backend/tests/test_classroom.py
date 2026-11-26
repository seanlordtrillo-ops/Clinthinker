import json
import unittest

from fastapi import HTTPException
from starlette.testclient import TestClient

from app import classroom, main, quiz_server
from app.core.checks import suppress_check_exception_logging
from tests.test_assessments import AssessmentTestCase, pool_question


class FakeServer:
    def __init__(self):
        self.started = []
        self.stopped = 0

    def start(self, port):
        self.started.append(port)
        return port

    def stop(self):
        self.stopped += 1


class ClassroomTestCase(AssessmentTestCase):
    def setUp(self):
        super().setUp()
        classroom._reset_for_tests()
        self.addCleanup(classroom._reset_for_tests)
        pool = [pool_question(i, "Usability", "Multiple Choice", 0.9) for i in range(3)] + [
            pool_question(i, "Affordance", "True or False", 0.4) for i in range(3, 5)
        ]
        self.test = self.build(
            pool, {"Usability": 3, "Affordance": 2}, total_items=5,
            question_types=["Multiple Choice", "True or False"],
        )
        self.server = FakeServer()

    def start(self, set_mode="alternate", **options):
        # Most tests answer with each set's own letters, so they keep the set's order.
        options.setdefault("shuffle_questions", False)
        return classroom.start_session(self.test["id"], set_mode, 8800, server=self.server, **options)

    def key(self, label):
        return {key["number"]: key["answer"] for key in self.test["answer_keys"][label]}

    def perfect(self, label):
        return {
            str(number): ("True" if answer == "TRUE" else "False" if answer == "FALSE" else answer)
            for number, answer in self.key(label).items()
        }


class SessionTests(ClassroomTestCase):
    def test_start_shows_a_room_code_and_join_addresses(self):
        status = self.start()
        self.assertTrue(status["running"])
        self.assertRegex(status["code"], r"^\d{4}$")
        self.assertEqual(status["port"], 8800)
        self.assertEqual(self.server.started, [8800])
        self.assertTrue(all(url.endswith(":8800") for url in status["join_urls"]))
        with self.assertRaises(HTTPException) as error:
            self.start()
        self.assertEqual(error.exception.status_code, 409)

    def test_students_alternate_sets_and_duplicate_names_are_numbered(self):
        code = self.start()["code"]
        first = classroom.join(code, "Ana", "10.0.0.2")
        second = classroom.join(code, " ana ", "10.0.0.3")
        third = classroom.join(code, "<b>Ben</b>", "10.0.0.4")
        self.assertEqual([first["set"], second["set"], third["set"]], ["A", "B", "A"])
        self.assertEqual(second["name"], "ana (2)")
        self.assertEqual(third["name"], "bBen/b")
        self.assertNotEqual(first["token"], second["token"])

    def test_wrong_code_and_blank_name_are_refused(self):
        code = self.start()["code"]
        wrong = "0000" if code != "0000" else "1111"
        for args, status in (((wrong, "Ana"), 403), ((code, "   "), 422)):
            with self.subTest(args=args), self.assertRaises(HTTPException) as error:
                classroom.join(*args, "10.0.0.2")
            self.assertEqual(error.exception.status_code, status)

    def test_join_attempts_are_rate_limited(self):
        self.start()
        for _ in range(classroom.RATE_LIMITS["wrong_code"][0]):
            with self.assertRaises(HTTPException):
                classroom.join("9999x", "Guess", "10.0.0.9")
        with self.assertRaises(HTTPException) as error:
            classroom.join("9999x", "Guess", "10.0.0.9")
        self.assertEqual(error.exception.status_code, 429)
        code = classroom.session_status()["code"]
        for index in range(30):
            classroom.join(code, f"Student {index}", "10.0.0.50")

    def test_questions_never_include_answers(self):
        code = self.start()["code"]
        token = classroom.join(code, "Ana", "10.0.0.2")["token"]
        data = classroom.questions_for(token, "10.0.0.2")
        self.assertEqual(data["total"], 5)
        text = json.dumps(data)
        self.assertNotIn("correct_answer", text)
        self.assertNotIn("explanation", text)
        self.assertNotIn("answer_key", text)
        with self.assertRaises(HTTPException) as error:
            classroom.questions_for("not-a-token", "10.0.0.2")
        self.assertEqual(error.exception.status_code, 401)

    def test_submit_once_with_each_sets_own_key(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        ben = classroom.join(code, "Ben", "10.0.0.3")
        self.assertEqual(classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")["score"], 5)
        self.assertEqual(classroom.submit(ben["token"], self.perfect("B"), "10.0.0.3")["score"], 5)
        with self.assertRaises(HTTPException) as error:
            classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(classroom.questions_for(ana["token"], "10.0.0.2")["submitted"])

    def test_bad_answer_values_are_ignored_not_crashing(self):
        code = self.start()["code"]
        token = classroom.join(code, "Ana", "10.0.0.2")["token"]
        result = classroom.submit(token, {"99": "A", "x": "B", "1": 5, "2": "A" * 1000}, "10.0.0.2")
        self.assertEqual(result["total"], 5)

    def test_end_saves_results_for_item_analysis(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        ben = classroom.join(code, "Ben", "10.0.0.3")
        classroom.join(code, "Cara", "10.0.0.4")
        classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        classroom.submit(ben["token"], {}, "10.0.0.3")
        result = classroom.end_session(server=self.server)
        self.assertEqual(self.server.stopped, 1)
        self.assertEqual((result["joined"], result["submitted"]), (3, 2))
        self.assertEqual(result["not_submitted"], ["Cara"])
        self.assertTrue(result["saved"])
        analysis = main.read_analysis(self.test["id"])
        self.assertEqual([student["score"] for student in analysis["students"]], [5, 0])
        with self.assertRaises(HTTPException) as error:
            classroom.join(code, "Late", "10.0.0.5")
        self.assertEqual(error.exception.status_code, 410)
        self.assertEqual(classroom.student_status(ana["token"], "10.0.0.2"), {"state": "ended"})

    def test_ending_with_no_submissions_keeps_existing_results(self):
        self.start()
        result = classroom.end_session(server=self.server)
        self.assertFalse(result["saved"])
        self.assertIn("kept", result["message"])
        with self.assertRaises(HTTPException) as error:
            classroom.end_session(server=self.server)
        self.assertEqual(error.exception.status_code, 409)

    def test_set_choice_follows_the_test(self):
        status = self.start("B")
        self.assertEqual(status["set_mode"], "B")
        classroom.end_session(server=self.server)
        single = self.build([pool_question(1, "Usability", "Multiple Choice")] * 1 + [pool_question(2, "Usability", "Multiple Choice")],
                            {"Usability": 2}, total_items=5, include_set_b=False)
        with self.assertRaises(HTTPException):
            classroom.start_session(single["id"], "B", 8800, server=self.server)
        self.assertEqual(classroom.start_session(single["id"], "alternate", 8800, server=self.server)["set_mode"], "A")


class QuizServerHttpTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(quiz_server.build_app())

    def test_full_flow_over_http(self):
        code = self.start()["code"]
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Join the quiz", page.text)
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        joined = self.client.post("/api/join", json={"code": code, "name": "Ana"})
        self.assertEqual(joined.status_code, 200, joined.text)
        token = joined.json()["token"]
        questions = self.client.get("/api/questions", headers={"X-Quiz-Token": token})
        self.assertEqual(questions.status_code, 200)
        self.assertEqual(questions.headers["cache-control"], "no-store")
        submitted = self.client.post("/api/submit", json={"answers": self.perfect("A")}, headers={"X-Quiz-Token": token})
        self.assertEqual(submitted.json(), {"submitted": True, "score": 5, "total": 5})
        self.assertEqual(self.client.get("/api/status", headers={"X-Quiz-Token": token}).json()["state"], "submitted")
        self.assertEqual(self.client.post("/api/away", json={"away": True}, headers={"X-Quiz-Token": token}).json(), {"ok": True})
        self.assertEqual(self.client.get("/api/review", headers={"X-Quiz-Token": token}).status_code, 403)
        classroom.control_session(release_answers=True)
        review = self.client.get("/api/review", headers={"X-Quiz-Token": token})
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["score"], 5)

    def test_bad_requests_get_clear_errors(self):
        code = self.start()["code"]
        self.assertEqual(self.client.post("/api/join", content=b"not json").status_code, 400)
        self.assertEqual(self.client.post("/api/join", content=b"x" * 70000).status_code, 413)
        self.assertEqual(self.client.post("/api/join", json={"code": "abc", "name": "Ana"}).status_code, 403)
        self.assertEqual(self.client.get("/api/questions").status_code, 401)
        self.assertEqual(self.client.get("/api/uploads").status_code, 404)
        self.assertEqual(self.client.post("/api/questions/save", json={}).status_code, 404)
        classroom.end_session(server=self.server)
        self.assertEqual(self.client.post("/api/join", json={"code": code, "name": "Ana"}).status_code, 410)


class TeacherRouteTests(ClassroomTestCase):
    def test_teacher_routes_use_the_session(self):
        from app.schemas import EndClassroomRequest, StartClassroomRequest
        from unittest.mock import patch

        with patch.object(quiz_server, "SERVER", self.server):
            self.assertEqual(main.read_classroom(), {"running": False})
            started = main.start_classroom(StartClassroomRequest(test_id=self.test["id"]))
            self.assertTrue(started["running"])
            self.assertTrue(main.read_classroom()["running"])
            from app.schemas import ClassroomControlRequest, RecoverClassroomRequest
            self.assertTrue(main.control_classroom(ClassroomControlRequest(locked=True))["locked"])
            ended = main.end_classroom(EndClassroomRequest(save=False))
            with self.assertRaises(HTTPException) as error:
                main.recover_classroom(RecoverClassroomRequest(session_id="missing"))
            self.assertEqual(error.exception.status_code, 404)
            self.assertFalse(ended["saved"])
            self.assertFalse(main.read_classroom()["running"])


class SavedAsTheyArriveTests(ClassroomTestCase):
    def stored(self):
        from app.database import connect
        with connect() as db:
            return db.execute("SELECT student_name, score FROM classroom_submissions ORDER BY student_name").fetchall()

    def test_each_submission_is_stored_and_cleared_when_the_quiz_ends(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        self.assertEqual([(row["student_name"], row["score"]) for row in self.stored()], [("Ana", 5)])
        self.assertNotIn("unsaved_quizzes", classroom.session_status())  # the running quiz is not "unsaved"
        classroom.end_session(server=self.server)
        self.assertEqual(self.stored(), [])

    def test_a_crashed_quiz_can_be_recovered_into_item_analysis(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        ben = classroom.join(code, "Ben", "10.0.0.3")
        classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        classroom.submit(ben["token"], {}, "10.0.0.3")
        classroom._reset_for_tests()  # the app closed without ending the quiz
        status = classroom.session_status()
        self.assertFalse(status["running"])
        unsaved = status["unsaved_quizzes"]
        self.assertEqual(len(unsaved), 1)
        self.assertEqual((unsaved[0]["test_id"], unsaved[0]["submitted"]), (self.test["id"], 2))
        result = classroom.recover_quiz(unsaved[0]["session_id"], save=True)
        self.assertTrue(result["saved"])
        analysis = main.read_analysis(self.test["id"])
        self.assertEqual(sorted(student["score"] for student in analysis["students"]), [0, 5])
        self.assertEqual(self.stored(), [])
        self.assertNotIn("unsaved_quizzes", classroom.session_status())
        with self.assertRaises(HTTPException) as error:
            classroom.recover_quiz(unsaved[0]["session_id"], save=True)
        self.assertEqual(error.exception.status_code, 404)

    def test_recovered_answers_can_be_discarded(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        session_id = classroom._session.id
        with self.assertRaises(HTTPException) as error:
            classroom.recover_quiz(session_id, save=True)  # still running
        self.assertEqual(error.exception.status_code, 409)
        classroom._reset_for_tests()
        self.assertFalse(classroom.recover_quiz(session_id, save=False)["saved"])
        self.assertEqual(self.stored(), [])
        from app.database import connect
        with connect() as db:
            saved = db.execute("SELECT COUNT(*) FROM assessment_results WHERE test_id=?", (self.test["id"],)).fetchone()[0]
        self.assertEqual(saved, 0)


class TimeLimitTests(ClassroomTestCase):
    def test_time_limit_counts_down_and_closes_after_the_grace_period(self):
        from unittest.mock import patch
        now = 1_000_000.0
        with patch.object(classroom.time, "time", return_value=now):
            status = self.start(time_limit_minutes=2)
            self.assertEqual((status["time_limit_minutes"], status["seconds_left"], status["time_up"]), (2, 120, False))
            code = status["code"]
            ana = classroom.join(code, "Ana", "10.0.0.2")
            ben = classroom.join(code, "Ben", "10.0.0.3")
            self.assertEqual(classroom.questions_for(ana["token"], "10.0.0.2")["seconds_left"], 120)
        with patch.object(classroom.time, "time", return_value=now + 120 + classroom.LATE_SUBMIT_GRACE_SECONDS - 1):
            self.assertTrue(classroom.session_status()["time_up"])
            self.assertEqual(classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")["score"], 5)  # phone's auto-submit
        with patch.object(classroom.time, "time", return_value=now + 120 + classroom.LATE_SUBMIT_GRACE_SECONDS + 1):
            with self.assertRaises(HTTPException) as error:
                classroom.submit(ben["token"], {}, "10.0.0.3")
            self.assertEqual(error.exception.status_code, 410)
            self.assertIn("Time is up", error.exception.detail)
            status = classroom.control_session(add_minutes=5)  # the teacher gives more time
            self.assertEqual(status["seconds_left"], 300)
            self.assertEqual(classroom.submit(ben["token"], {}, "10.0.0.3")["score"], 0)

    def test_bad_time_limits_are_refused(self):
        with self.assertRaises(HTTPException) as error:
            self.start(time_limit_minutes=500)
        self.assertEqual(error.exception.status_code, 422)
        status = self.start()
        self.assertIsNone(status["seconds_left"])
        with self.assertRaises(HTTPException) as error:
            classroom.control_session(add_minutes=90)
        self.assertEqual(error.exception.status_code, 422)


class LockAndReleaseTests(ClassroomTestCase):
    def test_locking_stops_new_students_but_not_those_already_in(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        self.assertTrue(classroom.control_session(locked=True)["locked"])
        with self.assertRaises(HTTPException) as error:
            classroom.join(code, "Late", "10.0.0.9")
        self.assertEqual(error.exception.status_code, 403)
        self.assertIn("closed joining", error.exception.detail)
        self.assertEqual(classroom.questions_for(ana["token"], "10.0.0.2")["total"], 5)
        classroom.control_session(locked=False)
        self.assertEqual(classroom.join(code, "Late", "10.0.0.9")["name"], "Late")

    def test_corrections_only_after_the_teacher_shows_the_answers(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        ben = classroom.join(code, "Ben", "10.0.0.3")
        answers = self.perfect("A")
        answers["1"] = "D" if answers["1"] != "D" else "C"
        classroom.submit(ana["token"], answers, "10.0.0.2")
        with self.assertRaises(HTTPException) as error:
            classroom.review_for(ana["token"], "10.0.0.2")
        self.assertEqual(error.exception.status_code, 403)
        status = classroom.control_session(release_answers=True)
        self.assertTrue(status["answers_released"])
        self.assertTrue(status["locked"])
        review = classroom.review_for(ana["token"], "10.0.0.2")
        self.assertEqual((review["score"], review["total"]), (4, 5))
        self.assertEqual([item["correct"] for item in review["items"]], [False, True, True, True, True])
        self.assertTrue(review["items"][0]["correct_answer"])
        with self.assertRaises(HTTPException) as error:
            classroom.review_for(ben["token"], "10.0.0.3")  # never submitted
        self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as error:
            classroom.submit(ben["token"], self.perfect("B"), "10.0.0.3")
        self.assertEqual(error.exception.status_code, 410)
        with self.assertRaises(HTTPException) as error:
            classroom.join(code, "Cara", "10.0.0.4")
        self.assertEqual(error.exception.status_code, 403)


class LiveStatsAndAwayTests(ClassroomTestCase):
    def test_teacher_sees_how_each_question_is_going(self):
        code = self.start("A")["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        ben = classroom.join(code, "Ben", "10.0.0.3")
        classroom.submit(ana["token"], self.perfect("A"), "10.0.0.2")
        stats = classroom.session_status()["item_stats"]
        self.assertEqual([item["number"] for item in stats], [1, 2, 3, 4, 5])
        self.assertTrue(all(item["submitted"] == 1 and item["percent_correct"] == 100 for item in stats))
        classroom.submit(ben["token"], {"1": self.perfect("A")["1"]}, "10.0.0.3")
        stats = classroom.session_status()["item_stats"]
        self.assertEqual(stats[0]["percent_correct"], 100)
        self.assertEqual([item["percent_correct"] for item in stats[1:]], [50, 50, 50, 50])
        self.assertEqual(stats[1]["answered"], 1)

    def test_leaving_the_page_is_counted_once_per_time(self):
        code = self.start()["code"]
        ana = classroom.join(code, "Ana", "10.0.0.2")
        classroom.report_away(ana["token"], True, "10.0.0.2")
        classroom.report_away(ana["token"], True, "10.0.0.2")  # the same absence reported twice
        status = classroom.session_status()
        self.assertEqual((status["students"][0]["left_page"], status["students"][0]["away"], status["away_now"]), (1, True, 1))
        classroom.report_away(ana["token"], False, "10.0.0.2")
        classroom.report_away(ana["token"], True, "10.0.0.2")
        self.assertEqual(classroom.session_status()["students"][0]["left_page"], 2)
        classroom.submit(ana["token"], {}, "10.0.0.2")
        classroom.report_away(ana["token"], True, "10.0.0.2")  # after submitting it no longer matters
        student = classroom.session_status()["students"][0]
        self.assertEqual((student["left_page"], student["away"]), (2, False))


class ShuffleTests(ClassroomTestCase):
    def answer_by_display(self, token, address):
        """Answer every question correctly, using the letters this phone shows."""
        data = classroom.questions_for(token, address)
        student = classroom._session.students[token]
        answers = {}
        for question in data["questions"]:
            entry = self.test["sets"][student.set_label][question["key"] - 1]
            correct = self.test["items"][entry["item"]]["correct_answer"]
            if question["type"] == "Multiple Choice":
                answers[str(question["key"])] = "ABCDEFGH"[question["choices"].index(correct)]
            else:
                answers[str(question["key"])] = correct
        return data, answers

    def test_each_student_gets_their_own_order_and_is_graded_correctly(self):
        code = self.start("A", shuffle_questions=True)["code"]
        orders = set()
        for index in range(6):
            token = classroom.join(code, f"Student {index}", f"10.0.1.{index}")["token"]
            data, answers = self.answer_by_display(token, f"10.0.1.{index}")
            self.assertEqual([question["number"] for question in data["questions"]], [1, 2, 3, 4, 5])
            keys = [question["key"] for question in data["questions"]]
            self.assertEqual(sorted(keys), [1, 2, 3, 4, 5])
            types = [question["type"] for question in data["questions"]]
            self.assertEqual(types, sorted(types, key=["Multiple Choice", "True or False", "Identification"].index))
            self.assertEqual(data, classroom.questions_for(token, f"10.0.1.{index}"))  # same order every time
            orders.add((tuple(keys), tuple(tuple(question["choices"]) for question in data["questions"])))
            self.assertEqual(classroom.submit(token, answers, f"10.0.1.{index}")["score"], 5)
        self.assertGreater(len(orders), 1)
        classroom.end_session(server=self.server)
        self.assertEqual([student["score"] for student in main.read_analysis(self.test["id"])["students"]], [5] * 6)


class QrCodeTests(unittest.TestCase):
    def test_qr_code_has_the_standard_structure(self):
        from app import qr_code

        modules = qr_code.matrix("http://192.168.137.1:8800")
        self.assertEqual(len(modules), 25)  # version 2
        finder = [[max(abs(x - 3), abs(y - 3)) not in (2, 4) for x in range(7)] for y in range(7)]
        size = len(modules)
        for ox, oy in ((0, 0), (size - 7, 0), (0, size - 7)):
            self.assertEqual([list(row[ox:ox + 7]) for row in modules[oy:oy + 7]], finder)
        self.assertEqual([modules[6][x] for x in range(8, size - 8)], [x % 2 == 0 for x in range(8, size - 8)])
        self.assertTrue(modules[size - 8][8])  # the dark module
        # Both copies of the format information must hold the same valid level-M word.
        first = [modules[y][8] for y in (0, 1, 2, 3, 4, 5, 7, 8)] + [modules[8][x] for x in (7, 5, 4, 3, 2, 1, 0)]
        second = [modules[8][size - 1 - i] for i in range(8)] + [modules[size - 15 + i][8] for i in range(8, 15)]
        value = lambda bits: sum(1 << index for index, bit in enumerate(bits) if bit)
        valid = {qr_code._format_bits(mask) for mask in range(8)}
        self.assertIn(value(first), valid)
        self.assertEqual(value(first), value(second))
        self.assertEqual(qr_code.matrix("http://192.168.137.1:8800"), modules)
        svg = qr_code.svg("http://192.168.137.1:8800")
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertNotIn("<script", svg)
        self.assertEqual(len(qr_code.matrix("http://192.168.100.200:8809")), 29)  # version 3
        with self.assertRaises(ValueError):
            qr_code.matrix("x" * 200)


if __name__ == "__main__":
    unittest.main()
