const API_ROOT = window.location.origin;
let startupUpdateCheck;
export const SAFETY_BLOCKED_MESSAGE =
  "This request was blocked for safety. Open Clinthinker from its own window or from http://localhost:5173.";

function normalizeSafetyError(message, status) {
  return [400, 403].includes(status) && /other websites|unknown address/i.test(message)
    ? SAFETY_BLOCKED_MESSAGE
    : message;
}

export function formatApiError(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item?.msg)
      .filter((message) => typeof message === "string")
      .map((message) => message.replace(/^Value error, /, ""));
    return messages.join("; ") || fallback;
  }
  return fallback;
}

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_ROOT}${path}`, options);
  } catch (error) {
    throw new Error(
      `The local service is unavailable. Start the app's backend and try again. (${error.message})`
    );
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = formatApiError(body.detail, message);
    } catch {
      // Keep the HTTP status message if the server did not return JSON.
    }
    throw Object.assign(
      new Error(normalizeSafetyError(message, response.status)),
      { status: response.status }
    );
  }
  return response.json();
}

async function apiDownload(path) {
  let response;
  try {
    response = await fetch(`${API_ROOT}${path}`);
  } catch (error) {
    throw new Error(
      `The local service is unavailable. Start the app's backend and try again. (${error.message})`
    );
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = formatApiError(body.detail, message);
    } catch {
      // Keep the HTTP status message if the server did not return JSON.
    }
    throw Object.assign(
      new Error(normalizeSafetyError(message, response.status)),
      { status: response.status }
    );
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const quotedName = disposition.match(/filename="([^"]+)"/i)?.[1];
  const plainName = disposition.match(/filename=([^;\s]+)/i)?.[1];
  return {
    blob: await response.blob(),
    filename: encodedName
      ? decodeURIComponent(encodedName)
      : quotedName || plainName || "download"
  };
}

