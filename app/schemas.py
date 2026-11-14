"""Pydantic models for requests, LLM results and API responses."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioKey(str, Enum):
    SUPPORT = "support"
    SALES = "sales"
    DOCUMENTS = "documents"


class ProcessStatus(str, Enum):
    PROCESSED = "processed"
    ESCALATED = "escalated"
    INVALID = "invalid"
    ERROR = "error"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SupportCategory(str, Enum):
    BILLING = "billing"
    DELIVERY = "delivery"
    TECHNICAL = "technical"
    RETURN = "return"
    COMPLAINT = "complaint"
    OTHER = "other"


class LeadCategory(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    SPAM = "spam"
    UNKNOWN = "unknown"


class DocumentCategory(str, Enum):
    TZ = "tz"
    BRIEF = "brief"
    CONTRACT = "contract"
    OTHER = "other"


class ProcessRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scenario: ScenarioKey
    text: str = Field(min_length=3, max_length=20000)
    source: str = Field(default="api", max_length=50)
    metadata: dict[str, str] = Field(default_factory=dict)


class CommonResult(BaseModel):
    """Fields shared by all three process scenarios."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    summary: str = Field(min_length=1, max_length=2000)
    priority: Priority
    next_action: str = Field(min_length=1, max_length=1000)
    fields: dict[str, Any] = Field(default_factory=dict)
    confidence: Confidence
    escalate: bool = False
    escalate_reason: str | None = None
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("priority", "confidence", mode="before")
    @classmethod
    def normalize_enum(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("fields", mode="before")
    @classmethod
    def normalize_fields(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise ValueError("fields must be an object")

    @field_validator("missing_fields", mode="before")
    @classmethod
    def normalize_missing_fields(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("escalate_reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class SupportResult(CommonResult):
    category: SupportCategory

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SalesResult(CommonResult):
    category: LeadCategory
    score: int = Field(ge=0, le=100)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class DocumentResult(CommonResult):
    category: DocumentCategory
    draft_kp: str | None = None

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ProcessMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    temperature: float
    latency_ms: int
    created_at: str
    usage: dict[str, Any] = Field(default_factory=dict)


class ProcessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str
    scenario: str
    status: ProcessStatus
    result: dict[str, Any]
    meta: ProcessMeta
    error: str | None = None


class ScenarioInfo(BaseModel):
    key: str
    title: str
    description: str
    schema_hint: str
    example_input: str


class EvalCase(BaseModel):
    id: str
    scenario: ScenarioKey
    text: str
    expected_status: ProcessStatus | None = None
    note: str = ""
