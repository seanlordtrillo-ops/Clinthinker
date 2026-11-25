import { useEffect, useRef, useState } from "react";
import {
  AlertCircle, BrainCircuit, Check, ChevronDown, ChevronRight, Database, Download, Eye,
  FileSpreadsheet, FileText, FileUp, FolderOpen, Printer, RotateCcw,
  NotebookText, Pencil, Save, ShieldCheck, Sparkles, ThumbsDown, ThumbsUp, Trash2, Upload, X
} from "lucide-react";
import cmuShieldImage from "./assets/cmu-shield (2).png";
import Sidebar from "./components/Sidebar.jsx";
import { api, SAFETY_BLOCKED_MESSAGE } from "./lib/api.js";

const initialSettings = { appearance: "orange" };
const initialQuestionForm = {
  topic: "All Topics",
  question_type: "Multiple Choice",
  difficulty: "Moderate",
  number_of_questions: 10,
  questions_per_topic: 3,
  similarity_threshold: 82,
  allow_repeats: false,
  weights: { historical_frequency: 40, course_importance: 30, model_confidence: 20, recent_occurrence: 10 }
};

function AppErrorMessage({ message }) {
  return <div className="app-message app-message-error">
    <AlertCircle size={16} />
    {message === SAFETY_BLOCKED_MESSAGE
      ? <>This request was blocked for safety. Open Clinthinker from its own window or from <a href="http://localhost:5173">http://localhost:5173</a>.</>
      : message}
  </div>;
}