export const api = {
  health: () => apiRequest("/api/health"),
  startupUpdateCheck: () => {
    if (!startupUpdateCheck) startupUpdateCheck = apiRequest("/api/updates/check");
    return startupUpdateCheck;
  },
  checkForUpdates: () => apiRequest("/api/updates/check"),
  installUpdate: () => apiRequest("/api/updates/install", {
    method: "POST",
    headers: { "X-Clinthinker-Request": "1" }
  }),
  uploads: () => apiRequest("/api/uploads"),
  trainingDatasets: () => apiRequest("/api/training-datasets"),
  evaluateTrainingDataset: (trainingDatasetId) => apiRequest("/api/training-datasets/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ training_dataset_id: trainingDatasetId })
  }),
  questionPreferences: () => apiRequest("/api/questions/preferences"),
  rateQuestion: (questionId, rating, generationId = null) => apiRequest("/api/questions/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question_id: questionId,
      rating,
      ...(generationId ? { generation_id: generationId } : {})
    })
  }),
  clearQuestionPreferences: () => apiRequest("/api/questions/feedback", { method: "DELETE" }),
  trainingTopics: (id) => apiRequest(`/api/training-datasets/${encodeURIComponent(id)}/topics`),
  generateQuestions: (payload) => apiRequest("/api/questions/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }),
  resetQuestionHistory: (uploadIds) => apiRequest("/api/questions/history/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_ids: uploadIds })
  }),
  saveQuestions: (generationId, questionIds) => apiRequest("/api/questions/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ generation_id: generationId, question_ids: questionIds })
  }),
  revealQuestionAnswers: (generationId, questionIds) => apiRequest("/api/questions/answers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ generation_id: generationId, question_ids: questionIds })
  }),
  submitAnswer: (questionId, answer, generationId = null) => apiRequest("/api/attempts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question_id: questionId, answer, generation_id: generationId })
  }),
  progress: () => apiRequest("/api/progress"),
  dueReviews: ({ limit = 20, topic = null, mistakesOnly = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), mistakes_only: String(mistakesOnly) });
    if (topic) params.set("topic", topic);
    return apiRequest(`/api/review/due?${params}`);
  },
  clearProgress: () => apiRequest("/api/progress", { method: "DELETE" }),
  savedQuestions: (includeAnswers = false, sessionId = null) => apiRequest(
    `/api/questions/saved?include_answers=${includeAnswers}${sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : ""}`
  ),
  renameSavedSession: (id, title) => apiRequest(`/api/questions/sessions/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title })
  }),
  deleteSavedSession: (id) => apiRequest(`/api/questions/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE"
  }),
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
  classroom: () => apiRequest("/api/classroom"),
  startClassroom: (testId, setMode = "alternate", { timeLimitMinutes = null, shuffleQuestions = true } = {}) =>
    apiRequest("/api/classroom/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_id: testId,
      set_mode: setMode,
      time_limit_minutes: timeLimitMinutes || null,
      shuffle_questions: shuffleQuestions
    })
  }),
  controlClassroom: ({ locked = null, addMinutes = null, releaseAnswers = false } = {}) =>
    apiRequest("/api/classroom/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locked, add_minutes: addMinutes, release_answers: releaseAnswers })
    }),
  recoverClassroom: (sessionId, save = true) => apiRequest("/api/classroom/recover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, save })
  }),
  endClassroom: (save = true) => apiRequest("/api/classroom/end", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ save })
  }),
  downloadTestExport: (id, document, setLabel = null) => {
    const params = new URLSearchParams({ document });
    if (setLabel) params.set("set_label", setLabel);
    return apiDownload(`/api/tests/${encodeURIComponent(id)}/export?${params}`);
  },
  downloadTestResultsTemplate: (id) => apiDownload(`/api/tests/${encodeURIComponent(id)}/results-template`),
  latestAnalysis: () => apiRequest("/api/analysis/latest"),
  settings: () => apiRequest("/api/settings"),
  saveSettings: (settings) => apiRequest("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings)
  }),
  uploadMaterial: async (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiRequest("/api/upload", { method: "POST", body: form });
  },
  uploadLesson: async (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiRequest("/api/lessons/upload", { method: "POST", body: form });
  },
  savedMaterial: (id) => apiRequest(`/api/uploads/${encodeURIComponent(id)}/text`),
  setUploadExam: (id, isExam) => apiRequest(`/api/uploads/${encodeURIComponent(id)}/exam`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_exam: isExam })
  }),
  deleteUpload: (id) => apiRequest(`/api/uploads/${encodeURIComponent(id)}`, { method: "DELETE" }),
  importTrainingCsv: (file, name) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return apiRequest("/api/training-datasets/csv", { method: "POST", body: form });
  },
  createDocumentDataset: (payload) => apiRequest("/api/training-datasets/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }),
  deleteTrainingDataset: (id) => apiRequest(`/api/training-datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  predict: async (payload, onProgress) => {
    let response;
    try {
      response = await fetch(`${API_ROOT}/api/predict/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (error) {
      throw new Error(`The local service is unavailable. (${error.message})`);
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const message = formatApiError(body.detail, `Prediction failed (${response.status})`);
      throw Object.assign(
        new Error(normalizeSafetyError(message, response.status)),
        { status: response.status }
      );
    }
    if (!response.body) throw new Error("The local service did not provide prediction progress.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let result = null;
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value || new Uint8Array(), { stream: !done });
      const frames = pending.split("\n\n");
      pending = frames.pop() || "";
      for (const frame of frames) {
        const event = frame.match(/^event:\s*(.+)$/m)?.[1];
        const data = frame.match(/^data:\s*(.+)$/m)?.[1];
        if (!event || !data) continue;
        const parsed = JSON.parse(data);
        if (event === "progress") onProgress(parsed);
        if (event === "error") {
          const status = Number(parsed.status || parsed.status_code) || null;
          const message = normalizeSafetyError(
            parsed.detail || "Prediction failed.",
            status
          );
          throw Object.assign(new Error(message), status ? { status } : {});
        }
        if (event === "result") result = parsed;
      }
      if (done) break;
    }
    if (!result) throw new Error("The prediction stream ended without a result.");
    return result;
  }
};
