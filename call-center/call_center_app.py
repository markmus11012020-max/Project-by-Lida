"""CallPilot: a product-style demo for call-center QA automation."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

CALL_CENTER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.config import get_settings  # noqa: E402
from app.scenarios.call_qa import AUTO_PASS_SCORE, QA_CRITERIA  # noqa: E402
from call_store import CallStore  # noqa: E402

DB_PATH = Path(
    os.getenv(
        "CALLPILOT_DB_PATH",
        str(CALL_CENTER_DIR / "data" / "call_center.db"),
    )
)
STATIC_DIR = CALL_CENTER_DIR / "static"
TEMPLATES_DIR = CALL_CENTER_DIR / "templates"

settings = get_settings().model_copy(update={"database_path": DB_PATH})
store = CallStore(settings, DB_PATH)

app = FastAPI(
    title="CallPilot",
    version="1.0.0",
    description="AI-контроль качества и постобработка звонков для колл-центров.",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

INTENT_LABELS = {
    "order_status": "Статус заказа",
    "delivery": "Доставка",
    "refund": "Возврат",
    "billing": "Оплата",
    "technical": "Техническая проблема",
    "complaint": "Жалоба",
    "consultation": "Консультация",
    "other": "Другое",
}
STATUS_LABELS = {
    "new": "Не обработан",
    "pending": "На проверке",
    "confirmed": "Подтверждён",
    "rejected": "Отклонён",
    "auto_pass": "Авто-проверка",
    "manual_review": "Ручная проверка",
    "processed": "Обработан",
    "escalated": "Эскалирован",
    "invalid": "Ошибка JSON",
    "error": "Ошибка LLM",
}
FINDING_LABELS = {
    "pass": "Выполнено",
    "fail": "Нарушение",
    "na": "Не применимо",
}
SEVERITY_LABELS = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "critical": "Критичный",
}
SENTIMENT_LABELS = {
    "positive": "Позитивный",
    "neutral": "Нейтральный",
    "negative": "Негативный",
}


def _label(mapping: dict[str, str], value: Any) -> str:
    return mapping.get(str(value or ""), str(value or "—"))


def _badge_class(value: Any) -> str:
    value = str(value or "")
    if value in {"confirmed", "auto_pass", "processed", "pass", "positive"}:
        return "badge badge-green"
    if value in {"manual_review", "pending", "escalated", "medium", "na", "neutral"}:
        return "badge badge-amber"
    if value in {"rejected", "invalid", "error", "fail", "critical", "high", "negative"}:
        return "badge badge-red"
    return "badge badge-gray"


def _display_status(call: dict[str, Any]) -> str:
    if call.get("review_status") in {"confirmed", "rejected"}:
        return call["review_status"]
    result = call.get("result") or {}
    if result:
        return result.get("auto_qa_status", "manual_review")
    return "new"


def _duration(ms: Any) -> str:
    try:
        total = int(ms or 0)
    except (TypeError, ValueError):
        total = 0
    minutes, seconds = divmod(total // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def _datetime(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value or "—")


templates.env.filters["label"] = lambda value, mapping: _label(mapping, value)
templates.env.filters["badge"] = _badge_class
templates.env.filters["display_status"] = _display_status
templates.env.filters["duration"] = _duration
templates.env.filters["datetime"] = _datetime
templates.env.globals.update(
    app_name="CallPilot",
    intent_labels=INTENT_LABELS,
    status_labels=STATUS_LABELS,
    finding_labels=FINDING_LABELS,
    severity_labels=SEVERITY_LABELS,
    sentiment_labels=SENTIMENT_LABELS,
    qa_criteria=QA_CRITERIA,
    qa_criteria_count=len(QA_CRITERIA),
    auto_pass_score=AUTO_PASS_SCORE,
    llm_configured=settings.llm_configured,
    model_name=settings.aitunnel_model,
)


class ConfirmPayload(BaseModel):
    final_result: dict[str, Any]
    reviewer: str = "Менеджер"
    reason: str = ""


class RejectPayload(BaseModel):
    reviewer: str = "Менеджер"
    reason: str = ""


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    metrics = store.metrics()
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"metrics": metrics},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status: str = "all",
    qa: str = "all",
    role: str = "manager",
):
    calls = store.list_calls()
    metrics = store.metrics()
    if status != "all":
        calls = [call for call in calls if _display_status(call) == status]
    if qa != "all":
        calls = [
            call
            for call in calls
            if (call.get("result") or {}).get("auto_qa_status") == qa
        ]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "calls": calls,
            "metrics": metrics,
            "status_filter": status,
            "qa_filter": qa,
            "role": role,
        },
    )


@app.get("/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: str, role: str = "manager"):
    call = store.get_call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    draft = call.get("result") or {}
    read_only = call["review_status"] in {"confirmed", "rejected"}
    return templates.TemplateResponse(
        request=request,
        name="call_detail.html",
        context={
            "call": call,
            "draft": draft,
            "draft_json": json.dumps(draft, ensure_ascii=False),
            "segments_json": json.dumps(
                call.get("segments", []), ensure_ascii=False
            ),
            "read_only": read_only,
            "role": role,
            "confirmed": call["review_status"] == "confirmed",
            "rejected": call["review_status"] == "rejected",
        },
    )


@app.post("/calls/{call_id}/process")
def process_call(call_id: str):
    try:
        store.process_call(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    return RedirectResponse(
        url=f"/calls/{call_id}?processed=1", status_code=303
    )


@app.post("/calls/{call_id}/confirm")
def confirm_call(call_id: str, payload: ConfirmPayload):
    try:
        call = store.confirm_call(
            call_id,
            payload.final_result,
            payload.reviewer,
            payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Проверьте карточку: {exc}"
        ) from exc
    return JSONResponse(
        {
            "ok": True,
            "redirect": f"/calls/{call_id}?confirmed=1",
            "call": call,
        }
    )


@app.post("/calls/{call_id}/reject")
def reject_call(call_id: str, payload: RejectPayload):
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="Укажите причину отклонения")
    try:
        store.reject_call(call_id, payload.reviewer, payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    return JSONResponse({"ok": True, "redirect": f"/calls/{call_id}?rejected=1"})


@app.post("/demo/reset")
def reset_demo():
    store.reset_demo()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/qa", response_class=HTMLResponse)
def qa_dashboard(request: Request):
    metrics = store.metrics()
    return templates.TemplateResponse(
        request=request,
        name="qa.html",
        context={"metrics": metrics, "role": "manager"},
    )


@app.get("/offer", response_class=HTMLResponse)
def offer(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="offer.html",
        context={"metrics": store.metrics()},
    )


@app.get("/health")
def health():
    metrics = store.metrics()
    return {
        "status": "ok",
        "app": "CallPilot",
        "llm_configured": settings.llm_configured,
        "model": settings.aitunnel_model,
        "calls": metrics["total"],
        "processed": metrics["processed"],
    }