export default function App() {
  const [page, setPage] = useState("Upload");
  const [menuOpen, setMenuOpen] = useState(false);
  const [settings, setSettings] = useState(initialSettings);
  const [uploads, setUploads] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("builtin");
  const [trainingDatasetName, setTrainingDatasetName] = useState("");
  const [selectedTrainingUploads, setSelectedTrainingUploads] = useState([]);
  const [trainingLabels, setTrainingLabels] = useState({});
  const [trainingBusy, setTrainingBusy] = useState(false);
  const [queuedFiles, setQueuedFiles] = useState([]);
  const [latest, setLatest] = useState(null);
  const [latestSourceUploadIds, setLatestSourceUploadIds] = useState([]);
  const [progress, setProgress] = useState([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setErrorState] = useState("");
  const setError = (nextError) => {
    setErrorState((current) => {
      const message = typeof nextError === "function" ? nextError(current) : nextError;
      return typeof message === "string" && message.includes(SAFETY_BLOCKED_MESSAGE)
        ? SAFETY_BLOCKED_MESSAGE
        : message;
    });
  };
  const [notice, setNotice] = useState("");
  const [appVersion, setAppVersion] = useState("");
  const [updateOffer, setUpdateOffer] = useState(null);
  const [updateCheckBusy, setUpdateCheckBusy] = useState(false);
  const [updateState, setUpdateState] = useState("");
  const [updateFailureMessage, setUpdateFailureMessage] = useState("");
  const [updateInstallMessage, setUpdateInstallMessage] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [questionDatasetId, setQuestionDatasetId] = useState("builtin");
  const [questionUploadIds, setQuestionUploadIds] = useState([]);
  const [questionTopics, setQuestionTopics] = useState([]);
  const [lessonUploads, setLessonUploads] = useState([]);
  const [lessonUploadBusy, setLessonUploadBusy] = useState(false);
  const [lessonProgress, setLessonProgress] = useState(null);
  const [useExamStyle, setUseExamStyle] = useState(true);
  const [savedQuestions, setSavedQuestions] = useState([]);
  const [savedQuestionsBusy, setSavedQuestionsBusy] = useState(false);
  const [expandedSavedSessions, setExpandedSavedSessions] = useState([]);
  const [savedAnswerSessions, setSavedAnswerSessions] = useState([]);
  const [savedAnswersLoadedSessions, setSavedAnswersLoadedSessions] = useState([]);
  const [printingSavedSessionId, setPrintingSavedSessionId] = useState(null);
  const [questionResult, setQuestionResult] = useState(null);
  const [questionSetUnavailable, setQuestionSetUnavailable] = useState(false);
  const [questionPreferences, setQuestionPreferences] = useState({
    ratings_recorded: 0,
    positive_ratings: 0,
    negative_ratings: 0,
    learned_preferences: []
  });
  const [questionAnswers, setQuestionAnswers] = useState({});
  const [questionExplanations, setQuestionExplanations] = useState({});
  const [selectedQuestionAnswers, setSelectedQuestionAnswers] = useState({});
  const [questionAttemptResults, setQuestionAttemptResults] = useState({});
  const [selectedPracticeTopic, setSelectedPracticeTopic] = useState(null);
  const [checkingQuestionId, setCheckingQuestionId] = useState(null);
  const [studyProgress, setStudyProgress] = useState(null);
  const [studyProgressBusy, setStudyProgressBusy] = useState(false);
  const [teacherTests, setTeacherTests] = useState([]);
  const [teacherTestsBusy, setTeacherTestsBusy] = useState(false);
  const [classroomState, setClassroomState] = useState(null);
  const [classroomEndResult, setClassroomEndResult] = useState(null);
  const [classroomTestId, setClassroomTestId] = useState("");
  const [classroomBusy, setClassroomBusy] = useState(false);
  const [classroomPollError, setClassroomPollError] = useState("");
  const [classroomCopyNotice, setClassroomCopyNotice] = useState("");
  const [testBuildBusy, setTestBuildBusy] = useState(false);
  const [testOpenBusy, setTestOpenBusy] = useState(false);
  const [testResultsBusy, setTestResultsBusy] = useState(false);
  const [testTitle, setTestTitle] = useState("");
  const [testDatasetId, setTestDatasetId] = useState(null);
  const [testLessonUploadIds, setTestLessonUploadIds] = useState([]);
  const [testItemCount, setTestItemCount] = useState(30);
  const [testQuestionTypes, setTestQuestionTypes] = useState(["Multiple Choice"]);
  const [testIncludeSetB, setTestIncludeSetB] = useState(true);
  const [builtTest, setBuiltTest] = useState(null);
  const [testTab, setTestTab] = useState("specification");
  const [previewSet, setPreviewSet] = useState("A");
  const [showTestAnswers, setShowTestAnswers] = useState(false);
  const [showEmptyTestTopics, setShowEmptyTestTopics] = useState(false);
  const [specItemCounts, setSpecItemCounts] = useState({});
  const [analysisTestId, setAnalysisTestId] = useState("");
  const [testAnalysis, setTestAnalysis] = useState(null);
  const [testAnalysisBusy, setTestAnalysisBusy] = useState(false);
  const [analysisFilter, setAnalysisFilter] = useState("All");

  useEffect(() => {
    if (!printingSavedSessionId) return undefined;
    const clearPrintingSession = () => setPrintingSavedSessionId(null);
    window.addEventListener("afterprint", clearPrintingSession);
    window.print();
    return () => window.removeEventListener("afterprint", clearPrintingSession);
  }, [printingSavedSessionId]);
  useEffect(() => {
    if (updateState !== "installing") return undefined;
    const reminder = window.setTimeout(
      () => setUpdateInstallMessage("If the app did not close, close it to finish installing."),
      15000
    );
    return () => window.clearTimeout(reminder);
  }, [updateState]);
  const [questionBusy, setQuestionBusy] = useState(false);
  const [questionsSaved, setQuestionsSaved] = useState(false);
  const [questionForm, setQuestionForm] = useState({
    ...initialQuestionForm,
    weights: { ...initialQuestionForm.weights }
  });
  const fileInput = useRef(null);
  const trainingFileInput = useRef(null);
  const lessonFileInput = useRef(null);
  const csvInput = useRef(null);
  const testResultsInput = useRef(null);
  const testResultRef = useRef(null);
  const shouldScrollToTestRef = useRef(false);
  const classroomPollTimerRef = useRef(null);
  const classroomStatusVersionRef = useRef(0);
  const knownQuestionUploadIds = useRef(new Set());
  const answerStateVersion = useRef(0);
  const analysisRequestVersion = useRef(0);

  useEffect(() => {
    if (!builtTest || !shouldScrollToTestRef.current) return undefined;
    shouldScrollToTestRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      testResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [builtTest]);

  const refreshTeacherTests = async () => {
    setTeacherTestsBusy(true);
    try {
      const { tests: savedTests } = await api.tests();
      const sortedTests = [...savedTests].sort(
        (left, right) => new Date(right.created_at) - new Date(left.created_at)
      );
      setTeacherTests(sortedTests);
      return sortedTests;
    } catch (loadError) {
      setError(`Tests could not be loaded: ${loadError.message}`);
      return null;
    } finally {
      setTeacherTestsBusy(false);
    }
  };

  const loadTeacherTest = async (id) => {
    setTestOpenBusy(true);
    setError("");
    try {
      const loadedTest = await api.test(id);
      shouldScrollToTestRef.current = true;
      setBuiltTest(loadedTest);
      setTestTitle(loadedTest.title);
      setTestItemCount(loadedTest.total_items);
      setTestQuestionTypes(loadedTest.question_types);
      setTestIncludeSetB(Boolean(loadedTest.sets?.B));
      setTestLessonUploadIds(uploads
        .filter((upload) => (loadedTest.lesson_names || []).includes(upload.name) && !upload.is_exam)
        .map((upload) => upload.id));
      setTestDatasetId(datasets.find(
        (dataset) => dataset.name === loadedTest.training_dataset_name
      )?.id || questionDatasetId);
      setSpecItemCounts(Object.fromEntries(
        (loadedTest.specification?.rows || []).map((row) => [row.topic, String(row.items)])
      ));
      setTestTab("preview");
      setPreviewSet("A");
      setShowTestAnswers(false);
      return loadedTest;
    } catch (loadError) {
      shouldScrollToTestRef.current = false;
      setError(`Test could not be opened: ${loadError.message}`);
      return null;
    } finally {
      setTestOpenBusy(false);
    }
  };

  const loadTestAnalysis = async (id) => {
    if (!id) {
      setTestAnalysis(null);
      return null;
    }
    const requestVersion = ++analysisRequestVersion.current;
    setTestAnalysisBusy(true);
    setTestAnalysis(null);
    setError("");
    try {
      const analysis = await api.testAnalysis(id);
      if (requestVersion === analysisRequestVersion.current) setTestAnalysis(analysis);
      return analysis;
    } catch (analysisError) {
      if (requestVersion === analysisRequestVersion.current) {
        setError(analysisError.message);
      }
      return null;
    } finally {
      if (requestVersion === analysisRequestVersion.current) setTestAnalysisBusy(false);
    }
  };

  const refreshStudyProgress = async () => {
    setStudyProgressBusy(true);
    try {
      const result = await api.progress();
      setStudyProgress(result);
      return result;
    } catch (loadError) {
      setError(`Study progress could not be loaded: ${loadError.message}`);
      return null;
    } finally {
      setStudyProgressBusy(false);
    }
  };

  const syncSavedUploads = (savedUploads, excludedNewUploadIds = []) => {
    const availableIds = new Set(savedUploads.map((upload) => upload.id));
    const excludedIds = new Set(excludedNewUploadIds);
    const newlyAddedIds = savedUploads
      .filter((upload) => (
        !knownQuestionUploadIds.current.has(upload.id) && !excludedIds.has(upload.id)
      ))
      .map((upload) => upload.id);
    knownQuestionUploadIds.current = availableIds;
    setUploads(savedUploads);
    setQuestionUploadIds((current) => {
      const selectedIds = new Set([
        ...current.filter((id) => availableIds.has(id)),
        ...newlyAddedIds
      ]);
      return savedUploads
        .filter((upload) => selectedIds.has(upload.id))
        .map((upload) => upload.id);
    });
  };

  useEffect(() => {
    let active = true;
    Promise.all([api.health(), api.settings(), api.uploads(), api.latestAnalysis(), api.trainingDatasets()])
      .then(([health, savedSettings, savedUploads, savedAnalysis, savedDatasets]) => {
        if (!active) return;
        setAppVersion(health.version);
        setSettings({
          appearance: savedSettings.appearance || initialSettings.appearance
        });
        syncSavedUploads(savedUploads);
        const savedQuestionSettings = savedSettings.question_generation;
        const preferredDatasetId = savedQuestionSettings?.training_dataset_id || "builtin";
        const resolvedDatasetId = savedDatasets.some((dataset) => dataset.id === preferredDatasetId)
          ? preferredDatasetId
          : savedDatasets.find((dataset) => dataset.id !== "builtin")?.id || "builtin";
        setQuestionDatasetId(resolvedDatasetId);
        setSelectedDatasetId(resolvedDatasetId);
        if (savedQuestionSettings) {
          setQuestionForm({
            ...initialQuestionForm,
            ...savedQuestionSettings,
            similarity_threshold: Math.round(
              (savedQuestionSettings.similarity_threshold ?? 0.82) * 100
            ),
            weights: Object.fromEntries(
              Object.entries({
                ...initialQuestionForm.weights,
                ...Object.fromEntries(
                  Object.entries(savedQuestionSettings.priority_weights || {}).map(
                    ([key, value]) => [key, Math.round(value * 100)]
                  )
                )
              })
            )
          });
          const savedUploadIds = (savedQuestionSettings.upload_ids || []).filter((id) =>
            savedUploads.some((upload) => upload.id === id)
          );
          const allCurrentUploadsWereSelected = savedUploads.length > 0
            && savedUploads.every((upload) => savedUploadIds.includes(upload.id));
          setQuestionUploadIds(
            savedQuestionSettings.upload_ids === null || allCurrentUploadsWereSelected
              ? savedUploads.map((upload) => upload.id)
              : savedUploadIds
          );
        } else {
          setQuestionUploadIds(savedUploads.map((upload) => upload.id));
        }
        setLatest(savedAnalysis);
        setDatasets(savedDatasets);
      })
      .catch((loadError) => {
        if (active) setError(loadError.message);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    api.startupUpdateCheck()
      .then((update) => {
        if (active && update.available) setUpdateOffer(update);
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    api.questionPreferences()
      .then((preferences) => {
        if (active) setQuestionPreferences(preferences);
      })
      .catch((loadError) => {
        if (active) setError(`Question preferences could not be loaded: ${loadError.message}`);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    const requestVersion = classroomStatusVersionRef.current;
    api.classroom()
      .then((status) => {
        if (active && requestVersion === classroomStatusVersionRef.current) {
          setClassroomState(status);
          setClassroomPollError("");
        }
      })
      .catch((statusError) => {
        if (active && requestVersion === classroomStatusVersionRef.current) {
          setClassroomPollError(statusError.message);
        }
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (page !== "Settings") return;
    let active = true;
    api.trainingTopics(questionDatasetId)
      .then(({ topics }) => {
        if (!active) return;
        setQuestionTopics(topics);
        setQuestionForm((current) => ({
          ...current,
          topic: current.topic === "All Topics" || topics.includes(current.topic)
            ? current.topic : "All Topics"
        }));
      })
      .catch((loadError) => {
        if (active) setError(`Training topics could not be loaded: ${loadError.message}`);
      });
    return () => { active = false; };
  }, [page, questionDatasetId]);

  useEffect(() => {
    if (page !== "Saved Questions") return;
    let active = true;
    setSavedQuestionsBusy(true);
    setError("");
    api.savedQuestions()
      .then(({ sessions }) => {
        if (!active) return;
        setSavedQuestions(sessions);
        setExpandedSavedSessions(sessions.length ? [sessions[0].id] : []);
        setSavedAnswerSessions([]);
        setSavedAnswersLoadedSessions([]);
      })
      .catch((loadError) => {
        if (active) setError(`Saved questions could not be loaded: ${loadError.message}`);
      })
      .finally(() => {
        if (active) setSavedQuestionsBusy(false);
      });
    return () => { active = false; };
  }, [page]);

  useEffect(() => {
    if (page !== "My Progress") return;
    let active = true;
    setStudyProgressBusy(true);
    setError("");
    api.progress()
      .then((result) => {
        if (active) setStudyProgress(result);
      })
      .catch((loadError) => {
        if (active) setError(`Study progress could not be loaded: ${loadError.message}`);
      })
      .finally(() => {
        if (active) setStudyProgressBusy(false);
      });
    return () => { active = false; };
  }, [page]);

  useEffect(() => {
    if (page !== "Test Builder" && page !== "Item Analysis" && page !== "Classroom Quiz") return;
    let active = true;
    setTeacherTestsBusy(true);
    setError("");
    api.tests()
      .then(({ tests: savedTests }) => {
        if (!active) return;
        setTeacherTests([...savedTests].sort(
          (left, right) => new Date(right.created_at) - new Date(left.created_at)
        ));
      })
      .catch((loadError) => {
        if (active) setError(`Tests could not be loaded: ${loadError.message}`);
      })
      .finally(() => {
        if (active) setTeacherTestsBusy(false);
      });
    return () => { active = false; };
  }, [page]);

  useEffect(() => {
    if (page !== "Classroom Quiz") return undefined;
    if (!classroomState?.running && classroomState?.state === "ended") return undefined;
    let active = true;
    let inFlight = false;
    let timer = null;
    setClassroomPollError("");
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      const requestVersion = classroomStatusVersionRef.current;
      try {
        const status = await api.classroom();
        if (active && requestVersion === classroomStatusVersionRef.current) {
          setClassroomState(status);
          setClassroomPollError("");
          if (!status.running && status.state === "ended" && timer) {
            window.clearInterval(timer);
            if (classroomPollTimerRef.current === timer) classroomPollTimerRef.current = null;
          }
        }
      } catch {
        if (active && requestVersion === classroomStatusVersionRef.current) {
          setClassroomPollError("Lost connection to the quiz. Retrying…");
        }
      } finally {
        inFlight = false;
      }
    };
    timer = window.setInterval(poll, 2000);
    classroomPollTimerRef.current = timer;
    void poll();
    return () => {
      active = false;
      window.clearInterval(timer);
      if (classroomPollTimerRef.current === timer) classroomPollTimerRef.current = null;
    };
  }, [page, classroomState?.running, classroomState?.state]);

  useEffect(() => {
    if (page === "Test Builder" && testDatasetId === null) {
      setTestDatasetId(questionDatasetId);
    }
  }, [page, questionDatasetId, testDatasetId]);

  useEffect(() => {
    if (page !== "Item Analysis") return;
    if (!teacherTests.length) {
      if (analysisTestId) setAnalysisTestId("");
      return;
    }
    if (!teacherTests.some((test) => test.id === analysisTestId)) {
      setAnalysisTestId(teacherTests[0].id);
    }
  }, [page, analysisTestId, teacherTests]);

  useEffect(() => {
    if (page !== "Classroom Quiz" || !teacherTests.length) return;
    if (!teacherTests.some((test) => test.id === classroomTestId)) {
      setClassroomTestId(teacherTests[0].id);
    }
  }, [page, classroomTestId, teacherTests]);

  useEffect(() => {
    if (page !== "Item Analysis") return;
    if (!analysisTestId) {
      analysisRequestVersion.current += 1;
      setTestAnalysis(null);
      setTestAnalysisBusy(false);
      return;
    }
    void loadTestAnalysis(analysisTestId);
  }, [page, analysisTestId]);

  useEffect(() => {
    document.documentElement.dataset.appearance = settings.appearance;
    document.title = "Clinthinker©";
    const themeColors = { orange: "#100d0a", pink: "#fff8fc", regal: "#171225", cmu: "#f6f9fc" };
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      themeColors[settings.appearance] || themeColors.orange
    );
  }, [settings.appearance]);

  const addFiles = (fileList) => {
    const selected = Array.from(fileList || []);
    const accepted = selected.filter((file) => /\.(pdf|docx|txt)$/i.test(file.name));
    if (accepted.length !== selected.length) {
      setError("Only PDF, DOCX, and TXT course materials are supported.");
    } else {
      setError("");
    }
    if (!accepted.length) return;
    setQueuedFiles((current) => {
      const fresh = accepted.filter((file) => !current.some(
        (item) => item.name === file.name && item.size === file.size
      ));
      return [...current, ...fresh.map((file) => ({
        id: crypto.randomUUID(),
        name: file.name,
        bytes: file.size,
        file,
        saved: false
      }))];
    });
  };

  const includeSavedFile = async (upload) => {
    if (queuedFiles.some((item) => item.savedId === upload.id)) return;
    setError("");
    try {
      const savedFile = await api.savedMaterial(upload.id);
      setQueuedFiles((current) => current.some((item) => item.savedId === upload.id)
        ? current
        : [...current, {
          id: crypto.randomUUID(),
          savedId: upload.id,
          name: savedFile.name,
          bytes: upload.bytes,
          text: savedFile.text,
          saved: true
        }]);
    } catch (loadError) {
      setError(`Could not load ${upload.name}: ${loadError.message}`);
    }
  };

  const removeUpload = async (upload) => {
    if (!window.confirm(`Delete ${upload.name} from this device?`)) return;
    setError("");
    try {
      await api.deleteUpload(upload.id);
      setUploads((current) => current.filter((item) => item.id !== upload.id));
      if (lessonUploads.some((lesson) => lesson.id === upload.id)) {
        const remainingLessons = lessonUploads.filter((lesson) => lesson.id !== upload.id);
        setLessonUploads(remainingLessons);
        setQuestionResult(null);
        setQuestionAnswers({});
        setQuestionExplanations({});
        setQuestionAttemptResults({});
        setSelectedQuestionAnswers({});
        setQuestionsSaved(false);
        if (remainingLessons.length) {
          await generateQuestions({ lessons: remainingLessons, topic: selectedPracticeTopic || "All Topics" });
        } else {
          setLessonProgress(null);
        }
      }
      knownQuestionUploadIds.current.delete(upload.id);
      setQueuedFiles((current) => current.filter((item) => item.savedId !== upload.id));
      setQuestionUploadIds((current) => current.filter((id) => id !== upload.id));
      setSelectedTrainingUploads((current) => current.filter((id) => id !== upload.id));
      setQuestionUploadIds((current) => current.filter((id) => id !== upload.id));
      setTrainingLabels((current) => {
        const next = { ...current };
        delete next[upload.id];
        return next;
      });
      setNotice("File deleted from local storage.");
    } catch (deleteError) {
      setError(`Could not delete ${upload.name}: ${deleteError.message}`);
    }
  };

  const setUploadExam = async (upload, isExam) => {
    setError("");
    try {
      const updated = await api.setUploadExam(upload.id, isExam);
      setUploads((current) => current.map((item) => item.id === upload.id
        ? { ...item, is_exam: updated.is_exam }
        : item));
    } catch (updateError) {
      setError(`Could not update ${upload.name}: ${updateError.message}`);
    }
  };

  const refreshTrainingDatasets = async () => {
    const savedDatasets = await api.trainingDatasets();
    setDatasets(savedDatasets);
    return savedDatasets;
  };

  const checkForUpdates = async () => {
    setUpdateCheckBusy(true);
    setUpdateState("");
    try {
      const update = await api.checkForUpdates();
      setUpdateOffer(update.available ? update : null);
    } catch {
      setUpdateOffer(null);
    } finally {
      setUpdateCheckBusy(false);
    }
  };

  const installUpdate = async () => {
    if (!updateOffer) return;
    setUpdateState("downloading");
    setUpdateFailureMessage("");
    setUpdateInstallMessage("");
    try {
      await api.installUpdate();
      setUpdateInstallMessage("Installing update. The app will close and restart.");
      setUpdateState("installing");
    } catch (installError) {
      setUpdateState("failed");
      setUpdateFailureMessage(
        installError?.status
          ? installError.message
          : "The update service could not be reached. Check the app connection and try again."
      );
    }
  };

  const uploadTrainingFiles = async (fileList) => {
    const selected = Array.from(fileList || []);
    const accepted = selected.filter((file) => /\.(pdf|docx|txt)$/i.test(file.name));
    if (accepted.length !== selected.length) {
      setError("Training documents must be PDF, DOCX, or TXT files.");
      return;
    }
    setTrainingBusy(true);
    setError("");
    setNotice("");
    try {
      for (const file of accepted) await api.uploadMaterial(file);
      syncSavedUploads(await api.uploads());
      setNotice(`${accepted.length} document${accepted.length === 1 ? "" : "s"} saved for labeling.`);
    } catch (uploadError) {
      setError(`Training document upload failed: ${uploadError.message}`);
      try {
        syncSavedUploads(await api.uploads());
      } catch (refreshError) {
        setError((current) => `${current} Saved-file list could not refresh: ${refreshError.message}`);
      }
    } finally {
      setTrainingBusy(false);
    }
  };

  const importTrainingCsv = async (file) => {
    if (!file) return;
    setTrainingBusy(true);
    setError("");
    setNotice("");
    try {
      const requestedName = trainingDatasetName.trim();
      const dataset = await api.importTrainingCsv(file, requestedName);
      await refreshTrainingDatasets();
      setSelectedDatasetId(dataset.id);
      setQuestionDatasetId(dataset.id);
      setTrainingDatasetName("");
      const detected = dataset.detected;
      const details = detected
        ? ` Topic column: ${detected.topic_column}. Text column: ${detected.text_column}.`
          + (detected.rows_skipped ? ` ${detected.rows_skipped} incomplete rows skipped.` : "")
          + (detected.rows_repaired ? ` ${detected.rows_repaired} rows with extra separators were joined back into the text.` : "")
          + (detected.columns_guessed ? " The columns were guessed from the data, so check that this is right." : "")
        : "";
      setNotice((requestedName
        ? `Imported ${dataset.example_count} labeled rows across ${dataset.topic_count} topics.`
        : `Dataset "${dataset.name}" created from the file name (${dataset.example_count} rows, ${dataset.topic_count} topics).`) + details);
    } catch (importError) {
      setError(`CSV dataset could not be imported: ${importError.message}`);
    } finally {
      setTrainingBusy(false);
    }
  };

  const createDocumentTrainingDataset = async () => {
    if (!trainingDatasetName.trim()) {
      setError("Enter a name for this dataset.");
      setNotice("");
      return;
    }
    const examples = selectedTrainingUploads.map((uploadId) => ({
      upload_id: uploadId,
      topic: (trainingLabels[uploadId] || "").trim()
    }));
    if (examples.length < 2 || new Set(examples.map((item) => item.topic).filter(Boolean)).size < 2) {
      setError("Choose at least two documents and assign at least two different topic labels.");
      return;
    }
    setTrainingBusy(true);
    setError("");
    setNotice("");
    try {
      const dataset = await api.createDocumentDataset({
        name: trainingDatasetName.trim(),
        examples
      });
      await refreshTrainingDatasets();
      setSelectedDatasetId(dataset.id);
      setQuestionDatasetId(dataset.id);
      setTrainingDatasetName("");
      setSelectedTrainingUploads([]);
      setNotice(`Created training dataset with ${dataset.example_count} labeled documents.`);
    } catch (createError) {
      setError(`Document dataset could not be created: ${createError.message}`);
    } finally {
      setTrainingBusy(false);
    }
  };

  const removeTrainingDataset = async (dataset) => {
    if (!window.confirm(`Delete the training dataset "${dataset.name}"? This does not delete your uploaded files.`)) return;
    setTrainingBusy(true);
    setError("");
    try {
      await api.deleteTrainingDataset(dataset.id);
      const remaining = await refreshTrainingDatasets();
      if (selectedDatasetId === dataset.id) setSelectedDatasetId("builtin");
      if (questionDatasetId === dataset.id) {
        setQuestionDatasetId("builtin");
        setQuestionForm((current) => ({ ...current, topic: "All Topics" }));
      }
      setNotice(`Training dataset "${dataset.name}" deleted.`);
      return remaining;
    } catch (deleteError) {
      setError(`Training dataset could not be deleted: ${deleteError.message}`);
    } finally {
      setTrainingBusy(false);
    }
  };

  const analyze = async () => {
    if (busy) return;
    if (!queuedFiles.length) {
      setError("Upload at least one PDF, DOCX, or TXT file to begin.");
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    setProgress([]);
    try {
      const materials = [];
      for (const item of queuedFiles) {
        if (item.saved) {
          materials.push(item);
          continue;
        }
        const uploaded = await api.uploadMaterial(item.file);
        const savedItem = { ...item, saved: true, savedId: uploaded.id, text: uploaded.text };
        materials.push(savedItem);
        setQueuedFiles((current) => current.map(
          (queued) => queued.id === item.id ? savedItem : queued
        ));
      }
      const savedUploads = await api.uploads();
      syncSavedUploads(savedUploads);
      setQueuedFiles(materials);
      const analyzedUploadIds = materials
        .map((item) => item.savedId || item.id)
        .filter((id) => savedUploads.some((upload) => upload.id === id));
      const text = materials.map((item) => item.text).filter(Boolean).join("\n\n");
      if (!text.trim()) throw new Error("No readable text was found in the selected files.");
      const result = await api.predict({ text, training_dataset_id: selectedDatasetId }, (event) => {
        setProgress((current) => {
          const order = ["extraction", "cleaning", "features", "analysis"];
          const index = order.indexOf(event.phase);
          const phases = [
            ["extraction", "Text extraction complete"],
            ["cleaning", "Text cleaning complete"],
            ["features", "Feature extraction complete"],
            ["analysis", "Topic analysis"]
          ];
          return phases.map(([phase, label], phaseIndex) => ({
            phase,
            label,
            state: phaseIndex < index || (phaseIndex === index && phase !== "analysis")
              ? "done"
              : phaseIndex === index ? "active" : "pending"
          }));
        });
      });
      setLatest(result);
      setLatestSourceUploadIds(analyzedUploadIds);
      setProgress((current) => current.map((item) => ({ ...item, state: "done" })));
      setNotice("Analysis finished. Your result is saved on this device.");
    } catch (analysisError) {
      setError(`Analysis could not be completed: ${analysisError.message}`);
      setProgress([]);
      try {
        setUploads(await api.uploads());
      } catch (refreshError) {
        setError((current) => `${current} Uploaded-file list could not refresh: ${refreshError.message}`);
      }
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async () => {
    setSettingsBusy(true);
    setError("");
    try {
      const saved = await api.saveSettings({
        appearance: settings.appearance,
        question_generation: {
          training_dataset_id: questionDatasetId,
          upload_ids: uploads.every((upload) => questionUploadIds.includes(upload.id))
            ? null
            : questionUploadIds,
          topic: "All Topics",
          question_type: questionForm.question_type,
          difficulty: "Moderate",
          number_of_questions: Number(questionForm.number_of_questions),
          questions_per_topic: Number(questionForm.questions_per_topic),
          similarity_threshold: Number(questionForm.similarity_threshold) / 100,
          allow_repeats: Boolean(questionForm.allow_repeats),
          priority_weights: Object.fromEntries(
            Object.entries(questionForm.weights).map(([key, value]) => [key, Number(value) / 100])
          )
        }
      });
      setSettings({
        appearance: saved.appearance || initialSettings.appearance
      });
      setNotice("Preferences and question-generation settings saved locally.");
    } catch (saveError) {
      setError(`Preferences could not be saved: ${saveError.message}`);
    } finally {
      setSettingsBusy(false);
    }
  };

  const submitStudyAnswer = async (questionId, answer, generationId = null) => {
    setError("");
    setNotice("");
    try {
      const result = await api.submitAnswer(questionId, answer, generationId);
      await refreshStudyProgress();
      return result;
    } catch (answerError) {
      if (answerError.status === 410) setQuestionSetUnavailable(true);
      setError(answerError.message);
      return null;
    }
  };

  const checkGeneratedAnswer = async (item) => {
    const answer = selectedQuestionAnswers[item.id];
    if (answer === undefined || answer.trim() === "") return;
    const version = answerStateVersion.current;
    setCheckingQuestionId(item.id);
    try {
      const result = await submitStudyAnswer(item.id, answer, questionResult?.generation_id);
      if (result && version === answerStateVersion.current) {
        setQuestionAttemptResults((current) => ({ ...current, [item.id]: result }));
      }
    } finally {
      if (version === answerStateVersion.current) setCheckingQuestionId(null);
    }
  };

  const clearStudyProgress = async () => {
    if (!window.confirm("Delete all your answers, mastery scores and review schedule? Your lessons, saved questions and training data are kept.")) return false;
    setError("");
    setNotice("");
    try {
      const result = await api.clearProgress();
      answerStateVersion.current += 1;
      setQuestionAttemptResults({});
      setSelectedQuestionAnswers({});
      setCheckingQuestionId(null);
      setNotice(`Deleted ${result.attempts_deleted} answer${result.attempts_deleted === 1 ? "" : "s"} and ${result.questions_deleted} tracked question${result.questions_deleted === 1 ? "" : "s"}.`);
      await refreshStudyProgress();
      return true;
    } catch (clearError) {
      setError(`Study progress could not be reset: ${clearError.message}`);
      return false;
    }
  };

  const generateQuestions = async ({
    lessons: lessonOverride = lessonUploads,
    useStyle = useExamStyle,
    topic = "All Topics",
    trainingDatasetId = questionDatasetId
  } = {}) => {
    setError("");
    setNotice("");
    setSelectedPracticeTopic(topic === "All Topics" ? null : topic);
    const selectedLessons = lessonOverride.filter((lesson) => lesson.status === "Ready");
    const useLesson = selectedLessons.length > 0;
    const uploadIds = useLesson
      ? selectedLessons.map((lesson) => lesson.id)
      : questionUploadIds;
    if (!uploadIds.length) {
      setError("Select at least one saved course material as a grounded source.");
      return null;
    }
    setQuestionBusy(true);
    answerStateVersion.current += 1;
    setQuestionSetUnavailable(false);
    if (useLesson) {
      setLessonProgress({
        phase: "generating",
        message: `Generating questions from ${selectedLessons.length} lesson${selectedLessons.length === 1 ? "" : "s"}...`
      });
    }
    setQuestionAnswers({});
    setQuestionExplanations({});
    setQuestionAttemptResults({});
    setSelectedQuestionAnswers({});
    setQuestionsSaved(false);
    try {
      const result = await api.generateQuestions({
        training_dataset_id: trainingDatasetId,
        upload_ids: uploadIds,
        lesson_upload_id: useLesson && selectedLessons.length === 1
          ? selectedLessons[0].id
          : null,
        lesson_upload_ids: useLesson ? uploadIds : [],
        lesson_only: useLesson,
        use_exam_style: useStyle,
        topic,
        question_type: questionForm.question_type,
        difficulty: "Moderate",
        number_of_questions: Number(questionForm.number_of_questions),
        questions_per_topic: Number(questionForm.questions_per_topic),
        similarity_threshold: Number(questionForm.similarity_threshold) / 100,
        allow_repeats: Boolean(questionForm.allow_repeats),
        priority_weights: Object.fromEntries(
          Object.entries(questionForm.weights).map(([key, value]) => [key, Number(value) / 100])
        )
      });
      setQuestionResult(result);
      if (useLesson) {
        setNotice(
          `Generated ${result.questions.length} of ${result.requested_count} requested. Skipped: `
          + `${result.diagnostics.skipped_low_confidence || 0} low-confidence, `
          + `${result.diagnostics.no_valid_distractors || 0} no valid distractors.`
        );
      } else if (result.shortfall > 0) {
        setNotice(
          `Generated ${result.questions.length} supported question${result.questions.length === 1 ? "" : "s"}`
          + `; ${result.shortfall} of `
          + `${result.requested_count} requested could not be supported by the selected source.`
        );
      } else if (result.questions.length) {
        setNotice(`${result.questions.length} supported practice question${result.questions.length === 1 ? "" : "s"} generated.`);
      } else {
        setNotice("");
      }
      if (useLesson) {
        setLessonProgress({
          phase: "done",
          message: `Done — ${result.questions.length} question${result.questions.length === 1 ? "" : "s"} generated from ${selectedLessons.length} lesson${selectedLessons.length === 1 ? "" : "s"}.`
        });
      }
      return result;
    } catch (generationError) {
      setError(generationError.status === 422
        ? generationError.message
        : `Questions could not be generated: ${generationError.message}`);
      if (useLesson) {
        setLessonProgress({
          phase: "error",
          message: `Question generation from ${selectedLessons.length} lesson${selectedLessons.length === 1 ? "" : "s"} did not complete.`
        });
      }
      return null;
    } finally {
      setQuestionBusy(false);
    }
  };

  const practiceProgressTopic = (topic) => {
    setPage("Generate Practice Questions");
    setMenuOpen(false);
    setQuestionResult(null);
    setQuestionAnswers({});
    setQuestionExplanations({});
    setQuestionsSaved(false);
    void generateQuestions({ topic });
  };

  const practiceAnalyzedTopic = (topic) => {
    const analyzedLessons = latestSourceUploadIds
      .map((id) => uploads.find((upload) => upload.id === id))
      .filter(Boolean)
      .map((upload) => ({ ...upload, status: "Ready" }));
    if (!analyzedLessons.length) {
      setError("The files used for this analysis are no longer available.");
      return;
    }
    const datasetId = latest?.training_dataset_id || selectedDatasetId;
    setQuestionDatasetId(datasetId);
    setQuestionUploadIds(analyzedLessons.map((lesson) => lesson.id));
    setLessonUploads(analyzedLessons);
    setPage("Generate Practice Questions");
    setMenuOpen(false);
    setQuestionResult(null);
    setQuestionAnswers({});
    setQuestionExplanations({});
    setQuestionAttemptResults({});
    setSelectedQuestionAnswers({});
    setQuestionsSaved(false);
    void generateQuestions({
      lessons: analyzedLessons,
      topic,
      trainingDatasetId: datasetId
    });
  };

  const buildTestFromAnalyzedFiles = () => {
    const analyzedUploads = latestSourceUploadIds
      .map((id) => uploads.find((upload) => upload.id === id))
      .filter(Boolean);
    if (!analyzedUploads.length) {
      setError("The files used for this analysis are no longer available.");
      return;
    }
    const datasetId = latest?.training_dataset_id || selectedDatasetId;
    setTestTitle(analyzedUploads
      .map((upload) => upload.name.replace(/\.[^.]+$/, ""))
      .join(" & ")
      .slice(0, 120));
    setTestLessonUploadIds(analyzedUploads.map((upload) => upload.id));
    setTestDatasetId(datasetId);
    setBuiltTest(null);
    setError("");
    setNotice("");
    setPage("Test Builder");
    setMenuOpen(false);
  };

  const buildTeacherTest = async (itemsPerTopic = null) => {
    const title = testTitle.trim();
    const totalItems = Number(testItemCount);
    if (!title) {
      setError("Enter a title for the test.");
      return null;
    }
    if (!Number.isInteger(totalItems) || totalItems < 5 || totalItems > 100) {
      setError("Number of items must be a whole number from 5 to 100.");
      return null;
    }
    if (!testLessonUploadIds.length) {
      setError("Select at least one lesson for the test.");
      return null;
    }
    if (!testQuestionTypes.length) {
      setError("Select at least one question type.");
      return null;
    }
    setTestBuildBusy(true);
    setError("");
    setNotice("");
    const payload = {
      title,
      training_dataset_id: testDatasetId || questionDatasetId,
      lesson_upload_ids: testLessonUploadIds,
      total_items: totalItems,
      question_types: testQuestionTypes,
      include_set_b: testIncludeSetB
    };
    if (itemsPerTopic) payload.items_per_topic = itemsPerTopic;
    try {
      const result = await api.buildTest(payload);
      setBuiltTest(result);
      setTestTitle(result.title);
      setTestItemCount(result.total_items);
      setSpecItemCounts(Object.fromEntries(
        result.specification.rows.map((row) => [row.topic, String(row.items)])
      ));
      setTestTab("specification");
      setPreviewSet("A");
      setShowTestAnswers(false);
      setNotice(`Test "${result.title}" built with ${result.total_items} items.`);
      await refreshTeacherTests();
      return result;
    } catch (buildError) {
      setError(`Test could not be built: ${buildError.message}`);
      return null;
    } finally {
      setTestBuildBusy(false);
    }
  };

  const renameTeacherTest = async (id, title) => {
    if (!title.trim()) {
      setError("Test title cannot be empty.");
      return false;
    }
    setError("");
    try {
      const updated = await api.renameTest(id, title.trim());
      setTeacherTests((current) => current.map((item) => (
        item.id === id ? { ...item, title: updated.title } : item
      )));
      setBuiltTest((current) => current?.id === id
        ? { ...current, title: updated.title }
        : current);
      setNotice("Test renamed.");
      return true;
    } catch (renameError) {
      setError(`Test could not be renamed: ${renameError.message}`);
      return false;
    }
  };

  const deleteTeacherTest = async (savedTest) => {
    if (!window.confirm(`Delete "${savedTest.title}" and its test materials?`)) return;
    setError("");
    try {
      await api.deleteTest(savedTest.id);
      const remaining = teacherTests.filter((item) => item.id !== savedTest.id);
      setTeacherTests(remaining);
      if (builtTest?.id === savedTest.id) setBuiltTest(null);
      if (analysisTestId === savedTest.id) setAnalysisTestId(remaining[0]?.id || "");
      setNotice(`Test "${savedTest.title}" deleted.`);
    } catch (deleteError) {
      setError(`Test could not be deleted: ${deleteError.message}`);
    }
  };

  const startClassroomQuiz = async (testId, setMode) => {
    if (!testId) {
      setError("Choose a saved test before starting the quiz.");
      return;
    }
    setClassroomBusy(true);
    setError("");
    setNotice("");
    setClassroomPollError("");
    setClassroomCopyNotice("");
    try {
      const result = await api.startClassroom(testId, setMode);
      classroomStatusVersionRef.current += 1;
      setClassroomState(result);
      setClassroomEndResult(null);
    } catch (startError) {
      setError(startError.message);
    } finally {
      setClassroomBusy(false);
    }
  };

  const endClassroomQuiz = async (save) => {
    if (!classroomState?.running) return;
    const notSubmitted = Math.max(
      0,
      Number(classroomState.joined || 0) - Number(classroomState.submitted || 0)
    );
    if (save && notSubmitted) {
      const studentWord = notSubmitted === 1 ? "student hasn't" : "students haven't";
      if (!window.confirm(
        `${notSubmitted} ${studentWord} submitted. End the quiz anyway? Their answers won't be saved.`
      )) return;
    }
    if (!save && !window.confirm("Cancel the classroom quiz? Student answers will not be saved.")) return;
    setClassroomBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.endClassroom(save);
      classroomStatusVersionRef.current += 1;
      if (classroomPollTimerRef.current) {
        window.clearInterval(classroomPollTimerRef.current);
        classroomPollTimerRef.current = null;
      }
      setClassroomEndResult(result);
      setClassroomState((current) => current ? {
        ...current,
        running: false,
        state: "ended",
        joined: result.joined ?? current.joined,
        submitted: result.submitted,
        students: current.students
      } : current);
    } catch (endError) {
      setError(endError.message);
    } finally {
      setClassroomBusy(false);
    }
  };

  const copyClassroomAddress = async (address) => {
    try {
      await navigator.clipboard.writeText(address);
      setClassroomCopyNotice("Address copied.");
      setError("");
    } catch {
      setClassroomCopyNotice("");
      setError("Could not copy the student address. Select and copy it manually.");
    }
  };

  const openClassroomForTest = (testId) => {
    setClassroomTestId(testId);
    setClassroomEndResult(null);
    setClassroomCopyNotice("");
    setError("");
    setNotice("");
    setPage("Classroom Quiz");
    setMenuOpen(false);
  };

  const openClassroomAnalysis = () => {
    const testId = classroomEndResult?.test_id || classroomState?.test_id;
    if (!testId) {
      setError("The classroom quiz test could not be identified.");
      return;
    }
    setAnalysisTestId(testId);
    setError("");
    setNotice("");
    setPage("Item Analysis");
    setMenuOpen(false);
  };

  const importTeacherTestResults = async (id, file) => {
    if (!id || !file) return;
    setTestResultsBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.importTestResults(id, file);
      const setCounts = Object.entries(result.sets || {})
        .map(([label, count]) => `Set ${label}: ${count}`)
        .join(", ");
      setNotice(
        `Imported results for ${result.students} students${setCounts ? ` (${setCounts})` : ""}.`
        + (result.warnings?.length ? ` ${result.warnings.join(" ")}` : "")
      );
      await refreshTeacherTests();
      await loadTestAnalysis(id);
    } catch (importError) {
      setError(`Results could not be imported: ${importError.message}`);
    } finally {
      setTestResultsBusy(false);
    }
  };

  const downloadTeacherFile = async (request, description) => {
    setError("");
    try {
      const { blob, filename } = await request();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(`${description} could not be downloaded: ${downloadError.message}`);
    }
  };

  const uploadLessons = async (fileList) => {
    const selectedFiles = Array.from(fileList || []);
    if (!selectedFiles.length) return;
    const accepted = selectedFiles.filter((file) => /\.(pdf|docx|txt)$/i.test(file.name));
    const rejected = selectedFiles.filter((file) => !accepted.includes(file));
    const rejectedLessons = rejected.map((file) => ({
      id: `error-${crypto.randomUUID()}`,
      name: file.name,
      bytes: file.size,
      status: "Error",
      error: "Unsupported file type"
    }));
    if (rejectedLessons.length) {
      setLessonUploads((current) => [...current, ...rejectedLessons]);
    }
    if (!accepted.length) {
      setError("Lessons must be PDF, DOCX, or TXT files.");
      return;
    }
    setLessonUploadBusy(true);
    setError("");
    setNotice("");
    setQuestionResult(null);
    setQuestionAnswers({});
    setQuestionExplanations({});
    setQuestionAttemptResults({});
    setSelectedQuestionAnswers({});
    setQuestionsSaved(false);
    let nextLessons = [...lessonUploads, ...rejectedLessons];
    const uploadErrors = rejected.map((file) => `${file.name}: unsupported file type`);
    for (const file of accepted) {
      const pendingId = `pending-${crypto.randomUUID()}`;
      const pendingLesson = {
        id: pendingId,
        name: file.name,
        bytes: file.size,
        status: "Uploading"
      };
      nextLessons = [...nextLessons, pendingLesson];
      setLessonUploads(nextLessons);
      setLessonProgress({
        phase: "uploading",
        message: `Uploading ${file.name}...`
      });
      try {
        const savedLesson = await api.uploadLesson(file);
        nextLessons = nextLessons.map((lesson) => (
          lesson.id === pendingId
            ? { ...lesson, status: "Reading" }
            : lesson
        ));
        setLessonUploads(nextLessons);
        setLessonProgress({
          phase: "reading",
          message: `Reading ${file.name} — ${savedLesson.text_chars.toLocaleString()} characters extracted.`
        });
        await new Promise((resolve) => window.requestAnimationFrame(resolve));
        const readyLesson = {
          id: savedLesson.id,
          name: savedLesson.name,
          bytes: savedLesson.bytes,
          status: "Ready"
        };
        const priorIndex = nextLessons.findIndex(
          (lesson) => lesson.id === savedLesson.id
        );
        nextLessons = nextLessons.filter((lesson) => lesson.id !== pendingId);
        if (priorIndex >= 0 && savedLesson.id !== pendingId) {
          const existingIndex = nextLessons.findIndex(
            (lesson) => lesson.id === savedLesson.id
          );
          if (existingIndex >= 0) nextLessons[existingIndex] = readyLesson;
          else nextLessons.push(readyLesson);
        } else if (!nextLessons.some((lesson) => lesson.id === savedLesson.id)) {
          nextLessons.push(readyLesson);
        }
        setLessonUploads(nextLessons);
      } catch (uploadError) {
        nextLessons = nextLessons.map((lesson) => (
          lesson.id === pendingId
            ? { ...lesson, status: "Error", error: uploadError.message }
            : lesson
        ));
        setLessonUploads(nextLessons);
        uploadErrors.push(`${file.name}: ${uploadError.message}`);
      }
    }
    try {
      const readyLessons = nextLessons.filter((lesson) => lesson.status === "Ready");
      if (readyLessons.length) {
        try {
          syncSavedUploads(
            await api.uploads(),
            readyLessons.map((lesson) => lesson.id)
          );
        } catch (refreshError) {
          uploadErrors.push(`Saved upload list could not refresh: ${refreshError.message}`);
        }
        await generateQuestions({ lessons: readyLessons, topic: selectedPracticeTopic || "All Topics" });
      }
    } finally {
      setLessonUploadBusy(false);
    }
    if (uploadErrors.length) {
      setError(`Some lesson files could not be added: ${uploadErrors.join("; ")}`);
    }
  };

  const removeLessonFromSetup = (lessonId) => {
    const remainingLessons = lessonUploads.filter((lesson) => lesson.id !== lessonId);
    setLessonUploads(remainingLessons);
    setQuestionResult(null);
    setQuestionAnswers({});
    setQuestionExplanations({});
    setQuestionAttemptResults({});
    setSelectedQuestionAnswers({});
    setQuestionsSaved(false);
    if (remainingLessons.some((lesson) => lesson.status === "Ready")) {
      void generateQuestions({ lessons: remainingLessons, topic: selectedPracticeTopic || "All Topics" });
    } else {
      setLessonProgress(null);
    }
  };

  const changeExamStyle = (enabled) => {
    setUseExamStyle(enabled);
    if (lessonUploads.some((lesson) => lesson.status === "Ready")) {
      void generateQuestions({
        lessons: lessonUploads,
        useStyle: enabled,
        topic: selectedPracticeTopic || "All Topics"
      });
    }
  };

  const saveGeneratedQuestions = async () => {
    if (!questionResult?.questions?.length) return;
    setQuestionBusy(true);
    setError("");
    try {
      const result = await api.saveQuestions(
        questionResult.generation_id,
        questionResult.questions.map((item) => item.id)
      );
      setQuestionsSaved(true);
      setNotice(`${result.saved_count} question${result.saved_count === 1 ? "" : "s"} saved on this device.`);
    } catch (saveError) {
      setError(`Questions could not be saved: ${saveError.message}`);
      if (saveError.status === 410) setQuestionSetUnavailable(true);
    } finally {
      setQuestionBusy(false);
    }
  };

  const revealGeneratedAnswers = async () => {
    if (!questionResult?.questions?.length) return;
    if (Object.keys(questionAnswers).length) {
      setQuestionAnswers({});
      setQuestionExplanations({});
      return;
    }
    setQuestionBusy(true);
    setError("");
    try {
      const result = await api.revealQuestionAnswers(
        questionResult.generation_id,
        questionResult.questions.map((item) => item.id)
      );
      setQuestionAnswers(result.answers);
      setQuestionExplanations(result.explanations || {});
    } catch (answerError) {
      setError(`Answer key could not be loaded: ${answerError.message}`);
      if (answerError.status === 410) setQuestionSetUnavailable(true);
    } finally {
      setQuestionBusy(false);
    }
  };

  const rateQuestion = async (item, rating, generationId = null) => {
    setError("");
    try {
      const preferences = await api.rateQuestion(item.id, rating, generationId);
      setQuestionPreferences(preferences);
      setQuestionResult((current) => current && generationId === current.generation_id
        ? {
          ...current,
          questions: current.questions.map((question) => question.id === item.id
            ? { ...question, feedback_rating: rating } : question)
        }
        : current);
      setSavedQuestions((current) => current.map((session) => ({
        ...session,
        questions: session.questions.map((question) => question.id === item.id
          ? { ...question, feedback_rating: rating } : question)
      })));
    } catch (feedbackError) {
      setError(`Question feedback could not be saved: ${feedbackError.message}`);
    }
  };

  const resetQuestionPreferences = async () => {
    if (!window.confirm("Clear all question ratings and reset your global preferences?")) return;
    setError("");
    try {
      setQuestionPreferences(await api.clearQuestionPreferences());
      setQuestionResult((current) => current ? {
        ...current,
        questions: current.questions.map((question) => ({ ...question, feedback_rating: null }))
      } : current);
      setSavedQuestions((current) => current.map((session) => ({
        ...session,
        questions: session.questions.map((question) => ({ ...question, feedback_rating: null }))
      })));
      setNotice("Question preferences were reset.");
    } catch (resetError) {
      setError(`Question preferences could not be reset: ${resetError.message}`);
    }
  };

  const resetQuestionHistory = async () => {
    const selectedLessons = lessonUploads.filter((lesson) => lesson.status === "Ready");
    if (!selectedLessons.length) return;
    if (!window.confirm(
      "Reset excerpt usage for the selected lessons? Saved questions will be kept."
    )) return;
    setError("");
    setNotice("");
    setQuestionBusy(true);
    try {
      await api.resetQuestionHistory(
        selectedLessons.map((lesson) => lesson.id)
      );
      setNotice(
        `Question history was reset for ${selectedLessons.length} lesson${selectedLessons.length === 1 ? "" : "s"}.`
      );
    } catch (resetError) {
      setError(`Question history could not be reset: ${resetError.message}`);
    } finally {
      setQuestionBusy(false);
    }
  };

  const revealSavedAnswers = async (sessionIds = savedQuestions.map((session) => session.id)) => {
    const unloadedSessionIds = sessionIds.filter(
      (sessionId) => !savedAnswersLoadedSessions.includes(sessionId)
    );
    if (unloadedSessionIds.length) {
      setSavedQuestionsBusy(true);
      setError("");
      try {
        const requestedSessionId = unloadedSessionIds.length === 1
          ? unloadedSessionIds[0] : null;
        const { sessions } = await api.savedQuestions(true, requestedSessionId);
        if (requestedSessionId) {
          const requestedSession = sessions.find((session) => session.id === requestedSessionId);
          if (!requestedSession) throw new Error("Saved question session was not found.");
          setSavedQuestions((current) => current.map((session) =>
            session.id === requestedSessionId ? requestedSession : session
          ));
        } else {
          setSavedQuestions(sessions);
        }
        setSavedAnswersLoadedSessions((current) => [
          ...new Set([...current, ...unloadedSessionIds])
        ]);
      } catch (answerError) {
        setError(`Saved answer key could not be loaded: ${answerError.message}`);
        setSavedQuestionsBusy(false);
        return;
      }
      setSavedQuestionsBusy(false);
    }
    setSavedAnswerSessions((current) => [...new Set([...current, ...sessionIds])]);
  };

  const toggleSavedSessionAnswers = (sessionId) => {
    if (savedAnswerSessions.includes(sessionId)) {
      setSavedAnswerSessions((current) => current.filter((id) => id !== sessionId));
      return;
    }
    revealSavedAnswers([sessionId]);
  };

  const toggleAllSavedAnswers = () => {
    const sessionsWithQuestions = savedQuestions
      .filter((session) => session.questions.length)
      .map((session) => session.id);
    const allVisible = sessionsWithQuestions.length > 0
      && sessionsWithQuestions.every((id) => savedAnswerSessions.includes(id));
    if (allVisible) setSavedAnswerSessions([]);
    else revealSavedAnswers(sessionsWithQuestions);
  };

  const renameSavedSession = async (session) => {
    const title = window.prompt("Rename this question session:", session.title);
    if (title === null || !title.trim()) return;
    setError("");
    try {
      const updated = await api.renameSavedSession(session.id, title.trim());
      setSavedQuestions((current) => current.map((item) =>
        item.id === session.id ? { ...item, title: updated.title } : item
      ));
    } catch (renameError) {
      setError(`Session could not be renamed: ${renameError.message}`);
    }
  };

  const deleteSavedSession = async (session) => {
    if (!window.confirm(`Delete "${session.title}" and all ${session.question_count} saved questions in it?`)) return;
    setError("");
    try {
      await api.deleteSavedSession(session.id);
      setSavedQuestions((current) => current.filter((item) => item.id !== session.id));
      setExpandedSavedSessions((current) => current.filter((id) => id !== session.id));
      setSavedAnswerSessions((current) => current.filter((id) => id !== session.id));
      setSavedAnswersLoadedSessions((current) => current.filter((id) => id !== session.id));
    } catch (deleteError) {
      setError(`Session could not be deleted: ${deleteError.message}`);
    }
  };

  const exportSavedQuestionsCsv = (session) => {
    if (!session?.questions?.length) return;
    const includeAnswers = savedAnswerSessions.includes(session.id);
    const rows = [
      ["Topic", "Type", "Difficulty", "Priority", "Confidence", "Question", "Choices", "Answer", "Source"],
      ...session.questions.map((item) => [
        item.topic, item.question_type, item.difficulty,
        `${Math.round(item.priority_score * 100)}%`,
        `${Math.round(item.confidence_score * 100)}%`,
        item.question_text, (item.choices || []).join(" | "),
        includeAnswers ? item.correct_answer || "" : "",
        item.source_reference
      ])
    ];
    const csv = "\ufeff" + rows.map((row) => row.map((value) => {
      const text = String(value);
      const safeText = /^[=+\-@]/.test(text) ? `'${text}` : text;
      return `"${safeText.replaceAll('"', '""')}"`;
    }).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    const safeSessionId = String(session.id).replace(/[^a-z0-9_-]/gi, "-");
    anchor.download = `clinthinker-saved-questions-${safeSessionId}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const printSavedQuestions = (session) => {
    setPrintingSavedSessionId(session.id);
  };

  return (
    <div
      className={`app-shell app-window theme-${settings.appearance}${printingSavedSessionId ? " printing-saved-session" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        // On the questions page, dropped files are lessons, so skip the "add course files" overlay.
        if (page !== "Generate Practice Questions") setDragging(true);
      }}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (page === "Generate Practice Questions") {
          if (!busy && !lessonUploadBusy) uploadLessons(event.dataTransfer.files);
        } else {
          addFiles(event.dataTransfer.files);
        }
      }}
    >
      <Sidebar
        active={page}
        classroomRunning={Boolean(classroomState?.running)}
        onNavigate={(next) => {
          setPage(next);
          setMenuOpen(false);
          setError("");
          setNotice("");
          setClassroomCopyNotice("");
        }}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
      />
      <main className="main-area medium-main">
        <header className="topbar">
          <button className="menu-trigger" onClick={() => setMenuOpen(true)}><img className="menu-trigger-icon" src={cmuShieldImage} alt="" /><span>MENU</span></button>
          <div className="mobile-brand"><div className="brand-mark"><BrainCircuit size={17} /></div> Clinthinker©</div>
          <div className="breadcrumb"><span>LOCAL WORKSPACE</span><span className="breadcrumb-sep">/</span><strong>{page}</strong></div>
          <div className="local-status"><span /> OFFLINE · SAVED ON THIS DEVICE</div>
        </header>
        {updateOffer && <div className="app-update-banner">
          <span role={updateState === "failed" ? "alert" : undefined}>
            {updateState === "failed"
              ? updateFailureMessage
              : updateState === "installing"
                ? updateInstallMessage
                : `Version ${updateOffer.version} is available`}
          </span>
          <button
            className="button-dark"
            onClick={installUpdate}
            disabled={updateState === "downloading" || updateState === "installing"}
          >
            {updateState === "downloading"
              ? "Downloading..."
              : updateState === "installing"
                ? "Installing..."
                : updateState === "failed"
                  ? "Retry update"
                  : "Update"}
          </button>
          <button className="button-outline" disabled={updateState === "downloading" || updateState === "installing"} onClick={() => {
            setUpdateOffer(null);
            setUpdateState("");
          }}>Later</button>
        </div>}

        {page === "Upload" && <UploadPage
          uploads={uploads}
          datasets={datasets}
          selectedDatasetId={selectedDatasetId}
          setSelectedDatasetId={setSelectedDatasetId}
          showBuiltInWarning={
            selectedDatasetId === "builtin" && datasets.some((dataset) => dataset.id !== "builtin")
          }
          trainingBusy={trainingBusy}
          queuedFiles={queuedFiles}
          addFiles={addFiles}
          fileInput={fileInput}
          removeQueued={(id) => setQueuedFiles((current) => current.filter((item) => item.id !== id))}
          includeSavedFile={includeSavedFile}
          removeUpload={removeUpload}
          setUploadExam={setUploadExam}
          analyze={analyze}
          busy={busy}
          progress={progress}
          latest={latest}
          onPracticeTopic={practiceAnalyzedTopic}
          onBuildTestFromFiles={buildTestFromAnalyzedFiles}
          error={error}
          notice={notice}
          dragging={dragging}
        />}
        {page === "Training Data" && <TrainingDataPage
          uploads={uploads}
          datasets={datasets}
          selectedDatasetId={selectedDatasetId}
          datasetName={trainingDatasetName}
          setDatasetName={setTrainingDatasetName}
          selectedUploads={selectedTrainingUploads}
          setSelectedUploads={setSelectedTrainingUploads}
          labels={trainingLabels}
          setLabels={setTrainingLabels}
          busy={trainingBusy}
          fileInput={trainingFileInput}
          csvInput={csvInput}
          onImportCsv={importTrainingCsv}
          onCreateDocuments={createDocumentTrainingDataset}
          onRemoveUpload={removeUpload}
          onDeleteDataset={removeTrainingDataset}
          error={error}
          notice={notice}
        />}
        {page === "Saved Questions" && <SavedQuestionsPage
          sessions={savedQuestions}
          busy={savedQuestionsBusy}
          expandedSessions={expandedSavedSessions}
          setExpandedSessions={setExpandedSavedSessions}
          visibleAnswerSessions={savedAnswerSessions}
          onToggleAnswers={toggleSavedSessionAnswers}
          onToggleAllAnswers={toggleAllSavedAnswers}
          onRename={renameSavedSession}
          onDelete={deleteSavedSession}
          onExportCsv={exportSavedQuestionsCsv}
          onExportPdf={printSavedQuestions}
          printingSessionId={printingSavedSessionId}
          onRateQuestion={rateQuestion}
          error={error}
        />}
        {page === "Generate Practice Questions" && <PracticeQuestionsPage
          datasets={datasets}
          uploads={uploads}
          selectedDatasetId={questionDatasetId}
          selectedUploadIds={questionUploadIds}
          lessonUploads={lessonUploads}
          lessonUploadBusy={lessonUploadBusy}
          lessonProgress={lessonProgress}
          useExamStyle={useExamStyle}
          onChangeExamStyle={changeExamStyle}
          lessonUploadInput={lessonFileInput}
          onUploadLessons={uploadLessons}
          onRemoveLesson={removeLessonFromSetup}
          form={questionForm}
          onOpenSettings={() => setPage("Settings")}
          result={questionResult}
          questionSetUnavailable={questionSetUnavailable}
          selectedTopic={selectedPracticeTopic}
          onClearTopic={() => generateQuestions({ topic: "All Topics" })}
          preferences={questionPreferences}
          answers={questionAnswers}
          explanations={questionExplanations}
          selectedAnswers={selectedQuestionAnswers}
          submittedAnswers={questionAttemptResults}
          checkingQuestionId={checkingQuestionId}
          onSelectAnswer={(id, answer) => setSelectedQuestionAnswers((current) => ({ ...current, [id]: answer }))}
          onSubmitAnswer={checkGeneratedAnswer}
          busy={questionBusy}
          saved={questionsSaved}
          onGenerate={selectedPracticeTopic
            ? () => generateQuestions({ topic: selectedPracticeTopic })
            : generateQuestions}
          onSave={saveGeneratedQuestions}
          onRevealAnswers={revealGeneratedAnswers}
          onRateQuestion={rateQuestion}
          onResetPreferences={resetQuestionPreferences}
          onResetQuestionHistory={resetQuestionHistory}
          onBack={() => setPage("Upload")}
          error={error}
          notice={notice}
        />}
        {page === "My Progress" && <MyProgressPage
          data={studyProgress}
          busy={studyProgressBusy}
          error={error}
          notice={notice}
          onNavigate={setPage}
          onAnswer={submitStudyAnswer}
          onRefresh={refreshStudyProgress}
          onClearProgress={clearStudyProgress}
          onError={setError}
          onPracticeTopic={practiceProgressTopic}
        />}
        {page === "Test Builder" && <TestBuilderPage
          uploads={uploads.filter((upload) => !upload.is_exam)}
          datasets={datasets}
          selectedDatasetId={testDatasetId || questionDatasetId}
          setSelectedDatasetId={setTestDatasetId}
          lessonIds={testLessonUploadIds}
          setLessonIds={setTestLessonUploadIds}
          title={testTitle}
          setTitle={setTestTitle}
          itemCount={testItemCount}
          setItemCount={setTestItemCount}
          questionTypes={testQuestionTypes}
          setQuestionTypes={setTestQuestionTypes}
          includeSetB={testIncludeSetB}
          setIncludeSetB={setTestIncludeSetB}
          buildBusy={testBuildBusy}
          openBusy={testOpenBusy}
          tests={teacherTests}
          testsBusy={teacherTestsBusy}
          test={builtTest}
          testResultRef={testResultRef}
          tab={testTab}
          setTab={setTestTab}
          previewSet={previewSet}
          setPreviewSet={setPreviewSet}
          showAnswers={showTestAnswers}
          setShowAnswers={setShowTestAnswers}
          showEmptyTopics={showEmptyTestTopics}
          setShowEmptyTopics={setShowEmptyTestTopics}
          itemCounts={specItemCounts}
          setItemCounts={setSpecItemCounts}
          error={error}
          notice={notice}
          onBuild={buildTeacherTest}
          onOpenTest={loadTeacherTest}
          onRenameTest={renameTeacherTest}
          onDeleteTest={deleteTeacherTest}
          onAnalyzeTest={(id) => {
            setAnalysisTestId(id);
            setPage("Item Analysis");
            setMenuOpen(false);
          }}
          onStartClassroom={openClassroomForTest}
          onUploadClick={() => lessonFileInput.current?.click()}
          onDownload={(id, documentType, setLabel) => downloadTeacherFile(
            () => api.downloadTestExport(id, documentType, setLabel),
            documentType === "test" ? `Set ${setLabel} test paper` : documentType
          )}
          onDownloadTemplate={(id) => downloadTeacherFile(
            () => api.downloadTestResultsTemplate(id),
            "Results template"
          )}
        />}
        {page === "Classroom Quiz" && <ClassroomQuizPage
          tests={teacherTests}
          testsBusy={teacherTestsBusy}
          selectedTestId={classroomTestId}
          onSelectTest={setClassroomTestId}
          session={classroomState}
          endResult={classroomEndResult}
          actionBusy={classroomBusy}
          error={error}
          pollError={classroomPollError}
          notice={notice}
          copyNotice={classroomCopyNotice}
          onStart={startClassroomQuiz}
          onEnd={endClassroomQuiz}
          onCopyAddress={copyClassroomAddress}
          onOpenAnalysis={openClassroomAnalysis}
        />}
        {page === "Item Analysis" && <ItemAnalysisPage
          tests={teacherTests}
          testsBusy={teacherTestsBusy}
          selectedTestId={analysisTestId}
          onSelectTest={setAnalysisTestId}
          analysis={testAnalysis}
          analysisBusy={testAnalysisBusy}
          resultsBusy={testResultsBusy}
          resultsInput={testResultsInput}
          error={error}
          notice={notice}
          onDownloadTemplate={(id) => downloadTeacherFile(
            () => api.downloadTestResultsTemplate(id),
            "Results template"
          )}
        />}
        {page === "Settings" && <SettingsPage
          settings={settings}
          setSettings={setSettings}
          datasets={datasets}
          uploads={uploads}
          selectedDatasetId={questionDatasetId}
          setSelectedDatasetId={(id) => {
            setQuestionDatasetId(id);
            setQuestionForm((current) => ({ ...current, topic: "All Topics" }));
            setQuestionResult(null);
            setQuestionAnswers({});
            setQuestionExplanations({});
            setQuestionAttemptResults({});
            setSelectedQuestionAnswers({});
          }}
          selectedUploadIds={questionUploadIds}
          setSelectedUploadIds={(update) => {
            setQuestionUploadIds(update);
            setQuestionResult(null);
            setQuestionAnswers({});
            setQuestionExplanations({});
            setQuestionAttemptResults({});
            setSelectedQuestionAnswers({});
          }}
          topics={questionTopics}
          questionForm={questionForm}
          setQuestionForm={(update) => {
            setQuestionForm(update);
            setQuestionResult(null);
            setQuestionAnswers({});
            setQuestionExplanations({});
            setQuestionAttemptResults({});
            setSelectedQuestionAnswers({});
          }}
          saveSettings={saveSettings}
          busy={settingsBusy}
          appVersion={appVersion}
          onCheckForUpdates={checkForUpdates}
          updateCheckBusy={updateCheckBusy}
          error={error}
          notice={notice}
        />}
        {page === "Help" && <HelpPage />}
        <input
          ref={fileInput}
          className="hidden-input"
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }}
        />
        <input
          ref={lessonFileInput}
          className="hidden-input"
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          onChange={(event) => { uploadLessons(event.target.files); event.target.value = ""; }}
        />
        <input
          ref={trainingFileInput}
          className="hidden-input"
          type="file"
          accept=".pdf,.docx,.txt"
          multiple
          onChange={(event) => { uploadTrainingFiles(event.target.files); event.target.value = ""; }}
        />
        <input
          ref={csvInput}
          className="hidden-input"
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => { importTrainingCsv(event.target.files?.[0]); event.target.value = ""; }}
        />
        <input
          ref={testResultsInput}
          className="hidden-input"
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => {
            importTeacherTestResults(analysisTestId, event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </main>
      {dragging && <div className="global-drop-overlay"><div><Upload size={30} /><strong>Drop course files to add them</strong><span>PDF, DOCX, or TXT · Stored locally</span></div></div>}
    </div>
  );
}

function PracticeQuestionsPage({
  datasets, uploads, selectedDatasetId, selectedUploadIds, lessonUploads,
  lessonUploadBusy, lessonProgress, useExamStyle, onChangeExamStyle, lessonUploadInput,
  onUploadLessons, onRemoveLesson, form, onOpenSettings,
  result, selectedTopic, onClearTopic, preferences, answers, explanations, selectedAnswers, submittedAnswers,
  checkingQuestionId, onSelectAnswer, onSubmitAnswer, busy, saved, questionSetUnavailable, onGenerate, onSave, onRevealAnswers,
  onBack, error, notice, onRateQuestion, onResetPreferences, onResetQuestionHistory
}) {
  const [lessonDropActive, setLessonDropActive] = useState(false);
  const [questionSort, setQuestionSort] = useState("likelihood");
  const selectedDatasetName = datasets.find((dataset) => dataset.id === selectedDatasetId)?.name || "Built-in examples";
  const selectedUploadNames = uploads
    .filter((upload) => selectedUploadIds.includes(upload.id))
    .map((upload) => upload.name);
  const readyLessons = lessonUploads.filter((lesson) => lesson.status === "Ready");
  const examFiles = uploads.filter((upload) => (
    /\.pdf$/i.test(upload.name) && /(?:^|[_\s-])exam(?:[_\s.-]|$)/i.test(upload.name)
  ));
  const effectiveUploadNames = lessonUploads.length
    ? readyLessons.map((lesson) => lesson.name)
    : selectedUploadNames;
  const sortedQuestions = result?.questions ? [...result.questions].sort((left, right) => {
    if (questionSort === "topic") {
      return left.topic.localeCompare(right.topic) || left.lesson_order - right.lesson_order;
    }
    if (questionSort === "lesson") return left.lesson_order - right.lesson_order;
    return right.likelihood_score - left.likelihood_score
      || left.lesson_order - right.lesson_order;
  }) : [];
  const examQuestions = result?.likely_topics ? sortedQuestions : (result?.questions || []);
  let nextExamNumber = 1;
  const questionParts = ["Multiple Choice", "True or False", "Identification"]
    .map((type) => ({
      type,
      questions: examQuestions
        .filter((item) => item.question_type === type)
        .map((item) => ({ ...item, exam_number: nextExamNumber++ }))
    }))
    .filter((part) => part.questions.length > 0);
  const numberedExamQuestions = questionParts.flatMap((part) => part.questions);
  const rejectionLabels = {
    already_a_question: "Already phrased as a question",
    below_topic_relevance: "Below the 45% topic-relevance threshold",
    candidate_validation_failed: "Failed source/answer validation",
    different_difficulty: "Did not match the selected difficulty",
    no_readable_words: "No readable words after text cleaning",
    unclean_sentence: "Statement was incomplete or not a clean sentence",
    no_safe_negation: "No safe true/false negation could be formed",
    not_enough_distinct_distractors: "Not enough distinct source-defined answer choices",
    distractor_is_answer_in_set: "A distractor conflicted with another selected answer",
    not_definition: "Not written in a supported definition format",
    outside_sentence_length: "Too short or long to use as a sentence",
    per_topic_limit_reached: "Skipped after reaching the per-topic limit",
    too_similar: "Too similar to another question",
    topic_not_selected: "Classified outside the selected topic"
  };
  return <section className="question-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> SOURCE-GROUNDED STUDY TOOLS</div>
        <h1>Generate practice questions</h1>
        <p>Review your generation setup and create a source-grounded practice set. No external knowledge is used.</p>
      </div>
      <button className="button-outline question-back" onClick={onBack}>Back to Results</button>
    </div>

    <div className="question-priority-notice">
      <ShieldCheck size={17} />
      <span><strong>Likelihood is an estimate from your materials, not a guarantee of actual exam content.</strong> Past-exam signals are used only when enabled and matching exam PDFs are available locally.</span>
    </div>
    <div className="question-overview-card">
      <div className="section-heading">
        <div><h2><Sparkles size={17} /> Current setup</h2><p>Change question settings in Settings. Your choices are saved locally.</p></div>
        <button className="button-outline" type="button" onClick={onOpenSettings}>Question settings</button>
      </div>
      {readyLessons.length > 0 && <div className="question-overview-sources question-generating-from">
        <strong>Generating from: {readyLessons.length} lesson{readyLessons.length === 1 ? "" : "s"}</strong>
        <span title={readyLessons.map((lesson) => lesson.name).join(", ")}>
          {readyLessons.map((lesson) => lesson.name).join(", ")}
        </span>
      </div>}
      <div className="question-overview-sources question-style-reference">
        <strong>Past-exam evidence: {useExamStyle ? `${examFiles.length} exam file${examFiles.length === 1 ? "" : "s"}` : "Off"}</strong>
        <span>Past exams help rank likely topics. Question stems and choices are newly written from selected lesson material.</span>
      </div>
      <div className="question-overview-grid">
        <div><span>Training dataset</span><strong>{selectedDatasetName}</strong></div>
        <div><span>Source files</span><strong>{effectiveUploadNames.length} selected</strong></div>
        <div><span>Question format</span><strong>{form.question_type}</strong></div>
        <div><span>Question count</span><strong>{form.number_of_questions} requested · {form.questions_per_topic} per topic max</strong></div>
      </div>
      <div className="question-overview-sources">
        <strong>Selected materials</strong>
        {effectiveUploadNames.length
          ? <span title={effectiveUploadNames.join(", ")}>{effectiveUploadNames.join(", ")}</span>
          : <span>No source files selected. Choose materials in Settings.</span>}
      </div>
      <div
        className={`lesson-upload-card ${lessonDropActive ? "lesson-upload-card-active" : ""}`}
        onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); setLessonDropActive(true); }}
        onDragLeave={(event) => {
          event.stopPropagation();
          if (event.currentTarget === event.target) setLessonDropActive(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setLessonDropActive(false);
          onUploadLessons(event.dataTransfer.files);
        }}
      >
        <div className="lesson-upload-heading">
          <div><strong>Upload lessons</strong><span>Each listed lesson is a content source; all listed lessons generate together.</span></div>
          <button className="button-outline" type="button" disabled={lessonUploadBusy || busy} onClick={() => lessonUploadInput.current?.click()}>
            <Upload size={14} /> Choose lessons
          </button>
        </div>
        <button className="lesson-upload-drop" type="button" disabled={lessonUploadBusy || busy} onClick={() => lessonUploadInput.current?.click()}>
          {lessonUploadBusy
            ? <><span className="spinner" /> Uploading and reading lesson files locally...</>
            : <>Drop multiple PDF, DOCX, or TXT lessons here, or choose files</>}
        </button>
        {lessonUploads.length > 0 && <ul className="lesson-upload-list">
          {lessonUploads.map((lesson) => <li className={`lesson-upload-chip lesson-upload-chip-${lesson.status.toLowerCase()}`} key={lesson.id}>
            <FileText size={14} />
            <span className="lesson-upload-chip-copy">
              <strong title={lesson.name}>{lesson.name}</strong>
              <small>{lesson.status}{lesson.bytes ? ` · ${(lesson.bytes / (1024 * 1024)).toFixed(2)} MB` : ""}{lesson.error ? ` · ${lesson.error}` : ""}</small>
            </span>
            <button
              className="icon-button"
              type="button"
              onClick={() => onRemoveLesson(lesson.id)}
              disabled={lessonUploadBusy || busy}
              aria-label={`Remove ${lesson.name} from lesson generation`}
              title={`Remove ${lesson.name}`}
            ><X size={14} /></button>
          </li>)}
        </ul>}
        {lessonProgress && <div
          className={`lesson-processing lesson-processing-${lessonProgress.phase}`}
          role="status"
          aria-live="polite"
        >
          {lessonProgress.phase === "done"
            ? <Check size={14} />
            : lessonProgress.phase === "error"
              ? <AlertCircle size={14} />
              : <span className="spinner" />}
          <span>{lessonProgress.message}</span>
        </div>}
        {readyLessons.length > 0 && <button
          className="button-outline"
          type="button"
          disabled={busy || lessonUploadBusy}
          onClick={onResetQuestionHistory}
        >
          Reset question history for these lessons
        </button>}
        <label className="lesson-style-toggle">
          <input type="checkbox" checked={useExamStyle} onChange={(event) => onChangeExamStyle(event.target.checked)} disabled={lessonUploadBusy || busy} />
          <span><strong>Use past exams for topic ranking</strong><small>Past exams inform likely-topic estimates, but question stems and answers come from your lesson material.</small></span>
        </label>
        <small className="lesson-upload-hint">PDF, DOCX, TXT · maximum 20 MB · scanned PDFs need local Tesseract OCR</small>
      </div>
      <button className="button-dark question-generate" disabled={busy || lessonUploadBusy || !effectiveUploadNames.length} onClick={onGenerate}>
        {busy ? <><span className="spinner" /> Generating...</> : <><Sparkles size={16} /> Generate Questions</>}
      </button>
      {!effectiveUploadNames.length && <p className="question-validation-note">Select materials in Settings or upload a lesson above.</p>}
    </div>

    {(preferences?.ratings_recorded > 0 || result?.preference_learning?.applied) && <QuestionPreferenceNotice
      preferences={preferences}
      onReset={onResetPreferences}
    />}
    {error && <AppErrorMessage message={error} />}
    {notice && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
    {selectedTopic && <div className="practice-topic-filter">
      <span>Topic: {selectedTopic}</span>
      <button type="button" className="icon-button" aria-label="Clear topic filter" onClick={onClearTopic}><X size={14} /></button>
    </div>}

    {result && <div className="question-results">
      {result.likely_topics && <section className="likely-topics-panel">
        <div className="section-heading"><div><h2>Likely exam topics</h2>
          <p>{result.exam_evidence_available
            ? `Ranked with ${result.exam_sources.length} readable past-exam file(s) and lesson emphasis.`
            : "Ranked by lesson emphasis only; no readable past-exam PDFs were found."}</p></div>
        </div>
        {result.classifier_training && <p className="classifier-training-note">
          Topic classifier fitted on demand during generation; new fit time {result.classifier_training.fit_seconds.toFixed(3)}s
          {result.classifier_training.cache_hits ? ` · ${result.classifier_training.cache_hits} cached reuse(s)` : ""}
          {result.classifier_training.exam_passages_added
            ? ` · ${result.classifier_training.exam_passages_added} confidently topic-labeled exam passages added`
            : " · no exam passages met the labeling confidence threshold"}.
        </p>}
        {result.style_reference_enabled && <p className="classifier-training-note">
          Detected {result.question_pattern_count} wording pattern(s) across {result.style_reference_files} exam file(s). These are not copied; questions are written from lesson concepts.
        </p>}
        {result.skipped_exam_files?.length > 0 && <p className="lesson-exam-note">
          Past-exam evidence could not be extracted from: {result.skipped_exam_files.join(", ")}
        </p>}
        <div className="likely-topic-list">{result.likely_topics.map((item) => <article className="likely-topic-card" key={item.topic}>
          <div><strong>{item.topic}</strong><span className={`likelihood-chip likelihood-${item.likelihood.toLowerCase()}`}>{item.likelihood} likelihood</span></div>
          <p>{item.why.join(" · ")}</p>
        </article>)}</div>
        <details className="lesson-passage-analysis">
          <summary>Lesson passage topic analysis · {result.lesson_analysis.passages.length} passages, {result.lesson_analysis.unclassified_count} unclassified</summary>
          <ul>{result.lesson_analysis.passages.map((passage, index) => <li key={`${index}-${passage.text.slice(0, 20)}`}>
            <div className="lesson-passage-copy">
              <span className="lesson-passage-topic">{passage.topic}</span>
              <span>{passage.text}</span>
              <span className="lesson-passage-signals">
                {passage.signals.heading && <span>Heading</span>}
                {passage.signals.definition && <span>Definition</span>}
                {passage.signals.list && <span>List item</span>}
                {passage.signals.emphasized_terms.map((term) => <span key={`em-${term}`}>Emphasis: {term}</span>)}
                {passage.signals.repeated_terms.map((term) => <span key={`rep-${term}`}>Repeated: {term}</span>)}
              </span>
            </div>
          </li>)}</ul>
        </details>
      </section>}
      <div className="section-heading"><div><h2>Practice set</h2><p>{result.lesson_analysis
        ? `Generated ${result.questions.length} of ${result.requested_count} requested. Skipped: ${result.diagnostics.skipped_low_confidence || 0} low-confidence, ${result.diagnostics.no_valid_distractors || 0} no valid distractors.`
        : `${result.questions.length} of ${result.requested_count} requested questions passed source and duplicate checks.`}</p></div></div>
      {result.shortfall > 0 && <div className="question-shortfall">{result.shortfall_reason} The app will not fill the set with unsupported questions.</div>}
      {result.diagnostics?.rejections?.length > 0 && <details className="question-diagnostics">
        <summary>Why some source text was skipped</summary>
        <p>Skipped {result.diagnostics.header_lines_skipped || 0} exam-header or student-information lines. Checked {result.diagnostics.source_sentence_count} text segments; {result.diagnostics.sentences_matching_filters} matched the basic text, difficulty, and question-format filters.</p>
        <ul>{result.diagnostics.rejections.map(({ reason, count }) => <li key={reason}>
          <span>{rejectionLabels[reason] || reason.replaceAll("_", " ")}</span><strong>{count}</strong>
        </li>)}</ul>
      </details>}
      <div className="question-actions">
        <button className="button-outline" disabled={busy || !result.questions.length} onClick={onGenerate}><RotateCcw size={14} /> Generate Again</button>
        <button className="button-outline" disabled={busy || saved || questionSetUnavailable || !result.questions.length} onClick={onSave}><Save size={14} /> {saved ? "Saved Locally" : "Save Questions"}</button>
        <button className="button-outline" disabled={busy || !result.questions.length || (questionSetUnavailable && !Object.keys(answers).length)} onClick={onRevealAnswers}><Eye size={14} /> {Object.keys(answers).length ? "Hide Answers" : "Show Answers"}</button>
      </div>
      {result.likely_topics && <label className="question-sort-control">
        Sort questions
        <select value={questionSort} onChange={(event) => setQuestionSort(event.target.value)}>
          <option value="likelihood">Likelihood</option>
          <option value="topic">Topic</option>
          <option value="lesson">Lesson order</option>
        </select>
      </label>}
      <div className="exam-screen">
        {questionParts.map((part) => <section className="exam-part" key={part.type}>
          <div className="exam-question-list">
            {part.questions.map((item) => <article className="exam-question" key={item.id}>
              <p className="exam-question-stem"><strong>{item.exam_number}.</strong> {item.question_text}</p>
              {item.choices?.length > 0 && <ol className="exam-choices">
                {item.choices.map((choice, choiceIndex) => <li key={`${item.id}-${choiceIndex}`}>
                  <span>{String.fromCharCode(65 + choiceIndex)}.</span>{choice}
                </li>)}
              </ol>}
              {item.question_type === "True or False" && <div className="exam-response-line exam-print-response">True / False: ____________________</div>}
              {item.question_type === "Identification" && <div className="exam-response-line exam-print-response" />}
              <div className="practice-answer-entry">
                <AnswerControls
                  item={item}
                  answer={selectedAnswers[item.id] || ""}
                  disabled={Boolean(submittedAnswers[item.id]) || checkingQuestionId === item.id || questionSetUnavailable}
                  onChange={(answer) => onSelectAnswer(item.id, answer)}
                  onSubmit={() => onSubmitAnswer(item)}
                  submitting={checkingQuestionId === item.id}
                />
                {submittedAnswers[item.id] && <AnswerResult result={submittedAnswers[item.id]} />}
              </div>
              <details className="question-instructor-details no-print">
                <summary>Question details and feedback</summary>
                <div className="practice-question-meta">
                  <span>{item.topic}</span>
                  <span>{item.difficulty}</span>
                  {item.likelihood && <span className={`likelihood-chip likelihood-${item.likelihood.toLowerCase()}`}>{item.likelihood} likelihood</span>}
                  {!item.likelihood && <><span>PRIORITY {Math.round(item.priority_score * 100)}%</span><span>RELEVANCE {Math.round(item.confidence_score * 100)}%</span></>}
                </div>
                {item.likelihood_why && <p className="question-likelihood-why"><strong>Why:</strong> {item.likelihood_why.join(" · ")}</p>}
                <QuestionFeedbackButtons
                  item={item}
                  onRate={(rating) => onRateQuestion(item, rating, result.generation_id)}
                />
                <details className="practice-source">
                  <summary>View source reference</summary>
                  <p>{item.source_reference}</p>
                </details>
              </details>
            </article>)}
          </div>
        </section>)}
      </div>
      {Object.keys(answers).length > 0 && <details className="exam-answer-key no-print">
        <summary>Answer key and explanations</summary>
        <ol>{numberedExamQuestions.map((item) => <li key={item.id}>
          <strong>{item.exam_number}.</strong> {answers[item.id]}
          {explanations[item.id] && <p>{explanations[item.id]}</p>}
        </li>)}</ol>
      </details>}
      {!result.lesson_analysis && result.topic_priorities?.length > 0 && <details className="question-priority-breakdown">
        <summary>Transparent topic priority breakdown</summary>
        <div className="priority-table-wrap"><table><thead><tr><th>Topic</th><th>Priority</th><th>Frequency</th><th>Material</th><th>Model</th><th>Recent*</th></tr></thead>
          <tbody>{result.topic_priorities.map((item) => <tr key={item.topic}>
            <td>{item.topic}</td><td>{Math.round(item.priority_score * 100)}%</td>
            <td>{Math.round(item.frequency_score * 100)}%</td><td>{Math.round(item.course_importance_score * 100)}%</td>
            <td>{Math.round(item.model_confidence_score * 100)}%</td><td>{Math.round(item.recent_occurrence_score * 100)}%</td>
          </tr>)}</tbody></table></div>
        <p>*Recent occurrence cannot be established because the selected training records do not contain per-example dates; the score is neutral, not an inferred chronology.</p>
      </details>}
      <p className="output-disclaimer">{result.disclaimer}</p>
    </div>}
  </section>;
}

function AnswerControls({ item, answer, disabled, onChange, onSubmit, submitting = false }) {
  const hasAnswer = typeof answer === "string" && answer.trim().length > 0;
  return <div className="answer-controls">
    {item.question_type === "Multiple Choice" && <div className="answer-choice-list">
      {(item.choices || []).map((choice, index) => (
        <button
          className={`answer-choice ${answer === choice ? "answer-choice-selected" : ""}`}
          type="button"
          key={`${item.id}-${index}`}
          aria-pressed={answer === choice}
          disabled={disabled}
          onClick={() => onChange(choice)}
        >
          <span>{String.fromCharCode(65 + index)}.</span>{choice}
        </button>
      ))}
    </div>}
    {item.question_type === "True or False" && <div className="answer-binary-choice">
      {["True", "False"].map((choice) => (
        <button
          className={`button-outline ${answer === choice ? "answer-choice-selected" : ""}`}
          type="button"
          key={choice}
          aria-pressed={answer === choice}
          disabled={disabled}
          onClick={() => onChange(choice)}
        >{choice}</button>
      ))}
    </div>}
    {item.question_type === "Identification" && <label className="answer-identification">
      <span>Your answer</span>
      <input
        type="text"
        value={answer}
        maxLength={240}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>}
    <button className="button-dark answer-check-button" type="button" disabled={!hasAnswer || disabled} onClick={onSubmit}>
      {submitting ? <><span className="spinner" /> Checking...</> : "Check"}
    </button>
  </div>;
}

function AnswerResult({ result }) {
  const intervals = { 1: 0, 2: 1, 3: 3, 4: 7, 5: 14 };
  const days = intervals[result.review_box];
  const nextReview = days === 0
    ? "today"
    : days
      ? `in ${days} day${days === 1 ? "" : "s"}`
      : result.next_review_at
        ? formatDate(result.next_review_at)
        : "scheduled";
  return <div className={`answer-result ${result.correct ? "answer-result-correct" : "answer-result-incorrect"}`} role="status">
    <strong>{result.correct ? "✓ Correct" : "✗ Incorrect"}</strong>
    <span><b>Correct answer:</b> {result.correct_answer}</span>
    {result.explanation && <span><b>Explanation:</b> {result.explanation}</span>}
    <small>Next review: {nextReview}</small>
  </div>;
}

function MyProgressPage({
  data, busy, error, notice, onNavigate, onPracticeTopic, onAnswer, onRefresh, onClearProgress, onError
}) {
  const [mistakesOnly, setMistakesOnly] = useState(false);
  const [reviewQuestions, setReviewQuestions] = useState([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewAnswer, setReviewAnswer] = useState("");
  const [reviewResult, setReviewResult] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewComplete, setReviewComplete] = useState(false);
  const [reviewTopic, setReviewTopic] = useState(null);
  const reviewSessionVersion = useRef(0);
  const total = data?.totals || {};
  const currentReview = reviewQuestions[reviewIndex];

  const resetReviewSession = () => {
    reviewSessionVersion.current += 1;
    setReviewQuestions([]);
    setReviewIndex(0);
    setReviewAnswer("");
    setReviewResult(null);
    setReviewBusy(false);
    setReviewComplete(false);
    setReviewTopic(null);
  };

  const startReview = async (topic = null) => {
    reviewSessionVersion.current += 1;
    const version = reviewSessionVersion.current;
    setReviewBusy(true);
    setReviewQuestions([]);
    setReviewResult(null);
    setReviewAnswer("");
    setReviewIndex(0);
    setReviewComplete(false);
    setReviewTopic(topic);
    onError("");
    try {
      const result = await api.dueReviews({ limit: 20, topic, mistakesOnly });
      if (version === reviewSessionVersion.current) setReviewQuestions(result.questions || []);
    } catch (loadError) {
      if (version === reviewSessionVersion.current) {
        onError(`Due reviews could not be loaded: ${loadError.message}`);
      }
    } finally {
      if (version === reviewSessionVersion.current) setReviewBusy(false);
    }
  };

  const submitReviewAnswer = async () => {
    if (!currentReview || !reviewAnswer.trim()) return;
    const version = reviewSessionVersion.current;
    setReviewBusy(true);
    const result = await onAnswer(currentReview.question_id, reviewAnswer);
    if (version === reviewSessionVersion.current) {
      if (result) setReviewResult(result);
      setReviewBusy(false);
    }
  };

  const resetProgress = async () => {
    if (await onClearProgress()) resetReviewSession();
  };

  const nextReviewQuestion = async () => {
    if (reviewIndex + 1 >= reviewQuestions.length) {
      setReviewComplete(true);
      setReviewQuestions([]);
      setReviewResult(null);
      setReviewAnswer("");
      await onRefresh();
      return;
    }
    setReviewIndex((index) => index + 1);
    setReviewResult(null);
    setReviewAnswer("");
  };

  const topics = data?.topics || [];
  return <section className="progress-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> STUDY HISTORY</div>
        <h1>My Progress</h1>
        <p>Track answers, build mastery, and revisit questions on a spaced schedule.</p>
      </div>
    </div>
    {error && <AppErrorMessage message={error} />}
    {notice && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
    {busy && !data && <div className="training-empty">Loading your progress...</div>}
    {!busy && data && topics.length === 0 ? <div className="progress-empty">
      <p>Answer a few practice questions and your progress will appear here.</p>
      <button className="button-dark" type="button" onClick={() => onNavigate("Generate Practice Questions")}>
        <Sparkles size={15} /> Generate Practice Questions
      </button>
    </div> : data && <>
      <div className="progress-summary">
        <SummaryMetric label="Total answers" value={total.attempts ?? 0} />
        <SummaryMetric label="Accuracy" value={total.accuracy == null ? "—" : `${Math.round(total.accuracy * 100)}%`} />
        <SummaryMetric label="Topics practiced" value={total.topics_practiced ?? 0} />
        <SummaryMetric label="Questions due now" value={total.due_now ?? 0} />
      </div>

      <section className="progress-section">
        <div className="section-heading"><div><h2>Study next</h2><p>Topics prioritized by exam likelihood and mastery.</p></div></div>
        {data.recommendations?.length
          ? <div className="progress-recommendations">{data.recommendations.map((topic) => (
            <article className="progress-card" key={topic.topic}>
              <div className="progress-card-heading">
                <h3>{topic.topic}</h3>
                <span className={`likelihood-chip likelihood-${(topic.likelihood || "Unknown").toLowerCase()}`}>
                  {topic.likelihood || "Unknown"}
                </span>
              </div>
              {topic.attempts === 0
                ? <span className="progress-not-practiced">Not practiced yet</span>
                : <div className="progress-mastery">
                  <MasteryBar mastery={topic.mastery} />
                  <strong>{topic.mastery == null ? "—" : `${Math.round(topic.mastery * 100)}%`}</strong>
                </div>}
              <p>{topic.reason}</p>
              <button
                className="button-outline"
                type="button"
                onClick={() => topic.due_reviews > 0
                  ? startReview(topic.topic)
                  : onPracticeTopic(topic.topic)}
              >{topic.due_reviews > 0 ? `Review ${topic.due_reviews} questions` : "Practice this topic"}</button>
            </article>
          ))}</div>
          : <p className="progress-muted">No recommendations yet.</p>}
      </section>

      <section className="progress-section">
        <div className="section-heading"><div><h2>Topic progress</h2><p>Sorted by study priority.</p></div></div>
        <div className="progress-table-wrap"><table className="progress-table">
          <thead><tr>
            <th>Topic</th><th>Exam likelihood</th><th>Mastery</th><th>Correct / answers</th><th>Due</th><th>Priority</th>
          </tr></thead>
          <tbody>{topics.map((topic) => (
            <tr key={topic.topic}>
              <td>{topic.topic}</td>
              <td><span className={`likelihood-chip likelihood-${(topic.likelihood || "Unknown").toLowerCase()}`}>{topic.likelihood || "Unknown"}</span></td>
              <td><div className="progress-table-mastery">
                {topic.attempts === 0
                  ? <small>Not practiced yet</small>
                  : <>
                    <MasteryBar mastery={topic.mastery} />
                    <strong>{topic.mastery == null ? "—" : `${Math.round(topic.mastery * 100)}%`}</strong>
                    {!topic.mastery_measured && <small>Not enough answers yet</small>}
                  </>}
              </div></td>
              <td>{topic.correct} / {topic.attempts}</td>
              <td>{topic.due_reviews}</td>
              <td>{topic.priority == null ? "—" : `${Math.round(topic.priority * 100)}%`}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>

      <section className="progress-section progress-review-section">
        <div className="section-heading">
          <div><h2>Due for review: {total.due_now ?? 0}</h2><p>Strengthen recall with spaced practice.</p></div>
          <button className="button-dark" type="button" disabled={reviewBusy || !total.due_now} onClick={() => startReview()}>
            {reviewBusy && !currentReview ? "Loading..." : "Review now"}
          </button>
        </div>
        <label className="progress-mistakes-toggle">
          <input type="checkbox" checked={mistakesOnly} onChange={(event) => setMistakesOnly(event.target.checked)} />
          <span>Mistakes only</span>
        </label>
        {reviewTopic && <p className="progress-review-filter">Reviewing {reviewTopic}</p>}
        {reviewComplete && <div className="progress-review-complete" role="status">Review complete</div>}
        {reviewBusy && currentReview && <p className="progress-muted">Saving your answer...</p>}
        {currentReview && !reviewComplete && <article className="progress-review-card">
          <div className="practice-question-meta">
            <span>{currentReview.topic}</span><span>{currentReview.difficulty}</span><span>BOX {currentReview.box}</span>
          </div>
          <h3>{currentReview.question_text}</h3>
          {currentReview.source_material_name && <small className="progress-review-source">Source: {currentReview.source_material_name}</small>}
          {!reviewResult ? <AnswerControls
            item={currentReview}
            answer={reviewAnswer}
            disabled={reviewBusy}
            onChange={setReviewAnswer}
            onSubmit={submitReviewAnswer}
            submitting={reviewBusy}
          /> : <>
            <AnswerResult result={reviewResult} />
            <button className="button-dark progress-next-button" type="button" onClick={nextReviewQuestion}>Next</button>
          </>}
        </article>}
        {!reviewBusy && !currentReview && !reviewComplete && reviewQuestions.length === 0 && (
          <p className="progress-muted">{total.due_now === 0
            ? "Nothing to review right now. Answer practice questions and the ones you miss will come back here."
            : reviewTopic
              ? "No questions are due for this topic."
              : "Select Review now to load due questions."}</p>
        )}
      </section>

      <details className="progress-method">
        <summary>How is this calculated?</summary>
        <p><strong>Mastery:</strong> {data.method?.mastery}</p>
        <p><strong>Priority:</strong> {data.method?.priority}</p>
        <div><strong>Review intervals:</strong>
          <ul>{Object.entries(data.method?.review_intervals_days || {}).map(([box, days]) => (
            <li key={box}>Box {box}: {days === 0 ? "today" : `in ${days} days`}</li>
          ))}</ul>
        </div>
      </details>
      <div className="progress-reset-row">
        <button className="button-outline progress-reset-button" type="button" onClick={resetProgress}>Reset answer history</button>
      </div>
    </>}
  </section>;
}

function SummaryMetric({ label, value }) {
  return <div className="progress-summary-card"><span>{label}</span><strong>{value}</strong></div>;
}

function MasteryBar({ mastery }) {
  const percent = mastery == null ? 0 : Math.max(0, Math.min(100, mastery * 100));
  return <span className="mastery-bar" aria-label={`${Math.round(percent)}% mastery`}>
    <i style={{ width: `${percent}%` }} />
  </span>;
}

function formatItemRanges(numbers = []) {
  const sorted = [...numbers].sort((left, right) => left - right);
  const ranges = [];
  let start = sorted[0];
  let end = sorted[0];
  for (const number of sorted.slice(1)) {
    if (number === end + 1) {
      end = number;
    } else {
      ranges.push(start === end ? String(start) : `${start}-${end}`);
      start = number;
      end = number;
    }
  }
  if (start !== undefined) ranges.push(start === end ? String(start) : `${start}-${end}`);
  return ranges.join(", ");
}

function TestBuilderPage({
  uploads, datasets, selectedDatasetId, setSelectedDatasetId, lessonIds, setLessonIds,
  lessonUploadInput, title, setTitle, itemCount, setItemCount, questionTypes, setQuestionTypes,
  includeSetB, setIncludeSetB, buildBusy, openBusy, tests, testsBusy, test, testResultRef, tab, setTab,
  previewSet, setPreviewSet, showAnswers, setShowAnswers, showEmptyTopics, setShowEmptyTopics,
  itemCounts, setItemCounts, error, notice, onBuild, onOpenTest, onRenameTest, onDeleteTest,
  onAnalyzeTest, onStartClassroom, onUploadClick, onDownload, onDownloadTemplate
}) {
  const [renamingTestId, setRenamingTestId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const lessonOptions = uploads.filter((upload) => !upload.is_exam);
  const availableSets = test?.sets?.B ? ["A", "B"] : ["A"];
  const activeSet = availableSets.includes(previewSet) ? previewSet : "A";

  const toggleQuestionType = (type) => {
    setQuestionTypes((current) => current.includes(type)
      ? current.length > 1 ? current.filter((value) => value !== type) : current
      : [...current, type]);
  };

  const rebuildWithCounts = () => {
    if (!test?.specification?.rows) return;
    const counts = Object.fromEntries(test.specification.rows.map((row) => [
      row.topic,
      Math.max(0, Number(itemCounts[row.topic] ?? row.items) || 0)
    ]));
    void onBuild(counts);
  };

  const saveRename = async (savedTest) => {
    if (await onRenameTest(savedTest.id, renameValue)) setRenamingTestId(null);
  };

  const renderSpecification = () => {
    const rows = test.specification.rows || [];
    const visibleRows = showEmptyTopics ? rows : rows.filter((row) => row.items > 0);
    const rememberingTotal = rows.reduce(
      (sum, row) => sum + (row.cognitive_levels?.Remembering || 0), 0
    );
    return <div className="test-specification">
      <label className="test-toggle">
        <input type="checkbox" checked={showEmptyTopics} onChange={(event) => setShowEmptyTopics(event.target.checked)} />
        <span>Show topics with no items</span>
      </label>
      <div className="test-table-wrap"><table className="teacher-table">
        <thead><tr>
          <th>Topic</th><th>Lesson passages</th><th>Weight %</th><th>No. of items</th>
          <th>% of test</th><th>Remembering</th><th>Item placement</th>
        </tr></thead>
        <tbody>
          {visibleRows.map((row) => <tr key={row.topic}>
            <td>{row.topic}</td>
            <td>{row.lesson_passages}</td>
            <td>{Number(row.weight_percent).toFixed(1)}%</td>
            <td><input
              className="spec-item-count"
              type="number"
              min="0"
              max={row.questions_available}
              value={itemCounts[row.topic] ?? row.items}
              onChange={(event) => setItemCounts((current) => ({
                ...current,
                [row.topic]: event.target.value
              }))}
              aria-label={`Items for ${row.topic}`}
            /></td>
            <td>{Number(row.percent_of_test).toFixed(1)}%</td>
            <td>{row.cognitive_levels?.Remembering || 0}</td>
            <td>{formatItemRanges(row.item_numbers)}</td>
          </tr>)}
          <tr className="teacher-table-total">
            <th>Total</th>
            <td>{test.specification.totals.lesson_passages}</td>
            <td>100%</td>
            <td>{test.specification.totals.items}</td>
            <td>100%</td>
            <td>{rememberingTotal}</td>
            <td>—</td>
          </tr>
        </tbody>
      </table></div>
      <button className="button-dark" type="button" disabled={buildBusy} onClick={rebuildWithCounts}>
        {buildBusy ? <><span className="spinner" /> Rebuilding...</> : "Rebuild with these numbers"}
      </button>
      <p className="teacher-method-note">{test.specification.method}</p>
    </div>;
  };

  const renderPreview = () => {
    const entries = test.sets?.[activeSet] || [];
    const sections = [
      ["Multiple Choice", "Test I. Multiple Choice"],
      ["True or False", "Test II. True or False"],
      ["Identification", "Test III. Identification"]
    ];
    return <div className="test-preview">
      <div className="test-preview-controls">
        <div className="test-set-switch" aria-label="Test set">
          {availableSets.map((label) => <button
            className={activeSet === label ? "test-tab-active" : ""}
            type="button"
            key={label}
            onClick={() => setPreviewSet(label)}
          >Set {label}</button>)}
        </div>
        <label className="test-toggle">
          <input type="checkbox" checked={showAnswers} onChange={(event) => setShowAnswers(event.target.checked)} />
          <span>Show answers</span>
        </label>
      </div>
      {sections.map(([type, heading]) => {
        const questions = entries
          .map((entry, index) => ({ entry, number: index + 1, item: test.items[entry.item] }))
          .filter(({ item }) => item?.question_type === type);
        if (!questions.length) return null;
        return <section className="test-preview-section" key={type}>
          <h3>{heading}</h3>
          {questions.map(({ entry, number, item }) => {
            const answerKey = test.answer_keys?.[activeSet]?.find((answer) => answer.number === number);
            const choices = entry.choices || item.choices || [];
            const answerLetter = String(answerKey?.answer || "").trim().toUpperCase();
            const correctIndex = /^[A-D]$/.test(answerLetter)
              ? answerLetter.charCodeAt(0) - 65
              : choices.findIndex((choice) => choice === (answerKey?.answer_text || item.correct_answer));
            return <article className="test-preview-item" key={`${activeSet}-${number}`}>
              <p><strong>{number}.</strong> {item.question_text}</p>
              {type === "Multiple Choice" && <ol className="test-preview-choices">
                {choices.map((choice, index) => <li
                  className={showAnswers && index === correctIndex ? "test-preview-answer" : ""}
                  key={`${number}-${index}`}
                ><span>{String.fromCharCode(65 + index)}.</span>{choice}</li>)}
              </ol>}
              {type === "True or False" && <p className="test-preview-response">True / False: ____________________</p>}
              {type === "Identification" && <p className="test-preview-response" />}
              {showAnswers && <>
                <p className="test-preview-answer-text">
                  <strong>Answer:</strong> {answerKey?.answer || item.correct_answer}
                  {answerKey?.answer_text ? ` · ${answerKey.answer_text}` : ""}
                </p>
                {item.explanation && <p className="test-preview-explanation">{item.explanation}</p>}
              </>}
            </article>;
          })}
        </section>;
      })}
    </div>;
  };

  const renderAnswerKey = () => {
    const setLabels = test.sets?.B ? ["A", "B"] : ["A"];
    const maxNumber = Math.max(0, ...setLabels.map((label) => test.answer_keys?.[label]?.length || 0));
    return <div className="test-table-wrap"><table className="teacher-table">
      <thead><tr><th>No.</th>{setLabels.map((label) => <th key={label}>Set {label}</th>)}</tr></thead>
      <tbody>{Array.from({ length: maxNumber }, (_, index) => {
        const number = index + 1;
        return <tr key={number}>
          <td>{number}</td>
          {setLabels.map((label) => {
            const answer = test.answer_keys?.[label]?.find((item) => item.number === number);
            return <td key={label}>{answer
              ? `${answer.answer}${answer.answer_text ? ` · ${answer.answer_text}` : ""}`
              : "—"}</td>;
          })}
        </tr>;
      })}</tbody>
    </table></div>;
  };

  return <section className="teacher-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> TEACHER TOOLS</div>
        <h1>Test Builder</h1>
        <p>Assemble balanced tests and export student papers, keys, and specifications.</p>
      </div>
    </div>
    {error && <AppErrorMessage message={error} />}
    {notice && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}

    <section className="teacher-panel test-builder-form">
      <div className="section-heading"><div><h2>Build a test</h2><p>Choose lessons and the assessment format.</p></div></div>
      <label className="teacher-field">
        <span>Test title</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. HCI Midterm" />
      </label>
      <div className="teacher-form-grid">
        <label className="teacher-field">
          <span>Training dataset</span>
          <select value={selectedDatasetId} onChange={(event) => setSelectedDatasetId(event.target.value)}>
            {datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label className="teacher-field">
          <span>Number of items (5–100)</span>
          <input
            type="number"
            min="5"
            max="100"
            step="1"
            value={itemCount}
            onChange={(event) => setItemCount(event.target.value === "" ? "" : Math.max(5, Math.min(100, Number(event.target.value))))}
          />
        </label>
      </div>
      <div className="teacher-field teacher-lessons-field">
        <div className="teacher-field-heading">
          <span>Lessons</span>
          <button className="button-outline" type="button" onClick={onUploadClick}><Upload size={13} /> Upload lessons</button>
        </div>
        {uploads.length
          ? <div className="teacher-lesson-list">{uploads.map((upload) => <label className="teacher-lesson-option" key={upload.id}>
            <input
              type="checkbox"
              checked={lessonIds.includes(upload.id)}
              onChange={() => setLessonIds((current) => current.includes(upload.id)
                ? current.filter((id) => id !== upload.id)
                : [...current, upload.id])}
            />
            <span>{upload.name}</span>
          </label>)}</div>
          : <p className="teacher-empty">Upload course lessons to build a test.</p>}
      </div>
      <fieldset className="teacher-question-types">
        <legend>Question types</legend>
        {["Multiple Choice", "True or False", "Identification"].map((type) => (
          <label key={type}>
            <input
              type="checkbox"
              checked={questionTypes.includes(type)}
              disabled={questionTypes.length === 1 && questionTypes.includes(type)}
              onChange={() => toggleQuestionType(type)}
            />
            <span>{type}</span>
          </label>
        ))}
      </fieldset>
      <label className="test-toggle test-set-b-toggle">
        <input type="checkbox" checked={includeSetB} onChange={(event) => setIncludeSetB(event.target.checked)} />
        <span>Make a Set B (shuffled)</span>
      </label>
      <button className="button-dark test-build-button" type="button" disabled={buildBusy || openBusy} onClick={() => onBuild()}>
        {buildBusy ? <><span className="spinner" /> Building test...</> : "Build test"}
      </button>
    </section>

    {test && <>
      {test.warnings?.length > 0 && <div className="app-message app-message-success test-warning-list">
        <AlertCircle size={16} />
        <div><strong>Warnings</strong><ul>{test.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></div>
      </div>}
      <section className="teacher-panel test-result-panel" ref={testResultRef}>
        <div className="test-result-heading">
          <div><h2>{test.title}</h2><p>{test.total_items} items · {test.lesson_names.join(", ")}</p></div>
          {openBusy && <span className="teacher-loading"><span className="spinner" /> Opening...</span>}
        </div>
        <div className="test-tabs" role="tablist" aria-label="Test details">
          {[
            ["specification", "Table of Specifications"],
            ["preview", "Preview"],
            ["key", "Answer key"],
            ["download", "Download"]
          ].map(([value, label]) => <button
            className={tab === value ? "test-tab-active" : ""}
            type="button"
            role="tab"
            aria-selected={tab === value}
            key={value}
            onClick={() => setTab(value)}
          >{label}</button>)}
        </div>
        {tab === "specification" && renderSpecification()}
        {tab === "preview" && renderPreview()}
        {tab === "key" && renderAnswerKey()}
        {tab === "download" && <div className="test-download-panel">
          <p>Download editable Word documents for both test sets, the answer key, the specification, or a CSV template for results.</p>
          <div className="test-download-buttons">
            <button className="button-outline" type="button" onClick={() => onDownload(test.id, "test", "A")}><Download size={14} /> Test paper – Set A</button>
            {test.sets?.B && <button className="button-outline" type="button" onClick={() => onDownload(test.id, "test", "B")}><Download size={14} /> Test paper – Set B</button>}
            <button className="button-outline" type="button" onClick={() => onDownload(test.id, "key")}><Download size={14} /> Answer key</button>
            <button className="button-outline" type="button" onClick={() => onDownload(test.id, "tos")}><Download size={14} /> Table of Specifications</button>
            <button className="button-outline" type="button" onClick={() => onDownloadTemplate(test.id)}><FileSpreadsheet size={14} /> Results template (CSV)</button>
          </div>
          <small>Word files open in Microsoft Word, WPS Office or Google Docs.</small>
        </div>}
      </section>
    </>}

    <section className="teacher-panel teacher-saved-tests">
      <div className="section-heading">
        <div><h2>Saved tests</h2><p>Open, rename, delete, or analyze an existing test.</p></div>
        {testsBusy && <span className="teacher-loading"><span className="spinner" /> Loading...</span>}
      </div>
      {tests.length
        ? <div className="saved-test-list">{tests.map((savedTest) => (
          <article
            className={`saved-test-row${test?.id === savedTest.id ? " saved-test-row-active" : ""}`}
            key={savedTest.id}
          >
            {renamingTestId === savedTest.id
              ? <div className="saved-test-rename">
                <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label="Test title" />
                <button className="button-outline" type="button" onClick={() => saveRename(savedTest)}>Save</button>
                <button className="icon-button" type="button" aria-label="Cancel rename" onClick={() => setRenamingTestId(null)}><X size={14} /></button>
              </div>
              : <div className="saved-test-info">
                <strong>{savedTest.title}</strong>
                <small>{formatDate(savedTest.created_at)} · {savedTest.total_items} items · Sets {savedTest.sets.join(", ")} · {savedTest.students} students</small>
              </div>}
            {renamingTestId !== savedTest.id && <div className="saved-test-actions">
              <button className="button-outline" type="button" onClick={() => onOpenTest(savedTest.id)}>Open</button>
              <button className="icon-button" type="button" aria-label={`Rename ${savedTest.title}`} onClick={() => {
                setRenamingTestId(savedTest.id);
                setRenameValue(savedTest.title);
              }}><Pencil size={14} /></button>
              <button className="icon-button" type="button" aria-label={`Delete ${savedTest.title}`} onClick={() => onDeleteTest(savedTest)}><Trash2 size={14} /></button>
              <button className="button-outline" type="button" onClick={() => onAnalyzeTest(savedTest.id)}>Analyze</button>
              <button className="button-outline" type="button" onClick={() => onStartClassroom(savedTest.id)}>Start classroom quiz</button>
            </div>}
          </article>
        ))}</div>
        : !testsBusy && <p className="teacher-empty">No saved tests yet.</p>}
    </section>
  </section>;
}

function ClassroomQuizPage({
  tests, testsBusy, selectedTestId, onSelectTest, session, endResult, actionBusy,
  error, pollError, notice, copyNotice, onStart, onEnd, onCopyAddress, onOpenAnalysis
}) {
  const [setMode, setSetMode] = useState("alternate");
  const selectedTest = tests.find((test) => test.id === selectedTestId);
  const hasSetB = selectedTest?.sets?.includes("B") || false;
  const running = Boolean(session?.running);
  const ended = !running && session?.state === "ended";
  const joined = Number(endResult?.joined ?? session?.joined ?? 0);
  const submitted = Number(endResult?.submitted ?? session?.submitted ?? 0);
  const students = [...(session?.students || [])].sort((left, right) => (
    Number(right.submitted) - Number(left.submitted)
    || left.name.localeCompare(right.name)
  ));
  const unansweredNames = endResult?.not_submitted
    || session?.students?.filter((student) => !student.submitted).map((student) => student.name)
    || [];

  useEffect(() => {
    setSetMode(hasSetB ? "alternate" : "A");
  }, [selectedTestId, hasSetB]);

  return <section className="teacher-page classroom-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> TEACHER TOOLS</div>
        <h1>Classroom Quiz</h1>
        <p>Run a live quiz on your local network and save submitted answers for Item Analysis.</p>
      </div>
    </div>
    {error && <AppErrorMessage message={error} />}
    {pollError && <AppErrorMessage message={pollError} />}
    {notice && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}

    {running && <section className="teacher-panel classroom-running-panel">
      <div className="classroom-running-heading">
        <div><h2>{session.title}</h2><p>{session.total_items} questions · {session.set_mode === "alternate" ? "Alternating sets" : `Set ${session.set_mode}`}</p></div>
        <span className="classroom-live-badge"><i /> Quiz running</span>
      </div>
      <div className="classroom-code-block">
        <span>ROOM CODE</span>
        <strong aria-label={`Room code ${session.code}`}>{session.code}</strong>
      </div>
      <div className="classroom-join-panel">
        <span className="classroom-section-label">Students open:</span>
        {session.join_urls?.[0] && <div className="classroom-main-address">
          <a href={session.join_urls[0]} target="_blank" rel="noreferrer">{session.join_urls[0]}</a>
          <button className="button-outline" type="button" onClick={() => onCopyAddress(session.join_urls[0])}>Copy</button>
        </div>}
        {copyNotice && <div className="classroom-copy-notice">{copyNotice}</div>}
        {session.join_urls?.length > 1 && <div className="classroom-other-addresses">
          <span>If that doesn&apos;t work, try:</span>
          {session.join_urls.slice(1).map((address) => <a href={address} key={address} target="_blank" rel="noreferrer">{address}</a>)}
        </div>}
      </div>
      <div className="classroom-counters">
        <div><span>Joined</span><strong>{session.joined}</strong></div>
        <div><span>Submitted</span><strong>{submitted} of {session.joined} submitted</strong></div>
      </div>
      <div className="classroom-students">
        <h3>Students</h3>
        <div className="teacher-table-wrap"><table className="teacher-table">
          <thead><tr><th>Name</th><th>Set</th><th>Status</th><th>Score</th></tr></thead>
          <tbody>{students.length ? students.map((student) => <tr key={`${student.name}-${student.set}`}>
            <td>{student.name}</td>
            <td>{student.set}</td>
            <td>{student.submitted ? "Submitted" : "Answering…"}</td>
            <td>{student.submitted ? `${student.score} / ${session.total_items}` : "—"}</td>
          </tr>) : <tr><td colSpan="4">No students have joined yet.</td></tr>}</tbody>
        </table></div>
      </div>
      <div className="classroom-actions">
        <button className="button-dark" type="button" disabled={actionBusy} onClick={() => onEnd(true)}>
          {actionBusy ? <><span className="spinner" /> Ending quiz...</> : "End quiz and save results"}
        </button>
        <button className="button-outline" type="button" disabled={actionBusy} onClick={() => onEnd(false)}>
          Cancel quiz
        </button>
      </div>
    </section>}

    {ended && <section className="teacher-panel classroom-ended-panel">
      <div className="classroom-ended-icon"><Check size={18} /></div>
      <div>
        <h2>Quiz ended</h2>
        <p>{endResult?.message || `${submitted} of ${joined} students submitted · ${endResult?.saved === false ? "results not saved" : "results saved"}`}</p>
        {unansweredNames.length > 0 && <div className="classroom-unsubmitted">
          <strong>Did not submit:</strong> {unansweredNames.join(", ")}
        </div>}
        <button className="button-dark" type="button" onClick={onOpenAnalysis}>Open Item Analysis</button>
      </div>
    </section>}

    {!running && <section className="teacher-panel classroom-start-panel">
      <div className="section-heading"><div><h2>Before you start</h2></div></div>
      <ol className="classroom-before-start">
        <li>Turn on your phone&apos;s or laptop&apos;s hotspot (school Wi-Fi usually blocks this).</li>
        <li>Connect this laptop and the students&apos; phones to it.</li>
        <li>The first time, Windows will ask to allow Clinthinker on the network. Choose Private networks and click Allow.</li>
      </ol>
      <label className="teacher-field">
        <span>Saved test</span>
        <select value={selectedTestId} onChange={(event) => onSelectTest(event.target.value)} disabled={testsBusy || !tests.length}>
          {!tests.length && <option value="">{testsBusy ? "Loading saved tests..." : "No saved tests"}</option>}
          {tests.map((test) => <option value={test.id} key={test.id}>
            {test.title} · {test.total_items} items · Sets {(test.sets || []).join(", ")}
          </option>)}
        </select>
      </label>
      <label className="teacher-field">
        <span>Sets</span>
        <select value={hasSetB ? setMode : "A"} onChange={(event) => setSetMode(event.target.value)} disabled={!selectedTest}>
          {hasSetB && <option value="alternate">Alternate A and B</option>}
          <option value="A">Set A only</option>
          {hasSetB && <option value="B">Set B only</option>}
        </select>
      </label>
      <button
        className="button-dark classroom-start-button"
        type="button"
        disabled={actionBusy || testsBusy || !selectedTest}
        onClick={() => onStart(selectedTestId, hasSetB ? setMode : "A")}
      >
        {actionBusy ? <><span className="spinner" /> Starting quiz...</> : "Start quiz"}
      </button>
    </section>}
  </section>;
}

function ItemAnalysisPage({
  tests, testsBusy, selectedTestId, onSelectTest, analysis, analysisBusy, resultsBusy,
  resultsInput, error, notice, onDownloadTemplate
}) {
  const [filter, setFilter] = useState("All");
  const summary = analysis?.summary;
  const visibleItems = (analysis?.items || []).filter(
    (item) => filter === "All" || item.decision === filter
  );
  const students = [...(analysis?.students || [])].sort((left, right) => right.score - left.score);
  const decisions = summary?.decisions || {};
  const topicMax = Math.max(0, ...(analysis?.topics || []).map((topic) => topic.average_difficulty_index));

  const renderSummary = (label, value, detail = "") => <div className="analysis-summary-card" key={label}>
    <span>{label}</span>
    <strong>{value}</strong>
    {detail && <small>{detail}</small>}
  </div>;

  return <section className="teacher-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> TEACHER TOOLS</div>
        <h1>Item Analysis</h1>
        <p>Review class results, item quality, distractor performance, and test reliability.</p>
      </div>
    </div>
    {error && <AppErrorMessage message={error} />}
    {notice && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
    <section className="teacher-panel analysis-import-panel">
      <label className="teacher-field">
        <span>Saved test</span>
        <select value={selectedTestId} onChange={(event) => onSelectTest(event.target.value)} disabled={testsBusy}>
          <option value="">Select a saved test</option>
          {tests.map((test) => <option value={test.id} key={test.id}>{test.title}</option>)}
        </select>
      </label>
      <ol className="analysis-instructions">
        <li>Download the results template.</li>
        <li>Enter each student's answers (letters for multiple choice, T/F for true or false, the term for identification) and their set.</li>
        <li>Import the CSV.</li>
      </ol>
      <div className="analysis-import-actions">
        <button className="button-outline" type="button" disabled={!selectedTestId} onClick={() => onDownloadTemplate(selectedTestId)}>
          <Download size={14} /> Download template
        </button>
        <button
          className="button-dark"
          type="button"
          disabled={!selectedTestId || resultsBusy}
          onClick={() => resultsInput.current?.click()}
        >
          {resultsBusy ? <><span className="spinner" /> Importing...</> : <><Upload size={14} /> Import results (CSV)</>}
        </button>
      </div>
    </section>

    {analysisBusy && <div className="teacher-loading analysis-loading"><span className="spinner" /> Loading item analysis...</div>}
    {analysis?.warnings?.length > 0 && <div className="app-message app-message-success test-warning-list">
      <AlertCircle size={16} />
      <div><strong>Warnings</strong><ul>{analysis.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></div>
    </div>}
    {summary && <div className="analysis-results">
      <section className="teacher-panel">
        <div className="section-heading"><div><h2>{analysis.title} · Summary</h2><p>{summary.items} items analyzed</p></div></div>
        <div className="analysis-summary-grid">
          {renderSummary("Students", summary.students)}
          {renderSummary("Mean score", `${summary.mean_score} / ${summary.items}`, `${Number(summary.mean_percent).toFixed(1)}%`)}
          {renderSummary("Median", summary.median_score)}
          {renderSummary("Standard deviation", Number(summary.standard_deviation).toFixed(1))}
          {renderSummary("Highest / lowest", `${summary.highest_score} / ${summary.lowest_score}`)}
          {renderSummary("KR-20 reliability", summary.kr20 == null ? "—" : Number(summary.kr20).toFixed(2), summary.kr20 == null ? "" : summary.reliability)}
          {renderSummary("Retain", decisions.Retain || 0)}
          {renderSummary("Revise", decisions.Revise || 0)}
          {renderSummary("Discard", decisions.Discard || 0)}
        </div>
      </section>

      <section className="teacher-panel analysis-items-panel">
        <div className="section-heading">
          <div><h2>Item analysis</h2><p>Difficulty and discrimination indices with recommended decisions.</p></div>
          <label className="analysis-filter">
            <span>Decision</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value)}>
              {["All", "Retain", "Revise", "Discard"].map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
        </div>
        <div className="teacher-table-wrap"><table className="teacher-table analysis-item-table">
          <thead><tr>
            <th>No.</th><th>Question</th><th>Topic</th><th>Difficulty index</th><th>Discrimination index</th><th>Decision</th>
          </tr></thead>
          <tbody>{visibleItems.map((item) => <tr key={item.number}>
            <td>{item.number}</td>
            <td><details className="analysis-item-details">
              <summary title={item.question_text}>{item.question_text}</summary>
              <div className="analysis-item-expanded">
                <p><strong>Full question:</strong> {item.question_text}</p>
                <p><strong>Correct answer:</strong> {item.correct_answer}</p>
                <p><strong>Correct:</strong> {item.correct_count} · <strong>Unanswered:</strong> {item.unanswered}</p>
                {item.question_type === "Multiple Choice" && <div className="analysis-distractors">
                  <strong>Distractor analysis</strong>
                  <div className="teacher-table-wrap"><table className="teacher-table">
                    <thead><tr><th>Option</th><th>Chosen by</th><th>Upper</th><th>Lower</th><th>Flag</th></tr></thead>
                    <tbody>{(item.options || []).map((option, index) => <tr className={option.is_answer ? "analysis-correct-option" : ""} key={`${item.number}-${index}`}>
                      <td>{option.choice}{option.is_answer ? " · Correct answer" : ""}</td>
                      <td>{option.chosen_by}</td><td>{option.upper}</td><td>{option.lower}</td><td>{option.flag || "—"}</td>
                    </tr>)}</tbody>
                  </table></div>
                </div>}
              </div>
            </details></td>
            <td>{item.topic}</td>
            <td>{Number(item.difficulty_index).toFixed(3)} <small>({item.difficulty})</small></td>
            <td>{Number(item.discrimination_index).toFixed(3)} <small>({item.discrimination})</small></td>
            <td><span className={`analysis-decision analysis-decision-${item.decision.toLowerCase()}`}>{item.decision}</span></td>
          </tr>)}</tbody>
        </table></div>
        {!visibleItems.length && <p className="teacher-empty">No items match this decision filter.</p>}
      </section>

      <section className="teacher-panel">
        <div className="section-heading"><div><h2>Topics</h2><p>Average difficulty, hardest first.</p></div></div>
        <div className="analysis-topic-list">{analysis.topics.map((topic) => {
          const value = Number(topic.average_difficulty_index) || 0;
          return <div className="analysis-topic-row" key={topic.topic}>
            <strong>{topic.topic}</strong>
            <span className="analysis-topic-bar"><i style={{ width: `${topicMax ? value / topicMax * 100 : 0}%` }} /></span>
            <small>{value.toFixed(3)}</small>
          </div>;
        })}</div>
      </section>

      <section className="teacher-panel">
        <div className="section-heading"><div><h2>Students</h2><p>Sorted by score, highest first.</p></div></div>
        <div className="teacher-table-wrap"><table className="teacher-table">
          <thead><tr><th>Name</th><th>Set</th><th>Score</th></tr></thead>
          <tbody>{students.map((student, index) => <tr key={`${student.name}-${student.set}-${index}`}>
            <td>{student.name}</td><td>{student.set}</td><td>{student.score}</td>
          </tr>)}</tbody>
        </table></div>
      </section>

      <details className="test-method-details">
        <summary>How is this calculated?</summary>
        <p><strong>Difficulty index:</strong> {analysis.method.difficulty_index}</p>
        <p><strong>Discrimination index:</strong> {analysis.method.discrimination_index}</p>
        <p><strong>Decision:</strong> {analysis.method.decision}</p>
        <p><strong>KR-20:</strong> {analysis.method.kr20}</p>
      </details>
    </div>}
    {!analysisBusy && !analysis && !error && !selectedTestId && (
      <p className="teacher-empty">Select a saved test to review its analysis.</p>
    )}
  </section>;
}

function SavedQuestionsPage({
  sessions, busy, expandedSessions, setExpandedSessions, visibleAnswerSessions,
  onToggleAnswers, onToggleAllAnswers, onRename, onDelete, onExportCsv, onExportPdf,
  printingSessionId, onRateQuestion, error
}) {
  const questionSessions = sessions.filter((session) => session.questions.length);
  const allAnswersVisible = questionSessions.length > 0
    && questionSessions.every((session) => visibleAnswerSessions.includes(session.id));
  const allExpanded = sessions.length > 0
    && sessions.every((session) => expandedSessions.includes(session.id));

  return <section className="question-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> SAVED LOCALLY</div>
        <h1>Saved questions</h1>
        <p>Questions are grouped by practice-question generation session. Answers stay hidden until revealed.</p>
      </div>
      {sessions.length > 0 && <div className="saved-session-global-actions">
        <button className="button-outline" onClick={() => setExpandedSessions(
          allExpanded ? [] : sessions.map((session) => session.id)
        )}>
          {allExpanded ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          {allExpanded ? "Collapse All" : "Expand All"}
        </button>
        {questionSessions.length > 0 && <button
          className="button-outline"
          disabled={busy}
          onClick={onToggleAllAnswers}
        >
          <Eye size={14} /> {busy ? "Loading..." : allAnswersVisible ? "Hide All Answers" : "Show All Answers"}
        </button>}
      </div>}
    </div>
    <p className="exam-export-note no-print">
      PDF exports include an answer key only while that session's answers are shown.
    </p>

    {error && <AppErrorMessage message={error} />}
    {busy && !sessions.length
      ? <div className="output-empty"><span className="spinner" /><strong>Loading saved questions...</strong></div>
      : sessions.length
        ? <div className="saved-session-list">
          {sessions.map((session) => {
            const expanded = expandedSessions.includes(session.id);
            const answersVisible = visibleAnswerSessions.includes(session.id);
            const printFooterCss = `${session.title} | ${session.questions.length} questions`
              .replaceAll("\\", "\\\\")
              .replaceAll('"', '\\"')
              .replaceAll("<", "\\3C ")
              .replaceAll("\r", " ")
              .replaceAll("\n", " ")
              .replaceAll("\f", " ");
            const createdAt = new Date(session.created_at);
            const formattedDate = Number.isNaN(createdAt.getTime())
              ? session.created_at : createdAt.toLocaleString();
            return <article
              className={`saved-session-card${printingSessionId === session.id ? " saved-session-print-target" : ""}`}
              key={session.id}
            >
              <div className="saved-session-heading">
                <button
                  className="saved-session-expand"
                  aria-expanded={expanded}
                  onClick={() => setExpandedSessions((current) => expanded
                    ? current.filter((id) => id !== session.id)
                    : [...current, session.id]
                  )}
                >
                  {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span className="saved-session-heading-copy">
                    <strong>{session.title}</strong>
                    <small>{formattedDate} · {session.question_count} question{session.question_count === 1 ? "" : "s"}</small>
                  </span>
                </button>
                <div className="saved-session-actions">
                  <button
                    className="button-outline"
                    onClick={() => onExportCsv(session)}
                    aria-label={`Export ${session.title} as CSV`}
                    title="Export session as CSV"
                  >
                    <Download size={13} />
                  </button>
                  <button
                    className="button-outline"
                    onClick={() => onExportPdf(session)}
                    aria-label={`Export ${session.title} as PDF`}
                    title="Export session as PDF"
                  >
                    <Printer size={13} />
                  </button>
                  <button className="button-outline" onClick={() => onRename(session)} aria-label={`Rename ${session.title}`} title="Rename session">
                    <Pencil size={13} />
                  </button>
                  <button className="button-outline saved-session-delete" onClick={() => onDelete(session)} aria-label={`Delete ${session.title}`} title="Delete session">
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
              <div className="saved-session-tags">
                <span>{session.topic}</span>
                <span>{session.source_file}</span>
                <span>{session.difficulty}</span>
                <span>{session.question_type}</span>
              </div>
              {expanded && <>
                <div className="saved-session-answer-actions">
                  <button
                    className="button-outline"
                    disabled={busy}
                    onClick={() => onToggleAnswers(session.id)}
                  >
                    <Eye size={13} /> {busy ? "Loading..." : answersVisible ? "Hide Answers" : "Show Answers"}
                  </button>
                </div>
                <div className="question-cards">
                  {session.questions.map((item, index) => <article className="practice-question-card" key={item.id}>
                    <div className="practice-question-meta">
                      <span>QUESTION {String(index + 1).padStart(2, "0")}</span>
                      <span>{item.topic}</span>
                      <span>{item.difficulty}</span>
                      <span>{item.question_type}</span>
                    </div>
                    <h3>{item.question_text}</h3>
                    {item.choices?.length > 0 && <ol className="practice-choices">
                      {item.choices.map((choice, choiceIndex) => (
                        <li key={`${item.id}-${choiceIndex}`}>
                          <span>{String.fromCharCode(65 + choiceIndex)}.</span>{choice}
                        </li>
                      ))}
                    </ol>}
                    {answersVisible && item.correct_answer && <div className="practice-answer">
                      <strong>Answer</strong><span>{item.correct_answer}</span>
                    </div>}
                    <QuestionFeedbackButtons
                      item={item}
                      onRate={(rating) => onRateQuestion(item, rating)}
                    />
                    <details className="practice-source">
                      <summary>View source reference</summary>
                      <p>{item.source_reference}</p>
                      <small>{item.source_dataset_name} · {item.source_material_name}</small>
                    </details>
                  </article>)}
                </div>
              </>}
              <div className="saved-session-print-document">
                {printingSessionId === session.id && <style>{`@media print {
                  @page {
                    margin: 18mm 15mm 20mm;
                    @bottom-left { content: "${printFooterCss}"; font-size: 8pt; color: #333; }
                    @bottom-right { content: "Page " counter(page); font-size: 8pt; color: #333; }
                  }
                }`}</style>}
                <header className="exam-print-header">
                  <h1>{session.title}</h1>
                  <p>Saved Practice Questions</p>
                  <div><span>Topic: {session.topic}</span><span>{formattedDate}</span></div>
                </header>
                <section className="exam-part">
                  <div className="exam-question-list">
                    {session.questions.map((item, index) => <article className="exam-question" key={`print-${item.id}`}>
                      <p className="exam-question-stem"><strong>{index + 1}.</strong> {item.question_text}</p>
                      {item.choices?.length > 0 && <ol className="exam-choices">
                        {item.choices.map((choice, choiceIndex) => <li key={`${item.id}-${choiceIndex}`}>
                          <span>{String.fromCharCode(65 + choiceIndex)}.</span>{choice}
                        </li>)}
                      </ol>}
                      {item.question_type === "True or False" && <div className="exam-response-line">True / False: ____________________</div>}
                      {item.question_type === "Identification" && <div className="exam-response-line" />}
                    </article>)}
                  </div>
                </section>
                {answersVisible && <section className="exam-print-answer-key">
                  <h2>ANSWER KEY</h2>
                  <ol>{session.questions.map((item, index) => <li key={`answer-${item.id}`}>
                    <strong>{index + 1}. {item.correct_answer || ""}</strong>
                  </li>)}</ol>
                </section>}
              </div>
            </article>;
          })}
        </div>
        : <div className="output-empty">
          <NotebookText size={24} />
          <strong>No saved questions yet</strong>
          <span>Generate a practice set and choose “Save Questions” to keep it here.</span>
        </div>}
  </section>;
}

function QuestionPreferenceNotice({ preferences, onReset }) {
  const liked = preferences.learned_preferences?.slice(0, 3).map((item) => {
    if (item.feature === "wording_pattern") return `${item.value} wording`;
    return item.value;
  }) || [];
  return <div className="question-feedback-notice">
    <ThumbsUp size={16} />
    <span>
      <strong>Using your feedback ({preferences.ratings_recorded} rating{preferences.ratings_recorded === 1 ? "" : "s"})</strong>
      {liked.length ? ` · Current positive signals: ${liked.join(", ")}.` : " · Ratings guide future question ordering by format, wording, and length."}
    </span>
    {preferences.ratings_recorded > 0 && <button className="button-outline" onClick={onReset}>Reset preferences</button>}
  </div>;
}

function QuestionFeedbackButtons({ item, onRate }) {
  return <div className="question-feedback-actions" aria-label="Rate this question">
    <span>Was this a good question?</span>
    <button
      className={`button-outline ${item.feedback_rating === 1 ? "question-feedback-selected" : ""}`}
      type="button"
      aria-pressed={item.feedback_rating === 1}
      onClick={() => onRate(1)}
    >
      <ThumbsUp size={13} /> Good
    </button>
    <button
      className={`button-outline ${item.feedback_rating === -1 ? "question-feedback-selected" : ""}`}
      type="button"
      aria-pressed={item.feedback_rating === -1}
      onClick={() => onRate(-1)}
    >
      <ThumbsDown size={13} /> Not for me
    </button>
  </div>;
}

function UploadPage({
  uploads, datasets, selectedDatasetId, setSelectedDatasetId, showBuiltInWarning, trainingBusy, queuedFiles,
  addFiles, fileInput, removeQueued, includeSavedFile, removeUpload, setUploadExam, analyze,
  busy, progress, latest, onPracticeTopic, onBuildTestFromFiles, error, notice, dragging
}) {
  return (
    <section className="upload-page">
      <div className="upload-page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> PRIVATE STUDY WORKSPACE</div>
          <h1>Upload course materials</h1>
          <p>Add notes, quizzes, or past exams. The app extracts the text and presents topic predictions here.</p>
        </div>
        <div className="local-badge"><ShieldCheck size={15} /> Local-only storage</div>
      </div>

      <div className={`upload-layout ${dragging ? "upload-layout-dragging" : ""}`}>
        <div className="upload-primary">
          <div className="upload-controls">
          <button className="upload-dropzone" onClick={() => fileInput.current?.click()}>
            <span className="upload-drop-icon"><FileUp size={25} /></span>
            <strong>Choose files or drag them here</strong>
            <span>PDF, DOCX, and TXT files · Stored on this device</span>
            <span className="button-dark upload-browse"><FolderOpen size={15} /> Browse files</span>
          </button>

          {queuedFiles.length > 0 && <div className="queued-files">
            <div className="section-heading"><div><h3>Ready to analyze</h3><p>{queuedFiles.length} file{queuedFiles.length === 1 ? "" : "s"} selected</p></div></div>
            {queuedFiles.map((item) => <div className="queued-file" key={item.id}>
              <FileText size={17} />
              <span><strong>{item.name}</strong><small>{formatBytes(item.bytes)}{item.saved ? " · saved locally" : ""}</small></span>
              <button className="icon-button" onClick={() => removeQueued(item.id)} aria-label={`Remove ${item.name}`}><X size={16} /></button>
            </div>)}
          </div>}

          <div className="analysis-options">
            <label className="dataset-choice"><span><strong>Training data for this prediction</strong><small>Models are trained locally and cached for reuse when practical.</small></span>
              <select value={selectedDatasetId} onChange={(event) => setSelectedDatasetId(event.target.value)} disabled={busy || trainingBusy}>
                {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>
                  {dataset.name} · {dataset.example_count} examples · {dataset.topic_count} topics
                </option>)}
              </select>
            </label>
            {showBuiltInWarning && <div className="app-message app-message-success dataset-guidance">
              <AlertCircle size={14} />
              <span>Built-in examples only cover 8 general computing topics. Choose your course dataset for accurate topics.</span>
            </div>}
            <div className="ensemble-note"><BrainCircuit size={15} /><span><strong>Combined prediction</strong><small>TF-IDF features are analyzed by SVM and Naive Bayes together.</small></span></div>
            <button className="button-dark analyze-button" disabled={busy || trainingBusy || !queuedFiles.length} onClick={analyze}>
              {busy ? <><span className="spinner" /> Analyzing materials...</> : <><BrainCircuit size={16} /> Analyze materials</>}
            </button>
          </div>
          <p className="storage-note"><ShieldCheck size={14} /> Files and predictions are saved locally on this computer.</p>
          </div>

          <aside className="saved-materials">
          <div className="section-heading"><div><h3>Saved materials</h3><p>Files stored locally for later use</p></div><span className="count-badge">{uploads.length}</span></div>
          {uploads.length ? <div className="saved-file-list">
            {uploads.map((upload) => <div className="saved-file" key={upload.id}>
              <span className="saved-file-icon"><FileText size={16} /></span>
              <span className="saved-file-copy">
                <strong title={upload.name}>{upload.name}</strong>
                <small>{formatBytes(upload.bytes)} · {formatDate(upload.uploaded_at)}</small>
                {upload.is_exam === null && upload.exam_auto && <small className="saved-file-exam-auto">Auto-detected</small>}
              </span>
              <label className="saved-file-exam-toggle">
                <input
                  type="checkbox"
                  checked={upload.is_exam ?? upload.exam_auto}
                  onChange={(event) => setUploadExam(upload, event.target.checked)}
                  aria-label={`Past exam: ${upload.name}`}
                />
                <span>Past exam</span>
              </label>
              <button className="icon-button saved-use" title={`Use ${upload.name} in analysis`} aria-label={`Use ${upload.name} in analysis`} onClick={() => includeSavedFile(upload)}><RotateCcw size={15} /></button>
              <button className="icon-button saved-delete" title={`Delete ${upload.name}`} aria-label={`Delete ${upload.name}`} onClick={() => removeUpload(upload)}><Trash2 size={15} /></button>
            </div>)}
          </div> : <div className="saved-empty"><FolderOpen size={22} /><span>Uploaded files will appear here.</span></div>}
          </aside>
        </div>

        <div className="upload-results">
          {(busy || progress.length > 0) && <ProgressPanel progress={progress} busy={busy} />}
          {error && <AppErrorMessage message={error} />}
          {notice && !error && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
          <AnalysisOutput
            analysis={latest}
            onPracticeTopic={onPracticeTopic}
            onBuildTestFromFiles={onBuildTestFromFiles}
          />
        </div>
      </div>
    </section>
  );
}

function ProgressPanel({ progress, busy }) {
  const phases = progress.length ? progress : [
    { phase: "extraction", label: "Reading course materials", state: "active" },
    { phase: "cleaning", label: "Cleaning and preparing text", state: "pending" },
    { phase: "features", label: "Extracting text features", state: "pending" },
    { phase: "analysis", label: "Ranking likely topics", state: "pending" }
  ];
  return <div className="progress-panel">
    <div className="section-heading"><div><h3>{busy ? "Analyzing materials" : "Analysis steps"}</h3><p>Text stays on this device.</p></div><span className="progress-live">{busy ? "IN PROGRESS" : "COMPLETE"}</span></div>
    <div className="progress-steps">{phases.map((item) => <div className={`progress-step progress-step-${item.state}`} key={item.phase}>
      <span>{item.state === "done" ? <Check size={12} /> : item.state === "active" && busy ? <span className="spinner-small" /> : null}</span>{item.label}
    </div>)}</div>
  </div>;
}

function AnalysisOutput({ analysis, onPracticeTopic, onBuildTestFromFiles }) {
  return <section className="analysis-output">
    <div className="section-heading"><div><h2>Topic predictions</h2><p>Most likely topics based on the analyzed material</p></div>
      {analysis && <span className="output-method">{analysis.method || "TF-IDF + SVM + Naive Bayes ensemble"}</span>}
    </div>
    {!analysis ? <div className="output-empty"><BrainCircuit size={24} /><strong>Your output will appear here</strong><span>Upload materials and run an analysis to see ranked topics.</span></div>
      : <div className="output-card">
        <div className="output-card-heading"><div><span className="output-source-icon"><FolderOpen size={17} /></span><span><strong>{analysis.label || "Uploaded materials"}</strong><small>Saved locally · {formatDate(analysis.created_at)}</small></span></div><span className="saved-indicator"><span /> SAVED</span></div>
        <div className="prediction-list">{analysis.predictions.map((prediction, index) => <div className="prediction-row" key={`${prediction.topic}-${index}`}>
          <span className="prediction-rank">{String(index + 1).padStart(2, "0")}</span>
          <span className="prediction-topic"><strong>{prediction.topic}</strong><span><i style={{ width: `${Math.max(0, Math.min(100, prediction.confidence * 100))}%` }} /></span></span>
          <strong className="prediction-confidence">{Math.round(prediction.confidence * 100)}%</strong>
          <button
            className="button-outline prediction-practice-button"
            type="button"
            aria-label={`Practice ${prediction.topic}`}
            onClick={() => onPracticeTopic(prediction.topic)}
          >Practice</button>
        </div>)}</div>
        <p className="output-disclaimer">Training data: {analysis.training_dataset_name || "Built-in examples"}. SVM and Naive Bayes scores are averaged equally over shared TF-IDF features.</p>
        <button
          className="button-outline analysis-build-test-button"
          type="button"
          onClick={onBuildTestFromFiles}
        >Build a test from these files</button>
      </div>}
  </section>;
}

function TrainingDataPage({
  uploads, datasets, selectedDatasetId, datasetName, setDatasetName, selectedUploads,
  setSelectedUploads, labels, setLabels, busy, fileInput, csvInput,
  onImportCsv, onCreateDocuments, onRemoveUpload, onDeleteDataset, error, notice
}) {
  const [evaluation, setEvaluation] = useState(null);
  const [evaluationBusy, setEvaluationBusy] = useState(false);
  const [evaluationError, setEvaluationError] = useState("");
  const toggleUpload = (id) => setSelectedUploads((current) => current.includes(id)
    ? current.filter((item) => item !== id)
    : [...current, id]);
  const evaluateSelectedDataset = async () => {
    setEvaluationBusy(true);
    setEvaluationError("");
    setEvaluation(null);
    try {
      setEvaluation(await api.evaluateTrainingDataset(selectedDatasetId));
    } catch (requestError) {
      setEvaluationError(`Evaluation failed: ${requestError.message}`);
    } finally {
      setEvaluationBusy(false);
    }
  };
  const calibrationNotice = evaluation?.calibration_saved
    ? `This evaluation updated the abstain thresholds used for predictions with this dataset: confidence ${(evaluation.decision_policy.confidence_threshold * 100).toFixed(1)}%, margin ${(evaluation.decision_policy.min_margin * 100).toFixed(1)}%.`
    : "";

  return <section className="training-page">
    <div className="training-page-heading">
      <div>
        <div className="eyebrow"><span className="eyebrow-dot" /> LOCAL MODEL TRAINING</div>
        <h1>Manage training data</h1>
        <p>Import labeled examples or assign topics to your documents. Select a saved dataset on the Upload tab when you want to use it for a prediction.</p>
      </div>
      <div className="local-badge"><ShieldCheck size={15} /> Local-only storage</div>
    </div>
    <div className="training-data-panel model-evaluation-panel">
      <div className="section-heading">
        <div><h2><BrainCircuit size={16} /> Model evaluation</h2>
          <p>Evaluate {datasets.find((dataset) => dataset.id === selectedDatasetId)?.name || "the selected dataset"} with stratified cross-validation.</p>
        </div>
        <button className="button-outline" onClick={evaluateSelectedDataset} disabled={evaluationBusy || busy}>
          {evaluationBusy ? <span className="spinner" /> : <Check size={14} />}
          {evaluationBusy ? "Evaluating…" : "Evaluate selected dataset"}
        </button>
      </div>
      <p className="evaluation-disclaimer">
        Metrics summarize predictions on held-out folds of the labeled dataset. They do not measure performance on future exams.
        {calibrationNotice && <span>{calibrationNotice}</span>}
      </p>
      {evaluationError && <div className="app-message app-message-error"><AlertCircle size={16} />{evaluationError}</div>}
      {evaluation && <div className="evaluation-report">
        <div className="evaluation-report-meta">
          <strong>{evaluation.training_dataset_name}</strong>
          <span>{evaluation.examples_evaluated} examples · {evaluation.folds} folds · {evaluation.examples_excluded} unreadable rows excluded</span>
        </div>
        <div className="evaluation-metrics">
          {[
            ["Accuracy", evaluation.metrics.accuracy],
            ["Macro precision", evaluation.metrics.macro_precision],
            ["Macro recall", evaluation.metrics.macro_recall],
            ["Macro F1", evaluation.metrics.macro_f1]
          ].map(([label, score]) => <div key={label}>
            <span>{label}</span><strong>{(score * 100).toFixed(1)}%</strong>
          </div>)}
        </div>
        <div className="evaluation-matrix-wrap">
          <strong>Confusion matrix <span>(rows: actual · columns: predicted)</span></strong>
          <table className="evaluation-matrix">
            <thead><tr><th>Actual / predicted</th>{evaluation.confusion_matrix.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead>
            <tbody>{evaluation.confusion_matrix.values.map((row, rowIndex) => <tr key={evaluation.confusion_matrix.labels[rowIndex]}>
              <th>{evaluation.confusion_matrix.labels[rowIndex]}</th>
              {row.map((count, columnIndex) => <td key={evaluation.confusion_matrix.labels[columnIndex]}>{count}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
        <p className="evaluation-calibration-note">{calibrationNotice}</p>
      </div>}
    </div>
    <div className="training-data-panel">
    <div className="section-heading">
      <div><h2><Database size={16} /> Create a dataset</h2><p>CSV rows or labeled documents become training examples for SVM and Naive Bayes.</p></div>
      <span className="count-badge">{datasets.length}</span>
    </div>
    <div className="training-data-grid">
      <div className="training-builder">
        <label className="training-name-field"><span>Dataset name</span>
          <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} maxLength={100} placeholder="Optional for CSV (uses the file name). Required for labeled documents." />
        </label>
        <div className="training-actions">
          <button className="button-outline" onClick={() => csvInput.current?.click()} disabled={busy}>
            {busy ? <span className="spinner" /> : <FileSpreadsheet size={15} />} Import labeled CSV
          </button>
          <button className="button-outline" onClick={() => fileInput.current?.click()} disabled={busy}>
            <FileUp size={15} /> Add documents
          </button>
        </div>
        <p className="training-help">CSV format: one column for the topic and one for the text (for example a header row <code>topic,text</code>). Commas, semicolons or tabs, Excel and Google Sheets files, and common column names such as subject or content are detected automatically. Uploaded documents are saved locally, but do not become an available dataset until you label them and choose <strong>Create from labeled documents</strong>.</p>
        {uploads.length ? <div className="training-upload-list">
          {uploads.map((upload) => {
            const selected = selectedUploads.includes(upload.id);
            return <div className={`training-upload-row ${selected ? "training-upload-selected" : ""}`} key={upload.id}>
              <label className="training-upload-select">
                <input type="checkbox" checked={selected} onChange={() => toggleUpload(upload.id)} />
                <span title={upload.name}>{upload.name}</span>
              </label>
              <div className="training-upload-actions">
                <input
                  className="training-topic-input"
                  value={labels[upload.id] || ""}
                  onChange={(event) => setLabels((current) => ({ ...current, [upload.id]: event.target.value }))}
                  aria-label={`Topic label for ${upload.name}`}
                  placeholder="Topic label"
                  disabled={!selected}
                />
                <button
                  className="icon-button training-upload-delete"
                  type="button"
                  onClick={() => onRemoveUpload(upload)}
                  disabled={busy}
                  title={`Delete ${upload.name} from this device`}
                  aria-label={`Delete uploaded document ${upload.name}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>;
          })}
          <button className="button-dark create-dataset-button" onClick={onCreateDocuments} disabled={busy || selectedUploads.length < 2}>
            <Database size={14} /> Create from labeled documents
          </button>
        </div> : <div className="training-empty">Add at least two documents and label each with its topic to train from documents.</div>}
      </div>
      <div className="training-saved">
        <h3>Available datasets</h3>
        <div className="dataset-list">
          {datasets.map((dataset) => <div className="dataset-list-row" key={dataset.id}>
            <span className="dataset-list-icon"><Database size={15} /></span>
            <span className="dataset-list-copy"><strong>{dataset.name}</strong><small>{dataset.example_count} examples · {dataset.topic_count} topics · {dataset.source_type}</small></span>
            {dataset.id !== "builtin" && <button className="icon-button saved-delete" onClick={() => onDeleteDataset(dataset)} title={`Delete ${dataset.name}`} aria-label={`Delete dataset ${dataset.name}`}><Trash2 size={15} /></button>}
          </div>)}
        </div>
      </div>
    </div>
    </div>
    {error && <AppErrorMessage message={error} />}
    {notice && !error && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
  </section>;
}

function SettingsPage({
  settings, setSettings, datasets, uploads, selectedDatasetId,
  setSelectedDatasetId, selectedUploadIds, setSelectedUploadIds, topics,
  questionForm, setQuestionForm, saveSettings, busy, appVersion,
  onCheckForUpdates, updateCheckBusy, error, notice
}) {
  const setQuestionField = (key, value) => setQuestionForm((current) => ({
    ...current,
    [key]: value
  }));
  const weightTotal = Object.values(questionForm.weights)
    .reduce((sum, value) => sum + Number(value || 0), 0);
  const weightLabels = {
    historical_frequency: "Selected-dataset topic frequency",
    course_importance: "Course-material importance",
    model_confidence: "ML topic confidence",
    recent_occurrence: "Recent occurrence"
  };
  const toggleSource = (id) => setSelectedUploadIds((current) => current.includes(id)
    ? current.filter((item) => item !== id)
    : [...current, id]);

  return <section className="simple-page settings-page">
    <div className="eyebrow">CLINTHINKER© WORKSPACE</div><h1>Settings</h1>
    <p>Choose interface preferences and configure how practice questions are generated. Settings are saved locally.</p>
    <div className="simple-settings-card">
      <label><span><strong>Appearance</strong><small>Choose your workspace color theme.</small></span>
        <select value={settings.appearance} onChange={(event) => setSettings((current) => ({ ...current, appearance: event.target.value }))}>
          <option value="orange">Black &amp; Orange</option>
          <option value="pink">Clinthinker White &amp; Pink</option>
          <option value="regal">Alamo&apos;s Regal Nature (Gold &amp; Purple)</option>
          <option value="cmu">CMU Version</option>
        </select>
      </label>
      <div className="app-version-row">
        <span><strong>Version {appVersion || "..."}</strong></span>
        <button className="button-outline" onClick={onCheckForUpdates} disabled={updateCheckBusy}>
          {updateCheckBusy ? "Checking..." : "Check for updates"}
        </button>
      </div>
    </div>
    <div className="settings-question-generation">
      <div className="section-heading">
        <div><h2><Sparkles size={17} /> Question generation</h2>
          <p>Choose the training dataset, source files, and question format used on the Generate Practice Questions overview.</p>
        </div>
      </div>
      <div className="question-controls-grid">
        <label className="question-control"><span>Training dataset for topic guidance</span>
          <select value={selectedDatasetId} onChange={(event) => setSelectedDatasetId(event.target.value)}>
            {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>
              {dataset.name} · {dataset.topic_count} topics
            </option>)}
          </select>
        </label>
        <label className="question-control"><span>Question type</span>
          <select value={questionForm.question_type} onChange={(event) => setQuestionField("question_type", event.target.value)}>
            {["Multiple Choice", "True or False", "Identification"].map((type) => <option key={type}>{type}</option>)}
          </select>
        </label>
        <label className="question-control"><span>Number of questions</span>
          <input type="number" min="1" max="50" value={questionForm.number_of_questions}
            onChange={(event) => setQuestionField("number_of_questions", event.target.value)} />
        </label>
        <label className="question-control"><span>Questions per topic</span>
          <input type="number" min="1" max="50" value={questionForm.questions_per_topic}
            onChange={(event) => setQuestionField("questions_per_topic", event.target.value)} />
        </label>
      </div>
      <div className="question-source-picker">
        <div className="question-subheading">
          <strong>Course materials used as question sources</strong>
          <span>All saved files are used by default, including files added later. Uncheck any file to exclude it. Training examples guide classification; custom training rows can also be candidates in standard generation, but never in lesson mode.</span>
          {uploads.length > 0 && <div className="question-source-actions">
            <button className="button-outline" type="button" onClick={() => setSelectedUploadIds(uploads.map((upload) => upload.id))}>Select all</button>
            <button className="button-outline" type="button" onClick={() => setSelectedUploadIds([])}>Clear selection</button>
            <span>{selectedUploadIds.length} of {uploads.length} selected</span>
          </div>}
        </div>
        {uploads.length ? <div className="question-upload-list">
          {uploads.map((upload) => <label key={upload.id} className="question-upload-choice">
            <input type="checkbox" checked={selectedUploadIds.includes(upload.id)} onChange={() => toggleSource(upload.id)} />
            <FileText size={15} /><span>{upload.name}</span>
          </label>)}
        </div> : <div className="training-empty">Upload course materials on the Upload page first.</div>}
      </div>

      <details className="question-weights">
        <summary>Configure topic priority score <span>{weightTotal}% total</span></summary>
        <p>Weights must total 100%. Historical examples have no timestamps, so recency uses a neutral score.</p>
        <div className="question-weight-grid">{Object.entries(weightLabels).map(([key, label]) =>
          <label className="question-control" key={key}><span>{label} (%)</span>
            <input type="number" min="0" max="100" value={questionForm.weights[key]}
              onChange={(event) => setQuestionForm((current) => ({
                ...current, weights: { ...current.weights, [key]: event.target.value }
              }))} />
          </label>
        )}</div>
        <label className="question-control question-threshold"><span>Duplicate similarity threshold (%)</span>
          <input type="number" min="50" max="100" value={questionForm.similarity_threshold}
            onChange={(event) => setQuestionField("similarity_threshold", event.target.value)} />
        </label>
        <label className="question-repeat-toggle">
          <input type="checkbox" checked={Boolean(questionForm.allow_repeats)}
            onChange={(event) => setQuestionField("allow_repeats", event.target.checked)} />
          <span><strong>Allow repeats from previous generations</strong>
            <small>Questions can recur across runs, but fresh source sentences are always used first.</small>
          </span>
        </label>
      </details>
      {weightTotal !== 100 && <p className="question-validation-note">Priority weights currently total {weightTotal}%. Adjust them to 100% before saving.</p>}
    </div>
    <button className="button-dark settings-save" onClick={saveSettings} disabled={busy || weightTotal !== 100}>
      {busy ? "Saving..." : "Save settings"}
    </button>
    {error && <AppErrorMessage message={error} />}
    {notice && !error && <div className="app-message app-message-success"><Check size={16} />{notice}</div>}
    <div className="offline-note"><ShieldCheck size={17} /><span><strong>Offline by design</strong><small>Clinthinker© runs the prediction service and stores data on this computer. No cloud account or external data service is used.</small></span></div>
  </section>;
}

function HelpPage() {
  return <section className="simple-page">
    <div className="eyebrow">GETTING STARTED</div><h1>Help</h1>
    <p>Use the local assistant to turn study materials into a short list of likely exam topics.</p>
    <div className="help-steps">
      <div><span>01</span><strong>Add materials</strong><p>Choose PDF, DOCX, or TXT notes, quizzes, and past exams. Uploaded copies stay in local storage.</p></div>
      <div><span>02</span><strong>Choose training data</strong><p>Select built-in examples or import a labeled CSV with topic/text columns. You can also upload documents and assign a topic to each.</p></div>
      <div><span>03</span><strong>Analyze locally</strong><p>The SVM and Naive Bayes classifier is fitted on demand from the selected dataset and cached in memory. Lesson generation can add confidently topic-labeled exam passages. It classifies topics; it does not learn how to write questions.</p></div>
    </div>
    <div className="offline-note"><ShieldCheck size={17} /><span><strong>Local data folder</strong><small>Uploads and training datasets are stored in <code>%LOCALAPPDATA%\Clinthinker©\storage\</code>. Existing Topic Prediction Assistant data is moved here on first launch.</small></span></div>
  </section>;
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
