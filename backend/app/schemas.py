from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .questions import DEFAULT_SIMILARITY_THRESHOLD


class PredictionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500000)
    training_dataset_id: str = Field(default="builtin", min_length=1, max_length=100)


class LabeledUpload(BaseModel):
    upload_id: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=100)


class UploadExamUpdate(BaseModel):
    is_exam: bool


class EvaluateDatasetRequest(BaseModel):
    training_dataset_id: str = Field(min_length=1, max_length=100)


class DocumentDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    examples: list[LabeledUpload] = Field(min_length=2, max_length=500)


class PriorityWeights(BaseModel):
    historical_frequency: float = Field(default=0.40, ge=0, le=1)
    course_importance: float = Field(default=0.30, ge=0, le=1)
    model_confidence: float = Field(default=0.20, ge=0, le=1)
    recent_occurrence: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def weights_must_total_one(self):
        if abs(sum(self.model_dump().values()) - 1.0) > 0.001:
            raise ValueError("Priority weights must add up to 100%.")
        return self


class QuestionGenerationSettings(BaseModel):
    training_dataset_id: str = Field(default="builtin", min_length=1, max_length=100)
    upload_ids: list[str] | None = None
    topic: str = Field(default="All Topics", min_length=1, max_length=100)
    question_type: Literal["Multiple Choice", "True or False", "Identification"] = "Multiple Choice"
    difficulty: Literal["Easy", "Moderate", "Difficult"] = "Moderate"
    number_of_questions: int = Field(default=10, ge=1, le=50)
    questions_per_topic: int = Field(default=3, ge=1, le=50)
    similarity_threshold: float = Field(default=DEFAULT_SIMILARITY_THRESHOLD, ge=0.5, le=1)
    allow_repeats: bool = False
    priority_weights: PriorityWeights = Field(default_factory=PriorityWeights)


class SettingsUpdate(BaseModel):
    language: str | None = Field(default=None, max_length=40)
    appearance: Literal["orange", "pink", "regal", "cmu"] | None = None
    question_generation: QuestionGenerationSettings | None = None


class GenerateQuestionsRequest(BaseModel):
    training_dataset_id: str = Field(min_length=1, max_length=100)
    upload_ids: list[str] = Field(min_length=1)
    lesson_upload_id: str | None = Field(default=None, min_length=1, max_length=100)
    lesson_upload_ids: list[str] = Field(default_factory=list)
    lesson_only: bool = False
    use_exam_style: bool = True
    topic: str = Field(default="All Topics", min_length=1, max_length=100)
    question_type: Literal["Multiple Choice", "True or False", "Identification"]
    difficulty: Literal["Easy", "Moderate", "Difficult"]
    number_of_questions: int = Field(default=10, ge=1, le=50)
    questions_per_topic: int = Field(default=3, ge=1, le=50)
    similarity_threshold: float = Field(
        default=DEFAULT_SIMILARITY_THRESHOLD, ge=0.5, le=1
    )
    allow_repeats: bool = False
    priority_weights: PriorityWeights = Field(default_factory=PriorityWeights)


class SaveQuestionsRequest(BaseModel):
    generation_id: str = Field(min_length=1, max_length=100)
    question_ids: list[str] = Field(min_length=1, max_length=50)


class ResetQuestionHistoryRequest(BaseModel):
    upload_ids: list[str] = Field(min_length=1)


class QuestionFeedbackRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=-1, le=1)
    generation_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def rating_must_be_positive_or_negative(self):
        if self.rating not in {-1, 1}:
            raise ValueError("Choose either positive or negative feedback.")
        return self


class RenameSavedSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
