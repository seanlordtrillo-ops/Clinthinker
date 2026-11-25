# Copilot prompt: Test Builder, Item Analysis, and "Practice this topic"

Paste everything below the line into Copilot Chat (Agent mode) with the `clinthinker` folder open.

---

The backend for teacher tools is already done and tested. **Do not change anything in `backend/`.** Only change `frontend/src/lib/api.js`, `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx` and `frontend/src/styles.css`. Follow the existing code style, components, CSS classes, color themes (orange, pink, regal, cmu) and the narrow mobile layout. Reuse the existing `apiRequest` helper, the error/notice display, and the existing Blob + anchor download pattern used for the saved-questions CSV export.

## 1. Add to the `api` object in `frontend/src/lib/api.js`

```js
buildTest: (payload) => apiRequest("/api/tests", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
}),
tests: () => apiRequest("/api/tests"),
test: (id) => apiRequest(`/api/tests/${encodeURIComponent(id)}`),
renameTest: (id, title) => apiRequest(`/api/tests/${encodeURIComponent(id)}`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ title })
}),
deleteTest: (id) => apiRequest(`/api/tests/${encodeURIComponent(id)}`, { method: "DELETE" }),
importTestResults: (id, file) => {
  const body = new FormData();
  body.append("file", file);
  return apiRequest(`/api/tests/${encodeURIComponent(id)}/results`, { method: "POST", body });
},
testAnalysis: (id) => apiRequest(`/api/tests/${encodeURIComponent(id)}/analysis`),
```

The two download endpoints return files, not JSON, so fetch them as blobs (handle errors like `apiRequest` does) and save with the existing download pattern, using the file name from the `Content-Disposition` header:
- `GET /api/tests/{id}/export?document=test&set_label=A` (or `B`) → Word test paper
- `GET /api/tests/{id}/export?document=key` → Word answer key (both sets)
- `GET /api/tests/{id}/export?document=tos` → Word Table of Specifications
- `GET /api/tests/{id}/results-template` → CSV template for entering the class's answers

## 2. Backend response shapes

`POST /api/tests` body:
```json
{ "title": "HCI Midterm", "training_dataset_id": "<id or builtin>", "lesson_upload_ids": ["…"],
  "total_items": 30, "question_types": ["Multiple Choice", "True or False", "Identification"],
  "items_per_topic": null, "include_set_b": true }
```
`total_items` 5–100. `question_types` 1–3 of those three values. `items_per_topic` is optional, e.g. `{"Usability": 5, "Affordance": 3}`; when given, it overrides `total_items`. Building takes a few seconds; show a spinner.

`POST /api/tests` and `GET /api/tests/{id}` return:
```json
{
  "id": "…", "title": "HCI Midterm", "created_at": "2026-11-25 08:00:00",
  "lesson_names": ["HCI 2.pdf"], "training_dataset_name": "…",
  "question_types": ["Multiple Choice", "True or False"], "total_items": 30,
  "items": [{ "index": 0, "question_id": "…", "question_type": "Multiple Choice",
              "question_text": "…", "choices": ["…"], "correct_answer": "…", "topic": "Usability",
              "cognitive_level": "Remembering", "likelihood": "High",
              "source_material_name": "HCI 2.pdf", "explanation": "full source sentence" }],
  "specification": {
    "rows": [{ "topic": "Usability", "lesson_passages": 12, "weight_percent": 40.0,
               "questions_available": 15, "items": 12, "percent_of_test": 40.0,
               "item_numbers": [1, 2, 3], "cognitive_levels": { "Remembering": 12 } }],
    "totals": { "lesson_passages": 30, "items": 30, "questions_available": 48 },
    "cognitive_levels": ["Remembering"], "method": "explanation text"
  },
  "sets": { "A": [{ "item": 0, "choices": ["…"] }], "B": [{ "item": 7, "choices": ["…"] }] },
  "answer_keys": { "A": [{ "number": 1, "answer": "C", "answer_text": "Usability" }], "B": [] },
  "warnings": ["…"]
}
```
`sets.A[n]` is question number n+1 in Set A: `items[entry.item]` with options in `entry.choices` order. `sets.B` only exists when Set B was made.

`GET /api/tests` → `{ "tests": [{ "id", "title", "created_at", "total_items", "question_types", "lesson_names", "sets": ["A","B"], "students": 0 }] }`

`POST /api/tests/{id}/results` (CSV upload) → `{ "test_id", "students": 30, "sets": {"A": 15, "B": 15}, "warnings": ["…"] }`. Importing again replaces the previous results.

