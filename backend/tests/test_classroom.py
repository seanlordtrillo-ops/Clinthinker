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

    def start(self, set_mode="alternate"):
        return classroom.start_session(self.test["id"], set_mode, 8800, server=self.server)

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
        self.assertEqual(self.client.get("/api/status", headers={"X-Quiz-Token": token}).json(), {"state": "submitted"})

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
            ended = main.end_classroom(EndClassroomRequest(save=False))
            self.assertFalse(ended["saved"])
            self.assertFalse(main.read_classroom()["running"])


if __name__ == "__main__":
    unittest.main()
