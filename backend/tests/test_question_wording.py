import unittest

from app.definitions import _choice_without_note, _description_question, _normalize_choice, _stem_heading
from app.lesson_structure import sentence_headings
from app.questions import generate_questions
from app.text_cleaning import _SENTENCE_END

LESSON = """Applications Development Lesson

1. Software Development Life Cycle (SDLC)
Planning — define the problem, goals, scope, budget and feasibility.
Requirements analysis — gather functional and non-functional requirements.
Design — create the architecture, database design and user interface.
Implementation (coding) — write the program.
Testing — find and fix defects before release.
Deployment — release the system to users.
Maintenance — fix bugs, update and improve the system.

2. Types of Applications
Native mobile apps — built for one platform such as Android or iOS.
Cross-platform apps — one codebase for several platforms.
Web apps — applications that run in a web browser.
Progressive Web Apps (PWAs) — web apps that can be installed and work offline.

Extended Reality (XR)
Virtual Reality (VR) — a fully computer-generated environment.
Augmented Reality (AR) — digital content overlaid on the real world.
Mixed Reality (MR) — digital objects interact with the real world.
"""

TRAINING = [
    ("software development life cycle planning requirements design implementation testing deployment maintenance", "Software Development"),
    ("sdlc phases planning analysis design coding testing release", "Software Development"),
    ("requirements analysis design phase implementation coding program", "Software Development"),
    ("native mobile apps cross platform web apps progressive web apps browser", "Applications"),
    ("android ios flutter react native web application install offline", "Applications"),
    ("virtual reality augmented reality mixed reality headset immersive", "Applications"),
]


def headings_for(text):
    parts = _SENTENCE_END.split(text)
    return dict(zip(parts, sentence_headings(text, parts)))


class LessonStructureTests(unittest.TestCase):
    def test_list_items_get_their_heading(self):
        headings = headings_for(LESSON)
        self.assertEqual(headings["Design — create the architecture, database design and user interface."],
                         "Software Development Life Cycle (SDLC)")
        self.assertEqual(headings["Web apps — applications that run in a web browser."], "Types of Applications")
        self.assertEqual(headings["Mixed Reality (MR) — digital objects interact with the real world."],
                         "Extended Reality (XR)")

    def test_numbered_list_items_and_wrapped_lines_are_not_headings(self):
        text = (
            "Nielsen's 10 Usability Heuristics\n1.\nVisibility of system status\n2.\n"
            "Match between system and the real world\n3.\nUser control and freedom\n"
            "User-based methods\nUsability testing — real users perform tasks while observers record success.\n"
            "AI is the ability of machines to do tasks. Machine\nLearning lets systems learn from data.\n"
        )
        headings = headings_for(text)
        self.assertEqual(headings["Usability testing — real users perform tasks while observers record success."],
                         "User-based methods")
        self.assertEqual(headings["Match between system and the real world"], "Nielsen's 10 Usability Heuristics")
        self.assertNotEqual(headings["Learning lets systems learn from data."], "Machine")


class ChoiceFormattingTests(unittest.TestCase):
    def test_acronyms_in_mixed_case_terms_stay_uppercase(self):
        self.assertEqual(_normalize_choice("Augmented Reality (AR)"), "Augmented reality (AR)")
        self.assertEqual(_normalize_choice("CLOCK SPEED"), "Clock speed")
        self.assertEqual(_normalize_choice("Progressive Web Apps (PWAs)"), "Progressive web apps (PWAs)")

    def test_options_drop_bracketed_notes(self):
        self.assertEqual(_choice_without_note("Implementation (coding)"), "Implementation")
        self.assertEqual(_choice_without_note("Augmented reality (AR)"), "Augmented reality")
        self.assertEqual(_choice_without_note("(AR)"), "(AR)")

    def test_stem_names_the_list_and_keeps_only_acronym_notes(self):
        self.assertEqual(_stem_heading("Design Thinking (Stanford d.school)"), "Design Thinking")
        self.assertEqual(_stem_heading("Software Development Life Cycle (SDLC)"), "Software Development Life Cycle (SDLC)")
        stems = {_description_question("write the program.", "Software Development Life Cycle (SDLC)", seed) for seed in "abcdefghij"}
        self.assertTrue(all('"Software Development Life Cycle (SDLC)"' in stem and '"write the program"' in stem for stem in stems))
        self.assertGreater(len(stems), 1)


class GeneratedQuestionTests(unittest.TestCase):
    def generate(self, question_type="Multiple Choice"):
        return generate_questions(
            requested_count=20,
            question_type=question_type,
            difficulty="Moderate",
            topic_filter="All Topics",
            per_topic=20,
            training_examples=TRAINING,
            dataset_id="patch4",
            dataset_name="Patch 4",
            sources=[{"id": "lesson", "name": "Lesson", "text": LESSON, "kind": "lesson"}],
            lesson_mode=True,
            random_seed=11,
            allow_repeats=True,
        )["questions"]

    def test_options_come_from_the_same_list(self):
        groups = [
            {"planning", "requirements analysis", "design", "implementation", "testing", "deployment", "maintenance"},
            {"native mobile apps", "cross-platform apps", "web apps", "progressive web apps"},
            {"virtual reality", "augmented reality", "mixed reality"},
        ]
        questions = [item for item in self.generate() if item.get("choices")]
        self.assertTrue(questions)
        for item in questions:
            answer = item["correct_answer"].casefold()
            group = next((group for group in groups if answer in group), None)
            if group is None or len(group) < 4:
                continue
            with self.subTest(question=item["question_text"]):
                self.assertTrue(all(choice.casefold() in group for choice in item["choices"]), item["choices"])

    def test_no_option_has_a_bracketed_note_or_lowercase_acronym(self):
        for item in self.generate():
            for choice in item.get("choices") or []:
                with self.subTest(choice=choice):
                    self.assertNotRegex(choice, r"\)$")
                    self.assertNotRegex(choice, r"\((?:ar|vr|mr|pwas)\)")

    def test_description_stems_name_their_list(self):
        headings = ("Software Development Life Cycle (SDLC)", "Types of Applications", "Extended Reality (XR)")
        stems = [item["question_text"] for item in self.generate()]
        self.assertTrue(stems)
        for stem in stems:
            with self.subTest(stem=stem):
                self.assertTrue(any(f'"{heading}"' in stem for heading in headings))


if __name__ == "__main__":
    unittest.main()