`GET /api/tests/{id}/analysis` (422 if fewer than 2 students imported) →
```json
{
  "title": "…",
  "summary": { "students": 30, "items": 30, "group_size": 8, "mean_score": 18, "median_score": 18,
               "standard_deviation": 5.9, "highest_score": 29, "lowest_score": 6, "mean_percent": 60.0,
               "kr20": 0.83, "reliability": "Good", "decisions": { "Retain": 28, "Revise": 1, "Discard": 1 } },
  "items": [{ "number": 1, "question_text": "…", "question_type": "Multiple Choice", "topic": "…",
              "correct_answer": "…", "correct_count": 19, "upper_correct": 8, "lower_correct": 3,
              "difficulty_index": 0.633, "difficulty": "Easy", "discrimination_index": 0.625,
              "discrimination": "Very good", "decision": "Retain", "unanswered": 0,
              "options": [{ "choice": "…", "is_answer": true, "chosen_by": 19, "upper": 8, "lower": 3, "flag": null }] }],
  "topics": [{ "topic": "…", "items": 5, "average_difficulty_index": 0.42 }],
  "students": [{ "name": "…", "set": "A", "score": 29 }],
  "warnings": ["…"],
  "method": { "difficulty_index": "…", "discrimination_index": "…", "decision": "…", "kr20": "…" }
}
```
`options` exists only for Multiple Choice items. `kr20` can be `null`. `topics` is sorted hardest first.

## 3. Sidebar

In `Sidebar.jsx`, add a second label **TEACHER TOOLS** under the existing items, with two pages: `["Test Builder", ClipboardList]` and `["Item Analysis", BarChart3]` (import both icons from `lucide-react`). Add both pages to `App.jsx` the same way the other pages are added.

## 4. Test Builder page

**Build form (top):**
- Title text input.
- Lessons: checkboxes listing the saved uploads that aren't marked as exams (reuse the uploads list already loaded in `App.jsx`), with an Upload button that reuses the existing lesson upload flow.
- Training dataset: a dropdown of the existing training datasets (default: the one selected in Settings).
- Number of items (5–100, default 30).
- Question types: three checkboxes (Multiple Choice checked by default; at least one must stay checked).
- "Make a Set B (shuffled)" checkbox, on by default.
- **Build test** button with a spinner.

**After building, show the test in four tabs:**
1. **Table of Specifications:** a table with Topic | Lesson passages | Weight % | No. of items | % of test | Remembering | Item placement (format item_numbers as ranges like "1-3, 7"), plus a Total row and the `method` text in small print below. Hide rows with 0 items behind a "Show topics with no items" toggle. Make the **No. of items** cells editable number inputs, with a **Rebuild with these numbers** button that calls `buildTest` again with `items_per_topic` set from the table, keeping the other form values.
2. **Preview:** a Set A / Set B switch. Show the test as the student sees it, grouped into sections ("Test I. Multiple Choice", "Test II. True or False", "Test III. Identification") using `sets[label]` order and numbering, with options lettered A–D in `entry.choices` order. Add a **Show answers** toggle that highlights the answer from `answer_keys` and shows `explanation` under each item.
3. **Answer key:** a table No. | Set A | Set B.
4. **Download:** buttons for "Test paper – Set A", "Test paper – Set B" (only if Set B exists), "Answer key", "Table of Specifications" and "Results template (CSV)". Add a note: "Word files open in Microsoft Word, WPS Office or Google Docs."

Show any `warnings` in the existing notice style above the tabs.

**Saved tests list (bottom or side):** from `api.tests()`, newest first: title, date, item count, sets, number of students imported. Buttons: Open (loads it with `api.test(id)` into the tabs above), Rename (inline), Delete (with `window.confirm`), and **Analyze** (goes to the Item Analysis page with that test selected).

## 5. Item Analysis page

- A dropdown of saved tests (from `api.tests()`), preselected when coming from **Analyze**.
- Short instructions: "1. Download the results template. 2. Enter each student's answers (letters for multiple choice, T/F for true or false, the term for identification) and their set. 3. Import the CSV." Include the **Download template** button and an **Import results (CSV)** file button. After import, show the result message and any warnings, then load the analysis.
- If the analysis returns 422, show its message instead of the results.

**Results:**
1. **Summary cards:** students, mean score (and mean %), median, standard deviation, highest/lowest, KR-20 reliability with its label (show "—" when null), and counts of Retain / Revise / Discard.
2. **Item table:** No. | Question (truncated, full text on hover or expand) | Topic | Difficulty index (with label) | Discrimination index (with label) | Decision. Color the decision with the theme's success/warning/danger styles. Add a filter: All / Retain / Revise / Discard.
3. Expanding a Multiple Choice row shows **distractor analysis**: each option with chosen by / upper / lower, the correct answer marked, and the `flag` text when present.
4. **Topics:** average difficulty index per topic, hardest first, as a simple bar list.
5. **Students:** name, set, score, sorted highest first.
6. Show `warnings`, and a collapsible **"How is this calculated?"** with the four `method` texts.

## 6. "Practice this topic" on My Progress

When the user clicks a topic's **Practice this topic** button on My Progress, open Generate Practice Questions and generate questions for **only that topic**: the backend already accepts a specific topic in lesson mode. In `generateQuestions` in `App.jsx`, add an optional `topic` argument (default `"All Topics"`) and send it as the `topic` field instead of the hard-coded `"All Topics"`. While a topic is selected, show a small chip "Topic: Usability ✕" above the questions; clicking ✕ goes back to all topics. If the response is a 422 error, show its message.

## 7. Finish

- Don't change any other behavior. Keep "Reveal answers" on the practice page as it is.
- Run `npm.cmd --prefix frontend run build:web` and fix any errors before finishing.
